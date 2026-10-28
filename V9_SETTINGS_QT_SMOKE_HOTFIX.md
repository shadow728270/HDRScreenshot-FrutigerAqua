# Prismwake v0.2.0 (9): Windows step-4 GUI smoke failure hotfix

## Root cause (confirmed from Windows logs)

The 69 headless tests completed successfully. The next test, `tests/smoke_qt_gui.py`, failed while constructing `SettingsDialog`:

`TypeError: SettingsDialog.__init__.<locals>._add_labeled_row() got an unexpected keyword argument 'helper_label'`

The helper had been changed to accept an optional fourth **positional** parameter (`helper_or_field`) but several Settings cards still invoke it as `helper_label=...`.

## Changes

- `Prismwake.py`: Give `_add_labeled_row` an explicit keyword-only `helper_label` parameter while retaining normal 3-argument calls and the legacy 4-positional-argument signature. Validate field controls are real Qt widgets for actionable errors.
- `tests/smoke_qt_gui.py`: Extend the real Qt test to check that three subtitle QLabel widgets are constructed. The GUI smoke test already constructs the complete SettingsDialog and will catch future helper signature mismatches.
- `START_BUILD_KEEP_OPEN.cmd`: Launch a separate `cmd.exe /K` persistent console and print the current test log paths. No more losing build failures because the window closes.
- All other source/build/OCR files are unchanged from the previously reviewed v9 ZIP.

## Verification limits

The user-provided Windows logs already show **69/69 headless tests passed** and RapidOCR models initialized. This hotfix is statically checked for Python syntax and source contract, but the real Windows PyQt6 smoke test and EXE packaging must be rerun on Windows. Do not publish this as v0.2.0 until the Windows build and GUI checks pass.
