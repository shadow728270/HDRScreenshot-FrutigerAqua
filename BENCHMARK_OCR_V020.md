# Prismwake v0.2.0 — Side-by-Side OCR Engine Benchmark Report

## Backend Execution Provenance & Honesty Statement

- **Host Environment**: `Linux 4.19.0-gvisor (x86_64)` (Python `3.11.2`, Peak Process RSS `157.3 MB`)
- **RapidOCR Neural Backend (`RapidOcrBackend`)**: `available=False` — onnxruntime 1.31.0 is installed, but the 'rapidocr' Python package is not installed in this environment.
- **Region-Island Tesseract Backend (`TesseractOcrBackend`)**: `available=True` — Ready (tesseract 5.3.0, langs=eng).
- **Was RapidOCR Neural Inference Demonstrated Live in This Run?**: **`NO (Tesseract fallback evaluated; run build_windows_oneclick.ps1 or GitHub Actions on Windows to execute live RapidOCR ONNX inference)`**

> **Important Note on Benchmark Claims**: Scores achieved by `TesseractOcrBackend` (`region_island_tesseract`) measure the connected-component white-core / Fisher island + stacked ROI Tesseract fallback pipeline and **must never be cited as RapidOCR neural accuracy**. Live RapidOCR neural accuracy is reported exclusively in the `RapidOCR (ONNX CPU)` column when `neural_demonstrated_in_this_run == True`.

## Aggregate Side-by-Side Engine Summary (Identical Unscaled Native Images)

| Engine / Pipeline | Demonstrated Live | Exact Matches | Mean CER | Mean WER | Char Errors | Word Errors | Missed Lines | Hallucinated Chars | Mean Latency | p95 Latency | Mean Peak Heap | Coords Valid |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Legacy Baseline (`recognize_image_ocr_legacy`)** | Yes | 13 / 31 | 25.63% | 38.12% | 376 | 84 | 11 | 14 | 379.9 ms | 702.9 ms | 1550.5 KB | `True` |
| **2. Region-Island Tesseract (`TesseractOcrBackend`)** | Yes | **30 / 31** | **0.25%** | **1.08%** | 2 | 1 | 0 | 0 | 1051.4 ms | 1946.9 ms | 8776.0 KB | `True` |
| **3. RapidOCR Neural (`RapidOcrBackend` ONNX CPU)** | **No (Not installed in offline Linux VM)** | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| **4. Production Hybrid Service (`recognize_production_ocr`)** | Yes (`Tesseract fallback`) | **30 / 31** | **0.25%** | **1.08%** | 2 | 1 | 0 | 0 | 1043.5 ms | 2021.7 ms | 8777.0 KB | `True` |

## Tier 1 — Native Unmodified Real Screenshot Crops (`native_real_capture`)

