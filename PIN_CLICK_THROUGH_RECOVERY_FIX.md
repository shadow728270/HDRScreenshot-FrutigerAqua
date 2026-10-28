# Prismwake v0.2.0: Pinned Screenshot Click-Through Recovery Hotfix

## User-reported problem
Click-Through on a pinned screenshot successfully lets mouse clicks pass to underlying apps, but clicking the floating **Click to Control** unlock pill does nothing. The pin becomes effectively stuck above the desktop.

## Recovery without rebuilding
From the Prismwake system-tray context menu, select **Pinned & Diagnostics → Unlock All Click-Through Pins**. If necessary, select **Close All Pinned Screenshots**. Exit Prismwake from the tray if both fail.

## Code correction (`pinning/manager.py`)
- On the real Qt **Windows** platform, use **only** Win32 `WS_EX_TRANSPARENT` for the pinned image, instead of layering it with `Qt.WindowTransparentForInput` and Qt's mouse-events transparency. Those redundant layers risk blocking recovery after Windows styles change.
- Apply/clear extended window styles using correctly sized `GetWindowLongPtrW` / `SetWindowLongPtrW` signatures, refresh hit testing with `SetWindowPos(SWP_FRAMECHANGED)`, and confirm that `WS_EX_TRANSPARENT` matches the requested state.
- Avoid recreating the pinned image HWND when toggling only Click-Through.
- Keep the floating unlock pill as a separate, opaque, always-on-top top-level window. Explicitly ensure that it has **no** input-transparent flag and that Windows native hit-testing remains enabled.
- Allow the tray's **Unlock All Click-Through Pins** action to restore all pins through the same native path.
- Use `GetAsyncKeyState` for the global **Alt+Shift + hover** emergency unlock gesture even when Prismwake is not the foreground application.
- Safely retain Qt-only behavior for offscreen GUI smoke tests; the offscreen Qt platform does not provide real Windows HWNDs.

## Tests
- Python syntax checks pass across the project.
- Five targeted UI/capture headless tests pass.
- GUI smoke test now verifies the unlock pill is a separate mouse-interactive window and that manager-level emergency unlock restores a pin.
- Native Windows hit-testing is **not available in the Linux test container**. Run the Windows build and test a click-through pin using real mouse clicks before release.

## Expected Windows manual test
1. Build with `START_BUILD_KEEP_OPEN.cmd`, then run `dist\\Prismwake.exe`.
2. Pin a screenshot, activate Click-Through, verify clicks pass to underlying app.
3. Click the visible **Click to Control** floating pill. Verify you can move and resize the original pin again.
4. Repeat three times, including over a fullscreen or maximized window.
5. Re-enable Click-Through and use **Pinned & Diagnostics → Unlock All Click-Through Pins**. Verify recovery.
6. Re-enable Click-Through and hold **Alt+Shift** with the pointer over the pinned screenshot. Verify recovery even when another app is focused.
7. Verify normal opacity and resizes, and that pin windows and unlock pills are closed when exiting.

This source patch does not publish to GitHub and does not change the OCR engine or build scripts.
