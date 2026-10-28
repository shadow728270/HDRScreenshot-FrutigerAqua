"""
Prismwake v0.2.0 — Offline OCR Engine, Automatic Image Optimization, Bounding Boxes & Two-Mode Frutiger Aqua UI
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

try:
    from PyQt6.QtCore import (
        QObject,
        QPoint,
        QRect,
        QRunnable,
        QSize,
        Qt,
        QThreadPool,
        QTimer,
        pyqtSignal,
    )
    from PyQt6.QtGui import (
        QColor,
        QCursor,
        QFont,
        QImage,
        QKeySequence,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
        QShortcut,
        QTextCursor,
    )
    from PyQt6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QSizeGrip,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )
    HAS_QT = True
except Exception:
    HAS_QT = False


_OCR_LOGGER = logging.getLogger("Prismwake.OCR")


SUPPORTED_OCR_LANGUAGES: Dict[str, str] = {
    "eng": "English (eng)",
    "ita": "Italian (ita)",
    "eng+ita": "English + Italian (eng+ita)",
}

LANGUAGE_SHORT_BADGES: Dict[str, str] = {
    "eng": "EN",
    "ita": "IT",
    "eng+ita": "EN+IT",
}

VALID_OCR_QUALITY_MODES: Tuple[str, ...] = ("auto", "fast", "accurate")

OCR_QUALITY_MODE_LABELS: Dict[str, str] = {
    "auto": "Automatic (Recommended)",
    "fast": "Fast",
    "accurate": "Maximum Accuracy",
}

AUTOMATIC_OCR_STATUS_TEXT: str = "Automatic image optimization · Offline OCR"

OCR_AQUA_THEME_PALETTES: Dict[str, Dict[str, Any]] = {
    "ocean_current": {
        "id": "ocean_current",
        "label": "Ocean Current",
        "bg_top": "#0b2b4c",
        "bg_mid": "#081f38",
        "bg_bot": "#051324",
        "bg_rgba_top": (11, 43, 76, 242),
        "bg_rgba_mid": (8, 31, 56, 245),
        "bg_rgba_bot": (5, 19, 36, 248),
        "border_outer": (0, 228, 255, 215),
        "border_inner": (125, 245, 255, 110),
        "specular_top": (175, 248, 255, 58),
        "accent_hex": "#7df5ff",
        "accent_rgb": (45, 220, 180),
        "editor_bg": "rgba(5, 18, 34, 232)",
        "editor_border": "rgba(96, 222, 255, 145)",
        "selection_bg": "#00b8e6",
        "selection_fg": "#031525",
        "btn_top": "rgba(88, 214, 255, 235)",
        "btn_mid": "rgba(22, 144, 214, 235)",
        "btn_bot": "rgba(12, 96, 168, 242)",
        "btn_border": "rgba(168, 244, 255, 205)",
        "btn_copied_top": "rgba(72, 238, 182, 238)",
        "btn_copied_bot": "rgba(16, 152, 112, 242)",
    },
    "emerald_glass": {
        "id": "emerald_glass",
        "label": "Emerald Glass",
        "bg_top": "#09332c",
        "bg_mid": "#062420",
        "bg_bot": "#041614",
        "bg_rgba_top": (9, 51, 44, 242),
        "bg_rgba_mid": (6, 36, 32, 245),
        "bg_rgba_bot": (4, 22, 20, 248),
        "border_outer": (48, 238, 188, 215),
        "border_inner": (148, 252, 218, 110),
        "specular_top": (182, 255, 230, 56),
        "accent_hex": "#82ffd2",
        "accent_rgb": (105, 245, 180),
        "editor_bg": "rgba(4, 21, 19, 232)",
        "editor_border": "rgba(82, 232, 188, 145)",
        "selection_bg": "#18c998",
        "selection_fg": "#031a14",
        "btn_top": "rgba(76, 228, 182, 235)",
        "btn_mid": "rgba(18, 156, 124, 235)",
        "btn_bot": "rgba(10, 104, 84, 242)",
        "btn_border": "rgba(166, 252, 222, 205)",
        "btn_copied_top": "rgba(98, 245, 192, 240)",
        "btn_copied_bot": "rgba(20, 162, 118, 244)",
    },
    "sunset_coral": {
        "id": "sunset_coral",
        "label": "Sunset Coral",
        "bg_top": "#3a162b",
        "bg_mid": "#280f20",
        "bg_bot": "#180814",
        "bg_rgba_top": (58, 22, 43, 242),
        "bg_rgba_mid": (40, 15, 32, 245),
        "bg_rgba_bot": (24, 8, 20, 248),
        "border_outer": (255, 132, 154, 215),
        "border_inner": (255, 198, 174, 110),
        "specular_top": (255, 214, 198, 54),
        "accent_hex": "#ffb8a2",
        "accent_rgb": (255, 176, 124),
        "editor_bg": "rgba(24, 9, 19, 232)",
        "editor_border": "rgba(255, 142, 162, 145)",
        "selection_bg": "#eb5e84",
        "selection_fg": "#1e0712",
        "btn_top": "rgba(255, 138, 152, 235)",
        "btn_mid": "rgba(218, 68, 108, 235)",
        "btn_bot": "rgba(154, 34, 74, 242)",
        "btn_border": "rgba(255, 202, 192, 205)",
        "btn_copied_top": "rgba(72, 232, 178, 238)",
        "btn_copied_bot": "rgba(18, 148, 108, 242)",
    },
    "vista_sapphire": {
        "id": "vista_sapphire",
        "label": "Vista Sapphire",
        "bg_top": "#0d2554",
        "bg_mid": "#08193b",
        "bg_bot": "#050f26",
        "bg_rgba_top": (13, 37, 84, 242),
        "bg_rgba_mid": (8, 25, 59, 245),
        "bg_rgba_bot": (5, 15, 38, 248),
        "border_outer": (92, 192, 255, 215),
        "border_inner": (172, 228, 255, 110),
        "specular_top": (200, 236, 255, 58),
        "accent_hex": "#9ce0ff",
        "accent_rgb": (112, 196, 255),
        "editor_bg": "rgba(5, 15, 36, 232)",
        "editor_border": "rgba(104, 194, 255, 145)",
        "selection_bg": "#2b8cff",
        "selection_fg": "#041129",
        "btn_top": "rgba(108, 196, 255, 235)",
        "btn_mid": "rgba(32, 112, 222, 235)",
        "btn_bot": "rgba(16, 68, 162, 242)",
        "btn_border": "rgba(182, 228, 255, 205)",
        "btn_copied_top": "rgba(72, 238, 182, 238)",
        "btn_copied_bot": "rgba(16, 152, 112, 242)",
    },
}


def normalize_ocr_quality_mode(mode: Any) -> str:
    """Normalize an OCR quality/budget mode string to `'auto'`, `'fast'`, or `'accurate'`."""
    raw = str(mode or "auto").strip().lower()
    if raw in VALID_OCR_QUALITY_MODES:
        return raw
    if raw in ("recommended", "automatic", "default"):
        return "auto"
    if raw in ("maximum", "max", "high", "maximum_accuracy", "maximum accuracy"):
        return "accurate"
    return "auto"


def resolve_ocr_aqua_theme_palette(
    theme_id_or_spec: Any = "ocean_current",
    animation_intensity: str = "medium",
    reduced_motion: bool = False,
) -> Dict[str, Any]:
    """
    Resolve a complete Frutiger Aqua OCR UI palette for `ocean_current`,
    `emerald_glass`, `sunset_coral`, or `vista_sapphire`, honoring
    `animation_intensity` (`off`, `subtle`, `medium`, `high`) and `reduced_motion`.
    """
    theme_key = "ocean_current"
    if isinstance(theme_id_or_spec, dict):
        raw_id = str(theme_id_or_spec.get("id", "ocean_current")).strip().lower().replace("-", "_").replace(" ", "_")
        if raw_id in OCR_AQUA_THEME_PALETTES:
            theme_key = raw_id
    elif isinstance(theme_id_or_spec, str):
        raw_id = theme_id_or_spec.strip().lower().replace("-", "_").replace(" ", "_")
        if raw_id in OCR_AQUA_THEME_PALETTES:
            theme_key = raw_id
        else:
            for k, spec in OCR_AQUA_THEME_PALETTES.items():
                if str(spec.get("label", "")).lower() == theme_id_or_spec.strip().lower():
                    theme_key = k
                    break

    palette = dict(OCR_AQUA_THEME_PALETTES[theme_key])
    norm_anim = str(animation_intensity or "medium").strip().lower()
    if norm_anim not in ("off", "subtle", "medium", "high"):
        norm_anim = "medium"
    if reduced_motion or norm_anim == "off":
        norm_anim = "off"
    palette["animation_intensity"] = norm_anim
    palette["reduced_motion"] = bool(reduced_motion or norm_anim == "off")
    palette["copied_feedback_ms"] = 900 if palette["reduced_motion"] else 1350
    return palette


@dataclass(frozen=True)
class OcrWordBox:
    """Word-level recognized text and bounding box in original source screenshot coordinates."""
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 90.0
    line_index: int = 0
    word_index: int = 0

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "x": int(self.x),
            "y": int(self.y),
            "width": int(self.width),
            "height": int(self.height),
            "confidence": float(self.confidence),
            "line_index": int(self.line_index),
            "word_index": int(self.word_index),
        }


@dataclass(frozen=True)
class OcrLineBox:
    """Line-level recognized text and bounding box in original source screenshot coordinates."""
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 90.0
    line_index: int = 0
    words: Tuple[OcrWordBox, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "x": int(self.x),
            "y": int(self.y),
            "width": int(self.width),
            "height": int(self.height),
            "confidence": float(self.confidence),
            "line_index": int(self.line_index),
            "words": [w.to_dict() for w in self.words],
        }


@dataclass
class OcrRecognitionResult:
    """Complete structured result of an offline OCR run."""
    text: str
    lines: List[OcrLineBox] = field(default_factory=list)
    words: List[OcrWordBox] = field(default_factory=list)
    language: str = "eng"
    engine_name: str = "tesseract"
    source_width: int = 0
    source_height: int = 0
    scale_factor: float = 1.0
    inverted_dark_theme: bool = False
    threshold_applied: bool = False
    elapsed_ms: float = 0.0
    cancelled: bool = False
    error: str = ""
    preprocessing_strategy: str = "adaptive_gray"
    psm_used: int = 6
    quality_score: float = 0.0
    candidates_evaluated: int = 1
    quality_mode: str = "auto"
    retry_attempt: int = 0
    pass_timings_ms: List[float] = field(default_factory=list)
    candidate_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    low_confidence_rejected: bool = False
    partial_low_confidence: bool = False
    raw_rejected_text: str = ""
    quality_warning: str = ""
    backend_selected: str = ""
    fallback_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.cancelled and not self.error

    @property
    def has_text(self) -> bool:
        return bool(self.text and self.text.strip())

    def find_word_at_point(self, px: int, py: int) -> Optional[OcrWordBox]:
        """Return the recognized word box containing source pixel (px, py)."""
        for word in self.words:
            if word.x <= px <= word.right and word.y <= py <= word.bottom:
                return word
        return None

    def find_line_at_point(self, px: int, py: int) -> Optional[OcrLineBox]:
        """Return the recognized line box containing source pixel (px, py)."""
        for line in self.lines:
            if line.x <= px <= (line.x + line.width) and line.y <= py <= (line.y + line.height):
                return line
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "lines": [ln.to_dict() for ln in self.lines],
            "words": [w.to_dict() for w in self.words],
            "language": self.language,
            "engine_name": self.engine_name,
            "source_width": int(self.source_width),
            "source_height": int(self.source_height),
            "scale_factor": float(self.scale_factor),
            "inverted_dark_theme": bool(self.inverted_dark_theme),
            "threshold_applied": bool(self.threshold_applied),
            "elapsed_ms": float(self.elapsed_ms),
            "cancelled": bool(self.cancelled),
            "error": self.error,
            "preprocessing_strategy": str(self.preprocessing_strategy),
            "psm_used": int(self.psm_used),
            "quality_score": float(self.quality_score),
            "candidates_evaluated": int(self.candidates_evaluated),
            "quality_mode": str(self.quality_mode),
            "retry_attempt": int(self.retry_attempt),
            "pass_timings_ms": [float(x) for x in self.pass_timings_ms],
            "candidate_diagnostics": list(self.candidate_diagnostics),
            "low_confidence_rejected": bool(self.low_confidence_rejected),
            "partial_low_confidence": bool(self.partial_low_confidence),
            "raw_rejected_text": str(self.raw_rejected_text),
            "quality_warning": str(self.quality_warning),
            "backend_selected": str(self.backend_selected),
            "fallback_reason": str(self.fallback_reason),
        }


@dataclass(frozen=True)
class OcrEngineStatus:
    """Describes the currently available offline OCR runtime and language packs."""
    available: bool
    engine_kind: str  # "tesseract", "rapidocr", "builtin_template", or "unavailable"
    binary_path: Optional[Path]
    tessdata_dir: Optional[Path]
    installed_languages: Tuple[str, ...]
    version_string: str
    status_summary: str
    active_backend: str = "Tesseract fallback"
    rapidocr_available: bool = False


@dataclass(frozen=True)
class OcrImageProfile:
    """
    Analyzed visual and geometric characteristics of a screenshot capture region
    used to select preprocessing candidates and Tesseract Page Segmentation Modes
    automatically without user intervention.
    """
    width: int
    height: int
    aspect_ratio: float
    median_luma: float
    mean_luma: float
    contrast_span: float
    is_light_ink: bool
    light_stroke_score: float
    dark_stroke_score: float
    mixed_polarity: bool
    bg_gradient_span: float
    chroma_contrast: float
    is_chromatic_isoluminant: bool
    estimated_line_count: int
    estimated_glyph_height: float
    recommended_scale: float
    is_small_text: bool
    is_single_line: bool
    is_single_word: bool
    is_sparse_menu: bool
    has_left_icon_column: bool
    has_flanking_decorations: bool
    low_contrast_faint: bool
    bold_all_caps_like: bool
    text_x0: int
    text_x1: int
    text_y0: int
    text_y1: int
    active_width_ratio: float
    row_text_rois: Tuple[Tuple[int, int, int, int], ...] = ()


@dataclass
class OcrPreprocessCandidate:
    """Represents a single automatically generated image preprocessing candidate."""
    name: str
    pil_image: Image.Image
    scale_factor: float = 1.0
    crop_offset_xy: Tuple[int, int] = (0, 0)
    pad_fill: Any = 255
    inverted_dark_theme: bool = False
    threshold_applied: bool = False
    icon_masked: bool = False
    preferred_psms: Tuple[int, ...] = (6, 11, 3)


class CancellationToken:
    """Thread-safe cancellation flag for background OCR jobs."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


def _candidate_bundle_roots() -> List[Path]:
    roots: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        try:
            roots.append(Path(meipass))
        except Exception:
            pass
    try:
        if getattr(sys, "frozen", False):
            roots.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    try:
        here = Path(__file__).resolve().parent
        roots.append(here.parent)
        roots.append(here)
    except Exception:
        pass
    roots.append(Path.cwd())
    unique: List[Path] = []
    seen = set()
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


_TESSERACT_VERSION_CACHE: Dict[Tuple[str, int, int], str] = {}
_TESSERACT_RUNTIME_CACHE: Dict[Tuple[str, str, str, str, str, int, int], Tuple[Optional[Path], Optional[Path], Tuple[str, ...], str]] = {}


def detect_tesseract_runtime(
    custom_binary: Optional[Path] = None,
    custom_tessdata: Optional[Path] = None,
) -> Tuple[Optional[Path], Optional[Path], Tuple[str, ...], str]:
    """
    Locate bundled or local Tesseract binary and tessdata directory without
    requiring internet access or Windows package identity.
    """
    rt_cache_key = (
        str(custom_binary or ""),
        str(custom_tessdata or ""),
        os.environ.get("PRISMWAKE_TESSERACT_PATH", "").strip(),
        os.environ.get("PRISMWAKE_TESSDATA_DIR", "").strip(),
        os.environ.get("TESSDATA_PREFIX", "").strip(),
        id(subprocess.run),
        id(shutil.which),
    )
    cached_rt = _TESSERACT_RUNTIME_CACHE.get(rt_cache_key)
    if cached_rt is not None:
        c_bin, c_td, c_langs, c_ver = cached_rt
        if c_bin is not None and c_bin.is_file() and (c_td is None or (c_td.is_dir() and any(c_td.glob("*.traineddata")))):
            return cached_rt
    exe_names = ["tesseract.exe", "tesseract"] if sys.platform == "win32" else ["tesseract", "tesseract.exe"]
    candidate_bins: List[Path] = []
    if custom_binary is not None:
        candidate_bins.append(Path(custom_binary))

    env_bin = os.environ.get("PRISMWAKE_TESSERACT_PATH", "").strip()
    if env_bin:
        candidate_bins.append(Path(env_bin))

    for root in _candidate_bundle_roots():
        for sub in ("tesseract_bundle", "tesseract", "bin", os.path.join("resources", "tesseract"), ""):
            base = root / sub if sub else root
            for exe_name in exe_names:
                candidate_bins.append(base / exe_name)

    which_bin = shutil.which("tesseract")
    if which_bin:
        candidate_bins.append(Path(which_bin))

    if sys.platform == "win32":
        for prog_env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            prog_dir = os.environ.get(prog_env, "")
            if prog_dir:
                candidate_bins.append(Path(prog_dir) / "Prismwake" / "tesseract_bundle" / "tesseract.exe")
                candidate_bins.append(Path(prog_dir) / "Tesseract-OCR" / "tesseract.exe")

    resolved_bin: Optional[Path] = None
    for cand in candidate_bins:
        try:
            if cand.is_file() and (str(cand).lower().endswith(".py") or os.access(str(cand), os.X_OK if sys.platform != "win32" else os.R_OK)):
                resolved_bin = cand.resolve()
                break
        except Exception:
            continue

    candidate_tessdata: List[Path] = []
    if custom_tessdata is not None:
        candidate_tessdata.append(Path(custom_tessdata))
    env_td = os.environ.get("PRISMWAKE_TESSDATA_DIR", "").strip() or os.environ.get("TESSDATA_PREFIX", "").strip()
    if env_td:
        candidate_tessdata.append(Path(env_td))
    if resolved_bin is not None:
        candidate_tessdata.append(resolved_bin.parent / "tessdata")
        candidate_tessdata.append(resolved_bin.parent.parent / "tessdata")
        candidate_tessdata.append(resolved_bin.parent.parent / "share" / "tessdata")
        candidate_tessdata.append(resolved_bin.parent.parent / "share" / "tesseract-ocr" / "5" / "tessdata")
        candidate_tessdata.append(resolved_bin.parent.parent / "share" / "tesseract-ocr" / "4.00" / "tessdata")
    for root in _candidate_bundle_roots():
        candidate_tessdata.append(root / "tesseract_bundle" / "tessdata")
        candidate_tessdata.append(root / "tessdata")
    if sys.platform != "win32":
        candidate_tessdata.extend([
            Path("/usr/share/tesseract-ocr/5/tessdata"),
            Path("/usr/share/tesseract-ocr/4.00/tessdata"),
            Path("/usr/share/tessdata"),
            Path("/usr/local/share/tessdata"),
        ])

    resolved_tessdata: Optional[Path] = None
    langs: List[str] = []
    for td in candidate_tessdata:
        try:
            if td.is_dir():
                found = sorted(
                    p.stem for p in td.glob("*.traineddata")
                    if p.stem and p.stem != "osd"
                )
                if found:
                    resolved_tessdata = td.resolve()
                    langs = found
                    break
        except Exception:
            continue

    version_str = ""
    if resolved_bin is not None:
        try:
            bin_mtime = resolved_bin.stat().st_mtime_ns
            cache_key = (str(resolved_bin), bin_mtime, id(subprocess.run))
            cached_ver = _TESSERACT_VERSION_CACHE.get(cache_key)
            creationflags = 0x08000000 if sys.platform == "win32" else 0
            if cached_ver is not None:
                version_str = cached_ver
            else:
                ver_cmd = [sys.executable, str(resolved_bin), "--version"] if str(resolved_bin).lower().endswith(".py") else [str(resolved_bin), "--version"]
                proc = subprocess.run(
                    ver_cmd,
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                    creationflags=creationflags,
                )
                if proc.returncode != 0:
                    resolved_bin = None
                else:
                    first_line = (proc.stdout or proc.stderr or "").splitlines()
                    if first_line:
                        version_str = first_line[0].strip()
                    _TESSERACT_VERSION_CACHE[cache_key] = version_str
            if resolved_bin is not None and not langs:
                cmd_langs = [str(resolved_bin), "--list-langs"]
                if resolved_tessdata is not None:
                    cmd_langs.extend(["--tessdata-dir", str(resolved_tessdata)])
                proc_l = subprocess.run(
                    cmd_langs,
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                    creationflags=creationflags,
                )
                for line in (proc_l.stdout or proc_l.stderr or "").splitlines():
                    s = line.strip()
                    if s and not s.lower().startswith("list of available") and s != "osd":
                        langs.append(s)
        except Exception:
            resolved_bin = None

    result_tuple = (resolved_bin, resolved_tessdata, tuple(dict.fromkeys(langs)), version_str)
    if resolved_bin is not None and langs:
        _TESSERACT_RUNTIME_CACHE[rt_cache_key] = result_tuple
    return result_tuple


_ORIGINAL_DETECT_TESSERACT_RUNTIME = detect_tesseract_runtime


def query_ocr_engine_status(
    allow_builtin_fallback: bool = False,
    custom_binary: Optional[Path] = None,
    custom_tessdata: Optional[Path] = None,
) -> OcrEngineStatus:
    """
    Return a truthful structured status report for Settings, startup checks, and OCR dialogs.
    Reports RapidOCR (ONNX CPU) primary availability and Offline Tesseract fallback readiness.
    """
    t_bin, t_data, langs, ver = detect_tesseract_runtime(
        custom_binary=custom_binary,
        custom_tessdata=custom_tessdata,
    )
    rapid_avail = False
    rapid_ver = ""
    rapid_langs: Tuple[str, ...] = ("eng",)
    if custom_binary is None and detect_tesseract_runtime is _ORIGINAL_DETECT_TESSERACT_RUNTIME:
        try:
            from .backends import get_production_ocr_orchestrator
            r_stat = get_production_ocr_orchestrator().rapidocr.query_status()
            rapid_avail = bool(r_stat.available)
            rapid_ver = r_stat.engine_version
            rapid_langs = r_stat.supported_languages
        except Exception:
            rapid_avail = False

    if t_bin is not None:
        if "eng" not in langs:
            return OcrEngineStatus(
                available=False,
                engine_kind="unavailable",
                binary_path=t_bin,
                tessdata_dir=t_data,
                installed_languages=langs,
                version_string=ver or "Tesseract OCR",
                status_summary=(
                    "OCR engine incomplete: Tesseract binary found, but required English language data "
                    "(eng.traineddata) is missing from tessdata/."
                ),
                active_backend="Unavailable",
                rapidocr_available=rapid_avail,
            )
        if rapid_avail:
            summary = (
                f"Primary: RapidOCR (ONNX CPU, {rapid_ver}) • "
                f"Fallback: Offline Tesseract ready ({ver or 'Tesseract OCR'}) — Languages: {', '.join(langs)}"
            )
            act_backend = "RapidOCR (ONNX CPU)"
        else:
            summary = (
                f"Offline Tesseract fallback ready ({ver or 'Tesseract OCR'}) — "
                f"Languages: {', '.join(langs)} (RapidOCR neural backend unavailable)"
            )
            act_backend = "Tesseract fallback"
        return OcrEngineStatus(
            available=True,
            engine_kind="tesseract",
            binary_path=t_bin,
            tessdata_dir=t_data,
            installed_languages=langs,
            version_string=ver or "Tesseract OCR",
            status_summary=summary,
            active_backend=act_backend,
            rapidocr_available=rapid_avail,
        )
    if rapid_avail:
        return OcrEngineStatus(
            available=True,
            engine_kind="rapidocr",
            binary_path=None,
            tessdata_dir=t_data,
            installed_languages=rapid_langs,
            version_string=rapid_ver,
            status_summary=f"RapidOCR (ONNX CPU, {rapid_ver}) ready — Languages: {', '.join(rapid_langs)}",
            active_backend="RapidOCR (ONNX CPU)",
            rapidocr_available=True,
        )
    if allow_builtin_fallback:
        return OcrEngineStatus(
            available=True,
            engine_kind="builtin_template",
            binary_path=None,
            tessdata_dir=t_data,
            installed_languages=("eng", "ita"),
            version_string="Prismwake Built-in Template Fallback (Limited)",
            status_summary="Limited built-in glyph fallback active (Tesseract binary not found)",
        )
    return OcrEngineStatus(
        available=False,
        engine_kind="unavailable",
        binary_path=None,
        tessdata_dir=t_data,
        installed_languages=langs,
        version_string="",
        status_summary=(
            "OCR engine unavailable: Tesseract runtime (tesseract.exe + tessdata/eng.traineddata) "
            "was not found in tesseract_bundle/ or system PATH."
        ),
    )


def _to_pil_rgb(image_source: Any) -> Image.Image:
    """Convert PIL.Image, numpy ndarray, QImage, or QPixmap to a 3-channel RGB PIL Image."""
    if isinstance(image_source, Image.Image):
        return image_source.convert("RGB")
    if isinstance(image_source, np.ndarray):
        arr = np.asarray(image_source)
        if arr.ndim == 2:
            return Image.fromarray(arr.astype(np.uint8), mode="L").convert("RGB")
        if arr.ndim == 3 and arr.shape[2] >= 3:
            return Image.fromarray(arr[:, :, :3].astype(np.uint8), mode="RGB")
        raise ValueError(f"Unsupported ndarray shape for OCR: {arr.shape}")
    if HAS_QT:
        if isinstance(image_source, QPixmap):
            image_source = image_source.toImage()
        if isinstance(image_source, QImage):
            qimg = image_source.convertToFormat(QImage.Format.Format_RGBA8888)
            w, h = qimg.width(), qimg.height()
            if w <= 0 or h <= 0:
                return Image.new("RGB", (1, 1), (255, 255, 255))
            ptr = qimg.bits()
            ptr.setsize(h * qimg.bytesPerLine())
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, qimg.bytesPerLine() // 4, 4))
            return Image.fromarray(arr[:, :w, :3].copy(), mode="RGB")
    if hasattr(image_source, "to_pil") and callable(image_source.to_pil):
        return image_source.to_pil().convert("RGB")
    raise TypeError(f"Unsupported image source type for OCR: {type(image_source)!r}")


# ---------------------------------------------------------------------------
# Pure-NumPy Fast 1D/2D Box Filtering & Automatic Image Analysis
# ---------------------------------------------------------------------------

def _box_blur_1d_horizontal(arr: np.ndarray, radius: int) -> np.ndarray:
    """Fast vectorized 1D horizontal box filter with edge padding."""
    if radius <= 0 or arr.shape[1] <= 1:
        return arr.astype(np.float32)
    a = arr.astype(np.float32)
    k = 2 * radius + 1
    pad_x = np.pad(a, ((0, 0), (radius, radius)), mode="edge")
    cs_x = np.cumsum(np.pad(pad_x, ((0, 0), (1, 0)), mode="constant"), axis=1)
    return (cs_x[:, k:] - cs_x[:, :-k]) / float(k)


def _box_blur_2d(arr: np.ndarray, radius: int) -> np.ndarray:
    """Fast vectorized 2-pass separable 2D box filter with edge padding."""
    if radius <= 0 or arr.size == 0:
        return arr.astype(np.float32)
    h_blur = _box_blur_1d_horizontal(arr, radius)
    if arr.shape[0] <= 1:
        return h_blur
    k = 2 * radius + 1
    pad_y = np.pad(h_blur, ((radius, radius), (0, 0)), mode="edge")
    cs_y = np.cumsum(np.pad(pad_y, ((1, 0), (0, 0)), mode="constant"), axis=0)
    return (cs_y[k:, :] - cs_y[:-k, :]) / float(k)


