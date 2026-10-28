# Prismwake v0.2.0 | Windows Qt Smoke Frame Lifetime Fix

## Reproduced failure

`tests/smoke_qt_gui.py` passed the 77 headless tests and reached native PyQt6 GUI smoke testing, but an annotation crop export returned `1x1` instead of `800x500`. The smoke test had called `ov.close()` on the earlier window-capture overlay, correctly releasing the shared `CapturedFrame` and replacing its `srgb_image` with a `1x1` memory-release sentinel. It then reused that released frame in a new annotation overlay.

## Minimal fix

Only `tests/smoke_qt_gui.py` changes in executable code. The window-capture fixture now verifies normal release on close; annotation smoke uses an independent freshly allocated `CapturedFrame` with the same `1280x720` image dimensions and physical geometry, and checks that its own buffers are released on close. The mouse event selection and exact `800x500` annotated export assertions remain intact. No capture/render/pinning/history/OCR/runtime logic was changed.

## Verification

- Source Python syntax and ZIP integrity: verified.
- Native Windows PyQt6 GUI smoke: not run in this Linux environment; requires Windows `START_BUILD_KEEP_OPEN.cmd` run.
- This corrects a test fixture lifecycle bug. It does *not* constitute live Windows validation of other drawing/export issues.
- GitHub remains untouched.
