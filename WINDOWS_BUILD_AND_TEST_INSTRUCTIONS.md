# Prismwake v0.2.0 — Windows Build, Packaging & Verification Guide

This guide documents the actual Windows build scripts, model staging pipeline, automated test suites, and manual verification checklist for **Prismwake v0.2.0**.

---

## 1. Verified Tests vs. Windows-Only Tests

To keep verification transparent, tests are divided into what has already been executed and verified in the automated Linux test environment versus what requires a native Windows 10/11 desktop environment.

| Test Suite / Verification Stage | Command / Entrypoint | Verified in Linux Offscreen Environment | Requires Native Windows 10/11 | What It Verifies |
| :--- | :--- | :--- | :--- | :--- |
| **Headless Unit & Regression Suite (77 tests)** | `python -u tests\run_headless_tests.py` | **Verified (77 / 77 PASS)** | Also runs in Step `[4/7]` of Windows build | Core OCR engine, RapidOCR/Tesseract fallback routing, SHA-256 ONNX manifest checks, SQLite + FTS5 History CRUD, Frutiger Aqua History themes/views/actions, 200-item gallery responsiveness, 4-layer annotation caching, dirty-rect bounds, 10-tool export fidelity, **asynchronous full-resolution preview loading**, **selection cancellation / stale-result rejection**, **zero synchronous disk/decode I/O in `HistoryCardDelegate.paint()`**, and **viewport-prioritized asynchronous thumbnail decoding with GUI-thread `QPixmap` creation**. |
| **Qt GUI Branch Subprocess Verification (`test_08`)** | Included in `tests\test_prismwake_v020.py` (`TestPart15HistoryRedesignAndAnnotationPerformance.test_08`) | **Verified (PASS via `tests/qt_cairo_harness.py`)** | Uses native `PyQt6` automatically on Windows | Executes the `if HAS_QT:` `HistoryWindow` and `HistoryCardDelegate` code paths directly: verifies zero synchronous thumbnail I/O in `paint()`, immediate thumbnail preview followed by off-thread full-resolution decode and GUI-thread `QPixmap` upgrade, and rapid selection cancellation. |
| **PyQt6 GUI Smoke Test** | `python -u tests\smoke_qt_gui.py` | **Verified (Headless controller path PASS)** | **Windows-Only for native `PyQt6` (`qwindows.dll`)** | Instantiates real `PyQt6` `OcrResultsDialog`, `SettingsDialog`, `PinnedScreenshotWindow`, `SnipOverlayWindow`, and `HistoryWindow` widgets; verifies live signals, view toggles, asynchronous full-resolution preview upgrades, selection cancellation, and 4-layer annotation cache initialization. |
| **RapidOCR ONNX Model Stager & Offline Verifier** | `python tools\stage_rapidocr_models.py --output-dir rapidocr_models --strict` | Tested with synthetic ONNX session mocks in `TestPart13` | **Windows-Only for real `.onnx` model staging** | Extracts `det`, `rec`, and `cls` `.onnx` models plus dictionary/config files from installed `rapidocr`, verifies sessions with `onnxruntime`, writes `rapidocr_models\model_manifest.json` with SHA-256 digests, and performs a network-blocked dry run. |
| **Side-by-Side RapidOCR vs. Tesseract Evaluation** | `python -u -m ocr.eval_side_by_side --require-neural --output-json BENCHMARK_OCR_V020.json --output-md BENCHMARK_OCR_V020.md` | Tested with mock/Tesseract backends | **Windows-Only with `--require-neural`** | Runs side-by-side accuracy and latency evaluation across English, Italian, and stylized UI fixtures requiring live `rapidocr` + `onnxruntime` CPU inference. |
| **Standalone PyInstaller Single-EXE Build & Self-Test** | `START_BUILD_KEEP_OPEN.cmd` / `build_windows_oneclick.ps1` | Not applicable on Linux | **Windows-Only (Steps `[5/7]`–`[7/7]`)** | Packages `dist\Prismwake.exe`, runs `dist\Prismwake.exe --write-ocr-verify-file dist\ocr_verify.json --require-neural`, and writes `dist\Prismwake.exe.sha256`. |

