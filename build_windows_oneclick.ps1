# Prismwake v0.2.0 — One-Click Windows Standalone Builder & Offline Neural/Tesseract OCR Bundler
# ===============================================================================================
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_oneclick.ps1
#   (or double-click build_windows_oneclick.bat)
#
# Release-Gated Build Steps:
#   1. Provisions an isolated project-local `.venv_build` using Python 3.12 / 3.13 / 3.11
#      (without modifying your global Python 3.14 installation). If only Python 3.14 is
#      present and compatible wheels are unavailable, automatically installs Python 3.12
#      in user scope via winget so `.venv_build` can be created reproducibly.
#   2. Installs all pinned dependencies from `requirements.txt` (including `rapidocr` and
#      `onnxruntime`). Fails immediately if neural dependencies cannot be installed.
#   3. Stages and cryptographically/structurally verifies the offline RapidOCR ONNX models
#      (`det`, `rec`, `cls` `.onnx` weights + configs + dictionaries + `model_manifest.json`)
#      via `tools\stage_rapidocr_models.py --output-dir rapidocr_models --strict`, plus stages
#      the offline Tesseract fallback runtime (`tesseract.exe` + DLLs + `eng`/`ita.traineddata`).
#   4. Generates `prismwake.ico` and runs isolated headless tests, native PyQt6 smoke tests,
#      and the side-by-side neural vs. Tesseract benchmark (`ocr.eval_side_by_side`).
#   5. Packages a single standalone `dist\Prismwake.exe` bundling `rapidocr`, `onnxruntime`
#      native DLLs, `rapidocr_models`, `tesseract_bundle`, and `THIRD_PARTY_LICENSES.md`.
#   6. Executes the release-blocking packaged-EXE self-test:
#        `dist\Prismwake.exe --write-ocr-verify-file dist\ocr_verify.json --require-neural`
#      and prints the 5-point Backend Self-Test Summary:
#        - RapidOCR installed
#        - models verified
#        - neural EXE inference PASS/FAIL
#        - Tesseract fallback PASS/FAIL
#        - offline cache-cleared test PASS/FAIL
#      A Tesseract-only build fails this gate and halts the build.
#   7. Writes `dist\Prismwake.exe.sha256`.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
Start-Transcript -Path (Join-Path $PSScriptRoot "Prismwake-build.log") -Force | Out-Null

function Assert-NativeSuccess([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$step failed with exit code $LASTEXITCODE. See Prismwake-build.log for details."
    }
}

Write-Host "=== [1/7] Provisioning Build Python Environment & Installing Required Neural + GUI Dependencies ===" -ForegroundColor Cyan

$venvDir = Join-Path $PSScriptRoot ".venv_build"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

function Find-CompatiblePythonForVenv {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($pyTag in @("-3.12", "-3.13", "-3.11")) {
            & py $pyTag -c "import sys; assert (3, 11) <= sys.version_info[:2] <= (3, 13)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                $exePath = (& py $pyTag -c "import sys; print(sys.executable)" 2>$null | Out-String).Trim()
                if ($exePath -and (Test-Path -LiteralPath $exePath)) {
                    return $exePath
                }
            }
        }
    }
    $candPaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        "C:\Python312\python.exe",
        "C:\Python313\python.exe",
        "C:\Python311\python.exe",
        (Join-Path $env:ProgramFiles "Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python313\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe")
    )
    foreach ($cp in $candPaths) {
        if ($cp -and (Test-Path -LiteralPath $cp)) {
            return $cp
        }
    }
    return $null
}

if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -c "import sys; sys.exit(0)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $venvDir -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $compatPy = Find-CompatiblePythonForVenv
    if (-not $compatPy) {
        $activePy = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($activePy) {
            & $activePy -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                $compatPy = $activePy
            }
        }
    }

    if (-not $compatPy -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "Global Python is not 3.11-3.13; installing isolated user-scope Python 3.12 via winget for .venv_build (global Python 3.14 is preserved)..." -ForegroundColor Yellow
        winget install --id Python.Python.3.12 -e --silent --scope user --accept-package-agreements --accept-source-agreements
        $LASTEXITCODE = 0
        $compatPy = Find-CompatiblePythonForVenv
    }

    if ($compatPy) {
        Write-Host "Creating isolated project-local build environment (.venv_build) using $compatPy..." -ForegroundColor Cyan
        & $compatPy -m venv $venvDir
        Assert-NativeSuccess "Creating .venv_build virtual environment"
    }
}

