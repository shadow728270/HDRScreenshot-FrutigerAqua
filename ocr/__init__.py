"""
Prismwake v0.2.0 — Offline OCR & Text Extraction Subsystem (`ocr`)
===================================================================
Provides 100% offline text recognition for Windows 10/11 unpackaged executables:
  - Single production OCR orchestration service (`HybridOcrOrchestrator`, `recognize_production_ocr`,
    `get_production_ocr_orchestrator`, `set_production_ocr_orchestrator`, `override_production_ocr_orchestrator`)
    wired across Quick OCR, Advanced OCR, Retry, tray Text Capture, editor OCR, screenshot-history
    indexing, history gallery OCR, and packaged-EXE self-tests.
  - Pluggable OCR backend architecture (`OcrBackend`, `RapidOcrBackend`, `TesseractOcrBackend`,
    `OcrBackendStatus`) supporting local CPU ONNX Runtime neural models (`rapidocr`) with verified
    weights and automatic fallback to offline Tesseract (`tesseract.exe` + `tessdata/`).
  - Connected-component white-core & Fisher linear discriminant text-island segmentation with
    single-pass stacked ROI recognition for multi-column game HUD pills, vivid buttons, and menus.
  - Token- and line-level partial-result salvage (`filter_and_salvage_partial_ocr_result`) so
    credible recognized words (such as `'CLOSED'`) are never zeroed out when other regions fail,
    marking incomplete reads with `'partial result / low confidence'`.
  - Background `QRunnable` worker (`OcrWorkerJob`) with progress reporting and cancellation.
  - Two-mode progressively disclosed Frutiger Aqua `OcrResultsDialog` with Advanced backend diagnostics.
"""

from .engine import (
    SUPPORTED_OCR_LANGUAGES,
    VALID_OCR_QUALITY_MODES,
    OCR_QUALITY_MODE_LABELS,
    AUTOMATIC_OCR_STATUS_TEXT,
    OCR_AQUA_THEME_PALETTES,
    OcrWordBox,
    OcrLineBox,
    OcrRecognitionResult,
    OcrEngineStatus,
    OcrImageProfile,
    OcrPreprocessCandidate,
    CancellationToken,
    detect_tesseract_runtime,
    query_ocr_engine_status,
    analyze_image_for_ocr,
    preprocess_image_for_ocr,
    generate_ocr_preprocessing_candidates,
    select_adaptive_psms,
    score_ocr_candidate,
    is_plausible_ocr_result,
    filter_and_salvage_partial_ocr_result,
    run_bounded_ocr_subprocess,
    export_ocr_diagnostic_bundle,
    refine_ocr_result_layout_and_spacing,
    recognize_image_ocr,
    recognize_image_ocr_legacy,
    verify_packaged_tesseract_launch,
    format_ocr_summary,
    count_recognized_words_and_lines,
    format_quick_ocr_badge_text,
    format_quick_ocr_footer_label,
    resolve_ocr_aqua_theme_palette,
    compute_quick_ocr_panel_geometry,
    compute_advanced_ocr_panel_geometry,
)
from .backends import (
    OcrBackend,
    OcrBackendStatus,
    RapidOcrBackend,
    TesseractOcrBackend,
    HybridOcrOrchestrator,
    get_production_ocr_orchestrator,
    set_production_ocr_orchestrator,
    override_production_ocr_orchestrator,
    recognize_production_ocr,
    verify_rapidocr_model_directory,
    verify_packaged_ocr_launch,
)

__all__ = [
    "SUPPORTED_OCR_LANGUAGES",
    "VALID_OCR_QUALITY_MODES",
    "OCR_QUALITY_MODE_LABELS",
    "AUTOMATIC_OCR_STATUS_TEXT",
    "OCR_AQUA_THEME_PALETTES",
    "OcrWordBox",
    "OcrLineBox",
    "OcrRecognitionResult",
    "OcrEngineStatus",
    "OcrImageProfile",
    "OcrPreprocessCandidate",
    "CancellationToken",
    "OcrBackend",
    "OcrBackendStatus",
    "RapidOcrBackend",
    "TesseractOcrBackend",
    "HybridOcrOrchestrator",
    "get_production_ocr_orchestrator",
    "set_production_ocr_orchestrator",
    "override_production_ocr_orchestrator",
    "recognize_production_ocr",
    "verify_rapidocr_model_directory",
    "verify_packaged_ocr_launch",
    "detect_tesseract_runtime",
    "query_ocr_engine_status",
    "analyze_image_for_ocr",
    "preprocess_image_for_ocr",
    "generate_ocr_preprocessing_candidates",
    "select_adaptive_psms",
    "score_ocr_candidate",
    "is_plausible_ocr_result",
    "filter_and_salvage_partial_ocr_result",
    "run_bounded_ocr_subprocess",
    "export_ocr_diagnostic_bundle",
    "refine_ocr_result_layout_and_spacing",
    "recognize_image_ocr",
    "recognize_image_ocr_legacy",
    "verify_packaged_tesseract_launch",
    "format_ocr_summary",
    "count_recognized_words_and_lines",
    "format_quick_ocr_badge_text",
    "format_quick_ocr_footer_label",
    "resolve_ocr_aqua_theme_palette",
    "compute_quick_ocr_panel_geometry",
    "compute_advanced_ocr_panel_geometry",
]
