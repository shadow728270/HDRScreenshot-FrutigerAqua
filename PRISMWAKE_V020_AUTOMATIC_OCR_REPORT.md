# Prismwake v0.2.0 (v8 Repair) — RapidOCR Production Integration & Release-Gated Packaging Report

## 1. Executive Summary of v8 Release-Blocker Repairs

This update resolves all P0 and P1 release blockers identified in the static and runtime audit of `Prismwake_v0.2.0_v8_Windows_Test_Ready.zip`:

1. **P0 Fixed — All User-Facing & Background OCR Workflows Wired to Production `HybridOcrOrchestrator` (`recognize_production_ocr`)**:
   - Previously, `HybridOcrOrchestrator` and `RapidOcrBackend` existed in `ocr/backends.py` and were called by `ocr/eval_side_by_side.py`, while `OcrWorkerJob.run()` in `ocr/engine.py` and history OCR in `Prismwake.py` still called `recognize_image_ocr()` (Tesseract) directly.
   - **Repair**: Created the single production orchestration service `recognize_production_ocr()` (`get_production_ocr_orchestrator()` / `set_production_ocr_orchestrator()` / `override_production_ocr_orchestrator()` in `ocr/backends.py`) and wired **every** production OCR entry point to it:
     - `OcrWorkerJob.run()` (both Qt `QRunnable` and headless worker in `ocr/engine.py`)
     - `OcrResultsDialog.start_recognition()` (Compact Quick OCR, Advanced OCR, Quick Retry, and Advanced Retry Recognition)
     - System tray **Text Capture** (`trigger_capture_mode("ocr")`) and Editor **Text (OCR)** (`SnipOverlayWindow.ocr_snip()`)
     - Asynchronous **screenshot-history OCR indexing** (`_on_overlay_capture_completed` in `Prismwake.py`)
     - **History Gallery OCR** (`open_history_window` / `HistoryWindow.copy_current_text` in `Prismwake.py` and `history/storage.py`, running asynchronously off the Qt GUI thread)
     - Packaged-EXE CLI verification (`--write-ocr-verify-file` / `--require-neural` in `Prismwake.py`)

2. **P0 Fixed — User-Visible Backend Diagnostic Indicator (`RapidOCR (ONNX CPU)` vs `Tesseract fallback`)**:
   - Added `backend_selected` and `fallback_reason` to `OcrRecognitionResult`.
   - Added `backend_diag_label` to `OcrResultsDialog` (hidden in Compact Quick OCR so Quick OCR stays uncluttered, and visible in Advanced OCR displaying `Backend: RapidOCR (ONNX CPU)` or `Backend: Tesseract fallback` with a tooltip showing the exact fallback reason).
   - Updated `format_ocr_summary()` and `query_ocr_engine_status()` (used by Settings Card 8 and startup checks) to report truthfully whether `RapidOCR (ONNX CPU)` is active or whether `Tesseract fallback` is active.

