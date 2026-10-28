# v0.2.0 (9) Windows GUI smoke-test coordinate fix

## Windows failure captured on October 26, 2026

- Stage 4: **69/69 headless tests passed**.
- Next stage `tests/smoke_qt_gui.py` raised `RuntimeError: Clicking a second window in Window Capture mode failed to switch target` at line 301.
- The previous SettingsDialog `_add_labeled_row(helper_label=...)` fix was successful: the GUI smoke got through Settings and pinned controls before reaching Window Capture.

## Root cause

The Qt offscreen smoke test synthesized a captured framebuffer and candidate windows in **physical pixels (1280x720)** but called `ov.click_window_at(800, 300)` with a literal **overlay-local logical** coordinate. `SnipOverlayWindow` correctly maps local coordinates into physical coordinates using `window_capture_controller.px_scale_x/y`. When Qt's offscreen display dimensions differ (e.g. local overlay width 800), a local click at x=800 translates to physical x=1280 and is no longer inside mock target 5002 (physical x=640..1200). The test was DPI/virtual-screen-size-dependent, not a demonstrated real-user capture failure.

## Fix

Only `tests/smoke_qt_gui.py` changed. It now derives per-window click coordinates from the **center of each mock Win32 window** and the actual controller-local scaling. It asserts that the first and second click both target the expected HWND **and** that the final selection rectangle matches the target window bounds to within one pixel. It explicitly verifies the second hover target.

## Validation

- Reproduced the fixed-coordinate false negative in a standalone controller check at 1.6x and 2.0x overlay scaling; the new scaled coordinates select the correct second window at 1.0x, 1.25x, 1.6x, and 2.0x.
- Python compilation of updated GUI smoke test passed.
- The user's last run already passed 69/69 headless tests and staged RapidOCR.
- The full real PyQt6 Windows smoke test remains to be rerun on Windows. It may expose further GUI issues. This patch does not modify production OCR, capture, updater, or build scripts.

## Apply without reinstalling dependencies

Extract the small patch ZIP into the **root folder** of your existing `Prismwake_v0.2.0_v9_Settings_GUI_Smoke_Fix` project. Allow it to overwrite `tests/smoke_qt_gui.py`. Keep `.venv_build/`, `rapidocr_models/`, and `tesseract_bundle/`. Then run `START_BUILD_KEEP_OPEN.cmd`.

Do not publish v0.2.0 yet.
