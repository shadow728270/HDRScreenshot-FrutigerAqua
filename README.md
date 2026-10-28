# Prismwake — Catch the light. Keep the detail.

**Version:** `v0.2.0` (*The Productivity Update*)  
**Platform:** Windows 10 & Windows 11 (x64)  
**Canonical Executable:** `Prismwake.exe`  
**Repository:** [https://github.com/shadow728270/HDRScreenshot-FrutigerAqua](https://github.com/shadow728270/HDRScreenshot-FrutigerAqua)  
**Official Website:** [https://shadow728270.github.io/HDRScreenshot-FrutigerAqua/](https://shadow728270.github.io/HDRScreenshot-FrutigerAqua/)

---

## Overview

**Prismwake v0.2.0** expands Prismwake from an HDR-aware screenshot and annotation utility into a desktop productivity suite while preserving its signature **Frutiger Aqua** liquid-glass design and 64-bit half-float (`DXGI_FORMAT_R16G16B16A16_FLOAT`) scRGB HDR capture pipeline.

### Four Major Productivity Systems in v0.2.0

1. **Pinned Floating Screenshots (`pinning/`)**
   - Pin any region selection, annotated screenshot, or history item as an independent top-level desktop window (`WindowStaysOnTopHint`).
   - Freely draggable and 8-edge/corner resizable with aspect-ratio lock by default (`Shift` allows free resize).
   - Hover toolbar & context menu with live **Opacity slider (`15%–100%`)** + presets (`Alt+Wheel`), **Click-Through toggle** (Win32 `WS_EX_TRANSPARENT` on Windows, with an independent interactive unlock control) with a top-right interactive **Click-Through Unlock Pill** (`👻 Click-Thru ON (Click to Control)`), `Alt+Shift` hover unlock, and tray **Unlock All Click-Through Pins**.
   - Zoom presets (`25%`, `50%`, `75%`, `100%`, `150%`, `200%`, `300%`, `Fit`, `1:1` Reset Size, and `Ctrl+Wheel`), Lock Position, Toggle Always-on-Top (`📌 Top`), Duplicate Pin, Copy (`Ctrl+C`), Save As (`Ctrl+S`), Open Source in Editor, and `Esc` to close only the focused pin.
   - Multi-monitor & mixed-DPI aware with automatic offscreen/disconnected-monitor recovery and capture exclusion (`SetWindowDisplayAffinity` + pre-capture hide/restore).

2. **100% Offline Hybrid Neural + Region-Aware OCR (`ocr/`)**
   - Extracts text from any screen region or saved screenshot 100% offline with zero cloud calls, zero telemetry, and no Windows Store package identity requirement.
   - **Single Production Hybrid OCR Service (`HybridOcrOrchestrator` / `recognize_production_ocr`)**:
     - **Primary Backend (`RapidOcrBackend`)**: Local CPU ONNX Runtime (`CPUExecutionProvider`) neural text detector + recognizer (`rapidocr` + `onnxruntime`) using bundled, SHA-256-verified PP-OCR ONNX models (`rapidocr_models/`) with native support for English and Italian (`eng`, `ita`, `eng+ita`) and zero runtime model downloads.
     - **Automatic Fallback Backend (`TesseractOcrBackend`)**: Region-aware offline Tesseract (`tesseract.exe` + `eng.traineddata` & `ita.traineddata`) using connected-component white-core & Fisher linear discriminant text-island detection, single-pass stacked ROI recognition for multi-pill game HUDs and vivid colored buttons, bounded non-deadlocking subprocess pipe draining, and token/line-level partial-result salvage (`filter_and_salvage_partial_ocr_result`).
   - **100% Automatic Image Optimization**: Quick OCR remains compact and uncluttered while Advanced OCR exposes the active backend (`Backend: RapidOCR (ONNX CPU)` vs `Backend: Tesseract fallback`), clickable line boxes in native screenshot coordinates, language/mode selection, and opt-in diagnostic bundle export.

3. **Persistent Searchable Screenshot History (`history/`)**
   - Local-first SQLite + FTS5 database at `%LOCALAPPDATA%\Prismwake\History\` (`history.db`, `images/`, `thumbnails/`).
   - Privacy-first default (`saved_or_copied`): records saved, copied, pinned, or OCR-extracted captures and never records canceled captures.
   - Asynchronous background OCR indexing via `recognize_production_ocr`, configurable retention limits (`Max History Items`, `Max Storage Size MB`, `Retention Period Days`), **Storage & Privacy Settings** deep link, Re-pin focus, Clear History, Delete Selected, and corruption recovery.

4. **Unified Capture-Mode Flow & True Window Capture (`capture/`)**
   - **Focused System Tray Menu**: Single primary **Capture** action (`Ctrl+Shift+X`), **History**, **Settings...**, **Open Screenshots Folder**, **Check for Updates...**, **Pinned & Diagnostics** submenu, and **Exit**.
   - **In-Capture Mode HUD Bar**: Switch seamlessly between **Region (`1`)**, **Window (`2`)**, **Monitor (`3`)**, **OCR / Text (`4`)**, and **Delayed Capture (`5` — `3s` / `5s` / `10s`)** right inside the capture overlay.
   - **True Window Capture**: Enumerates visible top-level windows in Z-order (`EnumWindows`, `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`, `GetClientRect` + `ClientToScreen`), highlights the topmost window under the cursor live as you move the mouse, snaps the selection to that window's exact bounds when clicked (or switches to another window when clicked), and supports a live **Client Area (`W`)** toggle.

---

## Building `Prismwake.exe` on Windows 10/11

Run the one-click builder from PowerShell or Command Prompt (or double-click `START_BUILD_KEEP_OPEN.cmd` / `build_windows_oneclick.bat`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_oneclick.ps1
```

- **Python Environment Note**: If your global Python installation is Python 3.14, `build_windows_oneclick.ps1` automatically locates or provisions a side-by-side Python 3.12 user-scope installation into a project-local `.venv_build` virtual environment (leaving your global Python 3.14 untouched), installs pinned `rapidocr` and `onnxruntime` CPU wheels, stages and hash-verifies the ONNX models into `rapidocr_models/`, builds `dist\Prismwake.exe`, and runs the release-blocking 5-gate neural + fallback self-test (`--write-ocr-verify-file dist\ocr_verify.json --require-neural`).

---

## Single-Executable Architecture & Upgrading to v0.2.0

Starting in **Prismwake v0.2.0**, `Prismwake.exe` is the sole Windows executable built and published alongside `Prismwake.exe.sha256` (`HDRSnipFusion.exe` is retired and never built).
