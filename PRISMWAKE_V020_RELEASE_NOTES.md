# Prismwake v0.2.0 Release Notes — *The Productivity Update*

**Release Version:** `v0.2.0`  
**Tagline:** *Catch the light. Keep the detail.*  
**Published Assets:** `Prismwake.exe`, `Prismwake.exe.sha256`

## Highlights

- **Unified Capture-Mode HUD & Streamlined Tray Menu (`capture/`, `Prismwake.py`)**:
  - **Focused System Tray Menu**: Exposes one primary **Capture (`Ctrl+Shift+X`)** entry, **History**, **Settings...**, **Open Screenshots Folder**, **Check for Updates...**, a compact **Pinned & Diagnostics** submenu (`Unlock All Click-Through Pins`, `Close All Pinned Screenshots`, `Open Diagnostic Log...`), and **Exit Prismwake**.
  - **In-Capture Mode HUD Bar**: Pressing the capture shortcut or clicking **Capture** opens the Frutiger Aqua capture overlay with a top-center Mode HUD Bar for live switching between **Region (`1`)**, **Window (`2`)**, **Monitor (`3`)**, **OCR / Text (`4`)**, and **Delayed Capture (`5` — `3s` / `5s` / `10s`)** without returning to the tray menu.
- **True Deterministic Window Capture (`capture/smart_modes.py`, `Prismwake.py`)**:
  -Snapshots visible, non-minimized, non-cloaked top-level desktop windows in Z-order (`EnumWindows`, `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`, and `GetClientRect` + `ClientToScreen`), excluding Prismwake's own overlays/windows and shell clutter.
  - Hovering any window highlights the topmost window under the cursor with a live Frutiger Aqua outline, dimmed surround, and window title/dimension badge.
  - Clicking a window snaps the capture selection to that window's exact bounds; clicking a different window immediately moves the capture area to the newly clicked window rather than acting like a freehand region drag. Includes a live **Client Area (`W`)** toggle.
- **Pinned Floating Screenshots with Live Opacity & Click-Through (`pinning/manager.py`)**:
  - Keep captured regions or history screenshots floating above other windows with an auto-hiding hover toolbar and right-click context menu.
  - Includes a live **Opacity slider (`15%–100%`)** + presets + `Alt+Wheel`, **Click-Through toggle** (`WindowTransparentForInput` + Win32 `WS_EX_TRANSPARENT | WS_EX_LAYERED`), a top-right interactive **Click-Through Unlock Pill** (`👻 Click-Thru ON (Click to Control)`) + `Alt+Shift` hover unlock + tray **Unlock All Click-Through Pins**, **Always-on-Top (`📌 Top`)** toggle, **`1:1` Reset Size**, aspect-ratio-preserving 8-edge resize, and re-pin focus from History.
- **Reliable Settings & Storage Privacy Controls (`Prismwake.py`, `history/storage.py`)**:
  - Both the tray **Settings...** item and Screenshot History's **Storage & Privacy Settings** button reliably open `SettingsDialog` (bringing an existing instance to the front without duplicates and scrolling directly to the **Screenshot History & Storage Privacy** section when opened from History).
- **100% Offline Hybrid Neural + Region-Aware OCR (`ocr/`)**:
  - **Single Production Hybrid Service (`HybridOcrOrchestrator` / `recognize_production_ocr`)**: Wired across Quick OCR, Advanced OCR, Retry, Text Capture, editor OCR, asynchronous screenshot-history indexing, history gallery OCR, and packaged-EXE self-tests.
  - **Primary Offline Neural Backend (`RapidOcrBackend`)**: Local CPU ONNX Runtime (`CPUExecutionProvider`) text detection and recognition (`rapidocr` + `onnxruntime`) using bundled, SHA-256-verified PP-OCR ONNX models (`rapidocr_models/`) with zero runtime downloads.
  - **Automatic Region-Island Fallback (`TesseractOcrBackend`)**: Offline Tesseract (`tesseract.exe` + `eng.traineddata` & `ita.traineddata`) with connected-component white-core & Fisher text-island detection, single-pass stacked ROI recognition, and partial-result salvage.
- **Persistent Searchable Screenshot History (`history/`)**: Local SQLite + FTS5 gallery at `%LOCALAPPDATA%\Prismwake\History\` with instant full-text search, 5 sort modes, favorites, rename, save as, copy image/text, reopen in editor, pin/focus, and retention enforcement.
- **Single-Executable Release Architecture**: From v0.2.0 onward, `Prismwake.exe` and `Prismwake.exe.sha256` are the only release assets built and published.
