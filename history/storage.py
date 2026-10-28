"""
Prismwake v0.2.0 — SQLite + FTS5 Screenshot History Storage & Frutiger Aqua Gallery UI
======================================================================================
Features:
  - Persistent SQLite + FTS5 Screenshot History store with automatic corruption recovery,
    schema migration, retention enforcement, and non-blocking background OCR indexing.
  - Authentic Frutiger Aqua / Aero Gel `HistoryWindow` gallery matching the main Prismwake
    interface:
      * Layered translucent Frutiger Aqua glass panels (`AquaGlassPanel`) and bounded
        low-resolution animated optical water & caustic background synchronized to the
        shared ~30 FPS `AeroAnimationDirector` clock (paused automatically when hidden,
        minimized, closed, or when Animation Intensity is Off / Safe Mode).
      * Genuine `AeroGelButton` controls with smooth 240ms hover sweeps, centered inward
        silicone-gel compression, elastic rebound, moving specular highlights, and click
        water ripples across all primary, secondary, and destructive ruby actions.
      * 3-Region Gallery Layout + Top Header Bar:
          1. Top Header Bar: Title, live item count badge, instant debounced search bar
             (`Ctrl+F`) with clear button, 5-mode sort selector, Grid / Compact List view
             toggle, `New Capture`, and `Storage & Privacy Settings`.
          2. Left Filter & Storage Sidebar: Frutiger Aqua category filter pills (`All Captures`,
             `★ Favorites`, `Recent (7 Days)`, `Recognized Text`) with live item counts,
             structured Storage & Privacy liquid meter card, and visually separated
             destructive cleanup actions (`Delete Selected`, `Clear Non-Favorites`, `Clear History...`).
          3. Center Screenshot Gallery: Custom-painted rounded Frutiger Aqua glass screenshot
             cards (`HistoryCardDelegate`) with crisp aspect-ratio-preserving thumbnails,
             hover lift & cyan glow, selected double-rim glow, interactive favorite star
             badge, OCR indicator pill, and clean empty / no-results states.
          4. Right Preview & Actions Inspector: Large undistorted aspect-ratio screenshot
             preview well, capture metadata badges, Recognized Text (OCR) glass card, and
             logically grouped `AeroGelButton` actions.
      * High-Performance Large-History Pipeline:
          - Bounded LRU `QPixmap` thumbnail cache + viewport-prioritized lazy batch loading.
          - Bounded LRU full-preview `QPixmap` cache + instant progressive thumbnail preview
            with cancellable asynchronous full-resolution image decoding.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

try:
    from PyQt6.QtCore import (
        QEasingCurve,
        QElapsedTimer,
        QEvent,
        QObject,
        QPoint,
        QPointF,
        QRect,
        QRectF,
        QSize,
        Qt,
        QTimer,
        QVariantAnimation,
        pyqtSignal,
    )
    from PyQt6.QtGui import (
        QAction,
        QBrush,
        QColor,
        QCursor,
        QFont,
        QFontMetrics,
        QIcon,
        QImage,
        QKeySequence,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
        QRadialGradient,
        QShortcut,
    )
    from PyQt6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QComboBox,
        QDialog,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMenu,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSplitter,
        QStyle,
        QStyledItemDelegate,
        QVBoxLayout,
        QWidget,
    )
    HAS_QT = True
except Exception:
    HAS_QT = False


HISTORY_SCHEMA_VERSION: int = 2
VALID_HISTORY_MODES: Tuple[str, ...] = ("off", "saved_or_copied", "all_completed")
VALID_HISTORY_SORT_MODES: Tuple[str, ...] = (
    "newest",
    "oldest",
    "largest",
    "smallest",
    "favorites_first",
)
VALID_HISTORY_VIEW_MODES: Tuple[str, ...] = ("grid", "list")
HISTORY_VIEW_MODES: Tuple[str, ...] = VALID_HISTORY_VIEW_MODES
HISTORY_CATEGORY_FILTERS: Tuple[str, ...] = ("all", "favorites", "recent", "with_text")

HISTORY_AQUA_THEMES: Dict[str, Dict[str, Any]] = {
    "ocean_current": {
        "label": "Aqua Classic",
        "primary_rgb": (0, 145, 225),
        "mid_rgb": (0, 210, 245),
        "accent_rgb": (65, 255, 195),
        "dialog_top_rgb": (10, 62, 118),
        "dialog_mid_rgb": (6, 108, 174),
        "dialog_bot_rgb": (4, 48, 92),
        "border_rgb": (95, 235, 255),
        "border_inner_rgb": (0, 230, 255),
        "card_bg_rgb": (7, 34, 68),
        "card_sel_rgb": (12, 88, 156),
        "text_accent_hex": "#8CF4FF",
    },
    "emerald_lagoon": {
        "label": "Emerald Glass",
        "primary_rgb": (0, 158, 148),
        "mid_rgb": (18, 222, 188),
        "accent_rgb": (110, 255, 165),
        "dialog_top_rgb": (8, 72, 78),
        "dialog_mid_rgb": (10, 122, 118),
        "dialog_bot_rgb": (4, 52, 58),
        "border_rgb": (110, 250, 215),
        "border_inner_rgb": (32, 242, 195),
        "card_bg_rgb": (6, 42, 48),
        "card_sel_rgb": (12, 104, 102),
        "text_accent_hex": "#98FFE0",
    },
    "aurora_mint": {
        "label": "Deep Ocean",
        "primary_rgb": (14, 138, 195),
        "mid_rgb": (42, 228, 212),
        "accent_rgb": (135, 255, 210),
        "dialog_top_rgb": (10, 66, 98),
        "dialog_mid_rgb": (14, 118, 148),
        "dialog_bot_rgb": (5, 48, 76),
        "border_rgb": (125, 252, 235),
        "border_inner_rgb": (64, 245, 220),
        "card_bg_rgb": (7, 38, 60),
        "card_sel_rgb": (14, 96, 132),
        "text_accent_hex": "#9EFFEC",
    },
    "sapphire_zenith": {
        "label": "Sunset Gel",
        "primary_rgb": (18, 108, 230),
        "mid_rgb": (55, 178, 255),
        "accent_rgb": (110, 235, 255),
        "dialog_top_rgb": (12, 48, 118),
        "dialog_mid_rgb": (18, 86, 178),
        "dialog_bot_rgb": (6, 34, 88),
        "border_rgb": (120, 215, 255),
        "border_inner_rgb": (65, 195, 255),
        "card_bg_rgb": (8, 30, 74),
        "card_sel_rgb": (18, 76, 164),
        "text_accent_hex": "#9EDBFF",
    },
    "crystal_frost": {
        "label": "Midnight Slate",
        "primary_rgb": (52, 138, 196),
        "mid_rgb": (118, 208, 248),
        "accent_rgb": (195, 248, 255),
        "dialog_top_rgb": (20, 58, 92),
        "dialog_mid_rgb": (36, 96, 144),
        "dialog_bot_rgb": (12, 38, 66),
        "border_rgb": (175, 242, 255),
        "border_inner_rgb": (135, 228, 255),
        "card_bg_rgb": (14, 34, 56),
        "card_sel_rgb": (32, 82, 128),
        "text_accent_hex": "#C4F4FF",
    },
}

_THEME_ALIASES: Dict[str, str] = {
    "aqua classic": "ocean_current",
    "bondi blue": "ocean_current",
    "deep sea": "aurora_mint",
    "ocean current": "ocean_current",
    "ocean_current": "ocean_current",
    "emerald glass": "emerald_lagoon",
    "emerald lagoon": "emerald_lagoon",
    "emerald_lagoon": "emerald_lagoon",
    "deep ocean": "aurora_mint",
    "aurora mint": "aurora_mint",
    "aurora_mint": "aurora_mint",
    "sunset gel": "sapphire_zenith",
    "sapphire zenith": "sapphire_zenith",
    "sapphire_zenith": "sapphire_zenith",
    "midnight slate": "crystal_frost",
    "crystal frost": "crystal_frost",
    "crystal_frost": "crystal_frost",
}


def normalize_history_aqua_theme(theme_name: str) -> str:
    raw = str(theme_name or "ocean_current").strip().lower()
    if raw in HISTORY_AQUA_THEMES:
        return raw
    if raw in _THEME_ALIASES:
        return _THEME_ALIASES[raw]
    for k, spec in HISTORY_AQUA_THEMES.items():
        if str(spec.get("label", "")).strip().lower() == raw:
            return k
    return "ocean_current"


def get_history_aqua_theme_spec(theme_name: str) -> Dict[str, Any]:
    return HISTORY_AQUA_THEMES[normalize_history_aqua_theme(theme_name)]


def get_default_history_root() -> Path:
    """Return `%LOCALAPPDATA%\\Prismwake\\History` on Windows or `~/.local/share/Prismwake/History` elsewhere."""
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            return Path(local_appdata) / "Prismwake" / "History"
        return Path.home() / "AppData" / "Local" / "Prismwake" / "History"
    xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data:
        return Path(xdg_data) / "Prismwake" / "History"
    return Path.home() / ".local" / "share" / "Prismwake" / "History"


@dataclass
class HistoryEntry:
    """Single screenshot history record stored in SQLite."""
    capture_id: str
    timestamp_utc: float
    date_iso: str
    image_path: str
    thumbnail_path: str
    external_save_path: str = ""
    width: int = 0
    height: int = 0
    file_size_bytes: int = 0
    favorite: bool = False
    title: str = ""
    ocr_available: bool = False
    ocr_text: str = ""
    capture_mode: str = "region"
    schema_version: int = HISTORY_SCHEMA_VERSION

    @property
    def display_title(self) -> str:
        if self.title and self.title.strip():
            return self.title.strip()
        if self.external_save_path:
            return Path(self.external_save_path).name
        if self.image_path:
            return Path(self.image_path).name
        return f"Capture {self.capture_id[:8]}"

    @property
    def image_exists(self) -> bool:
        try:
            if self.image_path and Path(self.image_path).is_file():
                return True
            if self.external_save_path and Path(self.external_save_path).is_file():
                return True
        except Exception:
            pass
        return False

    @property
    def resolved_image_path(self) -> Optional[Path]:
        for cand in (self.image_path, self.external_save_path):
            if cand:
                try:
                    p = Path(cand)
                    if p.is_file():
                        return p
                except Exception:
                    continue
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capture_id": self.capture_id,
            "timestamp_utc": float(self.timestamp_utc),
            "date_iso": self.date_iso,
            "image_path": self.image_path,
            "thumbnail_path": self.thumbnail_path,
            "external_save_path": self.external_save_path,
            "width": int(self.width),
            "height": int(self.height),
            "file_size_bytes": int(self.file_size_bytes),
            "favorite": bool(self.favorite),
            "title": self.title,
            "ocr_available": bool(self.ocr_available),
            "ocr_text": self.ocr_text,
            "capture_mode": self.capture_mode,
            "schema_version": int(self.schema_version),
        }


@dataclass(frozen=True)
class HistoryStorageStats:
    total_items: int
    favorite_items: int
    ocr_indexed_items: int
    managed_images_bytes: int
    thumbnails_bytes: int
    database_bytes: int
    total_bytes: int
    root_dir: Path

    @property
    def total_megabytes(self) -> float:
        return self.total_bytes / (1024.0 * 1024.0)


def _to_pil_rgb(image_source: Any) -> Image.Image:
    if isinstance(image_source, Image.Image):
        return image_source.convert("RGB")
    if isinstance(image_source, np.ndarray):
        arr = np.asarray(image_source)
        if arr.ndim == 2:
            return Image.fromarray(arr.astype(np.uint8), mode="L").convert("RGB")
        if arr.ndim == 3 and arr.shape[2] >= 3:
            return Image.fromarray(arr[:, :, :3].astype(np.uint8), mode="RGB")
        raise ValueError(f"Unsupported ndarray shape: {arr.shape}")
    if HAS_QT:
        if isinstance(image_source, QPixmap):
            image_source = image_source.toImage()
        if isinstance(image_source, QImage):
            qimg = image_source.convertToFormat(QImage.Format.Format_RGBA8888)
            w, h = qimg.width(), qimg.height()
            if w <= 0 or h <= 0:
                return Image.new("RGB", (1, 1), (0, 0, 0))
            ptr = qimg.bits()
            ptr.setsize(h * qimg.bytesPerLine())
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, qimg.bytesPerLine() // 4, 4))
            return Image.fromarray(arr[:, :w, :3].copy(), mode="RGB")
    raise TypeError(f"Unsupported image source type: {type(image_source)!r}")


def _atomic_save_pil_png(pil_img: Image.Image, dest_path: Path) -> int:
    """Save `pil_img` atomically via a temporary sibling file and return file size in bytes."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        prefix=f".{dest_path.stem}_",
        suffix=".tmp.png",
        dir=str(dest_path.parent),
    )
    os.close(fd)
    tmp_path = Path(tmp_str)
    try:
        pil_img.save(str(tmp_path), format="PNG", optimize=False)
        os.replace(str(tmp_path), str(dest_path))
        return int(dest_path.stat().st_size)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