| Fixture ID | Size | Legacy CER / WER | Region-Island Tesseract CER / WER (Errs, Miss, Halluc, ms) | RapidOCR Neural CER / WER (Errs, Miss, Halluc, ms) | Production Active Backend |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `real_win11_explorer_search` | `350x36` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 335ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `real_win11_preview_warning` | `275x38` | 1.9% / 9.1% | **0.0% / 0.0%** (0c, 0m, 0h, 1720ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `real_code_python_imports` | `260x94` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 2256ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `real_dark_titlebar_compressed` | `195x28` | 3.9% / 33.3% | **7.7% / 33.3%** (2c, 0m, 0h, 1241ms) | `Unavailable in offline VM` | `Tesseract fallback` |

## Tier 2 — Held-Out Game HUDs, Menus, Tables & UI (`heldout_game_hud_and_ui`)

| Fixture ID | Size | Legacy CER / WER | Region-Island Tesseract CER / WER (Errs, Miss, Halluc, ms) | RapidOCR Neural CER / WER (Errs, Miss, Halluc, ms) | Production Active Backend |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `unseen_prose_leading_I_A_O` | `540x155` | 1.6% / 7.7% | **0.0% / 0.0%** (0c, 0m, 0h, 1792ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `unseen_markdown_pipe_table` | `560x115` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 1658ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `unseen_bordered_icon_menu` | `380x200` | 16.7% / 50.0% | **0.0% / 0.0%** (0c, 0m, 0h, 1700ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `unseen_shell_and_metadata` | `660x115` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 1697ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `unseen_cyan_five_buttons_menu` | `360x296` | 100.0% / 100.0% | **0.0% / 0.0%** (0c, 0m, 0h, 873ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `unseen_tall_sidebar_game_list` | `270x580` | 18.5% / 48.3% | **0.0% / 0.0%** (0c, 0m, 0h, 1252ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `unseen_vivid_colored_pills_menu` | `340x240` | 100.0% / 100.0% | **0.0% / 0.0%** (0c, 0m, 0h, 1796ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `unseen_tiny_colored_badges_hud` | `380x56` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 427ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `unseen_four_pill_game_hud` | `420x118` | 61.5% / 100.0% | **0.0% / 0.0%** (0c, 0m, 0h, 520ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `new_game_menu` | `400x260` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 1611ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `keep_leading_I` | `450x100` | 9.1% / 33.3% | **0.0% / 0.0%** (0c, 0m, 0h, 371ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `novel_stylized_sign` | `380x100` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 619ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `punctuation` | `700x135` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 1600ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `new_icon_menu` | `370x100` | 14.3% / 50.0% | **0.0% / 0.0%** (0c, 0m, 0h, 343ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `gradient` | `590x90` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 391ms) | `Unavailable in offline VM` | `Tesseract fallback` |

## Tier 3 — Synthetic Development Mockups (`synthetic_dev_mockup`)

| Fixture ID | Size | Legacy CER / WER | Region-Island Tesseract CER / WER (Errs, Miss, Halluc, ms) | RapidOCR Neural CER / WER (Errs, Miss, Halluc, ms) | Production Active Backend |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `windows_light_ui` | `680x130` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 577ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `windows_dark_ui` | `640x96` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 444ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `small_antialiased_code` | `620x210` | 5.3% / 25.0% | **0.0% / 0.0%** (0c, 0m, 0h, 1073ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `game_menu_with_icons` | `260x310` | 39.1% / 70.0% | **0.0% / 0.0%** (0c, 0m, 0h, 2098ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `stylized_sign_sell_logs` | `340x76` | 55.6% / 150.0% | **0.0% / 0.0%** (0c, 0m, 0h, 1345ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `usernames_mixed_case` | `520x88` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 456ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `gradient_antialiased_banner` | `540x80` | 66.7% / 80.0% | **0.0% / 0.0%** (0c, 0m, 0h, 1112ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `faint_low_contrast_watermark` | `540x90` | 100.0% / 100.0% | **0.0% / 0.0%** (0c, 0m, 0h, 440ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `threshold_harm_antialiased` | `540x110` | 6.2% / 25.0% | **0.0% / 0.0%** (0c, 0m, 0h, 473ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `inversion_harm_slate_surface` | `540x100` | 97.1% / 100.0% | **0.0% / 0.0%** (0c, 0m, 0h, 1290ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `inversion_help_dark_pill_in_light` | `520x180` | 0.0% / 0.0% | **0.0% / 0.0%** (0c, 0m, 0h, 534ms) | `Unavailable in offline VM` | `Tesseract fallback` |
| `isoluminant_rgb_alert` | `520x90` | 97.0% / 100.0% | **0.0% / 0.0%** (0c, 0m, 0h, 549ms) | `Unavailable in offline VM` | `Tesseract fallback` |

## Tier 4 — Diagnostic Preview-Widget Crops (`preview_crop_diagnostic`, Excluded from Native Accuracy Totals)

These two files (`diagnostic_only_*.png`) were cropped from a downscaled OCR-dialog preview widget with cyan overlay boxes burned into the pixels. They are evaluated separately for diagnostic transparency:

| Preview Crop File | Dimensions | Strategy & PSM | Mean Conf | Rejected as Low-Conf | Output / Diagnostic Warning |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `diagnostic_only_cyan_menu_preview_crop.png` | `232x194` | `row_roi_canvas` (PSM 6) | 95.5% | `False` | `'Report Bug / Request Feature\nJoin us on Discord\nSteam Workshop\nVideo Tutorials\nMerch Store'` |
| `diagnostic_only_tall_menu_preview_crop.png` | `67x191` | `local_polarity_norm` (PSM 6) | 0.0% | `True` | `REJECTED (Low-confidence or incomplete OCR output ('4\n&\no\nNI\nal\n“\nr "]\n...)` |