3. **P0 Fixed — Release-Gated Neural Installation, Model Staging, Integrity Verification & Packaged-EXE Self-Test**:
   - **`requirements.txt`**: Pinned mutually compatible versions of `onnxruntime>=1.20.0,<=1.31.0`, `rapidocr>=3.9.2,<=3.10.0`, `opencv-python-headless>=4.8.0,<5.0.0`, `pyclipper>=1.3.0,<2.0.0`, `shapely>=2.0.0,<3.0.0`, `PyYAML>=6.0,<7.0`, and `omegaconf>=2.3.0,<3.0.0` alongside `PyQt6`, `numpy`, and `Pillow`.
   - **`tools/stage_rapidocr_models.py` & `verify_rapidocr_model_directory()`**:
     - Stages the exact detector, recognizer, and classifier `.onnx` weights plus configuration and dictionary files into `rapidocr_models/` and writes `rapidocr_models/model_manifest.json` with SHA-256 digests.
     - Validates every `.onnx` file by loading it into `onnxruntime.InferenceSession(..., providers=["CPUExecutionProvider"])` (rejecting dummy or corrupt `*det*.onnx` / `*rec*.onnx` files), verifies SHA-256 hashes against `model_manifest.json`, and inspects the recognizer's embedded character dictionary metadata (`character`) to verify English + Italian (`à, è, é, ì, ò, ù`) support.
     - Enforces `_block_network_downloads()` (blocking `urllib.request.urlopen`, `urllib.request.urlretrieve`, and `socket.create_connection`) so zero runtime model downloads can ever occur.
   - **`build_windows_oneclick.ps1` & `.github/workflows/build-windows.yml`**:
     - Provisions an isolated `.venv_build` using Python 3.12 / 3.13 / 3.11 (automatically installing user-scope Python 3.12 via `winget` if only Python 3.14 is present, without modifying global Python 3.14).
     - Fails immediately if `rapidocr` or `onnxruntime` installation or `tools/stage_rapidocr_models.py --strict` fails.
     - Bundles `--collect-all rapidocr`, `--collect-all onnxruntime`, `--add-data "rapidocr_models;rapidocr_models"`, `--add-data "tesseract_bundle;tesseract_bundle"`, and `--add-data "THIRD_PARTY_LICENSES.md;."` in PyInstaller (`Prismwake.exe` only; no `HDRSnipFusion.exe`).
     - Executes `dist\Prismwake.exe --write-ocr-verify-file dist\ocr_verify.json --require-neural` and prints the 5-point **Offline OCR Backend Self-Test Summary**:
       1. `RapidOCR installed` (`PASS` / `FAIL`)
       2. `models verified` (`PASS` / `FAIL`)
       3. `neural EXE inference` (`PASS` / `FAIL`)
       4. `Tesseract fallback` (`PASS` / `FAIL`)
       5. `offline cache-cleared test` (`PASS` / `FAIL`)
     - A Tesseract-only build fails `--require-neural` with exit code `3`.

4. **P1 Fixed — Honest Side-by-Side Benchmark & Provenance Separation (`ocr/eval_side_by_side.py`, `BENCHMARK_OCR_V020.md`)**:
   - Explicitly separates native real screenshot crops (`native_real_capture`), held-out game HUDs/menus/tables (`heldout_game_hud_and_ui`), synthetic development mockups (`synthetic_dev_mockup`), and downscaled dialog-preview crops (`preview_crop_diagnostic`).
   - Reports character/word errors, CER/WER, missed lines, hallucinated characters, latency, `tracemalloc` peak heap, process RSS, and native coordinate bounds validity side-by-side across `LegacyTesseractPipeline`, `TesseractOcrBackend`, `RapidOcrBackend`, and `HybridOcrOrchestrator`.
   - Clearly states that in the offline Linux test sandbox (where outbound internet/pip is disabled and `rapidocr` is not pre-installed), the live numbers measure the region-island Tesseract fallback (`TesseractOcrBackend`), whereas `build_windows_oneclick.ps1` and GitHub Actions run `python -m ocr.eval_side_by_side --require-neural` on Windows with the staged ONNX models.

---

## 2. Automated Verification Summary

| Test Suite | Tests Run | Result | Key Verifications |
| :--- | :---: | :---: | :--- |
| `tests/test_prismwake_v020.py` (`TestPart1`–`TestPart13`) | **64** | **PASS (64/64)** | Sentinel fake neural backend proves all 8 production OCR flows dispatch through `recognize_production_ocr`; throwing/unavailable neural backends prove fallback to `TesseractOcrBackend`; ONNX graph & SHA-256 manifest validation rejects dummy `.onnx` files; `--require-neural` CLI gate fails on Tesseract-only and passes when neural is active |
| `tests/smoke_qt_gui.py` | **1** | **PASS** | Quick OCR default compact geometry, `backend_diag_label` hidden in Quick mode and visible (`Backend: RapidOCR (ONNX CPU)`) in Advanced mode, no manual threshold checkbox, no clipboard overwrite on empty OCR |
| `test_prismwake_v014.py` | **13** | **PASS (13/13)** | Settings dialog responsive layout, multi-size icon frames, v0.1.4 stability regressions |
| `test_prismwake_v013.py` | **13** | **PASS (13/13)** | Aqua glass rendering, DXGI HDR scRGB tone-mapping, annotation tools |
| `test_legacy_updater_contract.py` | **5** | **PASS (5/5)** | Updater SHA-256 verification, PE64 validation, rollback safety |
