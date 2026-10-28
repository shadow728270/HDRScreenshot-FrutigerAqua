Windows test fixes retained in this v0.2.0 (9) source project:
- Windows-safe optional resource imports in OCR benchmarks.
- Deterministic PNG OCR fixtures instead of OS-dependent font rendering.
- Neural backend availability/fallback tests isolated from installed models.
- Production RapidOCR and packaged neural-EXE verification preserved.
- Tests for updated settings, unified capture HUD, window targeting, pin
  opacity/click-through and history controls.
- Subprocess timeout PID test threshold restored to Windows-tested values.
- START_BUILD_KEEP_OPEN.cmd preserves the build window and diagnostic logs.

BUILD: Extract ZIP -> START_BUILD_KEEP_OPEN.cmd -> dist\Prismwake.exe.
Do not publish v0.2.0; this is a test candidate.
