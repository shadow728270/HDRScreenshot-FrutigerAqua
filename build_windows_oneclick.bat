@echo off
setlocal
cd /d "%~dp0"
echo Launching Prismwake v0.2.0 One-Click Windows Builder and Offline OCR Bundler...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows_oneclick.ps1"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Build failed with exit code %ERRORLEVEL%.
    echo [ERROR] Detailed log: %~dp0Prismwake-build.log
    echo.
    pause
    exit /b 1
)
echo.
echo [SUCCESS] Standalone dist\Prismwake.exe and dist\Prismwake.exe.sha256 are ready!
echo Detailed log: %~dp0Prismwake-build.log
pause
exit /b 0