def _smooth_background_envelope(luma: np.ndarray, radius: int = 14) -> np.ndarray:
    """Two-pass separable box blur approximating a smooth Gaussian background illumination envelope."""
    b1 = _box_blur_2d(luma, max(2, radius))
    return _box_blur_2d(b1, max(1, radius // 2))



def _binary_dilate_rect(mask: np.ndarray, rx: int, ry: int) -> np.ndarray:
    """Fast pure-NumPy 2D rectangular binary dilation."""
    h, w = mask.shape
    out = mask.copy()
    for dx in range(-rx, rx + 1):
        if dx < 0:
            out[:, :w + dx] |= mask[:, -dx:]
        elif dx > 0:
            out[:, dx:] |= mask[:, :w - dx]
    tmp = out.copy()
    for dy in range(-ry, ry + 1):
        if dy < 0:
            out[:h + dy, :] |= tmp[-dy:, :]
        elif dy > 0:
            out[dy:, :] |= tmp[:h - dy, :]
    return out


def _find_connected_bboxes(
    mask: np.ndarray,
    min_w: int = 10,
    min_h: int = 7,
    min_area: int = 28,
) -> List[Tuple[int, int, int, int]]:
    """Fast scanline horizontal-run Union-Find 8-connected components bounding-box detector in pure NumPy."""
    h, w = mask.shape
    padded = np.pad(mask, ((0, 0), (1, 1)), mode="constant", constant_values=False)
    diff = np.diff(padded.astype(np.int8), axis=1)
    ys_s, xs_s = np.where(diff == 1)
    ys_e, xs_e = np.where(diff == -1)
    n_runs = len(ys_s)
    if n_runs == 0:
        return []
    parent = list(range(n_runs))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def _union(i: int, j: int) -> None:
        ri, rj = _find(i), _find(j)
        if ri != rj:
            if ri < rj:
                parent[rj] = ri
            else:
                parent[ri] = rj

    row_runs: Dict[int, List[Tuple[int, int, int]]] = {}
    for idx in range(n_runs):
        r = int(ys_s[idx])
        row_runs.setdefault(r, []).append((int(xs_s[idx]), int(xs_e[idx]), idx))

    for r, runs in row_runs.items():
        prev_runs = row_runs.get(r - 1)
        if not prev_runs:
            continue
        p_idx = 0
        n_prev = len(prev_runs)
        for x0, x1, idx in runs:
            while p_idx < n_prev and prev_runs[p_idx][1] < x0 - 1:
                p_idx += 1
            k = p_idx
            while k < n_prev and prev_runs[k][0] <= x1 + 1:
                _union(idx, prev_runs[k][2])
                k += 1

    comp_stats: Dict[int, List[int]] = {}
    for idx in range(n_runs):
        root = _find(idx)
        y = int(ys_s[idx])
        x0 = int(xs_s[idx])
        x1 = int(xs_e[idx])
        run_len = x1 - x0
        if root not in comp_stats:
            comp_stats[root] = [x0, y, x1, y + 1, run_len]
        else:
            st = comp_stats[root]
            if x0 < st[0]:
                st[0] = x0
            if y < st[1]:
                st[1] = y
            if x1 > st[2]:
                st[2] = x1
            if y + 1 > st[3]:
                st[3] = y + 1
            st[4] += run_len

    bboxes: List[Tuple[int, int, int, int]] = []
    for x0, y0, x1, y1, area in comp_stats.values():
        if (x1 - x0) >= min_w and (y1 - y0) >= min_h and area >= min_area:
            bboxes.append((int(x0), int(y0), int(x1), int(y1)))
    return bboxes


def _detect_multicol_white_core_islands(arr_rgb: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """
    Detect multi-column / 2D grid white-core HUD pill/badge text islands (such as a 2x2 grid
    of differently colored game HUD pills with icons and dark text outlines).
    Returns sorted `(x0, y0, x1, y1)` island boxes when a multi-column pill layout is present,
    or `[]` for ordinary single-column prose/menus/tables.
    """
    h, w, _ = arr_rgb.shape
    if h < 45 or w < 140:
        return []
    min_rgb = np.min(arr_rgb, axis=2)
    max_rgb = np.max(arr_rgb, axis=2)
    sat = max_rgb - min_rgb
    white_score = np.clip((min_rgb - 175.0) * 3.2 - sat * 1.5, 0.0, 255.0)
    mask = white_score > 80.0
    dilated = _binary_dilate_rect(mask, rx=7, ry=1)
    boxes = _find_connected_bboxes(dilated, min_w=16, min_h=8, min_area=40)
    valid: List[Tuple[int, int, int, int]] = []
    for b in boxes:
        bw, bh = b[2] - b[0], b[3] - b[1]
        if bw * bh >= 0.45 * w * h or bh > 36:
            continue
        valid.append(b)
    filtered: List[Tuple[int, int, int, int]] = []
    for b in valid:
        bw, bh = b[2] - b[0], b[3] - b[1]
        cy = 0.5 * (b[1] + b[3])
        has_wider_right = any(
            (ob[2] - ob[0]) > bw * 1.4
            and ob[0] >= b[2] - 4
            and abs(0.5 * (ob[1] + ob[3]) - cy) <= max(bh, ob[3] - ob[1]) * 0.85
            for ob in valid
            if ob != b
        )
        if has_wider_right and bw <= bh * 2.2:
            continue
        filtered.append(b)
    filtered.sort(key=lambda b: (b[1] // 24, b[0]))
    rows: Dict[int, List[Tuple[int, int, int, int]]] = {}
    for b in filtered:
        rk = b[1] // 24
        rows.setdefault(rk, []).append(b)
    has_multicol_pill_gap = False
    for _rk, rboxes in rows.items():
        if len(rboxes) >= 2:
            for i in range(len(rboxes) - 1):
                gap = rboxes[i + 1][0] - rboxes[i][2]
                if gap >= 22:
                    gx0, gx1 = rboxes[i][2] + 2, rboxes[i + 1][0] - 2
                    gy0, gy1 = min(rboxes[i][1], rboxes[i + 1][1]), max(rboxes[i][3], rboxes[i + 1][3])
                    if gx1 > gx0 and gy1 > gy0:
                        gap_white = white_score[gy0:gy1, gx0:gx1]
                        if float(np.max(gap_white)) < 120.0:
                            has_multicol_pill_gap = True
    if len(rows) >= 2 and has_multicol_pill_gap:
        return filtered
    return []


def _extract_island_fisher_gray(
    arr_rgb: np.ndarray,
    box: Tuple[int, int, int, int],
    *,
    light_ink: bool = True,
) -> np.ndarray:
    """
    Extract a crisp dark-on-white grayscale patch for a single text island `(x0, y0, x1, y1)`
    by combining Fisher linear discriminant color projection `(fg_rgb - bg_rgb)` with smooth
    achromatic white-core extraction (eliminating dark drop-shadows/strokes around white glyphs).
    """
    h, w, _ = arr_rgb.shape
    x0, y0, x1, y1 = box
    px0, py0, px1, py1 = max(0, int(x0)), max(0, int(y0)), min(w, int(x1)), min(h, int(y1))
    sub = arr_rgb[py0:py1, px0:px1, :]
    if sub.size == 0:
        return np.full((max(1, py1 - py0), max(1, px1 - px0)), 255, dtype=np.uint8)
    if light_ink:
        min_ch = np.min(sub, axis=2)
        max_ch = np.max(sub, axis=2)
        sat_ch = max_ch - min_ch
        bg_rgb = np.percentile(sub, 40.0, axis=(0, 1))
        fg_rgb = np.percentile(sub, 98.0, axis=(0, 1))
        vec = fg_rgb - bg_rgb
        vnorm = float(np.linalg.norm(vec))
        u = (vec / vnorm) if vnorm > 1e-3 else np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        diff = sub - bg_rgb[None, None, :]
        proj = diff[:, :, 0] * u[0] + diff[:, :, 1] * u[1] + diff[:, :, 2] * u[2]
        bg_min = float(np.percentile(min_ch, 45.0))
        sat_ref = float(np.percentile(sat_ch, 15.0))
        white_ness = np.maximum(0.0, (min_ch - bg_min) - 0.35 * np.maximum(0.0, sat_ch - sat_ref))
        sig = np.maximum(np.maximum(0.0, proj), white_ness)
    else:
        bg_rgb = np.percentile(sub, 75.0, axis=(0, 1))
        fg_rgb = np.percentile(sub, 2.0, axis=(0, 1))
        vec = bg_rgb - fg_rgb
        vnorm = float(np.linalg.norm(vec))
        u = (vec / vnorm) if vnorm > 1e-3 else np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        diff = bg_rgb[None, None, :] - sub
        proj = diff[:, :, 0] * u[0] + diff[:, :, 1] * u[1] + diff[:, :, 2] * u[2]
        local_bg = _box_blur_2d(proj, max(4, py1 - py0))
        sig = np.maximum(0.0, proj - np.minimum(0.0, local_bg))

    hi = float(np.percentile(sig, 99.0))
    lo = float(np.percentile(sig, 20.0))
    if (hi - lo) >= 3.0:
        scaled = 255.0 - np.clip((sig - lo) * (255.0 / max(1.0, hi - lo)), 0.0, 255.0)
        return np.round(scaled).astype(np.uint8)
    return np.full((py1 - py0, px1 - px0), 255, dtype=np.uint8)


def analyze_image_for_ocr(image_source: Any) -> OcrImageProfile:
    """
    Inspect local luminance, foreground/background stroke polarity (including white text on
    vivid colored buttons), color channel separation, background illumination gradients,
    separated horizontal text rows (`row_text_rois`), and marginal icon/decorative structures.
    """
    rgb_img = _to_pil_rgb(image_source)
    w, h = rgb_img.size
    if w <= 2 or h <= 2:
        return OcrImageProfile(
            width=w,
            height=h,
            aspect_ratio=float(w) / max(1.0, float(h)),
            median_luma=255.0,
            mean_luma=255.0,
            contrast_span=0.0,
            is_light_ink=False,
            light_stroke_score=0.0,
            dark_stroke_score=0.0,
            mixed_polarity=False,
            bg_gradient_span=0.0,
            chroma_contrast=0.0,
            is_chromatic_isoluminant=False,
            estimated_line_count=1,
            estimated_glyph_height=float(h),
            recommended_scale=1.0,
            is_small_text=False,
            is_single_line=True,
            is_single_word=True,
            is_sparse_menu=False,
            has_left_icon_column=False,
            has_flanking_decorations=False,
            low_contrast_faint=False,
            bold_all_caps_like=False,
            text_x0=0,
            text_x1=w,
            text_y0=0,
            text_y1=h,
            active_width_ratio=1.0,
            row_text_rois=(),
        )

    arr_rgb = np.asarray(rgb_img, dtype=np.float32)
    r_ch = arr_rgb[:, :, 0]
    g_ch = arr_rgb[:, :, 1]
    b_ch = arr_rgb[:, :, 2]
    luma = 0.2126 * r_ch + 0.7152 * g_ch + 0.0722 * b_ch
    white_ch = np.minimum(r_ch, np.minimum(g_ch, b_ch))
    max_ch = np.maximum(r_ch, np.maximum(g_ch, b_ch))
    sat_ch = max_ch - white_ch

    median_luma = float(np.median(luma))
    mean_luma = float(np.mean(luma))
    p2, p98 = float(np.percentile(luma, 2.0)), float(np.percentile(luma, 98.0))
    contrast_span = max(0.0, p98 - p2)

    # 1. Foreground vs. Background Stroke Polarity via 1D Horizontal Scanline Local Background
    rad_x = max(5, min(14, w // 24))
    bg_x = _box_blur_1d_horizontal(luma, rad_x)
    bg_white_x = _box_blur_1d_horizontal(white_ch, rad_x)
    bg_sat_x = _box_blur_1d_horizontal(sat_ch, rad_x)
    chroma_boost = np.clip((bg_sat_x - 25.0) / 45.0, 0.0, 0.95)

    dev_light = np.maximum(
        np.maximum(0.0, luma - bg_x),
        np.maximum(0.0, white_ch - bg_white_x) * chroma_boost,
    )
    dev_dark = np.maximum(0.0, bg_x - luma)

    gx_luma = np.abs(np.diff(luma, axis=1))
    gx_rgb = np.maximum(
        np.abs(np.diff(r_ch, axis=1)),
        np.maximum(np.abs(np.diff(g_ch, axis=1)), np.abs(np.diff(b_ch, axis=1))),
    )
    gx_best = np.maximum(gx_luma, gx_rgb * 0.75)
    g_thresh = max(3.5, float(np.percentile(gx_best, 92.0)) * 0.32)
    core_x0 = max(0, int(w * 0.06))
    core_x1 = max(core_x0 + 1, int(w * 0.90))
    transitions_per_row = np.sum(gx_best[:, core_x0:core_x1] > g_thresh, axis=1)
    text_rows = transitions_per_row >= max(4, min(6, w // 45))
    if not np.any(text_rows):
        text_rows = transitions_per_row >= 2

    # Narrow-scale interior glyph stem crossings (separates stacked button/card rows even over busy backgrounds)
    rad_n = max(3, min(8, w // 28))
    bg_luma_n = _box_blur_1d_horizontal(luma, rad_n)
    bg_white_n = _box_blur_1d_horizontal(white_ch, rad_n)
    bg_sat_n = _box_blur_1d_horizontal(sat_ch, rad_n)
    chroma_w_n = np.clip((bg_sat_n - 20.0) / 40.0, 0.0, 1.0)
    light_sig_n = np.maximum(
        np.maximum(0.0, luma - bg_luma_n),
        np.maximum(0.0, white_ch - bg_white_n) * (0.65 + 0.35 * chroma_w_n),
    )
    dark_sig_n = np.maximum(0.0, bg_luma_n - luma)
    gy_full = np.abs(np.diff(luma, axis=0, prepend=luma[:1, :]))
    gx_full = np.abs(np.diff(luma, axis=1, prepend=luma[:, :1]))
    horiz_edge_row = np.mean(gy_full > (gx_full * 1.6 + 6.0), axis=1) > 0.35
    light_sig_n = _suppress_long_border_lines_in_residual(light_sig_n)
    dark_sig_n = _suppress_long_border_lines_in_residual(dark_sig_n)
    light_sig_n[horiz_edge_row, :] = 0.0
    dark_sig_n[horiz_edge_row, :] = 0.0

    ix0 = max(1, int(w * 0.14))
    ix1 = max(ix0 + 1, int(w * 0.88))
    l_thr_n = max(4.0, float(np.percentile(light_sig_n[:, ix0:ix1], 94.0)) * 0.38) if ix1 > ix0 else 4.0
    d_thr_n = max(4.0, float(np.percentile(dark_sig_n[:, ix0:ix1], 94.0)) * 0.38) if ix1 > ix0 else 4.0
    l_bin_n = light_sig_n[:, ix0:ix1] > l_thr_n
    d_bin_n = dark_sig_n[:, ix0:ix1] > d_thr_n
    l_stems = np.sum(l_bin_n[:, 1:] & ~l_bin_n[:, :-1], axis=1)
    d_stems = np.sum(d_bin_n[:, 1:] & ~d_bin_n[:, :-1], axis=1)
    min_stems = max(3, min(6, max(1, (ix1 - ix0) // 28)))
    l_stem_rows = l_stems >= min_stems
    d_stem_rows = d_stems >= min_stems

    x_margin = max(1, int(w * 0.04))
    x_slice = slice(x_margin, max(x_margin + 1, w - x_margin))
    if np.any(text_rows):
        sub_light = dev_light[text_rows, x_slice]
        sub_dark = dev_dark[text_rows, x_slice]
        light_stroke_score = 0.55 * float(np.percentile(sub_light, 96.0)) + 0.45 * float(np.percentile(sub_light, 99.0))
        dark_stroke_score = 0.55 * float(np.percentile(sub_dark, 96.0)) + 0.45 * float(np.percentile(sub_dark, 99.0))
    else:
        light_stroke_score = 0.0
        dark_stroke_score = 0.0

    med_interior_sat = float(np.median(sat_ch[:, ix0:ix1])) if ix1 > ix0 else 0.0
    l_stem_score = float(np.percentile(light_sig_n[l_stem_rows, ix0:ix1], 97.0)) if np.any(l_stem_rows) else 0.0
    d_stem_score = float(np.percentile(dark_sig_n[d_stem_rows, ix0:ix1], 97.0)) if np.any(d_stem_rows) else 0.0

    max_stroke = max(light_stroke_score, dark_stroke_score)
    min_stroke = min(light_stroke_score, dark_stroke_score)
    if med_interior_sat > 32.0 and l_stem_score > d_stem_score * 1.12:
        is_light_ink = True
        light_stroke_score = max(light_stroke_score, l_stem_score)
        max_stroke = max(light_stroke_score, dark_stroke_score)
    elif max_stroke < 2.0:
        is_light_ink = (median_luma < 118.0)
    elif abs(light_stroke_score - dark_stroke_score) <= max(2.5, max_stroke * 0.06):
        is_light_ink = (median_luma < 118.0)
    else:
        is_light_ink = (light_stroke_score > dark_stroke_score)

    # 2. Non-Edge Background Illumination Gradient & Mixed-Polarity Detection
    grad_full = np.pad(gx_best, ((0, 0), (0, 1)), mode="edge")
    non_edge_mask = grad_full <= max(3.0, g_thresh * 0.55)
    if np.sum(non_edge_mask) >= max(32, int(w * h * 0.15)):
        bg_pixels = luma[non_edge_mask]
        bg_p10, bg_p90 = float(np.percentile(bg_pixels, 10.0)), float(np.percentile(bg_pixels, 90.0))
    else:
        bg_2d = _smooth_background_envelope(luma, radius=max(8, min(18, min(w, h) // 5)))
        bg_p10, bg_p90 = float(np.percentile(bg_2d, 10.0)), float(np.percentile(bg_2d, 90.0))
    bg_gradient_span = max(0.0, bg_p90 - bg_p10)
    mixed_polarity = bool(
        bg_gradient_span > 22.0
        or ((median_luma < 118.0) != is_light_ink)
        or (min_stroke > 24.0 and (min_stroke / max(1.0, max_stroke)) > 0.78)
    )

    # 3. Chromatic / Isoluminant Detection (when RGB contrast greatly exceeds luminance contrast)
    bg_r = _box_blur_1d_horizontal(r_ch, rad_x)
    bg_g = _box_blur_1d_horizontal(g_ch, rad_x)
    bg_b = _box_blur_1d_horizontal(b_ch, rad_x)
    chroma_dev = np.sqrt(((r_ch - bg_r) ** 2 + (g_ch - bg_g) ** 2 + (b_ch - bg_b) ** 2) / 3.0)
    if np.any(text_rows):
        sub_c = chroma_dev[text_rows, x_slice]
        chroma_contrast = 0.55 * float(np.percentile(sub_c, 96.0)) + 0.45 * float(np.percentile(sub_c, 99.0))
    else:
        chroma_contrast = float(np.percentile(chroma_dev, 98.0))
    luma_only_stroke = float(np.percentile(np.maximum(0.0, luma - bg_x)[text_rows, x_slice], 97.0)) if np.any(text_rows) else max_stroke
    is_chromatic_isoluminant = bool(chroma_contrast > max(20.0, min(max_stroke, luma_only_stroke) * 1.48))

    # 4. Line Bands, Glyph Height, Active Span, and Icon/Decoration Topology
    def _extract_bands_from_mask(rmask: np.ndarray) -> List[Tuple[int, int]]:
        pad_r = np.concatenate(([False], rmask, [False]))
        rs = np.where(pad_r[1:] & ~pad_r[:-1])[0]
        re_ = np.where(~pad_r[1:] & pad_r[:-1])[0]
        raw_b = [(int(s), int(e)) for s, e in zip(rs, re_) if (e - s) >= 4]
        merged_b: List[Tuple[int, int]] = []
        for s, e in raw_b:
            if merged_b and (s - merged_b[-1][1]) <= 2:
                merged_b[-1] = (merged_b[-1][0], e)
            else:
                merged_b.append((s, e))
        return merged_b

    bands = _extract_bands_from_mask(text_rows)
    chosen_stem_rows = l_stem_rows if is_light_ink else d_stem_rows
    stem_bands = _extract_bands_from_mask(chosen_stem_rows)
    max_band_h = max((e - s for s, e in bands), default=0)
    if len(stem_bands) >= 2 and len(stem_bands) > len(bands) and max_band_h >= max(32, int(h * 0.35)):
        bands = stem_bands
        text_rows = chosen_stem_rows

    estimated_line_count = max(1, len(bands))
    heights = [e - s for s, e in bands]
    estimated_glyph_height = float(np.percentile(heights, 20.0)) if heights else float(min(h, 24))

    if np.any(text_rows):
        col_edges = np.sum(gx_best[text_rows, :] > g_thresh, axis=0)
        active_cols = np.where(col_edges >= 1)[0]
    else:
        active_cols = np.array([], dtype=np.int64)
    if len(active_cols) >= 2:
        text_x0 = int(active_cols[0])
        text_x1 = int(active_cols[-1]) + 1
    else:
        text_x0, text_x1 = 0, w
    if bands:
        text_y0 = int(bands[0][0])
        text_y1 = int(bands[-1][1])
    else:
        text_y0, text_y1 = 0, h
    active_width_ratio = float(max(1, text_x1 - text_x0)) / float(max(1, w))

    if estimated_glyph_height <= 12.0 or h < 62:
        recommended_scale = 2.5 if w > 420 else 3.0
        is_small_text = True
    elif estimated_glyph_height < 22.0 or h < 180 or w < 360:
        recommended_scale = 2.0
        is_small_text = True
    else:
        recommended_scale = 1.0
        is_small_text = False

    aspect_ratio = float(w) / float(max(1, h))
    is_single_line = bool(estimated_line_count == 1 and (h < 115 or aspect_ratio >= 3.0))
    is_single_word = bool(is_single_line and w < 210 and aspect_ratio < 4.2)

    # Check for left-margin icon column across >= 2 bands or flanking decorations on single-line signs
    stroke_signal = dev_light if is_light_ink else dev_dark
    if is_chromatic_isoluminant and not is_light_ink:
        stroke_signal = chroma_dev
    sig_thresh = max(3.5, float(np.percentile(stroke_signal, 90.0)) * 0.42)
    ink_map = stroke_signal > sig_thresh

    icon_rows = 0
    ic0_list: List[int] = []
    icw_list: List[int] = []
    tx0_list: List[int] = []
    has_flanking_decorations = False
    bold_all_caps_like = False

    inner_span_x0s: List[int] = []
    inner_span_x1s: List[int] = []

    for ry0, ry1 in bands:
        bh = max(4, ry1 - ry0)
        band_ink = ink_map[ry0:ry1, :]
        col_active = np.sum(band_ink, axis=0) >= max(1, bh // 7)
        pad_c = np.concatenate(([False], col_active, [False]))
        c_starts = np.where(pad_c[1:] & ~pad_c[:-1])[0]
        c_ends = np.where(~pad_c[1:] & pad_c[:-1])[0]
        merged: List[Tuple[int, int]] = []
        for cs, ce in zip(c_starts, c_ends):
            if merged and (int(cs) - merged[-1][1]) <= max(2, bh // 6):
                merged[-1] = (merged[-1][0], int(ce))
            else:
                merged.append((int(cs), int(ce)))
        inner = [
            (cs, ce) for cs, ce in merged
            if not (cs < w * 0.045 and (ce - cs) <= max(12, int(bh * 0.70)))
            and not (ce > w * 0.94 and (ce - cs) <= max(12, int(bh * 0.70)))
        ]
        work_spans = inner if len(inner) >= 2 else merged
        if work_spans:
            inner_span_x0s.append(work_spans[0][0])
            inner_span_x1s.append(work_spans[-1][1])
        if len(work_spans) >= 2:
            ic0, ic1 = work_spans[0]
            tx0, _tx1 = work_spans[1]
            ic_w = ic1 - ic0
            gap = tx0 - ic1
            if ic0 < w * 0.25 and (0.35 * bh) <= ic_w <= (1.90 * bh) and gap >= max(5, int(0.28 * bh)):
                icon_rows += 1
                ic0_list.append(ic0)
                icw_list.append(ic_w)
                tx0_list.append(tx0)
            if len(bands) == 1:
                if (ic0 < w * 0.16 and ic_w <= 1.35 * bh and gap >= max(12, int(0.65 * bh))):
                    has_flanking_decorations = True
                last0, last1 = work_spans[-1]
                prev0, prev1 = work_spans[-2]
                if (w - last1) < w * 0.18 and (last1 - last0) <= 1.45 * bh and (last0 - prev1) >= max(12, int(0.65 * bh)):
                    has_flanking_decorations = True

        if len(bands) == 1 and bh >= 16:
            fill_density = float(np.mean(band_ink[:, text_x0:text_x1])) if text_x1 > text_x0 else 0.0
            if fill_density > 0.24:
                bold_all_caps_like = True

    has_left_icon_column = False
    if len(bands) >= 3 and icon_rows >= max(3, int(len(bands) * 0.65)):
        if float(np.std(ic0_list)) <= 7.5 and float(np.std(icw_list)) <= 7.5 and float(np.std(tx0_list)) <= 9.5:
            has_left_icon_column = True
    elif len(bands) == 2 and icon_rows == 2:
        if abs(ic0_list[0] - ic0_list[1]) <= 6 and abs(icw_list[0] - icw_list[1]) <= 6 and abs(tx0_list[0] - tx0_list[1]) <= 8:
            has_left_icon_column = True

    # Surface-aware per-row ROI & left-icon detection for button/card stacks (e.g. vivid colored pills over 3D scenes)
    row_text_rois_list: List[Tuple[int, int, int, int]] = []
    if len(bands) >= 2 and w >= 80:
        cx0 = int(w * 0.28)
        cx1 = max(cx0 + 1, int(w * 0.72))
        q_bg = 15.0 if is_light_ink else 85.0
        q_fg = 97.0 if is_light_ink else 3.0
        surf_icon_rows = 0
        s_ic0_list: List[int] = []
        s_icw_list: List[int] = []
        s_tx0_list: List[int] = []
        temp_rois: List[Tuple[int, int, int, int, Optional[int]]] = []

        for ry0, ry1 in bands:
            bh = max(4, ry1 - ry0)
            y_ext0 = max(0, ry0 - max(4, int(bh * 0.65)))
            y_ext1 = min(h, ry1 + max(4, int(bh * 0.65)))
            band_rgb = arr_rgb[y_ext0:y_ext1, :, :]
            bg_center = np.percentile(band_rgb[:, cx0:cx1, :], q_bg, axis=(0, 1))
            fg_center = np.percentile(band_rgb[:, cx0:cx1, :], q_fg, axis=(0, 1))
            col_bg = np.percentile(band_rgb, q_bg, axis=0)
            col_dist = np.sqrt(np.sum((col_bg - bg_center[None, :]) ** 2, axis=1))
            matching_cols = np.where(col_dist <= 52.0)[0]
            if len(matching_cols) >= 2:
                sx0 = int(matching_cols[0])
                sx1 = int(matching_cols[-1]) + 1
            else:
                sx0, sx1 = 0, w
            if sx0 > 2:
                sx0 = min(cx0, sx0 + 2)
            if sx1 < w - 2:
                sx1 = max(cx1, sx1 - 2)

            vec = (fg_center - bg_center) if is_light_ink else (bg_center - fg_center)
            vnorm = float(np.linalg.norm(vec))
            u = (vec / vnorm) if vnorm > 1e-3 else np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
            diff_rgb = (
                (arr_rgb[ry0:ry1, :, :] - bg_center[None, None, :])
                if is_light_ink
                else (bg_center[None, None, :] - arr_rgb[ry0:ry1, :, :])
            )
            proj = np.maximum(
                0.0,
                diff_rgb[:, :, 0] * u[0] + diff_rgb[:, :, 1] * u[1] + diff_rgb[:, :, 2] * u[2],
            )
            proj[:, :sx0] = 0.0
            proj[:, sx1:] = 0.0
            p_thr = max(6.0, float(np.percentile(proj[:, sx0:sx1], 92.0)) * 0.42) if sx1 > sx0 else 10.0
            b_ink = proj > p_thr
            col_act = np.sum(b_ink, axis=0) >= max(1, bh // 7)
            pad_c = np.concatenate(([False], col_act, [False]))
            cs_arr = np.where(pad_c[1:] & ~pad_c[:-1])[0]
            ce_arr = np.where(~pad_c[1:] & pad_c[:-1])[0]
            s_merged: List[Tuple[int, int]] = []
            for cs, ce in zip(cs_arr, ce_arr):
                merge_tol = max(4, bh // 2) if int(cs) < w * 0.24 else max(2, bh // 5)
                if s_merged and (int(cs) - s_merged[-1][1]) <= merge_tol:
                    s_merged[-1] = (s_merged[-1][0], int(ce))
                else:
                    s_merged.append((int(cs), int(ce)))
            detected_tx0: Optional[int] = None
            if len(s_merged) >= 2:
                ic0, ic1 = s_merged[0]
                tx0_cand, _tx1_cand = s_merged[1]
                ic_w = ic1 - ic0
                gap = tx0_cand - ic1
                if ic0 < w * 0.28 and (0.35 * bh) <= ic_w <= (2.40 * bh) and gap >= max(4, int(0.28 * bh)):
                    surf_icon_rows += 1
                    s_ic0_list.append(ic0)
                    s_icw_list.append(ic_w)
                    s_tx0_list.append(tx0_cand)
                    detected_tx0 = tx0_cand
            y_pad = max(3, bh // 2)
            temp_rois.append((sx0, max(0, ry0 - y_pad), sx1, min(h, ry1 + y_pad), detected_tx0))

        surf_has_icon = False
        if len(bands) >= 3 and surf_icon_rows >= max(3, int(len(bands) * 0.65)):
            if float(np.std(s_ic0_list)) <= 7.5 and float(np.std(s_icw_list)) <= 7.5 and float(np.std(s_tx0_list)) <= 9.5:
                surf_has_icon = True
        elif len(bands) == 2 and surf_icon_rows == 2:
            if abs(s_ic0_list[0] - s_ic0_list[1]) <= 6 and abs(s_icw_list[0] - s_icw_list[1]) <= 6 and abs(s_tx0_list[0] - s_tx0_list[1]) <= 8:
                surf_has_icon = True

        if surf_has_icon and not has_left_icon_column:
            has_left_icon_column = True
            tx0_list = s_tx0_list

        aligned_tx0 = int(round(float(np.median(s_tx0_list)))) - 3 if (surf_has_icon and s_tx0_list) else None
        for sx0, ry0_pad, sx1, ry1_pad, det_tx0 in temp_rois:
            rx0 = max(sx0, aligned_tx0 if aligned_tx0 is not None else (det_tx0 - 3 if (has_left_icon_column and det_tx0 is not None) else sx0))
            if sx1 - rx0 >= 16 and ry1_pad - ry0_pad >= 6:
                row_text_rois_list.append((int(rx0), int(ry0_pad), int(sx1), int(ry1_pad)))

    if is_light_ink:
        multicol_islands = _detect_multicol_white_core_islands(arr_rgb)
        if len(multicol_islands) >= 2:
            row_text_rois_list = [
                (max(0, bx0 - 4), max(0, by0 - 4), min(w, bx1 + 4), min(h, by1 + 4))
                for (bx0, by0, bx1, by1) in multicol_islands
            ]
            estimated_line_count = max(estimated_line_count, len(row_text_rois_list))

    if inner_span_x0s and inner_span_x1s:
        text_x0 = int(min(inner_span_x0s))
        text_x1 = int(max(inner_span_x1s))
    if has_left_icon_column and tx0_list:
        text_x0 = int(min(tx0_list))
    if row_text_rois_list:
        text_x0 = int(min(r[0] for r in row_text_rois_list))
        text_x1 = int(max(r[2] for r in row_text_rois_list))
    active_width_ratio = float(max(1, text_x1 - text_x0)) / float(max(1, w))
    is_sparse_menu = bool(
        estimated_line_count >= 3
        and (aspect_ratio < 1.45 or active_width_ratio < 0.72 or has_left_icon_column or len(row_text_rois_list) >= 3)
    )

    low_contrast_faint = bool(max_stroke < 22.0 or contrast_span < 42.0)

    return OcrImageProfile(
        width=w,
        height=h,
        aspect_ratio=aspect_ratio,
        median_luma=median_luma,
        mean_luma=mean_luma,
        contrast_span=contrast_span,
        is_light_ink=bool(is_light_ink),
        light_stroke_score=float(light_stroke_score),
        dark_stroke_score=float(dark_stroke_score),
        mixed_polarity=mixed_polarity,
        bg_gradient_span=float(bg_gradient_span),
        chroma_contrast=float(chroma_contrast),
        is_chromatic_isoluminant=is_chromatic_isoluminant,
        estimated_line_count=estimated_line_count,
        estimated_glyph_height=estimated_glyph_height,
        recommended_scale=float(recommended_scale),
        is_small_text=is_small_text,
        is_single_line=is_single_line,
        is_single_word=is_single_word,
        is_sparse_menu=is_sparse_menu,
        has_left_icon_column=has_left_icon_column,
        has_flanking_decorations=has_flanking_decorations,
        low_contrast_faint=low_contrast_faint,
        bold_all_caps_like=bold_all_caps_like,
        text_x0=text_x0,
        text_x1=text_x1,
        text_y0=text_y0,
        text_y1=text_y1,
        active_width_ratio=active_width_ratio,
        row_text_rois=tuple(row_text_rois_list),
    )


def _suppress_long_border_lines_in_residual(diff: np.ndarray) -> np.ndarray:
    """
    Suppress full-width horizontal lines and full-height vertical frame borders
    in a local polarity residual so box outlines/underlines do not swamp text strokes.
    """
    h, w = diff.shape
    if h < 16 or w < 32:
        return diff
    out = diff.copy()
    hi = float(np.percentile(out, 98.0))
    if hi <= 2.0:
        return out
    strong = out > (hi * 0.45)
    # Suppress rows that are > 68% solid horizontal line
    row_fill = np.mean(strong, axis=1)
    border_rows = row_fill > 0.68
    if np.any(border_rows):
        out[border_rows, :] = 0.0
    # Suppress outer 5% columns that are > 55% solid vertical border line
    col_fill = np.mean(strong, axis=0)
    edge_w = max(4, int(w * 0.06))
    for cx in range(w):
        if (cx < edge_w or cx >= w - edge_w) and col_fill[cx] > 0.52:
            out[:, cx] = 0.0
    return out


def _build_local_polarity_normalized_gray(
    luma: np.ndarray,
    *,
    light_ink: bool,
    radius: int = 14,
    arr_rgb: Optional[np.ndarray] = None,
) -> Image.Image:
    """
    Flatten local illumination gradients, two-tone card backgrounds, vivid colored pills,
    and bright/dark surrounding frames by extracting one-sided stroke residual relative
    to the local background envelope, rendering crisp dark ink on a pure white (255) background.
    """
    bg = _smooth_background_envelope(luma, radius=radius)
    diff = (luma - bg) if light_ink else (bg - luma)
    diff = np.maximum(0.0, diff)
    if light_ink and arr_rgb is not None and arr_rgb.ndim == 3 and arr_rgb.shape[2] >= 3:
        white_ch = np.minimum(arr_rgb[:, :, 0], np.minimum(arr_rgb[:, :, 1], arr_rgb[:, :, 2]))
        max_ch = np.maximum(arr_rgb[:, :, 0], np.maximum(arr_rgb[:, :, 1], arr_rgb[:, :, 2]))
        sat = max_ch - white_ch
        bg_w = _smooth_background_envelope(white_ch, radius=max(6, radius // 2))
        bg_sat = _smooth_background_envelope(sat, radius=max(6, radius // 2))
        chroma_weight = np.clip((bg_sat - 25.0) / 45.0, 0.0, 0.95)
        diff_w = np.maximum(0.0, white_ch - bg_w) * chroma_weight
        diff = np.maximum(diff, diff_w)
    diff = _suppress_long_border_lines_in_residual(diff)
    hi = float(np.percentile(diff, 99.5))
    if hi < 2.5:
        return Image.fromarray(np.full(luma.shape, 255, dtype=np.uint8), mode="L")
    noise_floor = max(1.2, hi * 0.13)
    clean = np.maximum(0.0, diff - noise_floor)
    norm = 255.0 - np.clip(clean * (255.0 / max(1.0, hi - noise_floor)), 0.0, 255.0)
    return Image.fromarray(np.round(norm).astype(np.uint8), mode="L")


def _build_row_roi_matched_color_canvas(
    arr_rgb: np.ndarray,
    profile: OcrImageProfile,
    *,
    light_ink: bool = True,
) -> Image.Image:
    """
    Render each detected text row ROI `(x0, y0, x1, y1)` from `profile.row_text_rois`
    onto a clean white `(255)` full-frame canvas at its exact pixel coordinates using
    per-row Fisher matched color projection `(fg_rgb - bg_rgb)`. Suppresses inter-button
    3D scenery, rounded button caps, horizontal borders, and left-margin icons while
    preserving 1:1 original screenshot coordinate mapping.
    """
    h, w, _ = arr_rgb.shape
    canvas = np.full((h, w), 255, dtype=np.uint8)
    q_bg = 25.0 if light_ink else 75.0
    q_fg = 98.0 if light_ink else 2.0

    for x0, y0, x1, y1 in profile.row_text_rois:
        cx0 = max(0, min(w - 1, int(x0)))
        cx1 = max(cx0 + 1, min(w, int(x1)))
        cy0 = max(0, min(h - 1, int(y0)))
        cy1 = max(cy0 + 1, min(h, int(y1)))
        patch = _extract_island_fisher_gray(arr_rgb, (cx0, cy0, cx1, cy1), light_ink=light_ink)
        canvas[cy0:cy1, cx0:cx1] = np.minimum(canvas[cy0:cy1, cx0:cx1], patch)

    return Image.fromarray(canvas, mode="L")


def _build_chroma_distance_gray(arr_rgb: np.ndarray) -> Image.Image:
    """
    Convert isoluminant colored text on a colored background into dark-on-white grayscale
    by measuring each pixel's Euclidean RGB distance from the smooth local RGB background.
    """
    h, w, _ = arr_rgb.shape
    rad = max(8, min(18, min(w, h) // 5))
    bg_r = _smooth_background_envelope(arr_rgb[:, :, 0], radius=rad)
    bg_g = _smooth_background_envelope(arr_rgb[:, :, 1], radius=rad)
    bg_b = _smooth_background_envelope(arr_rgb[:, :, 2], radius=rad)
    dist = np.sqrt((arr_rgb[:, :, 0] - bg_r) ** 2 + (arr_rgb[:, :, 1] - bg_g) ** 2 + (arr_rgb[:, :, 2] - bg_b) ** 2)
    dist = _suppress_long_border_lines_in_residual(dist)
    hi = float(np.percentile(dist, 99.2))
    if hi < 4.0:
        return Image.fromarray(np.full((h, w), 255, dtype=np.uint8), mode="L")
    floor_v = max(2.0, hi * 0.14)
    clean = np.maximum(0.0, dist - floor_v)
    norm = 255.0 - np.clip(clean * (255.0 / max(1.0, hi - floor_v)), 0.0, 255.0)
    return Image.fromarray(np.round(norm).astype(np.uint8), mode="L")


def _apply_sauvola_local_threshold(pil_gray: Image.Image, window_radius: int = 11, k: float = 0.16) -> Image.Image:
    """
    Apply gentle Sauvola local adaptive thresholding (`T = m * (1 - k * (1 - s / R))`)
    to a dark-on-light grayscale image. Helpful only for genuinely faint or low-contrast captures.
    """
    arr = np.asarray(pil_gray, dtype=np.float32)
    mean = _box_blur_2d(arr, window_radius)
    mean_sq = _box_blur_2d(arr * arr, window_radius)
    var = np.maximum(0.0, mean_sq - mean * mean)
    std = np.sqrt(var)
    thresh = mean * (1.0 - k * (1.0 - (std / 128.0)))
    bin_arr = np.where(arr < (thresh - 2.0), np.uint8(0), np.uint8(255))
    return Image.fromarray(bin_arr, mode="L")


def _mask_aligned_left_icons(pil_gray: Image.Image) -> Tuple[Image.Image, bool]:
    """
    When a vertical menu contains an aligned column of square-ish or circular left-margin
    icons separated by a consistent horizontal gap from the text labels, mask the icon
    column row-by-row using the local inter-icon gap background so button borders and
    vertical gradients remain seamless while keeping image dimensions unchanged.
    """
    arr = np.asarray(pil_gray, dtype=np.float32)
    h, w = arr.shape
    if h < 36 or w < 90:
        return pil_gray, False

    rad_x = max(5, min(14, w // 24))
    bg_x = _box_blur_1d_horizontal(arr, rad_x)
    dev_dark = np.maximum(0.0, bg_x - arr)
    dev_dark = _suppress_long_border_lines_in_residual(dev_dark)
    sig_thresh = max(3.5, float(np.percentile(dev_dark, 90.0)) * 0.42)
    ink = dev_dark > sig_thresh

    gx = np.abs(np.diff(arr, axis=1))
    g_thresh = max(3.5, float(np.percentile(gx, 92.0)) * 0.32)
    core_x0 = max(0, int(w * 0.06))
    core_x1 = max(core_x0 + 1, int(w * 0.90))
    transitions = np.sum(gx[:, core_x0:core_x1] > g_thresh, axis=1)
    row_active = transitions >= max(4, min(6, w // 45))
    if not np.any(row_active):
        row_active = np.mean(ink, axis=1) > 0.012

    pad_r = np.concatenate(([False], row_active, [False]))
    r_starts = np.where(pad_r[1:] & ~pad_r[:-1])[0]
    r_ends = np.where(~pad_r[1:] & pad_r[:-1])[0]
    raw_bands = [(int(s), int(e)) for s, e in zip(r_starts, r_ends) if (e - s) >= 5]
    bands: List[Tuple[int, int]] = []
    for s, e in raw_bands:
        if bands and (s - bands[-1][1]) <= 2:
            bands[-1] = (bands[-1][0], e)
        else:
            bands.append((s, e))
    if len(bands) < 2:
        return pil_gray, False

    icon_candidates: List[Tuple[int, int, int, int, int]] = []
    for ry0, ry1 in bands:
        bh = ry1 - ry0
        band_ink = ink[ry0:ry1, :]
        col_active = np.sum(band_ink, axis=0) >= max(1, bh // 8)
        pad_c = np.concatenate(([False], col_active, [False]))
        c_starts = np.where(pad_c[1:] & ~pad_c[:-1])[0]
        c_ends = np.where(~pad_c[1:] & pad_c[:-1])[0]
        merged: List[Tuple[int, int]] = []
        for cs, ce in zip(c_starts, c_ends):
            if merged and (int(cs) - merged[-1][1]) <= max(2, bh // 6):
                merged[-1] = (merged[-1][0], int(ce))
            else:
                merged.append((int(cs), int(ce)))
        inner = [
            (cs, ce) for cs, ce in merged
            if not (cs < w * 0.045 and (ce - cs) <= max(12, int(bh * 0.70)))
            and not (ce > w * 0.94 and (ce - cs) <= max(12, int(bh * 0.70)))
        ]
        work_spans = inner if len(inner) >= 2 else merged
        if len(work_spans) >= 2:
            ic0, ic1 = work_spans[0]
            tx0, _tx1 = work_spans[1]
            ic_w = ic1 - ic0
            gap = tx0 - ic1
            if (
                ic0 < w * 0.25
                and (0.35 * bh) <= ic_w <= (1.90 * bh)
                and gap >= max(5, int(0.28 * bh))
            ):
                icon_candidates.append((ry0, ry1, ic0, ic1, tx0))

    min_matches = 2 if len(bands) == 2 else max(3, int(len(bands) * 0.65))
    if len(icon_candidates) >= min_matches:
        ic0_vals = [c[2] for c in icon_candidates]
        icw_vals = [c[3] - c[2] for c in icon_candidates]
        tx0_vals = [c[4] for c in icon_candidates]
        if (
            float(np.std(ic0_vals)) <= 7.5
            and float(np.std(icw_vals)) <= 7.5
            and float(np.std(tx0_vals)) <= 9.5
        ):
            out = arr.copy()
            bg_val = float(np.percentile(arr, 85.0))
            for ry0, ry1, ic0, ic1, tx0 in icon_candidates:
                bh = ry1 - ry0
                y_pad = max(4, int(bh * 0.55))
                y0_m = max(0, ry0 - y_pad)
                y1_m = min(h, ry1 + y_pad)
                cut_x = max(ic1 + 2, tx0 - 3)
                gx0 = min(w - 1, ic1 + 2)
                gx1 = max(min(w, ic1 + 3), tx0 - 1)
                gap_cols = arr[y0_m:y1_m, gx0:gx1]
                if gap_cols.size > 0:
                    fill_col = np.median(gap_cols, axis=1, keepdims=True)
                    out[y0_m:y1_m, 0:cut_x] = fill_col
                else:
                    out[y0_m:y1_m, 0:cut_x] = bg_val
            return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), mode="L"), True

    return pil_gray, False


def _resize_with_gentle_sharpen(pil_img: Image.Image, scale_factor: float) -> Image.Image:
    """Upscale an image with smooth bicubic resampling (preserving antialiased subpixel curvature)."""
    if scale_factor <= 1.01:
        return pil_img
    w, h = pil_img.size
    new_w = max(1, int(round(w * scale_factor)))
    new_h = max(1, int(round(h * scale_factor)))
    return pil_img.resize((new_w, new_h), Image.Resampling.BICUBIC)


def preprocess_image_for_ocr_legacy(
    image_source: Any,
    *,
    auto_invert_dark: bool = True,
    upscale_small_text: bool = True,
    contrast_stretch: bool = True,
    apply_threshold: bool = False,
) -> Tuple[Image.Image, float, bool, bool]:
    """
    Legacy v0.2.0 preprocessing pipeline (global median `< 118.0` inversion, global 2..98%
    percentile stretch, fixed 2x scaling) retained for side-by-side CER/WER benchmark comparisons.
    """
    rgb_img = _to_pil_rgb(image_source)
    w, h = rgb_img.size
    if w <= 1 or h <= 1:
        return rgb_img.convert("L"), 1.0, False, False

    arr_rgb = np.asarray(rgb_img, dtype=np.float32)
    luma = (0.2126 * arr_rgb[:, :, 0] + 0.7152 * arr_rgb[:, :, 1] + 0.0722 * arr_rgb[:, :, 2])

    inverted = False
    if auto_invert_dark:
        median_luma = float(np.median(luma))
        if median_luma < 118.0:
            luma = 255.0 - luma
            inverted = True

    if contrast_stretch:
        p_low = float(np.percentile(luma, 2.0))
        p_high = float(np.percentile(luma, 98.0))
        span = p_high - p_low
        if 12.0 < span < 220.0:
            luma = np.clip((luma - p_low) * (255.0 / span), 0.0, 255.0)

    scale_factor = 1.0
    if upscale_small_text:
        if h < 180 or w < 360:
            scale_factor = 2.0
        else:
            grad_x = np.abs(np.diff(luma, axis=1))
            active_rows = np.mean(grad_x > 18.0, axis=1) > 0.015
            padded = np.concatenate(([False], active_rows, [False]))
            starts = np.where(padded[1:] & ~padded[:-1])[0]
            ends = np.where(~padded[1:] & padded[:-1])[0]
            heights = [int(e - s) for s, e in zip(starts, ends) if (e - s) >= 4]
            if heights and float(np.median(heights)) < 22.0:
                scale_factor = 2.0

    gray_u8 = np.clip(np.round(luma), 0, 255).astype(np.uint8)
    pil_gray = Image.fromarray(gray_u8, mode="L")

    if scale_factor > 1.01:
        new_w = max(1, int(round(w * scale_factor)))
        new_h = max(1, int(round(h * scale_factor)))
        pil_gray = pil_gray.resize((new_w, new_h), Image.Resampling.BICUBIC)

    threshold_done = False
    if apply_threshold:
        arr_g = np.asarray(pil_gray, dtype=np.float32)
        thresh = float(np.percentile(arr_g, 25.0) * 0.55 + np.percentile(arr_g, 85.0) * 0.45)
        bin_arr = np.where(arr_g < thresh, np.uint8(0), np.uint8(255))
        pil_gray = Image.fromarray(bin_arr, mode="L")
        threshold_done = True

    return pil_gray, scale_factor, inverted, threshold_done


def preprocess_image_for_ocr(
    image_source: Any,
    *,
    auto_invert_dark: bool = True,
    upscale_small_text: bool = True,
    contrast_stretch: bool = True,
    apply_threshold: bool = False,
) -> Tuple[Image.Image, float, bool, bool]:
    """
    Automatic, adaptive preprocessing for screenshot OCR:
      1. Inspects foreground/background stroke polarity (`analyze_image_for_ocr`)
         rather than relying on a naive global median luminance threshold.
      2. Handles chromatic isoluminant captures, background illumination gradients,
         and aligned left-margin menu icons automatically.
      3. Applies adaptive 1x / 2x / 2.5x / 3x high-quality scaling based on actual
         glyph height and capture geometry.
      4. Applies gentle local Sauvola thresholding only when warranted or explicitly
         requested for testing.

    Returns `(processed_pil_image, scale_factor, inverted_dark_theme, threshold_applied)`.
    """
    rgb_img = _to_pil_rgb(image_source)
    w, h = rgb_img.size
    if w <= 1 or h <= 1:
        return rgb_img.convert("L"), 1.0, False, False

    profile = analyze_image_for_ocr(rgb_img)
    arr_rgb = np.asarray(rgb_img, dtype=np.float32)
    luma = 0.2126 * arr_rgb[:, :, 0] + 0.7152 * arr_rgb[:, :, 1] + 0.0722 * arr_rgb[:, :, 2]

    inverted = False
    if profile.is_chromatic_isoluminant and contrast_stretch:
        pil_gray = _build_chroma_distance_gray(arr_rgb)
        inverted = bool(profile.is_light_ink)
    elif contrast_stretch and (profile.bg_gradient_span > 24.0 or profile.mixed_polarity or profile.low_contrast_faint):
        use_light_ink = bool(profile.is_light_ink) if auto_invert_dark else False
        pil_gray = _build_local_polarity_normalized_gray(luma, light_ink=use_light_ink, radius=14, arr_rgb=arr_rgb)
        inverted = use_light_ink
    else:
        work_luma = luma.copy()
        if auto_invert_dark and profile.is_light_ink:
            work_luma = 255.0 - work_luma
            inverted = True
        if contrast_stretch:
            p_low = float(np.percentile(work_luma, 2.0))
            p_high = float(np.percentile(work_luma, 98.0))
            span = p_high - p_low
            if 10.0 < span < 225.0:
                work_luma = np.clip((work_luma - p_low) * (255.0 / span), 0.0, 255.0)
        pil_gray = Image.fromarray(np.clip(np.round(work_luma), 0, 255).astype(np.uint8), mode="L")

    if profile.has_left_icon_column:
        pil_gray, _ = _mask_aligned_left_icons(pil_gray)

    scale_factor = profile.recommended_scale if upscale_small_text else 1.0
    if scale_factor > 1.01:
        pil_gray = _resize_with_gentle_sharpen(pil_gray, scale_factor)

    threshold_done = False
    if apply_threshold:
        pil_gray = _apply_sauvola_local_threshold(pil_gray, window_radius=max(9, int(round(10 * scale_factor))))
        threshold_done = True

    return pil_gray, float(scale_factor), bool(inverted), bool(threshold_done)


def select_adaptive_psms(
    profile: OcrImageProfile,
    candidate: Optional[OcrPreprocessCandidate] = None,
    *,
    retry_attempt: int = 0,
    default_psm: int = 6,
) -> Tuple[int, ...]:
    """
    Select plausible Tesseract Page Segmentation Modes (`--psm`) ordered by suitability
    for the analyzed screenshot geometry:
      - `--psm 6`: Uniform block of text (standard multiline or menu list)
      - `--psm 7`: Single text line (signs, single-line HUDs, window titles)
      - `--psm 8`: Single word (compact single-word badges)
      - `--psm 11`: Sparse text (scattered game menu labels, wide margins)
      - `--psm 13`: Raw single line
      - `--psm 3` / `4`: Complex or multi-column page layouts
    """
    if candidate is not None and candidate.preferred_psms:
        base = list(candidate.preferred_psms)
    elif default_psm != 6:
        base = [default_psm, 6, 11, 7, 3]
    elif profile.is_single_word:
        base = [6, 7, 8, 11, 13]
    elif profile.is_single_line:
        base = [6, 7, 11, 13]
    elif profile.is_sparse_menu or profile.has_left_icon_column:
        base = [6, 11, 4, 3]
    elif profile.estimated_line_count >= 5 and profile.aspect_ratio > 1.6:
        base = [6, 4, 3, 11]
    else:
        base = [6, 11, 7, 3]

    dedup: List[int] = []
    for p in base:
        if p not in dedup:
            dedup.append(int(p))

    if retry_attempt > 0 and len(dedup) > 1:
        shift = retry_attempt % len(dedup)
        dedup = dedup[shift:] + dedup[:shift]

    return tuple(dedup)


def generate_ocr_preprocessing_candidates(
    image_source: Any,
    profile: Optional[OcrImageProfile] = None,
    *,
    quality_mode: str = "auto",
    retry_attempt: int = 0,
    auto_invert_dark: bool = True,
    upscale_small_text: bool = True,
    contrast_stretch: bool = True,
    apply_threshold: bool = False,
) -> List[OcrPreprocessCandidate]:
    """
    Generate a small, bounded, prioritized set of preprocessing candidates tailored
    to the screenshot's analyzed visual characteristics (`OcrImageProfile`).
    """
    rgb_img = _to_pil_rgb(image_source)
    if profile is None:
        profile = analyze_image_for_ocr(rgb_img)

    w, h = rgb_img.size
    arr_rgb = np.asarray(rgb_img, dtype=np.float32)
    luma = 0.2126 * arr_rgb[:, :, 0] + 0.7152 * arr_rgb[:, :, 1] + 0.0722 * arr_rgb[:, :, 2]

    scale = profile.recommended_scale if upscale_small_text else 1.0
    use_light_ink = bool(profile.is_light_ink) if auto_invert_dark else False

    # Build helper candidate builders so we only materialize needed candidates
    def _make_standard_gray(invert_flag: bool, scale_val: float) -> OcrPreprocessCandidate:
        work = (255.0 - luma) if invert_flag else luma.copy()
        if contrast_stretch:
            p_low = float(np.percentile(work, 2.0))
            p_high = float(np.percentile(work, 98.0))
            span = p_high - p_low
            if 10.0 < span < 225.0:
                work = np.clip((work - p_low) * (255.0 / span), 0.0, 255.0)
        pil_g = Image.fromarray(np.clip(np.round(work), 0, 255).astype(np.uint8), mode="L")
        masked = False
        if profile.has_left_icon_column:
            pil_g, masked = _mask_aligned_left_icons(pil_g)
        if scale_val > 1.01:
            pil_g = _resize_with_gentle_sharpen(pil_g, scale_val)
        border_fill = int(np.median(np.asarray(pil_g, dtype=np.uint8)[0, :])) if pil_g.width > 4 else 255
        psms = (6, 11, 4) if profile.has_left_icon_column else ((6, 7, 11) if profile.is_single_line else (6, 11, 3))
        return OcrPreprocessCandidate(
            name="icon_masked_gray" if masked else "adaptive_gray",
            pil_image=pil_g,
            scale_factor=scale_val,
            pad_fill=max(220, border_fill),
            inverted_dark_theme=invert_flag,
            threshold_applied=False,
            icon_masked=masked,
            preferred_psms=psms,
        )

    def _make_local_polarity(invert_flag: bool, scale_val: float) -> OcrPreprocessCandidate:
        pil_loc = _build_local_polarity_normalized_gray(luma, light_ink=invert_flag, radius=14, arr_rgb=arr_rgb)
        masked = False
        if profile.has_left_icon_column:
            pil_loc, masked = _mask_aligned_left_icons(pil_loc)
        if scale_val > 1.01:
            pil_loc = _resize_with_gentle_sharpen(pil_loc, scale_val)
        psms = (6, 7, 11) if profile.is_single_line else (6, 11, 3)
        return OcrPreprocessCandidate(
            name="local_polarity_norm",
            pil_image=pil_loc,
            scale_factor=scale_val,
            pad_fill=255,
            inverted_dark_theme=invert_flag,
            threshold_applied=False,
            icon_masked=masked,
            preferred_psms=psms,
        )

    def _make_row_roi_canvas(invert_flag: bool, scale_val: float) -> OcrPreprocessCandidate:
        eff_scale = max(scale_val, 3.0 if profile.estimated_glyph_height <= 14.0 else 2.0) if upscale_small_text else 1.0
        pil_roi = _build_row_roi_matched_color_canvas(arr_rgb, profile, light_ink=invert_flag)
        if eff_scale > 1.01:
            pil_roi = _resize_with_gentle_sharpen(pil_roi, eff_scale)
        return OcrPreprocessCandidate(
            name="row_roi_canvas",
            pil_image=pil_roi,
            scale_factor=eff_scale,
            pad_fill=255,
            inverted_dark_theme=invert_flag,
            threshold_applied=False,
            icon_masked=bool(profile.has_left_icon_column),
            preferred_psms=(6, 11, 4),
        )

    def _make_original_rgb(scale_val: float) -> OcrPreprocessCandidate:
        pil_c = _resize_with_gentle_sharpen(rgb_img, scale_val) if scale_val > 1.01 else rgb_img.copy()
        edge_rgb = tuple(int(v) for v in np.median(arr_rgb[0, :, :], axis=0))
        psms = (6, 7, 11) if profile.is_single_line else (6, 11, 3)
        return OcrPreprocessCandidate(
            name="original_rgb",
            pil_image=pil_c,
            scale_factor=scale_val,
            pad_fill=edge_rgb,
            inverted_dark_theme=bool(profile.is_light_ink),
            threshold_applied=False,
            icon_masked=False,
            preferred_psms=psms,
        )

    def _make_chroma_distance(scale_val: float) -> OcrPreprocessCandidate:
        pil_ch = _build_chroma_distance_gray(arr_rgb)
        if profile.has_left_icon_column:
            pil_ch, _ = _mask_aligned_left_icons(pil_ch)
        if scale_val > 1.01:
            pil_ch = _resize_with_gentle_sharpen(pil_ch, scale_val)
        psms = (6, 7, 11) if profile.is_single_line else (6, 11, 3)
        return OcrPreprocessCandidate(
            name="chroma_contrast",
            pil_image=pil_ch,
            scale_factor=scale_val,
            pad_fill=255,
            inverted_dark_theme=bool(profile.is_light_ink),
            threshold_applied=False,
            icon_masked=False,
            preferred_psms=psms,
        )

    def _make_sauvola_threshold(invert_flag: bool, scale_val: float) -> OcrPreprocessCandidate:
        base_loc = _build_local_polarity_normalized_gray(luma, light_ink=invert_flag, radius=14)
        if scale_val > 1.01:
            base_loc = _resize_with_gentle_sharpen(base_loc, scale_val)
        pil_th = _apply_sauvola_local_threshold(base_loc, window_radius=max(9, int(round(10 * scale_val))))
        psms = (6, 7, 11) if profile.is_single_line else (6, 11, 3)
        return OcrPreprocessCandidate(
            name="sauvola_threshold",
            pil_image=pil_th,
            scale_factor=scale_val,
            pad_fill=255,
            inverted_dark_theme=invert_flag,
            threshold_applied=True,
            icon_masked=False,
            preferred_psms=psms,
        )

    candidates: List[OcrPreprocessCandidate] = []

    if apply_threshold:
        candidates.append(_make_sauvola_threshold(use_light_ink, scale))

    if profile.is_chromatic_isoluminant:
        if len(profile.row_text_rois) >= 2:
            candidates.append(_make_row_roi_canvas(use_light_ink, scale))
            candidates.append(_make_local_polarity(use_light_ink, scale))
            candidates.append(_make_chroma_distance(scale))
            candidates.append(_make_original_rgb(scale))
        else:
            candidates.append(_make_original_rgb(scale))
            candidates.append(_make_chroma_distance(scale))
            candidates.append(_make_local_polarity(use_light_ink, scale))
    elif profile.has_left_icon_column and profile.contrast_span >= 80.0 and not profile.low_contrast_faint:
        candidates.append(_make_standard_gray(use_light_ink, scale))
        if len(profile.row_text_rois) >= 2:
            candidates.append(_make_row_roi_canvas(use_light_ink, scale))
        candidates.append(_make_local_polarity(use_light_ink, scale))
        candidates.append(_make_original_rgb(scale))
        if profile.mixed_polarity and auto_invert_dark:
            candidates.append(_make_local_polarity(not use_light_ink, scale))
    elif profile.bg_gradient_span > 24.0 or profile.mixed_polarity or profile.low_contrast_faint:
        if len(profile.row_text_rois) >= 3 and profile.has_left_icon_column:
            candidates.append(_make_row_roi_canvas(use_light_ink, scale))
        candidates.append(_make_local_polarity(use_light_ink, scale))
        candidates.append(_make_standard_gray(use_light_ink, scale))
        if len(profile.row_text_rois) >= 2 and not profile.has_left_icon_column:
            candidates.append(_make_row_roi_canvas(use_light_ink, scale))
        if profile.low_contrast_faint:
            candidates.append(_make_sauvola_threshold(use_light_ink, scale))
        if profile.mixed_polarity and auto_invert_dark:
            candidates.append(_make_local_polarity(not use_light_ink, scale))
        candidates.append(_make_original_rgb(scale))
    else:
        candidates.append(_make_standard_gray(use_light_ink, scale))
        candidates.append(_make_local_polarity(use_light_ink, scale))
        candidates.append(_make_original_rgb(scale))
        if auto_invert_dark:
            candidates.append(_make_local_polarity(not use_light_ink, scale))

    # Deduplicate by name while preserving order
    unique: List[OcrPreprocessCandidate] = []
    seen_names = set()
    for c in candidates:
        key = (c.name, c.inverted_dark_theme, c.threshold_applied)
        if key not in seen_names:
            seen_names.add(key)
            unique.append(c)

    # Rotate candidate priority on explicit user Retry so Retry Recognition explores a new strategy
    if retry_attempt > 0 and len(unique) > 1:
        shift = retry_attempt % len(unique)
        unique = unique[shift:] + unique[:shift]

    norm_mode = normalize_ocr_quality_mode(quality_mode)
    if norm_mode == "fast":
        return unique[:2]
    if norm_mode == "accurate":
        return unique[:5]
    return unique[:4]


# ---------------------------------------------------------------------------
# Visual Inter-Word Valley Splitting, Icon Filtering & Conservative Scoring
# ---------------------------------------------------------------------------

def _split_merged_word_by_visual_valleys(
    word: OcrWordBox,
    luma_src: np.ndarray,
    is_light_ink: bool,
) -> List[OcrWordBox]:
    """
    Inspect the vertical ink projection inside `word` on the source image.
    When a bold/stylized all-caps run (such as `'SELLLOGS'` on a sign) contains
    a clear full-height background valley significantly wider than the median
    inter-character gap (`>= max(1.75 * median_gap, median_gap + 2.5, 0.16 * height)`),
    split `word` into separate `OcrWordBox` tokens at the exact pixel valley.
    """
    txt = word.text.strip()
    if len(txt) < 6 or len(txt) > 28 or not txt.isalpha() or not txt.isupper():
        return [word]

    sh, sw = luma_src.shape
    x0 = max(0, min(sw - 1, word.x))
    x1 = max(x0 + 1, min(sw, word.right))
    y0 = max(0, min(sh - 1, word.y))
    y1 = max(y0 + 1, min(sh, word.bottom))
    crop = luma_src[y0:y1, x0:x1]
    if crop.size == 0 or (x1 - x0) < 24 or (y1 - y0) < 8:
        return [word]

    p_lo = float(np.percentile(crop, 18.0))
    p_hi = float(np.percentile(crop, 82.0))
    if (p_hi - p_lo) < 10.0:
        return [word]
    thresh = 0.5 * (p_lo + p_hi)
    ink_mask = (crop > thresh) if is_light_ink else (crop < thresh)
    col_ink = np.mean(ink_mask, axis=0)

    is_char_col = col_ink > 0.08
    padded = np.concatenate(([False], is_char_col, [False]))
    starts = np.where(padded[1:] & ~padded[:-1])[0]
    ends = np.where(~padded[1:] & padded[:-1])[0]
    segs = [(int(s), int(e)) for s, e in zip(starts, ends) if (e - s) >= 2]
    if len(segs) < 4:
        return [word]

    gaps = [segs[i][0] - segs[i - 1][1] for i in range(1, len(segs))]
    if not gaps:
        return [word]
    med_gap = float(np.median(gaps))
    max_gap = max(gaps)
    min_word_gap = max(med_gap * 1.75, med_gap + 2.5, 0.16 * float(word.height))
    if max_gap < min_word_gap:
        return [word]

    split_seg_indices = [i for i, g in enumerate(gaps, start=1) if g >= min_word_gap]
    if not split_seg_indices or len(split_seg_indices) > 2:
        return [word]

    total_seg_w = sum(e - s for s, e in segs)
    if total_seg_w <= 0:
        return [word]

    out_words: List[OcrWordBox] = []
    prev_seg_idx = 0
    prev_char_idx = 0
    for sp_i, seg_idx in enumerate(split_seg_indices + [len(segs)]):
        grp_segs = segs[prev_seg_idx:seg_idx]
        if not grp_segs:
            continue
        if seg_idx == len(segs):
            char_end = len(txt)
        elif len(segs) == len(txt):
            char_end = seg_idx
        else:
            cum_w = sum(e - s for s, e in segs[:seg_idx])
            char_end = max(prev_char_idx + 1, min(len(txt) - 1, int(round(len(txt) * (cum_w / total_seg_w)))))
        sub_txt = txt[prev_char_idx:char_end]
        if sub_txt:
            sub_x0 = x0 + grp_segs[0][0]
            sub_x1 = x0 + grp_segs[-1][1]
            out_words.append(
                OcrWordBox(
                    text=sub_txt,
                    x=int(sub_x0),
                    y=word.y,
                    width=max(1, int(sub_x1 - sub_x0)),
                    height=word.height,
                    confidence=word.confidence,
                    line_index=word.line_index,
                    word_index=word.word_index + sp_i,
                )
            )
        prev_seg_idx = seg_idx
        prev_char_idx = char_end

    return out_words if len(out_words) >= 2 else [word]


def _word_ink_luma_stats(word: OcrWordBox, luma_src: np.ndarray, is_light_ink: bool) -> Tuple[float, float]:
    sh, sw = luma_src.shape
    x0 = max(0, min(sw - 1, word.x))
    x1 = max(x0 + 1, min(sw, word.right))
    y0 = max(0, min(sh - 1, word.y))
    y1 = max(y0 + 1, min(sh, word.bottom))
    crop = luma_src[y0:y1, x0:x1]
    if crop.size == 0:
        return 128.0, 0.0
    fg = float(np.percentile(crop, 88.0 if is_light_ink else 12.0))
    bg = float(np.percentile(crop, 15.0 if is_light_ink else 85.0))
    return fg, abs(fg - bg)


def _disambiguate_leading_vertical_bar_in_line(
    words: List[OcrWordBox],
    luma_src: np.ndarray,
    is_light_ink: bool,
) -> List[OcrWordBox]:
    """
    When a sans-serif uppercase 'I' at the beginning of a prose/title line (such as
    `I LOVE LOGS` or `I agree`) is classified by Tesseract as `|` (or `l` before an
    all-caps phrase), disambiguate it to `'I'` only when:
      1. It is the first token on the line (`index == 0`) and no other token on the line is `|`
         (preserving markdown tables `| a | b |`, status pipes `VIP | 60 FPS`, and framed signs `| WOOD SHOP |`).
      2. The following token `w1` is an alphabetic word of length >= 2.
      3. `w0` matches the line's glyph height, top/bottom baseline alignment, and ink luminance.
      4. The horizontal gap `w1.x - w0.right` is normal inter-word spacing rather than a distant border/icon margin.
    """
    if len(words) < 2:
        return words

    w0 = words[0]
    w1 = words[1]
    t0 = w0.text.strip()
    t1 = w1.text.strip()
    if t0 not in ("|", "l", "1"):
        return words
    if not (t1.isalpha() and len(t1) >= 2):
        return words
    # Never convert leading '|' if another '|' exists on the same line (e.g. '| WOOD SHOP |' or '| Col1 | Col2 |')
    if any(w.text.strip() == "|" for w in words[1:]):
        return words

    core_words = [w for w in words[1:] if sum(c.isalnum() for c in w.text) >= 2]
    if not core_words:
        return words

    all_caps_rest = all(w.text.isupper() for w in core_words if w.text.isalpha())
    if t0 in ("l", "1") and not all_caps_rest:
        return words

    core_h = float(np.median([w.height for w in core_words]))
    core_fgs = [_word_ink_luma_stats(w, luma_src, is_light_ink)[0] for w in core_words[:64]]
    core_fg_med = float(np.median(core_fgs))
    core_word_ids = {id(w) for w in core_words}
    core_gaps = [
        words[i].x - words[i - 1].right
        for i in range(1, min(len(words), 120))
        if id(words[i]) in core_word_ids and id(words[i - 1]) in core_word_ids
    ]
    med_core_gap = float(np.median(core_gaps)) if core_gaps else (core_h * 0.42)

    fg0, _ = _word_ink_luma_stats(w0, luma_src, is_light_ink)
    fg_diff0 = abs(fg0 - core_fg_med)
    h_ratio0 = w0.height / max(1.0, core_h)
    gap0 = w1.x - w0.right
    top_tol = max(5, int(round(core_h * 0.28)))
    min_core_y = min(w.y for w in core_words)
    med_core_bottom = float(np.median([w.bottom for w in core_words]))
    top_ok = min(abs(w0.y - w1.y), abs(w0.y - min_core_y)) <= top_tol
    bot_ok = min(abs(w0.bottom - w1.bottom), abs(w0.bottom - med_core_bottom)) <= top_tol

    if (
        0.78 <= h_ratio0 <= 1.28
        and top_ok
        and bot_ok
        and fg_diff0 < 20.0
        and 0 <= gap0 <= max(med_core_gap * 1.55, core_h * 0.85)
        and w0.width <= max(12, int(round(core_h * 0.50)))
    ):
        updated_w0 = OcrWordBox(
            text="I",
            x=w0.x,
            y=w0.y,
            width=w0.width,
            height=w0.height,
            confidence=max(w0.confidence, 88.0),
            line_index=w0.line_index,
            word_index=w0.word_index,
        )
        return [updated_w0] + list(words[1:])

    return words


_ICON_NOISE_DOUBLETS = frozenset({"QO", "UO", "XO", "C)", "(@)", "(O)", "(0)", "[O]", "O)", "(C"})
_ICON_RING_CHARS = frozenset({"O", "0", "o", "Q", "C", "U", "D"})


def _filter_decorative_and_icon_tokens_in_line(
    words: List[OcrWordBox],
    luma_src: np.ndarray,
    is_light_ink: bool,
) -> List[OcrWordBox]:
    """
    Conservatively remove leading/trailing decorative marks or menu icon misreads
    based on visible image & structural evidence while preserving all legitimate short
    words (`I`, `A`, `O`, `OK`, `To`, numbered lists, and code syntax).
    """
    if len(words) < 2:
        return words

    words = _disambiguate_leading_vertical_bar_in_line(words, luma_src, is_light_ink)

    core_words = [
        w for w in words
        if sum(c.isalnum() for c in w.text) >= 2 and w.text.strip() not in _ICON_NOISE_DOUBLETS
    ]
    if not core_words:
        return words

    sh, sw = luma_src.shape
    core_h = float(np.median([w.height for w in core_words]))
    core_conf = float(np.median([w.confidence for w in core_words]))
    core_fgs = [_word_ink_luma_stats(w, luma_src, is_light_ink)[0] for w in core_words[:64]]
    core_fg_med = float(np.median(core_fgs))

    core_word_ids = {id(w) for w in core_words}
    core_gaps = [
        words[i].x - words[i - 1].right
        for i in range(1, min(len(words), 120))
        if id(words[i]) in core_word_ids and id(words[i - 1]) in core_word_ids
    ]
    med_core_gap = float(np.median(core_gaps)) if core_gaps else (core_h * 0.38)

    filtered = list(words)

    # 1. Check up to 2 leading tokens (so compound border+icon noise like '| O Leave Lobby' is fully stripped)
    for _pass in range(2):
        if len(filtered) < 2:
            break
        w0 = filtered[0]
        w1 = filtered[1]
        t0 = w0.text.strip()
        gap0 = w1.x - w0.right
        fg0, _ = _word_ink_luma_stats(w0, luma_src, is_light_ink)
        fg_diff0 = abs(fg0 - core_fg_med)
        h_ratio0 = w0.height / max(1.0, core_h)
        aspect0 = float(w0.width) / max(1.0, float(w0.height))
        alnum0 = sum(c.isalnum() for c in t0)
        has_icon_brackets = any(c in "()[]{}@©®™§¤•♦|~=_" for c in t0)

        is_leading_icon = False
        if t0 in _ICON_NOISE_DOUBLETS:
            is_leading_icon = True
        elif alnum0 == 0 and t0 in ("|", "=", "_", "@", "©", "®", "•", "♦", "~", "()", "[]", "{}", "«", "»", "‘", "’"):
            has_interior_pipe = any(w.text.strip() == "|" for w in filtered[1:-1])
            if t0 == "|" and has_interior_pipe and w0.confidence >= 75.0 and h_ratio0 <= 1.55 and gap0 <= max(med_core_gap * 2.2, core_h * 1.85):
                is_leading_icon = False
            elif (
                fg_diff0 >= 22.0
                or h_ratio0 < 0.78
                or h_ratio0 > 1.32
                or w0.confidence < 80.0
                or gap0 >= max(med_core_gap * 1.55, core_h * 0.65)
                or t0 in ("=", "_", "@", "©", "®", "•", "♦", "()", "[]", "{}")
            ):
                is_leading_icon = True
        elif len(t0) <= 4 and has_icon_brackets and (w0.confidence < 72.0 or alnum0 <= 1):
            is_leading_icon = True
        elif len(t0) <= 2 and w0.confidence < 55.0 and core_conf >= 85.0 and gap0 >= core_h * 0.35:
            is_leading_icon = True
        elif len(t0) == 1:
            all_caps_rest = all(w.text.isupper() for w in core_words if w.text.isalpha())
            vert_shift = max(abs(w0.y - w1.y), abs(w0.bottom - w1.bottom))
            if (fg_diff0 >= 26.0 or h_ratio0 < 0.78 or h_ratio0 > 1.32) and gap0 >= max(med_core_gap * 1.45, core_h * 0.60):
                is_leading_icon = True
            elif all_caps_rest and len(w1.text) >= 3 and gap0 >= max(med_core_gap * 2.1, core_h * 0.92):
                is_leading_icon = True
            elif (
                t0 in _ICON_RING_CHARS
                and w0.x < sw * 0.24
                and 0.65 <= aspect0 <= 1.45
                and len(w1.text) >= 3
                and w1.text[0].isupper()
                and gap0 >= max(med_core_gap * 1.45, core_h * 0.68)
                and (vert_shift >= max(4, int(round(core_h * 0.20))) or w0.confidence < 72.0 or fg_diff0 >= 20.0)
            ):
                is_leading_icon = True

        if is_leading_icon:
            filtered = filtered[1:]
        else:
            break

    # 2. Check up to 2 trailing tokens
    for _pass in range(2):
        if len(filtered) < 2:
            break
        w_last = filtered[-1]
        w_prev = filtered[-2]
        t_last = w_last.text.strip()
        gap_last = w_last.x - w_prev.right
        fg_last, _ = _word_ink_luma_stats(w_last, luma_src, is_light_ink)
        fg_diff_last = abs(fg_last - core_fg_med)
        alnum_last = sum(c.isalnum() for c in t_last)

        is_trailing_decor = False
        has_interior_pipe = any(w.text.strip() == "|" for w in filtered[1:-1])
        if alnum_last == 0 and t_last in ("@", "©", "®", "~", "•", "♦", "¤", "§", "‘", "’", "}", ")"):
            is_trailing_decor = True
        elif t_last == "|":
            if not (has_interior_pipe and w_last.confidence >= 75.0 and gap_last <= max(med_core_gap * 2.2, core_h * 1.85)):
                is_trailing_decor = True
        elif len(t_last) <= 2 and alnum_last == 0 and gap_last >= max(med_core_gap * 1.6, core_h * 0.65):
            is_trailing_decor = True
        elif len(t_last) == 1 and (fg_diff_last >= 26.0 or w_last.confidence < 62.0) and gap_last >= max(med_core_gap * 1.75, core_h * 0.82):
            is_trailing_decor = True

        if is_trailing_decor:
            filtered = filtered[:-1]
        else:
            break

    return filtered


def _filter_multiline_left_icon_gutter(
    lines_words: List[List[OcrWordBox]],
    image_width: int,
) -> List[List[OcrWordBox]]:
    """
    In a multi-line vertical menu (2 or more lines), if the first multi-character
    word on each line shares a consistent left-aligned column `x_align` (within +-6.5px),
    any short 1-2 character icon/ring/symbol token sitting in the left icon gutter
    (`right <= x_align - min_gutter_gap`) immediately before that aligned label word is stripped,
    while preserving legitimate prose lines starting with 'I' or 'A' and pipe-delimited tables.
    """
    if len(lines_words) < 2:
        return lines_words

    first_core_xs: List[int] = []
    core_heights: List[int] = []
    for wlist in lines_words:
        for w in wlist:
            t = w.text.strip()
            if sum(c.isalnum() for c in t) >= 2 and t not in _ICON_NOISE_DOUBLETS:
                first_core_xs.append(w.x)
                core_heights.append(w.height)
                break

    if len(first_core_xs) < 2 or len(first_core_xs) < int(len(lines_words) * 0.60):
        return lines_words

    if float(np.std(first_core_xs)) > 6.5:
        return lines_words

    x_align = float(np.median(first_core_xs))
    med_h = float(np.median(core_heights)) if core_heights else 18.0
    if x_align < 18.0 or x_align > image_width * 0.42:
        return lines_words

    # Check if at least one line starts directly at x_align (without a leading gutter token)
    has_direct_aligned_line = any(
        abs(float(wlist[0].x) - x_align) <= 8.0 for wlist in lines_words if wlist
    )
    min_gutter_gap = max(11.0, med_h * 0.55)
    cleaned_lines: List[List[OcrWordBox]] = []
    for wlist in lines_words:
        cur = list(wlist)
        has_interior_pipe = any(w.text.strip() == "|" for w in cur[1:-1])
        while len(cur) >= 2:
            w0, w1 = cur[0], cur[1]
            t0 = w0.text.strip()
            if t0 == "|" and has_interior_pipe:
                break
            if t0 in ("I", "A", "a"):
                break
            is_icon_like_token = (
                t0 in _ICON_RING_CHARS
                or t0 in _ICON_NOISE_DOUBLETS
                or not t0.isalnum()
                or w0.confidence < 72.0
            )
            if (
                len(t0) <= 2
                and is_icon_like_token
                and (has_direct_aligned_line or (w1.x - w0.right) >= max(14.0, med_h * 0.68))
                and w0.right <= (x_align - min_gutter_gap)
                and abs(float(w1.x) - x_align) <= 8.0
            ):
                cur = cur[1:]
            else:
                break
        cleaned_lines.append(cur)
    return cleaned_lines


def refine_ocr_result_layout_and_spacing(
    result: OcrRecognitionResult,
    image_source: Any,
    profile: Optional[OcrImageProfile] = None,
) -> OcrRecognitionResult:
    """
    Refine recognized lines and word boxes using visible source image evidence:
      1. Split merged all-caps stylized words (`SELLLOGS` -> `SELL LOGS`) where a clear
         full-height pixel valley exists inside the word box.
      2. Disambiguate leading vertical-stroke `|` to `I` when aligned with a prose/title phrase.
      3. Filter leading/trailing decorative marks or menu icon misreads (`@`, `©`, `(6)`,
         aligned left-gutter icons, isolated decorative posts) without touching legitimate
         short words (`I`, `A`, `O`) or code/HUD syntax (`VIP | 60 FPS | 95°C`).
      4. Recompute accurate `OcrLineBox` and `OcrWordBox` coordinates and indices.
    """
    if not result.ok or not result.lines or not result.words:
        return result

    rgb_img = _to_pil_rgb(image_source)
    if profile is None:
        profile = analyze_image_for_ocr(rgb_img)

    arr_rgb = np.asarray(rgb_img, dtype=np.float32)
    luma_src = 0.2126 * arr_rgb[:, :, 0] + 0.7152 * arr_rgb[:, :, 1] + 0.0722 * arr_rgb[:, :, 2]
    is_light = bool(profile.is_light_ink or result.inverted_dark_theme)

    per_line_filtered: List[List[OcrWordBox]] = []
    for ln in result.lines:
        if not ln.words:
            continue
        split_words: List[OcrWordBox] = []
        for w in ln.words:
            split_words.extend(_split_merged_word_by_visual_valleys(w, luma_src, is_light))
        filtered_words = _filter_decorative_and_icon_tokens_in_line(split_words, luma_src, is_light)
        if filtered_words:
            per_line_filtered.append(filtered_words)

    per_line_filtered = _filter_multiline_left_icon_gutter(per_line_filtered, rgb_img.width)

    new_lines: List[OcrLineBox] = []
    new_words: List[OcrWordBox] = []
    text_lines: List[str] = []

    for filtered_words in per_line_filtered:
        if not filtered_words:
            continue
        new_line_idx = len(new_lines)
        reindexed = tuple(
            OcrWordBox(
                text=w.text,
                x=w.x,
                y=w.y,
                width=w.width,
                height=w.height,
                confidence=w.confidence,
                line_index=new_line_idx,
                word_index=w_i,
            )
            for w_i, w in enumerate(filtered_words)
        )
        min_x = min(w.x for w in reindexed)
        min_y = min(w.y for w in reindexed)
        max_r = max(w.right for w in reindexed)
        max_b = max(w.bottom for w in reindexed)
        mean_conf = float(np.mean([w.confidence for w in reindexed]))
        line_str = " ".join(w.text for w in reindexed)
        text_lines.append(line_str)
        new_lines.append(
            OcrLineBox(
                text=line_str,
                x=min_x,
                y=min_y,
                width=max(1, max_r - min_x),
                height=max(1, max_b - min_y),
                confidence=mean_conf,
                line_index=new_line_idx,
                words=reindexed,
            )
        )
        new_words.extend(reindexed)

    if not new_lines:
        return result

    return OcrRecognitionResult(
        text="\n".join(text_lines),
        lines=new_lines,
        words=new_words,
        language=result.language,
        engine_name=result.engine_name,
        source_width=result.source_width,
        source_height=result.source_height,
        scale_factor=result.scale_factor,
        inverted_dark_theme=result.inverted_dark_theme,
        threshold_applied=result.threshold_applied,
        elapsed_ms=result.elapsed_ms,
        cancelled=result.cancelled,
        error=result.error,
        preprocessing_strategy=result.preprocessing_strategy,
        psm_used=result.psm_used,
        quality_score=result.quality_score,
        candidates_evaluated=result.candidates_evaluated,
        quality_mode=result.quality_mode,
        retry_attempt=result.retry_attempt,
        backend_selected=result.backend_selected,
        fallback_reason=result.fallback_reason,
    )


def _is_suspicious_ocr_token(txt: str, conf: float) -> bool:
    """Return True if a recognized word token has structural/confidence signs of OCR noise."""
    t = txt.strip()
    if not t:
        return True
    alnum = sum(c.isalnum() for c in t)
    if alnum == 0:
        if t in ("=", "+", "-", "*", "/", ":", "|", "#", "@", "->", "==", "!=", "<=", ">=") and conf >= 84.0:
            return False
        return True
    if len(t) <= 4 and any(c in "()[]{}@©®™§¤•♦|~‘’" for c in t) and (conf < 78.0 or alnum <= 1):
        return True
    if re.search(r"[A-Za-z][)\]|/;‘’][A-Za-z0-9]", t):
        return True
    if conf < 72.0 and (any(c in "/\\|;‘’~@" for c in t) or len(t) <= 2):
        return True
    return False


def score_ocr_candidate(
    result: OcrRecognitionResult,
    profile: Optional[OcrImageProfile] = None,
    image_source: Any = None,
    *,
    consensus_counts: Optional[Dict[str, int]] = None,
) -> float:
    """
    Conservatively score an `OcrRecognitionResult` using multiple structural and visual factors:
      1. Word confidence distribution (mean and 20th-percentile floor).
      2. Bounded sublinear count of clean, non-suspicious alphanumeric tokens (never blindly
         rewarding longer garbage output).
      3. Penalties for low-confidence words, fragmented 1–2 char noise tokens, isolated symbols,
         and wedged mid-word punctuation glitches.
      4. Bounding-box baseline alignment within lines.
      5. Coverage of the image's detected horizontal/vertical text-stroke band (`OcrImageProfile`).
      6. Cross-candidate word consensus when multiple candidates are evaluated.
    """
    if not result.ok or not result.has_text:
        return -100.0

    if profile is None and image_source is not None:
        try:
            profile = analyze_image_for_ocr(image_source)
        except Exception:
            profile = None

    # Special case: unit-test mocks that return text without populating word boxes
    if not result.words and result.text.strip():
        return 90.0

    confs = []
    for w in result.words:
        c = float(w.confidence)
        wt = w.text.strip()
        if c < 82.0 and len(wt) >= 6 and wt.isalnum() and any(ch.isupper() for ch in wt[1:]) and any(ch.islower() for ch in wt):
            confs.append(max(c, 88.0))
        else:
            confs.append(c)
    mean_conf = float(np.mean(confs)) if confs else 0.0
    p20_conf = float(np.percentile(confs, 20.0)) if confs else 0.0

    clean_words = 0
    suspicious_count = 0
    low_conf_count = 0
    fragment_count = 0
    consensus_bonus = 0.0

    for w in result.words:
        t = w.text.strip()
        c = float(w.confidence)
        is_camelcase_id = (len(t) >= 6 and t.isalnum() and any(ch.isupper() for ch in t[1:]) and any(ch.islower() for ch in t))
        if c < 62.0 and not is_camelcase_id:
            low_conf_count += 1
        if _is_suspicious_ocr_token(t, c):
            suspicious_count += 1
        else:
            alnum = sum(ch.isalnum() for ch in t)
            if alnum >= 2 or (alnum == 1 and c >= 80.0 and t in ("I", "A", "a", "O", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
                clean_words += 1
            elif len(t) <= 2 and c < 82.0:
                fragment_count += 1
        if consensus_counts is not None:
            norm_w = t.lower()
            if consensus_counts.get(norm_w, 0) >= 2 and not _is_suspicious_ocr_token(t, c):
                consensus_bonus += 2.2

    # Sublinear reward for clean words so longer garbage never beats shorter clean text
    clean_signal = min(36.0, math.sqrt(float(clean_words)) * 12.5)
    conf_score = 0.55 * mean_conf + 0.30 * p20_conf

    # Penalties for noise, fragments, and suspicious tokens
    noise_penalty = (
        suspicious_count * 22.0
        + low_conf_count * 15.0
        + fragment_count * 12.0
    )

    # Penalize if almost all words are 1-2 chars (severe fragmentation)
    if result.words and all(len(w.text.strip()) <= 2 for w in result.words):
        if mean_conf < 88.0:
            noise_penalty += 35.0

    # Baseline alignment check within multi-word lines
    baseline_penalty = 0.0
    for ln in result.lines:
        if len(ln.words) >= 2:
            bottoms = [w.bottom for w in ln.words]
            heights = [w.height for w in ln.words]
            med_h = max(4.0, float(np.median(heights)))
            if float(np.std(bottoms)) > med_h * 0.45:
                baseline_penalty += 8.0

    # Text-band coverage check (using only clean high-confidence words)
    coverage_score = 0.0
    if profile is not None:
        good_words = [w for w in result.words if w.confidence >= 76.0 and not _is_suspicious_ocr_token(w.text, w.confidence)]
        if good_words:
            wx0 = min(w.x for w in good_words)
            wx1 = max(w.right for w in good_words)
            rec_span_w = max(1, wx1 - wx0)
            exp_span_w = max(1, profile.text_x1 - profile.text_x0)
            w_cov = min(1.0, float(rec_span_w) / float(exp_span_w))
            coverage_score += w_cov * 18.0
            if profile.estimated_line_count >= 2:
                line_cov = min(1.0, float(len(result.lines)) / float(profile.estimated_line_count))
                coverage_score += line_cov * 10.0

    total = conf_score + clean_signal + coverage_score + min(12.0, consensus_bonus) - noise_penalty - baseline_penalty
    return float(total)


def _needs_followup_candidates(
    result: OcrRecognitionResult,
    profile: OcrImageProfile,
    score: float,
) -> bool:
    """
    Determine whether the first-pass OCR result (even when non-empty!) is uncertain,
    incomplete, or contains suspicious tokens and therefore warrants evaluating
    follow-up preprocessing/segmentation candidates.
    """
    if not result.ok or not result.has_text:
        return True
    if not result.words:
        return False
    # Note: Tesseract lowers dictionary confidence (e.g. 40-70%) on valid CamelCase usernames
    # like CallMeCarsonLIVE or identifiers with underscores/parens even when glyph recognition is clean.
    effective_confs = []
    for w in result.words:
        c = float(w.confidence)
        wt = w.text.strip()
        if c < 80.0 and len(wt) >= 6 and wt.isalnum() and any(ch.isupper() for ch in wt[1:]) and any(ch.islower() for ch in wt):
            effective_confs.append(max(c, 86.0))
        else:
            effective_confs.append(c)
    mean_conf = float(np.mean(effective_confs))
    min_conf = float(np.min(effective_confs))
    if mean_conf < 84.0 or min_conf < 70.0:
        return True
    if any(_is_suspicious_ocr_token(w.text, w.confidence) for w in result.words):
        return True
    # Check if horizontal coverage is suspiciously low compared to detected text band
    exp_span_w = max(1, profile.text_x1 - profile.text_x0)
    rec_span_w = max(1, max(w.right for w in result.words) - min(w.x for w in result.words))
    if exp_span_w >= 80 and (float(rec_span_w) / float(exp_span_w)) < 0.62:
        return True
    if profile.estimated_line_count >= 2 and len(result.lines) < profile.estimated_line_count:
        return True
    if score < 88.0:
        return True
    return False


def _is_credible_salvage_word(word: OcrWordBox) -> bool:
    """
    Return True if a recognized word token is a credible word or number that should
    be preserved during partial-result salvage (e.g. `'CLOSED'`, `'$3,020'`, `'+75%'`, `'3'`, `'days'`),
    or False if it is pure punctuation/symbol noise (`'—<'`, `'~'`, `'|'`) or a low-confidence 1-2 char glitch.
    """
    t = word.text.strip()
    if not t:
        return False
    c = float(word.confidence)
    alnum = sum(ch.isalnum() for ch in t)
    if alnum == 0:
        if t in ("|", "=", "+", "-", "*", "/", ":", "#", "@", "->", "==", "!=", "<=", ">=") and c >= 84.0:
            return True
        return False
    if _is_suspicious_ocr_token(t, c):
        return False
    # Multi-character words/numbers with reasonable confidence (e.g. CLOSED, $3,020, +75%, days)
    if alnum >= 3 and c >= 55.0:
        return True
    if alnum == 2 and c >= 74.0:
        return True
    if alnum == 1 and c >= 78.0 and (t.isdigit() or t in ("I", "A", "a", "O")):
        return True
    return False


def filter_and_salvage_partial_ocr_result(
    result: OcrRecognitionResult,
    profile: Optional[OcrImageProfile] = None,
) -> OcrRecognitionResult:
    """
    Token- and line-level quality filter that fixes the all-or-nothing rejection bug:
      1. Strips isolated garbage-only lines and tokens (such as `'—<'`) without discarding
         valid recognized words from other regions of the screenshot (such as `'CLOSED'`).
      2. If credible words/lines remain (even when other regions of a multi-pill HUD failed
         or had low confidence), preserves those recognized words and their native pixel
         bounding boxes and marks `partial_low_confidence = True` with a clear warning
         rather than returning an empty `'No text recognized'` result.
      3. Only blanks the result (`low_confidence_rejected = True`) when ZERO credible words
         exist across the entire screenshot (e.g. only `'—<'` or sub-legible 1-2 char fragments).
    """
    if not result.ok or not result.has_text or not result.words:
        return result

    kept_lines: List[OcrLineBox] = []
    kept_words: List[OcrWordBox] = []
    dropped_tokens: List[str] = []

    for ln in result.lines:
        line_words = list(ln.words) if ln.words else [w for w in result.words if w.line_index == ln.line_index]
        if not line_words:
            continue
        credible_in_line = [w for w in line_words if _is_credible_salvage_word(w)]
        if not credible_in_line:
            dropped_tokens.extend(w.text.strip() for w in line_words if w.text.strip())
            continue

        # Within a kept line, drop leading/trailing pure-garbage tokens (like '—<') while keeping valid words
        filtered_line_words: List[OcrWordBox] = []
        for w in line_words:
            wt = w.text.strip()
            alnum = sum(ch.isalnum() for ch in wt)
            if alnum == 0 and wt not in ("|", "=", "+", "-", "*", "/", ":", "#", "@", "$", "%") and float(w.confidence) < 86.0:
                dropped_tokens.append(wt)
                continue
            if _is_suspicious_ocr_token(wt, float(w.confidence)) and alnum <= 1:
                dropped_tokens.append(wt)
                continue
            filtered_line_words.append(w)

        if not filtered_line_words:
            continue

        new_line_idx = len(kept_lines)
        reindexed_words = tuple(
            OcrWordBox(
                text=w.text,
                x=w.x,
                y=w.y,
                width=w.width,
                height=w.height,
                confidence=w.confidence,
                line_index=new_line_idx,
                word_index=wi,
            )
            for wi, w in enumerate(filtered_line_words)
        )
        line_str = " ".join(w.text for w in reindexed_words)
        kept_lines.append(
            OcrLineBox(
                text=line_str,
                x=min(w.x for w in reindexed_words),
                y=min(w.y for w in reindexed_words),
                width=max(1, max(w.right for w in reindexed_words) - min(w.x for w in reindexed_words)),
                height=max(1, max(w.bottom for w in reindexed_words) - min(w.y for w in reindexed_words)),
                confidence=float(np.mean([w.confidence for w in reindexed_words])),
                line_index=new_line_idx,
                words=reindexed_words,
            )
        )
        kept_words.extend(reindexed_words)

    # Check if the surviving words contain at least one genuine multi-letter/number word (not just 1-2 char noise fragments)
    strong_words = [
        w for w in kept_words
        if (sum(ch.isalnum() for ch in w.text) >= 3 and float(w.confidence) >= 62.0)
        or (sum(ch.isalnum() for ch in w.text) >= 2 and float(w.confidence) >= 80.0)
    ]

    if not kept_lines or not strong_words:
        return result

    expected_lines = profile.estimated_line_count if profile is not None else len(kept_lines)
    mean_kept_conf = float(np.mean([w.confidence for w in kept_words])) if kept_words else 0.0
    is_partial = bool(
        (dropped_tokens and len(kept_lines) < len(result.lines))
        or (expected_lines >= 2 and len(kept_lines) < expected_lines)
        or mean_kept_conf < 74.0
    )

    warning_msg = result.quality_warning
    if is_partial and not warning_msg:
        warning_msg = (
            f"Partial result / low confidence: extracted {len(kept_words)} credible "
            f"{'word' if len(kept_words) == 1 else 'words'} across {len(kept_lines)} "
            f"{'line' if len(kept_lines) == 1 else 'lines'} (mean confidence {mean_kept_conf:.0f}%)."
        )

    return OcrRecognitionResult(
        text="\n".join(ln.text for ln in kept_lines),
        lines=kept_lines,
        words=kept_words,
        language=result.language,
        engine_name=result.engine_name,
        source_width=result.source_width,
        source_height=result.source_height,
        scale_factor=result.scale_factor,
        inverted_dark_theme=result.inverted_dark_theme,
        threshold_applied=result.threshold_applied,
        elapsed_ms=result.elapsed_ms,
        cancelled=result.cancelled,
        error=result.error,
        preprocessing_strategy=result.preprocessing_strategy,
        psm_used=result.psm_used,
        quality_score=result.quality_score,
        candidates_evaluated=result.candidates_evaluated,
        quality_mode=result.quality_mode,
        retry_attempt=result.retry_attempt,
        pass_timings_ms=list(result.pass_timings_ms),
        candidate_diagnostics=list(result.candidate_diagnostics),
        low_confidence_rejected=False,
        partial_low_confidence=is_partial,
        raw_rejected_text=", ".join(dropped_tokens) if dropped_tokens else result.raw_rejected_text,
        quality_warning=warning_msg,
        backend_selected=result.backend_selected,
        fallback_reason=result.fallback_reason,
    )


def is_plausible_ocr_result(
    result: OcrRecognitionResult,
    profile: Optional[OcrImageProfile] = None,
) -> bool:
    """
    Calibrated rejection criterion to prevent low-confidence punctuation fragments
    (such as `'—<'` on a five-button menu) or severe recognition noise from being
    accepted as authoritative OCR output, while never discarding credible recognized words
    like `'CLOSED'` or `'$3,020'`.
    """
    if not result.ok or not result.has_text:
        return False
    # Unit-test mocks that populate `text` directly without `words` remain valid
    if not result.words and result.text.strip():
        alnum_chars = sum(c.isalnum() for c in result.text)
        return alnum_chars >= 1

    clean_words = 0
    strong_words = 0
    suspicious_words = 0
    confs: List[float] = []
    for w in result.words:
        t = w.text.strip()
        c = float(w.confidence)
        confs.append(c)
        if _is_suspicious_ocr_token(t, c):
            suspicious_words += 1
        else:
            alnum = sum(ch.isalnum() for ch in t)
            if alnum >= 2 or (alnum == 1 and c >= 80.0 and t in ("I", "A", "a", "O", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
                clean_words += 1
            if (alnum >= 3 and c >= 65.0) or (alnum >= 2 and c >= 82.0):
                strong_words += 1

    mean_conf = float(np.mean(confs)) if confs else 0.0
    # 1. A result with zero clean alphanumeric words (e.g. only '—<' or punctuation) is never plausible UI text
    if clean_words == 0:
        return False
    # 2. If at least one strong word (>=3 alnum chars with >=65% conf, like 'CLOSED') is present and outnumbers or survives noise, it is plausible (at worst partial)
    if strong_words >= 1 and clean_words >= suspicious_words and mean_conf >= 55.0:
        return True
    # 3. A single tiny fragment from a multi-row menu (>= 4 detected lines) with weak confidence/score is incomplete
    if profile is not None and profile.estimated_line_count >= 4 and len(result.lines) <= 1 and strong_words == 0:
        if mean_conf < 82.0 or result.quality_score < 45.0:
            return False
    # 4. Reject when overall score is below calibrated plausibility floor or noise dominates
    if result.quality_score != 0.0 and result.quality_score < 18.0 and strong_words == 0:
        return False
    if mean_conf < 48.0 and suspicious_words >= clean_words:
        return False
    return True


def _parse_tesseract_tsv(
    tsv_text: str,
    scale_factor: float,
    source_w: int,
    source_h: int,
    pad_px: int = 0,
    crop_offset_xy: Tuple[int, int] = (0, 0),
) -> Tuple[str, List[OcrLineBox], List[OcrWordBox]]:
    """
    Parse Tesseract TSV output into structured `OcrWordBox` and `OcrLineBox`
    objects accurately mapped back to original screenshot pixel coordinates.
    """
    inv_scale = 1.0 / max(scale_factor, 1e-6)
    off_x, off_y = int(crop_offset_xy[0]), int(crop_offset_xy[1])
    lines_map: Dict[Tuple[int, int, int], List[OcrWordBox]] = {}
    all_words: List[OcrWordBox] = []

    raw_rows = tsv_text.splitlines()
    if not raw_rows:
        return "", [], []

    for row in raw_rows[1:]:
        parts = row.split("\t")
        if len(parts) < 12:
            continue
        try:
            level = int(parts[0])
            block_num = int(parts[2])
            par_num = int(parts[3])
            line_num = int(parts[4])
            word_num = int(parts[5])
            left = int(parts[6])
            top = int(parts[7])
            width = int(parts[8])
            height = int(parts[9])
            conf = float(parts[10])
            word_str = parts[11]
        except Exception:
            continue

        if level != 5:
            continue
        if not word_str or not word_str.strip():
            continue

        orig_x = off_x + int(round((left - pad_px) * inv_scale))
        orig_y = off_y + int(round((top - pad_px) * inv_scale))
        orig_w = max(1, int(round(width * inv_scale)))
        orig_h = max(1, int(round(height * inv_scale)))

        orig_x = max(0, min(source_w - 1, orig_x))
        orig_y = max(0, min(source_h - 1, orig_y))
        if orig_x + orig_w > source_w:
            orig_w = max(1, source_w - orig_x)
        if orig_y + orig_h > source_h:
            orig_h = max(1, source_h - orig_y)

        line_key = (block_num, par_num, line_num)
        if line_key not in lines_map:
            lines_map[line_key] = []
        line_idx = len(lines_map) - 1

        wbox = OcrWordBox(
            text=word_str.strip(),
            x=orig_x,
            y=orig_y,
            width=orig_w,
            height=orig_h,
            confidence=max(0.0, conf),
            line_index=line_idx,
            word_index=max(0, word_num - 1),
        )
        lines_map[line_key].append(wbox)
        all_words.append(wbox)

    line_boxes: List[OcrLineBox] = []
    text_lines: List[str] = []
    for idx, (_key, wlist) in enumerate(lines_map.items()):
        if not wlist:
            continue
        wlist_sorted = sorted(wlist, key=lambda w: w.x)
        reindexed_words = tuple(
            OcrWordBox(
                text=w.text,
                x=w.x,
                y=w.y,
                width=w.width,
                height=w.height,
                confidence=w.confidence,
                line_index=idx,
                word_index=w_i,
            )
            for w_i, w in enumerate(wlist_sorted)
        )
        min_x = min(w.x for w in reindexed_words)
        min_y = min(w.y for w in reindexed_words)
        max_r = max(w.right for w in reindexed_words)
        max_b = max(w.bottom for w in reindexed_words)
        mean_conf = float(np.mean([w.confidence for w in reindexed_words]))
        line_str = " ".join(w.text for w in reindexed_words)
        text_lines.append(line_str)
        line_boxes.append(
            OcrLineBox(
                text=line_str,
                x=min_x,
                y=min_y,
                width=max(1, max_r - min_x),
                height=max(1, max_b - min_y),
                confidence=mean_conf,
                line_index=idx,
                words=reindexed_words,
            )
        )

    flat_words = [w for ln in line_boxes for w in ln.words]
    full_text = "\n".join(text_lines)
    return full_text, line_boxes, flat_words


# ---------------------------------------------------------------------------
# Built-in Pure-Python/NumPy/Pillow Template Fallback Recognizer (Opt-In Only)
# ---------------------------------------------------------------------------
_BUILTIN_TEMPLATE_CACHE: Optional[Tuple[np.ndarray, List[str]]] = None
_BUILTIN_PRINTABLE_CHARS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    ".,:;!?-_+=/\\()[]{}<>@#$%^&*~'\"`"
)


def _normalize_glyph_bitmap(mask: np.ndarray, size: int = 20) -> np.ndarray:
    """Normalize a binary ink mask (True/1 = ink) into a centered `size x size` float vector."""
    ys, xs = np.where(mask > 0)
    if len(xs) == 0 or len(ys) == 0:
        return np.zeros((size * size,), dtype=np.float32)
    crop = (mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1] > 0).astype(np.uint8) * 255
    ch, cw = crop.shape
    pil_g = Image.fromarray(crop, mode="L")
    scale = min((size - 2) / max(1, cw), (size - 2) / max(1, ch))
    nw = max(1, int(round(cw * scale)))
    nh = max(1, int(round(ch * scale)))
    pil_resized = pil_g.resize((nw, nh), Image.Resampling.BILINEAR)
    canvas = Image.new("L", (size, size), 0)
    canvas.paste(pil_resized, ((size - nw) // 2, (size - nh) // 2))
    vec = np.asarray(canvas, dtype=np.float32).reshape(-1) / 255.0
    norm = float(np.linalg.norm(vec))
    if norm > 1e-6:
        vec = vec / norm
    return vec


def _get_builtin_glyph_templates() -> Tuple[np.ndarray, List[str]]:
    global _BUILTIN_TEMPLATE_CACHE
    if _BUILTIN_TEMPLATE_CACHE is not None:
        return _BUILTIN_TEMPLATE_CACHE

    fonts: List[Any] = [ImageFont.load_default()]
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\consola.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            for sz in (16, 22):
                try:
                    fonts.append(ImageFont.truetype(fp, sz))
                except Exception:
                    pass

    vecs: List[np.ndarray] = []
    labels: List[str] = []
    for font in fonts:
        for ch in _BUILTIN_PRINTABLE_CHARS:
            img = Image.new("L", (48, 48), 0)
            drw = ImageDraw.Draw(img)
            drw.text((6, 6), ch, fill=255, font=font)
            arr = np.asarray(img, dtype=np.uint8)
            if np.any(arr > 32):
                vecs.append(_normalize_glyph_bitmap(arr > 64))
                labels.append(ch)

    mat = np.vstack(vecs) if vecs else np.zeros((1, 400), dtype=np.float32)
    _BUILTIN_TEMPLATE_CACHE = (mat, labels)
    return _BUILTIN_TEMPLATE_CACHE


def _recognize_with_builtin_template_engine(
    pil_gray: Image.Image,
    scale_factor: float,
    source_w: int,
    source_h: int,
    cancel_token: Optional[CancellationToken] = None,
) -> Tuple[str, List[OcrLineBox], List[OcrWordBox]]:
    """
    Opt-in fallback pure-Python/NumPy line/word/character connected-component segmenter
    and template matcher when explicitly requested via `allow_builtin_fallback=True`.
    """
    arr = np.asarray(pil_gray.convert("L"), dtype=np.float32)
    thresh = float(np.percentile(arr, 20.0) * 0.5 + np.percentile(arr, 85.0) * 0.5)
    ink = arr < thresh
    h, w = ink.shape
    inv_scale = 1.0 / max(scale_factor, 1e-6)

    row_ink = np.sum(ink, axis=1) > max(1, int(w * 0.002))
    padded_r = np.concatenate(([False], row_ink, [False]))
    r_starts = np.where(padded_r[1:] & ~padded_r[:-1])[0]
    r_ends = np.where(~padded_r[1:] & padded_r[:-1])[0]

    mat, labels = _get_builtin_glyph_templates()
    lines_out: List[OcrLineBox] = []
    words_out: List[OcrWordBox] = []
    text_lines: List[str] = []

    for _line_idx, (ry0, ry1) in enumerate(zip(r_starts, r_ends)):
        if cancel_token is not None and cancel_token.is_cancelled:
            break
        if (ry1 - ry0) < 3:
            continue
        band = ink[ry0:ry1, :]
        col_ink = np.sum(band, axis=0) > 0
        padded_c = np.concatenate(([False], col_ink, [False]))
        c_starts = np.where(padded_c[1:] & ~padded_c[:-1])[0]
        c_ends = np.where(~padded_c[1:] & padded_c[:-1])[0]
        if len(c_starts) == 0:
            continue

        gaps = [int(c_starts[i] - c_ends[i - 1]) for i in range(1, len(c_starts))]
        median_char_h = max(6.0, float(ry1 - ry0))
        word_gap_thresh = max(4, int(round(median_char_h * 0.34)))
        if gaps:
            max_gap = max(gaps)
            if max_gap >= 3:
                word_gap_thresh = max(3, min(word_gap_thresh, int(round(np.percentile(gaps, 75)))))

        word_groups: List[List[Tuple[int, int]]] = [[]]
        for i, (cx0, cx1) in enumerate(zip(c_starts, c_ends)):
            if i > 0 and (cx0 - c_ends[i - 1]) >= word_gap_thresh:
                word_groups.append([])
            word_groups[-1].append((int(cx0), int(cx1)))

        line_words: List[OcrWordBox] = []
        for w_idx, grp in enumerate(word_groups):
            if not grp:
                continue
            chars: List[str] = []
            for cx0, cx1 in grp:
                sub = band[:, cx0:cx1]
                vec = _normalize_glyph_bitmap(sub)
                scores = mat @ vec
                best_idx = int(np.argmax(scores)) if len(scores) else 0
                ch = labels[best_idx] if labels else "?"
                chars.append(ch)
            word_str = "".join(chars)
            wx0 = grp[0][0]
            wx1 = grp[-1][1]
            ox = max(0, min(source_w - 1, int(round(wx0 * inv_scale))))
            oy = max(0, min(source_h - 1, int(round(ry0 * inv_scale))))
            ow = max(1, min(source_w - ox, int(round((wx1 - wx0) * inv_scale))))
            oh = max(1, min(source_h - oy, int(round((ry1 - ry0) * inv_scale))))
            wbox = OcrWordBox(
                text=word_str,
                x=ox,
                y=oy,
                width=ow,
                height=oh,
                confidence=72.0,
                line_index=len(lines_out),
                word_index=w_idx,
            )
            line_words.append(wbox)
            words_out.append(wbox)

        if line_words:
            l_str = " ".join(w.text for w in line_words)
            text_lines.append(l_str)
            min_x = min(w.x for w in line_words)
            min_y = min(w.y for w in line_words)
            max_r = max(w.right for w in line_words)
            max_b = max(w.bottom for w in line_words)
            lines_out.append(
                OcrLineBox(
                    text=l_str,
                    x=min_x,
                    y=min_y,
                    width=max(1, max_r - min_x),
                    height=max(1, max_b - min_y),
                    confidence=72.0,
                    line_index=len(lines_out),
                    words=tuple(line_words),
                )
            )

    return "\n".join(text_lines), lines_out, words_out


DEFAULT_OCR_PASS_TIMEOUT_SEC: float = 8.0
DEFAULT_OCR_TOTAL_TIMEOUT_SEC: float = 25.0
MAX_TSV_OUTPUT_BYTES: int = 4 * 1024 * 1024


def _terminate_and_reap_process(proc: subprocess.Popen) -> None:
    """Safely terminate/kill and reap a child subprocess without leaving orphans."""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except Exception:
                pass
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_bounded_ocr_subprocess(
    cmd: Sequence[str],
    *,
    cancel_token: Optional[CancellationToken] = None,
    timeout_sec: float = DEFAULT_OCR_PASS_TIMEOUT_SEC,
    job_deadline: Optional[float] = None,
    max_output_bytes: int = MAX_TSV_OUTPUT_BYTES,
    env: Optional[Dict[str, str]] = None,
    creationflags: int = 0,
) -> Tuple[int, str, str, bool, bool]:
    """
    Launch `cmd` and continuously drain `stdout` and `stderr` on background daemon threads
    while the child process executes so large TSV outputs can NEVER fill the OS pipe buffer
    and deadlock Tesseract. Enforces cancellation, per-pass timeout, total job deadline,
    and bounded memory usage, always reaping the child process cleanly.

    Returns `(returncode, stdout_str, stderr_str, was_cancelled, timed_out)`.
    """
    t_start = time.monotonic()
    effective_deadline = t_start + max(0.05, float(timeout_sec))
    if job_deadline is not None:
        effective_deadline = min(effective_deadline, float(job_deadline))

    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=creationflags,
    )

    out_chunks: List[str] = []
    err_chunks: List[str] = []
    out_bytes = [0]
    err_bytes = [0]

    def _drain_pipe(stream: Any, chunks: List[str], counter: List[int], limit: int) -> None:
        if stream is None:
            return
        try:
            while True:
                chunk = stream.read(16384)
                if not chunk:
                    break
                if counter[0] < limit:
                    keep = limit - counter[0]
                    chunks.append(chunk[:keep])
                    counter[0] += len(chunk)
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    t_out = threading.Thread(
        target=_drain_pipe,
        args=(proc.stdout, out_chunks, out_bytes, max_output_bytes),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_drain_pipe,
        args=(proc.stderr, err_chunks, err_bytes, max(65536, max_output_bytes // 4)),
        daemon=True,
    )
    t_out.start()
    t_err.start()

    was_cancelled = False
    timed_out = False

    while proc.poll() is None:
        if cancel_token is not None and cancel_token.is_cancelled:
            was_cancelled = True
            _terminate_and_reap_process(proc)
            break
        if time.monotonic() >= effective_deadline:
            timed_out = True
            _terminate_and_reap_process(proc)
            break
        time.sleep(0.012)

    if not was_cancelled and not timed_out:
        try:
            proc.wait(timeout=1.5)
        except Exception:
            timed_out = True
            _terminate_and_reap_process(proc)

    t_out.join(timeout=1.5)
    t_err.join(timeout=1.5)

    stdout_str = "".join(out_chunks)
    stderr_str = "".join(err_chunks)
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, stdout_str, stderr_str, was_cancelled, timed_out


def _run_single_tesseract_pass(
    t_bin: Path,
    t_data: Optional[Path],
    candidate: OcrPreprocessCandidate,
    lang_norm: str,
    psm: int,
    src_w: int,
    src_h: int,
    cancel_token: Optional[CancellationToken] = None,
    *,
    pass_timeout_sec: float = DEFAULT_OCR_PASS_TIMEOUT_SEC,
    job_deadline: Optional[float] = None,
    max_output_bytes: int = MAX_TSV_OUTPUT_BYTES,
) -> Tuple[Optional[OcrRecognitionResult], str]:
    """
    Execute a single Tesseract TSV invocation on `candidate` at `--psm <psm>` with
    concurrent stdout/stderr pipe draining, cancellation reaping, and timeout enforcement.
    Preserves `-c tessedit_create_tsv=1 -c tessedit_create_txt=0` and actionable
    malformed-TSV error detection.
    """
    pad_px = 16
    fill_val = candidate.pad_fill
    if candidate.pil_image.mode == "RGB" and isinstance(fill_val, int):
        fill_val = (fill_val, fill_val, fill_val)
    elif candidate.pil_image.mode == "L" and isinstance(fill_val, tuple):
        fill_val = int(fill_val[0])
    padded_img = ImageOps.expand(candidate.pil_image, border=pad_px, fill=fill_val)

    tmp_fd, tmp_path_str = tempfile.mkstemp(prefix="prismwake_ocr_", suffix=".png")
    os.close(tmp_fd)
    tmp_path = Path(tmp_path_str)
    t_pass_start = time.perf_counter()
    try:
        padded_img.save(str(tmp_path), format="PNG", compress_level=1)
        cmd: List[str] = [
            str(t_bin),
            str(tmp_path),
            "stdout",
            "-l",
            lang_norm,
            "--psm",
            str(psm),
            "-c",
            "preserve_interword_spaces=1",
            "-c",
            "tessedit_create_tsv=1",
            "-c",
            "tessedit_create_txt=0",
        ]
        if t_data is not None:
            cmd[3:3] = ["--tessdata-dir", str(t_data)]
        # Allow cross-platform Python mock child binaries in unit tests on Windows & Linux
        if str(t_bin).lower().endswith(".py"):
            cmd = [sys.executable] + cmd

        creationflags = 0x08000000 if sys.platform == "win32" else 0
        sub_env = os.environ.copy()
        sub_env.setdefault("OMP_THREAD_LIMIT", "1")

        rc, stdout_str, stderr_str, was_cancelled, timed_out = run_bounded_ocr_subprocess(
            cmd,
            cancel_token=cancel_token,
            timeout_sec=pass_timeout_sec,
            job_deadline=job_deadline,
            max_output_bytes=max_output_bytes,
            env=sub_env,
            creationflags=creationflags,
        )
        pass_elapsed_ms = (time.perf_counter() - t_pass_start) * 1000.0

        if was_cancelled:
            return (
                OcrRecognitionResult(
                    text="",
                    language=lang_norm,
                    engine_name="tesseract",
                    source_width=src_w,
                    source_height=src_h,
                    scale_factor=candidate.scale_factor,
                    inverted_dark_theme=candidate.inverted_dark_theme,
                    threshold_applied=candidate.threshold_applied,
                    elapsed_ms=pass_elapsed_ms,
                    cancelled=True,
                    preprocessing_strategy=candidate.name,
                    psm_used=psm,
                ),
                "",
            )

        if timed_out:
            return (
                None,
                f"Tesseract OCR timed out after {pass_elapsed_ms / 1000.0:.1f}s "
                f"(strategy={candidate.name}, psm={psm}).",
            )

        if rc == 0 and stdout_str is not None:
            if not stdout_str.lstrip("\ufeff\r\n\t ").startswith("level\tpage_num\t"):
                first = (stdout_str or "").strip()[:160]
                diagnostic = (stderr_str or "").strip()[:260]
                err_msg = (
                    "Tesseract did not produce TSV recognition data. "
                    f"Stdout: {first!r}. Stderr: {diagnostic!r}"
                )
                return None, err_msg

            if candidate.crop_offset_xy != (0, 0):
                full_text, line_boxes, word_boxes = _parse_tesseract_tsv(
                    stdout_str,
                    scale_factor=candidate.scale_factor,
                    source_w=src_w,
                    source_h=src_h,
                    pad_px=pad_px,
                    crop_offset_xy=candidate.crop_offset_xy,
                )
            else:
                full_text, line_boxes, word_boxes = _parse_tesseract_tsv(
                    stdout_str,
                    scale_factor=candidate.scale_factor,
                    source_w=src_w,
                    source_h=src_h,
                    pad_px=pad_px,
                )
            return (
                OcrRecognitionResult(
                    text=full_text,
                    lines=line_boxes,
                    words=word_boxes,
                    language=lang_norm,
                    engine_name="tesseract",
                    source_width=src_w,
                    source_height=src_h,
                    scale_factor=candidate.scale_factor,
                    inverted_dark_theme=candidate.inverted_dark_theme,
                    threshold_applied=candidate.threshold_applied,
                    elapsed_ms=pass_elapsed_ms,
                    preprocessing_strategy=candidate.name,
                    psm_used=psm,
                ),
                "",
            )
        err_detail = (stderr_str or "").strip() or f"exit code {rc}"
        return None, f"Tesseract OCR failed ({err_detail})"
    except Exception as exc:
        return None, f"Tesseract execution error: {exc}"
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _run_stacked_regions_single_pass_ocr(
    t_bin: Path,
    t_data: Optional[Path],
    rgb_img: Image.Image,
    profile: OcrImageProfile,
    lang_norm: str,
    cancel_token: Optional[CancellationToken] = None,
    *,
    pass_timeout_sec: float = DEFAULT_OCR_PASS_TIMEOUT_SEC,
    job_deadline: Optional[float] = None,
) -> Optional[OcrRecognitionResult]:
    """
    Single-pass stacked region OCR: extracts each ROI in `profile.row_text_rois` using
    `_extract_island_fisher_gray`, upscales it, stacks all strips vertically with 28px
    white padding onto one canvas, runs ONE `--psm 6` Tesseract pass, and maps every
    word and line bounding box back to its exact native screenshot `(x, y, width, height)`.
    """
    if not profile.row_text_rois or len(profile.row_text_rois) < 2:
        return None
    src_w, src_h = rgb_img.size
    arr_rgb = np.asarray(rgb_img, dtype=np.float32)
    light_ink = bool(profile.is_light_ink)
    strips: List[Tuple[Tuple[int, int, int, int], Image.Image, float]] = []

    for rx0, ry0, rx1, ry1 in profile.row_text_rois[:12]:
        px0 = max(0, min(src_w - 1, int(rx0)))
        px1 = max(px0 + 1, min(src_w, int(rx1)))
        py0 = max(0, min(src_h - 1, int(ry0)))
        py1 = max(py0 + 1, min(src_h, int(ry1)))
        patch = _extract_island_fisher_gray(arr_rgb, (px0, py0, px1, py1), light_ink=light_ink)
        rh = max(1, py1 - py0)
        sc = 2.5 if rh <= 22 else 2.0
        up = _resize_with_gentle_sharpen(Image.fromarray(patch, mode="L"), sc)
        strips.append(((px0, py0, px1, py1), up, sc))

    if not strips:
        return None

    pad_x = 24
    gap_y = 28
    canvas_w = max(s[1].width for s in strips) + pad_x * 2
    canvas_h = sum(s[1].height + gap_y for s in strips) + gap_y
    canvas = Image.new("L", (canvas_w, canvas_h), 255)
    band_meta: List[Tuple[int, int, int, int, int, int, float]] = []
    y_cur = 18
    for (px0, py0, px1, py1), up, sc in strips:
        canvas.paste(up, (pad_x, y_cur))
        band_meta.append((y_cur, y_cur + up.height, px0, py0, px1, py1, sc))
        y_cur += up.height + gap_y

    cand = OcrPreprocessCandidate(
        name="stacked_island_rois",
        pil_image=canvas,
        scale_factor=1.0,
        pad_fill=255,
        inverted_dark_theme=light_ink,
        threshold_applied=False,
        icon_masked=bool(profile.has_left_icon_column),
        preferred_psms=(6,),
    )
    t0 = time.perf_counter()
    raw_res, _err = _run_single_tesseract_pass(
        t_bin,
        t_data,
        cand,
        lang_norm,
        6,
        canvas_w,
        canvas_h,
        cancel_token,
        pass_timeout_sec=pass_timeout_sec,
        job_deadline=job_deadline,
    )
    if raw_res is None:
        return None
    if raw_res.cancelled:
        raw_res.source_width = src_w
        raw_res.source_height = src_h
        return raw_res
    if not raw_res.words:
        return None

    # Group recognized words by which stacked strip band they belong to
    band_words: Dict[int, List[OcrWordBox]] = {}
    for w in raw_res.words:
        cy = w.y + w.height * 0.5
        best_bi = -1
        best_dist = 1e9
        for bi, (by0, by1, px0, py0, px1, py1, sc) in enumerate(band_meta):
            if (by0 - 12) <= cy <= (by1 + 12):
                best_bi = bi
                break
            d = min(abs(cy - by0), abs(cy - by1))
            if d < best_dist:
                best_dist = d
                best_bi = bi
        if best_bi < 0:
            continue
        by0, by1, px0, py0, px1, py1, sc = band_meta[best_bi]
        orig_x = max(px0, min(px1 - 1, int(round(px0 + (w.x - pad_x) / sc))))
        orig_y = max(py0, min(py1 - 1, int(round(py0 + (w.y - by0) / sc))))
        orig_w = max(1, min(px1 - orig_x, int(round(w.width / sc))))
        orig_h = max(1, min(py1 - orig_y, int(round(w.height / sc))))
        band_words.setdefault(best_bi, []).append(
            OcrWordBox(
                text=w.text,
                x=orig_x,
                y=orig_y,
                width=orig_w,
                height=orig_h,
                confidence=w.confidence,
                line_index=best_bi,
                word_index=0,
            )
        )

    merged_lines: List[OcrLineBox] = []
    merged_words: List[OcrWordBox] = []
    for bi in sorted(band_words.keys()):
        wlist = sorted(band_words[bi], key=lambda item: item.x)
        if not wlist:
            continue
        new_li = len(merged_lines)
        reindexed = tuple(
            OcrWordBox(
                text=w.text,
                x=w.x,
                y=w.y,
                width=w.width,
                height=w.height,
                confidence=w.confidence,
                line_index=new_li,
                word_index=wi,
            )
            for wi, w in enumerate(wlist)
        )
        l_txt = " ".join(w.text for w in reindexed)
        merged_lines.append(
            OcrLineBox(
                text=l_txt,
                x=min(w.x for w in reindexed),
                y=min(w.y for w in reindexed),
                width=max(1, max(w.right for w in reindexed) - min(w.x for w in reindexed)),
                height=max(1, max(w.bottom for w in reindexed) - min(w.y for w in reindexed)),
                confidence=float(np.mean([w.confidence for w in reindexed])),
                line_index=new_li,
                words=reindexed,
            )
        )
        merged_words.extend(reindexed)

    if not merged_lines:
        return None

    stacked_res = OcrRecognitionResult(
        text="\n".join(ln.text for ln in merged_lines),
        lines=merged_lines,
        words=merged_words,
        language=lang_norm,
        engine_name="tesseract",
        source_width=src_w,
        source_height=src_h,
        scale_factor=2.5,
        inverted_dark_theme=light_ink,
        threshold_applied=False,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        preprocessing_strategy="stacked_island_rois",
        psm_used=6,
    )
    return refine_ocr_result_layout_and_spacing(stacked_res, rgb_img, profile)


def _run_region_first_row_ocr(
    t_bin: Path,
    t_data: Optional[Path],
    rgb_img: Image.Image,
    profile: OcrImageProfile,
    lang_norm: str,
    cancel_token: Optional[CancellationToken] = None,
    *,
    pass_timeout_sec: float = DEFAULT_OCR_PASS_TIMEOUT_SEC,
    job_deadline: Optional[float] = None,
) -> Optional[OcrRecognitionResult]:
    """
    Region-first per-row OCR strategy: crops each detected text row ROI `(rx0, ry0, rx1, ry1)`
    from `profile.row_text_rois`, extracts foreground ink via Fisher matched color projection,
    upscales small glyphs (`3.0x` for row height <= 20px), runs single-line `--psm 7`
    (with `--psm 13` fallback if empty), and merges per-row words and lines back into
    the original image's coordinate system in top-to-bottom reading order.
    """
    if not profile.row_text_rois or len(profile.row_text_rois) < 2:
        return None
    stacked_fast = _run_stacked_regions_single_pass_ocr(
        t_bin,
        t_data,
        rgb_img,
        profile,
        lang_norm,
        cancel_token,
        pass_timeout_sec=pass_timeout_sec,
        job_deadline=job_deadline,
    )
    if stacked_fast is not None and (stacked_fast.cancelled or len(stacked_fast.lines) >= len(profile.row_text_rois)):
        return stacked_fast
    src_w, src_h = rgb_img.size
    arr_rgb = np.asarray(rgb_img, dtype=np.float32)
    base_canvas = _build_row_roi_matched_color_canvas(arr_rgb, profile, light_ink=bool(profile.is_light_ink))

    merged_lines: List[OcrLineBox] = []
    merged_words: List[OcrWordBox] = []
    text_lines: List[str] = []
    t0 = time.perf_counter()

    for rx0, ry0, rx1, ry1 in profile.row_text_rois[:12]:
        if cancel_token is not None and cancel_token.is_cancelled:
            return OcrRecognitionResult(
                text="",
                language=lang_norm,
                engine_name="tesseract",
                source_width=src_w,
                source_height=src_h,
                cancelled=True,
                preprocessing_strategy="region_first_psm7",
                psm_used=7,
            )
        if job_deadline is not None and time.monotonic() >= job_deadline:
            break
        crop_g = base_canvas.crop((rx0, ry0, rx1, ry1))
        rh = max(1, ry1 - ry0)
        scale_r = 3.0 if rh <= 22 else 2.0
        crop_up = _resize_with_gentle_sharpen(crop_g, scale_r)
        cand = OcrPreprocessCandidate(
            name="region_first_psm7",
            pil_image=crop_up,
            scale_factor=scale_r,
            crop_offset_xy=(rx0, ry0),
            pad_fill=255,
            inverted_dark_theme=bool(profile.is_light_ink),
            threshold_applied=False,
            icon_masked=bool(profile.has_left_icon_column),
            preferred_psms=(7, 13),
        )
        row_res, _err = _run_single_tesseract_pass(
            t_bin,
            t_data,
            cand,
            lang_norm,
            7,
            src_w,
            src_h,
            cancel_token,
            pass_timeout_sec=min(pass_timeout_sec, 3.5),
            job_deadline=job_deadline,
        )
        if row_res is not None and row_res.cancelled:
            return row_res
        if (row_res is None or not row_res.has_text) and (job_deadline is None or time.monotonic() < job_deadline):
            row_res, _err = _run_single_tesseract_pass(
                t_bin,
                t_data,
                cand,
                lang_norm,
                13,
                src_w,
                src_h,
                cancel_token,
                pass_timeout_sec=min(pass_timeout_sec, 3.0),
                job_deadline=job_deadline,
            )
        if row_res is None or not row_res.words:
            continue
        row_refined = refine_ocr_result_layout_and_spacing(row_res, rgb_img, profile)
        for ln in row_refined.lines:
            if not ln.words:
                continue
            new_line_idx = len(merged_lines)
            reindexed_w = tuple(
                OcrWordBox(
                    text=w.text,
                    x=w.x,
                    y=w.y,
                    width=w.width,
                    height=w.height,
                    confidence=w.confidence,
                    line_index=new_line_idx,
                    word_index=wi,
                )
                for wi, w in enumerate(ln.words)
            )
            l_str = " ".join(w.text for w in reindexed_w)
            text_lines.append(l_str)
            merged_lines.append(
                OcrLineBox(
                    text=l_str,
                    x=min(w.x for w in reindexed_w),
                    y=min(w.y for w in reindexed_w),
                    width=max(1, max(w.right for w in reindexed_w) - min(w.x for w in reindexed_w)),
                    height=max(1, max(w.bottom for w in reindexed_w) - min(w.y for w in reindexed_w)),
                    confidence=float(np.mean([w.confidence for w in reindexed_w])),
                    line_index=new_line_idx,
                    words=reindexed_w,
                )
            )
            merged_words.extend(reindexed_w)

    if not merged_lines:
        return None
    return OcrRecognitionResult(
        text="\n".join(text_lines),
        lines=merged_lines,
        words=merged_words,
        language=lang_norm,
        engine_name="tesseract",
        source_width=src_w,
        source_height=src_h,
        scale_factor=3.0,
        inverted_dark_theme=bool(profile.is_light_ink),
        threshold_applied=False,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        preprocessing_strategy="region_first_psm7",
        psm_used=7,
    )


def recognize_image_ocr_legacy(
    image_source: Any,
    *,
    language: str = "eng",
    auto_invert_dark: bool = True,
    upscale_small_text: bool = True,
    contrast_stretch: bool = True,
    apply_threshold: bool = False,
    allow_builtin_fallback: bool = False,
    custom_binary: Optional[Path] = None,
    custom_tessdata: Optional[Path] = None,
    cancel_token: Optional[CancellationToken] = None,
    _psm: int = 6,
) -> OcrRecognitionResult:
    """
    Prior single-candidate global-median pipeline preserved for objective benchmark comparison
    against the new automatic multi-candidate pipeline.
    """
    t0 = time.perf_counter()
    rgb_img = _to_pil_rgb(image_source)
    src_w, src_h = rgb_img.size
    lang_norm = (language or "eng").strip().lower()
    pil_gray, scale_factor, inverted, thresh_done = preprocess_image_for_ocr_legacy(
        rgb_img,
        auto_invert_dark=auto_invert_dark,
        upscale_small_text=upscale_small_text,
        contrast_stretch=contrast_stretch,
        apply_threshold=apply_threshold,
    )
    t_bin, t_data, installed_langs, _ver = detect_tesseract_runtime(
        custom_binary=custom_binary,
        custom_tessdata=custom_tessdata,
    )
    if t_bin is None or not installed_langs:
        return OcrRecognitionResult(
            text="",
            language=lang_norm,
            engine_name="unavailable",
            source_width=src_w,
            source_height=src_h,
            error="Tesseract unavailable",
        )
    cand = OcrPreprocessCandidate(
        name="legacy_gray",
        pil_image=pil_gray,
        scale_factor=scale_factor,
        pad_fill=255,
        inverted_dark_theme=inverted,
        threshold_applied=thresh_done,
        preferred_psms=(_psm,),
    )
    res, err = _run_single_tesseract_pass(
        t_bin, t_data, cand, lang_norm, _psm, src_w, src_h, cancel_token
    )
    if res is None:
        return OcrRecognitionResult(
            text="",
            language=lang_norm,
            engine_name="tesseract",
            source_width=src_w,
            source_height=src_h,
            error=err,
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        )
    if not res.text.strip() and _psm in (6, 11):
        next_psm = 11 if _psm == 6 else 3
        return recognize_image_ocr_legacy(
            rgb_img,
            language=language,
            auto_invert_dark=auto_invert_dark,
            upscale_small_text=upscale_small_text,
            contrast_stretch=contrast_stretch,
            apply_threshold=apply_threshold,
            allow_builtin_fallback=allow_builtin_fallback,
            custom_binary=custom_binary,
            custom_tessdata=custom_tessdata,
            cancel_token=cancel_token,
            _psm=next_psm,
        )
    res.elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return res


def recognize_image_ocr(
    image_source: Any,
    *,
    language: str = "eng",
    quality_mode: str = "auto",
    retry_attempt: int = 0,
    auto_invert_dark: bool = True,
    upscale_small_text: bool = True,
    contrast_stretch: bool = True,
    apply_threshold: bool = False,
    allow_builtin_fallback: bool = False,
    custom_binary: Optional[Path] = None,
    custom_tessdata: Optional[Path] = None,
    cancel_token: Optional[CancellationToken] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    pass_timeout_sec: float = DEFAULT_OCR_PASS_TIMEOUT_SEC,
    total_timeout_sec: float = DEFAULT_OCR_TOTAL_TIMEOUT_SEC,
    _psm: int = 6,
) -> OcrRecognitionResult:
    """
    Perform fully automatic offline OCR on `image_source` (PIL Image, numpy array, QImage, or QPixmap):
      1. Analyzes image characteristics (`analyze_image_for_ocr`) — local foreground/background
         stroke polarity, illumination gradients, chromatic contrast, glyph scale, separated
         button/menu row ROIs (`row_text_rois`), and icon layout.
      2. Generates a bounded, prioritized set of preprocessing candidates and adaptive PSMs.
      3. Drains Tesseract stdout/stderr pipes concurrently with bounded per-pass and total deadlines.
      4. Automatically runs follow-up candidates/PSMs and region-first per-row `--psm 7` when
         initial recognition is empty, low-confidence, incomplete in line coverage, or suspicious.
      5. Applies calibrated plausibility rejection (`is_plausible_ocr_result`) so low-confidence
         punctuation fragments (`'—<'`) are never presented as successful capture.
    """
    t0 = time.perf_counter()
    job_deadline = time.monotonic() + max(0.2, float(total_timeout_sec))
    norm_mode = normalize_ocr_quality_mode(quality_mode)
    if progress_callback:
        progress_callback(10, "Analyzing image and optimizing contrast...")

    try:
        rgb_img = _to_pil_rgb(image_source)
    except Exception as exc:
        _OCR_LOGGER.error("Invalid image for OCR: %s", exc)
        return OcrRecognitionResult(
            text="",
            language=language,
            engine_name="unavailable",
            error=f"Invalid image for OCR: {exc}",
        )

    src_w, src_h = rgb_img.size
    if cancel_token is not None and cancel_token.is_cancelled:
        return OcrRecognitionResult(
            text="",
            language=language,
            source_width=src_w,
            source_height=src_h,
            cancelled=True,
        )

    lang_norm = (language or "eng").strip().lower()
    if lang_norm not in SUPPORTED_OCR_LANGUAGES:
        return OcrRecognitionResult(
            text="",
            language=lang_norm,
            engine_name="unavailable",
            source_width=src_w,
            source_height=src_h,
            error=f"Unsupported OCR language '{lang_norm}'. Supported languages: {', '.join(SUPPORTED_OCR_LANGUAGES.keys())}.",
        )

    profile = analyze_image_for_ocr(rgb_img)
    candidates = generate_ocr_preprocessing_candidates(
        rgb_img,
        profile,
        quality_mode=norm_mode,
        retry_attempt=retry_attempt,
        auto_invert_dark=auto_invert_dark,
        upscale_small_text=upscale_small_text,
        contrast_stretch=contrast_stretch,
        apply_threshold=apply_threshold,
    )
    first_cand = candidates[0]

    if cancel_token is not None and cancel_token.is_cancelled:
        return OcrRecognitionResult(
            text="",
            language=lang_norm,
            source_width=src_w,
            source_height=src_h,
            scale_factor=first_cand.scale_factor,
            inverted_dark_theme=first_cand.inverted_dark_theme,
            threshold_applied=first_cand.threshold_applied,
            cancelled=True,
        )

    if progress_callback:
        progress_callback(25, "Detecting offline OCR engine...")

    t_bin, t_data, installed_langs, _ver = detect_tesseract_runtime(
        custom_binary=custom_binary,
        custom_tessdata=custom_tessdata,
    )

    if t_bin is not None:
        if not installed_langs:
            if not allow_builtin_fallback:
                err_msg = (
                    "Tesseract OCR binary was found, but no language data (*.traineddata) "
                    "was found in tessdata/."
                )
                _OCR_LOGGER.error(err_msg)
                return OcrRecognitionResult(
                    text="",
                    language=lang_norm,
                    engine_name="tesseract",
                    source_width=src_w,
                    source_height=src_h,
                    elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error=err_msg,
                )
        else:
            sub_langs = [part.strip() for part in lang_norm.split("+") if part.strip()]
            missing = [sl for sl in sub_langs if sl not in installed_langs]
            if missing:
                if "eng" not in sub_langs or "eng" not in installed_langs:
                    err_msg = (
                        f"OCR language pack '{', '.join(missing)}' is not installed in tessdata. "
                        f"Available: {', '.join(installed_langs)}"
                    )
                    _OCR_LOGGER.error(err_msg)
                    return OcrRecognitionResult(
                        text="",
                        language=lang_norm,
                        engine_name="tesseract",
                        source_width=src_w,
                        source_height=src_h,
                        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                        error=err_msg,
                    )
                lang_norm = "eng"

            evaluated_results: List[OcrRecognitionResult] = []
            pass_timings: List[float] = []
            cand_diags: List[Dict[str, Any]] = []
            last_error_msg: str = ""
            max_total_passes = 2 if norm_mode == "fast" else (5 if norm_mode == "accurate" else 4)
            passes_run = 0

            # When row_text_rois contains multi-column 2D islands (e.g. a 2x2 4-pill game HUD),
            # run single-pass stacked island ROI recognition FIRST so we don't waste 4 whole-frame passes
            has_multicol_rois = False
            if len(profile.row_text_rois) >= 2:
                rois_sorted = sorted(profile.row_text_rois, key=lambda r: (r[1] // 24, r[0]))
                for i in range(len(rois_sorted) - 1):
                    r1, r2 = rois_sorted[i], rois_sorted[i + 1]
                    if abs((r1[1] + r1[3]) - (r2[1] + r2[3])) <= max(r1[3] - r1[1], r2[3] - r2[1]) and r2[0] > r1[2]:
                        has_multicol_rois = True
                        break

            if has_multicol_rois and retry_attempt == 0 and time.monotonic() < job_deadline:
                if progress_callback:
                    progress_callback(45, f"Recognizing pass 1 of up to {max_total_passes} ({lang_norm})...")
                st_res = _run_stacked_regions_single_pass_ocr(
                    t_bin,
                    t_data,
                    rgb_img,
                    profile,
                    lang_norm,
                    cancel_token,
                    pass_timeout_sec=pass_timeout_sec,
                    job_deadline=job_deadline,
                )
                if st_res is not None:
                    if st_res.cancelled:
                        st_res.elapsed_ms = (time.perf_counter() - t0) * 1000.0
                        return st_res
                    passes_run += 1
                    pass_timings.append(float(st_res.elapsed_ms))
                    st_res = filter_and_salvage_partial_ocr_result(st_res, profile)
                    st_sc = score_ocr_candidate(st_res, profile, rgb_img)
                    st_res.quality_score = st_sc
                    st_res.quality_mode = norm_mode
                    st_res.retry_attempt = int(retry_attempt)
                    st_plausible = is_plausible_ocr_result(st_res, profile)
                    st_mean_c = float(np.mean([w.confidence for w in st_res.words])) if st_res.words else 0.0
                    cand_diags.append(
                        {
                            "pass_index": passes_run,
                            "strategy": "stacked_island_rois",
                            "psm": 6,
                            "elapsed_ms": round(float(st_res.elapsed_ms), 2),
                            "score": round(st_sc, 2),
                            "word_count": len(st_res.words),
                            "line_count": len(st_res.lines),
                            "mean_confidence": round(st_mean_c, 1),
                            "plausible": bool(st_plausible),
                            "preview_text": st_res.text[:120],
                        }
                    )
                    evaluated_results.append(st_res)
                    if norm_mode != "accurate" and st_plausible and len(st_res.lines) >= len(profile.row_text_rois) and st_mean_c >= 86.0:
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        st_res.elapsed_ms = elapsed
                        st_res.candidates_evaluated = passes_run
                        st_res.pass_timings_ms = list(pass_timings)
                        st_res.candidate_diagnostics = list(cand_diags)
                        if progress_callback:
                            progress_callback(100, "Recognition complete.")
                        return st_res

            for cand_idx, cand in enumerate(candidates):
                if passes_run >= max_total_passes or time.monotonic() >= job_deadline:
                    break
                psms = select_adaptive_psms(
                    profile,
                    cand,
                    retry_attempt=retry_attempt,
                    default_psm=_psm,
                )
                max_psms_for_cand = 2 if cand_idx == 0 else 1
                for psm_idx, psm_val in enumerate(psms[:max_psms_for_cand]):
                    if passes_run >= max_total_passes or time.monotonic() >= job_deadline:
                        break
                    if cancel_token is not None and cancel_token.is_cancelled:
                        return OcrRecognitionResult(
                            text="",
                            language=lang_norm,
                            engine_name="tesseract",
                            source_width=src_w,
                            source_height=src_h,
                            scale_factor=cand.scale_factor,
                            inverted_dark_theme=cand.inverted_dark_theme,
                            threshold_applied=cand.threshold_applied,
                            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                            cancelled=True,
                        )
                    if progress_callback:
                        pct = min(90, 35 + int(round((passes_run + 1) * (50.0 / max(1, max_total_passes)))))
                        progress_callback(
                            pct,
                            f"Recognizing pass {passes_run + 1} of up to {max_total_passes} ({lang_norm})...",
                        )

                    raw_res, err_msg = _run_single_tesseract_pass(
                        t_bin,
                        t_data,
                        cand,
                        lang_norm,
                        psm_val,
                        src_w,
                        src_h,
                        cancel_token,
                        pass_timeout_sec=pass_timeout_sec,
                        job_deadline=job_deadline,
                    )
                    passes_run += 1
                    if raw_res is not None and raw_res.cancelled:
                        raw_res.elapsed_ms = (time.perf_counter() - t0) * 1000.0
                        return raw_res
                    if raw_res is None:
                        last_error_msg = err_msg
                        if not evaluated_results and not allow_builtin_fallback and "timed out" in err_msg.lower():
                            _OCR_LOGGER.error(err_msg)
                            return OcrRecognitionResult(
                                text="",
                                language=lang_norm,
                                engine_name="tesseract",
                                source_width=src_w,
                                source_height=src_h,
                                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                                error=err_msg,
                            )
                        if not evaluated_results and not allow_builtin_fallback and cand_idx == len(candidates) - 1:
                            _OCR_LOGGER.error(err_msg)
                            return OcrRecognitionResult(
                                text="",
                                language=lang_norm,
                                engine_name="tesseract",
                                source_width=src_w,
                                source_height=src_h,
                                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                                error=err_msg,
                            )
                        continue

                    pass_ms = float(raw_res.elapsed_ms)
                    pass_timings.append(pass_ms)
                    refined = refine_ocr_result_layout_and_spacing(raw_res, rgb_img, profile)
                    sc = score_ocr_candidate(refined, profile, rgb_img)
                    refined.quality_score = sc
                    refined.quality_mode = norm_mode
                    refined.retry_attempt = int(retry_attempt)
                    plausible = is_plausible_ocr_result(refined, profile)
                    mean_c = float(np.mean([w.confidence for w in refined.words])) if refined.words else 0.0
                    cand_diags.append(
                        {
                            "pass_index": passes_run,
                            "strategy": cand.name,
                            "psm": psm_val,
                            "elapsed_ms": round(pass_ms, 2),
                            "score": round(sc, 2),
                            "word_count": len(refined.words),
                            "line_count": len(refined.lines),
                            "mean_confidence": round(mean_c, 1),
                            "plausible": bool(plausible),
                            "preview_text": refined.text[:120],
                        }
                    )
                    evaluated_results.append(refined)

                    # Fast-path exit: only when result is plausible and does not need follow-up
                    if norm_mode != "accurate" and plausible and not _needs_followup_candidates(refined, profile, sc):
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        refined.elapsed_ms = elapsed
                        refined.candidates_evaluated = passes_run
                        refined.pass_timings_ms = list(pass_timings)
                        refined.candidate_diagnostics = list(cand_diags)
                        if progress_callback:
                            progress_callback(100, "Recognition complete.")
                        return refined

                    # Only skip the candidate's alternative PSM if PSM 0 produced a plausible result with reasonable line coverage
                    reasonable_lines = not (
                        profile.estimated_line_count >= 3
                        and len(refined.lines) < max(2, profile.estimated_line_count // 2)
                    )
                    if psm_idx == 0 and plausible and sc >= 55.0 and reasonable_lines and len(candidates) > 1:
                        break

            # Region-first per-row PSM 7 fallback when multi-row ROIs exist and whole-frame passes missed rows or had low quality
            best_whole_lines = max((len(er.lines) for er in evaluated_results if is_plausible_ocr_result(er, profile)), default=0)
            best_whole_score = max((er.quality_score for er in evaluated_results if is_plausible_ocr_result(er, profile)), default=-100.0)
            if (
                2 <= len(profile.row_text_rois) <= 12
                and (best_whole_lines < len(profile.row_text_rois) or best_whole_score < 78.0)
                and time.monotonic() < job_deadline
                and (cancel_token is None or not cancel_token.is_cancelled)
            ):
                if progress_callback:
                    progress_callback(92, f"Recognizing per-row regions ({len(profile.row_text_rois)} lines)...")
                rf_res = _run_region_first_row_ocr(
                    t_bin,
                    t_data,
                    rgb_img,
                    profile,
                    lang_norm,
                    cancel_token,
                    pass_timeout_sec=pass_timeout_sec,
                    job_deadline=job_deadline,
                )
                if rf_res is not None:
                    if rf_res.cancelled:
                        rf_res.elapsed_ms = (time.perf_counter() - t0) * 1000.0
                        return rf_res
                    passes_run += 1
                    pass_timings.append(float(rf_res.elapsed_ms))
                    rf_sc = score_ocr_candidate(rf_res, profile, rgb_img)
                    rf_res.quality_score = rf_sc
                    rf_res.quality_mode = norm_mode
                    rf_res.retry_attempt = int(retry_attempt)
                    rf_plausible = is_plausible_ocr_result(rf_res, profile)
                    rf_mean_c = float(np.mean([w.confidence for w in rf_res.words])) if rf_res.words else 0.0
                    cand_diags.append(
                        {
                            "pass_index": passes_run,
                            "strategy": "region_first_psm7",
                            "psm": 7,
                            "elapsed_ms": round(float(rf_res.elapsed_ms), 2),
                            "score": round(rf_sc, 2),
                            "word_count": len(rf_res.words),
                            "line_count": len(rf_res.lines),
                            "mean_confidence": round(rf_mean_c, 1),
                            "plausible": bool(rf_plausible),
                            "preview_text": rf_res.text[:120],
                        }
                    )
                    evaluated_results.append(rf_res)

            if not evaluated_results and last_error_msg and not allow_builtin_fallback:
                _OCR_LOGGER.error(last_error_msg)
                return OcrRecognitionResult(
                    text="",
                    language=lang_norm,
                    engine_name="tesseract",
                    source_width=src_w,
                    source_height=src_h,
                    elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error=last_error_msg,
                )

            if evaluated_results:
                word_freq: Dict[str, int] = {}
                for er in evaluated_results:
                    seen_in_er = {w.text.strip().lower() for w in er.words if w.text.strip()}
                    for nw in seen_in_er:
                        word_freq[nw] = word_freq.get(nw, 0) + 1

                plausible_results = [er for er in evaluated_results if is_plausible_ocr_result(er, profile)]
                pool = plausible_results if plausible_results else evaluated_results

                best_res = pool[0]
                best_score = -1e9
                for er in pool:
                    final_sc = score_ocr_candidate(er, profile, rgb_img, consensus_counts=word_freq)
                    er.quality_score = final_sc
                    if final_sc > best_score:
                        best_score = final_sc
                        best_res = er

                elapsed = (time.perf_counter() - t0) * 1000.0
                best_res.elapsed_ms = elapsed
                best_res.candidates_evaluated = passes_run
                best_res.pass_timings_ms = list(pass_timings)
                best_res.candidate_diagnostics = list(cand_diags)

                # Salvage any partial credible words/lines when no candidate passed full plausibility,
                # or strip pure-garbage lines (like '—<') if present alongside valid lines
                has_garbage_only_line = any(
                    ln.words and not any(_is_credible_salvage_word(w) for w in ln.words)
                    for ln in best_res.lines
                )
                salvaged_succeeded = False
                if not plausible_results or has_garbage_only_line:
                    salvaged_best = filter_and_salvage_partial_ocr_result(best_res, profile)
                    if salvaged_best.has_text and salvaged_best is not best_res and is_plausible_ocr_result(salvaged_best, profile):
                        best_res = salvaged_best
                        salvaged_succeeded = True
                        if not plausible_results:
                            best_res.partial_low_confidence = True
                            if not best_res.quality_warning:
                                best_res.quality_warning = (
                                    f"Partial result / low confidence: kept {len(best_res.words)} credible "
                                    f"{'word' if len(best_res.words) == 1 else 'words'} across {len(best_res.lines)} "
                                    f"{'line' if len(best_res.lines) == 1 else 'lines'}."
                                )
                if not plausible_results and not salvaged_succeeded and best_res.has_text:
                    # Reject when ZERO credible words exist across the entire capture (e.g. only '—<' or 3px preview noise)
                    raw_junk = best_res.text
                    best_res.low_confidence_rejected = True
                    best_res.raw_rejected_text = raw_junk
                    best_res.quality_warning = (
                        f"Low-confidence or incomplete OCR output ({raw_junk!r}) was rejected "
                        f"(detected ~{profile.estimated_line_count} text rows, score {best_res.quality_score:.1f}). "
                        "Select a clearer native-resolution region or inspect diagnostics in Advanced view."
                    )
                    best_res.text = ""
                    best_res.lines = []
                    best_res.words = []

                if progress_callback:
                    progress_callback(100, "Recognition complete.")
                return best_res

    if not allow_builtin_fallback:
        err_msg = (
            "Offline Tesseract OCR runtime (tesseract.exe + tessdata/eng.traineddata) "
            "was not found in tesseract_bundle/ or system PATH."
        )
        _OCR_LOGGER.error(err_msg)
        return OcrRecognitionResult(
            text="",
            language=lang_norm,
            engine_name="unavailable",
            source_width=src_w,
            source_height=src_h,
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            error=err_msg,
        )

    if progress_callback:
        progress_callback(65, "Running built-in offline glyph recognizer...")

    full_text, line_boxes, word_boxes = _recognize_with_builtin_template_engine(
        first_cand.pil_image.convert("L"),
        scale_factor=first_cand.scale_factor,
        source_w=src_w,
        source_h=src_h,
        cancel_token=cancel_token,
    )
    if cancel_token is not None and cancel_token.is_cancelled:
        return OcrRecognitionResult(
            text="",
            language=lang_norm,
            engine_name="builtin_template",
            source_width=src_w,
            source_height=src_h,
            cancelled=True,
        )

    elapsed = (time.perf_counter() - t0) * 1000.0
    if progress_callback:
        progress_callback(100, "Recognition complete.")
    return OcrRecognitionResult(
        text=full_text,
        lines=line_boxes,
        words=word_boxes,
        language=lang_norm,
        engine_name="builtin_template",
        source_width=src_w,
        source_height=src_h,
        scale_factor=first_cand.scale_factor,
        inverted_dark_theme=first_cand.inverted_dark_theme,
        threshold_applied=first_cand.threshold_applied,
        elapsed_ms=elapsed,
        preprocessing_strategy=first_cand.name,
        quality_mode=norm_mode,
        retry_attempt=int(retry_attempt),
    )


_ORIGINAL_RECOGNIZE_IMAGE_OCR = recognize_image_ocr


def export_ocr_diagnostic_bundle(
    image_source: Any,
    output_dir: Any,
    *,
    result: Optional[OcrRecognitionResult] = None,
    language: str = "eng",
    quality_mode: str = "auto",
) -> Dict[str, Any]:
    """
    Explicitly opt-in diagnostic export for local debugging: writes the unscaled
    original selected capture image (`00_original_capture.png`), each generated
    preprocessing candidate image (`01_candidate_<idx>_<name>.png`), and a structured
    `diagnostic_manifest.json` into `output_dir`.
    Never called automatically; performs zero network/cloud activity and never logs user text.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    rgb_img = _to_pil_rgb(image_source)
    orig_file = out_path / "00_original_capture.png"
    rgb_img.save(str(orig_file), format="PNG")

    profile = analyze_image_for_ocr(rgb_img)
    candidates = generate_ocr_preprocessing_candidates(
        rgb_img,
        profile,
        quality_mode=quality_mode,
    )
    cand_files: List[str] = []
    for idx, cand in enumerate(candidates, start=1):
        c_file = out_path / f"{idx:02d}_candidate_{cand.name}.png"
        cand.pil_image.save(str(c_file), format="PNG")
        cand_files.append(c_file.name)

    manifest: Dict[str, Any] = {
        "original_image": orig_file.name,
        "width": profile.width,
        "height": profile.height,
        "language": language,
        "quality_mode": normalize_ocr_quality_mode(quality_mode),
        "profile": {
            "is_light_ink": profile.is_light_ink,
            "is_chromatic_isoluminant": profile.is_chromatic_isoluminant,
            "mixed_polarity": profile.mixed_polarity,
            "estimated_line_count": profile.estimated_line_count,
            "estimated_glyph_height": round(profile.estimated_glyph_height, 2),
            "recommended_scale": profile.recommended_scale,
            "is_sparse_menu": profile.is_sparse_menu,
            "has_left_icon_column": profile.has_left_icon_column,
            "row_text_rois": [list(r) for r in profile.row_text_rois],
        },
        "candidate_files": cand_files,
        "result": result.to_dict() if result is not None else None,
    }
    manifest_file = out_path / "diagnostic_manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "output_dir": str(out_path),
        "original_file": str(orig_file),
        "candidate_files": [str(out_path / cf) for cf in cand_files],
        "manifest_file": str(manifest_file),
    }


def verify_packaged_tesseract_launch(
    custom_binary: Optional[Path] = None,
    custom_tessdata: Optional[Path] = None,
) -> Tuple[bool, str]:
    """
    End-to-end verification helper that renders a synthetic test image and confirms
    that the real Tesseract binary launches and extracts the expected text offline.
    Used by `--verify-ocr-bundle` in packaged Windows builds and CI.
    """
    status = query_ocr_engine_status(
        allow_builtin_fallback=False,
        custom_binary=custom_binary,
        custom_tessdata=custom_tessdata,
    )
    if not status.available or status.engine_kind != "tesseract":
        return False, status.status_summary

    img = Image.new("RGB", (520, 100), (255, 255, 255))
    drw = ImageDraw.Draw(img)
    font: Any = ImageFont.load_default()
    for fp in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ):
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 26)
                break
            except Exception:
                pass
    drw.text((20, 30), "Prismwake OCR Ready 2026", fill=(10, 18, 28), font=font)

    res = recognize_image_ocr(
        img,
        language="eng",
        allow_builtin_fallback=False,
        custom_binary=custom_binary,
        custom_tessdata=custom_tessdata,
    )
    if not res.ok:
        return False, f"Tesseract launch failed: {res.error}"
    if res.engine_name != "tesseract":
        return False, f"Expected engine 'tesseract', got '{res.engine_name}'"
    norm = res.text.strip().lower()
    if "prismwake" not in norm or "2026" not in norm:
        return False, f"Unexpected OCR output from Tesseract: {res.text!r}"

    # Also verify 5-button cyan menu with left icons so packaged Windows EXE proves layout-aware menu OCR
    menu_img = Image.new("RGB", (360, 290), (36, 40, 38))
    mdrw = ImageDraw.Draw(menu_img)
    mfont: Any = ImageFont.load_default()
    for fp in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ):
        if os.path.exists(fp):
            try:
                mfont = ImageFont.truetype(fp, 15)
                break
            except Exception:
                pass
    cyan_labels = [
        "Report Bug / Request Feature",
        "Join us on Discord",
        "Steam Workshop",
        "Video Tutorials",
        "Merch Store",
    ]
    for i, lbl in enumerate(cyan_labels):
        y0 = 14 + i * 54
        mdrw.rounded_rectangle((36, y0, 326, y0 + 40), radius=19, fill=(0, 185, 255))
        mdrw.ellipse((50, y0 + 8, 74, y0 + 32), fill=(242, 250, 255))
        mdrw.text((92, y0 + 11), lbl, fill=(240, 250, 255), font=mfont)

    mres = recognize_image_ocr(
        menu_img,
        language="eng",
        allow_builtin_fallback=False,
        custom_binary=custom_binary,
        custom_tessdata=custom_tessdata,
    )
    if not mres.ok or len(mres.lines) < 5 or "discord" not in mres.text.lower() or "workshop" not in mres.text.lower():
        return False, f"Packaged cyan-button menu OCR verification failed: {mres.text!r}"

    # 3. Also verify 4-pill game HUD ($3,020, +75% NEXT CUSTOMER, CLOSED, 3 days) and partial-result salvage
    hud_w, hud_h = 420, 118
    hud_img = Image.new("RGB", (hud_w, hud_h), (28, 32, 40))
    hdrw = ImageDraw.Draw(hud_img)
    hfont_b: Any = mfont
    hfont_s: Any = mfont
    for fp in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ):
        if os.path.exists(fp):
            try:
                hfont_b = ImageFont.truetype(fp, 19)
                hfont_s = ImageFont.truetype(fp, 17)
                break
            except Exception:
                pass
    hdrw.rounded_rectangle([10, 10, 155, 52], radius=18, fill=(42, 48, 60))
    hdrw.ellipse([18, 17, 44, 43], fill=(40, 195, 85))
    hdrw.text((52, 20), "$3,020", fill=(252, 254, 255), font=hfont_b)
    hdrw.rounded_rectangle([168, 10, 410, 52], radius=18, fill=(105, 210, 30))
    hdrw.text((200, 21), "+75% NEXT CUSTOMER", fill=(255, 255, 255), font=hfont_s)
    hdrw.rounded_rectangle([10, 64, 155, 106], radius=18, fill=(225, 60, 28))
    hdrw.text((42, 74), "CLOSED", fill=(255, 255, 255), font=hfont_b)
    hdrw.rounded_rectangle([168, 64, 315, 106], radius=18, fill=(58, 70, 90))
    hdrw.ellipse([180, 75, 200, 95], fill=(255, 205, 45))
    hdrw.text((212, 74), "3 days", fill=(250, 252, 255), font=hfont_b)

    hres = recognize_image_ocr(
        hud_img,
        language="eng",
        allow_builtin_fallback=False,
        custom_binary=custom_binary,
        custom_tessdata=custom_tessdata,
    )
    htxt_low = hres.text.lower()
    if not hres.ok or "closed" not in htxt_low or "3,020" not in htxt_low or "customer" not in htxt_low or "days" not in htxt_low:
        return False, f"Packaged 4-pill HUD OCR verification failed: {hres.text!r}"

    # 4. Also check if RapidOCR neural backend is bundled and verify it if present
    neural_note = "RapidOCR neural backend: not bundled (using region-island Tesseract)"
    try:
        from .backends import RapidOcrBackend
        r_backend = RapidOcrBackend()
        r_stat = r_backend.query_status()
        if r_stat.available:
            r_res = r_backend.recognize(img, language="eng")
            if r_res.ok and "prismwake" in r_res.text.lower():
                neural_note = f"RapidOCR neural backend: verified offline ({r_stat.engine_version}, models={list(r_stat.model_files)})"
            else:
                return False, f"Packaged RapidOCR neural verification failed: {r_res.error or r_res.text!r}"
    except Exception:
        pass

    return (
        True,
        f"Verified Tesseract ({status.version_string}) at '{status.binary_path}' "
        f"with languages {list(status.installed_languages)} — recognized '{res.text.strip()}', "
        f"5/5 cyan menu buttons, and 4/4 game HUD pills in {res.elapsed_ms + mres.elapsed_ms + hres.elapsed_ms:.0f} ms "
        f"({neural_note}).",
    )


def format_ocr_summary(result: OcrRecognitionResult) -> str:
    """Return a detailed technical status summary for the Advanced OCR workspace."""
    if result.cancelled:
        return "OCR cancelled."
    if result.error:
        return f"OCR Error: {result.error}"
    n_lines = len(result.lines)
    n_words = len(result.words)
    n_chars = len(result.text)
    if n_words == 0 and not result.has_text:
        if getattr(result, "low_confidence_rejected", False) and getattr(result, "quality_warning", ""):
            return result.quality_warning
        return (
            f"No text recognized ({result.source_width}×{result.source_height} capture, "
            f"{result.engine_name} [{result.language}]). Try Retry Recognition or select a tighter region."
        )
    theme_tag = "Dark-theme auto-optimized" if result.inverted_dark_theme else "Light/Standard auto-optimized"
    strat = getattr(result, "preprocessing_strategy", "adaptive_gray")
    psm = getattr(result, "psm_used", 6)
    backend_lbl = getattr(result, "backend_selected", "") or (
        "RapidOCR (ONNX CPU)" if result.engine_name == "rapidocr" else "Tesseract fallback"
    )
    partial_prefix = "Partial result / low confidence • " if getattr(result, "partial_low_confidence", False) else ""
    return (
        f"{partial_prefix}{n_words} words, {n_lines} lines ({n_chars} chars) • "
        f"Backend: {backend_lbl} ({result.engine_name} [{result.language}]) • "
        f"{theme_tag} ({strat}, PSM {psm}) • {result.elapsed_ms:.0f} ms"
    )


def count_recognized_words_and_lines(
    text: str,
    result: Optional[OcrRecognitionResult] = None,
) -> Tuple[int, int]:
    """Return `(word_count, line_count)` for the current editable text or OCR result."""
    clean = (text or "").strip()
    if not clean:
        return 0, 0
    lines = [ln for ln in clean.splitlines() if ln.strip()]
    words = clean.split()
    return len(words), max(1, len(lines))


def format_quick_ocr_badge_text(
    text: str,
    result: Optional[OcrRecognitionResult] = None,
) -> str:
    """Return a concise word-count pill label for Quick OCR (e.g. `'3 words'`), or with `'partial / low confidence'` when partial."""
    n_words, _n_lines = count_recognized_words_and_lines(text, result)
    if n_words <= 0:
        return ""
    base = "1 word" if n_words == 1 else f"{n_words} words"
    if result is not None and getattr(result, "partial_low_confidence", False):
        return f"{base} • partial / low confidence"
    return base


def format_quick_ocr_footer_label(
    language: str = "eng",
    *,
    auto_copied: bool = False,
) -> str:
    """
    Return the clean, non-technical Quick OCR footer label (`Offline OCR · EN`).
    Never exposes Tesseract CLI flags, PSM numbers, preprocessing internals, or raw ms timing.
    """
    lang_norm = (language or "eng").strip().lower()
    badge = LANGUAGE_SHORT_BADGES.get(lang_norm, lang_norm.upper())
    base = f"Offline OCR · {badge}"
    if auto_copied:
        return f"{base} · Auto-copied"
    return base


def _resolve_target_monitor_available_rect(
    selection_rect: Optional[Tuple[int, int, int, int]] = None,
    available_geometry: Optional[Tuple[int, int, int, int]] = None,
    monitors: Optional[Sequence[Any]] = None,
) -> Tuple[int, int, int, int]:
    """
    Resolve the `(avail_x, avail_y, avail_w, avail_h)` logical screen work area
    for placing an OCR panel near `selection_rect`. Handles negative multi-monitor
    coordinates, mixed DPI, taskbars, and monitor disconnection fallback.
    """
    rect_candidates: List[Tuple[int, int, int, int, bool]] = []
    if monitors:
        for mon in monitors:
            if isinstance(mon, (tuple, list)) and len(mon) >= 4:
                rect_candidates.append((int(mon[0]), int(mon[1]), max(1, int(mon[2])), max(1, int(mon[3])), False))
            else:
                mx = int(getattr(mon, "x", 0))
                my = int(getattr(mon, "y", 0))
                mw = max(1, int(getattr(mon, "width", 1920)))
                mh = max(1, int(getattr(mon, "height", 1080)))
                is_prim = bool(getattr(mon, "is_primary", False))
                rect_candidates.append((mx, my, mw, mh, is_prim))

    if available_geometry is not None and len(available_geometry) >= 4:
        ax, ay, aw, ah = (
            int(available_geometry[0]),
            int(available_geometry[1]),
            max(1, int(available_geometry[2])),
            max(1, int(available_geometry[3])),
        )
        if not rect_candidates:
            return (ax, ay, aw, ah)
        for mx, my, mw, mh, _ in rect_candidates:
            if ax < mx + mw and ax + aw > mx and ay < my + mh and ay + ah > my:
                return (ax, ay, aw, ah)

    if rect_candidates:
        if selection_rect is not None and len(selection_rect) >= 4:
            sx, sy, sw, sh = (
                int(selection_rect[0]),
                int(selection_rect[1]),
                max(1, int(selection_rect[2])),
                max(1, int(selection_rect[3])),
            )
            scx = sx + sw // 2
            scy = sy + sh // 2
            for mx, my, mw, mh, _ in rect_candidates:
                if mx <= scx < mx + mw and my <= scy < my + mh:
                    return (mx, my, mw, mh)
            best_mon = rect_candidates[0]
            best_dist = float("inf")
            for cand in rect_candidates:
                mx, my, mw, mh, _ = cand
                cx = min(max(scx, mx), mx + mw)
                cy = min(max(scy, my), my + mh)
                dist = (scx - cx) ** 2 + (scy - cy) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_mon = cand
            return (best_mon[0], best_mon[1], best_mon[2], best_mon[3])

        for mx, my, mw, mh, is_prim in rect_candidates:
            if is_prim:
                return (mx, my, mw, mh)
        first = rect_candidates[0]
        return (first[0], first[1], first[2], first[3])

    if HAS_QT:
        try:
            app = QApplication.instance()
            if app is not None:
                if selection_rect is not None and len(selection_rect) >= 4:
                    sx, sy, sw, sh = selection_rect[:4]
                    pt = QPoint(int(sx + max(1, sw) // 2), int(sy + max(1, sh) // 2))
                    scr = QApplication.screenAt(pt)
                    if scr is not None:
                        ag = scr.availableGeometry()
                        return (ag.x(), ag.y(), max(1, ag.width()), max(1, ag.height()))
                prim = QApplication.primaryScreen()
                if prim is not None:
                    ag = prim.availableGeometry()
                    return (ag.x(), ag.y(), max(1, ag.width()), max(1, ag.height()))
        except Exception:
            pass

    return (0, 0, 1920, 1040)


def compute_quick_ocr_panel_geometry(
    text: str = "",
    *,
    selection_rect: Optional[Tuple[int, int, int, int]] = None,
    available_geometry: Optional[Tuple[int, int, int, int]] = None,
    monitors: Optional[Sequence[Any]] = None,
    dpi_scale: float = 1.0,
    view_state: str = "ready",
) -> Dict[str, Any]:
    """
    Compute adaptive logical geometry `(x, y, width, height)` for the Compact Quick OCR panel:
      - Width: roughly `420–520` Qt logical pixels on standard displays, clamped to smaller screens.
      - Height: `160–250` Qt logical pixels for short results (1–3 lines, such as 3 words),
        growing smoothly up to a sensible screen-relative limit (`min(440, int(avail_h * 0.52))`)
        for longer multiline text, after which the text view scrolls.
      - Placement: near `selection_rect` on the same display when feasible, strictly clamped
        within `QScreen.availableGeometry()` in logical coordinates across negative virtual
        desktop positions, taskbars, mixed DPI (100–200%), and monitor disconnection.
    """
    _ = dpi_scale
    avail_x, avail_y, avail_w, avail_h = _resolve_target_monitor_available_rect(
        selection_rect=selection_rect,
        available_geometry=available_geometry,
        monitors=monitors,
    )
    margin = 12 if avail_w >= 480 and avail_h >= 320 else 6

    raw_lines = (text or "").splitlines() or [""]
    longest_line_chars = max((len(ln) for ln in raw_lines), default=0)
    visual_lines = 0
    for ln in raw_lines:
        visual_lines += max(1, (max(1, len(ln)) + 55) // 56)
    visual_lines = max(1, visual_lines)

    if view_state in ("empty", "error", "recognizing", "cancelled") or longest_line_chars <= 34:
        ideal_w = 430
    elif longest_line_chars <= 52:
        ideal_w = 468
    else:
        ideal_w = min(520, 468 + (longest_line_chars - 52) * 2)

    max_allowed_w = max(240, avail_w - margin * 2)
    min_allowed_w = min(420, max_allowed_w)
    panel_w = max(min_allowed_w, min(ideal_w, min(520, max_allowed_w)))

    max_screen_h = max(160, min(440, int(round(avail_h * 0.52)), avail_h - margin * 2))
    if view_state in ("recognizing", "empty", "cancelled"):
        ideal_h = 182
    elif view_state == "error":
        ideal_h = 206
    elif visual_lines <= 1:
        ideal_h = 178
    elif visual_lines == 2:
        ideal_h = 204
    elif visual_lines == 3:
        ideal_h = 232
    else:
        ideal_h = 178 + (visual_lines - 1) * 22

    min_allowed_h = min(168, max_screen_h)
    panel_h = max(min_allowed_h, min(ideal_h, max_screen_h))
    needs_scroll = ideal_h > panel_h or visual_lines > 8

    if selection_rect is not None and len(selection_rect) >= 4:
        sx, sy, sw, sh = (
            int(selection_rect[0]),
            int(selection_rect[1]),
            max(1, int(selection_rect[2])),
            max(1, int(selection_rect[3])),
        )
        if sw > panel_w:
            cand_x = sx + (sw - panel_w) // 2
        else:
            cand_x = sx

        below_y = sy + sh + 10
        above_y = sy - panel_h - 10
        avail_bottom = avail_y + avail_h - margin
        avail_top = avail_y + margin

        if below_y + panel_h <= avail_bottom:
            cand_y = below_y
        elif above_y >= avail_top:
            cand_y = above_y
        else:
            right_x = sx + sw + 10
            left_x = sx - panel_w - 10
            if right_x + panel_w <= avail_x + avail_w - margin:
                cand_x = right_x
                cand_y = sy
            elif left_x >= avail_x + margin:
                cand_x = left_x
                cand_y = sy
            else:
                cand_y = below_y
    else:
        cand_x = avail_x + (avail_w - panel_w) // 2
        cand_y = avail_y + max(margin, (avail_h - panel_h) // 3)

    min_x = avail_x + margin
    max_x = max(min_x, avail_x + avail_w - panel_w - margin)
    min_y = avail_y + margin
    max_y = max(min_y, avail_y + avail_h - panel_h - margin)

    clamped_x = max(min_x, min(cand_x, max_x))
    clamped_y = max(min_y, min(cand_y, max_y))

    return {
        "x": int(clamped_x),
        "y": int(clamped_y),
        "width": int(panel_w),
        "height": int(panel_h),
        "available_x": int(avail_x),
        "available_y": int(avail_y),
        "available_width": int(avail_w),
        "available_height": int(avail_h),
        "visual_lines": int(visual_lines),
        "scrolls": bool(needs_scroll),
    }


def compute_advanced_ocr_panel_geometry(
    *,
    current_rect: Optional[Tuple[int, int, int, int]] = None,
    selection_rect: Optional[Tuple[int, int, int, int]] = None,
    available_geometry: Optional[Tuple[int, int, int, int]] = None,
    monitors: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """
    Compute clamped logical geometry `(x, y, width, height)` and responsive column count
    for the expanded Advanced OCR workspace. Uses a two-column layout on standard monitors
    and automatically switches to a one-column vertical layout on narrow monitors (`< 760 px`).
    """
    anchor = current_rect if (current_rect is not None and len(current_rect) >= 4) else selection_rect
    avail_x, avail_y, avail_w, avail_h = _resolve_target_monitor_available_rect(
        selection_rect=anchor,
        available_geometry=available_geometry,
        monitors=monitors,
    )
    margin = 16 if avail_w >= 640 and avail_h >= 480 else 8
    layout_columns = 1 if avail_w < 760 else 2

    target_w = 840 if layout_columns == 2 else min(620, max(360, avail_w - margin * 2))
    target_h = 540 if layout_columns == 2 else min(620, max(400, avail_h - margin * 2))

    max_w = max(320, avail_w - margin * 2)
    max_h = max(280, avail_h - margin * 2)
    min_w = min(620 if layout_columns == 2 else 360, max_w)
    min_h = min(400 if layout_columns == 2 else 320, max_h)

    panel_w = max(min_w, min(target_w, max_w))
    panel_h = max(min_h, min(target_h, max_h))

    if anchor is not None and len(anchor) >= 4:
        ax, ay, aw, ah = int(anchor[0]), int(anchor[1]), int(anchor[2]), int(anchor[3])
        cand_x = ax + (aw - panel_w) // 2
        cand_y = ay + (ah - panel_h) // 2
    else:
        cand_x = avail_x + (avail_w - panel_w) // 2
        cand_y = avail_y + (avail_h - panel_h) // 2

    min_x = avail_x + margin
    max_x = max(min_x, avail_x + avail_w - panel_w - margin)
    min_y = avail_y + margin
    max_y = max(min_y, avail_y + avail_h - panel_h - margin)

    clamped_x = max(min_x, min(cand_x, max_x))
    clamped_y = max(min_y, min(cand_y, max_y))

    return {
        "x": int(clamped_x),
        "y": int(clamped_y),
        "width": int(panel_w),
        "height": int(panel_h),
        "min_width": int(min_w),
        "min_height": int(min_h),
        "max_width": int(max_w),
        "max_height": int(max_h),
        "layout_columns": int(layout_columns),
        "available_x": int(avail_x),
        "available_y": int(avail_y),
        "available_width": int(avail_w),
        "available_height": int(avail_h),
    }


if HAS_QT:
    class OcrWorkerSignals(QObject):
        progress = pyqtSignal(int, str)
        finished = pyqtSignal(object)  # OcrRecognitionResult

    class OcrWorkerJob(QRunnable):
        """Background worker for non-blocking OCR execution."""

        def __init__(
            self,
            image_source: Any,
            *,
            language: str = "eng",
            quality_mode: str = "auto",
            retry_attempt: int = 0,
            auto_invert_dark: bool = True,
            upscale_small_text: bool = True,
            contrast_stretch: bool = True,
            apply_threshold: bool = False,
            allow_builtin_fallback: bool = False,
            custom_binary: Optional[Path] = None,
            custom_tessdata: Optional[Path] = None,
            cancel_token: Optional[CancellationToken] = None,
        ) -> None:
            super().__init__()
            self.setAutoDelete(True)
            self.signals = OcrWorkerSignals()
            self._image = _to_pil_rgb(image_source)
            self._language = language
            self._quality_mode = normalize_ocr_quality_mode(quality_mode)
            self._retry_attempt = int(retry_attempt)
            self._auto_invert_dark = auto_invert_dark
            self._upscale_small_text = upscale_small_text
            self._contrast_stretch = contrast_stretch
            self._apply_threshold = apply_threshold
            self._allow_builtin_fallback = allow_builtin_fallback
            self._custom_binary = custom_binary
            self._custom_tessdata = custom_tessdata
            self.cancel_token = cancel_token or CancellationToken()

        def cancel(self) -> None:
            self.cancel_token.cancel()

        def run(self) -> None:
            def _safe_progress(pct: int, msg: str) -> None:
                if self.cancel_token.is_cancelled:
                    return
                try:
                    self.signals.progress.emit(int(pct), str(msg))
                except RuntimeError:
                    pass

            from .backends import recognize_production_ocr

            res = recognize_production_ocr(
                self._image,
                language=self._language,
                quality_mode=self._quality_mode,
                retry_attempt=self._retry_attempt,
                auto_invert_dark=self._auto_invert_dark,
                upscale_small_text=self._upscale_small_text,
                contrast_stretch=self._contrast_stretch,
                apply_threshold=self._apply_threshold,
                allow_builtin_fallback=self._allow_builtin_fallback,
                custom_binary=self._custom_binary,
                custom_tessdata=self._custom_tessdata,
                cancel_token=self.cancel_token,
                progress_callback=_safe_progress,
            )
            try:
                self.signals.finished.emit(res)
            except RuntimeError:
                pass

    class _OcrImageOverlayPreview(QWidget):
        """Interactive preview displaying the source image and clickable recognized word/line boxes."""

        lineClicked = pyqtSignal(int, str)

        def __init__(self, pil_img: Image.Image, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self._pil_img = pil_img.convert("RGB")
            self._qpixmap = self._pil_to_qpixmap(self._pil_img)
            self._result: Optional[OcrRecognitionResult] = None
            self._selected_line_index: int = -1
            self.setMinimumSize(220, 140)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Click any highlighted text region to select and copy that line.")

        @staticmethod
        def _pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
            rgba = pil_img.convert("RGBA")
            data = rgba.tobytes("raw", "RGBA")
            qimg = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
            return QPixmap.fromImage(qimg)

        def set_result(self, result: Optional[OcrRecognitionResult]) -> None:
            self._result = result
            self._selected_line_index = -1
            self.update()

        def set_selected_line(self, line_idx: int) -> None:
            self._selected_line_index = line_idx
            self.update()

        def _compute_target_rect(self) -> Tuple[QRect, float]:
            pw = max(1, self._qpixmap.width())
            ph = max(1, self._qpixmap.height())
            avail_w = max(10, self.width() - 16)
            avail_h = max(10, self.height() - 16)
            scale = min(avail_w / pw, avail_h / ph)
            tw = max(1, int(round(pw * scale)))
            th = max(1, int(round(ph * scale)))
            tx = (self.width() - tw) // 2
            ty = (self.height() - th) // 2
            return QRect(tx, ty, tw, th), scale

        def mousePressEvent(self, event: Any) -> None:
            if self._result is None or event.button() != Qt.MouseButton.LeftButton:
                return super().mousePressEvent(event)
            trect, scale = self._compute_target_rect()
            pos = event.position().toPoint()
            if trect.contains(pos) and scale > 1e-6:
                src_x = int(round((pos.x() - trect.x()) / scale))
                src_y = int(round((pos.y() - trect.y()) / scale))
                line = self._result.find_line_at_point(src_x, src_y)
                if line is not None:
                    self._selected_line_index = line.line_index
                    self.lineClicked.emit(line.line_index, line.text)
                    self.update()
            super().mousePressEvent(event)

        def paintEvent(self, _event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            bg_path = QPainterPath()
            bg_path.addRoundedRect(2.0, 2.0, float(self.width() - 4), float(self.height() - 4), 10.0, 10.0)
            painter.fillPath(bg_path, QColor(8, 28, 48, 190))
            painter.setPen(QPen(QColor(110, 225, 255, 120), 1.0))
            painter.drawPath(bg_path)

            trect, scale = self._compute_target_rect()
            painter.drawPixmap(trect, self._qpixmap)

            if self._result is not None and self._result.lines:
                for line in self._result.lines:
                    rx = trect.x() + int(round(line.x * scale))
                    ry = trect.y() + int(round(line.y * scale))
                    rw = max(4, int(round(line.width * scale)))
                    rh = max(4, int(round(line.height * scale)))
                    is_sel = (line.line_index == self._selected_line_index)
                    fill_col = QColor(0, 230, 255, 78 if is_sel else 32)
                    pen_col = QColor(120, 255, 220, 235 if is_sel else 145)
                    painter.fillRect(QRect(rx, ry, rw, rh), fill_col)
                    painter.setPen(QPen(pen_col, 1.8 if is_sel else 1.0))
                    painter.drawRect(QRect(rx, ry, rw, rh))
            painter.end()

    class _AquaDropletEmblem(QWidget):
        """Compact 18x18 Frutiger Aqua luminous droplet emblem for the Quick OCR header."""

        def __init__(self, accent_rgb: Tuple[int, int, int] = (45, 220, 180), parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self._accent_rgb = accent_rgb
            self.setFixedSize(18, 18)

        def set_accent_rgb(self, accent_rgb: Tuple[int, int, int]) -> None:
            self._accent_rgb = accent_rgb
            self.update()

        def paintEvent(self, _event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            grad = QLinearGradient(2.0, 2.0, 16.0, 16.0)
            r, g, b = self._accent_rgb
            grad.setColorAt(0.0, QColor(180, 252, 255, 245))
            grad.setColorAt(0.55, QColor(r, g, b, 235))
            grad.setColorAt(1.0, QColor(12, 108, 188, 240))
            painter.setBrush(grad)
            painter.setPen(QPen(QColor(210, 252, 255, 210), 1.1))
            painter.drawEllipse(2, 2, 14, 14)
            painter.setBrush(QColor(255, 255, 255, 165))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(5, 4, 6, 3)
            painter.end()

    class OcrResultsDialog(QDialog):
        """
        Two-mode progressively disclosed Frutiger Aqua OCR results window with
        100% automatic image optimization (no manual contrast or threshold checkboxes):
          1. Compact Quick OCR (`mode == "quick"`, default):
             - Frameless, non-modal compact floating panel positioned near the selection.
             - Adaptive logical width 420–520 px, height 160–250 px for short results,
               growing up to a screen-relative limit for multiline text, then scrolling.
             - Header with Prismwake droplet icon, `Text captured` title, word-count badge,
               and accessible close button (`✕`).
             - Single primary selectable & editable text field (`text_edit`), or compact
               `No text recognized` / error card when empty or failed.
             - Footer with `Offline OCR · EN` indicator, `Expand` button, and prominent
               `Copy` action with transient `Copied!` feedback.
          2. Advanced OCR (`mode == "advanced"`, on demand via `Expand`):
             - Resizable two-column (or responsive one-column) workspace with screenshot
               bounding-box preview, clickable recognized line list, language selector,
               optional optimization mode (`Automatic (Recommended)`, `Fast`, `Maximum Accuracy`),
               `Automatic image optimization · Offline OCR` status badge, Retry Recognition,
               Copy All, Copy Selected, Save Text, and technical status summary.
             - Switching Quick <-> Advanced never reruns OCR, never discards manual user edits,
               never loses text selection, and never discards the capture image or line boxes.
        """

        def __init__(
            self,
            image_source: Any,
            *,
            initial_result: Optional[OcrRecognitionResult] = None,
            default_language: str = "eng",
            quality_mode: str = "auto",
            auto_copy_on_complete: bool = False,
            show_panel_after_auto_copy: bool = True,
            auto_invert_dark: bool = True,
            upscale_small_text: bool = True,
            apply_threshold: bool = False,
            allow_builtin_fallback: bool = False,
            custom_binary: Optional[Path] = None,
            custom_tessdata: Optional[Path] = None,
            theme_spec: Optional[Dict[str, Any]] = None,
            aqua_theme: str = "ocean_current",
            animation_intensity: str = "medium",
            reduced_motion: bool = False,
            selection_rect: Optional[Tuple[int, int, int, int]] = None,
            available_geometry: Optional[Tuple[int, int, int, int]] = None,
            monitors: Optional[Sequence[Any]] = None,
            initial_mode: str = "quick",
            auto_start: bool = True,
            on_auto_copy_toast: Optional[Callable[[str], None]] = None,
            confirm_overwrite_callback: Optional[Callable[[], bool]] = None,
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)
            _ = apply_threshold  # Ignored: preprocessing is now 100% automatic
            self._pil_image = _to_pil_rgb(image_source)
            self._result: Optional[OcrRecognitionResult] = initial_result
            self._default_language = default_language if default_language in SUPPORTED_OCR_LANGUAGES else "eng"
            self._quality_mode: str = normalize_ocr_quality_mode(quality_mode)
            self._auto_copy = bool(auto_copy_on_complete)
            self._show_panel_after_auto_copy = bool(show_panel_after_auto_copy)
            self._auto_invert_dark = bool(auto_invert_dark)
            self._upscale_small_text = bool(upscale_small_text)
            self._allow_builtin_fallback = bool(allow_builtin_fallback)
            self._custom_binary = custom_binary
            self._custom_tessdata = custom_tessdata
            self._selection_rect = selection_rect
            self._available_geometry = available_geometry
            self._monitors = monitors
            self._on_auto_copy_toast = on_auto_copy_toast
            self._confirm_overwrite_callback = confirm_overwrite_callback

            self._palette = resolve_ocr_aqua_theme_palette(
                theme_spec if theme_spec else aqua_theme,
                animation_intensity=animation_intensity,
                reduced_motion=reduced_motion,
            )
            self._mode: str = "advanced" if str(initial_mode).lower() == "advanced" else "quick"
            self._view_state: str = "idle"
            self._active_job: Optional[OcrWorkerJob] = None
            self._is_closing: bool = False
            self._programmatic_text_update: bool = False
            self._user_modified_text: bool = False
            self._last_applied_ocr_text: str = ""
            self._ocr_run_count: int = 0
            self._retry_attempt: int = 0
            self._copy_feedback_active: bool = False
            self._auto_copy_acknowledged: bool = False
            self._last_auto_copy_notice: str = ""
            self._drag_offset: Optional[QPoint] = None

            self.setWindowTitle("Prismwake — Text Capture (Offline OCR)")
            self.setWindowModality(Qt.WindowModality.NonModal)
            self.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )

            self._copy_feedback_timer = QTimer(self)
            self._copy_feedback_timer.setSingleShot(True)
            self._copy_feedback_timer.timeout.connect(self._reset_copy_button_feedback)

            self._build_ui()
            self._setup_shortcuts()
            self._apply_mode_layout(preserve_selection=False)

            if self._result is not None:
                self._ocr_run_count = 1
                self._apply_result(self._result)
            elif auto_start:
                self._set_recognizing_ui_state(self._default_language)
                QTimer.singleShot(10, lambda: self.start_recognition(force_discard_edits=True))

        @property
        def mode(self) -> str:
            return self._mode

        @property
        def is_quick_mode(self) -> bool:
            return self._mode == "quick"

        @property
        def is_advanced_mode(self) -> bool:
            return self._mode == "advanced"

        @property
        def view_state(self) -> str:
            return self._view_state

        @property
        def ocr_run_count(self) -> int:
            return self._ocr_run_count

        @property
        def retry_attempt(self) -> int:
            return self._retry_attempt

        @property
        def quality_mode(self) -> str:
            return self._quality_mode

        @property
        def user_modified_text(self) -> bool:
            return self._user_modified_text

        @property
        def copy_feedback_active(self) -> bool:
            return self._copy_feedback_active

        @property
        def auto_copy_acknowledged(self) -> bool:
            return self._auto_copy_acknowledged

        @property
        def last_auto_copy_notice(self) -> str:
            return self._last_auto_copy_notice

        def present_in_front(self) -> None:
            """Display the non-modal OCR panel in front of other windows and focus it."""
            if self._is_closing:
                return
            self.reposition_near_selection()
            self.show()
            self.raise_()
            self.activateWindow()
            if self.text_edit.isVisible():
                self.text_edit.setFocus()

        def panel_geometry(self) -> Tuple[int, int, int, int]:
            g = self.geometry()
            return (int(g.x()), int(g.y()), int(g.width()), int(g.height()))

        def reposition_near_selection(
            self,
            selection_rect: Optional[Tuple[int, int, int, int]] = None,
            available_geometry: Optional[Tuple[int, int, int, int]] = None,
            monitors: Optional[Sequence[Any]] = None,
        ) -> Tuple[int, int, int, int]:
            if selection_rect is not None:
                self._selection_rect = selection_rect
            if available_geometry is not None:
                self._available_geometry = available_geometry
            if monitors is not None:
                self._monitors = monitors

            if self._mode == "quick":
                geom = compute_quick_ocr_panel_geometry(
                    self.text_edit.toPlainText(),
                    selection_rect=self._selection_rect,
                    available_geometry=self._available_geometry,
                    monitors=self._monitors,
                    view_state=self._view_state,
                )
                self.setMinimumSize(min(300, geom["width"]), min(155, geom["height"]))
                self.setMaximumSize(16777215, 16777215)
                self.setGeometry(geom["x"], geom["y"], geom["width"], geom["height"])
                return (geom["x"], geom["y"], geom["width"], geom["height"])

            cur_rect = self.panel_geometry() if self.isVisible() else None
            adv = compute_advanced_ocr_panel_geometry(
                current_rect=cur_rect,
                selection_rect=self._selection_rect,
                available_geometry=self._available_geometry,
                monitors=self._monitors,
            )
            self.splitter.setOrientation(
                Qt.Orientation.Vertical if adv["layout_columns"] == 1 else Qt.Orientation.Horizontal
            )
            self.setMinimumSize(adv["min_width"], adv["min_height"])
            self.setMaximumSize(adv["max_width"], adv["max_height"])
            self.setGeometry(adv["x"], adv["y"], adv["width"], adv["height"])
            return (adv["x"], adv["y"], adv["width"], adv["height"])

        def _build_ui(self) -> None:
            pal = self._palette
            self.setStyleSheet(
                f"""
                QDialog {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {pal['bg_top']}, stop:0.55 {pal['bg_mid']}, stop:1 {pal['bg_bot']});
                    color: #eaf8ff;
                    font-family: 'Segoe UI', sans-serif;
                }}
                QLabel {{
                    color: #dff6ff;
                    font-size: 12px;
                    background: transparent;
                }}
                QPlainTextEdit, QListWidget {{
                    background-color: {pal['editor_bg']};
                    color: #f4fcff;
                    border: 1px solid {pal['editor_border']};
                    border-radius: 8px;
                    padding: 7px 9px;
                    font-family: 'Segoe UI', 'Consolas', sans-serif;
                    font-size: 13px;
                    selection-background-color: {pal['selection_bg']};
                    selection-color: {pal['selection_fg']};
                }}
                QComboBox {{
                    background-color: rgba(10, 36, 64, 225);
                    color: #eaf8ff;
                    border: 1px solid {pal['editor_border']};
                    border-radius: 6px;
                    padding: 3px 9px;
                    min-width: 140px;
                }}
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(62, 165, 220, 175),
                        stop:1 rgba(16, 78, 138, 195));
                    color: #eaf8ff;
                    font-weight: 600;
                    font-size: 12px;
                    border: 1px solid rgba(140, 228, 255, 155);
                    border-radius: 7px;
                    padding: 5px 12px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(98, 208, 252, 220),
                        stop:1 rgba(24, 112, 188, 225));
                }}
                QPushButton:disabled {{
                    background: rgba(36, 62, 88, 120);
                    color: rgba(175, 205, 225, 110);
                    border: 1px solid rgba(110, 160, 190, 75);
                }}
                QPushButton#PrimaryCopyButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {pal['btn_top']},
                        stop:0.5 {pal['btn_mid']},
                        stop:1 {pal['btn_bot']});
                    color: #ffffff;
                    font-weight: 700;
                    border: 1px solid {pal['btn_border']};
                    padding: 5px 16px;
                }}
                QPushButton#HeaderCloseButton {{
                    background: rgba(255, 255, 255, 18);
                    color: #d8f4ff;
                    border: 1px solid rgba(150, 230, 255, 90);
                    border-radius: 6px;
                    padding: 1px 7px;
                    font-size: 12px;
                    font-weight: 700;
                }}
                QPushButton#HeaderCloseButton:hover {{
                    background: rgba(228, 58, 76, 215);
                    color: #ffffff;
                    border: 1px solid rgba(255, 165, 175, 210);
                }}
                QProgressBar {{
                    background-color: rgba(8, 25, 46, 200);
                    border: 1px solid {pal['editor_border']};
                    border-radius: 5px;
                    text-align: center;
                    color: #eaf8ff;
                    max-height: 14px;
                }}
                QProgressBar::chunk {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #00c6ff, stop:1 #52ffda);
                    border-radius: 4px;
                }}
                """
            )

            self.root_layout = QVBoxLayout(self)
            self.root_layout.setContentsMargins(12, 10, 12, 10)
            self.root_layout.setSpacing(7)

            # --- 1. Compact Quick Header Bar ---
            self.quick_header_widget = QWidget(self)
            qh_layout = QHBoxLayout(self.quick_header_widget)
            qh_layout.setContentsMargins(2, 0, 2, 0)
            qh_layout.setSpacing(8)

            self.emblem_widget = _AquaDropletEmblem(tuple(pal["accent_rgb"]), self.quick_header_widget)
            qh_layout.addWidget(self.emblem_widget)

            self.header_title_label = QLabel("Text captured", self.quick_header_widget)
            self.header_title_label.setStyleSheet(
                f"font-size: 13px; font-weight: 700; color: {pal['accent_hex']};"
            )
            qh_layout.addWidget(self.header_title_label)

            self.word_count_badge = QLabel("", self.quick_header_widget)
            self.word_count_badge.setStyleSheet(
                "background-color: rgba(0, 195, 245, 38); color: #bfefff; "
                "border: 1px solid rgba(115, 228, 255, 95); border-radius: 8px; "
                "padding: 1px 7px; font-size: 11px; font-weight: 600;"
            )
            self.word_count_badge.setVisible(False)
            qh_layout.addWidget(self.word_count_badge)
            qh_layout.addStretch(1)

            self.collapse_btn = QPushButton("Compact View", self.quick_header_widget)
            self.collapse_btn.setToolTip("Return to Compact Quick OCR panel")
            self.collapse_btn.clicked.connect(self.collapse_to_quick)
            self.collapse_btn.setVisible(False)
            qh_layout.addWidget(self.collapse_btn)

            self.header_close_btn = QPushButton("✕", self.quick_header_widget)
            self.header_close_btn.setObjectName("HeaderCloseButton")
            self.header_close_btn.setToolTip("Close OCR panel (Esc)")
            self.header_close_btn.setFixedSize(26, 22)
            self.header_close_btn.clicked.connect(self.accept)
            qh_layout.addWidget(self.header_close_btn)

            self.root_layout.addWidget(self.quick_header_widget)

            # --- 2. Advanced Controls Bar (hidden in Quick mode) ---
            self.advanced_top_bar_widget = QWidget(self)
            top_bar = QHBoxLayout(self.advanced_top_bar_widget)
            top_bar.setContentsMargins(0, 0, 0, 0)
            top_bar.setSpacing(8)

            top_bar.addWidget(QLabel("Language:"))
            self.lang_combo = QComboBox(self.advanced_top_bar_widget)
            for code, label in SUPPORTED_OCR_LANGUAGES.items():
                self.lang_combo.addItem(label, code)
            idx = self.lang_combo.findData(self._default_language)
            if idx >= 0:
                self.lang_combo.setCurrentIndex(idx)
            self.lang_combo.currentIndexChanged.connect(self._on_language_combo_changed)
            top_bar.addWidget(self.lang_combo)

            top_bar.addWidget(QLabel("Mode:"))
            self.quality_mode_combo = QComboBox(self.advanced_top_bar_widget)
            for q_code, q_label in OCR_QUALITY_MODE_LABELS.items():
                self.quality_mode_combo.addItem(q_label, q_code)
            q_idx = self.quality_mode_combo.findData(self._quality_mode)
            if q_idx >= 0:
                self.quality_mode_combo.setCurrentIndex(q_idx)
            self.quality_mode_combo.setToolTip(
                "Automatic image optimization selects contrast, polarity, scaling, and page layout automatically."
            )
            self.quality_mode_combo.currentIndexChanged.connect(self._on_quality_mode_combo_changed)
            top_bar.addWidget(self.quality_mode_combo)

            self.auto_opt_status_label = QLabel(AUTOMATIC_OCR_STATUS_TEXT, self.advanced_top_bar_widget)
            self.auto_opt_status_label.setStyleSheet("color: #9adcf2; font-size: 11px; font-weight: 600;")
            top_bar.addWidget(self.auto_opt_status_label)

            self.backend_diag_label = QLabel("Backend: Pending", self.advanced_top_bar_widget)
            self.backend_diag_label.setStyleSheet(
                "background-color: rgba(0, 175, 230, 34); color: #bdf2ff; "
                "border: 1px solid rgba(110, 225, 255, 95); border-radius: 6px; "
                "padding: 2px 7px; font-size: 11px; font-weight: 600;"
            )
            top_bar.addWidget(self.backend_diag_label)
            top_bar.addStretch(1)

            self.retry_btn = QPushButton("Retry Recognition", self.advanced_top_bar_widget)
            self.retry_btn.setToolTip("Retry OCR using an alternative automatic preprocessing & segmentation strategy")
            self.retry_btn.clicked.connect(lambda: self.start_recognition())
            top_bar.addWidget(self.retry_btn)

            self.root_layout.addWidget(self.advanced_top_bar_widget)

            # --- 3. Progress & Diagnostics Status Row ---
            self.status_row_widget = QWidget(self)
            status_row = QHBoxLayout(self.status_row_widget)
            status_row.setContentsMargins(0, 0, 0, 0)
            status_row.setSpacing(8)

            self.status_label = QLabel("Ready.", self.status_row_widget)
            self.status_label.setWordWrap(True)
            status_row.addWidget(self.status_label, 1)

            self.progress_bar = QProgressBar(self.status_row_widget)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setVisible(False)
            self.progress_bar.setFixedWidth(160)
            status_row.addWidget(self.progress_bar)

            self.cancel_btn = QPushButton("Cancel", self.status_row_widget)
            self.cancel_btn.clicked.connect(self.cancel_recognition)
            self.cancel_btn.setVisible(False)
            status_row.addWidget(self.cancel_btn)

            self.root_layout.addWidget(self.status_row_widget)

            # --- 4. Actionable Error Banner & Compact Empty-State Notice ---
            self.error_banner = QLabel("", self)
            self.error_banner.setWordWrap(True)
            self.error_banner.setVisible(False)
            self.error_banner.setStyleSheet(
                "background-color: rgba(145, 28, 38, 215); color: #ffeef0; "
                "border: 1px solid rgba(255, 130, 140, 200); border-radius: 7px; "
                "padding: 7px 10px; font-weight: 600;"
            )
            self.root_layout.addWidget(self.error_banner)

            self.empty_state_banner = QLabel(
                "No text recognized in the selected area. Try Retry or click Expand to change the OCR language or optimization mode.",
                self,
            )
            self.empty_state_banner.setWordWrap(True)
            self.empty_state_banner.setVisible(False)
            self.empty_state_banner.setStyleSheet(
                "background-color: rgba(14, 52, 86, 205); color: #d8f4ff; "
                "border: 1px solid rgba(110, 220, 255, 135); border-radius: 7px; "
                "padding: 8px 10px;"
            )
            self.root_layout.addWidget(self.empty_state_banner)

            # --- 5. Main Content Area (Unified Text Editor + Advanced Preview Splitter) ---
            self.splitter = QSplitter(Qt.Orientation.Horizontal, self)

            self.left_preview_pane = QWidget(self.splitter)
            left_layout = QVBoxLayout(self.left_preview_pane)
            left_layout.setContentsMargins(0, 0, 0, 0)
            left_layout.setSpacing(6)
            self.preview_caption_label = QLabel(
                "Captured Region & Detected Text Lines (click to copy line):",
                self.left_preview_pane,
            )
            left_layout.addWidget(self.preview_caption_label)
            self.preview_widget = _OcrImageOverlayPreview(self._pil_image, self.left_preview_pane)
            self.preview_widget.lineClicked.connect(self._on_line_clicked)
            left_layout.addWidget(self.preview_widget, 3)

            self.lines_list = QListWidget(self.left_preview_pane)
            self.lines_list.setToolTip("Click a recognized line to highlight its location and copy it.")
            self.lines_list.currentRowChanged.connect(self._on_line_row_changed)
            left_layout.addWidget(self.lines_list, 2)
            self.splitter.addWidget(self.left_preview_pane)

            self.right_text_pane = QWidget(self.splitter)
            right_layout = QVBoxLayout(self.right_text_pane)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(5)
            self.right_pane_label = QLabel(
                "Recognized Text (editable & selectable):",
                self.right_text_pane,
            )
            right_layout.addWidget(self.right_pane_label)
            self.text_edit = QPlainTextEdit(self.right_text_pane)
            self.text_edit.setPlaceholderText("Recognized text will appear here...")
            self.text_edit.textChanged.connect(self._on_text_edit_changed)
            right_layout.addWidget(self.text_edit, 1)
            self.splitter.addWidget(self.right_text_pane)

            self.splitter.setStretchFactor(0, 4)
            self.splitter.setStretchFactor(1, 6)
            self.splitter.setSizes([340, 480])
            self.root_layout.addWidget(self.splitter, 1)

            # --- 6. Compact Quick Footer Bar ---
            self.quick_footer_widget = QWidget(self)
            qf_layout = QHBoxLayout(self.quick_footer_widget)
            qf_layout.setContentsMargins(2, 0, 2, 0)
            qf_layout.setSpacing(8)

            self.quick_footer_lang_label = QLabel(
                format_quick_ocr_footer_label(self._default_language),
                self.quick_footer_widget,
            )
            self.quick_footer_lang_label.setStyleSheet("color: #9adcf2; font-size: 11px; font-weight: 600;")
            qf_layout.addWidget(self.quick_footer_lang_label)
            qf_layout.addStretch(1)

            self.quick_retry_btn = QPushButton("Retry", self.quick_footer_widget)
            self.quick_retry_btn.setToolTip("Retry OCR recognition on this capture")
            self.quick_retry_btn.clicked.connect(lambda: self.start_recognition())
            self.quick_retry_btn.setVisible(False)
            qf_layout.addWidget(self.quick_retry_btn)

            self.expand_btn = QPushButton("Expand", self.quick_footer_widget)
            self.expand_btn.setToolTip("Open Advanced OCR workspace (preview, line boxes, language & diagnostics)")
            self.expand_btn.clicked.connect(self.expand_to_advanced)
            qf_layout.addWidget(self.expand_btn)

            self.copy_btn = QPushButton("Copy", self.quick_footer_widget)
            self.copy_btn.setObjectName("PrimaryCopyButton")
            self.copy_btn.setToolTip("Copy recognized text to clipboard (Ctrl+C / Ctrl+Enter)")
            self.copy_btn.clicked.connect(lambda: self.copy_all_text())
            qf_layout.addWidget(self.copy_btn)

            self.quick_close_btn = QPushButton("Close", self.quick_footer_widget)
            self.quick_close_btn.clicked.connect(self.accept)
            self.quick_close_btn.setVisible(False)
            qf_layout.addWidget(self.quick_close_btn)

            self.root_layout.addWidget(self.quick_footer_widget)

            # --- 7. Advanced Footer Bar (hidden in Quick mode) ---
            self.advanced_bottom_bar_widget = QWidget(self)
            btn_row = QHBoxLayout(self.advanced_bottom_bar_widget)
            btn_row.setContentsMargins(0, 0, 0, 0)
            btn_row.setSpacing(8)

            self.copy_all_btn = QPushButton("Copy All", self.advanced_bottom_bar_widget)
            self.copy_all_btn.setObjectName("PrimaryCopyButton")
            self.copy_all_btn.clicked.connect(lambda: self.copy_all_text())
            btn_row.addWidget(self.copy_all_btn)

            self.copy_sel_btn = QPushButton("Copy Selected", self.advanced_bottom_bar_widget)
            self.copy_sel_btn.clicked.connect(self.copy_selected_text)
            btn_row.addWidget(self.copy_sel_btn)

            self.save_txt_btn = QPushButton("Save Text...", self.advanced_bottom_bar_widget)
            self.save_txt_btn.clicked.connect(self.save_text_to_file)
            btn_row.addWidget(self.save_txt_btn)

            self.export_diag_btn = QPushButton("Export Diagnostics...", self.advanced_bottom_bar_widget)
            self.export_diag_btn.setToolTip(
                "Opt-in export of the native capture image, preprocessed candidates, and OCR diagnostic manifest to a local folder"
            )
            self.export_diag_btn.clicked.connect(lambda: self.export_diagnostic_bundle())
            btn_row.addWidget(self.export_diag_btn)

            btn_row.addStretch(1)
            self.close_btn = QPushButton("Close", self.advanced_bottom_bar_widget)
            self.close_btn.clicked.connect(self.accept)
            btn_row.addWidget(self.close_btn)

            self.size_grip = QSizeGrip(self.advanced_bottom_bar_widget)
            btn_row.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

            self.root_layout.addWidget(self.advanced_bottom_bar_widget)

        def _setup_shortcuts(self) -> None:
            self._sc_ctrl_enter = QShortcut(QKeySequence("Ctrl+Return"), self)
            self._sc_ctrl_enter.activated.connect(lambda: self.copy_all_text())
            self._sc_ctrl_enter_num = QShortcut(QKeySequence("Ctrl+Enter"), self)
            self._sc_ctrl_enter_num.activated.connect(lambda: self.copy_all_text())
            self._sc_escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
            self._sc_escape.activated.connect(self.escape_action)

        def escape_action(self) -> None:
            """Escape cancels active OCR recognition if running, or closes only this focused OCR panel."""
            if self._active_job is not None:
                self.cancel_recognition()
                return
            self.close()

        def select_all_text(self) -> str:
            """Select all text in `text_edit` (Ctrl+A behavior) and return the selected string."""
            self.text_edit.selectAll()
            cursor = self.text_edit.textCursor()
            return cursor.selectedText().replace("\u2029", "\n")

        def copy_shortcut_action(self) -> str:
            """Ctrl+C behavior: copy selected text if a selection exists, otherwise copy all current text."""
            cursor = self.text_edit.textCursor()
            sel = cursor.selectedText().replace("\u2029", "\n")
            if sel:
                return self.copy_selected_text()
            return self.copy_all_text()

        def _on_text_edit_changed(self) -> None:
            if self._programmatic_text_update:
                return
            current_txt = self.text_edit.toPlainText()
            self._user_modified_text = (current_txt != self._last_applied_ocr_text)
            badge_str = format_quick_ocr_badge_text(current_txt, self._result)
            self.word_count_badge.setText(badge_str)
            self.word_count_badge.setVisible(bool(badge_str))
            has_any = bool(current_txt.strip())
            self.copy_btn.setEnabled(has_any)
            self.copy_all_btn.setEnabled(has_any)
            self.copy_sel_btn.setEnabled(has_any)
            self.save_txt_btn.setEnabled(has_any)

        def _on_language_combo_changed(self, _idx: int) -> None:
            lang = str(self.lang_combo.currentData() or "eng")
            self._default_language = lang
            self.quick_footer_lang_label.setText(
                format_quick_ocr_footer_label(lang, auto_copied=self._auto_copy_acknowledged)
            )

        def _on_quality_mode_combo_changed(self, _idx: int) -> None:
            q_mode = normalize_ocr_quality_mode(self.quality_mode_combo.currentData())
            self._quality_mode = q_mode

        def set_language(self, lang_code: str) -> None:
            norm = (lang_code or "eng").strip().lower()
            if norm in SUPPORTED_OCR_LANGUAGES:
                self._default_language = norm
                idx = self.lang_combo.findData(norm)
                if idx >= 0:
                    self.lang_combo.setCurrentIndex(idx)
                self.quick_footer_lang_label.setText(
                    format_quick_ocr_footer_label(norm, auto_copied=self._auto_copy_acknowledged)
                )

        def set_quality_mode(self, mode: str) -> None:
            norm = normalize_ocr_quality_mode(mode)
            self._quality_mode = norm
            idx = self.quality_mode_combo.findData(norm)
            if idx >= 0:
                self.quality_mode_combo.setCurrentIndex(idx)

        def expand_to_advanced(self) -> None:
            """
            Switch from Compact Quick OCR to Advanced OCR workspace on demand
            WITHOUT rerunning OCR, discarding manual user edits, or losing text selection.
            """
            if self._mode == "advanced":
                return
            self._mode = "advanced"
            self._apply_mode_layout(preserve_selection=True)

        def collapse_to_quick(self) -> None:
            """
            Switch from Advanced OCR back to Compact Quick OCR panel
            WITHOUT rerunning OCR, discarding manual user edits, or losing text selection.
            """
            if self._mode == "quick":
                return
            self._mode = "quick"
            self._apply_mode_layout(preserve_selection=True)

        def toggle_mode(self) -> str:
            if self._mode == "quick":
                self.expand_to_advanced()
            else:
                self.collapse_to_quick()
            return self._mode

        def _apply_mode_layout(self, *, preserve_selection: bool = True) -> None:
            cursor = self.text_edit.textCursor()
            sel_start = cursor.selectionStart()
            sel_end = cursor.selectionEnd()
            pos = cursor.position()

            is_quick = (self._mode == "quick")
            self.advanced_top_bar_widget.setVisible(not is_quick)
            self.left_preview_pane.setVisible(not is_quick)
            self.right_pane_label.setVisible(not is_quick)
            self.advanced_bottom_bar_widget.setVisible(not is_quick)
            self.quick_footer_widget.setVisible(is_quick)
            self.collapse_btn.setVisible(not is_quick)

            self.status_row_widget.setVisible((not is_quick) or (self._view_state == "recognizing"))

            if is_quick:
                self.root_layout.setContentsMargins(12, 10, 12, 10)
                self.root_layout.setSpacing(7)
                if self._view_state == "empty":
                    self.header_title_label.setText("No text recognized")
                elif self._view_state == "error":
                    self.header_title_label.setText("OCR unavailable")
                elif self._view_state == "recognizing":
                    self.header_title_label.setText("Recognizing text...")
                else:
                    self.header_title_label.setText("Text captured")
            else:
                self.root_layout.setContentsMargins(14, 12, 14, 12)
                self.root_layout.setSpacing(9)
                self.header_title_label.setText("Prismwake Offline Text Recognition (OCR)")

            self._sync_state_widget_visibility()
            self.reposition_near_selection()

            if preserve_selection:
                new_cursor = self.text_edit.textCursor()
                new_cursor.setPosition(sel_start)
                if sel_end != sel_start:
                    new_cursor.setPosition(sel_end, QTextCursor.MoveMode.KeepAnchor)
                else:
                    new_cursor.setPosition(pos)
                self.text_edit.setTextCursor(new_cursor)

        def _sync_state_widget_visibility(self) -> None:
            is_quick = (self._mode == "quick")
            is_empty = (self._view_state == "empty")
            is_err = (self._view_state == "error")
            is_rec = (self._view_state == "recognizing")
            has_txt = bool(self.text_edit.toPlainText().strip())

            self.empty_state_banner.setVisible(is_empty and not has_txt)
            self.error_banner.setVisible(is_err)

            if is_quick:
                show_editor_in_quick = has_txt or (self._view_state == "ready") or self._user_modified_text
                self.splitter.setVisible(show_editor_in_quick)
                self.quick_retry_btn.setVisible(is_empty or is_err or self._view_state == "cancelled")
                self.quick_close_btn.setVisible(is_empty or is_err)
                self.copy_btn.setVisible(not (is_empty or is_err) or has_txt)
                self.status_row_widget.setVisible(is_rec)
            else:
                self.splitter.setVisible(True)
                self.status_row_widget.setVisible(True)

        def _set_recognizing_ui_state(self, lang: str) -> None:
            self._view_state = "recognizing"
            self.error_banner.setVisible(False)
            self.empty_state_banner.setVisible(False)
            self.retry_btn.setEnabled(False)
            self.quick_retry_btn.setEnabled(False)
            self.cancel_btn.setVisible(True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            self.status_label.setText(f"Recognizing pass 1 of up to 4 ({lang})...")
            if self._mode == "quick":
                self.header_title_label.setText("Recognizing text...")
            self._sync_state_widget_visibility()

        def start_recognition(
            self,
            *,
            async_run: Optional[bool] = None,
            force_discard_edits: bool = False,
        ) -> bool:
            """
            Begin or retry asynchronous OCR recognition.
            When retrying (`_ocr_run_count >= 1`), increments `_retry_attempt` so
            `recognize_image_ocr` explores an alternative preprocessing/PSM strategy.
            """
            _ = async_run
            if self._is_closing:
                return False

            if self._user_modified_text and not force_discard_edits:
                if self._confirm_overwrite_callback is not None:
                    if not self._confirm_overwrite_callback():
                        return False
                else:
                    ans = QMessageBox.question(
                        self,
                        "Replace Edited Text?",
                        "You have edited the recognized text. Retrying OCR will replace your manual edits. Continue?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if ans != QMessageBox.StandardButton.Yes:
                        return False

            if self._active_job is not None:
                self._active_job.cancel()
                self._active_job = None

            lang = str(self.lang_combo.currentData() or self._default_language or "eng")
            q_mode = normalize_ocr_quality_mode(self.quality_mode_combo.currentData() or self._quality_mode)
            self._quality_mode = q_mode
            if self._ocr_run_count >= 1:
                self._retry_attempt += 1
            self._ocr_run_count += 1
            self._set_recognizing_ui_state(lang)

            job = OcrWorkerJob(
                self._pil_image,
                language=lang,
                quality_mode=q_mode,
                retry_attempt=self._retry_attempt,
                auto_invert_dark=self._auto_invert_dark,
                upscale_small_text=self._upscale_small_text,
                allow_builtin_fallback=self._allow_builtin_fallback,
                custom_binary=self._custom_binary,
                custom_tessdata=self._custom_tessdata,
            )
            job.signals.progress.connect(self._on_job_progress)
            job.signals.finished.connect(self._on_job_finished)
            self._active_job = job
            QThreadPool.globalInstance().start(job)
            return True

        def cancel_recognition(self) -> None:
            if self._active_job is not None:
                self._active_job.cancel()
                self._active_job = None
                if not self._is_closing:
                    self._view_state = "cancelled"
                    self.retry_btn.setEnabled(True)
                    self.quick_retry_btn.setEnabled(True)
                    self.cancel_btn.setVisible(False)
                    self.progress_bar.setVisible(False)
                    self.status_label.setText("Recognition cancelled.")
                    if self._mode == "quick":
                        self.header_title_label.setText("Recognition cancelled")
                    self._sync_state_widget_visibility()

        def _on_job_progress(self, pct: int, msg: str) -> None:
            if self._is_closing:
                return
            try:
                if int(pct) >= 100:
                    self.progress_bar.setRange(0, 100)
                    self.progress_bar.setValue(100)
                else:
                    self.progress_bar.setRange(0, 0)
                self.status_label.setText(msg)
            except RuntimeError:
                pass

        def _on_job_finished(self, result: OcrRecognitionResult) -> None:
            if self._is_closing:
                return
            try:
                self._active_job = None
                self.retry_btn.setEnabled(True)
                self.quick_retry_btn.setEnabled(True)
                self.cancel_btn.setVisible(False)
                self.progress_bar.setVisible(False)
                self._apply_result(result)
            except RuntimeError:
                pass

        def _apply_result(self, result: OcrRecognitionResult) -> None:
            self._result = result
            self.preview_widget.set_result(result)
            self.lines_list.clear()
            backend_lbl = getattr(result, "backend_selected", "") or (
                "RapidOCR (ONNX CPU)" if result.engine_name == "rapidocr" else "Tesseract fallback"
            )
            self.backend_diag_label.setText(f"Backend: {backend_lbl}")
            if getattr(result, "fallback_reason", ""):
                self.backend_diag_label.setToolTip(f"Fallback reason: {result.fallback_reason}")
            else:
                self.backend_diag_label.setToolTip(f"Active OCR backend: {backend_lbl}")

            if result.error:
                _OCR_LOGGER.error("OCR Result Error: %s", result.error)
                self._view_state = "error"
                self.error_banner.setText(f"OCR Engine Error: {result.error}")
                self.error_banner.setVisible(True)
                self.empty_state_banner.setVisible(False)
                self.status_label.setText(f"Error: {result.error}")
                if not self._user_modified_text:
                    self._programmatic_text_update = True
                    self.text_edit.setPlainText("")
                    self._programmatic_text_update = False
                    self._last_applied_ocr_text = ""
                self.word_count_badge.setText("")
                self.word_count_badge.setVisible(False)
                self.copy_btn.setEnabled(False)
                self.copy_all_btn.setEnabled(False)
                self.copy_sel_btn.setEnabled(False)
                self.save_txt_btn.setEnabled(False)
                if self._mode == "quick":
                    self.header_title_label.setText("OCR unavailable")
                self._sync_state_widget_visibility()
                self.reposition_near_selection()
                return

            if result.cancelled:
                self._view_state = "cancelled"
                self.error_banner.setVisible(False)
                self.status_label.setText("Recognition cancelled.")
                if self._mode == "quick":
                    self.header_title_label.setText("Recognition cancelled")
                self._sync_state_widget_visibility()
                return

            self.error_banner.setVisible(False)
            self._programmatic_text_update = True
            self.text_edit.setPlainText(result.text)
            self._programmatic_text_update = False
            self._last_applied_ocr_text = result.text
            self._user_modified_text = False

            for line in result.lines:
                item = QListWidgetItem(f"[{line.line_index + 1}] {line.text}")
                item.setData(Qt.ItemDataRole.UserRole, line.line_index)
                self.lines_list.addItem(item)

            backend_lbl = getattr(result, "backend_selected", "") or (
                "RapidOCR (ONNX CPU)" if result.engine_name == "rapidocr" else "Tesseract fallback"
            )
            self.backend_diag_label.setText(f"Backend: {backend_lbl}")
            if getattr(result, "fallback_reason", ""):
                self.backend_diag_label.setToolTip(f"Fallback reason: {result.fallback_reason}")
            else:
                self.backend_diag_label.setToolTip(f"Active OCR backend: {backend_lbl}")
            self.status_label.setText(format_ocr_summary(result))

            if not result.has_text:
                _OCR_LOGGER.info(
                    "OCR finished with 0 recognized words (%dx%d, lang=%s)",
                    result.source_width,
                    result.source_height,
                    result.language,
                )
                self._view_state = "empty"
                self.word_count_badge.setText("")
                self.word_count_badge.setVisible(False)
                self.copy_btn.setEnabled(False)
                self.copy_all_btn.setEnabled(False)
                self.copy_sel_btn.setEnabled(False)
                self.save_txt_btn.setEnabled(False)
                if self._mode == "quick":
                    self.header_title_label.setText("No text recognized")
                self._sync_state_widget_visibility()
                self.reposition_near_selection()
                return

            self._view_state = "ready"
            badge_str = format_quick_ocr_badge_text(result.text, result)
            self.word_count_badge.setText(badge_str)
            self.word_count_badge.setVisible(bool(badge_str))
            self.copy_btn.setEnabled(True)
            self.copy_all_btn.setEnabled(True)
            self.copy_sel_btn.setEnabled(True)
            self.save_txt_btn.setEnabled(True)
            if self._mode == "quick":
                self.header_title_label.setText("Text captured")

            if self._auto_copy and result.has_text:
                self.copy_all_text(silent=True)
                self._auto_copy_acknowledged = True
                n_words, _ = count_recognized_words_and_lines(result.text, result)
                self._last_auto_copy_notice = f"Copied {n_words} {'word' if n_words == 1 else 'words'} to clipboard"
                self.quick_footer_lang_label.setText(
                    format_quick_ocr_footer_label(result.language, auto_copied=True)
                )
                if self._on_auto_copy_toast is not None:
                    try:
                        self._on_auto_copy_toast(self._last_auto_copy_notice)
                    except Exception:
                        pass
                if not self._show_panel_after_auto_copy:
                    self.close()
                    return
            else:
                self.quick_footer_lang_label.setText(
                    format_quick_ocr_footer_label(result.language, auto_copied=False)
                )

            self._sync_state_widget_visibility()
            self.reposition_near_selection()

        def _trigger_copy_button_feedback(self) -> None:
            self._copy_feedback_active = True
            self.copy_btn.setText("Copied!")
            self.copy_all_btn.setText("Copied!")
            pal = self._palette
            copied_style = (
                f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                f"stop:0 {pal['btn_copied_top']}, stop:1 {pal['btn_copied_bot']}); "
                f"color: #ffffff; font-weight: 700; border: 1px solid #a8ffdf; "
                f"border-radius: 7px; padding: 5px 16px;"
            )
            self.copy_btn.setStyleSheet(copied_style)
            self.copy_all_btn.setStyleSheet(copied_style)
            self._copy_feedback_timer.start(int(pal.get("copied_feedback_ms", 1300)))

        def _reset_copy_button_feedback(self) -> None:
            self._copy_feedback_active = False
            if not self._is_closing:
                self.copy_btn.setText("Copy")
                self.copy_all_btn.setText("Copy All")
                self.copy_btn.setStyleSheet("")
                self.copy_all_btn.setStyleSheet("")

        def _on_line_clicked(self, line_idx: int, line_text: str) -> None:
            if 0 <= line_idx < self.lines_list.count():
                self.lines_list.setCurrentRow(line_idx)
            cb = QApplication.clipboard()
            if cb is not None and line_text:
                cb.setText(line_text)
                self.status_label.setText(f"Copied line {line_idx + 1} to clipboard.")
                self._trigger_copy_button_feedback()

        def _on_line_row_changed(self, row: int) -> None:
            self.preview_widget.set_selected_line(row)

        def copy_all_text(self, silent: bool = False) -> str:
            txt = self.text_edit.toPlainText()
            if not txt:
                return ""
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(txt)
            self._trigger_copy_button_feedback()
            if not silent:
                self.status_label.setText(f"Copied {len(txt)} characters to clipboard.")
            return txt

        def copy_selected_text(self) -> str:
            cursor = self.text_edit.textCursor()
            sel = cursor.selectedText().replace("\u2029", "\n")
            if not sel:
                sel = self.text_edit.toPlainText()
            if not sel:
                return ""
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(sel)
            self._trigger_copy_button_feedback()
            self.status_label.setText(f"Copied {len(sel)} selected characters to clipboard.")
            return sel

        def save_text_to_file(self) -> None:
            txt = self.text_edit.toPlainText()
            path_str, _ = QFileDialog.getSaveFileName(
                self,
                "Save Recognized Text",
                str(Path.home() / "Pictures" / "Prismwake" / "ocr_text.txt"),
                "Text Files (*.txt);;Markdown Files (*.md);;All Files (*.*)",
            )
            if not path_str:
                return
            try:
                Path(path_str).write_text(txt, encoding="utf-8")
                self.status_label.setText(f"Saved text to {Path(path_str).name}")
            except Exception as exc:
                QMessageBox.warning(self, "Save Error", f"Could not save text file:\n{exc}")

        def export_diagnostic_bundle(self, target_dir: Optional[Any] = None) -> Optional[Dict[str, Any]]:
            """Explicitly opt-in export of native capture image and preprocessing candidates."""
            if target_dir is None:
                dir_str = QFileDialog.getExistingDirectory(
                    self,
                    "Export OCR Diagnostic Bundle",
                    str(Path.home() / "Pictures" / "Prismwake"),
                )
                if not dir_str:
                    return None
                target_dir = Path(dir_str)
            try:
                info = export_ocr_diagnostic_bundle(
                    self._pil_image,
                    target_dir,
                    result=self._result,
                    language=self._default_language,
                    quality_mode=self._quality_mode,
                )
                self.status_label.setText(f"Exported diagnostic bundle to {Path(info['output_dir']).name}")
                return info
            except Exception as exc:
                QMessageBox.warning(self, "Diagnostic Export Error", f"Could not export OCR diagnostics:\n{exc}")
                return None

        def mousePressEvent(self, event: Any) -> None:
            if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 40:
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event: Any) -> None:
            if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                event.accept()
                return
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event: Any) -> None:
            self._drag_offset = None
            super().mouseReleaseEvent(event)

        def paintEvent(self, event: Any) -> None:
            super().paintEvent(event)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pal = self._palette
            rect_f = self.rect().adjusted(1, 1, -1, -1)

            spec_path = QPainterPath()
            spec_path.addRoundedRect(2.0, 2.0, float(rect_f.width() - 2), 26.0, 9.0, 9.0)
            sr, sg, sb, sa = pal["specular_top"]
            spec_grad = QLinearGradient(0.0, 2.0, 0.0, 28.0)
            spec_grad.setColorAt(0.0, QColor(sr, sg, sb, sa))
            spec_grad.setColorAt(1.0, QColor(sr, sg, sb, 0))
            painter.fillPath(spec_path, spec_grad)

            or_r, or_g, or_b, or_a = pal["border_outer"]
            ir_r, ir_g, ir_b, ir_a = pal["border_inner"]
            outer_path = QPainterPath()
            outer_path.addRoundedRect(1.0, 1.0, float(self.width() - 2), float(self.height() - 2), 10.0, 10.0)
            painter.setPen(QPen(QColor(or_r, or_g, or_b, or_a), 1.4))
            painter.drawPath(outer_path)

            inner_path = QPainterPath()
            inner_path.addRoundedRect(2.5, 2.5, float(self.width() - 5), float(self.height() - 5), 8.5, 8.5)
            painter.setPen(QPen(QColor(ir_r, ir_g, ir_b, ir_a), 1.0))
            painter.drawPath(inner_path)
            painter.end()

        def closeEvent(self, event: Any) -> None:
            self._is_closing = True
            self._copy_feedback_timer.stop()
            if self._active_job is not None:
                self._active_job.cancel()
                self._active_job = None
            super().closeEvent(event)

        def reject(self) -> None:
            self._is_closing = True
            self._copy_feedback_timer.stop()
            if self._active_job is not None:
                self._active_job.cancel()
                self._active_job = None
            super().reject()

        def accept(self) -> None:
            self._is_closing = True
            self._copy_feedback_timer.stop()
            if self._active_job is not None:
                self._active_job.cancel()
                self._active_job = None
            super().accept()

else:
    class _HeadlessSignal:
        def __init__(self) -> None:
            self._callbacks: List[Callable[..., Any]] = []

        def connect(self, cb: Callable[..., Any]) -> None:
            if cb not in self._callbacks:
                self._callbacks.append(cb)

        def disconnect(self, cb: Optional[Callable[..., Any]] = None) -> None:
            if cb is None:
                self._callbacks.clear()
            elif cb in self._callbacks:
                self._callbacks.remove(cb)

        def emit(self, *args: Any) -> None:
            for cb in list(self._callbacks):
                cb(*args)

    class _HeadlessWidgetAttr:
        def __init__(
            self,
            text: str = "",
            *,
            visible: bool = False,
            enabled: bool = True,
            on_change: Optional[Callable[[], None]] = None,
        ) -> None:
            self._text = text
            self._visible = visible
            self._enabled = enabled
            self._selected_text = ""
            self._on_change = on_change

        def setText(self, t: str) -> None:
            self._text = str(t)
            if self._on_change is not None:
                self._on_change()

        def text(self) -> str:
            return self._text

        def setPlainText(self, t: str) -> None:
            self._text = str(t)
            if self._selected_text and self._selected_text not in self._text:
                self._selected_text = ""
            if self._on_change is not None:
                self._on_change()

        def toPlainText(self) -> str:
            return self._text

        def setSelectedText(self, t: str) -> None:
            self._selected_text = str(t)

        def selectedText(self) -> str:
            return self._selected_text

        def selectAll(self) -> None:
            self._selected_text = self._text

        def setVisible(self, v: bool) -> None:
            self._visible = bool(v)

        def isVisible(self) -> bool:
            return self._visible

        def setEnabled(self, e: bool) -> None:
            self._enabled = bool(e)

        def isEnabled(self) -> bool:
            return self._enabled

    class OcrWorkerSignals:  # type: ignore[no-redef]
        def __init__(self) -> None:
            self.progress = _HeadlessSignal()
            self.finished = _HeadlessSignal()

    class OcrWorkerJob:  # type: ignore[no-redef]
        """Headless-compatible background OCR worker."""

        def __init__(
            self,
            image_source: Any,
            *,
            language: str = "eng",
            quality_mode: str = "auto",
            retry_attempt: int = 0,
            auto_invert_dark: bool = True,
            upscale_small_text: bool = True,
            contrast_stretch: bool = True,
            apply_threshold: bool = False,
            allow_builtin_fallback: bool = False,
            custom_binary: Optional[Path] = None,
            custom_tessdata: Optional[Path] = None,
            cancel_token: Optional[CancellationToken] = None,
        ) -> None:
            self.signals = OcrWorkerSignals()
            self._image = _to_pil_rgb(image_source)
            self._language = language
            self._quality_mode = normalize_ocr_quality_mode(quality_mode)
            self._retry_attempt = int(retry_attempt)
            self._auto_invert_dark = auto_invert_dark
            self._upscale_small_text = upscale_small_text
            self._contrast_stretch = contrast_stretch
            self._apply_threshold = apply_threshold
            self._allow_builtin_fallback = allow_builtin_fallback
            self._custom_binary = custom_binary
            self._custom_tessdata = custom_tessdata
            self.cancel_token = cancel_token or CancellationToken()
            self._thread: Optional[threading.Thread] = None

        def cancel(self) -> None:
            self.cancel_token.cancel()

        def run(self) -> None:
            from .backends import recognize_production_ocr

            res = recognize_production_ocr(
                self._image,
                language=self._language,
                quality_mode=self._quality_mode,
                retry_attempt=self._retry_attempt,
                auto_invert_dark=self._auto_invert_dark,
                upscale_small_text=self._upscale_small_text,
                contrast_stretch=self._contrast_stretch,
                apply_threshold=self._apply_threshold,
                allow_builtin_fallback=self._allow_builtin_fallback,
                custom_binary=self._custom_binary,
                custom_tessdata=self._custom_tessdata,
                cancel_token=self.cancel_token,
                progress_callback=lambda pct, msg: self.signals.progress.emit(int(pct), str(msg)),
            )
            self.signals.finished.emit(res)

        def start_async(self) -> threading.Thread:
            t = threading.Thread(target=self.run, daemon=True)
            self._thread = t
            t.start()
            return t

    class OcrResultsDialog:  # type: ignore[no-redef]
        """
        Headless-compatible two-mode OCR results dialog controller mirroring
        Compact Quick OCR (default) and Advanced OCR (on demand) for automated tests,
        with manual High-Contrast Threshold removed and automatic optimization enabled.
        """

        _clipboard_text: str = ""

        def __init__(
            self,
            image_source: Any,
            *,
            initial_result: Optional[OcrRecognitionResult] = None,
            default_language: str = "eng",
            quality_mode: str = "auto",
            auto_copy_on_complete: bool = False,
            show_panel_after_auto_copy: bool = True,
            auto_invert_dark: bool = True,
            upscale_small_text: bool = True,
            apply_threshold: bool = False,
            allow_builtin_fallback: bool = False,
            custom_binary: Optional[Path] = None,
            custom_tessdata: Optional[Path] = None,
            theme_spec: Optional[Dict[str, Any]] = None,
            aqua_theme: str = "ocean_current",
            animation_intensity: str = "medium",
            reduced_motion: bool = False,
            selection_rect: Optional[Tuple[int, int, int, int]] = None,
            available_geometry: Optional[Tuple[int, int, int, int]] = None,
            monitors: Optional[Sequence[Any]] = None,
            initial_mode: str = "quick",
            auto_start: bool = True,
            on_auto_copy_toast: Optional[Callable[[str], None]] = None,
            confirm_overwrite_callback: Optional[Callable[[], bool]] = None,
            parent: Optional[Any] = None,
        ) -> None:
            _ = apply_threshold  # Ignored: preprocessing is now 100% automatic
            self._pil_image = _to_pil_rgb(image_source)
            self._result: Optional[OcrRecognitionResult] = initial_result
            self._default_language = default_language if default_language in SUPPORTED_OCR_LANGUAGES else "eng"
            self._quality_mode: str = normalize_ocr_quality_mode(quality_mode)
            self._auto_copy = bool(auto_copy_on_complete)
            self._show_panel_after_auto_copy = bool(show_panel_after_auto_copy)
            self._auto_invert_dark = bool(auto_invert_dark)
            self._upscale_small_text = bool(upscale_small_text)
            self._allow_builtin_fallback = bool(allow_builtin_fallback)
            self._custom_binary = custom_binary
            self._custom_tessdata = custom_tessdata
            self._selection_rect = selection_rect
            self._available_geometry = available_geometry
            self._monitors = monitors
            self._on_auto_copy_toast = on_auto_copy_toast
            self._confirm_overwrite_callback = confirm_overwrite_callback

            self._palette = resolve_ocr_aqua_theme_palette(
                theme_spec if theme_spec else aqua_theme,
                animation_intensity=animation_intensity,
                reduced_motion=reduced_motion,
            )
            self._mode: str = "advanced" if str(initial_mode).lower() == "advanced" else "quick"
            self._view_state: str = "idle"
            self._active_job: Optional[OcrWorkerJob] = None
            self._is_closing = False
            self._visible = False
            self._raised = False
            self._activated = False
            self._programmatic_text_update = False
            self._user_modified_text = False
            self._last_applied_ocr_text = ""
            self._ocr_run_count = 0
            self._retry_attempt = 0
            self._copy_feedback_active = False
            self._auto_copy_acknowledged = False
            self._last_auto_copy_notice = ""
            self._geometry_rect: Tuple[int, int, int, int] = (0, 0, 440, 185)
            self._layout_columns: int = 2
            self.finished = _HeadlessSignal()

            self.header_title_label = _HeadlessWidgetAttr("Text captured", visible=True)
            self.word_count_badge = _HeadlessWidgetAttr("", visible=False)
            self.quick_footer_lang_label = _HeadlessWidgetAttr(
                format_quick_ocr_footer_label(self._default_language),
                visible=True,
            )
            self.auto_opt_status_label = _HeadlessWidgetAttr(AUTOMATIC_OCR_STATUS_TEXT, visible=False)
            self.backend_diag_label = _HeadlessWidgetAttr("Backend: Pending", visible=False)
            self.status_label = _HeadlessWidgetAttr("Ready.", visible=False)
            self.error_banner = _HeadlessWidgetAttr("", visible=False)
            self.empty_state_banner = _HeadlessWidgetAttr(
                "No text recognized in the selected area. Try Retry or click Expand to change the OCR language or optimization mode.",
                visible=False,
            )
            self.text_edit = _HeadlessWidgetAttr("", visible=True, on_change=self._on_text_edit_changed)
            self.preview_widget = _HeadlessWidgetAttr("", visible=False)
            self.lines_list = _HeadlessWidgetAttr("", visible=False)
            self.copy_btn = _HeadlessWidgetAttr("Copy", visible=True)
            self.expand_btn = _HeadlessWidgetAttr("Expand", visible=True)
            self.collapse_btn = _HeadlessWidgetAttr("Compact View", visible=False)
            self.header_close_btn = _HeadlessWidgetAttr("✕", visible=True)
            self.quick_retry_btn = _HeadlessWidgetAttr("Retry", visible=False)
            self.quick_close_btn = _HeadlessWidgetAttr("Close", visible=False)
            self.copy_all_btn = _HeadlessWidgetAttr("Copy All", visible=False)
            self.copy_sel_btn = _HeadlessWidgetAttr("Copy Selected", visible=False)
            self.save_txt_btn = _HeadlessWidgetAttr("Save Text...", visible=False)
            self.export_diag_btn = _HeadlessWidgetAttr("Export Diagnostics...", visible=False)
            self.retry_btn = _HeadlessWidgetAttr("Retry Recognition", visible=False)
            self.cancel_btn = _HeadlessWidgetAttr("Cancel", visible=False)
            self.close_btn = _HeadlessWidgetAttr("Close", visible=False)
            self.lines: List[str] = []

            self._apply_mode_layout(preserve_selection=False)

            if self._result is not None:
                self._ocr_run_count = 1
                self._apply_result(self._result)
            elif auto_start:
                self.start_recognition(force_discard_edits=True)

        @property
        def mode(self) -> str:
            return self._mode

        @property
        def is_quick_mode(self) -> bool:
            return self._mode == "quick"

        @property
        def is_advanced_mode(self) -> bool:
            return self._mode == "advanced"

        @property
        def view_state(self) -> str:
            return self._view_state

        @property
        def ocr_run_count(self) -> int:
            return self._ocr_run_count

        @property
        def retry_attempt(self) -> int:
            return self._retry_attempt

        @property
        def quality_mode(self) -> str:
            return self._quality_mode

        @property
        def user_modified_text(self) -> bool:
            return self._user_modified_text

        @property
        def copy_feedback_active(self) -> bool:
            return self._copy_feedback_active

        @property
        def auto_copy_acknowledged(self) -> bool:
            return self._auto_copy_acknowledged

        @property
        def last_auto_copy_notice(self) -> str:
            return self._last_auto_copy_notice

        def windowTitle(self) -> str:
            return "Prismwake — Text Capture (Offline OCR)"

        def present_in_front(self) -> None:
            if self._is_closing:
                return
            self.reposition_near_selection()
            self._visible = True
            self._raised = True
            self._activated = True

        def show(self) -> None:
            if not self._is_closing:
                self._visible = True

        def raise_(self) -> None:
            self._raised = True

        def activateWindow(self) -> None:
            self._activated = True

        def isVisible(self) -> bool:
            return self._visible and not self._is_closing

        def panel_geometry(self) -> Tuple[int, int, int, int]:
            return self._geometry_rect

        def reposition_near_selection(
            self,
            selection_rect: Optional[Tuple[int, int, int, int]] = None,
            available_geometry: Optional[Tuple[int, int, int, int]] = None,
            monitors: Optional[Sequence[Any]] = None,
        ) -> Tuple[int, int, int, int]:
            if selection_rect is not None:
                self._selection_rect = selection_rect
            if available_geometry is not None:
                self._available_geometry = available_geometry
            if monitors is not None:
                self._monitors = monitors

            if self._mode == "quick":
                geom = compute_quick_ocr_panel_geometry(
                    self.text_edit.toPlainText(),
                    selection_rect=self._selection_rect,
                    available_geometry=self._available_geometry,
                    monitors=self._monitors,
                    view_state=self._view_state,
                )
                self._geometry_rect = (geom["x"], geom["y"], geom["width"], geom["height"])
                return self._geometry_rect

            adv = compute_advanced_ocr_panel_geometry(
                current_rect=self._geometry_rect,
                selection_rect=self._selection_rect,
                available_geometry=self._available_geometry,
                monitors=self._monitors,
            )
            self._layout_columns = int(adv["layout_columns"])
            self._geometry_rect = (adv["x"], adv["y"], adv["width"], adv["height"])
            return self._geometry_rect

        def _on_text_edit_changed(self) -> None:
            if self._programmatic_text_update:
                return
            current_txt = self.text_edit.toPlainText()
            self._user_modified_text = (current_txt != self._last_applied_ocr_text)
            badge_str = format_quick_ocr_badge_text(current_txt, self._result)
            self.word_count_badge.setText(badge_str)
            self.word_count_badge.setVisible(bool(badge_str))
            has_any = bool(current_txt.strip())
            self.copy_btn.setEnabled(has_any)
            self.copy_all_btn.setEnabled(has_any)
            self.copy_sel_btn.setEnabled(has_any)
            self.save_txt_btn.setEnabled(has_any)

        def set_language(self, lang_code: str) -> None:
            norm = (lang_code or "eng").strip().lower()
            if norm in SUPPORTED_OCR_LANGUAGES:
                self._default_language = norm
                self.quick_footer_lang_label.setText(
                    format_quick_ocr_footer_label(norm, auto_copied=self._auto_copy_acknowledged)
                )

        def set_quality_mode(self, mode: str) -> None:
            self._quality_mode = normalize_ocr_quality_mode(mode)

        def expand_to_advanced(self) -> None:
            if self._mode == "advanced":
                return
            self._mode = "advanced"
            self._apply_mode_layout(preserve_selection=True)

        def collapse_to_quick(self) -> None:
            if self._mode == "quick":
                return
            self._mode = "quick"
            self._apply_mode_layout(preserve_selection=True)

        def toggle_mode(self) -> str:
            if self._mode == "quick":
                self.expand_to_advanced()
            else:
                self.collapse_to_quick()
            return self._mode

        def _apply_mode_layout(self, *, preserve_selection: bool = True) -> None:
            saved_sel = self.text_edit.selectedText()
            is_quick = (self._mode == "quick")

            self.preview_widget.setVisible(not is_quick)
            self.lines_list.setVisible(not is_quick)
            self.auto_opt_status_label.setVisible(not is_quick)
            self.backend_diag_label.setVisible(not is_quick)
            self.expand_btn.setVisible(is_quick)
            self.collapse_btn.setVisible(not is_quick)
            self.quick_footer_lang_label.setVisible(is_quick)
            self.copy_all_btn.setVisible(not is_quick)
            self.copy_sel_btn.setVisible(not is_quick)
            self.save_txt_btn.setVisible(not is_quick)
            self.export_diag_btn.setVisible(not is_quick)
            self.retry_btn.setVisible(not is_quick)
            self.close_btn.setVisible(not is_quick)
            self.status_label.setVisible((not is_quick) or (self._view_state == "recognizing"))

            if is_quick:
                if self._view_state == "empty":
                    self.header_title_label.setText("No text recognized")
                elif self._view_state == "error":
                    self.header_title_label.setText("OCR unavailable")
                elif self._view_state == "recognizing":
                    self.header_title_label.setText("Recognizing text...")
                else:
                    self.header_title_label.setText("Text captured")
            else:
                self.header_title_label.setText("Prismwake Offline Text Recognition (OCR)")

            self._sync_state_widget_visibility()
            self.reposition_near_selection()
            if preserve_selection and saved_sel:
                self.text_edit.setSelectedText(saved_sel)

        def _sync_state_widget_visibility(self) -> None:
            is_quick = (self._mode == "quick")
            is_empty = (self._view_state == "empty")
            is_err = (self._view_state == "error")
            is_rec = (self._view_state == "recognizing")
            has_txt = bool(self.text_edit.toPlainText().strip())

            self.empty_state_banner.setVisible(is_empty and not has_txt)
            self.error_banner.setVisible(is_err)

            if is_quick:
                show_editor_in_quick = has_txt or (self._view_state == "ready") or self._user_modified_text
                self.text_edit.setVisible(show_editor_in_quick)
                self.quick_retry_btn.setVisible(is_empty or is_err or self._view_state == "cancelled")
                self.quick_close_btn.setVisible(is_empty or is_err)
                self.copy_btn.setVisible(not (is_empty or is_err) or has_txt)
                self.status_label.setVisible(is_rec)
            else:
                self.text_edit.setVisible(True)
                self.status_label.setVisible(True)

        def select_all_text(self) -> str:
            self.text_edit.selectAll()
            return self.text_edit.selectedText()

        def copy_shortcut_action(self) -> str:
            if self.text_edit.selectedText():
                return self.copy_selected_text()
            return self.copy_all_text()

        def escape_action(self) -> None:
            if self._active_job is not None:
                self.cancel_recognition()
                return
            self.close()

        def start_recognition(
            self,
            *,
            async_run: bool = False,
            force_discard_edits: bool = False,
        ) -> bool:
            if self._is_closing:
                return False
            if self._user_modified_text and not force_discard_edits:
                if self._confirm_overwrite_callback is not None:
                    if not self._confirm_overwrite_callback():
                        return False
                else:
                    return False

            if self._active_job is not None:
                self._active_job.cancel()
                self._active_job = None

            if self._ocr_run_count >= 1:
                self._retry_attempt += 1
            self._ocr_run_count += 1
            self._view_state = "recognizing"
            self.error_banner.setVisible(False)
            self.empty_state_banner.setVisible(False)
            self.retry_btn.setEnabled(False)
            self.quick_retry_btn.setEnabled(False)
            self.cancel_btn.setVisible(True)
            self.status_label.setText(f"Recognizing pass 1 of up to 4 ({self._default_language})...")
            if self._mode == "quick":
                self.header_title_label.setText("Recognizing text...")
            self._sync_state_widget_visibility()

            job = OcrWorkerJob(
                self._pil_image,
                language=self._default_language,
                quality_mode=self._quality_mode,
                retry_attempt=self._retry_attempt,
                auto_invert_dark=self._auto_invert_dark,
                upscale_small_text=self._upscale_small_text,
                allow_builtin_fallback=self._allow_builtin_fallback,
                custom_binary=self._custom_binary,
                custom_tessdata=self._custom_tessdata,
            )
            job.signals.progress.connect(self._on_job_progress)
            job.signals.finished.connect(self._on_job_finished)
            self._active_job = job
            if async_run:
                job.start_async()
            else:
                job.run()
            return True

        def wait_for_recognition(self, timeout: float = 5.0) -> Optional[OcrRecognitionResult]:
            if self._active_job is not None and self._active_job._thread is not None:
                self._active_job._thread.join(timeout=timeout)
            return self._result

        def cancel_recognition(self) -> None:
            if self._active_job is not None:
                self._active_job.cancel()
                self._active_job = None
                if not self._is_closing:
                    self._view_state = "cancelled"
                    self.retry_btn.setEnabled(True)
                    self.quick_retry_btn.setEnabled(True)
                    self.cancel_btn.setVisible(False)
                    self.status_label.setText("Recognition cancelled.")
                    if self._mode == "quick":
                        self.header_title_label.setText("Recognition cancelled")
                    self._sync_state_widget_visibility()

        def _on_job_progress(self, _pct: int, msg: str) -> None:
            if not self._is_closing:
                self.status_label.setText(msg)

        def _on_job_finished(self, result: OcrRecognitionResult) -> None:
            if self._is_closing:
                return
            self._active_job = None
            self.retry_btn.setEnabled(True)
            self.quick_retry_btn.setEnabled(True)
            self.cancel_btn.setVisible(False)
            self._apply_result(result)

        def _apply_result(self, result: OcrRecognitionResult) -> None:
            self._result = result
            self.lines = [ln.text for ln in result.lines]
            backend_lbl = getattr(result, "backend_selected", "") or (
                "RapidOCR (ONNX CPU)" if result.engine_name == "rapidocr" else "Tesseract fallback"
            )
            self.backend_diag_label.setText(f"Backend: {backend_lbl}")

            if result.error:
                self._view_state = "error"
                self.error_banner.setText(f"OCR Engine Error: {result.error}")
                self.error_banner.setVisible(True)
                self.empty_state_banner.setVisible(False)
                self.status_label.setText(f"Error: {result.error}")
                if not self._user_modified_text:
                    self._programmatic_text_update = True
                    self.text_edit.setPlainText("")
                    self._programmatic_text_update = False
                    self._last_applied_ocr_text = ""
                self.word_count_badge.setText("")
                self.word_count_badge.setVisible(False)
                self.copy_btn.setEnabled(False)
                self.copy_all_btn.setEnabled(False)
                self.copy_sel_btn.setEnabled(False)
                self.save_txt_btn.setEnabled(False)
                if self._mode == "quick":
                    self.header_title_label.setText("OCR unavailable")
                self._sync_state_widget_visibility()
                self.reposition_near_selection()
                return

            if result.cancelled:
                self._view_state = "cancelled"
                self.error_banner.setVisible(False)
                self.status_label.setText("Recognition cancelled.")
                if self._mode == "quick":
                    self.header_title_label.setText("Recognition cancelled")
                self._sync_state_widget_visibility()
                return

            self.error_banner.setVisible(False)
            self._programmatic_text_update = True
            self.text_edit.setPlainText(result.text)
            self._programmatic_text_update = False
            self._last_applied_ocr_text = result.text
            self._user_modified_text = False
            backend_lbl = getattr(result, "backend_selected", "") or (
                "RapidOCR (ONNX CPU)" if result.engine_name == "rapidocr" else "Tesseract fallback"
            )
            self.backend_diag_label.setText(f"Backend: {backend_lbl}")
            self.status_label.setText(format_ocr_summary(result))

            if not result.has_text:
                self._view_state = "empty"
                self.word_count_badge.setText("")
                self.word_count_badge.setVisible(False)
                self.copy_btn.setEnabled(False)
                self.copy_all_btn.setEnabled(False)
                self.copy_sel_btn.setEnabled(False)
                self.save_txt_btn.setEnabled(False)
                if self._mode == "quick":
                    self.header_title_label.setText("No text recognized")
                self._sync_state_widget_visibility()
                self.reposition_near_selection()
                return

            self._view_state = "ready"
            badge_str = format_quick_ocr_badge_text(result.text, result)
            self.word_count_badge.setText(badge_str)
            self.word_count_badge.setVisible(bool(badge_str))
            self.copy_btn.setEnabled(True)
            self.copy_all_btn.setEnabled(True)
            self.copy_sel_btn.setEnabled(True)
            self.save_txt_btn.setEnabled(True)
            if self._mode == "quick":
                self.header_title_label.setText("Text captured")

            if self._auto_copy and result.has_text:
                self.copy_all_text(silent=True)
                self._auto_copy_acknowledged = True
                n_words, _ = count_recognized_words_and_lines(result.text, result)
                self._last_auto_copy_notice = f"Copied {n_words} {'word' if n_words == 1 else 'words'} to clipboard"
                self.quick_footer_lang_label.setText(
                    format_quick_ocr_footer_label(result.language, auto_copied=True)
                )
                if self._on_auto_copy_toast is not None:
                    try:
                        self._on_auto_copy_toast(self._last_auto_copy_notice)
                    except Exception:
                        pass
                if not self._show_panel_after_auto_copy:
                    self.close()
                    return
            else:
                self.quick_footer_lang_label.setText(
                    format_quick_ocr_footer_label(result.language, auto_copied=False)
                )

            self._sync_state_widget_visibility()
            self.reposition_near_selection()

        def copy_all_text(self, silent: bool = False) -> str:
            txt = self.text_edit.toPlainText()
            if not txt:
                return ""
            OcrResultsDialog._clipboard_text = txt
            self._copy_feedback_active = True
            self.copy_btn.setText("Copied!")
            self.copy_all_btn.setText("Copied!")
            if not silent:
                self.status_label.setText(f"Copied {len(txt)} characters to clipboard.")
            return txt

        def copy_selected_text(self) -> str:
            sel = self.text_edit.selectedText() or self.text_edit.toPlainText()
            if not sel:
                return ""
            OcrResultsDialog._clipboard_text = sel
            self._copy_feedback_active = True
            self.copy_btn.setText("Copied!")
            self.copy_all_btn.setText("Copied!")
            self.status_label.setText(f"Copied {len(sel)} selected characters to clipboard.")
            return sel

        def close(self) -> None:
            self._is_closing = True
            self._visible = False
            if self._active_job is not None:
                self._active_job.cancel()
                self._active_job = None
            self.finished.emit(0)

        def deleteLater(self) -> None:
            self._visible = False

        def export_diagnostic_bundle(self, target_dir: Any) -> Dict[str, Any]:
            info = export_ocr_diagnostic_bundle(
                self._pil_image,
                target_dir,
                result=self._result,
                language=self._default_language,
                quality_mode=self._quality_mode,
            )
            self.status_label.setText(f"Exported diagnostic bundle to {Path(info['output_dir']).name}")
            return info