if (Test-Path -LiteralPath $venvPython) {
    $buildPython = $venvPython
    Write-Host "Using isolated build interpreter: $buildPython" -ForegroundColor Green
} else {
    $buildPython = (Get-Command python -ErrorAction Stop).Source
    Write-Host "Using active interpreter: $buildPython" -ForegroundColor Yellow
}

& $buildPython -m pip install --upgrade pip wheel
Assert-NativeSuccess "pip upgrade"

& $buildPython -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install required dependencies from requirements.txt (including rapidocr and onnxruntime) using $buildPython. Please install Python 3.12 side-by-side ('winget install Python.Python.3.12') and re-run build_windows_oneclick.bat so .venv_build can install prebuilt ONNX Runtime + RapidOCR wheels."
}

# Verify rapidocr and onnxruntime are importable in $buildPython (release-blocking)
& $buildPython -c "import onnxruntime, rapidocr; print('Verified neural packages:', 'onnxruntime=' + getattr(onnxruntime, '__version__', 'ok'), 'rapidocr=' + getattr(rapidocr, '__version__', 'ok'))"
Assert-NativeSuccess "RapidOCR + ONNX Runtime package verification"

Write-Host "=== [2/7] Staging & Verifying Offline RapidOCR ONNX Models & Tesseract Fallback Runtime ===" -ForegroundColor Cyan
$bundleDir = Join-Path $PSScriptRoot "tesseract_bundle"
$tessdataDir = Join-Path $bundleDir "tessdata"
$rapidModelsDir = Join-Path $PSScriptRoot "rapidocr_models"
New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null
New-Item -ItemType Directory -Force -Path $tessdataDir | Out-Null
New-Item -ItemType Directory -Force -Path $rapidModelsDir | Out-Null

# Stage and verify RapidOCR ONNX detector, recognizer, classifier, and manifest (release-blocking)
& $buildPython tools\stage_rapidocr_models.py --output-dir $rapidModelsDir --strict
Assert-NativeSuccess "RapidOCR offline ONNX model staging and verification"

if (-not (Test-Path -LiteralPath (Join-Path $rapidModelsDir "model_manifest.json"))) {
    throw "Missing rapidocr_models\model_manifest.json after model staging."
}

function Find-LocalTesseractDir {
    $candidates = @(
        (Join-Path $PSScriptRoot "tesseract_bundle"),
        "C:\Program Files\Tesseract-OCR",
        "C:\Program Files (x86)\Tesseract-OCR",
        (Join-Path $env:LOCALAPPDATA "Tesseract-OCR"),
        (Join-Path $env:LOCALAPPDATA "Programs\Tesseract-OCR"),
        "C:\ProgramData\chocolatey\lib\tesseract\tools"
    )
    foreach ($cand in $candidates) {
        if ($cand -and (Test-Path (Join-Path $cand "tesseract.exe"))) {
            return $cand
        }
    }
    $cmd = Get-Command tesseract.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        return (Split-Path -Parent $cmd.Source)
    }
    return $null
}

$tessSrcDir = Find-LocalTesseractDir
if (-not $tessSrcDir) {
    Write-Host "Local Tesseract installation not found; installing UB-Mannheim.TesseractOCR via winget/choco..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id UB-Mannheim.TesseractOCR -e --silent --accept-package-agreements --accept-source-agreements
        Assert-NativeSuccess "Tesseract installation via winget"
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install tesseract -y --no-progress
        Assert-NativeSuccess "Tesseract installation via Chocolatey"
    }
    $tessSrcDir = Find-LocalTesseractDir
}

if (-not $tessSrcDir) {
    throw "Could not locate or install tesseract.exe. Please install UB-Mannheim Tesseract-OCR into C:\Program Files\Tesseract-OCR or place tesseract.exe + *.dll into .\tesseract_bundle\ and re-run."
}