class ScreenshotHistoryStore:
    """
    Persistent local SQLite + FTS5 screenshot history store.
    Handles database corruption recovery, schema migrations, privacy modes,
    bounded thumbnail caching, fast stats caching, and safe managed-file cleanup.
    """

    def __init__(
        self,
        root_dir: Optional[Path] = None,
        *,
        privacy_mode: str = "saved_or_copied",
        max_items: int = 500,
        max_storage_mb: int = 1024,
        max_age_days: int = 90,
        enable_ocr_indexing: bool = True,
        thumbnail_size: Tuple[int, int] = (280, 175),
    ) -> None:
        self.root_dir: Path = Path(root_dir) if root_dir is not None else get_default_history_root()
        self.db_path: Path = self.root_dir / "history.db"
        self.images_dir: Path = self.root_dir / "images"
        self.thumbnails_dir: Path = self.root_dir / "thumbnails"

        self.privacy_mode: str = privacy_mode if privacy_mode in VALID_HISTORY_MODES else "saved_or_copied"
        self.max_items: int = max(1, int(max_items))
        self.max_storage_mb: int = max(5, int(max_storage_mb))
        self.max_age_days: int = max(0, int(max_age_days))
        self.enable_ocr_indexing: bool = bool(enable_ocr_indexing)
        self.thumbnail_size: Tuple[int, int] = thumbnail_size

        self._lock = threading.RLock()
        self._fts5_supported: bool = False
        self._recovered_from_corruption: bool = False
        self._thumb_memory_cache: "OrderedDict[str, Image.Image]" = OrderedDict()
        self._thumb_cache_capacity: int = 160
        self._entry_memory_cache: "OrderedDict[str, HistoryEntry]" = OrderedDict()
        self._entry_cache_capacity: int = 512
        self._cached_stats: Optional[HistoryStorageStats] = None
        self._stats_dirty: bool = True
        self._shutdown_event = threading.Event()
        self._bg_ocr_threads: List[threading.Thread] = []
        self._bg_ocr_semaphore = threading.BoundedSemaphore(2)
        # Transient progress only. OCR text itself is persisted in SQLite.
        self._ocr_job_states: Dict[str, str] = {}

        self._initialize_database()

    @property
    def recovered_from_corruption(self) -> bool:
        return self._recovered_from_corruption

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Commit/rollback AND close each connection, including on Python 3.14."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _initialize_database(self) -> None:
        with self._lock:
            self.root_dir.mkdir(parents=True, exist_ok=True)
            self.images_dir.mkdir(parents=True, exist_ok=True)
            self.thumbnails_dir.mkdir(parents=True, exist_ok=True)

            if self.db_path.exists():
                try:
                    raw_head = self.db_path.read_bytes()[:16]
                    if raw_head and raw_head != b"SQLite format 3\x00":
                        raise sqlite3.DatabaseError("Invalid SQLite file header")
                    with self._connect() as conn:
                        res = conn.execute("PRAGMA quick_check").fetchone()
                        if not res or str(res[0]).lower() != "ok":
                            raise sqlite3.DatabaseError("PRAGMA quick_check failed")
                except sqlite3.DatabaseError:
                    self._quarantine_corrupted_db()

            try:
                self._create_or_migrate_schema()
            except sqlite3.DatabaseError:
                self._quarantine_corrupted_db()
                self._create_or_migrate_schema()

    def _quarantine_corrupted_db(self) -> None:
        """Move a corrupted SQLite file aside without deleting any user screenshots."""
        self._recovered_from_corruption = True
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.root_dir / f"history.corrupt.{ts}.db"
        for suf in ("-wal", "-shm"):
            try:
                Path(str(self.db_path) + suf).unlink(missing_ok=True)
            except Exception:
                pass
        try:
            if self.db_path.exists():
                os.replace(str(self.db_path), str(backup_path))
        except Exception:
            try:
                self.db_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _create_or_migrate_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
            current_ver = int(row["value"]) if row else 0

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS captures (
                    capture_id TEXT PRIMARY KEY,
                    timestamp_utc REAL NOT NULL,
                    date_iso TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    thumbnail_path TEXT NOT NULL,
                    external_save_path TEXT NOT NULL DEFAULT '',
                    width INTEGER NOT NULL DEFAULT 0,
                    height INTEGER NOT NULL DEFAULT 0,
                    file_size_bytes INTEGER NOT NULL DEFAULT 0,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    title TEXT NOT NULL DEFAULT '',
                    ocr_available INTEGER NOT NULL DEFAULT 0,
                    ocr_text TEXT NOT NULL DEFAULT '',
                    capture_mode TEXT NOT NULL DEFAULT 'region',
                    schema_version INTEGER NOT NULL DEFAULT 2
                )
                """
            )

            existing_cols = {
                r["name"] for r in conn.execute("PRAGMA table_info(captures)").fetchall()
            }
            migrations = [
                ("external_save_path", "ALTER TABLE captures ADD COLUMN external_save_path TEXT NOT NULL DEFAULT ''"),
                ("favorite", "ALTER TABLE captures ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0"),
                ("title", "ALTER TABLE captures ADD COLUMN title TEXT NOT NULL DEFAULT ''"),
                ("ocr_available", "ALTER TABLE captures ADD COLUMN ocr_available INTEGER NOT NULL DEFAULT 0"),
                ("ocr_text", "ALTER TABLE captures ADD COLUMN ocr_text TEXT NOT NULL DEFAULT ''"),
                ("capture_mode", "ALTER TABLE captures ADD COLUMN capture_mode TEXT NOT NULL DEFAULT 'region'"),
                ("schema_version", f"ALTER TABLE captures ADD COLUMN schema_version INTEGER NOT NULL DEFAULT {HISTORY_SCHEMA_VERSION}"),
            ]
            for col_name, ddl in migrations:
                if col_name not in existing_cols:
                    conn.execute(ddl)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_ts ON captures(timestamp_utc DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_fav ON captures(favorite DESC, timestamp_utc DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_size ON captures(file_size_bytes DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_ocr ON captures(ocr_available, timestamp_utc DESC)")

            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
                        capture_id UNINDEXED,
                        title,
                        filename,
                        date_iso,
                        ocr_text
                    )
                    """
                )
                self._fts5_supported = True
            except sqlite3.OperationalError:
                self._fts5_supported = False

            if current_ver < HISTORY_SCHEMA_VERSION:
                conn.execute(
                    "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                    (str(HISTORY_SCHEMA_VERSION),),
                )
                if self._fts5_supported:
                    self._rebuild_fts_index(conn)
            conn.commit()

    def _rebuild_fts_index(self, conn: sqlite3.Connection) -> None:
        if not self._fts5_supported:
            return
        conn.execute("DELETE FROM captures_fts")
        rows = conn.execute(
            "SELECT capture_id, title, image_path, external_save_path, date_iso, ocr_text FROM captures"
        ).fetchall()
        for r in rows:
            fname = Path(r["external_save_path"] or r["image_path"]).name
            conn.execute(
                "INSERT INTO captures_fts(capture_id, title, filename, date_iso, ocr_text) VALUES (?, ?, ?, ?, ?)",
                (r["capture_id"], r["title"], fname, r["date_iso"], r["ocr_text"]),
            )

    def should_record_capture(self, *, was_saved_or_copied: bool, was_cancelled: bool = False) -> bool:
        if was_cancelled:
            return False
        if self.privacy_mode == "off":
            return False
        if self.privacy_mode == "saved_or_copied":
            return bool(was_saved_or_copied)
        if self.privacy_mode == "all_completed":
            return True
        return bool(was_saved_or_copied)

    def _generate_thumbnail_pil(self, pil_rgb: Image.Image) -> Image.Image:
        thumb = pil_rgb.copy()
        thumb.thumbnail(self.thumbnail_size, Image.Resampling.BILINEAR)
        return thumb

    def _set_cached_entry(self, entry: HistoryEntry) -> None:
        self._entry_memory_cache[entry.capture_id] = entry
        self._entry_memory_cache.move_to_end(entry.capture_id)
        while len(self._entry_memory_cache) > self._entry_cache_capacity:
            self._entry_memory_cache.popitem(last=False)

    def record_capture(
        self,
        image_source: Any,
        *,
        capture_mode: str = "region",
        title: str = "",
        ocr_text: str = "",
        external_save_path: Optional[Path] = None,
        favorite: bool = False,
        was_saved_or_copied: bool = True,
        was_cancelled: bool = False,
        timestamp_utc: Optional[float] = None,
        ocr_indexer: Optional[Callable[[Image.Image], str]] = None,
    ) -> Optional[HistoryEntry]:
        if not self.should_record_capture(
            was_saved_or_copied=was_saved_or_copied,
            was_cancelled=was_cancelled,
        ):
            return None

        pil_rgb = _to_pil_rgb(image_source)
        w, h = pil_rgb.size
        now_ts = float(timestamp_utc) if timestamp_utc is not None else time.time()
        dt = datetime.fromtimestamp(now_ts, tz=timezone.utc).astimezone()
        date_iso = dt.strftime("%Y-%m-%d %H:%M:%S")
        stamp = dt.strftime("%Y%m%d_%H%M%S_%f")
        token = secrets.token_hex(4)
        capture_id = f"pw_{stamp}_{token}"

        img_filename = f"{capture_id}.png"
        thumb_filename = f"{capture_id}_thumb.png"
        img_path = self.images_dir / img_filename
        thumb_path = self.thumbnails_dir / thumb_filename

        with self._lock:
            file_size = _atomic_save_pil_png(pil_rgb, img_path)
            thumb_pil = self._generate_thumbnail_pil(pil_rgb)
            _atomic_save_pil_png(thumb_pil, thumb_path)
            self._set_cached_thumb(capture_id, thumb_pil)

            resolved_ocr = (ocr_text or "").strip()
            if not resolved_ocr and self.enable_ocr_indexing and ocr_indexer is not None:
                try:
                    resolved_ocr = (ocr_indexer(pil_rgb) or "").strip()
                except Exception:
                    resolved_ocr = ""

            ocr_avail = bool(resolved_ocr)
            ext_str = str(external_save_path) if external_save_path is not None else ""
            entry = HistoryEntry(
                capture_id=capture_id,
                timestamp_utc=now_ts,
                date_iso=date_iso,
                image_path=str(img_path),
                thumbnail_path=str(thumb_path),
                external_save_path=ext_str,
                width=w,
                height=h,
                file_size_bytes=file_size,
                favorite=bool(favorite),
                title=title.strip(),
                ocr_available=ocr_avail,
                ocr_text=resolved_ocr if self.enable_ocr_indexing else "",
                capture_mode=(capture_mode or "region").strip(),
                schema_version=HISTORY_SCHEMA_VERSION,
            )

            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO captures (
                        capture_id, timestamp_utc, date_iso, image_path, thumbnail_path,
                        external_save_path, width, height, file_size_bytes, favorite,
                        title, ocr_available, ocr_text, capture_mode, schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.capture_id,
                        entry.timestamp_utc,
                        entry.date_iso,
                        entry.image_path,
                        entry.thumbnail_path,
                        entry.external_save_path,
                        entry.width,
                        entry.height,
                        entry.file_size_bytes,
                        1 if entry.favorite else 0,
                        entry.title,
                        1 if entry.ocr_available else 0,
                        entry.ocr_text,
                        entry.capture_mode,
                        entry.schema_version,
                    ),
                )
                if self._fts5_supported:
                    fname = Path(ext_str or entry.image_path).name
                    conn.execute(
                        "INSERT INTO captures_fts(capture_id, title, filename, date_iso, ocr_text) VALUES (?, ?, ?, ?, ?)",
                        (entry.capture_id, entry.title, fname, entry.date_iso, entry.ocr_text),
                    )
                conn.commit()

            self._set_cached_entry(entry)
            self._stats_dirty = True
            self.enforce_retention_limits()
            return entry

    def _set_cached_thumb(self, capture_id: str, pil_thumb: Image.Image) -> None:
        self._thumb_memory_cache[capture_id] = pil_thumb
        self._thumb_memory_cache.move_to_end(capture_id)
        while len(self._thumb_memory_cache) > self._thumb_cache_capacity:
            self._thumb_memory_cache.popitem(last=False)

    def load_thumbnail_pil(self, capture_id: str) -> Optional[Image.Image]:
        with self._lock:
            if capture_id in self._thumb_memory_cache:
                self._thumb_memory_cache.move_to_end(capture_id)
                return self._thumb_memory_cache[capture_id]

            entry = self.get_entry(capture_id)
            if entry is None:
                return None

            tpath = Path(entry.thumbnail_path) if entry.thumbnail_path else None
            if tpath is not None and tpath.is_file():
                try:
                    with Image.open(str(tpath)) as im:
                        thumb = im.convert("RGB")
                    self._set_cached_thumb(capture_id, thumb)
                    return thumb
                except Exception:
                    pass

            src_path = entry.resolved_image_path
            if src_path is not None and src_path.is_file():
                try:
                    with Image.open(str(src_path)) as src_im:
                        thumb = self._generate_thumbnail_pil(src_im.convert("RGB"))
                    if tpath is not None:
                        _atomic_save_pil_png(thumb, tpath)
                    self._set_cached_thumb(capture_id, thumb)
                    return thumb
                except Exception:
                    return None
            return None

    def load_full_image_pil(self, capture_id: str) -> Optional[Image.Image]:
        entry = self.get_entry(capture_id)
        if entry is None:
            return None
        src_path = entry.resolved_image_path
        if src_path is None or not src_path.is_file():
            return None
        try:
            with Image.open(str(src_path)) as im:
                return im.convert("RGB")
        except Exception:
            return None

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> HistoryEntry:
        return HistoryEntry(
            capture_id=str(row["capture_id"]),
            timestamp_utc=float(row["timestamp_utc"]),
            date_iso=str(row["date_iso"]),
            image_path=str(row["image_path"]),
            thumbnail_path=str(row["thumbnail_path"]),
            external_save_path=str(row["external_save_path"] or ""),
            width=int(row["width"]),
            height=int(row["height"]),
            file_size_bytes=int(row["file_size_bytes"]),
            favorite=bool(row["favorite"]),
            title=str(row["title"] or ""),
            ocr_available=bool(row["ocr_available"]),
            ocr_text=str(row["ocr_text"] or ""),
            capture_mode=str(row["capture_mode"] or "region"),
            schema_version=int(row["schema_version"] or HISTORY_SCHEMA_VERSION),
        )

    def get_entry(self, capture_id: str) -> Optional[HistoryEntry]:
        with self._lock:
            if capture_id in self._entry_memory_cache:
                self._entry_memory_cache.move_to_end(capture_id)
                return self._entry_memory_cache[capture_id]
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM captures WHERE capture_id = ?",
                    (capture_id,),
                ).fetchone()
                if row is None:
                    return None
                entry = self._row_to_entry(row)
                self._set_cached_entry(entry)
                return entry

    def update_title(self, capture_id: str, new_title: str) -> bool:
        clean = (new_title or "").strip()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE captures SET title = ? WHERE capture_id = ?",
                (clean, capture_id),
            )
            if cur.rowcount <= 0:
                return False
            if self._fts5_supported:
                conn.execute(
                    "UPDATE captures_fts SET title = ? WHERE capture_id = ?",
                    (clean, capture_id),
                )
            conn.commit()
            if capture_id in self._entry_memory_cache:
                self._entry_memory_cache[capture_id].title = clean
            return True

    def set_favorite(self, capture_id: str, favorite: bool) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE captures SET favorite = ? WHERE capture_id = ?",
                (1 if favorite else 0, capture_id),
            )
            conn.commit()
            if cur.rowcount > 0:
                if capture_id in self._entry_memory_cache:
                    self._entry_memory_cache[capture_id].favorite = bool(favorite)
                self._stats_dirty = True
                return True
            return False

    def update_ocr_text(self, capture_id: str, ocr_text: str) -> bool:
        clean = (ocr_text or "").strip()
        avail = 1 if clean else 0
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE captures SET ocr_available = ?, ocr_text = ? WHERE capture_id = ?",
                (avail, clean, capture_id),
            )
            if cur.rowcount <= 0:
                return False
            if self._fts5_supported:
                conn.execute(
                    "UPDATE captures_fts SET ocr_text = ? WHERE capture_id = ?",
                    (clean, capture_id),
                )
            conn.commit()
            if capture_id in self._entry_memory_cache:
                self._entry_memory_cache[capture_id].ocr_available = bool(avail)
                self._entry_memory_cache[capture_id].ocr_text = clean
            self._stats_dirty = True
            return True

    def enqueue_async_ocr_indexing(
        self,
        capture_id: str,
        image_source: Any,
        ocr_callable: Callable[[Image.Image], str],
    ) -> Optional[threading.Thread]:
        if self._shutdown_event.is_set() or not self.enable_ocr_indexing or not capture_id:
            return None
        try:
            pil_copy = _to_pil_rgb(image_source).copy()
        except Exception:
            return None

        with self._lock:
            active = next(
                (th for th in self._bg_ocr_threads
                 if th.is_alive() and th.name == f"PrismwakeHistoryOcr-{capture_id[-8:]}"),
                None,
            )
            if active is not None:
                return active
            self._ocr_job_states[capture_id] = "pending"

        def _worker() -> None:
            if not self._bg_ocr_semaphore.acquire(timeout=2.0):
                with self._lock:
                    self._ocr_job_states[capture_id] = "failed"
                return
            try:
                if self._shutdown_event.is_set():
                    return
                txt = (ocr_callable(pil_copy) or "").strip()
                if txt and not self._shutdown_event.is_set():
                    self.update_ocr_text(capture_id, txt)
                with self._lock:
                    self._ocr_job_states[capture_id] = "indexed" if txt else "empty"
            except Exception:
                with self._lock:
                    self._ocr_job_states[capture_id] = "failed"
            finally:
                self._bg_ocr_semaphore.release()

        t = threading.Thread(
            target=_worker,
            name=f"PrismwakeHistoryOcr-{capture_id[-8:]}",
            daemon=True,
        )
        with self._lock:
            self._bg_ocr_threads = [th for th in self._bg_ocr_threads if th.is_alive()]
            self._bg_ocr_threads.append(t)
        t.start()
        return t

    def get_ocr_job_state(self, capture_id: str) -> str:
        """Transient background OCR state; saved recognition lives in the capture row."""
        with self._lock:
            return self._ocr_job_states.get(capture_id, "not_started")

    def has_pending_ocr_jobs(self) -> bool:
        with self._lock:
            return any(state == "pending" for state in self._ocr_job_states.values())

    def wait_for_pending_ocr(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + max(0.05, float(timeout))
        with self._lock:
            threads = list(self._bg_ocr_threads)
        for th in threads:
            rem = max(0.0, deadline - time.monotonic())
            if th.is_alive():
                th.join(timeout=rem)
        with self._lock:
            self._bg_ocr_threads = [th for th in self._bg_ocr_threads if th.is_alive()]
            return len(self._bg_ocr_threads) == 0

    def shutdown(self, timeout: float = 1.0) -> None:
        self._shutdown_event.set()
        self.wait_for_pending_ocr(timeout=timeout)

    def compute_category_counts(self) -> Dict[str, int]:
        """Returns item counts for `all`, `favorites`, `recent`, and `with_text` in a single query."""
        cutoff = time.time() - (7 * 86400.0)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_cnt,
                    COALESCE(SUM(CASE WHEN favorite = 1 THEN 1 ELSE 0 END), 0) AS fav_cnt,
                    COALESCE(SUM(CASE WHEN timestamp_utc >= ? THEN 1 ELSE 0 END), 0) AS rec_cnt,
                    COALESCE(SUM(CASE WHEN ocr_available = 1 THEN 1 ELSE 0 END), 0) AS ocr_cnt
                FROM captures
                """,
                (cutoff,),
            ).fetchone()
            if row is None:
                return {"all": 0, "favorites": 0, "recent": 0, "recent_7d": 0, "with_text": 0, "with_ocr": 0}
            rec_v = int(row["rec_cnt"] or 0)
            ocr_v = int(row["ocr_cnt"] or 0)
            return {
                "all": int(row["total_cnt"] or 0),
                "favorites": int(row["fav_cnt"] or 0),
                "recent": rec_v,
                "recent_7d": rec_v,
                "with_text": ocr_v,
                "with_ocr": ocr_v,
            }

    def search_entries(
        self,
        query: str = "",
        *,
        filter_mode: str = "all",
        sort_by: str = "newest",
        limit: int = 500,
    ) -> List[HistoryEntry]:
        q = (query or "").strip()
        sort_clauses = {
            "newest": "c.timestamp_utc DESC",
            "oldest": "c.timestamp_utc ASC",
            "largest": "c.file_size_bytes DESC, c.timestamp_utc DESC",
            "smallest": "c.file_size_bytes ASC, c.timestamp_utc DESC",
            "favorites_first": "c.favorite DESC, c.timestamp_utc DESC",
        }
        order_sql = sort_clauses.get(sort_by, "c.timestamp_utc DESC")

        where_parts: List[str] = []
        params: List[Any] = []

        if filter_mode == "favorites":
            where_parts.append("c.favorite = 1")
        elif filter_mode == "with_text":
            where_parts.append("c.ocr_available = 1")
        elif filter_mode == "recent":
            cutoff = time.time() - (7 * 86400.0)
            where_parts.append("c.timestamp_utc >= ?")
            params.append(cutoff)

        with self._lock, self._connect() as conn:
            if q:
                like_pat = f"%{q}%"
                where_parts.append(
                    "(c.title LIKE ? OR c.date_iso LIKE ? OR c.image_path LIKE ? "
                    "OR c.external_save_path LIKE ? OR c.ocr_text LIKE ?)"
                )
                params.extend([like_pat, like_pat, like_pat, like_pat, like_pat])

            where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
            sql = f"SELECT c.* FROM captures c {where_sql} ORDER BY {order_sql} LIMIT ?"
            params.append(max(1, int(limit)))
            rows = conn.execute(sql, tuple(params)).fetchall()
            entries = [self._row_to_entry(r) for r in rows]
            for e in entries:
                self._set_cached_entry(e)
            return entries

    def _is_managed_path(self, candidate: Path) -> bool:
        try:
            resolved = candidate.resolve()
            img_root = self.images_dir.resolve()
            thumb_root = self.thumbnails_dir.resolve()
            return (img_root in resolved.parents) or (thumb_root in resolved.parents)
        except Exception:
            return False

    def delete_entries(self, capture_ids: Sequence[str]) -> int:
        ids = [str(cid) for cid in capture_ids if cid]
        if not ids:
            return 0

        deleted_count = 0
        with self._lock, self._connect() as conn:
            for cid in ids:
                row = conn.execute(
                    "SELECT image_path, thumbnail_path FROM captures WHERE capture_id = ?",
                    (cid,),
                ).fetchone()
                if row is None:
                    continue
                for col in ("image_path", "thumbnail_path"):
                    p_str = row[col]
                    if p_str:
                        p = Path(p_str)
                        if self._is_managed_path(p):
                            try:
                                p.unlink(missing_ok=True)
                            except Exception:
                                pass
                conn.execute("DELETE FROM captures WHERE capture_id = ?", (cid,))
                if self._fts5_supported:
                    conn.execute("DELETE FROM captures_fts WHERE capture_id = ?", (cid,))
                self._thumb_memory_cache.pop(cid, None)
                self._entry_memory_cache.pop(cid, None)
                deleted_count += 1
            conn.commit()
            self._stats_dirty = True
        return deleted_count

    def clear_history(self, keep_favorites: bool = False) -> int:
        with self._lock, self._connect() as conn:
            if keep_favorites:
                rows = conn.execute("SELECT capture_id FROM captures WHERE favorite = 0").fetchall()
            else:
                rows = conn.execute("SELECT capture_id FROM captures").fetchall()
            ids = [str(r["capture_id"]) for r in rows]
        return self.delete_entries(ids)

    def clear_thumbnail_cache(self) -> int:
        removed = 0
        with self._lock:
            self._thumb_memory_cache.clear()
            if self.thumbnails_dir.is_dir():
                for p in self.thumbnails_dir.glob("*_thumb.png"):
                    if self._is_managed_path(p):
                        try:
                            p.unlink(missing_ok=True)
                            removed += 1
                        except Exception:
                            pass
            self._stats_dirty = True
        return removed

    def enforce_retention_limits(self) -> int:
        removed_ids: List[str] = []
        with self._lock, self._connect() as conn:
            if self.max_age_days > 0:
                cutoff = time.time() - (self.max_age_days * 86400.0)
                old_rows = conn.execute(
                    "SELECT capture_id FROM captures WHERE favorite = 0 AND timestamp_utc < ?",
                    (cutoff,),
                ).fetchall()
                removed_ids.extend(str(r["capture_id"]) for r in old_rows)

        if removed_ids:
            self.delete_entries(removed_ids)
            removed_ids.clear()

        with self._lock, self._connect() as conn:
            all_rows = conn.execute(
                "SELECT capture_id, favorite, file_size_bytes FROM captures ORDER BY favorite ASC, timestamp_utc ASC"
            ).fetchall()
            excess_count = len(all_rows) - self.max_items
            if excess_count > 0:
                to_drop = [str(r["capture_id"]) for r in all_rows[:excess_count]]
                removed_ids.extend(to_drop)

        if removed_ids:
            self.delete_entries(removed_ids)
            removed_ids.clear()

        with self._lock, self._connect() as conn:
            max_bytes = int(self.max_storage_mb * 1024 * 1024)
            all_rows = conn.execute(
                "SELECT capture_id, file_size_bytes FROM captures ORDER BY favorite ASC, timestamp_utc ASC"
            ).fetchall()
            total_bytes = sum(int(r["file_size_bytes"]) for r in all_rows)
            idx = 0
            while total_bytes > max_bytes and idx < len(all_rows):
                total_bytes -= int(all_rows[idx]["file_size_bytes"])
                removed_ids.append(str(all_rows[idx]["capture_id"]))
                idx += 1

        if removed_ids:
            return self.delete_entries(removed_ids)
        return 0

    def compute_storage_stats(self) -> HistoryStorageStats:
        with self._lock:
            if not self._stats_dirty and self._cached_stats is not None:
                return self._cached_stats

            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_cnt,
                        COALESCE(SUM(CASE WHEN favorite = 1 THEN 1 ELSE 0 END), 0) AS fav_cnt,
                        COALESCE(SUM(CASE WHEN ocr_available = 1 THEN 1 ELSE 0 END), 0) AS ocr_cnt,
                        COALESCE(SUM(file_size_bytes), 0) AS img_bytes
                    FROM captures
                    """
                ).fetchone()
                total_items = int(row["total_cnt"] or 0) if row else 0
                fav_items = int(row["fav_cnt"] or 0) if row else 0
                ocr_items = int(row["ocr_cnt"] or 0) if row else 0
                img_bytes = int(row["img_bytes"] or 0) if row else 0

            thumb_bytes = 0
            if self.thumbnails_dir.is_dir():
                for p in self.thumbnails_dir.glob("*.png"):
                    try:
                        thumb_bytes += int(p.stat().st_size)
                    except Exception:
                        pass

            db_bytes = 0
            if self.db_path.is_file():
                try:
                    db_bytes = int(self.db_path.stat().st_size)
                except Exception:
                    pass

            stats = HistoryStorageStats(
                total_items=total_items,
                favorite_items=fav_items,
                ocr_indexed_items=ocr_items,
                managed_images_bytes=img_bytes,
                thumbnails_bytes=thumb_bytes,
                database_bytes=db_bytes,
                total_bytes=img_bytes + thumb_bytes + db_bytes,
                root_dir=self.root_dir,
            )
            self._cached_stats = stats
            self._stats_dirty = False
            return stats


# =============================================================================
# FRUTIGER AQUA GALLERY UI & SHARED DESIGN SYSTEM BRIDGE
# =============================================================================

_REGISTERED_TOOLKIT: Dict[str, Any] = {}


def register_history_aqua_toolkit(**components: Any) -> None:
    """Allows `Prismwake.py` to register its shared Frutiger Aqua components directly."""
    _REGISTERED_TOOLKIT.update(components)


def _resolve_prismwake_toolkit() -> Dict[str, Any]:
    """Resolves `AeroGelButton`, `AeroAnimationDirector`, `AquaOpticalFieldRenderer`, and glass painters."""
    if _REGISTERED_TOOLKIT:
        return _REGISTERED_TOOLKIT
    pw_mod = sys.modules.get("Prismwake")
    if pw_mod is not None and getattr(pw_mod, "HAS_QT", False):
        for name in (
            "AeroGelButton",
            "AeroAnimationDirector",
            "AquaOpticalFieldRenderer",
            "draw_frutiger_glass_base",
            "draw_frutiger_glass_Dynamic_Overlay",
            "draw_frutiger_glass_panel",
        ):
            val = getattr(pw_mod, name, None)
            if val is not None:
                _REGISTERED_TOOLKIT[name] = val
    return _REGISTERED_TOOLKIT