---

## 2. One-Click Windows Build & Packaging (`START_BUILD_KEEP_OPEN.cmd`)

The project uses **`START_BUILD_KEEP_OPEN.cmd`** (or **`build_windows_oneclick.bat`**) which invokes **`build_windows_oneclick.ps1`**.
* Do **not** look for `build_windows_release.bat` or a pre-bundled `Prismwake.spec`; `build_windows_oneclick.ps1` invokes `PyInstaller` directly via CLI flags and generates `Prismwake.spec` dynamically during the build.

### Option A — Persistent Diagnostic Console (Recommended)
Double-click **`START_BUILD_KEEP_OPEN.cmd`** in Windows Explorer, or run from Command Prompt / PowerShell:
```cmd
START_BUILD_KEEP_OPEN.cmd
```
`START_BUILD_KEEP_OPEN.cmd` opens a persistent `cmd.exe /K` window, runs `powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows_oneclick.ps1"`, prints the build status and log file paths, and keeps the console window open after completion.

### Option B — Direct PowerShell Invocation
From a PowerShell prompt in the project root directory:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_oneclick.ps1
```

---

## 3. What `build_windows_oneclick.ps1` Executes (Steps `[1/7]` to `[7/7]`)

1. **`[1/7]` Provisioning Isolated `.venv_build` & Installing Dependencies**:
   * Locates a compatible Python `3.12`, `3.13`, or `3.11` interpreter (installing user-scope `Python.Python.3.12` via `winget` if only Python 3.14 is present, without modifying your global Python installation).
   * Creates `.venv_build`, upgrades `pip` and `wheel`, installs `-r requirements.txt` and `pyinstaller`, and verifies `import onnxruntime, rapidocr`.
2. **`[2/7]` Staging Offline RapidOCR ONNX Models & Tesseract Fallback Runtime**:
   * Runs:
     ```powershell
     .\.venv_build\Scripts\python.exe tools\stage_rapidocr_models.py --output-dir rapidocr_models --strict
     ```
   * Populates `.\rapidocr_models\` with the detector, recognizer, and classifier `.onnx` models, character dictionaries, YAML configs, and `rapidocr_models\model_manifest.json` (containing per-file byte sizes and SHA-256 digests), then verifies offline inference with outbound network sockets blocked.
   * Stages `tesseract.exe`, native `*.dll` dependencies, `eng.traineddata`, and `ita.traineddata` into `.\tesseract_bundle\` and `.\tesseract_bundle\tessdata\`.
3. **`[3/7]` Generating Multi-Size Windows Icon**:
   * Runs `.\.venv_build\Scripts\python.exe make_prismwake_icon.py` to write `prismwake.ico` (16, 24, 32, 48, 64, 128, 256 px frames), `prismwake-mark.svg`, and `prismwake_version_info.txt`.
4. **`[4/7]` Running Automated Headless, Native Qt Smoke & Side-by-Side OCR Tests**:
   * `.\.venv_build\Scripts\python.exe -u tests\run_headless_tests.py`
   * `.\.venv_build\Scripts\python.exe -u tests\smoke_qt_gui.py`
   * `.\.venv_build\Scripts\python.exe -u -m ocr.eval_side_by_side --require-neural --output-json BENCHMARK_OCR_V020.json --output-md BENCHMARK_OCR_V020.md`
5. **`[5/7]` Building Standalone `dist\Prismwake.exe` with PyInstaller**:
   * Invokes `.\.venv_build\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name Prismwake ... Prismwake.py` bundling `rapidocr_models;rapidocr_models`, `tesseract_bundle;tesseract_bundle`, `prismwake.ico;.`, `prismwake-mark.svg;.`, and `THIRD_PARTY_LICENSES.md;.`.
   * Verifies `dist\Prismwake.exe` exists and legacy `dist\HDRSnipFusion.exe` is not created.
6. **`[6/7]` Release-Blocking Packaged-EXE Neural & Fallback Self-Test**:
   * Runs:
     ```powershell
     dist\Prismwake.exe --write-ocr-verify-file dist\ocr_verify.json --require-neural
     ```
   * Verifies all 5 release gates in `dist\ocr_verify.json`: `RapidOCR installed`, `models verified`, `neural EXE inference`, `Tesseract fallback`, and `offline cache-cleared test`.
7. **`[7/7]` Writing SHA-256 Checksum**:
   * Writes `<sha256>  Prismwake.exe` to `dist\Prismwake.exe.sha256`.

---

## 4. Documented Build Outputs & Log Artifacts

After a successful run of `START_BUILD_KEEP_OPEN.cmd` / `build_windows_oneclick.ps1`, the following files are produced:

| Output Path | Description |
| :--- | :--- |
| `dist\Prismwake.exe` | Standalone single-file Windows executable bundling PyQt6, RapidOCR, ONNX Runtime, `rapidocr_models\`, and `tesseract_bundle\`. |
| `dist\Prismwake.exe.sha256` | ASCII SHA-256 checksum file (`<hash>  Prismwake.exe`). |
| `dist\ocr_verify.json` | Packaged-EXE self-test report verifying neural inference, Tesseract fallback, and cache-cleared offline operation. |
| `rapidocr_models\model_manifest.json` | Cryptographic SHA-256 manifest and model metadata for staged `.onnx` weights and dictionaries in `rapidocr_models\`. |
| `tesseract_bundle\tesseract.exe` & `tesseract_bundle\tessdata\*.traineddata` | Bundled offline Tesseract fallback binary, DLLs, and `eng`/`ita` traineddata files. |
| `BENCHMARK_OCR_V020.json` & `BENCHMARK_OCR_V020.md` | Side-by-side RapidOCR neural vs. Tesseract benchmark metrics generated during Step `[4/7]`. |
| `Prismwake-build.log` | Full PowerShell build transcript. |
| `Prismwake-headless-tests.stdout.log` / `.stderr.log` | Output logs from `tests\run_headless_tests.py`. |
| `Prismwake-qt-smoke.stdout.log` / `.stderr.log` | Output logs from `tests\smoke_qt_gui.py`. |
| `Prismwake-side-by-side-eval.stdout.log` / `.stderr.log` | Output logs from `ocr.eval_side_by_side`. |

---

## 5. Manual Interactive Windows QA Checklist

After `dist\Prismwake.exe` builds and passes automated gates, perform these quick interactive checks on Windows:

1. **Screenshot History Gallery & Asynchronous Loading**:
   * Open **Screenshot History** from the system tray menu.
   * Confirm the Frutiger Aqua glass header, left category filter pills (`All Captures`, `★ Favorites`, `Recent (7 Days)`, `Recognized Text`), storage meter bar, custom rounded glass cards (`HistoryCardDelegate`), and right inspector panel render cleanly.
   * Scroll rapidly through a large history gallery: confirm scrolling stays smooth without disk I/O hitches and visible thumbnails populate progressively.
   * Click through several high-resolution captures in the gallery: confirm the thumbnail appears immediately in the right preview well and smoothly sharpens to the full-resolution image without freezing the UI or distorting aspect ratio.
   * Switch themes (`Bondi Blue`, `Emerald Lagoon`, `Aurora Mint`, `Sapphire Zenith`, `Crystal Frost`) and Animation Intensity (`Off`, `Subtle`, `Medium`, `High`) in Settings and confirm History updates live.
2. **Pre-Capture Annotation Drawing Responsiveness**:
   * Trigger a capture (`Ctrl+Shift+S`), drag a selection region, and draw rapid freehand strokes with **Pen**, **Arrow**, **Rectangle**, **Ellipse**, **Blur**, and **Pixelate** — both on a fresh canvas and after adding 50+ strokes.
   * Confirm drawing tracks the cursor smoothly with bounded dirty-rectangle updates and exported/copied/saved/pinned images match the live preview.
