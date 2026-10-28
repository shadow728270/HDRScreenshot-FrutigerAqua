# Prismwake v0.2.0 — Quick OCR + Advanced OCR Interface Redesign Change Report

## 1. Summary of Changes & Touched Files

Starting strictly from `Prismwake_v0.2.0_Gemini_OCR_UI_Handoff.zip`, the OCR interface has been redesigned into **two progressively disclosed modes** (**Compact Quick OCR** by default + **Advanced OCR** on demand) while preserving all five baseline fixes from the handoff archive.

| File | Summary of Changes |
| :--- | :--- |
| `ocr/engine.py` | Added `compute_quick_ocr_panel_geometry()`, `compute_advanced_ocr_panel_geometry()`, `resolve_ocr_aqua_theme_palette()`, `count_recognized_words_and_lines()`, `format_quick_ocr_badge_text()`, and `format_quick_ocr_footer_label()`; redesigned `OcrResultsDialog` (both PyQt6 and headless controller implementations) with frameless non-modal **Quick OCR** (`mode="quick"`) and resizable **Advanced OCR** (`mode="advanced"`) sharing a single `text_edit` widget so mode transitions never rerun OCR or lose user edits/selections; preserved `-c tessedit_create_tsv=1 -c tessedit_create_txt=0`, malformed-TSV error detection, dark-theme auto-inversion, and multi-PSM fallback (`6 -> 11 -> 3`). |
| `ocr/__init__.py` | Exported the new Quick/Advanced OCR geometry, formatting, and Frutiger Aqua theme helpers alongside all existing OCR engine symbols. |
| `Prismwake.py` | Added `ocr_show_panel_after_auto_copy: bool = True` to `AppConfig` alongside `ocr_auto_copy_text: bool = False`; added the corresponding checkbox in `SettingsDialog` (Card 8); updated `SnipOverlayWindow.ocr_snip()` and `HDRSnipFusionApplication._on_overlay_closed()` / `_on_overlay_ocr_requested()` / `_open_ocr_results_dialog()` to capture the selection's global logical screen rectangle and active `QScreen.availableGeometry()` before overlay teardown and pass them (along with the active Frutiger Aqua theme and animation preferences) to `OcrResultsDialog`. |
| `tests/test_prismwake_v020.py` | Preserved all 27 baseline tests and added `TestPart8QuickAndAdvancedOcrRedesign` (10 new tests; **37/37 total passing**) covering Quick mode sizing (short 3-word vs. long multiline scrolling), editable text, `Ctrl+A`/`Ctrl+C`/`Copy` transient `Copied!` feedback, `Expand` <-> `Compact View` state preservation without re-running OCR, explicit Retry edit protection, empty/error states, auto-copy preferences (and no clipboard overwrite on empty/error), multi-monitor/negative-coordinate clamping, full overlay-to-Quick-panel lifecycle, Frutiger Aqua themes, SQLite Windows handle closure, and `build_windows_oneclick.ps1` failure checks. |
| `tests/smoke_qt_gui.py` | Expanded the isolated native `QApplication` smoke test to verify Quick OCR default mode, 3-word compact logical dimensions (`420–520` px wide, `160–250` px tall), hidden preview/line list in Quick mode, editable text & `Copied!` feedback without auto-closing, `Expand`/`Collapse` state preservation without re-running OCR, and empty-state clipboard protection. |
| `.github/workflows/build-windows.yml` | Updated test step to execute `tests/run_headless_tests.py` and `tests/smoke_qt_gui.py` in isolated processes with explicit `$LASTEXITCODE` checks matching `build_windows_oneclick.ps1`. |
| `PRISMWAKE_V020_RELEASE_NOTES.md`, `TEST_FIXES_README.txt` | Updated release notes and test instructions to document the two-mode Quick/Advanced OCR workflow and auto-copy settings. |

## 2. Preserved Non-Negotiable Baseline Fixes

1. **Tesseract TSV without `configs/tsv` (`ocr/engine.py`)**: Continues to pass `-c tessedit_create_tsv=1 -c tessedit_create_txt=0` instead of positional `tsv`, validates the TSV header (`level\tpage_num\t`), reports malformed output as an actionable error, and preserves dark-theme auto-inversion and layout retry (`_psm 6 -> 11 -> 3`).
2. **Windows SQLite File Locking (`history/storage.py`)**: Preserves the explicit closing context manager in `ScreenshotHistoryStore._connect()` (`try: with conn: yield conn finally: conn.close()`), verified by immediate file rename in `test_10_sqlite_windows_file_locking_and_builder_failure_checks_regression`.
3. **Separated Headless & Real-Qt Test Runners (`tests/run_headless_tests.py`, `tests/smoke_qt_gui.py`)**: Keeps synthetic/headless controller tests isolated from native PyQt6 widget instantiation without a `QApplication`.
4. **Strict Windows One-Click Builder (`build_windows_oneclick.ps1`)**: Preserves `Assert-NativeSuccess`, `Invoke-IsolatedPythonTest`, per-step log files, stale `dist\Prismwake.exe` removal before PyInstaller, and `--write-ocr-verify-file` validation on the compiled executable.
5. **Single-EXE v0.2.0 Architecture**: Only `Prismwake.exe` and `Prismwake.exe.sha256` are built and verified; `HDRSnipFusion.exe` remains retired.

## 3. Automated Tests Run in This Environment vs. Windows Hardware Validation

- **Verified in Linux Sandbox (`37/37` passing in `25.4s`)**:
  - `python3 tests/run_headless_tests.py` ran all 27 baseline tests plus 10 new Quick/Advanced OCR tests against the real local Tesseract 5 binary (` verify_packaged_tesseract_launch`, missing `configs/tsv` regression, dark-theme small text, sparse layout fallback, SQLite history CRUD/FTS5/unlocked file rename, pinned screenshots, smart capture modes, single-EXE updater, and Quick/Advanced OCR UI controller & geometry clamping).
- **Requires Real Windows 10/11 Validation**:
  - Running `build_windows_oneclick.bat` / `build_windows_oneclick.ps1` on Windows to execute `tests\smoke_qt_gui.py` under a live Windows `QApplication`, compile `dist\Prismwake.exe` with PyInstaller, and visually verify the frameless Quick OCR panel and `Expand` transition on physical single/multi-monitor DPI setups.