if HAS_QT:
    class _FallbackGelButton(QPushButton):
        """
        Standalone Frutiger Aqua 3D Gel Capsule Button used only when `HistoryWindow` is
        instantiated in isolation without `Prismwake` imported. When `Prismwake` is imported,
        `create_aqua_gel_button()` returns genuine `Prismwake.AeroGelButton` instances.
        """
        PALETTES = {
            "glass": (
                QColor(65, 165, 225, 165),
                QColor(22, 90, 150, 185),
                QColor(90, 225, 255, 205),
                QColor(185, 245, 255, 210),
            ),
            "aqua_active": (
                QColor(35, 185, 255, 240),
                QColor(0, 110, 215, 248),
                QColor(115, 255, 245, 255),
                QColor(235, 255, 255, 250),
            ),
            "emerald": (
                QColor(70, 225, 115, 238),
                QColor(14, 150, 58, 245),
                QColor(155, 255, 130, 255),
                QColor(220, 255, 220, 245),
            ),
            "sapphire": (
                QColor(55, 170, 255, 238),
                QColor(0, 95, 210, 248),
                QColor(110, 240, 255, 255),
                QColor(215, 250, 255, 245),
            ),
            "ruby": (
                QColor(255, 105, 95, 238),
                QColor(195, 28, 28, 245),
                QColor(255, 165, 135, 255),
                QColor(255, 225, 225, 240),
            ),
        }

        def __init__(self, text: str, variant: str = "glass", parent: Optional[QWidget] = None) -> None:
            super().__init__(text, parent)
            self.variant = variant
            self._hovered = False
            self._hover_progress: float = 0.0
            self._jelly_strain: float = 0.0
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setMinimumHeight(32)

        def reset_animation_state(self) -> None:
            self._hover_progress = 0.0
            self._jelly_strain = 0.0
            self.update()

        def paintEvent(self, _event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rc = QRectF(self.rect()).adjusted(2.5, 2.0, -2.5, -2.0)
            rad = rc.height() * 0.5
            pal_key = "aqua_active" if (self.isCheckable() and self.isChecked()) else self.variant
            top_c, mid_c, bot_c, bdr_c = self.PALETTES.get(pal_key, self.PALETTES["glass"])
            grad = QLinearGradient(rc.topLeft(), rc.bottomLeft())
            grad.setColorAt(0.0, top_c)
            grad.setColorAt(0.55, mid_c)
            grad.setColorAt(1.0, bot_c)
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(bdr_c, 1.3))
            painter.drawRoundedRect(rc, rad, rad)
            cap = QRectF(rc.left() + 3.0, rc.top() + 1.5, max(2.0, rc.width() - 6.0), rc.height() * 0.42)
            cgrad = QLinearGradient(cap.topLeft(), cap.bottomLeft())
            cgrad.setColorAt(0.0, QColor(255, 255, 255, 155))
            cgrad.setColorAt(1.0, QColor(255, 255, 255, 8))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(cgrad))
            painter.drawRoundedRect(cap, cap.height() * 0.5, cap.height() * 0.5)
            painter.setPen(QColor(255, 255, 255, 248 if self.isEnabled() else 120))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.drawText(rc, Qt.AlignmentFlag.AlignCenter, self.text())
            painter.end()


    def create_aqua_gel_button(
        text: str,
        *,
        variant: str = "glass",
        parent: Optional[QWidget] = None,
        checkable: bool = False,
        tooltip: str = "",
        min_height: int = 32,
    ) -> QPushButton:
        tk = _resolve_prismwake_toolkit()
        btn_cls = tk.get("AeroGelButton", _FallbackGelButton)
        btn = btn_cls(text, variant=variant, parent=parent)
        btn.setMinimumHeight(min_height)
        if checkable:
            btn.setCheckable(True)
        if tooltip:
            btn.setToolTip(tooltip)
        return btn


    class AquaGlassPanel(QFrame):
        """
        Translucent Frutiger Aqua glass container panel used for the Header Bar,
        Left Filter & Storage Sidebar, Center Gallery Well, Right Inspector Panel,
        and Recognized Text (OCR) Card.
        Caches its static glass base pixmap per size/theme/transparency so child
        widget updates only blit the dirty sub-rectangle.
        """

        def __init__(
            self,
            parent: Optional[QWidget] = None,
            *,
            radius: float = 16.0,
            tint_style: str = "aqua",
            deep_veil_alpha: int = 92,
        ) -> None:
            super().__init__(parent)
            self._radius = float(radius)
            self._tint_style = str(tint_style)
            self._deep_veil_alpha = int(deep_veil_alpha)
            self._cached_pix: Optional[QPixmap] = None
            self._cached_key: Any = None
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        def invalidate_glass_cache(self) -> None:
            self._cached_pix = None
            self._cached_key = None
            self.update()

        def resizeEvent(self, event: Any) -> None:
            self._cached_pix = None
            super().resizeEvent(event)

        def paintEvent(self, event: Any) -> None:
            w = max(1, self.width())
            h = max(1, self.height())
            tk = _resolve_prismwake_toolkit()
            director_cls = tk.get("AeroAnimationDirector")
            director = director_cls.instance() if director_cls is not None else None
            theme_key = getattr(director, "theme", "ocean_current") if director is not None else "ocean_current"
            trans_val = getattr(director, "transparency", 72) if director is not None else 72
            cache_key = (w, h, theme_key, trans_val, self._tint_style, self._deep_veil_alpha)

            if self._cached_pix is None or self._cached_key != cache_key:
                pm = QPixmap(w, h)
                pm.fill(Qt.GlobalColor.transparent)
                p = QPainter(pm)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                rc = QRectF(1.5, 1.5, float(w) - 3.0, float(h) - 3.0)
                draw_panel = tk.get("draw_frutiger_glass_panel")
                if draw_panel is not None and self._tint_style in ("aqua", "dialog"):
                    draw_panel(
                        p,
                        rc,
                        radius=self._radius,
                        frosted_pixmap=None,
                        tint_style=self._tint_style,
                        t_sec=0.0,
                        intensity_scale=0.0,
                    )
                    if self._deep_veil_alpha > 0:
                        vpath = QPainterPath()
                        vpath.addRoundedRect(rc.adjusted(1.5, 1.5, -1.5, -1.5), max(2.0, self._radius - 1.5), max(2.0, self._radius - 1.5))
                        p.fillPath(vpath, QColor(3, 18, 38, self._deep_veil_alpha))
                else:
                    th_spec = get_history_aqua_theme_spec(theme_key)
                    path = QPainterPath()
                    path.addRoundedRect(rc, self._radius, self._radius)
                    if self._tint_style == "well":
                        grad = QLinearGradient(rc.topLeft(), rc.bottomLeft())
                        grad.setColorAt(0.0, QColor(3, 14, 28, 228))
                        grad.setColorAt(1.0, QColor(5, 22, 44, 238))
                        p.fillPath(path, QBrush(grad))
                    else:
                        dt_r, dt_g, dt_b = th_spec["dialog_top_rgb"]
                        db_r, db_g, db_b = th_spec["dialog_bot_rgb"]
                        grad = QLinearGradient(rc.topLeft(), rc.bottomLeft())
                        grad.setColorAt(0.0, QColor(dt_r, dt_g, dt_b, 175))
                        grad.setColorAt(1.0, QColor(db_r, db_g, db_b, 195))
                        p.fillPath(path, QBrush(grad))
                    b_r, b_g, b_b = th_spec["border_rgb"]
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(QColor(b_r, b_g, b_b, 155), 1.2))
                    p.drawRoundedRect(rc, self._radius, self._radius)
                p.end()
                self._cached_pix = pm
                self._cached_key = cache_key

            painter = QPainter(self)
            dirty_rc = event.rect()
            if self._cached_pix is not None:
                painter.drawPixmap(dirty_rc, self._cached_pix, dirty_rc)
            painter.end()


    class AquaStorageMeterBar(QWidget):
        """Custom-painted Frutiger Aqua 3D Liquid Gel Capacity Meter Bar."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self._ratio: float = 0.0
            self._label_text: str = "0%"
            self.setFixedHeight(20)

        def set_usage(self, ratio: float, label_text: str = "") -> None:
            self._ratio = max(0.0, min(1.0, float(ratio)))
            self._label_text = str(label_text or f"{int(round(self._ratio * 100))}%")
            self.update()

        def paintEvent(self, _event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rc = QRectF(self.rect()).adjusted(1.0, 2.0, -1.0, -2.0)
            rad = rc.height() * 0.5

            # Recessed dark glass trough
            painter.setPen(QPen(QColor(95, 225, 255, 130), 1.1))
            painter.setBrush(QColor(3, 14, 28, 215))
            painter.drawRoundedRect(rc, rad, rad)

            if self._ratio > 0.005:
                fill_w = max(rc.height(), rc.width() * self._ratio)
                fill_rc = QRectF(rc.left() + 1.0, rc.top() + 1.0, min(rc.width() - 2.0, fill_w), rc.height() - 2.0)
                fill_rad = fill_rc.height() * 0.5
                fgrad = QLinearGradient(fill_rc.topLeft(), fill_rc.topRight())
                if self._ratio >= 0.88:
                    fgrad.setColorAt(0.0, QColor(255, 120, 80, 235))
                    fgrad.setColorAt(1.0, QColor(255, 65, 65, 245))
                else:
                    fgrad.setColorAt(0.0, QColor(0, 185, 255, 230))
                    fgrad.setColorAt(0.55, QColor(28, 235, 220, 240))
                    fgrad.setColorAt(1.0, QColor(85, 255, 175, 245))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(fgrad))
                painter.drawRoundedRect(fill_rc, fill_rad, fill_rad)

                # Upper cylindrical gloss highlight
                shine_rc = QRectF(fill_rc.left() + 2.0, fill_rc.top() + 1.0, max(2.0, fill_rc.width() - 4.0), fill_rc.height() * 0.45)
                sgrad = QLinearGradient(shine_rc.topLeft(), shine_rc.bottomLeft())
                sgrad.setColorAt(0.0, QColor(255, 255, 255, 165))
                sgrad.setColorAt(1.0, QColor(255, 255, 255, 10))
                painter.setBrush(QBrush(sgrad))
                painter.drawRoundedRect(shine_rc, shine_rc.height() * 0.5, shine_rc.height() * 0.5)

            painter.setPen(QColor(235, 252, 255, 245))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(rc, Qt.AlignmentFlag.AlignCenter, self._label_text)
            painter.end()


    class HistoryCardDelegate(QStyledItemDelegate):
        """
        Custom-painted Frutiger Aqua rounded glass screenshot card delegate for `HistoryWindow`.
        Supports both Grid Card mode (`view_mode="grid"`) and Compact List mode (`view_mode="list"`).
        Draws:
          - Layered translucent aqua glass card body with upper specular reflection arc
          - Hover lift + cyan aura and Selected luminous double electric-cyan rim
          - Dark recessed thumbnail well with crisp aspect-ratio-preserving thumbnail
          - Top-right Favorite Star badge (`★`) and top-left OCR indicator pill (`OCR`)
          - Capture title, formatted date, dimensions pill, and file size
        """

        ROLE_ENTRY_META = Qt.ItemDataRole.UserRole + 1
        ROLE_THUMB_PIXMAP = Qt.ItemDataRole.UserRole + 2

        def __init__(self, history_window: "HistoryWindow", parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self._win = history_window

        def sizeHint(self, _option: Any, _index: Any) -> QSize:
            if getattr(self._win, "_view_mode", "grid") == "list":
                vp_w = max(360, self._win.grid_list.viewport().width() - 18)
                return QSize(vp_w, 72)
            return QSize(218, 182)

        def paint(self, painter: QPainter, option: Any, index: Any) -> None:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            raw_rect = QRectF(option.rect)
            row_idx = index.row()
            cid = str(index.data(Qt.ItemDataRole.UserRole) or "")
            meta: Optional[HistoryEntry] = index.data(self.ROLE_ENTRY_META)
            if meta is None and cid:
                meta = self._win.get_cached_entry_meta(cid)

            # Never perform disk I/O or image decoding inside paint():
            # read only in-memory cached QPixmap or schedule asynchronous background decode.
            thumb_pm: Optional[QPixmap] = index.data(self.ROLE_THUMB_PIXMAP)
            if (thumb_pm is None or thumb_pm.isNull()) and cid:
                thumb_pm = self._win.get_cached_thumbnail_pixmap(cid)
                if thumb_pm is None or thumb_pm.isNull():
                    self._win.request_thumbnail_async(cid, item_row=row_idx, high_priority=True)

            is_selected = bool(option.state & QStyle.StateFlag.State_Selected) or (
                self._win.grid_list.currentRow() == row_idx
            )
            is_hovered = (getattr(self._win.grid_list, "_hovered_row", -1) == row_idx) or bool(
                option.state & QStyle.StateFlag.State_MouseOver
            )

            th_spec = get_history_aqua_theme_spec(getattr(self._win, "_aqua_theme", "ocean_current"))
            b_r, b_g, b_b = th_spec["border_rgb"]
            bi_r, bi_g, bi_b = th_spec["border_inner_rgb"]
            cb_r, cb_g, cb_b = th_spec["card_bg_rgb"]
            cs_r, cs_g, cs_b = th_spec["card_sel_rgb"]

            lift_y = -1.6 if (is_hovered and not is_selected) else 0.0
            card_rc = raw_rect.adjusted(5.0, 5.0 + lift_y, -5.0, -5.0 + lift_y)
            card_rad = 13.0

            # 1. Soft outer hover/selection aura glow
            if is_selected or is_hovered:
                glow_rc = card_rc.adjusted(-2.2, -2.0, 2.2, 2.4)
                glow_col = QColor(bi_r, bi_g, bi_b, 88 if is_selected else 48)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow_col)
                painter.drawRoundedRect(glow_rc, card_rad + 2.0, card_rad + 2.0)

            # 2. Translucent Frutiger Aqua glass card body
            body_grad = QLinearGradient(card_rc.topLeft(), card_rc.bottomLeft())
            if is_selected:
                body_grad.setColorAt(0.0, QColor(cs_r + 18, min(255, cs_g + 35), min(255, cs_b + 45), 228))
                body_grad.setColorAt(0.55, QColor(cs_r, cs_g, cs_b, 218))
                body_grad.setColorAt(1.0, QColor(cb_r, cb_g + 16, cb_b + 28, 232))
            elif is_hovered:
                body_grad.setColorAt(0.0, QColor(cb_r + 16, cb_g + 34, cb_b + 54, 214))
                body_grad.setColorAt(1.0, QColor(cb_r + 4, cb_g + 12, cb_b + 24, 224))
            else:
                body_grad.setColorAt(0.0, QColor(cb_r + 8, cb_g + 20, cb_b + 36, 198))
                body_grad.setColorAt(1.0, QColor(cb_r, cb_g, cb_b, 214))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(body_grad))
            painter.drawRoundedRect(card_rc, card_rad, card_rad)

            # 3. Upper curved glass specular sheen
            shine_h = min(28.0, card_rc.height() * 0.28)
            shine_rc = QRectF(card_rc.left() + 2.0, card_rc.top() + 1.5, max(4.0, card_rc.width() - 4.0), shine_h)
            sgrad = QLinearGradient(shine_rc.topLeft(), shine_rc.bottomLeft())
            sgrad.setColorAt(0.0, QColor(255, 255, 255, 78 if is_selected else (58 if is_hovered else 38)))
            sgrad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(QBrush(sgrad))
            painter.drawRoundedRect(shine_rc, card_rad - 2.0, card_rad - 2.0)

            view_mode = getattr(self._win, "_view_mode", "grid")
            title_str = meta.display_title if meta is not None else (index.data(Qt.ItemDataRole.DisplayRole) or "Capture")
            is_fav = bool(meta.favorite) if meta is not None else False
            has_ocr = bool(meta.ocr_text.strip()) if meta is not None else False
            w_px = int(meta.width) if meta is not None else 0
            h_px = int(meta.height) if meta is not None else 0
            kb = (meta.file_size_bytes / 1024.0) if meta is not None else 0.0
            date_short = (meta.date_iso[:16] if meta and meta.date_iso else "")

            if view_mode == "list":
                # Compact List Card Layout
                well_rc = QRectF(card_rc.left() + 8.0, card_rc.top() + 7.0, 96.0, card_rc.height() - 14.0)
                self._draw_thumbnail_well(painter, well_rc, thumb_pm, is_fav=False, has_ocr=has_ocr)

                tx_left = well_rc.right() + 12.0
                tx_w = max(80.0, card_rc.right() - tx_left - 84.0)
                f_title = QFont("Segoe UI", 10, QFont.Weight.Bold)
                painter.setFont(f_title)
                painter.setPen(QColor(244, 252, 255, 252))
                fm_t = QFontMetrics(f_title)
                elided_t = fm_t.elidedText(("★ " if is_fav else "") + title_str, Qt.TextElideMode.ElideRight if hasattr(Qt, "TextElideMode") else Qt.AlignmentFlag.AlignLeft, int(tx_w)) if hasattr(fm_t, "elidedText") else title_str[:42]
                painter.drawText(
                    QRectF(tx_left, card_rc.top() + 8.0, tx_w, 22.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    elided_t,
                )

                sub_str = f"{date_short}  •  {w_px}×{h_px} px  •  {kb:.1f} KB"
                if meta and meta.ocr_text:
                    snippet = " ".join(meta.ocr_text.splitlines())[:48]
                    sub_str += f"  •  “{snippet}”"
                painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
                painter.setPen(QColor(156, 232, 255, 230))
                painter.drawText(
                    QRectF(tx_left, card_rc.top() + 32.0, tx_w + 70.0, 20.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    sub_str,
                )
            else:
                # Grid Card Layout
                well_rc = QRectF(
                    card_rc.left() + 8.0,
                    card_rc.top() + 8.0,
                    card_rc.width() - 16.0,
                    card_rc.height() - 56.0,
                )
                self._draw_thumbnail_well(painter, well_rc, thumb_pm, is_fav=is_fav, has_ocr=has_ocr)

                # Title & Secondary Metadata Footer
                foot_top = well_rc.bottom() + 5.0
                foot_w = card_rc.width() - 16.0
                painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                painter.setPen(QColor(244, 252, 255, 252))
                short_title = title_str if len(title_str) <= 24 else (title_str[:22] + "…")
                painter.drawText(
                    QRectF(card_rc.left() + 8.0, foot_top, foot_w, 19.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    short_title,
                )

                date_day = date_short.split(" ")[0] if date_short else ""
                sub_line = f"{date_day} • {w_px}×{h_px}"
                painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
                painter.setPen(QColor(156, 232, 255, 225))
                painter.drawText(
                    QRectF(card_rc.left() + 8.0, foot_top + 19.0, foot_w, 17.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    sub_line,
                )

            # 4. Card glass border rim
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if is_selected:
                painter.setPen(QPen(QColor(230, 255, 255, 248), 2.1))
                painter.drawRoundedRect(card_rc, card_rad, card_rad)
                painter.setPen(QPen(QColor(bi_r, bi_g, bi_b, 210), 1.0))
                painter.drawRoundedRect(card_rc.adjusted(1.8, 1.8, -1.8, -1.8), card_rad - 1.5, card_rad - 1.5)
            elif is_hovered:
                painter.setPen(QPen(QColor(175, 248, 255, 225), 1.5))
                painter.drawRoundedRect(card_rc, card_rad, card_rad)
            else:
                painter.setPen(QPen(QColor(b_r, b_g, b_b, 128), 1.1))
                painter.drawRoundedRect(card_rc, card_rad, card_rad)

            painter.restore()

        def _draw_thumbnail_well(
            self,
            painter: QPainter,
            well_rc: QRectF,
            thumb_pm: Optional[QPixmap],
            *,
            is_fav: bool,
            has_ocr: bool,
        ) -> None:
            well_rad = 8.0
            painter.setPen(QPen(QColor(80, 215, 255, 95), 1.0))
            painter.setBrush(QColor(3, 14, 28, 235))
            painter.drawRoundedRect(well_rc, well_rad, well_rad)

            if thumb_pm is not None and not thumb_pm.isNull():
                avail_w = max(8.0, well_rc.width() - 8.0)
                avail_h = max(8.0, well_rc.height() - 8.0)
                pw = max(1.0, float(thumb_pm.width()))
                ph = max(1.0, float(thumb_pm.height()))
                scale = min(avail_w / pw, avail_h / ph)
                dw = pw * scale
                dh = ph * scale
                dx = well_rc.left() + (well_rc.width() - dw) * 0.5
                dy = well_rc.top() + (well_rc.height() - dh) * 0.5
                dst_rc = QRectF(dx, dy, dw, dh)
                painter.drawPixmap(dst_rc.toRect(), thumb_pm)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(255, 255, 255, 55), 0.9))
                painter.drawRect(dst_rc)
            else:
                painter.setPen(QColor(120, 205, 235, 165))
                painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
                painter.drawText(well_rc, Qt.AlignmentFlag.AlignCenter, "Preview")

            if has_ocr:
                ocr_rc = QRectF(well_rc.left() + 5.0, well_rc.top() + 5.0, 32.0, 16.0)
                painter.setPen(QPen(QColor(150, 248, 255, 195), 0.9))
                painter.setBrush(QColor(4, 38, 72, 215))
                painter.drawRoundedRect(ocr_rc, 5.0, 5.0)
                painter.setPen(QColor(195, 252, 255, 248))
                painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
                painter.drawText(ocr_rc, Qt.AlignmentFlag.AlignCenter, "OCR")

            if is_fav:
                star_rc = QRectF(well_rc.right() - 25.0, well_rc.top() + 5.0, 20.0, 20.0)
                painter.setPen(QPen(QColor(255, 235, 130, 225), 1.0))
                painter.setBrush(QColor(28, 22, 8, 215))
                painter.drawEllipse(star_rc)
                painter.setPen(QColor(255, 215, 55, 255))
                painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                painter.drawText(star_rc, Qt.AlignmentFlag.AlignCenter, "★")


    class HistoryGalleryListWidget(QListWidget):
        """Screenshot gallery list widget with hover-row tracking for smooth Aqua card highlights."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self._hovered_row: int = -1
            self.setMouseTracking(True)
            self.viewport().setMouseTracking(True)

        def mouseMoveEvent(self, event: Any) -> None:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            idx = self.indexAt(pos)
            new_row = idx.row() if (idx is not None and idx.isValid()) else -1
            if new_row != self._hovered_row:
                self._hovered_row = new_row
                self.viewport().update()
            super().mouseMoveEvent(event)

        def leaveEvent(self, event: Any) -> None:
            if self._hovered_row != -1:
                self._hovered_row = -1
                self.viewport().update()
            super().leaveEvent(event)


    class HistoryWindow(QDialog):
        """
        Dedicated Frutiger Aqua Screenshot History Gallery Window:
          - Top Header Bar: Title, live item count badge, instant debounced search bar (`Ctrl+F`),
            sort selector, Grid / Compact List view toggle, `New Capture`, and `Storage & Privacy Settings`.
          - Left Sidebar (`AquaGlassPanel`): Frutiger Aqua category filter pills (`All Captures`,
            `★ Favorites`, `Recent (7 Days)`, `Recognized Text`) with live counts, structured
            Storage & Privacy liquid meter card, and visually separated destructive actions.
          - Center Gallery (`AquaGlassPanel`): Custom-painted rounded Frutiger Aqua glass cards
            (`HistoryCardDelegate`) with lazy/cached thumbnails, hover lift, selection glow,
            and clean empty/no-results states.
          - Right Preview & Inspector Panel (`AquaGlassPanel`): Undistorted aspect-ratio screenshot
            preview well, capture metadata badges, Recognized Text (OCR) card, and logically
            grouped `AeroGelButton` actions.
        """

        reopenInEditorRequested = pyqtSignal(object, str)       # (PIL.Image, title)
        pinImageRequested = pyqtSignal(object, str)             # (PIL.Image, title)
        pinEntryRequested = pyqtSignal(object, str, str)        # (PIL.Image, title, capture_id)
        openSettingsRequested = pyqtSignal()
        newCaptureRequested = pyqtSignal()
        _previewDecodedSignal = pyqtSignal(int, str)
        _thumbDecodedSignal = pyqtSignal(int)

        INITIAL_VIEWPORT_THUMB_COUNT: int = 16
        THUMB_GUI_DRAIN_BATCH: int = 24
        THUMB_CACHE_CAPACITY: int = 300
        PREVIEW_CACHE_CAPACITY: int = 32

        def __init__(
            self,
            store: ScreenshotHistoryStore,
            *,
            ocr_runner: Optional[Callable[[Image.Image], str]] = None,
            aqua_theme: str = "ocean_current",
            animation_intensity: str = "medium",
            glass_transparency: int = 72,
            safe_mode: bool = False,
            disable_continuous_animations: bool = False,
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)
            self.store = store
            self._ocr_runner = ocr_runner
            self._current_filter: str = "all"
            self._view_mode: str = "grid"
            self._entries: List[HistoryEntry] = []
            self._last_opened_location: Optional[Path] = None

            self._aqua_theme_display: str = str(aqua_theme or "Bondi Blue")
            self._aqua_theme: str = normalize_history_aqua_theme(aqua_theme)
            self._animation_intensity: str = str(animation_intensity or "medium").strip().lower()
            gt_f = float(glass_transparency)
            self._glass_transparency_float: float = gt_f if gt_f <= 1.0 else (gt_f / 100.0)
            self._glass_transparency: int = max(10, min(95, int(round(gt_f * 100.0)) if gt_f <= 1.0 else int(gt_f)))
            self._safe_mode: bool = bool(safe_mode)
            self._disable_continuous: bool = bool(disable_continuous_animations)
            self.current_entries: List[HistoryEntry] = []
            self.category_counts: Dict[str, int] = {"all": 0, "favorites": 0, "recent": 0, "recent_7d": 0, "with_text": 0, "with_ocr": 0}
            self.empty_state_kind: str = "empty"

            # Bounded LRU QPixmap caches & genuine asynchronous off-thread decode state
            self._gui_thread_id: int = threading.get_ident()
            self._closing: bool = False
            self._async_lock = threading.Lock()
            self._entry_meta_by_id: Dict[str, HistoryEntry] = {}

            self._thumb_pixmap_cache: "OrderedDict[str, QPixmap]" = OrderedDict()
            self._preview_pixmap_cache: "OrderedDict[str, QPixmap]" = OrderedDict()
            self._gallery_load_gen: int = 0
            self._pending_thumb_rows: List[Tuple[int, str, int]] = []
            self._inflight_thumb_cids: set[str] = set()
            self._completed_thumb_decodes: List[Tuple[int, int, str, int, int, Optional[bytes]]] = []
            self._thumb_worker_thread: Optional[threading.Thread] = None
            self._thumb_worker_event = threading.Event()
            self._explicit_visible_range: Optional[Tuple[int, int]] = None

            self._current_preview_full_pixmap: Optional[QPixmap] = None
            self._current_preview_is_thumbnail: bool = False
            self._current_preview_stage: str = "empty"
            self._current_preview_cid: Optional[str] = None
            self._preview_load_gen: int = 0
            self._pending_preview_request: Optional[Tuple[int, str]] = None
            self._preview_worker_busy: bool = False
            self._completed_preview_decodes: List[Tuple[int, str, int, int, Optional[bytes]]] = []
            self._preview_worker_thread: Optional[threading.Thread] = None
            self._preview_worker_event = threading.Event()
            self._preview_decode_delay_sec: float = 0.0

            # Verification & telemetry counters
            self._paint_sync_decode_count: int = 0
            self._bg_thumb_decode_count: int = 0
            self._last_thumb_decode_thread_id: Optional[int] = None
            self._last_thumb_pixmap_thread_id: Optional[int] = None
            self._thumb_decode_order: List[str] = []
            self._bg_preview_decode_count: int = 0
            self._cancelled_preview_decode_count: int = 0
            self._ignored_stale_preview_count: int = 0
            self._last_preview_decode_thread_id: Optional[int] = None
            self._last_preview_gui_update_thread_id: Optional[int] = None

            # Window background optical water & glass cache
            self._cached_base_pix: Optional[QPixmap] = None
            self._cached_water_frame: Optional[QPixmap] = None
            self._cached_dlg_scale: float = -1.0
            self._cached_theme_key: str = ""
            self._cached_trans_val: int = -1
            self._water_dirty: bool = True
            self._wave_paths = (
                QPainterPath(),
                QPainterPath(),
                QPainterPath(),
                QPainterPath(),
            )
            tk = _resolve_prismwake_toolkit()
            opt_cls = tk.get("AquaOpticalFieldRenderer")
            self._optical_renderer = (
                opt_cls(grid_w=176, grid_h=56, aspect=2.4) if opt_cls is not None else None
            )

            self.setWindowTitle("Prismwake — Screenshot History Gallery")
            self.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.WindowTitleHint
                | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowMinMaxButtonsHint
                | Qt.WindowType.WindowCloseButtonHint
            )
            self.resize(1180, 740)
            self.setMinimumSize(860, 520)

            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.setInterval(150)
            self._search_timer.timeout.connect(self.refresh_gallery)

            # Only poll while History is visible and recognition is in progress.
            self._ocr_ui_timer = QTimer(self)
            self._ocr_ui_timer.setInterval(350)
            self._ocr_ui_timer.timeout.connect(self._poll_history_ocr_status)
            self._ocr_copy_target: Optional[str] = None

            self._thumb_batch_timer = QTimer(self)
            self._thumb_batch_timer.setInterval(10)
            self._thumb_batch_timer.timeout.connect(self._drain_async_decodes_on_gui_thread)
            self._previewDecodedSignal.connect(self._on_preview_decoded_signal)
            self._thumbDecodedSignal.connect(self._on_thumb_decoded_signal)

            self._build_ui()
            self.apply_aqua_theme_and_config(
                aqua_theme=self._aqua_theme_display,
                animation_intensity=self._animation_intensity,
                glass_transparency=self._glass_transparency_float,
                safe_mode=self._safe_mode,
                disable_continuous_animations=self._disable_continuous,
            )
            self.refresh_gallery()

        @property
        def selected_capture_id(self) -> Optional[str]:
            entry = self._current_entry()
            return entry.capture_id if entry is not None else None

        @selected_capture_id.setter
        def selected_capture_id(self, cid: Optional[str]) -> None:
            if not cid:
                return
            target = str(cid)
            for i in range(self.grid_list.count()):
                it = self.grid_list.item(i)
                if it is not None and str(it.data(Qt.ItemDataRole.UserRole) or "") == target:
                    # QListWidget.setCurrentRow() defaults to NoUpdate on real Qt.
                    # With ExtendedSelection that leaves previously selected rows
                    # active, so the inspector can display the *wrong* screenshot.
                    # Programmatic selection must replace (not extend) selection.
                    selected = self.grid_list.selectedItems()
                    if (
                        self.grid_list.currentRow() == i
                        and len(selected) == 1
                        and selected[0] is it
                        and self._current_preview_cid == target
                    ):
                        return
                    was_blocked = self.grid_list.blockSignals(True)
                    try:
                        self.grid_list.clearSelection()
                        self.grid_list.setCurrentRow(i)
                        it.setSelected(True)
                    finally:
                        self.grid_list.blockSignals(was_blocked)
                    # Run once with stable selection, not during intermediate
                    # deselection or when a stale row is still selected.
                    if not was_blocked:
                        self._on_selection_changed()
                    return

        def _build_ui(self) -> None:
            self._apply_stylesheet()

            outer_layout = QVBoxLayout(self)
            outer_layout.setContentsMargins(14, 12, 14, 14)
            outer_layout.setSpacing(10)

            # -----------------------------------------------------------------
            # 1. Top Header Bar (`self.header_panel`)
            # -----------------------------------------------------------------
            self.header_panel = AquaGlassPanel(self, radius=16.0, tint_style="aqua", deep_veil_alpha=72)
            self.header_panel.setMinimumHeight(54)
            hdr_layout = QHBoxLayout(self.header_panel)
            hdr_layout.setContentsMargins(16, 8, 16, 8)
            hdr_layout.setSpacing(10)

            self.header_title_lbl = QLabel("<b>✦ Prismwake History</b>")
            self.header_title_lbl.setStyleSheet("font-size: 16px; color: #EFFFFF; background: transparent;")
            hdr_layout.addWidget(self.header_title_lbl)

            self.header_count_badge = QLabel("0 captures")
            self.header_count_badge.setStyleSheet(
                "font-size: 11px; font-weight: 600; color: #9CF6FF; "
                "background: rgba(4, 34, 68, 175); border: 1px solid rgba(110, 235, 255, 130); "
                "border-radius: 10px; padding: 3px 10px;"
            )
            hdr_layout.addWidget(self.header_count_badge)

            hdr_layout.addSpacing(6)

            self.search_edit = QLineEdit(self.header_panel)
            self.search_edit.setPlaceholderText(
                "Search captures by title, date, filename, or recognized OCR text... (Ctrl+F)"
            )
            self.search_edit.setMinimumWidth(260)
            self.search_edit.textChanged.connect(self._on_search_text_edited)
            hdr_layout.addWidget(self.search_edit, 1)

            self.clear_search_btn = create_aqua_gel_button(
                "✕",
                variant="glass",
                parent=self.header_panel,
                tooltip="Clear search query",
                min_height=30,
            )
            self.clear_search_btn.setFixedWidth(36)
            self.clear_search_btn.setVisible(False)
            self.clear_search_btn.clicked.connect(lambda _c=False: self.set_search_query(""))
            hdr_layout.addWidget(self.clear_search_btn)

            sort_lbl = QLabel("Sort:")
            sort_lbl.setStyleSheet("font-weight: 600; color: #C8F6FF; background: transparent;")
            hdr_layout.addWidget(sort_lbl)

            self.sort_combo = QComboBox(self.header_panel)
            self.sort_combo.addItem("Newest First", "newest")
            self.sort_combo.addItem("Oldest First", "oldest")
            self.sort_combo.addItem("Largest File", "largest")
            self.sort_combo.addItem("Smallest File", "smallest")
            self.sort_combo.addItem("Favorites First", "favorites_first")
            self.sort_combo.currentIndexChanged.connect(lambda _i: self.refresh_gallery())
            hdr_layout.addWidget(self.sort_combo)

            self.view_grid_btn = create_aqua_gel_button(
                "⊞ Grid",
                variant="glass",
                parent=self.header_panel,
                checkable=True,
                tooltip="Grid Card View",
                min_height=30,
            )
            self.view_grid_btn.setChecked(True)
            self.view_grid_btn.clicked.connect(lambda _c=False: self.set_view_mode("grid"))
            hdr_layout.addWidget(self.view_grid_btn)

            self.view_list_btn = create_aqua_gel_button(
                "☰ List",
                variant="glass",
                parent=self.header_panel,
                checkable=True,
                tooltip="Compact List View",
                min_height=30,
            )
            self.view_list_btn.clicked.connect(lambda _c=False: self.set_view_mode("list"))
            hdr_layout.addWidget(self.view_list_btn)

            self.new_capture_btn = create_aqua_gel_button(
                "✦ New Capture",
                variant="emerald",
                parent=self.header_panel,
                tooltip="Start a new screenshot capture",
                min_height=32,
            )
            self.new_capture_btn.clicked.connect(self.newCaptureRequested.emit)
            hdr_layout.addWidget(self.new_capture_btn)

            self.settings_btn = create_aqua_gel_button(
                "Storage & Privacy Settings",
                variant="glass",
                parent=self.header_panel,
                tooltip="Open Prismwake Settings directly to Screenshot History & Storage Privacy",
                min_height=32,
            )
            self.settings_btn.clicked.connect(self.openSettingsRequested.emit)
            hdr_layout.addWidget(self.settings_btn)

            outer_layout.addWidget(self.header_panel)

            # -----------------------------------------------------------------
            # 2. Main 3-Region Body Layout
            # -----------------------------------------------------------------
            body_layout = QHBoxLayout()
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(10)

            # 2A. Left Filter & Storage Sidebar (`self.sidebar_panel`)
            self.sidebar_panel = AquaGlassPanel(self, radius=16.0, tint_style="dialog", deep_veil_alpha=96)
            self.sidebar_panel.setFixedWidth(234)
            side_layout = QVBoxLayout(self.sidebar_panel)
            side_layout.setContentsMargins(12, 12, 12, 12)
            side_layout.setSpacing(7)

            cat_hdr = QLabel("<b>LIBRARY VIEWS</b>")
            cat_hdr.setStyleSheet("font-size: 11px; letter-spacing: 1px; color: #8CEEFF; background: transparent;")
            side_layout.addWidget(cat_hdr)

            self.category_specs = [
                ("All Captures", "all"),
                ("★ Favorites", "favorites"),
                ("Recent (7 Days)", "recent"),
                ("With Recognized Text", "with_text"),
            ]
            self.category_buttons: Dict[str, QPushButton] = {}
            self.nav_list = QListWidget(self.sidebar_panel)
            for label, code in self.category_specs:
                it = QListWidgetItem(label)
                it.setData(Qt.ItemDataRole.UserRole, code)
                self.nav_list.addItem(it)

                pill_btn = create_aqua_gel_button(
                    label,
                    variant="glass",
                    parent=self.sidebar_panel,
                    checkable=True,
                    tooltip=f"Filter gallery: {label}",
                    min_height=34,
                )
                pill_btn.setChecked(code == "all")
                pill_btn.clicked.connect(lambda _c=False, m=code: self.set_filter_mode(m))
                side_layout.addWidget(pill_btn)
                self.category_buttons[code] = pill_btn

            self.nav_list.setCurrentRow(0)
            self.nav_list.currentRowChanged.connect(self._on_nav_changed)
            self.nav_list.setVisible(False)

            side_layout.addSpacing(4)

            # Structured Storage & Privacy Meter Card
            self.storage_card = AquaGlassPanel(self.sidebar_panel, radius=13.0, tint_style="well", deep_veil_alpha=0)
            st_layout = QVBoxLayout(self.storage_card)
            st_layout.setContentsMargins(10, 9, 10, 9)
            st_layout.setSpacing(5)

            st_hdr_row = QHBoxLayout()
            st_title = QLabel("<b>STORAGE & PRIVACY</b>")
            st_title.setStyleSheet("font-size: 10px; color: #8CEEFF; background: transparent;")
            st_hdr_row.addWidget(st_title)
            self.privacy_badge_lbl = QLabel("Saved/Copied")
            self.privacy_badge_lbl.setStyleSheet(
                "font-size: 10px; font-weight: 700; color: #B8FFF0; "
                "background: rgba(0, 140, 160, 110); border-radius: 6px; padding: 1px 6px;"
            )
            st_hdr_row.addWidget(self.privacy_badge_lbl)
            st_layout.addLayout(st_hdr_row)

            self.storage_meter_bar = AquaStorageMeterBar(self.storage_card)
            st_layout.addWidget(self.storage_meter_bar)

            self.storage_label = QLabel("")
            self.storage_label.setWordWrap(True)
            self.storage_label.setStyleSheet("font-size: 11px; color: #C8F2FF; background: transparent;")
            st_layout.addWidget(self.storage_label)
            side_layout.addWidget(self.storage_card)

            side_layout.addStretch(1)

            # Visually separated Destructive History Actions
            clean_hdr = QLabel("<b>HISTORY CLEANUP</b>")
            clean_hdr.setStyleSheet("font-size: 10px; color: #FFB8B8; background: transparent;")
            side_layout.addWidget(clean_hdr)

            self.delete_sel_btn = create_aqua_gel_button(
                "Delete Selected",
                variant="ruby",
                parent=self.sidebar_panel,
                tooltip="Delete the selected screenshot(s) from History (Delete key)",
                min_height=31,
            )
            self.delete_sel_btn.clicked.connect(lambda _c=False: self.delete_selected_items(confirm=True))
            side_layout.addWidget(self.delete_sel_btn)

            self.clear_non_fav_btn = create_aqua_gel_button(
                "Clear Non-Favorites",
                variant="glass",
                parent=self.sidebar_panel,
                tooltip="Remove all non-favorite captures while keeping ★ Favorites",
                min_height=31,
            )
            self.clear_non_fav_btn.clicked.connect(
                lambda _c=False: self.prompt_clear_history(confirm=True, keep_favorites=True)
            )
            side_layout.addWidget(self.clear_non_fav_btn)

            self.clear_btn = create_aqua_gel_button(
                "Clear History...",
                variant="ruby",
                parent=self.sidebar_panel,
                tooltip="Delete all managed screenshots in History",
                min_height=31,
            )
            self.clear_btn.clicked.connect(lambda _c=False: self.prompt_clear_history(confirm=True))
            side_layout.addWidget(self.clear_btn)

            body_layout.addWidget(self.sidebar_panel)

            # 2B & 2C. Center Gallery & Right Inspector Splitter
            self.main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
            self.main_splitter.setHandleWidth(8)
            self.main_splitter.setChildrenCollapsible(False)

            # 2B. Center Screenshot Gallery (`self.gallery_panel`)
            self.gallery_panel = AquaGlassPanel(self, radius=16.0, tint_style="dialog", deep_veil_alpha=104)
            gal_layout = QVBoxLayout(self.gallery_panel)
            gal_layout.setContentsMargins(10, 10, 10, 10)
            gal_layout.setSpacing(8)

            self.grid_list = HistoryGalleryListWidget(self.gallery_panel)
            self.card_delegate = HistoryCardDelegate(self, self.grid_list)
            self.grid_list.setItemDelegate(self.card_delegate)
            self.grid_list.setViewMode(QListWidget.ViewMode.IconMode)
            self.grid_list.setIconSize(QSize(196, 114))
            self.grid_list.setGridSize(QSize(222, 186))
            self.grid_list.setResizeMode(QListWidget.ResizeMode.Adjust)
            self.grid_list.setMovement(QListWidget.Movement.Static)
            self.grid_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.grid_list.setUniformItemSizes(True)
            self.grid_list.setWordWrap(True)
            self.grid_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.grid_list.customContextMenuRequested.connect(self._show_context_menu)
            self.grid_list.itemSelectionChanged.connect(self._on_selection_changed)
            self.grid_list.itemDoubleClicked.connect(lambda _it: self.reopen_current_in_editor())
            try:
                sb = self.grid_list.verticalScrollBar()
                if sb is not None and hasattr(sb, "valueChanged"):
                    sb.valueChanged.connect(lambda _v: self._prioritize_visible_thumbnails())
            except Exception:
                pass
            gal_layout.addWidget(self.grid_list, 1)

            # Clean Empty / No-Results State Card inside Gallery
            self.empty_state_card = AquaGlassPanel(self.gallery_panel, radius=14.0, tint_style="well", deep_veil_alpha=0)
            emp_layout = QVBoxLayout(self.empty_state_card)
            emp_layout.setContentsMargins(24, 24, 24, 24)
            emp_layout.setSpacing(8)
            self.empty_title_lbl = QLabel("<b>No Captures in History Yet</b>")
            self.empty_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.empty_title_lbl.setStyleSheet("font-size: 15px; color: #9CF6FF; background: transparent;")
            emp_layout.addWidget(self.empty_title_lbl)

            self.empty_desc_lbl = QLabel(
                "Saved, copied, pinned, or OCR-recognized screenshots will appear here automatically."
            )
            self.empty_desc_lbl.setWordWrap(True)
            self.empty_desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.empty_desc_lbl.setStyleSheet("font-size: 12px; color: #CBEFFF; background: transparent;")
            emp_layout.addWidget(self.empty_desc_lbl)

            emp_btn_row = QHBoxLayout()
            emp_btn_row.addStretch(1)
            self.reset_filters_btn = create_aqua_gel_button(
                "Reset Search & Filters",
                variant="sapphire",
                parent=self.empty_state_card,
                tooltip="Clear search query and return to All Captures",
                min_height=32,
            )
            self.reset_filters_btn.clicked.connect(self._reset_search_and_filters)
            emp_btn_row.addWidget(self.reset_filters_btn)
            emp_btn_row.addStretch(1)
            emp_layout.addLayout(emp_btn_row)
            self.empty_state_card.setVisible(False)
            gal_layout.addWidget(self.empty_state_card)

            self.main_splitter.addWidget(self.gallery_panel)

            # 2C. Right Preview & Actions Inspector Panel (`self.preview_panel`)
            self.preview_panel = AquaGlassPanel(self, radius=16.0, tint_style="dialog", deep_veil_alpha=96)
            self.inspector_panel = self.preview_panel
            self.list_widget = self.grid_list
            self.preview_panel.setMinimumWidth(346)
            prev_layout = QVBoxLayout(self.preview_panel)
            prev_layout.setContentsMargins(12, 12, 12, 12)
            prev_layout.setSpacing(8)

            self.preview_title = QLabel("<b>Select a capture</b>")
            self.preview_title.setWordWrap(True)
            self.preview_title.setStyleSheet("font-size: 14px; color: #9EF6FF; background: transparent;")
            prev_layout.addWidget(self.preview_title)

            # Recessed dark glass preview well preserving screenshot aspect ratio
            self.preview_well = AquaGlassPanel(self.preview_panel, radius=12.0, tint_style="well", deep_veil_alpha=0)
            well_layout = QVBoxLayout(self.preview_well)
            well_layout.setContentsMargins(6, 6, 6, 6)
            self.preview_img_lbl = QLabel(self.preview_well)
            self.preview_img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_img_lbl.setMinimumSize(300, 190)
            self.preview_img_lbl.setStyleSheet("background: transparent; color: #9EDFFF; font-size: 12px;")
            well_layout.addWidget(self.preview_img_lbl, 1)
            prev_layout.addWidget(self.preview_well, 2)

            self.meta_label = QLabel("")
            self.meta_label.setWordWrap(True)
            self.meta_label.setStyleSheet(
                "font-size: 11px; color: #D4F6FF; background: rgba(4, 24, 48, 165); "
                "border: 1px solid rgba(95, 225, 255, 105); border-radius: 9px; padding: 6px 8px;"
            )
            prev_layout.addWidget(self.meta_label)

            # Recognized Text (OCR) Glass Card
            self.ocr_card = AquaGlassPanel(self.preview_panel, radius=12.0, tint_style="well", deep_veil_alpha=0)
            ocr_layout = QVBoxLayout(self.ocr_card)
            ocr_layout.setContentsMargins(8, 7, 8, 8)
            ocr_layout.setSpacing(5)

            ocr_hdr_row = QHBoxLayout()
            ocr_hdr_lbl = QLabel("<b>Recognized Text (OCR)</b>")
            ocr_hdr_lbl.setStyleSheet("font-size: 11px; color: #98F4FF; background: transparent;")
            ocr_hdr_row.addWidget(ocr_hdr_lbl)
            ocr_hdr_row.addStretch(1)
            self.ocr_status_badge = QLabel("Not indexed")
            self.ocr_status_badge.setStyleSheet("font-size: 10px; color: #9CE8FF; background: transparent;")
            ocr_hdr_row.addWidget(self.ocr_status_badge)
            self.btn_run_ocr = create_aqua_gel_button(
                "Run OCR",
                variant="glass",
                parent=self.ocr_card,
                tooltip="Recognize text from this screenshot without changing the image",
                min_height=25,
            )
            self.btn_run_ocr.clicked.connect(lambda _c=False: self.run_current_ocr())
            ocr_hdr_row.addWidget(self.btn_run_ocr)
            ocr_layout.addLayout(ocr_hdr_row)

            self.ocr_preview = QPlainTextEdit(self.ocr_card)
            self.ocr_preview.setReadOnly(True)
            self.ocr_preview.setPlaceholderText("No recognized text indexed for this capture yet.")
            self.ocr_preview.setMinimumHeight(68)
            ocr_layout.addWidget(self.ocr_preview, 1)
            prev_layout.addWidget(self.ocr_card, 1)

            # Logically Grouped Frutiger Aqua Gel Action Buttons
            # Primary Row: Pin, Reopen in Editor, Copy Image
            act_row1 = QHBoxLayout()
            act_row1.setSpacing(6)
            self.btn_pin = create_aqua_gel_button(
                "Pin",
                variant="sapphire",
                parent=self.preview_panel,
                tooltip="Pin this screenshot to the desktop (or focus if already pinned)",
                min_height=32,
            )
            self.btn_pin.clicked.connect(lambda _c=False: self.pin_current_entry())
            act_row1.addWidget(self.btn_pin)

            self.btn_edit = create_aqua_gel_button(
                "Reopen in Editor",
                variant="emerald",
                parent=self.preview_panel,
                tooltip="Reopen this screenshot in the Prismwake annotation editor",
                min_height=32,
            )
            self.btn_edit.clicked.connect(lambda _c=False: self.reopen_current_in_editor())
            act_row1.addWidget(self.btn_edit)

            self.btn_copy_img = create_aqua_gel_button(
                "Copy Image",
                variant="sapphire",
                parent=self.preview_panel,
                tooltip="Copy full-resolution screenshot image to clipboard",
                min_height=32,
            )
            self.btn_copy_img.clicked.connect(lambda _c=False: self.copy_current_image())
            act_row1.addWidget(self.btn_copy_img)
            prev_layout.addLayout(act_row1)

            # Secondary Row 1: Favorite, Copy Text, Save As...
            act_row2 = QHBoxLayout()
            act_row2.setSpacing(6)
            self.btn_fav = create_aqua_gel_button(
                "★ Favorite",
                variant="glass",
                parent=self.preview_panel,
                tooltip="Toggle ★ Favorite status (protected from automatic retention cleanup)",
                min_height=31,
            )
            self.btn_fav.clicked.connect(lambda _c=False: self.toggle_current_favorite())
            act_row2.addWidget(self.btn_fav)

            self.btn_copy_txt = create_aqua_gel_button(
                "Copy Text",
                variant="glass",
                parent=self.preview_panel,
                tooltip="Copy recognized OCR text (or run background OCR if not indexed yet)",
                min_height=31,
            )
            self.btn_copy_txt.clicked.connect(lambda _c=False: self.copy_current_text())
            act_row2.addWidget(self.btn_copy_txt)

            self.btn_save_as = create_aqua_gel_button(
                "Save As...",
                variant="glass",
                parent=self.preview_panel,
                tooltip="Export a copy of this screenshot to a chosen folder",
                min_height=31,
            )
            self.btn_save_as.clicked.connect(lambda _c=False: self.save_current_as())
            act_row2.addWidget(self.btn_save_as)
            prev_layout.addLayout(act_row2)

            # Secondary Row 2 + Visually Separated Destructive Delete
            act_row3 = QHBoxLayout()
            act_row3.setSpacing(6)
            self.btn_rename = create_aqua_gel_button(
                "Rename",
                variant="glass",
                parent=self.preview_panel,
                tooltip="Set or edit a custom searchable title for this screenshot",
                min_height=31,
            )
            self.btn_rename.clicked.connect(lambda _c=False: self.rename_current_entry())
            act_row3.addWidget(self.btn_rename)

            self.btn_folder = create_aqua_gel_button(
                "Open Location",
                variant="glass",
                parent=self.preview_panel,
                tooltip="Reveal screenshot file in Explorer / file manager",
                min_height=31,
            )
            self.btn_folder.clicked.connect(lambda _c=False: self.open_current_file_location())
            act_row3.addWidget(self.btn_folder)

            self.btn_del = create_aqua_gel_button(
                "Delete",
                variant="ruby",
                parent=self.preview_panel,
                tooltip="Delete selected screenshot from History (Delete key)",
                min_height=31,
            )
            self.btn_del.clicked.connect(lambda _c=False: self.delete_selected_items(confirm=True))
            act_row3.addWidget(self.btn_del)
            prev_layout.addLayout(act_row3)

            self.main_splitter.addWidget(self.preview_panel)
            self.main_splitter.setSizes([560, 360])
            body_layout.addWidget(self.main_splitter, 1)
            outer_layout.addLayout(body_layout, 1)

            # Keyboard shortcuts
            del_sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
            del_sc.activated.connect(lambda: self.delete_selected_items(confirm=True))
            find_sc = QShortcut(QKeySequence("Ctrl+F"), self)
            find_sc.activated.connect(self.search_edit.setFocus)

        def _apply_stylesheet(self) -> None:
            th_spec = get_history_aqua_theme_spec(self._aqua_theme)
            b_r, b_g, b_b = th_spec["border_rgb"]
            self.setStyleSheet(
                f"""
                QDialog {{
                    background: #06182E;
                    color: #EAF8FF;
                    font-family: 'Segoe UI', sans-serif;
                }}
                QLabel {{
                    color: #E2F7FF;
                    font-size: 12px;
                }}
                QLineEdit, QComboBox, QPlainTextEdit {{
                    background-color: rgba(4, 18, 36, 218);
                    color: #F4FCFF;
                    border: 1px solid rgba({b_r}, {b_g}, {b_b}, 155);
                    border-radius: 9px;
                    padding: 6px 10px;
                    font-size: 12px;
                    selection-background-color: rgba(0, 195, 255, 165);
                }}
                QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{
                    border: 1.5px solid rgba(165, 248, 255, 235);
                    background-color: rgba(6, 24, 48, 235);
                }}
                QListWidget {{
                    background: transparent;
                    border: none;
                    outline: none;
                }}
                QSplitter::handle {{
                    background: rgba({b_r}, {b_g}, {b_b}, 45);
                    border-radius: 3px;
                }}
                QScrollBar:vertical {{
                    background: rgba(4, 16, 32, 150);
                    width: 10px;
                    margin: 2px;
                    border-radius: 5px;
                }}
                QScrollBar::handle:vertical {{
                    background: rgba({b_r}, {b_g}, {b_b}, 145);
                    min-height: 28px;
                    border-radius: 4px;
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                    height: 0px;
                }}
                """
            )

        # -----------------------------------------------------------------
        # Live Theme, Animation Intensity & Lifecycle Management
        # -----------------------------------------------------------------
        def apply_aqua_theme_and_config(
            self,
            *,
            aqua_theme: Optional[str] = None,
            animation_intensity: Optional[str] = None,
            glass_transparency: Optional[int] = None,
            safe_mode: Optional[bool] = None,
            disable_continuous_animations: Optional[bool] = None,
        ) -> None:
            if aqua_theme is not None:
                self._aqua_theme_display = str(aqua_theme)
                self._aqua_theme = normalize_history_aqua_theme(aqua_theme)
            if animation_intensity is not None:
                self._animation_intensity = str(animation_intensity).strip().lower()
            if glass_transparency is not None:
                gt_f = float(glass_transparency)
                self._glass_transparency_float = gt_f if gt_f <= 1.0 else (gt_f / 100.0)
                self._glass_transparency = max(10, min(95, int(round(gt_f * 100.0)) if gt_f <= 1.0 else int(gt_f)))
            if safe_mode is not None:
                self._safe_mode = bool(safe_mode)
            if disable_continuous_animations is not None:
                self._disable_continuous = bool(disable_continuous_animations)

            tk = _resolve_prismwake_toolkit()
            director_cls = tk.get("AeroAnimationDirector")
            if director_cls is not None:
                director = director_cls.instance()
                director.set_theme(self._aqua_theme)
                director.set_transparency(self._glass_transparency)
                eff_int = "off" if (self._safe_mode or self._disable_continuous) else self._animation_intensity
                director.set_intensity(eff_int)

            self._apply_stylesheet()
            self._cached_base_pix = None
            self._water_dirty = True
            for panel in (
                self.header_panel,
                self.sidebar_panel,
                self.storage_card,
                self.gallery_panel,
                self.empty_state_card,
                self.preview_panel,
                self.preview_well,
                self.ocr_card,
            ):
                panel.invalidate_glass_cache()
            self.grid_list.viewport().update()
            self.update()

        def on_animation_tick(self) -> None:
            if not self.isVisible() or self.isMinimized():
                return
            self._water_dirty = True
            self.update()

        def on_animations_disabled(self) -> None:
            self._water_dirty = True
            for child in self.findChildren(QWidget):
                if hasattr(child, "reset_animation_state"):
                    child.reset_animation_state()
            if self.isVisible():
                self.update()

        def on_transparency_changed(self) -> None:
            tk = _resolve_prismwake_toolkit()
            director_cls = tk.get("AeroAnimationDirector")
            if director_cls is not None:
                director = director_cls.instance()
                self._aqua_theme = normalize_history_aqua_theme(getattr(director, "theme", self._aqua_theme))
                self._glass_transparency = int(getattr(director, "transparency", self._glass_transparency))
            self._apply_stylesheet()
            self._cached_base_pix = None
            self._water_dirty = True
            for panel in (
                self.header_panel,
                self.sidebar_panel,
                self.storage_card,
                self.gallery_panel,
                self.empty_state_card,
                self.preview_panel,
                self.preview_well,
                self.ocr_card,
            ):
                panel.invalidate_glass_cache()
            if self.isVisible():
                self.grid_list.viewport().update()
                self.update()

        def cleanup_resources(self) -> None:
            self._closing = True
            self._search_timer.stop()
            self._ocr_ui_timer.stop()
            self._thumb_batch_timer.stop()
            with self._async_lock:
                self._preview_load_gen += 1
                self._gallery_load_gen += 1
                self._pending_preview_request = None
                self._pending_thumb_rows.clear()
                self._inflight_thumb_cids.clear()
                self._completed_preview_decodes.clear()
                self._completed_thumb_decodes.clear()
            self._preview_worker_event.set()
            self._thumb_worker_event.set()
            for th in (self._preview_worker_thread, self._thumb_worker_thread):
                if th is not None and th.is_alive() and th is not threading.current_thread():
                    th.join(timeout=0.15)
            tk = _resolve_prismwake_toolkit()
            director_cls = tk.get("AeroAnimationDirector")
            if director_cls is not None:
                director_cls.instance().unregister_surface(self)
            for child in self.findChildren(QWidget):
                if hasattr(child, "reset_animation_state"):
                    child.reset_animation_state()
            self._cached_base_pix = None
            self._cached_water_frame = None
            if self._optical_renderer is not None and hasattr(self._optical_renderer, "clear_backdrop"):
                self._optical_renderer.clear_backdrop()

        def showEvent(self, event: Any) -> None:
            self._closing = False
            self._water_dirty = True
            super().showEvent(event)
            tk = _resolve_prismwake_toolkit()
            director_cls = tk.get("AeroAnimationDirector")
            if director_cls is not None:
                director = director_cls.instance()
                director.register_surface(self)
                director.notify_visibility_changed()
            self._prioritize_visible_thumbnails()
            self._refresh_ocr_panel()

        def hideEvent(self, event: Any) -> None:
            self._ocr_ui_timer.stop()
            self._thumb_batch_timer.stop()
            self.on_animations_disabled()
            super().hideEvent(event)
            tk = _resolve_prismwake_toolkit()
            director_cls = tk.get("AeroAnimationDirector")
            if director_cls is not None:
                director_cls.instance().notify_visibility_changed()

        def closeEvent(self, event: Any) -> None:
            self.cleanup_resources()
            super().closeEvent(event)

        def resizeEvent(self, event: Any) -> None:
            self._cached_base_pix = None
            self._water_dirty = True
            super().resizeEvent(event)
            if self._view_mode == "list":
                self.grid_list.viewport().update()
            self._prioritize_visible_thumbnails()
            self._rescale_active_preview_pixmap()

        def paintEvent(self, event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            w = max(1, self.width())
            h = max(1, self.height())
            rect = QRectF(self.rect()).adjusted(4.0, 4.0, -4.0, -4.0)

            tk = _resolve_prismwake_toolkit()
            director_cls = tk.get("AeroAnimationDirector")
            director = director_cls.instance() if director_cls is not None else None
            eff_scale = (
                0.0
                if (self._safe_mode or self._disable_continuous)
                else (float(director.scale) if director is not None else 0.0)
            )
            t_sec = float(director.elapsed_seconds()) if (director is not None and eff_scale > 0.0) else 0.0
            theme_key = getattr(director, "theme", self._aqua_theme) if director is not None else self._aqua_theme
            trans_val = int(getattr(director, "transparency", self._glass_transparency)) if director is not None else self._glass_transparency

            if (
                self._cached_base_pix is None
                or self._cached_base_pix.size() != self.size()
                or self._cached_theme_key != theme_key
                or self._cached_trans_val != trans_val
            ):
                base_pix = QPixmap(w, h)
                base_pix.fill(Qt.GlobalColor.transparent)
                bp = QPainter(base_pix)
                bp.setRenderHint(QPainter.RenderHint.Antialiasing)
                draw_base = tk.get("draw_frutiger_glass_base")
                if draw_base is not None:
                    draw_base(bp, rect, radius=18.0, frosted_pixmap=None, tint_style="dialog")
                else:
                    th_spec = get_history_aqua_theme_spec(theme_key)
                    dt_r, dt_g, dt_b = th_spec["dialog_top_rgb"]
                    db_r, db_g, db_b = th_spec["dialog_bot_rgb"]
                    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                    g.setColorAt(0.0, QColor(dt_r, dt_g, dt_b, 235))
                    g.setColorAt(1.0, QColor(db_r, db_g, db_b, 245))
                    bp.fillRect(rect, QBrush(g))
                veil_path = QPainterPath()
                veil_path.addRoundedRect(rect, 18.0, 18.0)
                bp.fillPath(veil_path, QColor(3, 20, 44, 96))
                bp.end()
                self._cached_base_pix = base_pix
                self._cached_theme_key = theme_key
                self._cached_trans_val = trans_val
                self._water_dirty = True

            if (
                self._water_dirty
                or self._cached_water_frame is None
                or self._cached_water_frame.size() != self.size()
                or self._cached_dlg_scale != eff_scale
            ):
                if self._cached_water_frame is None or self._cached_water_frame.size() != self.size():
                    self._cached_water_frame = QPixmap(w, h)
                self._cached_water_frame.fill(Qt.GlobalColor.transparent)
                fp = QPainter(self._cached_water_frame)
                fp.setRenderHint(QPainter.RenderHint.Antialiasing)
                fp.drawPixmap(0, 0, self._cached_base_pix)

                draw_dyn = tk.get("draw_frutiger_glass_Dynamic_Overlay")
                if draw_dyn is not None:
                    opt_qimg: Optional[QImage] = None
                    if eff_scale > 0.0 and self._optical_renderer is not None:
                        op_f = float(getattr(director, "opacity_factor", 0.42))
                        rgba_arr = self._optical_renderer.synthesize_rgba_field(
                            t_sec=t_sec,
                            intensity_scale=eff_scale,
                            opacity_factor=op_f,
                        )
                        gh, gw, _ = rgba_arr.shape
                        opt_qimg = QImage(
                            rgba_arr.data, gw, gh, gw * 4, QImage.Format.Format_RGBA8888
                        )
                    draw_dyn(
                        fp,
                        rect,
                        radius=18.0,
                        t_sec=t_sec,
                        intensity_scale=eff_scale,
                        wave_paths=self._wave_paths if eff_scale > 0.0 else None,
                        optical_qimage=opt_qimg,
                    )
                fp.end()
                self._cached_dlg_scale = eff_scale
                self._water_dirty = False

            if self._cached_water_frame is not None:
                dirty_rc = event.rect()
                painter.drawPixmap(dirty_rc, self._cached_water_frame, dirty_rc)
            painter.end()

        # -----------------------------------------------------------------
        # Asynchronous Thumbnail & Full-Preview Decoding + Bounded LRU Caches
        # -----------------------------------------------------------------
        @staticmethod
        def _pil_to_rgba_buffer(pil_img: Image.Image) -> Tuple[int, int, bytes]:
            rgba = pil_img.convert("RGBA")
            return rgba.width, rgba.height, rgba.tobytes("raw", "RGBA")

        @staticmethod
        def _rgba_bytes_to_qpixmap(width: int, height: int, rgba_bytes: bytes) -> QPixmap:
            qimg = QImage(rgba_bytes, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
            return QPixmap.fromImage(qimg)

        @classmethod
        def _pil_to_qpixmap(cls, pil_img: Image.Image) -> QPixmap:
            w, h, data = cls._pil_to_rgba_buffer(pil_img)
            return cls._rgba_bytes_to_qpixmap(w, h, data)

        def get_cached_entry_meta(self, capture_id: str) -> Optional[HistoryEntry]:
            if not capture_id:
                return None
            return self._entry_meta_by_id.get(capture_id)

        def get_cached_thumbnail_pixmap(self, capture_id: str) -> Optional[QPixmap]:
            """Pure in-memory LRU lookup for gallery thumbnails (safe inside paint())."""
            if not capture_id:
                return None
            pm = self._thumb_pixmap_cache.get(capture_id)
            if pm is not None:
                self._thumb_pixmap_cache.move_to_end(capture_id)
            return pm

        def _cache_thumb_pixmap(self, capture_id: str, pm: QPixmap) -> None:
            self._thumb_pixmap_cache[capture_id] = pm
            self._thumb_pixmap_cache.move_to_end(capture_id)
            while len(self._thumb_pixmap_cache) > self.THUMB_CACHE_CAPACITY:
                self._thumb_pixmap_cache.popitem(last=False)

        def _cache_preview_pixmap(self, capture_id: str, pm: QPixmap) -> None:
            self._preview_pixmap_cache[capture_id] = pm
            self._preview_pixmap_cache.move_to_end(capture_id)
            while len(self._preview_pixmap_cache) > self.PREVIEW_CACHE_CAPACITY:
                self._preview_pixmap_cache.popitem(last=False)

        def _load_thumbnail_pixmap_immediate(self, capture_id: str) -> Optional[QPixmap]:
            """Load or retrieve cached thumbnail on the GUI thread for instant selection preview."""
            cached = self.get_cached_thumbnail_pixmap(capture_id)
            if cached is not None and not cached.isNull():
                return cached
            thumb_pil = self.store.load_thumbnail_pil(capture_id)
            if thumb_pil is None:
                return None
            pm = self._pil_to_qpixmap(thumb_pil)
            self._last_thumb_pixmap_thread_id = threading.get_ident()
            self._cache_thumb_pixmap(capture_id, pm)
            return pm

        def ensure_thumbnail_pixmap(self, capture_id: str, *, item_row: int = -1) -> Optional[QPixmap]:
            """Return cached thumbnail QPixmap if present; otherwise schedule async decode."""
            pm = self.get_cached_thumbnail_pixmap(capture_id)
            if pm is not None and not pm.isNull():
                return pm
            self.request_thumbnail_async(capture_id, item_row=item_row, high_priority=True)
            return None

        def set_visible_row_range(self, start_row: int, end_row: int) -> None:
            """Explicitly set the visible gallery row range and re-prioritize pending thumbnails."""
            s = max(0, int(start_row))
            e = max(s, int(end_row))
            self._explicit_visible_range = (s, e)
            self._prioritize_visible_thumbnails()

        def _get_visible_row_range(self) -> Tuple[int, int]:
            total = self.grid_list.count()
            if total <= 0:
                return (0, 0)
            if self._explicit_visible_range is not None:
                s, e = self._explicit_visible_range
                return (max(0, min(total - 1, s)), max(0, min(total - 1, e)))
            try:
                vp_rect = self.grid_list.viewport().rect()
                vis_rows: List[int] = []
                if vp_rect.width() > 0 and vp_rect.height() > 0:
                    for r in range(total):
                        it = self.grid_list.item(r)
                        if it is not None:
                            rc = self.grid_list.visualItemRect(it)
                            if rc.isValid() and rc.intersects(vp_rect):
                                vis_rows.append(r)
                if vis_rows:
                    return (min(vis_rows), max(vis_rows))
                sb = self.grid_list.verticalScrollBar()
                if sb is not None and sb.maximum() > 0 and sb.value() > 0:
                    ratio = float(sb.value()) / float(max(1, sb.maximum()))
                    start_r = max(0, min(total - 1, int(round(ratio * max(0, total - self.INITIAL_VIEWPORT_THUMB_COUNT)))))
                    return (start_r, min(total - 1, start_r + self.INITIAL_VIEWPORT_THUMB_COUNT - 1))
            except Exception:
                pass
            return (0, min(total - 1, self.INITIAL_VIEWPORT_THUMB_COUNT - 1))

        def request_thumbnail_async(
            self,
            capture_id: str,
            *,
            item_row: int = -1,
            high_priority: bool = False,
        ) -> None:
            """Enqueue a capture_id for asynchronous off-GUI-thread thumbnail decoding."""
            if not capture_id or self._closing:
                return
            if capture_id in self._thumb_pixmap_cache:
                return
            gen = self._gallery_load_gen
            with self._async_lock:
                if capture_id in self._inflight_thumb_cids:
                    return
                for idx, (r_i, c_i, g_i) in enumerate(self._pending_thumb_rows):
                    if c_i == capture_id and g_i == gen:
                        if high_priority and idx > 0:
                            item_tup = self._pending_thumb_rows.pop(idx)
                            self._pending_thumb_rows.insert(0, (item_row if item_row >= 0 else item_tup[0], capture_id, gen))
                        return
                entry_tup = (item_row, capture_id, gen)
                if high_priority:
                    self._pending_thumb_rows.insert(0, entry_tup)
                else:
                    self._pending_thumb_rows.append(entry_tup)
            self._ensure_thumb_worker_running()
            if not self._thumb_batch_timer.isActive():
                self._thumb_batch_timer.start()

        def _prioritize_visible_thumbnails(self) -> None:
            vis_start, vis_end = self._get_visible_row_range()
            with self._async_lock:
                if not self._pending_thumb_rows:
                    return
                vis_bucket: List[Tuple[int, str, int]] = []
                off_bucket: List[Tuple[int, str, int]] = []
                for row_idx, cid, gen in self._pending_thumb_rows:
                    if vis_start <= row_idx <= vis_end:
                        vis_bucket.append((row_idx, cid, gen))
                    else:
                        off_bucket.append((row_idx, cid, gen))
                vis_bucket.sort(key=lambda t: t[0])
                self._pending_thumb_rows = vis_bucket + off_bucket
            self._ensure_thumb_worker_running()
            if not self._thumb_batch_timer.isActive():
                self._thumb_batch_timer.start()

        def _ensure_thumb_worker_running(self) -> None:
            if self._closing:
                return
            if self._thumb_worker_thread is None or not self._thumb_worker_thread.is_alive():
                self._thumb_worker_thread = threading.Thread(
                    target=self._thumb_decode_worker_loop,
                    name="PrismwakeHistoryThumbWorker",
                    daemon=True,
                )
                self._thumb_worker_thread.start()
            self._thumb_worker_event.set()

        def _thumb_decode_worker_loop(self) -> None:
            while not self._closing:
                item_tup: Optional[Tuple[int, str, int]] = None
                with self._async_lock:
                    if self._pending_thumb_rows:
                        item_tup = self._pending_thumb_rows.pop(0)
                        self._inflight_thumb_cids.add(item_tup[1])
                    else:
                        self._thumb_worker_event.clear()
                if item_tup is None:
                    self._thumb_worker_event.wait(timeout=0.05)
                    with self._async_lock:
                        if not self._pending_thumb_rows:
                            return
                    continue

                row_idx, cid, gen = item_tup
                try:
                    if self._closing or gen != self._gallery_load_gen:
                        continue
                    pil_img = self.store.load_thumbnail_pil(cid)
                    if self._closing or gen != self._gallery_load_gen:
                        continue
                    self._last_thumb_decode_thread_id = threading.get_ident()
                    self._bg_thumb_decode_count += 1
                    self._thumb_decode_order.append(cid)
                    if pil_img is not None:
                        w, h, rgba_bytes = self._pil_to_rgba_buffer(pil_img)
                        with self._async_lock:
                            self._completed_thumb_decodes.append((gen, row_idx, cid, w, h, rgba_bytes))
                        try:
                            self._thumbDecodedSignal.emit(gen)
                        except Exception:
                            pass
                finally:
                    with self._async_lock:
                        self._inflight_thumb_cids.discard(cid)

        def _ensure_preview_worker_running(self) -> None:
            if self._closing:
                return
            if self._preview_worker_thread is None or not self._preview_worker_thread.is_alive():
                self._preview_worker_thread = threading.Thread(
                    target=self._preview_decode_worker_loop,
                    name="PrismwakeHistoryPreviewWorker",
                    daemon=True,
                )
                self._preview_worker_thread.start()
            self._preview_worker_event.set()

        def _start_async_full_preview_load(self, capture_id: str, req_gen: int) -> None:
            if not capture_id or self._closing:
                return
            with self._async_lock:
                if self._pending_preview_request is not None and self._pending_preview_request[0] != req_gen:
                    self._cancelled_preview_decode_count += 1
                self._pending_preview_request = (req_gen, capture_id)
            self._ensure_preview_worker_running()
            if not self._thumb_batch_timer.isActive():
                self._thumb_batch_timer.start()

        def _preview_decode_worker_loop(self) -> None:
            while not self._closing:
                req: Optional[Tuple[int, str]] = None
                with self._async_lock:
                    if self._pending_preview_request is not None:
                        req = self._pending_preview_request
                        self._pending_preview_request = None
                        self._preview_worker_busy = True
                    else:
                        self._preview_worker_busy = False
                        self._preview_worker_event.clear()
                if req is None:
                    self._preview_worker_event.wait(timeout=0.05)
                    with self._async_lock:
                        if self._pending_preview_request is None:
                            self._preview_worker_busy = False
                            return
                    continue

                req_gen, cid = req
                try:
                    if self._closing or req_gen != self._preview_load_gen:
                        with self._async_lock:
                            self._cancelled_preview_decode_count += 1
                        continue

                    delay_rem = float(getattr(self, "_preview_decode_delay_sec", 0.0) or 0.0)
                    while delay_rem > 0.0 and not self._closing:
                        step = min(0.005, delay_rem)
                        time.sleep(step)
                        delay_rem -= step
                        if req_gen != self._preview_load_gen:
                            break

                    if self._closing or req_gen != self._preview_load_gen:
                        with self._async_lock:
                            self._cancelled_preview_decode_count += 1
                        continue

                    self._last_preview_decode_thread_id = threading.get_ident()
                    self._bg_preview_decode_count += 1
                    pil_img = self.store.load_full_image_pil(cid)
                    if self._closing:
                        continue
                    if req_gen != self._preview_load_gen:
                        with self._async_lock:
                            self._cancelled_preview_decode_count += 1
                            # Also queue stale entry so GUI-thread stale guard is exercised if drained
                            if pil_img is not None:
                                w, h, raw = self._pil_to_rgba_buffer(pil_img)
                                self._completed_preview_decodes.append((req_gen, cid, w, h, raw))
                        try:
                            self._previewDecodedSignal.emit(req_gen, cid)
                        except Exception:
                            pass
                        continue

                    if pil_img is not None:
                        w, h, rgba_bytes = self._pil_to_rgba_buffer(pil_img)
                        with self._async_lock:
                            self._completed_preview_decodes.append((req_gen, cid, w, h, rgba_bytes))
                    else:
                        with self._async_lock:
                            self._completed_preview_decodes.append((req_gen, cid, 0, 0, None))
                    try:
                        self._previewDecodedSignal.emit(req_gen, cid)
                    except Exception:
                        pass
                finally:
                    with self._async_lock:
                        if self._pending_preview_request is None:
                            self._preview_worker_busy = False

        def _on_preview_decoded_signal(self, _req_gen: int, _cid: str) -> None:
            self._drain_completed_preview_decodes()

        def _on_thumb_decoded_signal(self, _gen: int) -> None:
            self._drain_completed_thumb_decodes()

        def _drain_completed_preview_decodes(self) -> None:
            if self._closing or threading.get_ident() != self._gui_thread_id:
                return
            with self._async_lock:
                if not self._completed_preview_decodes:
                    return
                items = list(self._completed_preview_decodes)
                self._completed_preview_decodes.clear()

            for req_gen, cid, w, h, rgba_bytes in items:
                if self._closing or req_gen != self._preview_load_gen or self.selected_capture_id != cid:
                    self._ignored_stale_preview_count += 1
                    continue
                if rgba_bytes is None or w <= 0 or h <= 0:
                    if self._current_preview_full_pixmap is None:
                        self._current_preview_stage = "missing"
                        self.preview_img_lbl.clear()
                        self.preview_img_lbl.setText("Image file missing on disk")
                    continue
                full_pm = self._rgba_bytes_to_qpixmap(w, h, rgba_bytes)
                self._last_preview_gui_update_thread_id = threading.get_ident()
                self._cache_preview_pixmap(cid, full_pm)
                self._current_preview_full_pixmap = full_pm
                self._current_preview_is_thumbnail = False
                self._current_preview_stage = "full"
                self._current_preview_cid = cid
                self._rescale_active_preview_pixmap()

        def _drain_completed_thumb_decodes(self) -> None:
            if self._closing or threading.get_ident() != self._gui_thread_id:
                return
            with self._async_lock:
                if not self._completed_thumb_decodes:
                    return
                batch = self._completed_thumb_decodes[: self.THUMB_GUI_DRAIN_BATCH]
                self._completed_thumb_decodes = self._completed_thumb_decodes[self.THUMB_GUI_DRAIN_BATCH :]

            updated_any = False
            for gen, row_idx, cid, w, h, rgba_bytes in batch:
                if self._closing or gen != self._gallery_load_gen or rgba_bytes is None or w <= 0 or h <= 0:
                    continue
                pm = self._rgba_bytes_to_qpixmap(w, h, rgba_bytes)
                self._last_thumb_pixmap_thread_id = threading.get_ident()
                self._cache_thumb_pixmap(cid, pm)
                target_item = None
                if 0 <= row_idx < self.grid_list.count():
                    cand = self.grid_list.item(row_idx)
                    if cand is not None and str(cand.data(Qt.ItemDataRole.UserRole) or "") == cid:
                        target_item = cand
                if target_item is None:
                    for r in range(self.grid_list.count()):
                        cand = self.grid_list.item(r)
                        if cand is not None and str(cand.data(Qt.ItemDataRole.UserRole) or "") == cid:
                            target_item = cand
                            break
                if target_item is not None:
                    target_item.setData(HistoryCardDelegate.ROLE_THUMB_PIXMAP, pm)
                    target_item.setIcon(QIcon(pm))
                    updated_any = True
                if cid == self.selected_capture_id and self._current_preview_full_pixmap is None:
                    self._current_preview_full_pixmap = pm
                    self._current_preview_is_thumbnail = True
                    self._current_preview_stage = "thumbnail"
                    self._rescale_active_preview_pixmap()

            if updated_any:
                self.grid_list.viewport().update()

        def _drain_async_decodes_on_gui_thread(self) -> None:
            if self._closing:
                self._thumb_batch_timer.stop()
                return
            self._drain_completed_preview_decodes()
            self._drain_completed_thumb_decodes()
            with self._async_lock:
                has_more = bool(
                    self._pending_thumb_rows
                    or self._inflight_thumb_cids
                    or self._completed_thumb_decodes
                    or self._pending_preview_request is not None
                    or self._preview_worker_busy
                    or self._completed_preview_decodes
                )
            if not has_more:
                self._thumb_batch_timer.stop()

        def _process_next_thumbnail_batch(self) -> None:
            self._drain_async_decodes_on_gui_thread()

        def wait_for_async_preview(self, timeout: float = 2.0) -> bool:
            """Wait for pending background full-resolution preview decode and apply on GUI thread."""
            deadline = time.perf_counter() + max(0.05, float(timeout))
            while time.perf_counter() < deadline:
                self._drain_completed_preview_decodes()
                app = QApplication.instance()
                if app is not None:
                    app.processEvents()
                with self._async_lock:
                    busy = (
                        self._pending_preview_request is not None
                        or self._preview_worker_busy
                        or bool(self._completed_preview_decodes)
                    )
                if not busy and self._current_preview_stage in ("full", "missing", "empty"):
                    return self._current_preview_stage == "full"
                time.sleep(0.005)
            self._drain_completed_preview_decodes()
            return self._current_preview_stage == "full"

        def wait_for_async_thumbnails(self, timeout: float = 2.0) -> int:
            """Wait for pending background gallery thumbnail decodes and apply on GUI thread."""
            deadline = time.perf_counter() + max(0.05, float(timeout))
            while time.perf_counter() < deadline:
                self._drain_completed_thumb_decodes()
                app = QApplication.instance()
                if app is not None:
                    app.processEvents()
                with self._async_lock:
                    busy = bool(
                        self._pending_thumb_rows
                        or self._inflight_thumb_cids
                        or self._completed_thumb_decodes
                    )
                if not busy:
                    break
                time.sleep(0.005)
            self._drain_completed_thumb_decodes()
            return len(self._thumb_pixmap_cache)

        # -----------------------------------------------------------------
        # Filtering, Sorting, Searching & View Modes
        # -----------------------------------------------------------------
        def _on_search_text_edited(self, text: str) -> None:
            self.clear_search_btn.setVisible(bool(str(text or "").strip()))
            self._search_timer.start()

        def _reset_search_and_filters(self) -> List[HistoryEntry]:
            self._search_timer.stop()
            self.search_edit.blockSignals(True)
            self.search_edit.setText("")
            self.search_edit.blockSignals(False)
            self.clear_search_btn.setVisible(False)
            return self.set_filter_mode("all")

        def set_search_query(self, query: str) -> List[HistoryEntry]:
            self._search_timer.stop()
            clean = str(query or "")
            self.search_edit.blockSignals(True)
            self.search_edit.setText(clean)
            self.search_edit.blockSignals(False)
            self.clear_search_btn.setVisible(bool(clean.strip()))
            return self.refresh_gallery()

        def set_filter_mode(self, mode: str) -> List[HistoryEntry]:
            target = str(mode or "all").strip().lower()
            if target not in ("all", "favorites", "recent", "with_text"):
                target = "all"
            self._current_filter = target
            for code, btn in self.category_buttons.items():
                btn.blockSignals(True)
                btn.setChecked(code == target)
                btn.blockSignals(False)
                btn.update()
            for i in range(self.nav_list.count()):
                it = self.nav_list.item(i)
                if it is not None and str(it.data(Qt.ItemDataRole.UserRole) or "") == target:
                    self.nav_list.blockSignals(True)
                    self.nav_list.setCurrentRow(i)
                    self.nav_list.blockSignals(False)
                    break
            return self.refresh_gallery()

        def set_sort_mode(self, sort_by: str) -> List[HistoryEntry]:
            idx = self.sort_combo.findData(str(sort_by or "newest"))
            if idx >= 0:
                self.sort_combo.blockSignals(True)
                self.sort_combo.setCurrentIndex(idx)
                self.sort_combo.blockSignals(False)
            return self.refresh_gallery()

        @property
        def aqua_theme(self) -> str:
            return self._aqua_theme_display

        @property
        def animation_intensity(self) -> str:
            return self._animation_intensity

        @property
        def glass_transparency(self) -> float:
            return self._glass_transparency_float

        @property
        def view_mode(self) -> str:
            return self._view_mode

        def clear_search_and_filters(self) -> List[HistoryEntry]:
            return self._reset_search_and_filters()

        def clear_non_favorites(self, *, confirm: bool = False) -> int:
            return self.prompt_clear_history(confirm=confirm, keep_favorites=True)

        def request_new_capture(self) -> None:
            self.newCaptureRequested.emit()

        def set_view_mode(self, mode: str) -> str:
            norm = "list" if str(mode or "grid").strip().lower() == "list" else "grid"
            self._view_mode = norm
            self.view_grid_btn.blockSignals(True)
            self.view_list_btn.blockSignals(True)
            self.view_grid_btn.setChecked(norm == "grid")
            self.view_list_btn.setChecked(norm == "list")
            self.view_grid_btn.blockSignals(False)
            self.view_list_btn.blockSignals(False)
            self.view_grid_btn.update()
            self.view_list_btn.update()

            if norm == "list":
                self.grid_list.setViewMode(QListWidget.ViewMode.ListMode)
                self.grid_list.setIconSize(QSize(96, 54))
                self.grid_list.setGridSize(QSize(max(360, self.grid_list.viewport().width() - 18), 74))
            else:
                self.grid_list.setViewMode(QListWidget.ViewMode.IconMode)
                self.grid_list.setIconSize(QSize(196, 114))
                self.grid_list.setGridSize(QSize(222, 186))
            for i in range(self.grid_list.count()):
                it = self.grid_list.item(i)
                if it is not None:
                    it.setSizeHint(self.card_delegate.sizeHint(None, None))
            self.grid_list.viewport().update()
            return norm

        def _on_nav_changed(self, row: int) -> None:
            it = self.nav_list.item(row)
            if it is not None:
                code = str(it.data(Qt.ItemDataRole.UserRole) or "all")
                self.set_filter_mode(code)

        def _update_sidebar_counts_and_stats(self) -> None:
            counts = self.store.compute_category_counts()
            self.category_counts = dict(counts)
            self.current_entries = list(self._entries)
            if self._entries:
                self.empty_state_kind = "none"
            elif counts.get("all", 0) == 0:
                self.empty_state_kind = "empty"
            else:
                self.empty_state_kind = "no_results"
            base_labels = {
                "all": "All Captures",
                "favorites": "★ Favorites",
                "recent": "Recent (7 Days)",
                "with_text": "Recognized Text",
            }
            for code, btn in self.category_buttons.items():
                cnt = counts.get(code, 0)
                btn.setText(f"{base_labels.get(code, code)} ({cnt})")

            stats = self.store.compute_storage_stats()
            self.header_count_badge.setText(
                f"{stats.total_items} capture{'s' if stats.total_items != 1 else ''} • {stats.favorite_items} ★"
            )
            mode_labels = {
                "saved_or_copied": "Saved / Copied",
                "all_completed": "All Captures",
                "off": "Recording Off",
            }
            self.privacy_badge_lbl.setText(mode_labels.get(self.store.privacy_mode, self.store.privacy_mode))
            mb_ratio = stats.total_megabytes / max(1.0, float(self.store.max_storage_mb))
            item_ratio = stats.total_items / max(1.0, float(self.store.max_items))
            eff_ratio = max(mb_ratio, item_ratio)
            self.storage_meter_bar.set_usage(
                eff_ratio,
                f"{stats.total_megabytes:.1f} / {self.store.max_storage_mb} MB ({stats.total_items}/{self.store.max_items})",
            )
            self.storage_label.setText(
                f"Items: {stats.total_items} ({stats.favorite_items} ★)\n"
                f"OCR Indexed: {stats.ocr_indexed_items}\n"
                f"Storage: {stats.total_megabytes:.2f} MB / {self.store.max_storage_mb} MB\n"
                f"Mode: {self.store.privacy_mode}"
            )

        def refresh_gallery(self, preserve_capture_id: Optional[str] = None) -> List[HistoryEntry]:
            self._thumb_batch_timer.stop()
            target_cid = preserve_capture_id or self.selected_capture_id
            query = self.search_edit.text().strip()
            sort_mode = str(self.sort_combo.currentData() or "newest")
            self._entries = self.store.search_entries(
                query,
                filter_mode=self._current_filter,
                sort_by=sort_mode,
            )
            self._entry_meta_by_id = {e.capture_id: e for e in self._entries}

            with self._async_lock:
                self._gallery_load_gen += 1
                cur_gen = self._gallery_load_gen
                self._pending_thumb_rows.clear()
                self._completed_thumb_decodes.clear()

            self.grid_list.blockSignals(True)
            self.grid_list.clear()
            restore_row = 0
            card_sz = self.card_delegate.sizeHint(None, None)
            new_pending_rows: List[Tuple[int, str, int]] = []

            for idx, entry in enumerate(self._entries):
                if target_cid and entry.capture_id == target_cid:
                    restore_row = idx
                star = "★ " if entry.favorite else ""
                date_short = entry.date_iso.split(" ")[0] if entry.date_iso else ""
                caption = f"{star}{entry.display_title}\n{date_short} • {entry.width}×{entry.height}"
                item = QListWidgetItem(caption)
                item.setData(Qt.ItemDataRole.UserRole, entry.capture_id)
                item.setData(HistoryCardDelegate.ROLE_ENTRY_META, entry)
                item.setSizeHint(card_sz)

                cached_pm = self.get_cached_thumbnail_pixmap(entry.capture_id)
                if cached_pm is not None and not cached_pm.isNull():
                    item.setData(HistoryCardDelegate.ROLE_THUMB_PIXMAP, cached_pm)
                    item.setIcon(QIcon(cached_pm))
                else:
                    new_pending_rows.append((idx, entry.capture_id, cur_gen))

                self.grid_list.addItem(item)

            with self._async_lock:
                self._pending_thumb_rows = new_pending_rows

            self.grid_list.blockSignals(False)
            self._update_sidebar_counts_and_stats()

            if self.grid_list.count() > 0:
                self.empty_state_card.setVisible(False)
                self.grid_list.setVisible(True)
                self.grid_list.setCurrentRow(restore_row)
                r_item = self.grid_list.item(restore_row)
                if r_item is not None and not r_item.isSelected():
                    r_item.setSelected(True)
                self._on_selection_changed()
                self._prioritize_visible_thumbnails()
            else:
                self.grid_list.setVisible(False)
                self.empty_state_card.setVisible(True)
                has_filter = bool(query or self._current_filter != "all")
                if has_filter:
                    self.empty_title_lbl.setText("<b>No Matching Captures Found</b>")
                    self.empty_desc_lbl.setText(
                        f"No captures matched your current filter ('{self._current_filter}') "
                        + (f"and search query ('{query}')." if query else ".")
                    )
                    self.reset_filters_btn.setVisible(True)
                else:
                    self.empty_title_lbl.setText("<b>No Captures in History Yet</b>")
                    self.empty_desc_lbl.setText(
                        "Saved, copied, pinned, or OCR-recognized screenshots will appear here automatically."
                    )
                    self.reset_filters_btn.setVisible(False)
                self._clear_preview()
            return list(self._entries)

        def _clear_preview(self) -> None:
            with self._async_lock:
                self._preview_load_gen += 1
                self._pending_preview_request = None
            self._current_preview_full_pixmap = None
            self._current_preview_is_thumbnail = False
            self._current_preview_stage = "empty"
            self._current_preview_cid = None
            self.preview_title.setText("<b>No capture selected</b>")
            self.preview_img_lbl.clear()
            self.preview_img_lbl.setText("No preview available")
            self.meta_label.setText("Select a screenshot card on the left to inspect its details and actions.")
            self.ocr_status_badge.setText("No selection")
            self.ocr_preview.setPlainText("")
            self.btn_run_ocr.hide()
            self._ocr_ui_timer.stop()
            self._ocr_copy_target = None
            self.btn_fav.setText("★ Favorite")

        def _current_entry(self) -> Optional[HistoryEntry]:
            # When Ctrl/Shift multi-select is active, the focused (current)
            # selected card is the one shown in the inspector. selectedItems()[0]
            # is the first card in gallery order, not necessarily the current.
            current = self.grid_list.currentItem()
            selected = self.grid_list.selectedItems()
            if current is not None and (current.isSelected() or not selected):
                it = current
            elif selected:
                it = selected[0]
            else:
                return None
            cid = str(it.data(Qt.ItemDataRole.UserRole) or "")
            if not cid:
                return None
            return self._entry_meta_by_id.get(cid) or self.store.get_entry(cid)

        def _rescale_active_preview_pixmap(self) -> None:
            if self._current_preview_full_pixmap is None or self._current_preview_full_pixmap.isNull():
                return
            lbl_sz = self.preview_img_lbl.size() - QSize(12, 12)
            if lbl_sz.width() <= 300 and lbl_sz.height() <= 190:
                target_sz = QSize(max(lbl_sz.width(), 420), max(lbl_sz.height(), 260))
            else:
                target_sz = QSize(max(64, lbl_sz.width()), max(64, lbl_sz.height()))
            src_w = max(1, self._current_preview_full_pixmap.width())
            src_h = max(1, self._current_preview_full_pixmap.height())
            if self._current_preview_is_thumbnail:
                eff_sz = QSize(min(target_sz.width(), src_w), min(target_sz.height(), src_h))
            else:
                eff_sz = target_sz
            scaled = self._current_preview_full_pixmap.scaled(
                eff_sz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_img_lbl.setPixmap(scaled)

        def _on_selection_changed(self) -> None:
            entry = self._current_entry()
            if entry is None:
                self._clear_preview()
                return
            star = "★ " if entry.favorite else ""
            self.preview_title.setText(f"<b>{star}{entry.display_title}</b>")
            self.btn_fav.setText("★ Unfavorite" if entry.favorite else "★ Favorite")

            cid = entry.capture_id
            if self._ocr_copy_target is not None and self._ocr_copy_target != cid:
                self._ocr_copy_target = None
            with self._async_lock:
                self._preview_load_gen += 1
                req_gen = self._preview_load_gen
                if self._pending_preview_request is not None:
                    self._cancelled_preview_decode_count += 1
                    self._pending_preview_request = None
            self._current_preview_cid = cid

            if cid in self._preview_pixmap_cache:
                self._preview_pixmap_cache.move_to_end(cid)
                self._current_preview_full_pixmap = self._preview_pixmap_cache[cid]
                self._current_preview_is_thumbnail = False
                self._current_preview_stage = "full"
                self._rescale_active_preview_pixmap()
            elif not entry.image_exists:
                self._current_preview_full_pixmap = None
                self._current_preview_is_thumbnail = False
                self._current_preview_stage = "missing"
                self.preview_img_lbl.clear()
                self.preview_img_lbl.setText("Image file missing on disk")
            else:
                # 1. Show the thumbnail immediately (preserving aspect ratio)
                thumb_pm = self._load_thumbnail_pixmap_immediate(cid)
                if thumb_pm is not None and not thumb_pm.isNull():
                    self._current_preview_full_pixmap = thumb_pm
                    self._current_preview_is_thumbnail = True
                    self._current_preview_stage = "thumbnail"
                    self._rescale_active_preview_pixmap()
                else:
                    self._current_preview_full_pixmap = None
                    self._current_preview_is_thumbnail = False
                    self._current_preview_stage = "loading"
                    self.preview_img_lbl.clear()
                    self.preview_img_lbl.setText("Loading full-resolution preview...")

                # 2. Decode the full-resolution image off the GUI thread, then update on Qt GUI thread
                self._start_async_full_preview_load(cid, req_gen)

            kb = entry.file_size_bytes / 1024.0
            self.meta_label.setText(
                f"Date: {entry.date_iso}  •  Dimensions: {entry.width} × {entry.height} px\n"
                f"Size: {kb:.1f} KB  •  Mode: {entry.capture_mode.capitalize()}"
            )
            self._refresh_ocr_panel(entry)

        def _refresh_ocr_panel(self, entry: Optional[HistoryEntry] = None) -> None:
            """Show meaningful OCR status and keep controls in sync with background work."""
            entry = entry or self._current_entry()
            if entry is None:
                return
            state = self.store.get_ocr_job_state(entry.capture_id)
            txt = (entry.ocr_text or "").strip()
            if txt:
                word_cnt = len(txt.split())
                status = f"{word_cnt} word{'s' if word_cnt != 1 else ''}"
            elif state == "pending":
                status = "Indexing…"
            elif state == "empty":
                status = "No text found"
            elif state == "failed":
                status = "OCR failed"
            else:
                status = "Not indexed"

            if self.ocr_status_badge.text() != status:
                self.ocr_status_badge.setText(status)
            display = txt if txt else ("Recognizing text in the background…" if state == "pending" else "")
            if self.ocr_preview.toPlainText() != display:
                self.ocr_preview.setPlainText(display)
            self.ocr_preview.setPlaceholderText(
                "No readable text was found. You can retry OCR." if state == "empty"
                else "Text recognition failed. You can retry OCR." if state == "failed"
                else "No recognized text indexed for this capture yet."
            )
            can_run = self._ocr_runner is not None and not txt and state != "pending"
            self.btn_run_ocr.setVisible(can_run)
            if can_run:
                self.btn_run_ocr.setText("Retry OCR" if state in ("empty", "failed") else "Run OCR")
            if (state == "pending" or self.store.has_pending_ocr_jobs()) and self.isVisible() and not self._closing:
                self._ocr_ui_timer.start()

        def _poll_history_ocr_status(self) -> None:
            if self._closing or not self.isVisible():
                self._ocr_ui_timer.stop()
                return
            entry = self._current_entry()
            if entry is None:
                self._ocr_ui_timer.stop()
                return
            # The worker updates the cache and SQLite. Poll the selected screenshot only.
            current = self.store.get_entry(entry.capture_id)
            if current is None:
                self._ocr_ui_timer.stop()
                return
            changed = (current.ocr_text or "").strip() != self.ocr_preview.toPlainText().strip()
            state = self.store.get_ocr_job_state(entry.capture_id)
            self._refresh_ocr_panel(current)
            if changed and current.ocr_text:
                self._entry_meta_by_id[current.capture_id] = current
                for item in (self.grid_list.item(i) for i in range(self.grid_list.count())):
                    if str(item.data(Qt.ItemDataRole.UserRole) or "") == current.capture_id:
                        item.setData(HistoryCardDelegate.ROLE_ENTRY_META, current)
                        break
                self.grid_list.viewport().update()
                self._update_sidebar_counts_and_stats()
                if self._current_filter == "with_text":
                    self.refresh_gallery(preserve_capture_id=current.capture_id)
            if current.ocr_text and self._ocr_copy_target == current.capture_id:
                cb = QApplication.clipboard()
                if cb is not None:
                    cb.setText(current.ocr_text)
                self._ocr_copy_target = None
                self.btn_copy_txt.setText("Copied!")
                QTimer.singleShot(1100, lambda: self.btn_copy_txt.setText("Copy Text"))
            if not self.store.has_pending_ocr_jobs():
                self._ocr_ui_timer.stop()
                if self._ocr_copy_target == current.capture_id:
                    self._ocr_copy_target = None
                # Refresh every card's OCR badge and category counts after the batch completes.
                self.refresh_gallery(preserve_capture_id=current.capture_id)

        def run_current_ocr(self, *, copy_when_ready: bool = False) -> bool:
            """Explicit on-demand OCR, using the existing background indexer."""
            entry = self._current_entry()
            if entry is None or self._ocr_runner is None:
                return False
            if copy_when_ready:
                self._ocr_copy_target = entry.capture_id
            if entry.ocr_text.strip():
                return True
            if self.store.get_ocr_job_state(entry.capture_id) != "pending":
                pil_img = self.store.load_full_image_pil(entry.capture_id)
                if pil_img is None:
                    self.ocr_status_badge.setText("Image missing")
                    return False
                if self.store.enqueue_async_ocr_indexing(entry.capture_id, pil_img, self._ocr_runner) is None:
                    self.ocr_status_badge.setText("OCR unavailable")
                    return False
            self._refresh_ocr_panel(entry)
            self._ocr_ui_timer.start()
            return True

        def _show_context_menu(self, pos: QPoint) -> None:
            entry = self._current_entry()
            if entry is None:
                return
            menu = QMenu(self)
            menu.addAction("Open Image", self.open_current_image)
            menu.addAction("Reopen in Editor", self.reopen_current_in_editor)
            menu.addAction("Pin to Screen (or Focus Existing)", self.pin_current_entry)
            menu.addAction("Create Duplicate Pin", self.duplicate_pin_current_entry)
            menu.addSeparator()
            menu.addAction("Copy Image", self.copy_current_image)
            menu.addAction("Copy Recognized Text", self.copy_current_text)
            menu.addAction("Run / Retry OCR", self.run_current_ocr)
            menu.addAction("Save As...", lambda: self.save_current_as())
            menu.addSeparator()
            fav_label = "Remove from Favorites" if entry.favorite else "Add to Favorites"
            menu.addAction(fav_label, self.toggle_current_favorite)
            menu.addAction("Rename / Set Title...", lambda: self.rename_current_entry())
            menu.addAction("Open File Location", self.open_current_file_location)
            menu.addSeparator()
            menu.addAction("Delete Selected", lambda: self.delete_selected_items(confirm=True))
            menu.exec(self.grid_list.mapToGlobal(pos))

        def open_current_image(self) -> None:
            entry = self._current_entry()
            if entry is None or entry.resolved_image_path is None:
                return
            p = entry.resolved_image_path
            try:
                if sys.platform == "win32":
                    os.startfile(str(p))  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["xdg-open", str(p)])
            except Exception:
                pass

        def reopen_current_in_editor(self) -> bool:
            entry = self._current_entry()
            if entry is None:
                return False
            pil_img = self.store.load_full_image_pil(entry.capture_id)
            if pil_img is None:
                QMessageBox.warning(self, "Missing File", "The screenshot file for this history entry could not be found.")
                return False
            self.reopenInEditorRequested.emit(pil_img, entry.display_title)
            return True

        def pin_current_entry(self) -> bool:
            entry = self._current_entry()
            if entry is None:
                return False
            pil_img = self.store.load_full_image_pil(entry.capture_id)
            if pil_img is None:
                QMessageBox.warning(self, "Missing File", "The screenshot file for this history entry could not be found.")
                return False
            self.pinEntryRequested.emit(pil_img, entry.display_title, entry.capture_id)
            self.pinImageRequested.emit(pil_img, entry.display_title)
            return True

        def duplicate_pin_current_entry(self) -> bool:
            entry = self._current_entry()
            if entry is None:
                return False
            pil_img = self.store.load_full_image_pil(entry.capture_id)
            if pil_img is None:
                return False
            self.pinEntryRequested.emit(pil_img, f"{entry.display_title} (Copy)", "")
            self.pinImageRequested.emit(pil_img, f"{entry.display_title} (Copy)")
            return True

        def copy_current_image(self) -> bool:
            entry = self._current_entry()
            if entry is None:
                return False
            pil_img = self.store.load_full_image_pil(entry.capture_id)
            if pil_img is None:
                return False
            cb = QApplication.clipboard()
            if cb is not None:
                pm = self._pil_to_qpixmap(pil_img)
                self._cache_preview_pixmap(entry.capture_id, pm)
                cb.setPixmap(pm)
            self.btn_copy_img.setText("Copied!")
            QTimer.singleShot(1100, lambda: self.btn_copy_img.setText("Copy Image"))
            return True

        def copy_current_text(self) -> str:
            entry = self._current_entry()
            if entry is None:
                return ""
            txt = (entry.ocr_text or "").strip()
            if txt:
                cb = QApplication.clipboard()
                if cb is not None:
                    cb.setText(txt)
                self.btn_copy_txt.setText("Copied!")
                QTimer.singleShot(1100, lambda: self.btn_copy_txt.setText("Copy Text"))
                return txt
            self.run_current_ocr(copy_when_ready=True)
            return ""

        def save_current_as(self, dest_path: Optional[Path] = None) -> Optional[Path]:
            entry = self._current_entry()
            if entry is None:
                return None
            pil_img = self.store.load_full_image_pil(entry.capture_id)
            if pil_img is None:
                return None
            if dest_path is not None:
                target = Path(dest_path)
            else:
                default_name = entry.display_title
                if not default_name.lower().endswith(".png"):
                    default_name = f"{default_name}.png"
                dest_str, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save Screenshot As",
                    str(Path.home() / "Pictures" / "Prismwake" / default_name),
                    "PNG Image (*.png);;All Files (*.*)",
                )
                if not dest_str:
                    return None
                target = Path(dest_str)
            try:
                _atomic_save_pil_png(pil_img, target)
                return target
            except Exception as exc:
                QMessageBox.warning(self, "Save Error", f"Could not save screenshot:\n{exc}")
                return None

        def toggle_current_favorite(self) -> Optional[bool]:
            entry = self._current_entry()
            if entry is None:
                return None
            new_fav = not entry.favorite
            self.store.set_favorite(entry.capture_id, new_fav)
            self.refresh_gallery(preserve_capture_id=entry.capture_id)
            return new_fav

        def rename_current_entry(self, new_title: Optional[str] = None) -> bool:
            entry = self._current_entry()
            if entry is None:
                return False
            if new_title is None:
                entered, ok = QInputDialog.getText(
                    self,
                    "Rename Capture",
                    "Enter a title for this screenshot:",
                    text=entry.title or entry.display_title,
                )
                if not ok:
                    return False
                new_title = entered
            ok_upd = self.store.update_title(entry.capture_id, new_title)
            self.refresh_gallery(preserve_capture_id=entry.capture_id)
            return ok_upd

        def open_current_file_location(self) -> Optional[Path]:
            entry = self._current_entry()
            if entry is None or entry.resolved_image_path is None:
                return None
            p = entry.resolved_image_path
            self._last_opened_location = p
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["explorer.exe", f"/select,{p}"])
                else:
                    subprocess.Popen(["xdg-open", str(p.parent)])
            except Exception:
                pass
            return p

        def delete_selected_items(self, *, confirm: bool = True) -> int:
            sel = self.grid_list.selectedItems()
            if not sel:
                cur = self.grid_list.currentItem()
                if cur is not None:
                    sel = [cur]
            if not sel:
                return 0
            ids = [str(it.data(Qt.ItemDataRole.UserRole)) for it in sel if it.data(Qt.ItemDataRole.UserRole)]
            if confirm and len(ids) > 1:
                ans = QMessageBox.question(
                    self,
                    "Confirm Bulk Delete",
                    f"Delete {len(ids)} selected captures from Prismwake History?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return 0
            for cid in ids:
                self._thumb_pixmap_cache.pop(cid, None)
                self._preview_pixmap_cache.pop(cid, None)
            deleted = self.store.delete_entries(ids)
            self.refresh_gallery()
            return deleted

        def prompt_clear_history(self, *, confirm: bool = True, keep_favorites: bool = False) -> int:
            if confirm:
                msg = (
                    "Delete all non-favorite screenshots in History while keeping ★ Favorites?"
                    if keep_favorites
                    else "Are you sure you want to delete all managed screenshots in History?\n"
                    "(Separately saved files in your Pictures folder will not be deleted.)"
                )
                ans = QMessageBox.question(
                    self,
                    "Clear Screenshot History",
                    msg,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return 0
            if not keep_favorites:
                self._thumb_pixmap_cache.clear()
                self._preview_pixmap_cache.clear()
            cleared = self.store.clear_history(keep_favorites=keep_favorites)
            self.refresh_gallery()
            return cleared

else:
    class _HeadlessSize:
        def __init__(self, w: int, h: int) -> None:
            self._w = int(w)
            self._h = int(h)
        def width(self) -> int:
            return self._w
        def height(self) -> int:
            return self._h
        def __eq__(self, other: Any) -> bool:
            if isinstance(other, _HeadlessSize):
                return (self._w, self._h) == (other._w, other._h)
            if isinstance(other, tuple) and len(other) == 2:
                return (self._w, self._h) == (int(other[0]), int(other[1]))
            return False
        def __repr__(self) -> str:
            return f"_HeadlessSize({self._w}, {self._h})"

    class _HeadlessPixmap:
        """Lightweight headless QPixmap representation created strictly on the GUI thread."""
        def __init__(self, width: int, height: int, rgba_bytes: Optional[bytes] = None, *, is_thumbnail: bool = False) -> None:
            self._w = int(width)
            self._h = int(height)
            self._rgba_bytes = rgba_bytes
            self.is_thumbnail = bool(is_thumbnail)
            self.created_thread_id = threading.get_ident()

        def width(self) -> int:
            return self._w

        def height(self) -> int:
            return self._h

        def size(self) -> _HeadlessSize:
            return _HeadlessSize(self._w, self._h)

        def isNull(self) -> bool:
            return self._w <= 0 or self._h <= 0

        @property
        def aspect_ratio(self) -> float:
            return float(self._w) / float(max(1, self._h))

        def scaled(self, target_w: int, target_h: int) -> "_HeadlessPixmap":
            if self.isNull():
                return _HeadlessPixmap(0, 0)
            scale = min(float(max(1, target_w)) / float(self._w), float(max(1, target_h)) / float(self._h))
            dw = max(1, int(round(self._w * scale)))
            dh = max(1, int(round(self._h * scale)))
            return _HeadlessPixmap(dw, dh, None, is_thumbnail=self.is_thumbnail)

    class _HeadlessPreviewLabel:
        def __init__(self, width: int = 420, height: int = 260) -> None:
            self._w = int(width)
            self._h = int(height)
            self._pixmap: Optional[_HeadlessPixmap] = None
            self._text: str = ""

        def size(self) -> _HeadlessSize:
            return _HeadlessSize(self._w, self._h)

        def resize(self, w: int, h: int) -> None:
            self._w = int(w)
            self._h = int(h)

        def pixmap(self) -> Optional[_HeadlessPixmap]:
            return self._pixmap

        def setPixmap(self, pm: _HeadlessPixmap) -> None:
            self._pixmap = pm
            self._text = ""

        def text(self) -> str:
            return self._text

        def setText(self, t: str) -> None:
            self._text = str(t)

        def clear(self) -> None:
            self._pixmap = None
            self._text = ""

    class _HeadlessHistorySignal:
        def __init__(self) -> None:
            self._cbs: List[Callable[..., Any]] = []
        def connect(self, cb: Callable[..., Any]) -> None:
            self._cbs.append(cb)
        def emit(self, *args: Any) -> None:
            for cb in list(self._cbs):
                cb(*args)

    class _HeadlessGelButton:
        def __init__(self, text: str, variant: str = "glass") -> None:
            self._text = str(text)
            self.variant = str(variant)
            self._checked = False
            self._enabled = True
            self.clicked = _HeadlessHistorySignal()
        def text(self) -> str: return self._text
        def setText(self, t: str) -> None: self._text = str(t)
        def isChecked(self) -> bool: return self._checked
        def setChecked(self, c: bool) -> None: self._checked = bool(c)
        def isEnabled(self) -> bool: return self._enabled
        def setEnabled(self, e: bool) -> None: self._enabled = bool(e)
        def click(self) -> None: self.clicked.emit()

    class HistoryCardDelegate:  # type: ignore[no-redef]
        """Headless-compatible HistoryCardDelegate enforcing zero disk/decode I/O inside paint()."""

        ROLE_ENTRY_META = 257
        ROLE_THUMB_PIXMAP = 258

        def __init__(self, history_window: "HistoryWindow", parent: Optional[Any] = None) -> None:
            _ = parent
            self._win = history_window

        def paint(self, painter: Any, option: Any, index: Any) -> Optional[_HeadlessPixmap]:
            _ = (painter, option)
            row_idx = int(getattr(index, "row", lambda: -1)()) if hasattr(index, "row") else int(getattr(index, "row_idx", -1))
            cid = ""
            thumb_pm: Optional[_HeadlessPixmap] = None
            if hasattr(index, "data"):
                cid = str(index.data(256) or "")
                thumb_pm = index.data(self.ROLE_THUMB_PIXMAP)
            elif isinstance(index, dict):
                cid = str(index.get("capture_id", ""))
                thumb_pm = index.get("thumb_pixmap")
            if (thumb_pm is None or thumb_pm.isNull()) and cid:
                thumb_pm = self._win.get_cached_thumbnail_pixmap(cid)
                if thumb_pm is None or thumb_pm.isNull():
                    self._win.request_thumbnail_async(cid, item_row=row_idx, high_priority=True)
            return thumb_pm

    class HistoryWindow:  # type: ignore[no-redef]
        """Headless-compatible HistoryWindow controller with genuine async preview & thumbnail workers."""

        INITIAL_VIEWPORT_THUMB_COUNT: int = 16
        THUMB_GUI_DRAIN_BATCH: int = 24
        THUMB_CACHE_CAPACITY: int = 300
        PREVIEW_CACHE_CAPACITY: int = 32

        def __init__(
            self,
            store: ScreenshotHistoryStore,
            *,
            ocr_runner: Optional[Callable[[Image.Image], str]] = None,
            aqua_theme: str = "ocean_current",
            animation_intensity: str = "medium",
            glass_transparency: int = 72,
            safe_mode: bool = False,
            disable_continuous_animations: bool = False,
            parent: Optional[Any] = None,
        ) -> None:
            _ = parent
            self.store = store
            self._ocr_runner = ocr_runner
            self._visible = False
            self._current_filter: str = "all"
            self._current_sort: str = "newest"
            self._view_mode: str = "grid"
            self._search_query: str = ""
            self._aqua_theme_display: str = str(aqua_theme or "Bondi Blue")
            self._aqua_theme: str = normalize_history_aqua_theme(aqua_theme)
            self._animation_intensity: str = str(animation_intensity or "medium").strip().lower()
            gt_f = float(glass_transparency)
            self._glass_transparency_float: float = gt_f if gt_f <= 1.0 else (gt_f / 100.0)
            self._glass_transparency: int = max(10, min(95, int(round(gt_f * 100.0)) if gt_f <= 1.0 else int(gt_f)))
            self._safe_mode: bool = bool(safe_mode)
            self._disable_continuous: bool = bool(disable_continuous_animations)
            self.current_entries: List[HistoryEntry] = []
            self._entry_meta_by_id: Dict[str, HistoryEntry] = {}
            self.category_counts: Dict[str, int] = {"all": 0, "favorites": 0, "recent": 0, "recent_7d": 0, "with_text": 0, "with_ocr": 0}
            self.empty_state_kind: str = "empty"
            self.reopenInEditorRequested = _HeadlessHistorySignal()
            self.pinImageRequested = _HeadlessHistorySignal()
            self.pinEntryRequested = _HeadlessHistorySignal()
            self.openSettingsRequested = _HeadlessHistorySignal()
            self.newCaptureRequested = _HeadlessHistorySignal()
            self._selected_capture_id: Optional[str] = None
            self.selected_capture_ids: List[str] = []
            self._last_opened_location: Optional[Path] = None

            self._gui_thread_id: int = threading.get_ident()
            self._closing: bool = False
            self._async_lock = threading.Lock()
            self._thumb_pixmap_cache: "OrderedDict[str, _HeadlessPixmap]" = OrderedDict()
            self._preview_pixmap_cache: "OrderedDict[str, _HeadlessPixmap]" = OrderedDict()
            self._gallery_load_gen: int = 0
            self._pending_thumb_rows: List[Tuple[int, str, int]] = []
            self._inflight_thumb_cids: set[str] = set()
            self._completed_thumb_decodes: List[Tuple[int, int, str, int, int, Optional[bytes]]] = []
            self._thumb_worker_thread: Optional[threading.Thread] = None
            self._thumb_worker_event = threading.Event()
            self._explicit_visible_range: Optional[Tuple[int, int]] = None

            self.preview_img_lbl = _HeadlessPreviewLabel(420, 260)
            self._current_preview_full_pixmap: Optional[_HeadlessPixmap] = None
            self._current_preview_is_thumbnail: bool = False
            self._current_preview_stage: str = "empty"
            self._current_preview_cid: Optional[str] = None
            self._preview_load_gen: int = 0
            self._pending_preview_request: Optional[Tuple[int, str]] = None
            self._preview_worker_busy: bool = False
            self._completed_preview_decodes: List[Tuple[int, str, int, int, Optional[bytes]]] = []
            self._preview_worker_thread: Optional[threading.Thread] = None
            self._preview_worker_event = threading.Event()
            self._preview_decode_delay_sec: float = 0.0

            self._paint_sync_decode_count: int = 0
            self._bg_thumb_decode_count: int = 0
            self._last_thumb_decode_thread_id: Optional[int] = None
            self._last_thumb_pixmap_thread_id: Optional[int] = None
            self._thumb_decode_order: List[str] = []
            self._bg_preview_decode_count: int = 0
            self._cancelled_preview_decode_count: int = 0
            self._ignored_stale_preview_count: int = 0
            self._last_preview_decode_thread_id: Optional[int] = None
            self._last_preview_gui_update_thread_id: Optional[int] = None

            self.card_delegate = HistoryCardDelegate(self)
            self.settings_btn = _HeadlessGelButton("Storage & Privacy Settings", "glass")
            self.settings_btn.clicked.connect(self.openSettingsRequested.emit)
            self.new_capture_btn = _HeadlessGelButton("✦ New Capture", "emerald")
            self.new_capture_btn.clicked.connect(self.newCaptureRequested.emit)
            self.btn_pin = _HeadlessGelButton("Pin", "sapphire")
            self.btn_edit = _HeadlessGelButton("Reopen in Editor", "emerald")
            self.btn_copy_img = _HeadlessGelButton("Copy Image", "sapphire")
            self.btn_fav = _HeadlessGelButton("★ Favorite", "glass")
            self.btn_copy_txt = _HeadlessGelButton("Copy Text", "glass")
            self.btn_save_as = _HeadlessGelButton("Save As...", "glass")
            self.btn_rename = _HeadlessGelButton("Rename", "glass")
            self.btn_folder = _HeadlessGelButton("Open Location", "glass")
            self.btn_del = _HeadlessGelButton("Delete", "ruby")
            self.delete_sel_btn = _HeadlessGelButton("Delete Selected", "ruby")
            self.clear_non_fav_btn = _HeadlessGelButton("Clear Non-Favorites", "glass")
            self.clear_btn = _HeadlessGelButton("Clear History...", "ruby")
            self.category_buttons: Dict[str, _HeadlessGelButton] = {
                "all": _HeadlessGelButton("All Captures", "glass"),
                "favorites": _HeadlessGelButton("★ Favorites", "glass"),
                "recent": _HeadlessGelButton("Recent (7 Days)", "glass"),
                "with_text": _HeadlessGelButton("Recognized Text", "glass"),
            }
            self.refresh_gallery()

        @property
        def selected_capture_id(self) -> Optional[str]:
            return self._selected_capture_id

        @selected_capture_id.setter
        def selected_capture_id(self, cid: Optional[str]) -> None:
            new_cid = str(cid) if cid else None
            changed = (new_cid != self._selected_capture_id) or (new_cid != self._current_preview_cid)
            self._selected_capture_id = new_cid
            if changed:
                self._on_selection_changed()

        @staticmethod
        def _pil_to_rgba_buffer(pil_img: Image.Image) -> Tuple[int, int, bytes]:
            rgba = pil_img.convert("RGBA")
            return rgba.width, rgba.height, rgba.tobytes("raw", "RGBA")

        @staticmethod
        def _rgba_bytes_to_qpixmap(width: int, height: int, rgba_bytes: bytes, *, is_thumbnail: bool = False) -> _HeadlessPixmap:
            return _HeadlessPixmap(width, height, rgba_bytes, is_thumbnail=is_thumbnail)

        @classmethod
        def _pil_to_qpixmap(cls, pil_img: Image.Image, *, is_thumbnail: bool = False) -> _HeadlessPixmap:
            w, h, raw = cls._pil_to_rgba_buffer(pil_img)
            return cls._rgba_bytes_to_qpixmap(w, h, raw, is_thumbnail=is_thumbnail)

        def get_cached_entry_meta(self, capture_id: str) -> Optional[HistoryEntry]:
            return self._entry_meta_by_id.get(capture_id) if capture_id else None

        def get_cached_thumbnail_pixmap(self, capture_id: str) -> Optional[_HeadlessPixmap]:
            if not capture_id:
                return None
            pm = self._thumb_pixmap_cache.get(capture_id)
            if pm is not None:
                self._thumb_pixmap_cache.move_to_end(capture_id)
            return pm

        def _cache_thumb_pixmap(self, capture_id: str, pm: _HeadlessPixmap) -> None:
            self._thumb_pixmap_cache[capture_id] = pm
            self._thumb_pixmap_cache.move_to_end(capture_id)
            while len(self._thumb_pixmap_cache) > self.THUMB_CACHE_CAPACITY:
                self._thumb_pixmap_cache.popitem(last=False)

        def _cache_preview_pixmap(self, capture_id: str, pm: _HeadlessPixmap) -> None:
            self._preview_pixmap_cache[capture_id] = pm
            self._preview_pixmap_cache.move_to_end(capture_id)
            while len(self._preview_pixmap_cache) > self.PREVIEW_CACHE_CAPACITY:
                self._preview_pixmap_cache.popitem(last=False)

        def _load_thumbnail_pixmap_immediate(self, capture_id: str) -> Optional[_HeadlessPixmap]:
            cached = self.get_cached_thumbnail_pixmap(capture_id)
            if cached is not None and not cached.isNull():
                return cached
            thumb_pil = self.store.load_thumbnail_pil(capture_id)
            if thumb_pil is None:
                return None
            pm = self._pil_to_qpixmap(thumb_pil, is_thumbnail=True)
            self._last_thumb_pixmap_thread_id = threading.get_ident()
            self._cache_thumb_pixmap(capture_id, pm)
            return pm

        def ensure_thumbnail_pixmap(self, capture_id: str, *, item_row: int = -1) -> Optional[_HeadlessPixmap]:
            pm = self.get_cached_thumbnail_pixmap(capture_id)
            if pm is not None and not pm.isNull():
                return pm
            self.request_thumbnail_async(capture_id, item_row=item_row, high_priority=True)
            return None

        def set_visible_row_range(self, start_row: int, end_row: int) -> None:
            s = max(0, int(start_row))
            e = max(s, int(end_row))
            self._explicit_visible_range = (s, e)
            self._prioritize_visible_thumbnails()

        def _get_visible_row_range(self) -> Tuple[int, int]:
            total = len(self.current_entries)
            if total <= 0:
                return (0, 0)
            if self._explicit_visible_range is not None:
                s, e = self._explicit_visible_range
                return (max(0, min(total - 1, s)), max(0, min(total - 1, e)))
            return (0, min(total - 1, self.INITIAL_VIEWPORT_THUMB_COUNT - 1))

        def request_thumbnail_async(
            self,
            capture_id: str,
            *,
            item_row: int = -1,
            high_priority: bool = False,
        ) -> None:
            if not capture_id or self._closing or capture_id in self._thumb_pixmap_cache:
                return
            gen = self._gallery_load_gen
            with self._async_lock:
                if capture_id in self._inflight_thumb_cids:
                    return
                for idx, (r_i, c_i, g_i) in enumerate(self._pending_thumb_rows):
                    if c_i == capture_id and g_i == gen:
                        if high_priority and idx > 0:
                            item_tup = self._pending_thumb_rows.pop(idx)
                            self._pending_thumb_rows.insert(0, (item_row if item_row >= 0 else item_tup[0], capture_id, gen))
                        return
                entry_tup = (item_row, capture_id, gen)
                if high_priority:
                    self._pending_thumb_rows.insert(0, entry_tup)
                else:
                    self._pending_thumb_rows.append(entry_tup)
            self._ensure_thumb_worker_running()

        def _prioritize_visible_thumbnails(self) -> None:
            vis_start, vis_end = self._get_visible_row_range()
            with self._async_lock:
                if not self._pending_thumb_rows:
                    return
                vis_bucket: List[Tuple[int, str, int]] = []
                off_bucket: List[Tuple[int, str, int]] = []
                for row_idx, cid, gen in self._pending_thumb_rows:
                    if vis_start <= row_idx <= vis_end:
                        vis_bucket.append((row_idx, cid, gen))
                    else:
                        off_bucket.append((row_idx, cid, gen))
                vis_bucket.sort(key=lambda t: t[0])
                self._pending_thumb_rows = vis_bucket + off_bucket
            self._ensure_thumb_worker_running()

        def _ensure_thumb_worker_running(self) -> None:
            if self._closing:
                return
            if self._thumb_worker_thread is None or not self._thumb_worker_thread.is_alive():
                self._thumb_worker_thread = threading.Thread(
                    target=self._thumb_decode_worker_loop,
                    name="PrismwakeHeadlessThumbWorker",
                    daemon=True,
                )
                self._thumb_worker_thread.start()
            self._thumb_worker_event.set()

        def _thumb_decode_worker_loop(self) -> None:
            while not self._closing:
                item_tup: Optional[Tuple[int, str, int]] = None
                with self._async_lock:
                    if self._pending_thumb_rows:
                        item_tup = self._pending_thumb_rows.pop(0)
                        self._inflight_thumb_cids.add(item_tup[1])
                    else:
                        self._thumb_worker_event.clear()
                if item_tup is None:
                    self._thumb_worker_event.wait(timeout=0.05)
                    with self._async_lock:
                        if not self._pending_thumb_rows:
                            return
                    continue

                row_idx, cid, gen = item_tup
                try:
                    if self._closing or gen != self._gallery_load_gen:
                        continue
                    pil_img = self.store.load_thumbnail_pil(cid)
                    if self._closing or gen != self._gallery_load_gen:
                        continue
                    self._last_thumb_decode_thread_id = threading.get_ident()
                    self._bg_thumb_decode_count += 1
                    self._thumb_decode_order.append(cid)
                    if pil_img is not None:
                        w, h, rgba_bytes = self._pil_to_rgba_buffer(pil_img)
                        with self._async_lock:
                            self._completed_thumb_decodes.append((gen, row_idx, cid, w, h, rgba_bytes))
                finally:
                    with self._async_lock:
                        self._inflight_thumb_cids.discard(cid)

        def _ensure_preview_worker_running(self) -> None:
            if self._closing:
                return
            if self._preview_worker_thread is None or not self._preview_worker_thread.is_alive():
                self._preview_worker_thread = threading.Thread(
                    target=self._preview_decode_worker_loop,
                    name="PrismwakeHeadlessPreviewWorker",
                    daemon=True,
                )
                self._preview_worker_thread.start()
            self._preview_worker_event.set()

        def _start_async_full_preview_load(self, capture_id: str, req_gen: int) -> None:
            if not capture_id or self._closing:
                return
            with self._async_lock:
                if self._pending_preview_request is not None and self._pending_preview_request[0] != req_gen:
                    self._cancelled_preview_decode_count += 1
                self._pending_preview_request = (req_gen, capture_id)
            self._ensure_preview_worker_running()

        def _preview_decode_worker_loop(self) -> None:
            while not self._closing:
                req: Optional[Tuple[int, str]] = None
                with self._async_lock:
                    if self._pending_preview_request is not None:
                        req = self._pending_preview_request
                        self._pending_preview_request = None
                        self._preview_worker_busy = True
                    else:
                        self._preview_worker_busy = False
                        self._preview_worker_event.clear()
                if req is None:
                    self._preview_worker_event.wait(timeout=0.05)
                    with self._async_lock:
                        if self._pending_preview_request is None:
                            self._preview_worker_busy = False
                            return
                    continue

                req_gen, cid = req
                try:
                    if self._closing or req_gen != self._preview_load_gen:
                        with self._async_lock:
                            self._cancelled_preview_decode_count += 1
                        continue

                    delay_rem = float(getattr(self, "_preview_decode_delay_sec", 0.0) or 0.0)
                    while delay_rem > 0.0 and not self._closing:
                        step = min(0.005, delay_rem)
                        time.sleep(step)
                        delay_rem -= step
                        if req_gen != self._preview_load_gen:
                            break

                    if self._closing or req_gen != self._preview_load_gen:
                        with self._async_lock:
                            self._cancelled_preview_decode_count += 1
                        continue

                    self._last_preview_decode_thread_id = threading.get_ident()
                    self._bg_preview_decode_count += 1
                    pil_img = self.store.load_full_image_pil(cid)
                    if self._closing:
                        continue
                    if req_gen != self._preview_load_gen:
                        with self._async_lock:
                            self._cancelled_preview_decode_count += 1
                            if pil_img is not None:
                                w, h, raw = self._pil_to_rgba_buffer(pil_img)
                                self._completed_preview_decodes.append((req_gen, cid, w, h, raw))
                        continue

                    if pil_img is not None:
                        w, h, rgba_bytes = self._pil_to_rgba_buffer(pil_img)
                        with self._async_lock:
                            self._completed_preview_decodes.append((req_gen, cid, w, h, rgba_bytes))
                    else:
                        with self._async_lock:
                            self._completed_preview_decodes.append((req_gen, cid, 0, 0, None))
                finally:
                    with self._async_lock:
                        if self._pending_preview_request is None:
                            self._preview_worker_busy = False

        def _drain_completed_preview_decodes(self) -> None:
            if self._closing or threading.get_ident() != self._gui_thread_id:
                return
            with self._async_lock:
                if not self._completed_preview_decodes:
                    return
                items = list(self._completed_preview_decodes)
                self._completed_preview_decodes.clear()

            for req_gen, cid, w, h, rgba_bytes in items:
                if self._closing or req_gen != self._preview_load_gen or self._selected_capture_id != cid:
                    self._ignored_stale_preview_count += 1
                    continue
                if rgba_bytes is None or w <= 0 or h <= 0:
                    if self._current_preview_full_pixmap is None:
                        self._current_preview_stage = "missing"
                        self.preview_img_lbl.clear()
                        self.preview_img_lbl.setText("Image file missing on disk")
                    continue
                full_pm = self._rgba_bytes_to_qpixmap(w, h, rgba_bytes, is_thumbnail=False)
                self._last_preview_gui_update_thread_id = threading.get_ident()
                self._cache_preview_pixmap(cid, full_pm)
                self._current_preview_full_pixmap = full_pm
                self._current_preview_is_thumbnail = False
                self._current_preview_stage = "full"
                self._current_preview_cid = cid
                self._rescale_active_preview_pixmap()

        def _drain_completed_thumb_decodes(self) -> None:
            if self._closing or threading.get_ident() != self._gui_thread_id:
                return
            with self._async_lock:
                if not self._completed_thumb_decodes:
                    return
                batch = self._completed_thumb_decodes[: self.THUMB_GUI_DRAIN_BATCH]
                self._completed_thumb_decodes = self._completed_thumb_decodes[self.THUMB_GUI_DRAIN_BATCH :]

            for gen, _row_idx, cid, w, h, rgba_bytes in batch:
                if self._closing or gen != self._gallery_load_gen or rgba_bytes is None or w <= 0 or h <= 0:
                    continue
                pm = self._rgba_bytes_to_qpixmap(w, h, rgba_bytes, is_thumbnail=True)
                self._last_thumb_pixmap_thread_id = threading.get_ident()
                self._cache_thumb_pixmap(cid, pm)
                if cid == self._selected_capture_id and self._current_preview_full_pixmap is None:
                    self._current_preview_full_pixmap = pm
                    self._current_preview_is_thumbnail = True
                    self._current_preview_stage = "thumbnail"
                    self._rescale_active_preview_pixmap()

        def _rescale_active_preview_pixmap(self) -> None:
            if self._current_preview_full_pixmap is None or self._current_preview_full_pixmap.isNull():
                return
            lbl_sz = self.preview_img_lbl.size()
            target_w = max(64, lbl_sz.width() - 12)
            target_h = max(64, lbl_sz.height() - 12)
            src_w = max(1, self._current_preview_full_pixmap.width())
            src_h = max(1, self._current_preview_full_pixmap.height())
            if self._current_preview_is_thumbnail:
                eff_w, eff_h = min(target_w, src_w), min(target_h, src_h)
            else:
                eff_w, eff_h = target_w, target_h
            scaled = self._current_preview_full_pixmap.scaled(eff_w, eff_h)
            self.preview_img_lbl.setPixmap(scaled)

        def _on_selection_changed(self) -> None:
            entry = self._current_entry()
            if entry is None:
                with self._async_lock:
                    self._preview_load_gen += 1
                    self._pending_preview_request = None
                self._current_preview_full_pixmap = None
                self._current_preview_is_thumbnail = False
                self._current_preview_stage = "empty"
                self._current_preview_cid = None
                self.preview_img_lbl.clear()
                self.preview_img_lbl.setText("No preview available")
                return

            cid = entry.capture_id
            with self._async_lock:
                self._preview_load_gen += 1
                req_gen = self._preview_load_gen
                if self._pending_preview_request is not None:
                    self._cancelled_preview_decode_count += 1
                    self._pending_preview_request = None
            self._current_preview_cid = cid
            self.btn_fav.setText("★ Unfavorite" if entry.favorite else "★ Favorite")

            if cid in self._preview_pixmap_cache:
                self._preview_pixmap_cache.move_to_end(cid)
                self._current_preview_full_pixmap = self._preview_pixmap_cache[cid]
                self._current_preview_is_thumbnail = False
                self._current_preview_stage = "full"
                self._rescale_active_preview_pixmap()
            elif not entry.image_exists:
                self._current_preview_full_pixmap = None
                self._current_preview_is_thumbnail = False
                self._current_preview_stage = "missing"
                self.preview_img_lbl.clear()
                self.preview_img_lbl.setText("Image file missing on disk")
            else:
                thumb_pm = self._load_thumbnail_pixmap_immediate(cid)
                if thumb_pm is not None and not thumb_pm.isNull():
                    self._current_preview_full_pixmap = thumb_pm
                    self._current_preview_is_thumbnail = True
                    self._current_preview_stage = "thumbnail"
                    self._rescale_active_preview_pixmap()
                else:
                    self._current_preview_full_pixmap = None
                    self._current_preview_is_thumbnail = False
                    self._current_preview_stage = "loading"
                    self.preview_img_lbl.clear()
                    self.preview_img_lbl.setText("Loading full-resolution preview...")
                self._start_async_full_preview_load(cid, req_gen)

        def wait_for_async_preview(self, timeout: float = 2.0) -> bool:
            deadline = time.perf_counter() + max(0.05, float(timeout))
            while time.perf_counter() < deadline:
                self._drain_completed_preview_decodes()
                with self._async_lock:
                    busy = (
                        self._pending_preview_request is not None
                        or self._preview_worker_busy
                        or bool(self._completed_preview_decodes)
                    )
                if not busy and self._current_preview_stage in ("full", "missing", "empty"):
                    return self._current_preview_stage == "full"
                time.sleep(0.005)
            self._drain_completed_preview_decodes()
            return self._current_preview_stage == "full"

        def wait_for_async_thumbnails(self, timeout: float = 2.0) -> int:
            deadline = time.perf_counter() + max(0.05, float(timeout))
            while time.perf_counter() < deadline:
                self._drain_completed_thumb_decodes()
                with self._async_lock:
                    busy = bool(
                        self._pending_thumb_rows
                        or self._inflight_thumb_cids
                        or self._completed_thumb_decodes
                    )
                if not busy:
                    break
                time.sleep(0.005)
            self._drain_completed_thumb_decodes()
            return len(self._thumb_pixmap_cache)

        def apply_aqua_theme_and_config(
            self,
            *,
            aqua_theme: Optional[str] = None,
            animation_intensity: Optional[str] = None,
            glass_transparency: Optional[int] = None,
            safe_mode: Optional[bool] = None,
            disable_continuous_animations: Optional[bool] = None,
        ) -> None:
            if aqua_theme is not None:
                self._aqua_theme_display = str(aqua_theme)
                self._aqua_theme = normalize_history_aqua_theme(aqua_theme)
            if animation_intensity is not None:
                self._animation_intensity = str(animation_intensity).strip().lower()
            if glass_transparency is not None:
                gt_f = float(glass_transparency)
                self._glass_transparency_float = gt_f if gt_f <= 1.0 else (gt_f / 100.0)
                self._glass_transparency = max(10, min(95, int(round(gt_f * 100.0)) if gt_f <= 1.0 else int(gt_f)))
            if safe_mode is not None:
                self._safe_mode = bool(safe_mode)
            if disable_continuous_animations is not None:
                self._disable_continuous = bool(disable_continuous_animations)

        @property
        def aqua_theme(self) -> str:
            return self._aqua_theme_display

        @property
        def animation_intensity(self) -> str:
            return self._animation_intensity

        @property
        def glass_transparency(self) -> float:
            return self._glass_transparency_float

        @property
        def view_mode(self) -> str:
            return self._view_mode

        def clear_search_and_filters(self) -> List[HistoryEntry]:
            self._search_query = ""
            self._current_filter = "all"
            return self.refresh_gallery()

        def clear_non_favorites(self, *, confirm: bool = False) -> int:
            return self.prompt_clear_history(confirm=confirm, keep_favorites=True)

        def request_new_capture(self) -> None:
            self.newCaptureRequested.emit()

        def set_view_mode(self, mode: str) -> str:
            self._view_mode = "list" if str(mode or "grid").strip().lower() == "list" else "grid"
            return self._view_mode

        def show(self) -> None:
            self._closing = False
            self._visible = True
            self.refresh_gallery()

        def raise_(self) -> None:
            pass

        def activateWindow(self) -> None:
            pass

        def isVisible(self) -> bool:
            return self._visible

        def close(self) -> None:
            self._closing = True
            self._visible = False
            with self._async_lock:
                self._preview_load_gen += 1
                self._gallery_load_gen += 1
                self._pending_preview_request = None
                self._pending_thumb_rows.clear()
                self._inflight_thumb_cids.clear()
                self._completed_preview_decodes.clear()
                self._completed_thumb_decodes.clear()
            self._preview_worker_event.set()
            self._thumb_worker_event.set()
            for th in (self._preview_worker_thread, self._thumb_worker_thread):
                if th is not None and th.is_alive() and th is not threading.current_thread():
                    th.join(timeout=0.15)

        def set_search_query(self, query: str) -> List[HistoryEntry]:
            self._search_query = str(query or "").strip()
            return self.refresh_gallery()

        def set_filter_mode(self, mode: str) -> List[HistoryEntry]:
            self._current_filter = str(mode or "all").strip().lower()
            for k, btn in self.category_buttons.items():
                btn.setChecked(k == self._current_filter)
            return self.refresh_gallery()

        def set_sort_mode(self, sort_by: str) -> List[HistoryEntry]:
            self._current_sort = str(sort_by or "newest").strip().lower()
            return self.refresh_gallery()

        def refresh_gallery(self, preserve_capture_id: Optional[str] = None) -> List[HistoryEntry]:
            target_cid = preserve_capture_id or self._selected_capture_id
            entries = self.store.search_entries(
                self._search_query,
                filter_mode=self._current_filter,
                sort_by=self._current_sort,
            )
            self._entry_meta_by_id = {e.capture_id: e for e in entries}
            counts = self.store.compute_category_counts()
            self.category_counts = dict(counts)
            self.current_entries = list(entries)
            total_all = counts.get("all", 0)
            if entries:
                self.empty_state_kind = "none"
            elif total_all == 0:
                self.empty_state_kind = "empty"
            else:
                self.empty_state_kind = "no_results"
            for code, btn in self.category_buttons.items():
                btn.setText(f"{code} ({counts.get(code, 0)})")

            with self._async_lock:
                self._gallery_load_gen += 1
                cur_gen = self._gallery_load_gen
                self._pending_thumb_rows = [
                    (idx, e.capture_id, cur_gen)
                    for idx, e in enumerate(entries)
                    if e.capture_id not in self._thumb_pixmap_cache
                ]
                self._completed_thumb_decodes.clear()

            if entries:
                if target_cid and any(e.capture_id == target_cid for e in entries):
                    self.selected_capture_id = target_cid
                else:
                    self.selected_capture_id = entries[0].capture_id
                self._prioritize_visible_thumbnails()
            else:
                self.selected_capture_id = None
            return entries

        def _current_entry(self) -> Optional[HistoryEntry]:
            if not self._selected_capture_id:
                return None
            return self._entry_meta_by_id.get(self._selected_capture_id) or self.store.get_entry(self._selected_capture_id)

        def reopen_current_in_editor(self) -> bool:
            entry = self._current_entry()
            if entry is None:
                return False
            pil_img = self.store.load_full_image_pil(entry.capture_id)
            if pil_img is None:
                return False
            self.reopenInEditorRequested.emit(pil_img, entry.display_title)
            return True

        def pin_current_entry(self) -> bool:
            entry = self._current_entry()
            if entry is None:
                return False
            pil_img = self.store.load_full_image_pil(entry.capture_id)
            if pil_img is None:
                return False
            self.pinEntryRequested.emit(pil_img, entry.display_title, entry.capture_id)
            self.pinImageRequested.emit(pil_img, entry.display_title)
            return True

        def duplicate_pin_current_entry(self) -> bool:
            entry = self._current_entry()
            if entry is None:
                return False
            pil_img = self.store.load_full_image_pil(entry.capture_id)
            if pil_img is None:
                return False
            self.pinEntryRequested.emit(pil_img, f"{entry.display_title} (Copy)", "")
            self.pinImageRequested.emit(pil_img, f"{entry.display_title} (Copy)")
            return True

        def copy_current_image(self) -> bool:
            entry = self._current_entry()
            if entry is None:
                return False
            return self.store.load_full_image_pil(entry.capture_id) is not None

        def copy_current_text(self) -> str:
            entry = self._current_entry()
            if entry is None:
                return ""
            if entry.ocr_text.strip():
                return entry.ocr_text.strip()
            if self._ocr_runner is not None:
                pil_img = self.store.load_full_image_pil(entry.capture_id)
                if pil_img is not None:
                    txt = (self._ocr_runner(pil_img) or "").strip()
                    if txt:
                        self.store.update_ocr_text(entry.capture_id, txt)
                    return txt
            return ""

        def save_current_as(self, dest_path: Path) -> Optional[Path]:
            entry = self._current_entry()
            if entry is None:
                return None
            pil_img = self.store.load_full_image_pil(entry.capture_id)
            if pil_img is None:
                return None
            target = Path(dest_path)
            _atomic_save_pil_png(pil_img, target)
            return target

        def toggle_current_favorite(self) -> Optional[bool]:
            entry = self._current_entry()
            if entry is None:
                return None
            new_fav = not entry.favorite
            self.store.set_favorite(entry.capture_id, new_fav)
            self.refresh_gallery(preserve_capture_id=entry.capture_id)
            return new_fav

        def rename_current_entry(self, new_title: str) -> bool:
            entry = self._current_entry()
            if entry is None:
                return False
            ok = self.store.update_title(entry.capture_id, new_title)
            self.refresh_gallery(preserve_capture_id=entry.capture_id)
            return ok

        def open_current_file_location(self) -> Optional[Path]:
            entry = self._current_entry()
            if entry is None or entry.resolved_image_path is None:
                return None
            self._last_opened_location = entry.resolved_image_path
            return entry.resolved_image_path

        def delete_selected_items(self, *, confirm: bool = False) -> int:
            _ = confirm
            targets = list(self.selected_capture_ids) if self.selected_capture_ids else (
                [self._selected_capture_id] if self._selected_capture_id else []
            )
            if not targets:
                return 0
            for cid in targets:
                self._thumb_pixmap_cache.pop(cid, None)
                self._preview_pixmap_cache.pop(cid, None)
            deleted = self.store.delete_entries(targets)
            self.selected_capture_ids.clear()
            self.refresh_gallery()
            return deleted

        def prompt_clear_history(self, *, confirm: bool = False, keep_favorites: bool = False) -> int:
            _ = confirm
            if not keep_favorites:
                self._thumb_pixmap_cache.clear()
                self._preview_pixmap_cache.clear()
            cleared = self.store.clear_history(keep_favorites=keep_favorites)
            self.refresh_gallery()
            return cleared