if ((Resolve-Path $tessSrcDir).Path -ne (Resolve-Path $bundleDir).Path) {
    Copy-Item (Join-Path $tessSrcDir "tesseract.exe") $bundleDir -Force
    Get-ChildItem -Path $tessSrcDir -Filter "*.dll" | ForEach-Object {
        Copy-Item $_.FullName $bundleDir -Force
    }
    $srcTessdata = Join-Path $tessSrcDir "tessdata"
    if (Test-Path $srcTessdata) {
        Get-ChildItem -Path $srcTessdata -Filter "*.traineddata" | ForEach-Object {
            Copy-Item $_.FullName $tessdataDir -Force
        }
    }
}

foreach ($lang in @("eng", "ita")) {
    $tdFile = Join-Path $tessdataDir "$lang.traineddata"
    if (-not (Test-Path $tdFile) -or ((Get-Item $tdFile).Length -lt 500000)) {
        Write-Host "Fetching official tessdata_fast/$lang.traineddata..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$lang.traineddata" -OutFile $tdFile -UseBasicParsing
    }
}

if (-not (Test-Path (Join-Path $bundleDir "tesseract.exe"))) {
    throw "Missing tesseract_bundle\tesseract.exe"
}
if (-not (Test-Path (Join-Path $tessdataDir "eng.traineddata"))) {
    throw "Missing tesseract_bundle\tessdata\eng.traineddata"
}

Write-Host "=== [3/7] Generating Prismwake Multi-Size Windows Icon ===" -ForegroundColor Cyan
& $buildPython make_prismwake_icon.py
Assert-NativeSuccess "Prismwake icon generation"

Write-Host "=== [4/7] Running Isolated Headless Tests, Native Qt Tests & Side-by-Side Neural Evaluation ===" -ForegroundColor Cyan
$env:PYTHONFAULTHANDLER = "1"
function Invoke-IsolatedPythonTest([string]$label, [string[]]$argList, [string]$slug) {
    $stdoutFile = Join-Path $PSScriptRoot ("Prismwake-" + $slug + ".stdout.log")
    $stderrFile = Join-Path $PSScriptRoot ("Prismwake-" + $slug + ".stderr.log")
    foreach ($log in @($stdoutFile, $stderrFile)) {
        if (Test-Path -LiteralPath $log) { Remove-Item -LiteralPath $log -Force }
    }
    Write-Host ("Running " + $label + "...") -ForegroundColor Cyan
    $proc = Start-Process -FilePath $buildPython `
        -ArgumentList $argList -Wait -PassThru -NoNewWindow `
        -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile
    if (Test-Path -LiteralPath $stdoutFile) {
        Get-Content -LiteralPath $stdoutFile -Tail 35 | ForEach-Object { Write-Host $_ }
    }
    if (Test-Path -LiteralPath $stderrFile) {
        Get-Content -LiteralPath $stderrFile -Tail 80 | ForEach-Object { Write-Host $_ }
    }
    if ($proc.ExitCode -ne 0) {
        $exitHex = "0x{0:X8}" -f ($proc.ExitCode -band 0xffffffff)
        throw "$label failed (exit $($proc.ExitCode); $exitHex). See Prismwake-$slug.stderr.log and Prismwake-build.log."
    }
}
Invoke-IsolatedPythonTest "Headless & production OCR dispatch/fallback tests" @("-u", "tests\run_headless_tests.py") "headless-tests"
Invoke-IsolatedPythonTest "Real PyQt6 OCR window startup test" @("-u", "tests\smoke_qt_gui.py") "qt-smoke"
Invoke-IsolatedPythonTest "Side-by-side RapidOCR neural vs. Tesseract evaluation" @("-u", "-m", "ocr.eval_side_by_side", "--require-neural", "--output-json", "BENCHMARK_OCR_V020.json", "--output-md", "BENCHMARK_OCR_V020.md") "side-by-side-eval"

Write-Host "=== [5/7] Building Standalone dist\Prismwake.exe with PyInstaller ===" -ForegroundColor Cyan
if (Test-Path "dist\Prismwake.exe") { Remove-Item "dist\Prismwake.exe" -Force }
if (Test-Path "dist\Prismwake.exe.sha256") { Remove-Item "dist\Prismwake.exe.sha256" -Force }
if (Test-Path "dist\HDRSnipFusion.exe") { Remove-Item "dist\HDRSnipFusion.exe" -Force }

