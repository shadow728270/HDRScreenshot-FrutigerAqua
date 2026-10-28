# Prismwake v0.2.0 — Windows Qt History Selection Hotfix (27 Oct 2026)

## Why the previous build stopped

The Windows build reached stage `[4/7]`, ran 77 tests, and failed only `TestPart15HistoryRedesignAndAnnotationPerformance.test_08_qt_gui_branch_async_preview_cancellation_and_delegate_no_sync_paint`. In the embedded subprocess, the bare `AssertionError` occurred at `<string>`, line 90: `assert win.selected_capture_id == e2.capture_id` after rapid successive selections of three screenshots. The build script correctly aborts on a failed test.

## Root cause and fix

The real PyQt6 `QListWidget.setCurrentRow(row)` defaults to `QItemSelectionModel.NoUpdate`. With `ExtendedSelection`, previously selected rows can remain selected, while the old `HistoryWindow._current_entry()` used `selectedItems()[0]` (first in gallery order), which may not be the focused/current screenshot. The lightweight offline test harness automatically cleared selections on `setCurrentRow()` and therefore missed the Windows-specific behavior.

* `history/storage.py`: The `selected_capture_id` setter now atomically clears the prior selection, selects the target, and refreshes the inspector exactly once. `_current_entry()` prefers the currently focused selected card when there are multiple selected cards. Bulk-delete still uses `selectedItems()` for true multi-selection.
* `tests/test_prismwake_v020.py`: The precise 77th-test embedded Qt-branch subprocess now asserts there is exactly one selected row after programmatic switching and includes a Ctrl/Shift multi-selection inspector check. When running with the portable Qt harness, it simulates real Qt's `NoUpdate` selection semantics during the regression.
* `tests/qt_cairo_harness.py`: Added the missing `clearSelection()` method needed to exercise the production fix under the portable fake Qt backend.

## What was tested

* 8/8 new History/annotation tests: PASS (portable Qt/Cairo harness).
* 35/35 additional pinning, history storage, capture, updater, settings and UI regression tests: PASS (headless Python).
* Headless GUI smoke test: PASS.
* Python syntax compilation: PASS.
* An attempted full 77-test headless run reached the slow, real OCR tests but exceeded this environment's execution budget; it is **not** claimed as passed here.
* Native Windows GUI, packaged EXE, live HDR capture and click-through testing are **not** available in this Linux environment and must be verified on the user's Windows machine.

## Windows build

Extract this full project ZIP into a **fresh directory** and run `START_BUILD_KEEP_OPEN.cmd`. Do not apply the patch over an existing build environment or reuse an older `dist/Prismwake.exe`. The Windows builder must run all 77 tests and reach stages `[5/7]` through `[7/7]` before a release can be considered. No GitHub publication has been performed.
