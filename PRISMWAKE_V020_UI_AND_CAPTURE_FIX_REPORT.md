# Prismwake v0.2.0 — UI Polish, Settings Reliability, Pinned Controls & True Window Capture Report

## 1. Root Causes Identified & Fixed

1. **Settings Actions Doing Nothing (`Settings...` in Tray & `Storage & Privacy Settings` in History)**
   - **Root Cause**: In `SettingsDialog.__init__` (`Prismwake.py`), the helper `_add_labeled_row(parent_vbox, label_text, field_widget, helper_label=None)` took 3 required positional arguments, but Cards 6, 7, and 8 called `_add_labeled_row(cap_vbox, cap_card, "Default Mode:", self.default_cap_mode_combo)` with 4 arguments (passing the parent `QFrame` as `label_text` and the string `"Default Mode:"` as `field_widget`). Calling `"Default Mode:".setMinimumWidth(0)` raised `AttributeError: 'str' object has no attribute 'setMinimumWidth'` inside the Qt slot before the dialog could appear.
   - **Fix**: Fixed all `_add_labeled_row` calls, hardened `_add_labeled_row` to accept either signature defensively, unified Card 6–9 object names (`AquaSectionCard` / `SectionHeader`), added `Max History Items`, `Max Storage Size (MB)`, and `Retention Period (Days)` spinboxes to Card 7, added `SettingsDialog.focus_section(section)`, and updated `HDRSnipFusionApplication.open_settings(section=...)` to focus an existing `SettingsDialog` instance if already open, scroll directly to `storage_privacy` when opened from History, and log/surface any error via `QMessageBox.critical`.

2. **Window Capture Acting Like Freehand Region Capture**
   - **Root Cause**: Previously, `Window Capture` only queried `detect_window_at_physical_point` once when the tray menu item was clicked (while the cursor was still over the system tray) and had no window-hover or window-click logic inside `SnipOverlayWindow.mouseMoveEvent` or `mousePressEvent`.
   - **Fix**: Implemented `WindowCaptureSessionController` (`capture/smart_modes.py`) and wired it into `SnipOverlayWindow` (`Prismwake.py`). Before the overlay opens, Prismwake snapshots visible, non-minimized, non-cloaked top-level windows in Z-order (`EnumWindows` + `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)` + `GetClientRect`/`ClientToScreen`, excluding Prismwake's own PID/HWNDs and shell classes). Moving the cursor in Window Capture mode dynamically highlights the topmost window under the cursor with an Aqua outline, dimmed surround, and title/size badge. Clicking snaps the selection to that window's exact bounds, clicking a different window immediately moves the capture area to that newly clicked window, and pressing `W` (or clicking `Client Area`) toggles between full-window and client-area bounds.

3. **Cluttered Tray Menu & Missing In-Capture Mode Switcher**
   - **Root Cause**: All 5 capture modes (`Region`, `Window`, `Fullscreen`, `Text Capture`, `Delayed Capture`) plus utility items were exposed as top-level tray menu entries.
   - **Fix**: Simplified the tray menu to 7 focused entries (`✦ Capture`, `🗂 History`, `⚙ Settings...`, `Open Screenshots Folder`, `Check for Updates...`, `Pinned & Diagnostics` submenu, and `Exit Prismwake`) and added the Frutiger Aqua **Capture Mode HUD Bar** (`self.mode_hud_bar`) at the top-center of `SnipOverlayWindow` for live switching between `✦ Region (1)`, `▣ Window (2)`, `🖥 Monitor (3)`, `🔤 OCR / Text (4)`, and `⏱ Delay (5 — 3s/5s/10s)`.

4. **Pinned Screenshot Opacity & Click-Through Controls**
   - **Root Cause**: `PinnedScreenshotWindow` lacked a live opacity slider on its hover toolbar and had no click-through mode.
   - **Fix**: Upgraded `PinnedScreenshotState`, `PinnedScreenshotManager`, and `PinnedScreenshotWindow` (`pinning/manager.py`) with a live hover-toolbar **Opacity slider (`15%–100%`)** + `Alt+Wheel` + context-menu presets, **Click-Through toggle** (`WindowTransparentForInput` + `WA_TransparentForMouseEvents` + Win32 `WS_EX_TRANSPARENT | WS_EX_LAYERED`), an interactive top-right floating **Click-Through Unlock Pill** (`PinClickThroughControlPill`: `👻 Click-Thru ON (Click to Control)`), `Alt+Shift` hover auto-unlock, Tray Menu `Unlock All Click-Through Pins`, `📌 Top` (Always-on-Top) toggle, and `1:1` Reset Size. Also added `pin_manager.pin_or_focus(...)` so clicking `Pin` on an already-pinned History item focuses/raises and unlocks the existing pin window.

5. **Windows Builder & Test Non-Regression Preservation (Section 8A)**
   - Replaced unconditional `import resource` in `ocr/benchmark.py` and `ocr/eval_side_by_side.py` with platform-safe optional imports.
   - Saved portable deterministic PNG fixtures in `tests/fixtures/suite_a_ocr/` so Linux and Windows tests evaluate identical glyph bitmaps without OS font differences.
   - Isolated neural unavailability tests via `_UnavailableNeuralBackend` and strict `custom_model_dir` handling in `ocr/backends.py`.
   - Made Tesseract-specific tests explicitly select `HybridOcrOrchestrator(prefer_neural=False)` and made subprocess cancellation wait deterministically for `pid_file` creation before canceling.
   - Added `START_BUILD_KEEP_OPEN.cmd` alongside `build_windows_oneclick.bat` and `build_windows_oneclick.ps1`.
