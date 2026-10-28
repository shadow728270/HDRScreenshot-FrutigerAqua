# Prismwake v0.2.0 (v9) Real-World Capture/Settings Hotfix

This package is a **Windows test candidate, not a release**. Public v0.1.4 is unchanged.

## User-reported issues, findings, changes

1. **Top OCR button is redundant.** Removed OCR / Text mode button from capture HUD. The contextual **Text (OCR)** button remains on the bottom capture toolbar. The legacy direct OCR shortcut/workflow still exists for compatibility; pressing `4` during a selection now invokes the existing contextual OCR action.
2. **Window mode does not switch targets after one window is selected.** Fixed the actual Qt mouse-event priority: in Window mode `mousePressEvent` now asks the window controller to select the clicked window **before** selection resize handles, border dragging, or Move-tool hit tests can intercept the click. Hover highlighting now runs even inside the previous selection. A real Qt GUI smoke test now checks the mouse-event path rather than only calling `click_window_at` directly.
3. **Monitor mode only highlights the original display.** Root cause: `capture_screen_dxgi_hdr` captures the monitor under the pointer *before* the overlay opens; changing the overlay's mode cannot change that frozen framebuffer. Integrated the pre-existing **MonitorSelectorDialog**, added an explicit target-display argument to DXGI capture, and wired the Monitor HUD button/`3` key to choose a display then reopen a **fresh HDR-aware capture** on it. Window mode now has a **Change Display** HUD action for targeting windows on another monitor. This is intentionally explicit display selection rather than pretending a one-monitor overlay lets the user click a different physical monitor. On a single-monitor PC, selection happens automatically.
4. **Second capture fails: `wrapped C/C++ object of type AeroGlassToolbar has been deleted`.** Added explicit HUD cleanup and a destroyed-Qt-widget guard in the shared animation director, which held weak Python references to destroyed C++ widget wrappers. Prevents shared animation loops from dereferencing deleted toolbars after overlay close. The crash may have other contributing paths; repeat-capture Windows verification is required.
5. **Settings cannot close.** Settings had X/Cancel/Save widgets but an exception in preview reset/animation could prevent Qt's `reject()`. Cancel now always calls `QDialog.reject` in a `finally` block, and the finished callback always releases controller references. Added Ctrl+W and Escape shortcuts; real Qt smoke test now clicks X and Cancel and checks the dialog becomes hidden.

## Changed source files
- `Prismwake.py`: capture mode HUD, monitor selection, Win32 mouse routing, settings, animation lifecycle.
- `tests/smoke_qt_gui.py`: regression checks for missing redundant OCR HUD button, Settings X/Cancel, actual mouse event switching target window.

No OCR backend, model files, dependencies, or Windows build scripts changed. The historical Windows-specific benchmark/test portability fixes and builder logging are retained.

## Verification performed outside Windows
- `python -m compileall` on the full source: **PASS**.
- Five focused Part14 automated headless tests: **5/5 PASS**.
- The native Windows/Qt GUI smoke test and packaged EXE neural verification **cannot be run** in this Linux environment. The new monitor selection and deleted-toolbar safeguards specifically need a Windows test before considering release.

## Test on Windows
Use `START_BUILD_KEEP_OPEN.cmd` (it keeps the console and logs on failure). If reusing an existing project with a working `.venv_build` and staged `rapidocr_models`, apply the drop-in patch and replace existing files rather than extracting a fresh full project.

After a successful build:
1. Press capture hotkey; confirm **no OCR mode on top bar**, while bottom Text (OCR) works.
2. Select Window mode; hover/click **two different windows on same screen**. Confirm highlight, selection bounds, and switching.
3. If multiple monitors: click **Monitor**, choose display #2, confirm a new capture opens on #2. In Window mode, use **Change Display** then target a window on #2. Verify HDR color is preserved.
4. Close the overlay with Escape / X, reopen repeatedly using hotkey and tray. Confirm no deleted toolbar error.
5. Open Settings from tray, close using X, reopen and close with Cancel / Escape / Ctrl+W; reopen and Save & Apply.
6. Retest RapidOCR and history/pinning, particularly click-through and opacity.

Report diagnostic logs if any crash persists. Do not publish v0.2.0 yet.
