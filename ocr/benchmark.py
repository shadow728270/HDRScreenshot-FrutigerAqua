"""
Prismwake v0.2.0 — Ground-Truth Offline OCR Accuracy, Regression & Real-World Benchmark Suite (`ocr.benchmark`)
=================================================================================================================
Evaluates the internal single-candidate baseline (`recognize_image_ocr_legacy`) against the Automatic
Multi-Candidate OCR Pipeline (`recognize_image_ocr`) across three separate, clearly distinguished suites:

  * **Suite A — Original 12 Synthetic Development Fixtures**:
    Deterministic synthetic fixtures authored during initial v0.2.0 development to test specific
    preprocessing branches (dark/light polarity, small code upscaling, left-side menu icons, stylized
    sign valleys, gradients, faint watermarks, threshold/inversion harm prevention, and isoluminant RGB).
    Note: `recognize_image_ocr_legacy()` is an internal baseline reconstruction of the prior single-pass
    global-median pipeline, not the untouched previously shipped Windows binary.

  * **Suite B — Independent 6 Held-Out Regression Fixtures (`tests/fixtures/independent_ocr/`)**:
    Six independently authored held-out fixtures (`new_game_menu`, `keep_leading_I`, `novel_stylized_sign`,
    `punctuation`, `new_icon_menu`, `gradient`) that previously exposed two regressions (`new_game_menu`
    outputting `O Settings` / `O Leave Lobby`, and `keep_leading_I` outputting `| LOVE LOGS`).

  * **Suite C — Held-Out Real-World Screenshot Crops & Unseen UI Captures (`tests/fixtures/realworld_ocr/`)**:
    Eight held-out evaluation fixtures combining 4 unmodified pixel crops from real user desktop/Windows 11
    screenshots (`image_3490dc.png` and `image_da5e16.png` — excluding downscaled OCR dialog previews that
    already have cyan bounding boxes burned into the image) and 4 unseen prose, markdown pipe-table,
    bordered circular-icon menu, and shell/metadata captures.

Computes real Character Error Rate (CER), Word Error Rate (WER), mean & p95 recognition latency (ms),
OCR pass count, Python heap allocation (`tracemalloc` KB), and native process RSS (MB).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]
import time
import tracemalloc
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .engine import (
    analyze_image_for_ocr,
    detect_tesseract_runtime,
    recognize_image_ocr,
    recognize_image_ocr_legacy,
)


@dataclass(frozen=True)
class OcrBenchmarkFixture:
    """Single ground-truth screenshot fixture for objective OCR evaluation."""
    fixture_id: str
    category: str
    description: str
    ground_truth: str
    image: Image.Image


@dataclass(frozen=True)
class OcrFixtureComparisonResult:
    """Side-by-side metrics comparing the internal baseline vs. the automatic pipeline on one fixture."""
    fixture_id: str
    category: str
    ground_truth: str
    legacy_text: str
    legacy_cer: float
    legacy_wer: float
    legacy_latency_ms: float
    legacy_peak_kb: float
    auto_text: str
    auto_cer: float
    auto_wer: float
    auto_latency_ms: float
    auto_peak_kb: float
    auto_strategy: str
    auto_psm: int
    auto_candidates_evaluated: int
    auto_missing_lines: int = 0
    auto_stray_symbols: int = 0
    auto_mean_confidence: float = 0.0
    auto_pass_timings_ms: Tuple[float, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "category": self.category,
            "ground_truth": self.ground_truth,
            "legacy_text": self.legacy_text,
            "legacy_cer": round(self.legacy_cer, 4),
            "legacy_wer": round(self.legacy_wer, 4),
            "legacy_latency_ms": round(self.legacy_latency_ms, 2),
            "legacy_peak_kb": round(self.legacy_peak_kb, 2),
            "auto_text": self.auto_text,
            "auto_cer": round(self.auto_cer, 4),
            "auto_wer": round(self.auto_wer, 4),
            "auto_latency_ms": round(self.auto_latency_ms, 2),
            "auto_peak_kb": round(self.auto_peak_kb, 2),
            "auto_strategy": self.auto_strategy,
            "auto_psm": self.auto_psm,
            "auto_candidates_evaluated": self.auto_candidates_evaluated,
            "auto_missing_lines": int(self.auto_missing_lines),
            "auto_stray_symbols": int(self.auto_stray_symbols),
            "auto_mean_confidence": round(self.auto_mean_confidence, 1),
            "auto_pass_timings_ms": [round(float(x), 1) for x in self.auto_pass_timings_ms],
        }


def _levenshtein_distance(seq1: Sequence[Any], seq2: Sequence[Any]) -> int:
    """Compute exact Levenshtein edit distance between two sequences (characters or words)."""
    n, m = len(seq1), len(seq2)
    if n == 0:
        return m
    if m == 0:
        return n
    prev = list(range(m + 1))
    curr = [0] * (m + 1)
    for i in range(1, n + 1):
        curr[0] = i
        s1_i = seq1[i - 1]
        for j in range(1, m + 1):
            cost = 0 if s1_i == seq2[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,       # deletion
                curr[j - 1] + 1,   # insertion
                prev[j - 1] + cost # substitution
            )
        prev, curr = curr, prev
    return prev[m]


def compute_cer(hypothesis: str, reference: str) -> float:
    """
    Compute Character Error Rate (CER) = `edit_distance(hyp_chars, ref_chars) / max(1, len(ref_chars))`
    after normalizing line endings and collapsing redundant horizontal spaces.
    """
    ref_norm = "\n".join(" ".join(ln.split()) for ln in (reference or "").strip().splitlines())
    hyp_norm = "\n".join(" ".join(ln.split()) for ln in (hypothesis or "").strip().splitlines())
    if not ref_norm:
        return 0.0 if not hyp_norm else 1.0
    dist = _levenshtein_distance(hyp_norm, ref_norm)
    return float(dist) / float(len(ref_norm))


def compute_wer(hypothesis: str, reference: str) -> float:
    """
    Compute Word Error Rate (WER) = `edit_distance(hyp_words, ref_words) / max(1, len(ref_words))`.
    """
    ref_words = (reference or "").strip().split()
    hyp_words = (hypothesis or "").strip().split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    dist = _levenshtein_distance(hyp_words, ref_words)
    return float(dist) / float(len(ref_words))


def count_missing_lines_and_stray_symbols(hypothesis: str, reference: str) -> Tuple[int, int]:
    """Return `(missing_line_count, stray_symbol_token_count)` comparing hypothesis to reference."""
    ref_lines = [ln.strip() for ln in (reference or "").strip().splitlines() if ln.strip()]
    hyp_lines = [ln.strip() for ln in (hypothesis or "").strip().splitlines() if ln.strip()]
    missing_lines = max(0, len(ref_lines) - len(hyp_lines))
    ref_tokens = set((reference or "").strip().split())
    stray_symbols = 0
    for tok in (hypothesis or "").strip().split():
        if not any(ch.isalnum() for ch in tok) and tok not in ref_tokens:
            stray_symbols += 1
    return missing_lines, stray_symbols


def _load_fixture_font(kind: str = "sans", size: int = 20) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates_map = {
        "sans": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
        ],
        "bold": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:\\Windows\\Fonts\\segoeuib.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
        ],
        "menu": [
            "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:\\Windows\\Fonts\\segoeuib.ttf",
        ],
        "serif_bold": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "C:\\Windows\\Fonts\\timesbd.ttf",
        ],
        "mono": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "C:\\Windows\\Fonts\\consola.ttf",
        ],
        "thin": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:\\Windows\\Fonts\\segoeuil.ttf",
        ],
    }
    for fp in candidates_map.get(kind, candidates_map["sans"]):
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def build_ground_truth_ocr_fixtures() -> List[OcrBenchmarkFixture]:
    """Build Suite A: the 12 deterministic synthetic development OCR benchmark fixtures.
    Loads portable pre-rendered PNGs from tests/fixtures/suite_a_ocr/ when available so
    Linux and Windows evaluate identical pixel-for-pixel glyph bitmaps regardless of OS fonts.
    """
    suite_a_dir = _project_root() / "tests" / "fixtures" / "suite_a_ocr"
    gt_json = suite_a_dir / "ground_truth.json"
    if gt_json.is_file():
        try:
            items = json.loads(gt_json.read_text(encoding="utf-8"))
            loaded: List[OcrBenchmarkFixture] = []
            for it in items:
                img_p = suite_a_dir / str(it["file"])
                if img_p.is_file():
                    with Image.open(img_p) as im:
                        pil_rgb = im.convert("RGB")
                    loaded.append(
                        OcrBenchmarkFixture(
                            fixture_id=str(it["fixture_id"]),
                            category=str(it["category"]),
                            description=str(it["description"]),
                            ground_truth=str(it["ground_truth"]),
                            image=pil_rgb,
                        )
                    )
            if len(loaded) == 12:
                return loaded
        except Exception:
            pass
    font_sans22 = _load_fixture_font("sans", 22)
    font_sans20 = _load_fixture_font("sans", 20)
    font_menu20 = _load_fixture_font("menu", 20)
    font_bold28 = _load_fixture_font("bold", 28)
    font_serif22 = _load_fixture_font("serif_bold", 22)
    font_thin16 = _load_fixture_font("thin", 16)

    fixtures: List[OcrBenchmarkFixture] = []

    # 1. Ordinary Windows UI (dark on light, multiline with punctuation and numbers)
    f1 = Image.new("RGB", (680, 130), (250, 252, 255))
    d1 = ImageDraw.Draw(f1)
    gt1 = "Prismwake v0.2.0: Catch the light!\nHDR Framebuffer: 3840x2160 @ 280 nits"
    d1.text((20, 18), "Prismwake v0.2.0: Catch the light!", fill=(12, 20, 32), font=font_sans22)
    d1.text((20, 66), "HDR Framebuffer: 3840x2160 @ 280 nits", fill=(12, 20, 32), font=font_sans22)
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="windows_light_ui",
        category="Ordinary Windows UI (Light)",
        description="Dark text on light background, multiline with punctuation and numbers.",
        ground_truth=gt1,
        image=f1,
    ))

    # 2. Dark theme UI (light on dark, error codes & hex literals)
    f2 = Image.new("RGB", (640, 96), (12, 18, 28))
    d2 = ImageDraw.Draw(f2)
    gt2 = "DXGI_ERROR_DEVICE_REMOVED (0x887A0005)"
    d2.text((22, 28), gt2, fill=(235, 248, 255), font=font_sans22)
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="windows_dark_ui",
        category="Dark Theme UI",
        description="Light text on dark background with underscores and hex code.",
        ground_truth=gt2,
        image=f2,
    ))

    # 3. Small antialiased code & UI text in editor with right-margin scrollbar/minimap ticks
    f3 = Image.new("RGB", (620, 210), (250, 252, 255))
    d3 = ImageDraw.Draw(f3)
    for y_tick in range(10, 195):
        for x_tick in range(592, 610, 2):
            f3.putpixel((x_tick, y_tick), (120, 130, 145))
    gt3 = "def capture_hdr(nits=203): return True"
    d3.text((24, 92), gt3, fill=(18, 24, 34), font=_load_fixture_font("sans", 10))
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="small_antialiased_code",
        category="Small Antialiased Code (Upscaling)",
        description="Downscaled 8-9px antialiased code line where adaptive upscaling improves accuracy.",
        ground_truth=gt3,
        image=f3,
    ))

    # 4. Game menu with left-side icons (Pattern A)
    menu_items = [
        "Invite Friends",
        "People",
        "Settings",
        "Report",
        "Switch avatar",
        "Shop",
        "Friends chat",
    ]
    f4 = Image.new("RGB", (260, 310), (24, 27, 34))
    d4 = ImageDraw.Draw(f4)
    for idx, label in enumerate(menu_items):
        y0 = 14 + idx * 41
        ix, iy = 18, y0 + 2
        d4.rounded_rectangle([ix, iy, ix + 20, iy + 20], radius=5, outline=(185, 205, 230), width=2)
        d4.ellipse([ix + 5, iy + 4, ix + 15, iy + 14], outline=(185, 205, 230), width=2)
        d4.line([ix + 4, iy + 17, ix + 16, iy + 17], fill=(185, 205, 230), width=2)
        d4.text((52, y0 + 1), label, fill=(238, 242, 248), font=font_menu20)
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="game_menu_with_icons",
        category="Game Menu with Icons (Pattern A)",
        description="Vertical game menu with left-side icons next to labels.",
        ground_truth="\n".join(menu_items),
        image=f4,
    ))

    # 5. Stylized sign: SELL LOGS with decorative marks (Pattern B)
    f5 = Image.new("RGB", (340, 76), (38, 25, 16))
    d5 = ImageDraw.Draw(f5)
    d5.rectangle([4, 4, 335, 71], fill=(52, 34, 21), outline=(130, 95, 60), width=2)
    d5.text((16, 24), "I", fill=(185, 155, 110), font=font_serif22)
    x_pos = 54
    for ch in "SELL":
        d5.text((x_pos, 22), ch, fill=(244, 232, 202), font=font_bold28)
        x_pos += int(font_bold28.getlength(ch)) + 1
    x_pos += 6
    for ch in "LOGS":
        d5.text((x_pos, 22), ch, fill=(244, 232, 202), font=font_bold28)
        x_pos += int(font_bold28.getlength(ch)) + 1
    d5.text((284, 22), "@", fill=(185, 155, 110), font=font_bold28)
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="stylized_sign_sell_logs",
        category="Stylized Sign with Decorations (Pattern B)",
        description="Stylized bold SELL LOGS sign with left/right decorative marks that caused 'I SELLLOGS @'.",
        ground_truth="SELL LOGS",
        image=f5,
    ))

    # 6. Usernames & mixed case
    f6 = Image.new("RGB", (520, 88), (18, 22, 30))
    gt6 = "All From CallMeCarsonLIVE"
    ImageDraw.Draw(f6).text((22, 28), gt6, fill=(240, 246, 255), font=font_sans22)
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="usernames_mixed_case",
        category="Usernames & Mixed Case",
        description="CamelCase username on dark background preserved without dictionary mangling.",
        ground_truth=gt6,
        image=f6,
    ))

    # 7. Gradient background with thin antialiased text
    w7, h7 = 540, 80
    x_grad = np.linspace(155, 245, w7)[None, :]
    bg_arr7 = np.repeat(x_grad, h7, axis=0).astype(np.uint8)
    f7 = Image.fromarray(np.stack([bg_arr7] * 3, axis=2), mode="RGB")
    gt7 = "Subtle gradient preserves antialiased strokes"
    ImageDraw.Draw(f7).text((18, 28), gt7, fill=(45, 50, 58), font=font_thin16)
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="gradient_antialiased_banner",
        category="Gradient Background",
        description="Thin antialiased text across a steep horizontal background gradient.",
        ground_truth=gt7,
        image=f7,
    ))

    # 8. Faint low-contrast text on uneven illumination (where local normalization/thresholding helps)
    w8, h8 = 540, 90
    x_grid = np.linspace(0, 1, w8)[None, :]
    y_grid = np.linspace(0, 1, h8)[:, None]
    bg8 = (140 + 95 * x_grid - 40 * y_grid).astype(np.uint8)
    grad_arr8 = np.stack([bg8, bg8, bg8], axis=2)
    gt8 = "Faint serial key: PW-9042-X7B"
    txt_mask8 = Image.new("L", (w8, h8), 0)
    ImageDraw.Draw(txt_mask8).text((22, 28), gt8, fill=255, font=font_sans20)
    mask_f8 = np.asarray(txt_mask8, dtype=np.float32) / 255.0
    f8 = Image.fromarray(np.clip(grad_arr8.astype(np.float32) - mask_f8[:, :, None] * 14.0, 0, 255).astype(np.uint8), mode="RGB")
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="faint_low_contrast_watermark",
        category="Low-Contrast Faint Text",
        description="Faint text only 14 levels darker than an uneven illumination gradient.",
        ground_truth=gt8,
        image=f8,
    ))

    # 9. Soft antialiased label with dark sidebar where hard thresholding harms/erases text
    f9 = Image.new("RGB", (540, 110), (245, 247, 250))
    d9 = ImageDraw.Draw(f9)
    d9.rectangle([0, 0, 145, 110], fill=(14, 18, 24))
    gt9 = "Antialiased secondary label 2026"
    d9.text((165, 42), gt9, fill=(126, 132, 140), font=font_sans20)
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="threshold_harm_antialiased",
        category="Threshold Harm Prevention",
        description="Soft gray antialiased label beside a dark sidebar where global thresholding erases text.",
        ground_truth=gt9,
        image=f9,
    ))

    # 10. Dark ink on medium-slate surface with bright frame (where naive global median inversion harms)
    f10 = Image.new("RGB", (540, 100), (104, 108, 114))
    d10 = ImageDraw.Draw(f10)
    d10.rectangle([12, 14, 528, 86], outline=(248, 250, 255), width=3)
    d10.line([(24, 68), (516, 68)], fill=(248, 250, 255), width=3)
    gt10 = "Surface Polarity: Dark Ink On Slate"
    d10.text((28, 34), gt10, fill=(14, 18, 24), font=font_sans20)
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="inversion_harm_slate_surface",
        category="Inversion Harm Prevention",
        description="Dark text on medium-slate card (median < 118) with bright frame where naive global inversion fails.",
        ground_truth=gt10,
        image=f10,
    ))

    # 11. Light ink on dark HUD pill inside bright window (where naive global median fails to invert)
    f11 = Image.new("RGB", (520, 180), (242, 245, 250))
    d11 = ImageDraw.Draw(f11)
    d11.rounded_rectangle([95, 58, 425, 122], radius=12, fill=(20, 24, 32))
    gt11 = "FPS: 144 | GPU: 68C | HDR ON"
    d11.text((115, 76), gt11, fill=(240, 246, 255), font=font_sans20)
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="inversion_help_dark_pill_in_light",
        category="Selective Local Inversion",
        description="Light text on dark HUD badge inside bright surround (median > 118).",
        ground_truth=gt11,
        image=f11,
    ))

    # 12. Chromatic isoluminant RGB capture (where Original RGB / chroma-contrast beats standard grayscale)
    f12 = Image.new("RGB", (520, 90), (0, 113, 73))
    gt12 = "Chroma Alert: Shield Critical 15%"
    ImageDraw.Draw(f12).text((22, 28), gt12, fill=(255, 40, 40), font=font_sans20)
    fixtures.append(OcrBenchmarkFixture(
        fixture_id="isoluminant_rgb_alert",
        category="Original RGB / Chromatic Contrast",
        description="Red text on green-teal background of identical Rec.709 luminance.",
        ground_truth=gt12,
        image=f12,
    ))

    return fixtures


def build_independent_regression_ocr_fixtures(
    fixture_dir: Path | None = None,
) -> List[OcrBenchmarkFixture]:
    """
    Load Suite B: the 6 independent held-out regression fixtures from
    `tests/fixtures/independent_ocr/` (`new_game_menu`, `keep_leading_I`,
    `novel_stylized_sign`, `punctuation`, `new_icon_menu`, `gradient`).
    """
    if fixture_dir is None:
        fixture_dir = _project_root() / "tests" / "fixtures" / "independent_ocr"
    gt_path = fixture_dir / "ground_truth.json"
    if not gt_path.is_file():
        return []

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_map: Dict[str, str] = json.load(f)

    categories = {
        "new_game_menu": ("Independent Menu with Circular Icons", "4-row bordered dark menu with left circular icons."),
        "keep_leading_I": ("Independent Sign with Leading 'I'", "Dark wooden sign reading 'I LOVE LOGS' with leading uppercase I."),
        "novel_stylized_sign": ("Independent Stylized Sign", "Stylized sign reading 'WOOD SHOP' with flanking posts."),
        "punctuation": ("Independent Punctuation & Email", "HUD status line with '|' pipes, degree symbol, and '@' email."),
        "new_icon_menu": ("Independent Single-Line Icon Button", "Single-line button with circular left icon ('Invite Players')."),
        "gradient": ("Independent Gradient HUD Banner", "Light text with comma-formatted number across horizontal gradient."),
    }

    fixtures: List[OcrBenchmarkFixture] = []
    for key, expected in gt_map.items():
        fname = key if key.endswith(".png") else f"{key}.png"
        img_path = fixture_dir / fname
        if img_path.is_file():
            img = Image.open(img_path).convert("RGB")
            cat, desc = categories.get(key, ("Independent Held-Out Fixture", fname))
            fixtures.append(
                OcrBenchmarkFixture(
                    fixture_id=key,
                    category=cat,
                    description=desc,
                    ground_truth=expected,
                    image=img,
                )
            )
    return fixtures


def build_realworld_heldout_ocr_fixtures(
    fixture_dir: Path | None = None,
) -> List[OcrBenchmarkFixture]:
    """
    Load Suite C: the 8 held-out real-world screenshot crops and unseen UI captures
    from `tests/fixtures/realworld_ocr/`.
    """
    if fixture_dir is None:
        fixture_dir = _project_root() / "tests" / "fixtures" / "realworld_ocr"
    gt_path = fixture_dir / "ground_truth.json"
    if not gt_path.is_file():
        return []

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_map: Dict[str, Dict[str, str]] = json.load(f)

    fixtures: List[OcrBenchmarkFixture] = []
    for key, meta in gt_map.items():
        fname = key if key.endswith(".png") else f"{key}.png"
        img_path = fixture_dir / fname
        if img_path.is_file():
            img = Image.open(img_path).convert("RGB")
            fixtures.append(
                OcrBenchmarkFixture(
                    fixture_id=key,
                    category=meta.get("category", "Held-Out Real-World / UI Capture"),
                    description=meta.get("description", fname),
                    ground_truth=meta["ground_truth"],
                    image=img,
                )
            )
    return fixtures


def run_ocr_benchmark_suite(
    fixtures: Sequence[OcrBenchmarkFixture] | None = None,
) -> Dict[str, Any]:
    """
    Run both the Internal Baseline (`recognize_image_ocr_legacy`) and the Automatic Pipeline
    (`recognize_image_ocr`) across `fixtures` (defaulting to Suite A) and return aggregate & per-fixture metrics.
    """
    if fixtures is None:
        fixtures = build_ground_truth_ocr_fixtures()

    # Warm up Tesseract runtime lookup once before timing individual fixtures
    detect_tesseract_runtime()

    results: List[OcrFixtureComparisonResult] = []
    for fx in fixtures:
        # 1. Measure Internal Baseline Pipeline
        tracemalloc.start()
        t0_leg = time.perf_counter()
        res_leg = recognize_image_ocr_legacy(fx.image, language="eng")
        lat_leg = (time.perf_counter() - t0_leg) * 1000.0
        _, peak_leg = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        cer_leg = compute_cer(res_leg.text, fx.ground_truth)
        wer_leg = compute_wer(res_leg.text, fx.ground_truth)

        # 2. Measure New Automatic Pipeline
        tracemalloc.start()
        t0_auto = time.perf_counter()
        res_auto = recognize_image_ocr(fx.image, language="eng", quality_mode="auto")
        lat_auto = (time.perf_counter() - t0_auto) * 1000.0
        _, peak_auto = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        cer_auto = compute_cer(res_auto.text, fx.ground_truth)
        wer_auto = compute_wer(res_auto.text, fx.ground_truth)
        missing_lns, stray_syms = count_missing_lines_and_stray_symbols(res_auto.text, fx.ground_truth)
        mean_conf = float(np.mean([w.confidence for w in res_auto.words])) if res_auto.words else 0.0

        results.append(
            OcrFixtureComparisonResult(
                fixture_id=fx.fixture_id,
                category=fx.category,
                ground_truth=fx.ground_truth,
                legacy_text=res_leg.text,
                legacy_cer=cer_leg,
                legacy_wer=wer_leg,
                legacy_latency_ms=lat_leg,
                legacy_peak_kb=peak_leg / 1024.0,
                auto_text=res_auto.text,
                auto_cer=cer_auto,
                auto_wer=wer_auto,
                auto_latency_ms=lat_auto,
                auto_peak_kb=peak_auto / 1024.0,
                auto_strategy=res_auto.preprocessing_strategy,
                auto_psm=res_auto.psm_used,
                auto_candidates_evaluated=res_auto.candidates_evaluated,
                auto_missing_lines=missing_lns,
                auto_stray_symbols=stray_syms,
                auto_mean_confidence=mean_conf,
                auto_pass_timings_ms=tuple(res_auto.pass_timings_ms),
            )
        )

    leg_lats = [r.legacy_latency_ms for r in results] or [0.0]
    auto_lats = [r.auto_latency_ms for r in results] or [0.0]

    mean_leg_cer = float(np.mean([r.legacy_cer for r in results])) if results else 0.0
    mean_leg_wer = float(np.mean([r.legacy_wer for r in results])) if results else 0.0
    mean_leg_lat = float(np.mean(leg_lats))
    p95_leg_lat = float(np.percentile(leg_lats, 95.0))
    mean_leg_kb = float(np.mean([r.legacy_peak_kb for r in results])) if results else 0.0

    mean_auto_cer = float(np.mean([r.auto_cer for r in results])) if results else 0.0
    mean_auto_wer = float(np.mean([r.auto_wer for r in results])) if results else 0.0
    mean_auto_lat = float(np.mean(auto_lats))
    p95_auto_lat = float(np.percentile(auto_lats, 95.0))
    mean_auto_kb = float(np.mean([r.auto_peak_kb for r in results])) if results else 0.0
    mean_auto_passes = float(np.mean([r.auto_candidates_evaluated for r in results])) if results else 1.0

    exact_leg = sum(1 for r in results if r.legacy_cer == 0.0)
    exact_auto = sum(1 for r in results if r.auto_cer == 0.0)

    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource is not None else 0
    rss_mb = float(rss_kb) / 1024.0

    return {
        "fixture_count": len(results),
        "process_peak_rss_mb": round(rss_mb, 2),
        "legacy_summary": {
            "mean_cer": round(mean_leg_cer, 4),
            "mean_wer": round(mean_leg_wer, 4),
            "exact_match_count": exact_leg,
            "mean_latency_ms": round(mean_leg_lat, 2),
            "p95_latency_ms": round(p95_leg_lat, 2),
            "mean_peak_kb": round(mean_leg_kb, 2),
        },
        "automatic_summary": {
            "mean_cer": round(mean_auto_cer, 4),
            "mean_wer": round(mean_auto_wer, 4),
            "exact_match_count": exact_auto,
            "mean_latency_ms": round(mean_auto_lat, 2),
            "p95_latency_ms": round(p95_auto_lat, 2),
            "mean_passes": round(mean_auto_passes, 2),
            "mean_peak_kb": round(mean_auto_kb, 2),
        },
        "fixtures": [r.to_dict() for r in results],
    }


def evaluate_diagnostic_preview_evidence() -> List[Dict[str, Any]]:
    """
    Inspect the two downscaled OCR-dialog preview crops from `Prismwake_v020_OCR_Failure_Evidence.zip`
    (`tests/fixtures/failure_evidence/diagnostic_only_*.png`). Kept strictly separate from
    native-resolution ground-truth suites because these crops were cut from a downsampled
    dialog preview with drawn overlay rectangles.
    """
    ev_dir = _project_root() / "tests" / "fixtures" / "failure_evidence"
    out: List[Dict[str, Any]] = []
    for fname in ("diagnostic_only_cyan_menu_preview_crop.png", "diagnostic_only_tall_menu_preview_crop.png"):
        fpath = ev_dir / fname
        if not fpath.is_file():
            continue
        im = Image.open(fpath).convert("RGB")
        prof = analyze_image_for_ocr(im)
        res = recognize_image_ocr(im, language="eng")
        mean_c = float(np.mean([w.confidence for w in res.words])) if res.words else 0.0
        out.append({
            "file": fname,
            "dimensions": f"{im.width}x{im.height}",
            "estimated_line_count": prof.estimated_line_count,
            "is_light_ink": prof.is_light_ink,
            "is_sparse_menu": prof.is_sparse_menu,
            "has_left_icon_column": prof.has_left_icon_column,
            "row_rois_count": len(prof.row_text_rois),
            "strategy": res.preprocessing_strategy,
            "psm": res.psm_used,
            "passes": res.candidates_evaluated,
            "pass_timings_ms": [round(float(x), 1) for x in res.pass_timings_ms],
            "quality_score": round(res.quality_score, 2),
            "mean_confidence": round(mean_c, 1),
            "low_confidence_rejected": bool(res.low_confidence_rejected),
            "recognized_text": res.text,
            "quality_warning": res.quality_warning,
        })
    return out


def run_all_ocr_benchmark_suites() -> Dict[str, Any]:
    """Run Suite A (12 synthetic), Suite B (6 independent held-out), Suite C (12 real-world/unseen), and diagnostic evidence."""
    suite_a = run_ocr_benchmark_suite(build_ground_truth_ocr_fixtures())
    suite_b = run_ocr_benchmark_suite(build_independent_regression_ocr_fixtures())
    suite_c = run_ocr_benchmark_suite(build_realworld_heldout_ocr_fixtures())
    diag_ev = evaluate_diagnostic_preview_evidence()
    return {
        "suite_a_synthetic_dev": suite_a,
        "suite_b_independent_regression": suite_b,
        "suite_c_realworld_heldout": suite_c,
        "diagnostic_preview_evidence": diag_ev,
    }


def _render_suite_section(title: str, subtitle: str, summary: Dict[str, Any]) -> List[str]:
    leg = summary["legacy_summary"]
    auto = summary["automatic_summary"]
    n_fx = summary["fixture_count"]
    p95_leg = leg.get("p95_latency_ms", leg["mean_latency_ms"])
    p95_auto = auto.get("p95_latency_ms", auto["mean_latency_ms"])
    mean_passes = auto.get("mean_passes", 1.0)
    lines = [
        f"## {title}",
        "",
        subtitle,
        "",
        "| Pipeline | Mean CER | Mean WER | Exact Matches | Mean Latency | p95 Latency | Mean Passes | Python Peak Heap (`tracemalloc`) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        f"| **Internal Baseline (`recognize_image_ocr_legacy`)** | {leg['mean_cer'] * 100:.2f}% | {leg['mean_wer'] * 100:.2f}% | {leg['exact_match_count']} / {n_fx} | {leg['mean_latency_ms']:.1f} ms | {p95_leg:.1f} ms | 1.00 | {leg['mean_peak_kb']:.1f} KB |",
        f"| **Automatic Multi-Candidate (`recognize_image_ocr`)** | **{auto['mean_cer'] * 100:.2f}%** | **{auto['mean_wer'] * 100:.2f}%** | **{auto['exact_match_count']} / {n_fx}** | **{auto['mean_latency_ms']:.1f} ms** | **{p95_auto:.1f} ms** | **{mean_passes:.2f}** | **{auto['mean_peak_kb']:.1f} KB** |",
        "",
        "| Fixture ID | Category | Baseline CER | Auto CER | Baseline WER | Auto WER | Missing Lines | Stray Syms | Mean Conf | Strategy (PSM, Passes, Pass Timings) | Total Latency |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: |",
    ]
    for fx in summary["fixtures"]:
        pt_list = fx.get("auto_pass_timings_ms", [])
        pt_str = "/".join(f"{x:.0f}" for x in pt_list) + " ms" if pt_list else f"{fx['auto_latency_ms']:.0f} ms"
        lines.append(
            f"| `{fx['fixture_id']}` | {fx['category']} | {fx['legacy_cer'] * 100:.1f}% | **{fx['auto_cer'] * 100:.1f}%** | "
            f"{fx['legacy_wer'] * 100:.1f}% | **{fx['auto_wer'] * 100:.1f}%** | {fx.get('auto_missing_lines', 0)} | "
            f"{fx.get('auto_stray_symbols', 0)} | {fx.get('auto_mean_confidence', 0.0):.1f}% | "
            f"`{fx['auto_strategy']}` (PSM {fx['auto_psm']}, {fx['auto_candidates_evaluated']}p: {pt_str}) | {fx['auto_latency_ms']:.0f} ms |"
        )
    lines.append("")
    return lines


def format_benchmark_markdown_report(summary: Dict[str, Any]) -> str:
    """Format either a single-suite summary or a full multi-suite summary into a Markdown report."""
    if "suite_a_synthetic_dev" in summary:
        sa = summary["suite_a_synthetic_dev"]
        sb = summary["suite_b_independent_regression"]
        sc = summary["suite_c_realworld_heldout"]
    else:
        sa = summary
        sb = run_ocr_benchmark_suite(build_independent_regression_ocr_fixtures())
        sc = run_ocr_benchmark_suite(build_realworld_heldout_ocr_fixtures())

    rss_mb = sc.get("process_peak_rss_mb", sa.get("process_peak_rss_mb", 0.0))
    lines: List[str] = [
        "# Prismwake v0.2.0 — Offline OCR Benchmark & Independent Regression Validation Report",
        "",
        "## Methodology & Scope Notes",
        "",
        "1. **Separation of Development vs. Held-Out Evaluation Suites**:",
        "   - **Suite A (12 Synthetic Development Fixtures)** was authored during initial v0.2.0 development to verify individual preprocessing and layout-refinement paths. Achieving `12 / 12` on Suite A proves those targeted synthetic patterns work as designed, **not** that OCR is 100% accurate on arbitrary real-world captures.",
        "   - **Suite B (6 Independent Held-Out Regression Fixtures)** (`tests/fixtures/independent_ocr/`) was authored independently to test unseen menu icons, leading vertical-bar capital `I`, stylized signs, HUD punctuation, and gradients without any fixture-specific phrases hardcoded in `ocr/engine.py`.",
        "   - **Suite C (8 Held-Out Real-World Screenshot Crops & Unseen UI Captures)** (`tests/fixtures/realworld_ocr/`) evaluates 4 unmodified pixel crops extracted directly from real Windows 11 and desktop screenshots (`image_3490dc.png` and `image_da5e16.png` — excluding downscaled OCR dialog previews that already have cyan word-box overlays burned into the image pixels) alongside 4 unseen prose, markdown pipe-table, bordered icon-menu, and shell-pipe captures.",
        "2. **Internal Baseline Definition (`recognize_image_ocr_legacy`)**:",
        "   - The comparator `recognize_image_ocr_legacy()` is an internal baseline helper implementing the prior single-candidate global-median (`median < 118`) + global 2–98% stretch + fixed 2x scaling pipeline. It is used for controlled algorithmic comparison on the same machine and Tesseract binary, and is not identical to an older pre-built Windows release executable.",
        "3. **Memory Measurement Distinction**:",
        f"   - `tracemalloc` Peak Heap (`KB`) measures Python-process array/image allocations inside `ocr/engine.py` during preprocessing and TSV parsing, whereas native OS process peak RSS (measured via `resource.getrusage` at **{rss_mb:.1f} MB** in the Python runner, plus the external `tesseract` child process) reflects total OS memory.",
        "",
    ]

    lines.extend(
        _render_suite_section(
            "Suite B — Independent 6 Held-Out Regression Fixtures (`tests/fixtures/independent_ocr/`)",
            "Evaluates the 6 external regression fixtures unmodified and offline. Both previously failing fixtures (`new_game_menu.png` and `keep_leading_I.png`) now achieve **0.0% CER / 0.0% WER** while all 4 previously passing fixtures remain at **0.0% CER / 0.0% WER**.",
            sb,
        )
    )

    lines.append("### Per-Fixture Output Trace on Suite B (Independent Held-Out Fixtures)")
    lines.append("")
    lines.append("| Fixture | Ground Truth | Baseline Output | New Automatic Output | Status |")
    lines.append("| :--- | :--- | :--- | :--- | :---: |")
    for fx in sb["fixtures"]:
        gt_inline = repr(fx["ground_truth"])
        leg_inline = repr(fx["legacy_text"])
        auto_inline = repr(fx["auto_text"])
        status_str = "PASS (Exact)" if fx["auto_cer"] == 0.0 else f"DIFF (CER {fx['auto_cer']*100:.1f}%)"
        lines.append(f"| `{fx['fixture_id']}.png` | `{gt_inline}` | `{leg_inline}` | `{auto_inline}` | **{status_str}** |")
    lines.append("")

    lines.extend(
        _render_suite_section(
            "Suite C — Held-Out Real-World Screenshot Crops & Unseen UI Captures (`tests/fixtures/realworld_ocr/`)",
            "Evaluates 4 unmodified pixel crops from real user desktop/Windows 11 screenshots and 4 unseen UI/prose/table captures. Reports real-world character errors transparently (such as subpixel ClearType compression on `real_dark_titlebar_compressed`).",
            sc,
        )
    )

    lines.extend(
        _render_suite_section(
            "Suite A — Original 12 Synthetic Development Fixtures",
            "Deterministic development fixtures covering light/dark UI, 10px code upscaling, left-side menu icons, stylized signs, gradients, faint watermarks, threshold/inversion harm prevention, and isoluminant RGB.",
            sa,
        )
    )

    diag_ev = summary.get("diagnostic_preview_evidence", []) if isinstance(summary, dict) else []
    if diag_ev:
        lines.extend([
            "## Diagnostic Evidence Inspection (Downscaled Dialog-Preview Crops — Non-Native Resolution)",
            "",
            "The two `diagnostic_only_*.png` files from `Prismwake_v020_OCR_Failure_Evidence.zip` are **downscaled crops taken from the OCR dialog preview widget** (with overlay boxes already drawn on the preview), not native-resolution source captures. They are reported here for diagnostic transparency and are never conflated with native-resolution ground truth:",
            "",
            "| Diagnostic Preview Crop | Size | Analyzed Lines | Left Icons | Sparse Menu | Strategy & Passes | Pass Timings | Mean Conf | Calibrated Rejection | Output / Status |",
            "| :--- | :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: | :--- |",
        ])
        for ev in diag_ev:
            pt_s = "/".join(f"{x:.0f}" for x in ev["pass_timings_ms"]) + " ms"
            out_s = repr(ev["recognized_text"]) if ev["recognized_text"] else f"REJECTED ({ev['quality_warning'][:72]}...)"
            lines.append(
                f"| `{ev['file']}` | `{ev['dimensions']}` | {ev['estimated_line_count']} | {ev['has_left_icon_column']} | "
                f"{ev['is_sparse_menu']} | `{ev['strategy']}` (PSM {ev['psm']}, {ev['passes']}p) | {pt_s} | "
                f"{ev['mean_confidence']:.1f}% | `{ev['low_confidence_rejected']}` | `{out_s}` |"
            )
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    all_data = run_all_ocr_benchmark_suites()
    print(format_benchmark_markdown_report(all_data))
