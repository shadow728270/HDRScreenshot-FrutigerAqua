"""
Prismwake v0.2.0 — Side-by-Side OCR Engine Evaluation Utility (`ocr.eval_side_by_side`)
========================================================================================
Runs a controlled side-by-side benchmark on identical native-resolution images across:
  1. `RapidOcrBackend` (local CPU ONNX neural detector + recognizer via `rapidocr` / `onnxruntime`).
  2. `TesseractOcrBackend` (connected-component white-core / Fisher island detector + single-pass
     stacked ROI recognition + token/line partial-result salvage).
  3. `LegacyTesseractPipeline` (`recognize_image_ocr_legacy` — prior single-pass global-median baseline).
  4. `HybridOcrOrchestrator` (`recognize_production_ocr` — actual production service wired to the GUI).

Distinguishes fixture provenance tiers explicitly:
  - `native_real_capture`: unmodified pixel crops from real Windows 11 / desktop screenshots.
  - `heldout_game_hud_and_ui`: native-resolution game HUDs, menus, tables, and prose fixtures.
  - `synthetic_dev_mockup`: initial development fixtures.
  - `preview_crop_diagnostic`: downscaled OCR-dialog preview crops with overlay rectangles burned in
    (evaluated separately for diagnostic transparency and never mixed into native accuracy totals).

Records per-fixture and per-suite:
  - Character errors & CER, word errors & WER, missed lines, hallucinated/stray characters,
    wall-clock latency (ms), peak Python heap delta (`tracemalloc` KB), process RSS (MB),
    and native coordinate bounds verification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]
import sys
import time
import tracemalloc
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .backends import (
    HybridOcrOrchestrator,
    RapidOcrBackend,
    TesseractOcrBackend,
    _verify_coords_in_bounds,
    recognize_production_ocr,
)
from .benchmark import (
    OcrBenchmarkFixture,
    _levenshtein_distance,
    build_ground_truth_ocr_fixtures,
    build_independent_regression_ocr_fixtures,
    build_realworld_heldout_ocr_fixtures,
    compute_cer,
    compute_wer,
    count_missing_lines_and_stray_symbols,
    evaluate_diagnostic_preview_evidence,
)
from .engine import (
    OcrLineBox,
    OcrRecognitionResult,
    OcrWordBox,
    filter_and_salvage_partial_ocr_result,
    recognize_image_ocr_legacy,
)


def _normalize_ocr_eval_text(txt: str) -> str:
    return "\n".join(" ".join(ln.split()) for ln in (txt or "").strip().splitlines())


def _compute_char_and_word_errors(predicted: str, expected: str) -> Tuple[int, int, float, float]:
    pred_norm = _normalize_ocr_eval_text(predicted)
    exp_norm = _normalize_ocr_eval_text(expected)
    char_errs = int(_levenshtein_distance(list(pred_norm), list(exp_norm)))
    cer = float(char_errs) / float(max(1, len(exp_norm))) if exp_norm else (0.0 if not pred_norm else 1.0)

    pred_words = pred_norm.split()
    exp_words = exp_norm.split()
    word_errs = int(_levenshtein_distance(pred_words, exp_words))
    wer = float(word_errs) / float(max(1, len(exp_words))) if exp_words else (0.0 if not pred_words else 1.0)
    return char_errs, word_errs, cer, wer


def _measure_single_run(
    runner: Callable[[], OcrRecognitionResult],
    ground_truth: str,
) -> Dict[str, Any]:
    tracemalloc.start()
    t0 = time.perf_counter()
    res = runner()
    lat_ms = (time.perf_counter() - t0) * 1000.0
    _cur_b, peak_b = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    char_errs, word_errs, cer, wer = _compute_char_and_word_errors(res.text, ground_truth)
    miss_lines, stray_syms = count_missing_lines_and_stray_symbols(res.text, ground_truth)
    mean_conf = float(np.mean([w.confidence for w in res.words])) if res.words else 0.0
    coords_ok = _verify_coords_in_bounds(res) if res.has_text else True

    return {
        "text": res.text,
        "engine_name": res.engine_name,
        "backend_selected": getattr(res, "backend_selected", "") or res.engine_name,
        "fallback_reason": getattr(res, "fallback_reason", ""),
        "cer": round(cer, 4),
        "wer": round(wer, 4),
        "char_errors": char_errs,
        "word_errors": word_errs,
        "missing_lines": miss_lines,
        "hallucinated_chars": stray_syms,
        "stray_symbols": stray_syms,
        "latency_ms": round(lat_ms, 2),
        "peak_kb": round(peak_b / 1024.0, 2),
        "mean_confidence": round(mean_conf, 1),
        "strategy": res.preprocessing_strategy,
        "psm": res.psm_used,
        "passes": res.candidates_evaluated,
        "partial_low_confidence": bool(res.partial_low_confidence),
        "coords_within_bounds": bool(coords_ok),
        "error": res.error,
        "boxes": [w.to_dict() for w in res.words],
    }


def _classify_provenance_tier(fixture_id: str, suite_id: str) -> str:
    if fixture_id.startswith("real_"):
        return "native_real_capture"
    if suite_id in ("suite_b", "suite_c"):
        return "heldout_game_hud_and_ui"
    return "synthetic_dev_mockup"


def _summarize_engine_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not runs:
        return {
            "count": 0,
            "exact_matches": 0,
            "mean_cer": 0.0,
            "mean_wer": 0.0,
            "total_char_errors": 0,
            "total_word_errors": 0,
            "total_missing_lines": 0,
            "total_hallucinated_chars": 0,
            "mean_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "mean_peak_kb": 0.0,
            "all_coords_valid": True,
        }
    lats = [float(r["latency_ms"]) for r in runs]
    return {
        "count": len(runs),
        "exact_matches": sum(1 for r in runs if float(r["cer"]) == 0.0),
        "mean_cer": round(float(np.mean([float(r["cer"]) for r in runs])), 4),
        "mean_wer": round(float(np.mean([float(r["wer"]) for r in runs])), 4),
        "total_char_errors": int(sum(int(r["char_errors"]) for r in runs)),
        "total_word_errors": int(sum(int(r["word_errors"]) for r in runs)),
        "total_missing_lines": int(sum(int(r["missing_lines"]) for r in runs)),
        "total_hallucinated_chars": int(sum(int(r["hallucinated_chars"]) for r in runs)),
        "mean_latency_ms": round(float(np.mean(lats)), 2),
        "p95_latency_ms": round(float(np.percentile(lats, 95.0)), 2),
        "mean_peak_kb": round(float(np.mean([float(r["peak_kb"]) for r in runs])), 2),
        "all_coords_valid": all(bool(r.get("coords_within_bounds", True)) for r in runs),
    }


def run_side_by_side_evaluation(*, include_all_suites: bool = False) -> Dict[str, Any]:
    """
    Execute side-by-side evaluation of `RapidOcrBackend`, `recognize_image_ocr_legacy`,
    `TesseractOcrBackend`, and `recognize_production_ocr` on native-resolution fixtures.
    """
    rapid_backend = RapidOcrBackend()
    tess_backend = TesseractOcrBackend()
    rapid_status = rapid_backend.query_status()
    tess_status = tess_backend.query_status()

    rw_list = build_realworld_heldout_ocr_fixtures()
    ind_list = build_independent_regression_ocr_fixtures()
    dev_list = build_ground_truth_ocr_fixtures()

    if include_all_suites:
        tagged_fixtures: List[Tuple[str, OcrBenchmarkFixture]] = (
            [("suite_c", fx) for fx in rw_list]
            + [("suite_b", fx) for fx in ind_list]
            + [("suite_a", fx) for fx in dev_list]
        )
    else:
        rw_map = {f.fixture_id: f for f in rw_list}
        dev_map = {f.fixture_id: f for f in dev_list}
        ind_map = {f.fixture_id: f for f in ind_list}
        tagged_fixtures = []
        for fid in (
            "unseen_four_pill_game_hud",
            "unseen_cyan_five_buttons_menu",
            "unseen_tall_sidebar_game_list",
            "unseen_vivid_colored_pills_menu",
            "real_win11_explorer_search",
            "real_win11_preview_warning",
            "real_code_python_imports",
            "real_dark_titlebar_compressed",
        ):
            if fid in rw_map:
                tagged_fixtures.append(("suite_c", rw_map[fid]))
        for fid in ("stylized_sign_sell_logs", "small_antialiased_code"):
            if fid in dev_map:
                tagged_fixtures.append(("suite_a", dev_map[fid]))
        for fid in ("new_game_menu", "keep_leading_I"):
            if fid in ind_map:
                tagged_fixtures.append(("suite_b", ind_map[fid]))

    comparisons: List[Dict[str, Any]] = []
    leg_runs: List[Dict[str, Any]] = []
    tess_runs: List[Dict[str, Any]] = []
    rapid_runs: List[Dict[str, Any]] = []
    prod_runs: List[Dict[str, Any]] = []

    for suite_id, fx in tagged_fixtures:
        prov_tier = _classify_provenance_tier(fx.fixture_id, suite_id)

        leg_metrics = _measure_single_run(
            lambda: recognize_image_ocr_legacy(fx.image, language="eng"),
            fx.ground_truth,
        )
        leg_runs.append(leg_metrics)

        tess_metrics = _measure_single_run(
            lambda: tess_backend.recognize(fx.image, language="eng", quality_mode="auto"),
            fx.ground_truth,
        )
        tess_runs.append(tess_metrics)

        prod_metrics = _measure_single_run(
            lambda: recognize_production_ocr(fx.image, language="eng", quality_mode="auto"),
            fx.ground_truth,
        )
        prod_runs.append(prod_metrics)

        rapid_entry: Dict[str, Any] = {
            "available": bool(rapid_status.available),
            "status_reason": rapid_status.reason,
        }
        if rapid_status.available:
            rm = _measure_single_run(
                lambda: rapid_backend.recognize(fx.image, language="eng", quality_mode="auto"),
                fx.ground_truth,
            )
            rapid_entry.update(rm)
            rapid_runs.append(rm)

        comparisons.append(
            {
                "fixture_id": fx.fixture_id,
                "suite_id": suite_id,
                "provenance_tier": prov_tier,
                "category": fx.category,
                "dimensions": f"{fx.image.width}x{fx.image.height}",
                "ground_truth": fx.ground_truth,
                "legacy_tesseract": leg_metrics,
                "region_island_tesseract": tess_metrics,
                "rapidocr_neural": rapid_entry,
                "production_hybrid": prod_metrics,
            }
        )

    # Verify partial-result salvage on simulated noisy 4-pill output ['—<', 'CLOSED']
    w_noise = OcrWordBox("—<", 18, 22, 16, 12, 41.0, 0, 0)
    w_closed = OcrWordBox("CLOSED", 42, 74, 73, 14, 93.0, 1, 0)
    noisy_input = OcrRecognitionResult(
        text="—<\nCLOSED",
        lines=[
            OcrLineBox("—<", 18, 22, 16, 12, 41.0, 0, (w_noise,)),
            OcrLineBox("CLOSED", 42, 74, 73, 14, 93.0, 1, (w_closed,)),
        ],
        words=[w_noise, w_closed],
        source_width=420,
        source_height=118,
    )
    salvaged = filter_and_salvage_partial_ocr_result(noisy_input)
    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource is not None else 0
    rss_mb = float(rss_kb) / (1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0)

    return {
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python_version": sys.version.split()[0],
        "process_peak_rss_mb": round(rss_mb, 2),
        "neural_demonstrated_in_this_run": bool(rapid_status.available and len(rapid_runs) > 0),
        "backends": {
            "rapidocr": rapid_status.to_dict(),
            "tesseract": tess_status.to_dict(),
        },
        "engine_summaries": {
            "legacy_tesseract": _summarize_engine_runs(leg_runs),
            "region_island_tesseract": _summarize_engine_runs(tess_runs),
            "rapidocr_neural": _summarize_engine_runs(rapid_runs) if rapid_runs else {"available": False, "reason": rapid_status.reason},
            "production_hybrid": _summarize_engine_runs(prod_runs),
        },
        "partial_salvage_verification": {
            "raw_input_lines": ["—<", "CLOSED"],
            "salvaged_text": salvaged.text,
            "partial_low_confidence": bool(salvaged.partial_low_confidence),
            "low_confidence_rejected": bool(salvaged.low_confidence_rejected),
            "quality_warning": salvaged.quality_warning,
            "preserved_boxes": [w.to_dict() for w in salvaged.words],
        },
        "diagnostic_preview_evidence": evaluate_diagnostic_preview_evidence(),
        "comparisons": comparisons,
    }


def format_side_by_side_markdown(report: Dict[str, Any]) -> str:
    rapid_stat = report["backends"]["rapidocr"]
    tess_stat = report["backends"]["tesseract"]
    neural_ran = bool(report.get("neural_demonstrated_in_this_run", False))
    s_leg = report["engine_summaries"]["legacy_tesseract"]
    s_tess = report["engine_summaries"]["region_island_tesseract"]
    s_prod = report["engine_summaries"]["production_hybrid"]
    s_rapid = report["engine_summaries"]["rapidocr_neural"]

    lines: List[str] = [
        "# Prismwake v0.2.0 — Side-by-Side OCR Engine Benchmark Report",
        "",
        "## Backend Execution Provenance & Honesty Statement",
        "",
        f"- **Host Environment**: `{report['platform']}` (Python `{report['python_version']}`, Peak Process RSS `{report.get('process_peak_rss_mb', 0.0):.1f} MB`)",
        f"- **RapidOCR Neural Backend (`RapidOcrBackend`)**: `available={rapid_stat['available']}` — {rapid_stat['reason']}",
        f"- **Region-Island Tesseract Backend (`TesseractOcrBackend`)**: `available={tess_stat['available']}` — {tess_stat['reason']}",
        f"- **Was RapidOCR Neural Inference Demonstrated Live in This Run?**: **`{'YES' if neural_ran else 'NO (Tesseract fallback evaluated; run build_windows_oneclick.ps1 or GitHub Actions on Windows to execute live RapidOCR ONNX inference)'}`**",
        "",
        "> **Important Note on Benchmark Claims**: Scores achieved by `TesseractOcrBackend` (`region_island_tesseract`) measure the connected-component white-core / Fisher island + stacked ROI Tesseract fallback pipeline and **must never be cited as RapidOCR neural accuracy**. Live RapidOCR neural accuracy is reported exclusively in the `RapidOCR (ONNX CPU)` column when `neural_demonstrated_in_this_run == True`.",
        "",
        "## Aggregate Side-by-Side Engine Summary (Identical Unscaled Native Images)",
        "",
        "| Engine / Pipeline | Demonstrated Live | Exact Matches | Mean CER | Mean WER | Char Errors | Word Errors | Missed Lines | Hallucinated Chars | Mean Latency | p95 Latency | Mean Peak Heap | Coords Valid |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        f"| **1. Legacy Baseline (`recognize_image_ocr_legacy`)** | Yes | {s_leg['exact_matches']} / {s_leg['count']} | {s_leg['mean_cer']*100:.2f}% | {s_leg['mean_wer']*100:.2f}% | {s_leg['total_char_errors']} | {s_leg['total_word_errors']} | {s_leg['total_missing_lines']} | {s_leg['total_hallucinated_chars']} | {s_leg['mean_latency_ms']:.1f} ms | {s_leg['p95_latency_ms']:.1f} ms | {s_leg['mean_peak_kb']:.1f} KB | `{s_leg['all_coords_valid']}` |",
        f"| **2. Region-Island Tesseract (`TesseractOcrBackend`)** | Yes | **{s_tess['exact_matches']} / {s_tess['count']}** | **{s_tess['mean_cer']*100:.2f}%** | **{s_tess['mean_wer']*100:.2f}%** | {s_tess['total_char_errors']} | {s_tess['total_word_errors']} | {s_tess['total_missing_lines']} | {s_tess['total_hallucinated_chars']} | {s_tess['mean_latency_ms']:.1f} ms | {s_tess['p95_latency_ms']:.1f} ms | {s_tess['mean_peak_kb']:.1f} KB | `{s_tess['all_coords_valid']}` |",
    ]
    if neural_ran and isinstance(s_rapid, dict) and s_rapid.get("count", 0) > 0:
        lines.append(
            f"| **3. RapidOCR Neural (`RapidOcrBackend` ONNX CPU)** | **Yes** | **{s_rapid['exact_matches']} / {s_rapid['count']}** | **{s_rapid['mean_cer']*100:.2f}%** | **{s_rapid['mean_wer']*100:.2f}%** | {s_rapid['total_char_errors']} | {s_rapid['total_word_errors']} | {s_rapid['total_missing_lines']} | {s_rapid['total_hallucinated_chars']} | {s_rapid['mean_latency_ms']:.1f} ms | {s_rapid['p95_latency_ms']:.1f} ms | {s_rapid['mean_peak_kb']:.1f} KB | `{s_rapid['all_coords_valid']}` |"
        )
    else:
        lines.append(
            f"| **3. RapidOCR Neural (`RapidOcrBackend` ONNX CPU)** | **No (Not installed in offline Linux VM)** | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
        )
    lines.append(
        f"| **4. Production Hybrid Service (`recognize_production_ocr`)** | Yes (`{'RapidOCR primary' if neural_ran else 'Tesseract fallback'}`) | **{s_prod['exact_matches']} / {s_prod['count']}** | **{s_prod['mean_cer']*100:.2f}%** | **{s_prod['mean_wer']*100:.2f}%** | {s_prod['total_char_errors']} | {s_prod['total_word_errors']} | {s_prod['total_missing_lines']} | {s_prod['total_hallucinated_chars']} | {s_prod['mean_latency_ms']:.1f} ms | {s_prod['p95_latency_ms']:.1f} ms | {s_prod['mean_peak_kb']:.1f} KB | `{s_prod['all_coords_valid']}` |"
    )
    lines.append("")

    for tier_key, tier_title in (
        ("native_real_capture", "Tier 1 — Native Unmodified Real Screenshot Crops (`native_real_capture`)"),
        ("heldout_game_hud_and_ui", "Tier 2 — Held-Out Game HUDs, Menus, Tables & UI (`heldout_game_hud_and_ui`)"),
        ("synthetic_dev_mockup", "Tier 3 — Synthetic Development Mockups (`synthetic_dev_mockup`)"),
    ):
        tier_items = [c for c in report["comparisons"] if c.get("provenance_tier") == tier_key]
        if not tier_items:
            continue
        lines.extend([
            f"## {tier_title}",
            "",
            "| Fixture ID | Size | Legacy CER / WER | Region-Island Tesseract CER / WER (Errs, Miss, Halluc, ms) | RapidOCR Neural CER / WER (Errs, Miss, Halluc, ms) | Production Active Backend |",
            "| :--- | :---: | :---: | :---: | :---: | :---: |",
        ])
        for c in tier_items:
            lg = c["legacy_tesseract"]
            ts = c["region_island_tesseract"]
            rp = c["rapidocr_neural"]
            pr = c["production_hybrid"]
            if rp.get("available"):
                rp_cell = (
                    f"**{rp['cer']*100:.1f}% / {rp['wer']*100:.1f}%** "
                    f"({rp['char_errors']}c, {rp['missing_lines']}m, {rp['hallucinated_chars']}h, {rp['latency_ms']:.0f}ms)"
                )
            else:
                rp_cell = "`Unavailable in offline VM`"
            lines.append(
                f"| `{c['fixture_id']}` | `{c['dimensions']}` | {lg['cer']*100:.1f}% / {lg['wer']*100:.1f}% | "
                f"**{ts['cer']*100:.1f}% / {ts['wer']*100:.1f}%** ({ts['char_errors']}c, {ts['missing_lines']}m, {ts['hallucinated_chars']}h, {ts['latency_ms']:.0f}ms) | "
                f"{rp_cell} | `{pr['backend_selected']}` |"
            )
        lines.append("")

    diag_ev = report.get("diagnostic_preview_evidence", [])
    if diag_ev:
        lines.extend([
            "## Tier 4 — Diagnostic Preview-Widget Crops (`preview_crop_diagnostic`, Excluded from Native Accuracy Totals)",
            "",
            "These two files (`diagnostic_only_*.png`) were cropped from a downscaled OCR-dialog preview widget with cyan overlay boxes burned into the pixels. They are evaluated separately for diagnostic transparency:",
            "",
            "| Preview Crop File | Dimensions | Strategy & PSM | Mean Conf | Rejected as Low-Conf | Output / Diagnostic Warning |",
            "| :--- | :---: | :---: | :---: | :---: | :--- |",
        ])
        for ev in diag_ev:
            out_s = repr(ev["recognized_text"]) if ev["recognized_text"] else f"REJECTED ({ev['quality_warning'][:68]}...)"
            lines.append(
                f"| `{ev['file']}` | `{ev['dimensions']}` | `{ev['strategy']}` (PSM {ev['psm']}) | "
                f"{ev['mean_confidence']:.1f}% | `{ev['low_confidence_rejected']}` | `{out_s}` |"
            )
        lines.append("")

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Prismwake v0.2.0 side-by-side OCR evaluation.")
    parser.add_argument("--require-neural", action="store_true", help="Fail if RapidOCR neural backend is not available and functional.")
    parser.add_argument("--all-suites", action="store_true", help="Evaluate all 31 fixtures across Suites A, B, and C.")
    parser.add_argument("--output-json", default="", help="Optional path to write JSON evaluation report.")
    parser.add_argument("--output-md", default="", help="Optional path to write Markdown evaluation report.")
    args = parser.parse_args(argv)

    report = run_side_by_side_evaluation(include_all_suites=args.all_suites or bool(args.output_md))
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(format_side_by_side_markdown(report), encoding="utf-8")
    if not args.output_json and not args.output_md:
        print(json.dumps(report, indent=2))

    if args.require_neural and not report.get("neural_demonstrated_in_this_run", False):
        print(
            f"ERROR: --require-neural was specified, but RapidOCR neural backend was not available: "
            f"{report['backends']['rapidocr']['reason']}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