$pyiArgs = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "Prismwake",
    "--icon", "prismwake.ico",
    "--version-file", "prismwake_version_info.txt",
    "--collect-submodules", "PyQt6",
    "--collect-all", "rapidocr",
    "--collect-all", "onnxruntime",
    "--hidden-import", "ocr",
    "--hidden-import", "ocr.engine",
    "--hidden-import", "ocr.backends",
    "--hidden-import", "onnxruntime",
    "--hidden-import", "onnxruntime.capi._pybind_state",
    "--hidden-import", "rapidocr",
    "--hidden-import", "cv2",
    "--hidden-import", "pyclipper",
    "--hidden-import", "shapely",
    "--hidden-import", "omegaconf",
    "--hidden-import", "yaml",
    "--hidden-import", "history",
    "--hidden-import", "history.storage",
    "--hidden-import", "pinning",
    "--hidden-import", "pinning.manager",
    "--hidden-import", "capture",
    "--hidden-import", "capture.smart_modes",
    "--hidden-import", "updater",
    "--hidden-import", "updater.single_exe",
    "--add-data", "prismwake.ico;.",
    "--add-data", "prismwake-mark.svg;.",
    "--add-data", "THIRD_PARTY_LICENSES.md;.",
    "--add-data", "tesseract_bundle;tesseract_bundle",
    "--add-data", "rapidocr_models;rapidocr_models",
    "Prismwake.py"
)

& $buildPython @pyiArgs
Assert-NativeSuccess "PyInstaller Windows executable build"

if (-not (Test-Path "dist\Prismwake.exe")) {
    throw "PyInstaller failed to produce dist\Prismwake.exe"
}
if (Test-Path "dist\HDRSnipFusion.exe") {
    throw "Legacy alias dist\HDRSnipFusion.exe must not be built in v0.2.0"
}

Write-Host "=== [6/7] Running Release-Blocking Packaged-EXE Neural & Fallback Self-Test ===" -ForegroundColor Cyan
$ocrVerifyJson = Join-Path $PSScriptRoot "dist\ocr_verify.json"
if (Test-Path $ocrVerifyJson) { Remove-Item $ocrVerifyJson -Force }
$proc = Start-Process -FilePath "dist\Prismwake.exe" -ArgumentList @("--write-ocr-verify-file", $ocrVerifyJson, "--require-neural") -Wait -PassThru -NoNewWindow
if (-not (Test-Path $ocrVerifyJson)) {
    throw "Packaged dist\Prismwake.exe failed to write $ocrVerifyJson (exit code $($proc.ExitCode))."
}
$ocrMeta = Get-Content $ocrVerifyJson -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "=== Offline OCR Backend Self-Test Summary ===" -ForegroundColor Cyan
Write-Host ("  RapidOCR installed        : " + $ocrMeta.summary_table.'RapidOCR installed')
Write-Host ("  models verified           : " + $ocrMeta.summary_table.'models verified')
Write-Host ("  neural EXE inference      : " + $ocrMeta.summary_table.'neural EXE inference')
Write-Host ("  Tesseract fallback        : " + $ocrMeta.summary_table.'Tesseract fallback')
Write-Host ("  offline cache-cleared test: " + $ocrMeta.summary_table.'offline cache-cleared test')
Write-Host ("  Details                   : " + $ocrMeta.message)
Write-Host ""

if ($proc.ExitCode -ne 0 -or -not $ocrMeta.ok -or -not $ocrMeta.neural_exe_inference_pass -or -not $ocrMeta.tesseract_fallback_pass -or -not $ocrMeta.offline_cache_cleared_pass) {
    throw "Release-blocking packaged-EXE OCR verification FAILED: $($ocrMeta.message)"
}

Write-Host "=== [7/7] Writing SHA-256 Checksum (dist\Prismwake.exe.sha256) ===" -ForegroundColor Cyan
$hash = (Get-FileHash "dist\Prismwake.exe" -Algorithm SHA256).Hash.ToLower()
"$hash  Prismwake.exe" | Set-Content -Path "dist\Prismwake.exe.sha256" -NoNewline -Encoding ascii
Write-Host "Build Complete! Output: dist\Prismwake.exe (SHA-256: $hash)" -ForegroundColor Green
Stop-Transcript | Out-Null
