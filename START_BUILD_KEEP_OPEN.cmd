@echo off
setlocal
rem Launch an independent /K console when double-clicked so errors never disappear.
if /I not "%~1"=="--run" (
    start "Prismwake Windows Build" cmd.exe /K call "%~f0" --run
    exit /b 0
)
cd /d "%~dp0"
echo ============================================================================
echo Prismwake v0.2.0 - Windows Build (Persistent Diagnostic Console)
echo ============================================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows_oneclick.ps1"
set "BUILD_EXIT=%ERRORLEVEL%"
echo.
if not "%BUILD_EXIT%"=="0" (
    echo ============================================================================
    echo [ERROR] Build FAILED with exit code %BUILD_EXIT%.
    echo [ERROR] See "%~dp0Prismwake-build.log"
    echo [ERROR] Headless tests: Prismwake-headless-tests.stderr.log
    echo [ERROR] Qt GUI test: Prismwake-qt-smoke.stderr.log
    echo ============================================================================
) else (
    echo ============================================================================
    echo [SUCCESS] Build and verification passed.
    echo [SUCCESS] Output: "%~dp0dist\Prismwake.exe"
    echo ============================================================================
)
echo.
echo This window stays open. Type EXIT or close it when finished.
exit /b %BUILD_EXIT%
