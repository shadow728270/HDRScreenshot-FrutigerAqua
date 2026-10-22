#!/usr/bin/env python3
"""
HDRSnip Fusion - Frutiger Aero / Aqua Liquid Glass Edition
Game-Safe, HDR-Aware Screenshot & Annotation Tool for Windows 10/11
====================================================================================
Features:
  1. Authentic Frutiger Aero / Frutiger Aqua Translucent Acrylic & Living Liquid UI:
     - Real-time frosted glass backdrop blur sampled directly from the screen behind
       the floating toolbar and dimensions capsule (cached as a static base pixmap)
     - Living multi-layered water animation inside the glass toolbar with incommensurate
       sine/bezier wave currents, refracted sunlight caustics, wave-crest intersection
       glows, and drifting curved-surface specular reflections (~30 FPS shared clock)
     - 3D skeuomorphic glossy Aqua gel pill buttons with staggered idle reflections,
       smooth 240ms OutCubic hover specular sweeps, expressive ~102ms jelly compression
       (~9.0% vertical squash + ~5.0% horizontal volume compensation at Medium intensity)
       + ~405ms damped elastic rebound (~3.5% vertical overshoot), and localized water ripples
     - Glossy Aqua HDR slider with luminous active track trail and 340ms release settling
     - 4-level persistent Animation Intensity setting (Off, Subtle, Medium, High)
       that applies immediately and uses zero CPU when idle in the system tray
  2. Lives in the Windows Taskbar Hidden Icons (System Tray) with persistent config,
     single-instance mutex guard, "Open Screenshots Folder", and Windows Startup toggle.
  3. Configurable Global Hotkey via Win32 RegisterHotKey (anti-cheat friendly, no LL hooks).
  4. Captures the GPU framebuffer BEFORE showing any UI so fullscreen games never
     minimize before capture, using DXGI Desktop Duplication in 64-bit half-float
     scRGB (DXGI_FORMAT_R16G16B16A16_FLOAT).
  5. True Multi-GPU & Multi-Monitor aware: enumerates all DXGI adapters (IDXGIFactory1)
     and outputs to find the exact GPU and monitor holding your cursor, queries its
     Windows SDR white level via DisplayConfigGetDeviceInfo (DISPLAYCONFIG_SDR_WHITE_LEVEL),
     and applies single-stage C1-continuous highlight roll-off for Auto-HDR / native HDR.
  6. Refuses unsafe SDR fallback when Windows reports HDR enabled (or unknown) unless
     explicitly enabled in Settings, preventing accidental blown-out screenshots.

Requirements (Windows 10/11, Python 3.10+):
  pip install PyQt6 numpy Pillow
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime
import gc
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import weakref
import webbrowser
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageFilter

# Only import PyQt6 when running the GUI (allows headless unit testing of HDR math)
try:
    from PyQt6.QtCore import (
        QEasingCurve,
        QElapsedTimer,
        QObject,
        QPoint,
        QPointF,
        QRect,
        QRectF,
        QRunnable,
        QSize,
        Qt,
        QThreadPool,
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
        QGuiApplication,
        QIcon,
        QImage,
        QKeySequence,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
        QPolygonF,
        QRadialGradient,
    )
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QDialog,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGraphicsDropShadowEffect,
        QHBoxLayout,
        QInputDialog,
        QKeySequenceEdit,
        QLabel,
        QLineEdit,
        QMenu,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSlider,
        QSpinBox,
        QStyle,
        QStyleOptionSlider,
        QSystemTrayIcon,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    HAS_QT = True
except ImportError:
    HAS_QT = False


# =============================================================================
# 1. CONFIGURATION, DPI AWARENESS & DIAGNOSTIC LOGGING
# =============================================================================

import traceback

APP_VERSION: str = "0.1.1"
GITHUB_REPO_OWNER: str = "shadow728270"
GITHUB_REPO_NAME: str = "HDRScreenshot-FrutigerAqua"
GITHUB_REPO_URL: str = f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
GITHUB_RELEASES_PAGE_URL: str = f"{GITHUB_REPO_URL}/releases"
GITHUB_LATEST_RELEASE_API_URL: str = (
    f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"
)
EXPECTED_RELEASE_ASSET_NAME: str = "HDRSnipFusion.exe"
UPDATE_CHECK_INTERVAL_SEC: float = 86400.0  # Check roughly once per 24 hours
UPDATE_STARTUP_DELAY_MS: int = 4500         # Delay first background check until tray is ready
MIN_EXE_SIZE_BYTES: int = 1_048_576         # 1 MB minimum sanity bound for packaged EXE
MAX_EXE_SIZE_BYTES: int = 367_001_600       # 350 MB maximum sanity bound
MAX_API_RESPONSE_BYTES: int = 2_097_152     # 2 MB cap for GitHub JSON metadata
REQUIRE_AUTHENTICODE_SIGNATURE: bool = False
ALLOWED_GITHUB_HOSTS: Tuple[str, ...] = (
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "codeload.github.com",
)

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "HDRSnip Fusion"
CONFIG_FILE = CONFIG_DIR / "config.json"
DIAGNOSTIC_LOG_FILE = CONFIG_DIR / "diagnostics.log"
DIAGNOSTIC_LOG_BACKUP_FILE = CONFIG_DIR / "diagnostics.log.1"
DEFAULT_SAVE_DIR = Path.home() / "Pictures" / "HDRSnip Fusion"
LOCAL_UPDATE_ROOT_DIR = (
    Path(os.environ.get("LOCALAPPDATA", os.environ.get("APPDATA", Path.home())))
    / "HDRSnip Fusion"
    / "updates"
)

# Developer / environment overrides for Diagnostic Safe Mode and persistent logging
ENV_SAFE_MODE: bool = os.environ.get("HDRSNIP_SAFE_MODE", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
) or ("--safe-mode" in sys.argv)

ENV_DIAG_LOG_OVERRIDE: Optional[bool] = (
    True
    if os.environ.get("HDRSNIP_DIAGNOSTIC_LOG", "").strip().lower()
    in ("1", "true", "yes", "on")
    else (
        False
        if os.environ.get("HDRSNIP_DIAGNOSTIC_LOG", "").strip().lower()
        in ("0", "false", "no", "off")
        else None
    )
)


class DiagnosticLogger:
    r"""
    Persistent, bounded, thread-safe diagnostic logger writing to:
      %APPDATA%\HDRSnip Fusion\diagnostics.log
    Designed specifically for investigating hard Windows freezes and GPU/DXGI interactions:
      - Bounded file size (1.5 MB max, rotates to diagnostics.log.1) so it never grows unbounded.
      - Never logs per-frame animation ticks.
      - Flushes every entry and performs os.fsync() on critical milestones (pre-capture,
        device creation, duplication, frame acquisition, release, and errors) so recent
        milestones are maximally likely to survive a forced hardware restart.
    """

    MAX_BYTES: int = 1_572_864  # 1.5 MB cap per log file

    def __init__(self, log_path: Path = DIAGNOSTIC_LOG_FILE) -> None:
        self.log_path = Path(log_path)
        self.backup_path = self.log_path.with_name(self.log_path.name + ".1")
        self.enabled: bool = (
            ENV_DIAG_LOG_OVERRIDE if ENV_DIAG_LOG_OVERRIDE is not None else True
        )
        self._lock = threading.RLock()
        self._last_anim_state: Optional[str] = None

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            if ENV_DIAG_LOG_OVERRIDE is not None:
                self.enabled = ENV_DIAG_LOG_OVERRIDE
            else:
                self.enabled = bool(enabled)

    def _rotate_if_needed(self) -> None:
        try:
            if self.log_path.exists() and self.log_path.stat().st_size >= self.MAX_BYTES:
                if self.backup_path.exists():
                    try:
                        self.backup_path.unlink()
                    except OSError:
                        pass
                self.log_path.replace(self.backup_path)
        except Exception:
            pass

    def log(
        self,
        category: str,
        message: str,
        *,
        level: str = "INFO",
        flush_disk: bool = False,
    ) -> None:
        if not self.enabled:
            return
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        pid = os.getpid()
        t_name = threading.current_thread().name
        line = f"[{now_str}] [PID:{pid}] [{t_name}] [{level}] [{category}] {message}\n"
        with self._lock:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed()
                with open(self.log_path, "a", encoding="utf-8", errors="replace") as fh:
                    fh.write(line)
                    fh.flush()
                    if flush_disk:
                        try:
                            os.fsync(fh.fileno())
                        except OSError:
                            pass
            except Exception:
                pass

    def milestone(
        self, category: str, message: str, *, flush_disk: bool = False
    ) -> None:
        """Logs a high-priority milestone (flush_disk=False by default to avoid latency spikes on critical path)."""
        self.log(category, message, level="MILESTONE", flush_disk=flush_disk)

    def warning(self, category: str, message: str) -> None:
        self.log(category, message, level="WARN", flush_disk=True)

    def error(
        self, category: str, message: str, exc: Optional[BaseException] = None
    ) -> None:
        if exc is not None:
            tb = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ).strip()
            full_msg = f"{message} | Exception: {type(exc).__name__}: {exc}\n{tb}"
        else:
            full_msg = message
        self.log(category, full_msg, level="ERROR", flush_disk=True)

    def log_animation_state(self, state_desc: str) -> None:
        """Logs animation clock start/stop transitions without logging individual frames."""
        with self._lock:
            if state_desc == self._last_anim_state:
                return
            self._last_anim_state = state_desc
        self.log("ANIMATION", state_desc, level="INFO", flush_disk=False)


DIAG_LOG = DiagnosticLogger()


class _SafeWindowlessStream:
    """
    Safe no-op / diagnostic fallback stream for PyInstaller `--onefile --noconsole`
    and `pythonw.exe` environments where `sys.stdout` or `sys.stderr` is `None`.
    Prevents `print()` or traceback formatting from raising `AttributeError`.
    """

    encoding: str = "utf-8"

    def write(self, text: str) -> int:
        return len(text) if isinstance(text, str) else 0

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def _ensure_safe_stdio() -> None:
    """Ensures sys.stdout and sys.stderr are never None in PyInstaller --noconsole builds."""
    if sys.stdout is None:
        sys.stdout = _SafeWindowlessStream()  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _SafeWindowlessStream()  # type: ignore[assignment]


_ensure_safe_stdio()


def install_diagnostic_excepthooks() -> None:
    """Installs sys.excepthook and threading.excepthook so unhandled exceptions are persisted."""
    orig_sys_hook = sys.excepthook

    def _sys_hook(exc_type, exc_val, exc_tb):
        try:
            tb_str = "".join(traceback.format_exception(exc_type, exc_val, exc_tb)).strip()
            DIAG_LOG.log(
                "UNCAUGHT_EXCEPTION",
                f"Unhandled main/thread exception:\n{tb_str}",
                level="CRITICAL",
                flush_disk=True,
            )
        except Exception:
            pass
        try:
            if sys.stderr is not None and not isinstance(sys.stderr, _SafeWindowlessStream):
                orig_sys_hook(exc_type, exc_val, exc_tb)
        except Exception:
            pass

    sys.excepthook = _sys_hook

    if hasattr(threading, "excepthook"):
        orig_thread_hook = threading.excepthook

        def _thread_hook(args):
            try:
                tb_str = "".join(
                    traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback
                    )
                ).strip()
                t_name = getattr(args.thread, "name", "unknown")
                DIAG_LOG.log(
                    "THREAD_EXCEPTION",
                    f"Unhandled exception in thread '{t_name}':\n{tb_str}",
                    level="CRITICAL",
                    flush_disk=True,
                )
            except Exception:
                pass
            try:
                if sys.stderr is not None and not isinstance(sys.stderr, _SafeWindowlessStream):
                    orig_thread_hook(args)
            except Exception:
                pass

        threading.excepthook = _thread_hook


install_diagnostic_excepthooks()

# WeakSet tracking live SnipOverlayWindow instances to verify zero leaked editor windows
_LIVE_OVERLAY_INSTANCES: "weakref.WeakSet[Any]" = weakref.WeakSet()
_ACTIVE_TONE_WORKER_LOCK = threading.Lock()
_ACTIVE_TONE_WORKERS: int = 0


def _adjust_active_tone_workers(delta: int) -> int:
    global _ACTIVE_TONE_WORKERS
    with _ACTIVE_TONE_WORKER_LOCK:
        _ACTIVE_TONE_WORKERS = max(0, _ACTIVE_TONE_WORKERS + int(delta))
        return _ACTIVE_TONE_WORKERS


def get_active_tone_workers() -> int:
    with _ACTIVE_TONE_WORKER_LOCK:
        return _ACTIVE_TONE_WORKERS


# Lightweight multi-monitor diagnostic flag (disabled by default).
# Set DEBUG_MONITORS = True or environment variable HDRSNIP_DEBUG_MONITORS=1 to log
# physical cursor, Win32 HMONITOR, DXGI adapter/output, Qt screen, and DPI mapping details.
DEBUG_MONITORS: bool = os.environ.get("HDRSNIP_DEBUG_MONITORS", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _debug_monitor_log(message: str) -> None:
    """Prints single-shot monitor/coordinate diagnostic lines when DEBUG_MONITORS is enabled."""
    if DEBUG_MONITORS:
        print(f"[HDRSnip Fusion • DEBUG_MONITORS] {message}")


# Lightweight performance & memory telemetry flag (disabled by default, zero overhead when off).
# Set DEBUG_PERFORMANCE = True or environment variable HDRSNIP_DEBUG_PERF=1 to log
# animation FPS, toolbar paint timings, capture-to-overlay latency, and buffer cleanup stats.
DEBUG_PERFORMANCE: bool = os.environ.get("HDRSNIP_DEBUG_PERF", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _debug_perf_log(message: str) -> None:
    """Prints performance and memory lifecycle diagnostics when DEBUG_PERFORMANCE is enabled."""
    if DEBUG_PERFORMANCE:
        print(f"[HDRSnip Fusion • DEBUG_PERF] {message}")


@dataclass
class PerformanceTelemetry:
    """
    Lightweight, zero-dependency internal telemetry tracker (Phase 4).
    Separates direct wall-clock / byte measurements from Qt backing-store estimates:
      - Real Measurements:
        * measured_fps: Rolling 0.5s shared animation clock rate (FPS)
        * avg_toolbar_paint_ms / peak_toolbar_paint_ms: AeroGlassToolbar.paintEvent() CPU duration
        * avg_caustic_synth_ms / peak_caustic_synth_ms: 2D Voronoi raster + vector caustic CPU time
        * last_dxgi_acquire_ms: Framebuffer acquisition + GPU-to-CPU staging readback duration
        * last_capture_to_overlay_ms: End-to-end capture-to-overlay presentation latency
        * current_screenshot_bytes / peak_screenshot_bytes / last_freed_bytes: CapturedFrame NumPy RAM
        * retained_overlay_instances: Live SnipOverlayWindow objects in _LIVE_OVERLAY_INSTANCES
        * pending_worker_jobs: Active/pending ToneRenderJob tasks
        * active_animation_timers: Active QTimer / QVariantAnimation count across visible UI
      - Explicit Estimate:
        * estimated_qt_pixmap_bytes: Estimated 32-bpp backing store of active overlay QPixmaps
    """
    toolbar_paint_count: int = 0
    toolbar_paint_total_ms: float = 0.0
    toolbar_paint_peak_ms: float = 0.0
    last_toolbar_paint_ms: float = 0.0
    caustic_synth_count: int = 0
    caustic_synth_total_ms: float = 0.0
    caustic_synth_peak_ms: float = 0.0
    last_caustic_synth_ms: float = 0.0
    last_dxgi_acquire_ms: float = 0.0
    # Granular latency breakdown fields for the 9 stages:
    last_hotkey_to_handler_ms: float = 0.0
    last_monitor_enum_ms: float = 0.0
    last_d3d_device_init_ms: float = 0.0
    last_acquire_frame_ms: float = 0.0
    last_texture_readback_ms: float = 0.0
    last_tone_mapping_ms: float = 0.0
    last_pixmap_creation_ms: float = 0.0
    last_overlay_init_ms: float = 0.0
    last_time_to_first_paint_ms: float = 0.0
    last_bg_full_tone_map_ms: float = 0.0
    director_tick_count: int = 0
    director_window_start_sec: float = 0.0
    director_window_ticks: int = 0
    measured_fps: float = 0.0
    last_capture_to_overlay_ms: float = 0.0
    peak_screenshot_bytes: int = 0
    current_screenshot_bytes: int = 0
    last_buffer_lifetime_sec: float = 0.0
    last_freed_bytes: int = 0
    total_captures: int = 0
    total_releases: int = 0

    @property
    def avg_toolbar_paint_ms(self) -> float:
        if self.toolbar_paint_count <= 0:
            return 0.0
        return self.toolbar_paint_total_ms / float(self.toolbar_paint_count)

    @property
    def avg_caustic_synth_ms(self) -> float:
        if self.caustic_synth_count <= 0:
            return 0.0
        return self.caustic_synth_total_ms / float(self.caustic_synth_count)

    def record_director_tick(self, now_sec: float) -> None:
        self.director_tick_count += 1
        if self.director_window_start_sec <= 0.0:
            self.director_window_start_sec = now_sec
            self.director_window_ticks = 0
            return
        self.director_window_ticks += 1
        elapsed = now_sec - self.director_window_start_sec
        if elapsed >= 0.50:
            self.measured_fps = self.director_window_ticks / elapsed
            self.director_window_start_sec = now_sec
            self.director_window_ticks = 0

    def record_toolbar_paint(self, duration_ms: float) -> None:
        self.toolbar_paint_count += 1
        self.last_toolbar_paint_ms = float(duration_ms)
        self.toolbar_paint_total_ms += float(duration_ms)
        if duration_ms > self.toolbar_paint_peak_ms:
            self.toolbar_paint_peak_ms = float(duration_ms)

    def record_caustic_synth(self, duration_ms: float) -> None:
        self.caustic_synth_count += 1
        self.last_caustic_synth_ms = float(duration_ms)
        self.caustic_synth_total_ms += float(duration_ms)
        if duration_ms > self.caustic_synth_peak_ms:
            self.caustic_synth_peak_ms = float(duration_ms)

    def record_dxgi_acquire(self, duration_ms: float) -> None:
        self.last_dxgi_acquire_ms = max(0.0, float(duration_ms))

    def record_stage(self, stage_name: str, duration_ms: float) -> None:
        dur = max(0.0, float(duration_ms))
        if stage_name == "hotkey_to_handler":
            self.last_hotkey_to_handler_ms = dur
        elif stage_name == "monitor_enum":
            self.last_monitor_enum_ms = dur
        elif stage_name == "d3d_init":
            self.last_d3d_device_init_ms = dur
        elif stage_name == "acquire_frame":
            self.last_acquire_frame_ms = dur
        elif stage_name == "texture_readback":
            self.last_texture_readback_ms = dur
        elif stage_name == "tone_mapping":
            self.last_tone_mapping_ms = dur
        elif stage_name == "pixmap_creation":
            self.last_pixmap_creation_ms = dur
        elif stage_name == "overlay_init":
            self.last_overlay_init_ms = dur
        elif stage_name == "first_visible_paint":
            self.last_time_to_first_paint_ms = dur
        elif stage_name == "bg_full_tone_map":
            self.last_bg_full_tone_map_ms = dur

    def record_capture_allocated(self, nbytes: int) -> None:
        self.total_captures += 1
        self.current_screenshot_bytes += max(0, int(nbytes))
        if self.current_screenshot_bytes > self.peak_screenshot_bytes:
            self.peak_screenshot_bytes = self.current_screenshot_bytes
        _debug_perf_log(
            f"Allocated screenshot buffers: {nbytes / (1024 * 1024):.2f} MB "
            f"(current={self.current_screenshot_bytes / (1024 * 1024):.2f} MB, "
            f"peak={self.peak_screenshot_bytes / (1024 * 1024):.2f} MB)"
        )

    def record_capture_released(self, nbytes: int, lifetime_sec: float) -> None:
        self.total_releases += 1
        self.last_freed_bytes = max(0, int(nbytes))
        self.last_buffer_lifetime_sec = max(0.0, float(lifetime_sec))
        self.current_screenshot_bytes = max(
            0, self.current_screenshot_bytes - self.last_freed_bytes
        )
        _debug_perf_log(
            f"Released screenshot buffers: freed={self.last_freed_bytes / (1024 * 1024):.2f} MB "
            f"after {self.last_buffer_lifetime_sec:.2f}s "
            f"(remaining_active={self.current_screenshot_bytes / (1024 * 1024):.2f} MB, "
            f"avg_toolbar_paint={self.avg_toolbar_paint_ms:.3f} ms, "
            f"avg_caustic_synth={self.avg_caustic_synth_ms:.3f} ms, fps={self.measured_fps:.1f})"
        )

    def record_capture_to_overlay(self, latency_ms: float) -> None:
        self.last_capture_to_overlay_ms = max(0.0, float(latency_ms))
        _debug_perf_log(
            f"Capture-to-overlay latency: {self.last_capture_to_overlay_ms:.2f} ms"
        )

    def count_active_animation_timers(self) -> int:
        if not HAS_QT:
            return 0
        try:
            director = AeroAnimationDirector.instance()
            return director.count_active_timers()
        except Exception:
            return 0

    def retained_overlay_count(self) -> int:
        return sum(
            1
            for ov in list(_LIVE_OVERLAY_INSTANCES)
            if ov is not None and not getattr(ov, "_resources_released", True)
        )

    def estimated_qt_pixmap_bytes(self) -> int:
        est = 0
        for ov in list(_LIVE_OVERLAY_INSTANCES):
            if ov is not None and not getattr(ov, "_resources_released", True):
                bg = getattr(ov, "bg_pixmap", None)
                if bg is not None and not bg.isNull():
                    est += int(bg.width()) * int(bg.height()) * 4
        return est

    def snapshot(self) -> dict:
        return {
            "measured_fps": round(self.measured_fps, 2),
            "avg_toolbar_paint_ms": round(self.avg_toolbar_paint_ms, 3),
            "peak_toolbar_paint_ms": round(self.toolbar_paint_peak_ms, 3),
            "avg_caustic_synth_ms": round(self.avg_caustic_synth_ms, 3),
            "peak_caustic_synth_ms": round(self.caustic_synth_peak_ms, 3),
            "last_dxgi_acquire_ms": round(self.last_dxgi_acquire_ms, 2),
            "last_capture_to_overlay_ms": round(self.last_capture_to_overlay_ms, 2),
            "last_hotkey_to_handler_ms": round(self.last_hotkey_to_handler_ms, 2),
            "last_monitor_enum_ms": round(self.last_monitor_enum_ms, 2),
            "last_d3d_device_init_ms": round(self.last_d3d_device_init_ms, 2),
            "last_acquire_frame_ms": round(self.last_acquire_frame_ms, 2),
            "last_texture_readback_ms": round(self.last_texture_readback_ms, 2),
            "last_tone_mapping_ms": round(self.last_tone_mapping_ms, 2),
            "last_pixmap_creation_ms": round(self.last_pixmap_creation_ms, 2),
            "last_overlay_init_ms": round(self.last_overlay_init_ms, 2),
            "last_time_to_first_paint_ms": round(self.last_time_to_first_paint_ms, 2),
            "last_bg_full_tone_map_ms": round(self.last_bg_full_tone_map_ms, 2),
            "active_animation_timers": self.count_active_animation_timers(),
            "retained_overlay_instances": self.retained_overlay_count(),
            "pending_worker_jobs": get_active_tone_workers(),
            "current_screenshot_bytes": self.current_screenshot_bytes,
            "peak_screenshot_bytes": self.peak_screenshot_bytes,
            "estimated_qt_pixmap_bytes": self.estimated_qt_pixmap_bytes(),
            "last_freed_bytes": self.last_freed_bytes,
            "last_buffer_lifetime_sec": round(self.last_buffer_lifetime_sec, 3),
            "total_captures": self.total_captures,
            "total_releases": self.total_releases,
        }


PERF_TELEMETRY = PerformanceTelemetry()


DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE = ctypes.c_void_p(-3)
PROCESS_PER_MONITOR_DPI_AWARE = 2
MDT_EFFECTIVE_DPI = 0
MONITOR_DEFAULTTONULL = 0
MONITOR_DEFAULTTOPRIMARY = 1
MONITOR_DEFAULTTONEAREST = 2
MONITORINFOF_PRIMARY = 0x00000001


def ensure_per_monitor_dpi_awareness() -> None:
    """
    Configures the Windows process and current thread for Per-Monitor DPI Awareness V2
    BEFORE QApplication or Win32 cursor/monitor APIs run, preventing DWM coordinate
    virtualization across mixed-DPI multi-monitor setups.
    Explicitly declares 64-bit ctypes signatures before calling SetProcessDpiAwarenessContext.
    """
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
            if not user32.SetProcessDpiAwarenessContext(
                DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            ):
                user32.SetProcessDpiAwarenessContext(
                    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE
                )
    except Exception:
        pass
    try:
        shcore = ctypes.windll.shcore
        if hasattr(shcore, "SetProcessDpiAwareness"):
            shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
            shcore.SetProcessDpiAwareness.restype = ctypes.c_long
            shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
    except Exception:
        pass
    try:
        user32 = ctypes.windll.user32
        if hasattr(user32, "SetThreadDpiAwarenessContext"):
            user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            user32.SetThreadDpiAwarenessContext(
                DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            )
    except Exception:
        pass


# Initialize Per-Monitor DPI Awareness V2 immediately upon module load on Windows
ensure_per_monitor_dpi_awareness()

ANIMATION_INTENSITY_LEVELS = ("off", "subtle", "medium", "high")
ANIMATION_INTENSITY_SCALES = {
    "off": 0.0,
    "subtle": 0.50,
    "medium": 1.00,
    "high": 1.45,
}


def get_animation_intensity_scale(level: str) -> float:
    """Maps a persistent animation intensity name to its numeric multiplier."""
    return ANIMATION_INTENSITY_SCALES.get(str(level).strip().lower(), 1.00)


@dataclass(frozen=True)
class AquaIntensityProfile:
    """
    Art-directed optical parameters for Frutiger Aqua 3.2 animation intensities.
    Decouples animation intensity from uncontrolled increases in brightness:
      - `Off`: Clean static Frutiger Aqua glass with zero procedural caustics.
      - `Subtle`: Gentle atmospheric water movement, restrained caustics, high readability.
      - `Medium`: Reference visual balance — crystal-clear turquoise water, thin branching
        filaments, and ~12-14% softer white/cyan peaks so highlights never clip or glare.
      - `High`: Prioritizes optical complexity and 3-layer depth over peak brightness —
        richer secondary caustic sub-structures, wider filament thickness variation,
        stronger 2D background refraction with subtle chromatic prism dispersion, deeper
        basin-to-surface layer separation, and crisp jewel-like intersection glints while
        keeping peak highlight brightness within ~5% of refined Medium.
    """

    level: str
    is_active: bool
    motion_scale: float
    highlight_gain: float
    highlight_shoulder: float
    secondary_structure: float
    filament_variance: float
    refraction_scale: float
    chromatic_refraction: float
    depth_separation: float
    surface_reflection_gain: float
    glint_specificity: float


def resolve_aqua_intensity_profile(intensity_scale: float) -> AquaIntensityProfile:
    """
    Resolves a numeric `intensity_scale` (0.0=Off, 0.50=Subtle, 1.00=Medium, 1.45=High)
    into decoupled Frutiger Aqua 3.2 optical parameters with smooth interpolation.
    """
    eff = float(intensity_scale)
    if eff <= 0.0:
        return AquaIntensityProfile(
            level="off",
            is_active=False,
            motion_scale=0.0,
            highlight_gain=0.36,
            highlight_shoulder=0.30,
            secondary_structure=0.0,
            filament_variance=0.0,
            refraction_scale=0.0,
            chromatic_refraction=0.0,
            depth_separation=0.85,
            surface_reflection_gain=0.82,
            glint_specificity=0.0,
        )

    # Anchor presets: Subtle (0.50), Medium (1.00), High (1.45)
    if eff <= 0.55:
        u = max(0.0, min(1.0, eff / 0.50))
        return AquaIntensityProfile(
            level="subtle",
            is_active=True,
            motion_scale=0.60 + 0.18 * u,
            highlight_gain=0.52 + 0.16 * u,
            highlight_shoulder=0.28,
            secondary_structure=0.40 + 0.12 * u,
            filament_variance=0.45 + 0.13 * u,
            refraction_scale=0.58 + 0.18 * u,
            chromatic_refraction=0.0,
            depth_separation=0.72 + 0.06 * u,
            surface_reflection_gain=0.72 + 0.06 * u,
            glint_specificity=0.52 + 0.13 * u,
        )

    if eff <= 1.05:
        # Interpolate Subtle (0.50) -> Medium (1.00)
        u = max(0.0, min(1.0, (eff - 0.50) / 0.50))
        return AquaIntensityProfile(
            level="medium",
            is_active=True,
            motion_scale=0.78 + 0.24 * u,         # 1.02 at Medium
            highlight_gain=0.68 + 0.36 * u,       # 1.04 at Medium (~14% softer peaks than 1.22)
            highlight_shoulder=0.28 - 0.02 * u,   # 0.26 at Medium (prevents raster+vector clipping)
            secondary_structure=0.52 + 0.48 * u,  # 1.00 at Medium
            filament_variance=0.58 + 0.42 * u,    # 1.00 at Medium
            refraction_scale=0.76 + 0.40 * u,     # 1.16 at Medium
            chromatic_refraction=0.08 * u,        # 0.08 at Medium
            depth_separation=0.78 + 0.22 * u,     # 1.00 at Medium
            surface_reflection_gain=0.78 + 0.22 * u,  # 1.00 at Medium
            glint_specificity=0.65 + 0.35 * u,    # 1.00 at Medium
        )

    # Interpolate Medium (1.00) -> High (1.45)
    # Note how highlight_gain increases by only +4.8% (1.04 -> 1.09) while highlight_shoulder
    # increases (0.26 -> 0.30), whereas secondary_structure (+68%), filament_variance (+72%),
    # refraction_scale (+33%), chromatic_refraction, and depth_separation (+48%) expand!
    u = max(0.0, min(1.25, (eff - 1.00) / 0.45))
    return AquaIntensityProfile(
        level="high",
        is_active=True,
        motion_scale=1.02 + 0.08 * u,             # 1.10 at High (same calm organic speed)
        highlight_gain=1.04 + 0.05 * u,           # 1.09 at High (controlled peak brightness!)
        highlight_shoulder=0.26 + 0.04 * u,       # 0.30 at High (stronger highlight roll-off)
        secondary_structure=1.00 + 0.68 * u,      # 1.68 at High (richer secondary caustics)
        filament_variance=1.00 + 0.72 * u,        # 1.72 at High (wider filament width range)
        refraction_scale=1.16 + 0.38 * u,         # 1.54 at High (more pronounced 2D refraction)
        chromatic_refraction=0.08 + 0.20 * u,     # 0.28 at High (subtle R/B prism dispersion)
        depth_separation=1.00 + 0.48 * u,         # 1.48 at High (clear deep/mid/surface layering)
        surface_reflection_gain=1.00 + 0.35 * u,  # 1.35 at High (multi-rib surface reflections)
        glint_specificity=1.00 + 0.42 * u,        # 1.42 at High (crisp localized glints)
    )


@dataclass
class AppConfig:
    hotkey_str: str = "Ctrl+Shift+X"
    # Tone mapping mode:
    #   "sdr_exact_knee" = Exact SDR White Level match + smooth highlight shoulder (Best for Auto-HDR & Desktop)
    #   "reinhard_luma"  = Luminance-preserving extended Reinhard
    #   "aces_filmic"    = ACES Filmic HDR curve
    tone_map_mode: str = "sdr_exact_knee"
    # Manual override for SDR nits (0 = auto-detect from Windows DisplayConfig)
    manual_sdr_nits: float = 0.0
    # Soft knee start (0.80 means 0..80% of SDR white is 1:1 linear, highlights >80% smoothly roll off)
    knee_start: float = 0.80
    # Max HDR headroom in multiples of SDR white (e.g. 6.0 = 1200 nits when SDR white is 200 nits)
    max_headroom: float = 6.0
    # Fix Windows 11 Auto-HDR piecewise sRGB -> Gamma 2.2 washed-out shadows
    auto_hdr_gamma22_fix: bool = False
    # Delay in ms before showing overlay (0 = instant after GPU capture)
    overlay_delay_ms: int = 0
    # Explicit opt-in for fallback to ordinary SDR capture; unsafe for HDR screenshots
    allow_sdr_fallback: bool = False
    # Optional startup at user logon (HKCU Run, no admin required)
    start_with_windows: bool = False
    # Optional renormalization so pure 1.0 SDR reference white hits 255 even with soft knee
    boost_sdr_whites: bool = False
    # Liquid glass & gel animation intensity: "off", "subtle", "medium" (default), "high"
    animation_intensity: str = "medium"
    # Glass & gel transparency percentage (10 = dense aero glass, 72 = crystal clear default, 95 = ultra-sheer water)
    glass_transparency: int = 72
    # Default tool and color
    default_color: str = "#00E5FF"
    default_thickness: int = 3
    save_directory: str = str(DEFAULT_SAVE_DIR)
    # GitHub Automatic Updater preferences (v0.1.1+)
    auto_check_updates: bool = True
    auto_install_updates: bool = False
    last_update_check_epoch: float = 0.0
    declined_update_version: str = ""
    staged_update_version: str = ""
    staged_update_path: str = ""
    staged_update_sha256: str = ""
    # Stability & Diagnostic Safe Mode settings (Phase 1 Stability Investigation)
    enable_diagnostic_logging: bool = True
    diagnostic_safe_mode: bool = False
    disable_continuous_animations: bool = False
    disable_native_hdr_capture: bool = False
    disable_async_tone_workers: bool = False
    disable_dwm_acrylic_blur: bool = False

    @property
    def is_safe_mode_active(self) -> bool:
        return bool(self.diagnostic_safe_mode or ENV_SAFE_MODE)

    @property
    def effective_animations_disabled(self) -> bool:
        return bool(
            self.is_safe_mode_active
            or self.disable_continuous_animations
            or self.animation_intensity == "off"
        )

    @property
    def effective_decorative_effects_disabled(self) -> bool:
        return bool(self.is_safe_mode_active or self.animation_intensity == "off")

    @property
    def effective_async_workers_disabled(self) -> bool:
        return bool(self.is_safe_mode_active or self.disable_async_tone_workers)

    @property
    def effective_dwm_acrylic_disabled(self) -> bool:
        return bool(self.is_safe_mode_active or self.disable_dwm_acrylic_blur)

    @property
    def effective_animation_intensity(self) -> str:
        if self.effective_animations_disabled:
            return "off"
        return (
            self.animation_intensity
            if self.animation_intensity in ANIMATION_INTENSITY_LEVELS
            else "medium"
        )

    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        try:
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
                filtered = {k: v for k, v in data.items() if k in valid_keys}
                if "animation_intensity" in filtered:
                    val = str(filtered["animation_intensity"]).strip().lower()
                    filtered["animation_intensity"] = (
                        val if val in ANIMATION_INTENSITY_LEVELS else "medium"
                    )
                if "glass_transparency" in filtered:
                    try:
                        filtered["glass_transparency"] = max(
                            10, min(95, int(filtered["glass_transparency"]))
                        )
                    except Exception:
                        filtered["glass_transparency"] = 72
                if "save_directory" in filtered:
                    raw_dir = str(filtered["save_directory"] or "").strip()
                    filtered["save_directory"] = (
                        raw_dir if raw_dir else str(DEFAULT_SAVE_DIR)
                    )
                if "auto_check_updates" in filtered:
                    filtered["auto_check_updates"] = bool(filtered["auto_check_updates"])
                if "auto_install_updates" in filtered:
                    filtered["auto_install_updates"] = bool(
                        filtered["auto_install_updates"]
                    )
                if "last_update_check_epoch" in filtered:
                    try:
                        filtered["last_update_check_epoch"] = max(
                            0.0, float(filtered["last_update_check_epoch"])
                        )
                    except Exception:
                        filtered["last_update_check_epoch"] = 0.0
                for str_key in (
                    "declined_update_version",
                    "staged_update_version",
                    "staged_update_path",
                    "staged_update_sha256",
                ):
                    if str_key in filtered:
                        filtered[str_key] = str(filtered[str_key] or "").strip()
                cfg = cls(**filtered)
        except Exception as exc:
            print(f"[HDRSnip Fusion] Warning: Failed to load config: {exc}")
            DIAG_LOG.error("CONFIG", "Failed to load config.json; using defaults", exc)
        if ENV_SAFE_MODE:
            cfg.diagnostic_safe_mode = True
        DIAG_LOG.set_enabled(cfg.enable_diagnostic_logging)
        return cfg

    def save(self) -> None:
        try:
            if self.animation_intensity not in ANIMATION_INTENSITY_LEVELS:
                self.animation_intensity = "medium"
            DIAG_LOG.set_enabled(self.enable_diagnostic_logging)
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(
                json.dumps(self.__dict__, indent=2), encoding="utf-8"
            )
            DIAG_LOG.log(
                "CONFIG",
                f"Saved configuration (safe_mode={self.is_safe_mode_active}, "
                f"anim={self.animation_intensity}, disable_cont_anim={self.disable_continuous_animations}, "
                f"disable_hdr_dxgi={self.disable_native_hdr_capture}, "
                f"disable_workers={self.disable_async_tone_workers}, "
                f"disable_acrylic={self.disable_dwm_acrylic_blur})",
            )
        except Exception as exc:
            print(f"[HDRSnip Fusion] Warning: Failed to save config: {exc}")
            DIAG_LOG.error("CONFIG", "Failed to save config.json", exc)


# =============================================================================
# 2. WINDOWS DISPLAYCONFIG API: PER-MONITOR SDR WHITE LEVEL & HDR STATUS
# =============================================================================

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32)]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("size", wintypes.UINT),
        ("adapterId", LUID),
        ("id", wintypes.UINT),
    ]


class DISPLAYCONFIG_SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", ctypes.c_wchar * 32),
    ]


class DISPLAYCONFIG_SDR_WHITE_LEVEL(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("SDRWhiteLevel", ctypes.c_uint32),  # 1000 = 80 nits (1.0 in scRGB)
    ]


class DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value", wintypes.UINT),
        ("colorEncoding", wintypes.UINT),
        ("bitsPerColor", wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("statusFlags", wintypes.UINT),
    ]


class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.UINT), ("Denominator", wintypes.UINT)]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("outputTechnology", ctypes.c_int),
        ("rotation", ctypes.c_int),
        ("scaling", ctypes.c_int),
        ("refreshRate", DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", ctypes.c_int),
        ("targetAvailable", ctypes.c_int32),
        ("statusFlags", wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", wintypes.UINT),
    ]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    # Note: In Windows SDK wingdi.h, DISPLAYCONFIG_MODE_INFO contains a union whose
    # DISPLAYCONFIG_TARGET_MODE member starts with UINT64 pixelRate (8-byte aligned).
    # Using c_uint64 * 6 (48 bytes) guarantees both exact 64-byte struct size AND
    # 8-byte struct alignment on both 32-bit and 64-bit Windows.
    _fields_ = [
        ("infoType", ctypes.c_int),
        ("id", wintypes.UINT),
        ("adapterId", LUID),
        ("dummy", ctypes.c_uint64 * 6),
    ]


_WIN32_SIGNATURES_CONFIGURED: bool = False


def _ensure_win32_ctypes_signatures() -> None:
    """
    Explicitly declares 64-bit-safe argtypes and restype for all Win32, DXGI, D3D11,
    and SHCore ctypes functions so pointer arguments (especially NULL/None pointers
    on x64 stack slots) are never truncated to 32-bit c_int values.
    """
    global _WIN32_SIGNATURES_CONFIGURED
    if _WIN32_SIGNATURES_CONFIGURED or sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        user32.GetDisplayConfigBufferSizes.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(wintypes.UINT),
        ]
        user32.GetDisplayConfigBufferSizes.restype = wintypes.LONG

        user32.QueryDisplayConfig.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(DISPLAYCONFIG_PATH_INFO),
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(DISPLAYCONFIG_MODE_INFO),
            ctypes.c_void_p,
        ]
        user32.QueryDisplayConfig.restype = wintypes.LONG

        user32.DisplayConfigGetDeviceInfo.argtypes = [
            ctypes.POINTER(DISPLAYCONFIG_DEVICE_INFO_HEADER)
        ]
        user32.DisplayConfigGetDeviceInfo.restype = wintypes.LONG

        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL

        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetCursorPos.restype = wintypes.BOOL

        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR

        user32.mouse_event.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_size_t,
        ]
        user32.mouse_event.restype = None

        user32.GetWindowRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        user32.GetWindowRect.restype = wintypes.BOOL

        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.RegisterHotKey.restype = wintypes.BOOL

        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL

        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = wintypes.BOOL

        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL

        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = ctypes.c_ssize_t

        user32.PostThreadMessageW.argtypes = [
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.PostThreadMessageW.restype = wintypes.BOOL

        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int

        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            ctypes.c_wchar_p,
        ]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.GetLastError.argtypes = []
        kernel32.GetLastError.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = wintypes.BOOL

        try:
            shcore = ctypes.windll.shcore
            shcore.GetDpiForMonitor.argtypes = [
                wintypes.HMONITOR,
                ctypes.c_int,
                ctypes.POINTER(wintypes.UINT),
                ctypes.POINTER(wintypes.UINT),
            ]
            shcore.GetDpiForMonitor.restype = ctypes.c_long
        except Exception:
            pass

        _WIN32_SIGNATURES_CONFIGURED = True
    except Exception as exc:
        DIAG_LOG.warning("CTYPES", f"Win32 signature setup note: {exc}")


QDC_ONLY_ACTIVE_PATHS = 0x00000002
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO = 9
DISPLAYCONFIG_DEVICE_INFO_GET_SDR_WHITE_LEVEL = 11


def normalize_display_device_name(name: str) -> str:
    r"""
    Normalizes Win32/DXGI/Qt display device identifiers (such as '\\\\.\\DISPLAY2',
    '\\\\.\\DISPLAY2\\Monitor0', or 'DISPLAY2') into a canonical lowercase token ('display2').
    Preserves non-GDI monitor names as stripped lowercase strings.
    """
    if not name:
        return ""
    cleaned = str(name).split("\x00", 1)[0].strip().replace("/", "\\").casefold()
    while cleaned.startswith("\\"):
        cleaned = cleaned[1:]
    if cleaned.startswith(".\\") or cleaned.startswith("?\\"):
        cleaned = cleaned[2:]
    first_part = cleaned.split("\\", 1)[0].strip()
    if first_part.startswith("display") and first_part[7:].isdigit():
        return f"display{int(first_part[7:])}"
    # Also scan for embedded DISPLAY<N> token
    idx = cleaned.find("display")
    if idx != -1:
        tail = cleaned[idx + 7 :]
        digits = []
        for ch in tail:
            if ch.isdigit():
                digits.append(ch)
            else:
                break
        if digits:
            return f"display{int(''.join(digits))}"
    return first_part or cleaned


def _display_device_names_match(name_a: str, name_b: str) -> bool:
    """Returns True if two Win32/DXGI/Qt display device names refer to the same display output."""
    na = normalize_display_device_name(name_a)
    nb = normalize_display_device_name(name_b)
    return bool(na and nb and na == nb)


def get_windows_sdr_white_level_scale(
    manual_nits: float = 0.0, output_device_name: str = ""
) -> float:
    """
    Returns the scRGB white level multiplier (where 1.0 = 80 nits) for the target monitor.
    When Windows HDR is on, DWM multiplies SDR pixels (and Auto-HDR base diffuse)
    by (SDRWhiteLevel / 1000.0). For example, 200 nits -> 2.5.
    """
    if manual_nits > 0:
        return max(manual_nits / 80.0, 0.5)

    if sys.platform != "win32":
        return 2.5  # Default 200 nits fallback on non-Windows

    try:
        _ensure_win32_ctypes_signatures()
        user32 = ctypes.windll.user32
        num_paths = wintypes.UINT(0)
        num_modes = wintypes.UINT(0)
        res = user32.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS,
            ctypes.byref(num_paths),
            ctypes.byref(num_modes),
        )
        if res != 0 or num_paths.value == 0:
            return 2.5

        paths = (DISPLAYCONFIG_PATH_INFO * num_paths.value)()
        modes = (DISPLAYCONFIG_MODE_INFO * num_modes.value)()
        res = user32.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS,
            ctypes.byref(num_paths),
            paths,
            ctypes.byref(num_modes),
            modes,
            None,
        )
        if res != 0:
            return 2.5

        paths_to_try = []
        for i in range(num_paths.value):
            if output_device_name:
                src_info = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
                src_info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
                src_info.header.size = ctypes.sizeof(src_info)
                src_info.header.adapterId = paths[i].sourceInfo.adapterId
                src_info.header.id = paths[i].sourceInfo.id
                err = user32.DisplayConfigGetDeviceInfo(
                    ctypes.byref(src_info.header)
                )
                if err != 0 or not _display_device_names_match(
                    src_info.viewGdiDeviceName, output_device_name
                ):
                    continue
            paths_to_try.append(i)

        if not paths_to_try:
            paths_to_try = list(range(num_paths.value))

        for i in paths_to_try:
            sdr_info = DISPLAYCONFIG_SDR_WHITE_LEVEL()
            sdr_info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SDR_WHITE_LEVEL
            sdr_info.header.size = ctypes.sizeof(DISPLAYCONFIG_SDR_WHITE_LEVEL)
            sdr_info.header.adapterId = paths[i].targetInfo.adapterId
            sdr_info.header.id = paths[i].targetInfo.id
            if (
                user32.DisplayConfigGetDeviceInfo(ctypes.byref(sdr_info.header))
                == 0
            ):
                if sdr_info.SDRWhiteLevel > 0:
                    return float(sdr_info.SDRWhiteLevel) / 1000.0
    except Exception as exc:
        print(f"[HDRSnip Fusion] DisplayConfig query fallback: {exc}")
        DIAG_LOG.warning("DISPLAYCONFIG", f"SDRWhiteLevel query fallback: {exc}")

    return 2.5


def windows_display_hdr_enabled(output_device_name: str) -> Optional[bool]:
    """Returns True when the matching Windows display reports Advanced Color / HDR active."""
    if sys.platform != "win32" or not output_device_name:
        return None
    try:
        _ensure_win32_ctypes_signatures()
        u = ctypes.windll.user32
        count_paths, count_modes = wintypes.UINT(), wintypes.UINT()
        if u.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(count_paths), ctypes.byref(count_modes)
        ):
            return None
        if count_paths.value == 0:
            return None
        paths = (DISPLAYCONFIG_PATH_INFO * count_paths.value)()
        modes = (DISPLAYCONFIG_MODE_INFO * count_modes.value)()
        if u.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS,
            ctypes.byref(count_paths),
            paths,
            ctypes.byref(count_modes),
            modes,
            None,
        ):
            return None
        for i in range(count_paths.value):
            info = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
            info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
            info.header.size = ctypes.sizeof(info)
            info.header.adapterId = paths[i].sourceInfo.adapterId
            info.header.id = paths[i].sourceInfo.id
            if u.DisplayConfigGetDeviceInfo(ctypes.byref(info.header)) != 0:
                continue
            if not _display_device_names_match(
                info.viewGdiDeviceName, output_device_name
            ):
                continue
            color = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO()
            color.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO
            color.header.size = ctypes.sizeof(color)
            color.header.adapterId = paths[i].targetInfo.adapterId
            color.header.id = paths[i].targetInfo.id
            if u.DisplayConfigGetDeviceInfo(ctypes.byref(color.header)) == 0:
                return bool(color.value & 0b10)  # advancedColorEnabled bit
    except Exception as exc:
        print(f"[HDRSnip Fusion] HDR display check unavailable: {exc}")
        DIAG_LOG.warning("DISPLAYCONFIG", f"HDR status check unavailable: {exc}")
    return None


# =============================================================================
# 3. ACCURATE HDR / AUTO-HDR TONE MAPPING ENGINE (scRGB Float16 -> sRGB uint8)
# =============================================================================

def tone_map_scrgb_to_srgb(
    scrgb_float: np.ndarray,
    white_scale: float = 2.5,
    mode: str = "sdr_exact_knee",
    knee_start: float = 0.80,
    max_headroom: float = 6.0,
    auto_hdr_gamma22_fix: bool = False,
    boost_sdr_whites: bool = False,
) -> np.ndarray:
    """
    Converts a linear scRGB float16/float32 array (H, W, 3 or 4) from Windows DWM
    into an 8-bit sRGB uint8 array (H, W, 3) WITHOUT blowing out HDR or Auto-HDR.
    Optimized for in-place performance and reduced memory allocations.
    """
    rgb = np.array(scrgb_float[..., :3], dtype=np.float32, copy=True)

    pos_limit = float(max_headroom * white_scale)
    np.nan_to_num(rgb, copy=False, nan=0.0, posinf=pos_limit, neginf=0.0)
    np.maximum(rgb, 0.0, out=rgb)

    inv_white = np.float32(1.0 / max(white_scale, 0.1))
    rgb *= inv_white

    if mode == "sdr_exact_knee":
        r = rgb[..., 0]
        g = rgb[..., 1]
        b = rgb[..., 2]
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        peak_chan = np.maximum(r, np.maximum(g, b))
        ref = 0.85 * peak_chan + 0.15 * luma

        k = float(np.clip(knee_start, 0.5, 0.98))
        excess = np.maximum(ref - k, 0.0)
        headroom_span = max(max_headroom - k, 1.0)
        c = (1.0 - k) / headroom_span + 1.0
        denom = (1.0 - k) + excess * c
        compressed_excess = (1.0 - k) * (excess / denom)

        new_ref = np.where(ref > k, k + compressed_excess, ref)
        scale = np.where(ref > 1e-6, new_ref / np.maximum(ref, 1e-6), 1.0)
        rgb *= scale[..., np.newaxis]

        mask = rgb > 0.98
        if np.any(mask):
            rgb[mask] = 0.98 + 0.02 * ((rgb[mask] - 0.98) / (0.02 + (rgb[mask] - 0.98)))

    elif mode == "reinhard_luma":
        r = rgb[..., 0]
        g = rgb[..., 1]
        b = rgb[..., 2]
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        w2 = max(max_headroom * max_headroom, 1.0)
        new_luma = (luma * (1.0 + luma / w2)) / (1.0 + luma)
        scale = np.where(luma > 1e-6, new_luma / np.maximum(luma, 1e-6), 1.0)
        rgb *= scale[..., np.newaxis]

    elif mode == "aces_filmic":
        x = rgb * 0.85
        a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
        rgb = (x * (a * x + b)) / (x * (c * x + d) + e)

    np.clip(rgb, 0.0, 1.0, out=rgb)

    if auto_hdr_gamma22_fix:
        srgb = np.power(rgb, 1.0 / 2.2)
        linear_22 = np.where(
            srgb <= 0.04045,
            srgb / 12.92,
            np.power((srgb + 0.055) / 1.055, 2.4),
        )
        rgb = linear_22
        np.clip(rgb, 0.0, 1.0, out=rgb)

    srgb_out = np.empty_like(rgb)
    lin_mask = rgb <= 0.0031308
    srgb_out[lin_mask] = rgb[lin_mask] * 12.92
    non_lin = ~lin_mask
    srgb_out[non_lin] = 1.055 * np.power(rgb[non_lin], 1.0 / 2.4) - 0.055

    if mode == "sdr_exact_knee" and boost_sdr_whites:
        k = float(np.clip(knee_start, 0.5, 0.98))
        e = 1.0 - k
        span = max(max_headroom - k, 1.0)
        mapped = k + (1.0 - k) * (e / (e + e * ((1.0 - k) / span + 1.0)))
        if mapped > 0.98:
            mapped = 0.98 + 0.02 * ((mapped - 0.98) / (0.02 + (mapped - 0.98)))
        if auto_hdr_gamma22_fix:
            srgb_w = mapped ** (1.0 / 2.2)
            mapped = (
                srgb_w / 12.92
                if srgb_w <= 0.04045
                else ((srgb_w + 0.055) / 1.055) ** 2.4
            )
        encoded_white = (
            12.92 * mapped
            if mapped <= 0.0031308
            else 1.055 * mapped ** (1.0 / 2.4) - 0.055
        )
        srgb_out /= max(encoded_white, 1e-5)

    srgb_out *= 255.0
    srgb_out += 0.5
    np.clip(srgb_out, 0, 255, out=srgb_out)
    return np.ascontiguousarray(srgb_out.astype(np.uint8))


# =============================================================================
# 4. DIRECT3D11 + DXGI DESKTOP DUPLICATION (MULTI-GPU FLOAT16 scRGB CAPTURE)
# =============================================================================

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_str(cls, guid_str: str) -> "GUID":
        g = guid_str.strip("{}").split("-")
        d1 = int(g[0], 16)
        d2 = int(g[1], 16)
        d3 = int(g[2], 16)
        d4_hi = bytes.fromhex(g[3])
        d4_lo = bytes.fromhex(g[4])
        arr = (ctypes.c_ubyte * 8)(*(d4_hi + d4_lo))
        return cls(d1, d2, d3, arr)


class DXGI_OUTPUT_DESC(ctypes.Structure):
    _fields_ = [
        ("DeviceName", ctypes.c_wchar * 32),
        ("DesktopCoordinates", wintypes.RECT),
        ("AttachedToDesktop", ctypes.c_int32),
        ("Rotation", ctypes.c_int),
        ("Monitor", wintypes.HMONITOR),
    ]


class DXGI_SAMPLE_DESC(ctypes.Structure):
    _fields_ = [("Count", wintypes.UINT), ("Quality", wintypes.UINT)]


class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [
        ("Width", wintypes.UINT),
        ("Height", wintypes.UINT),
        ("MipLevels", wintypes.UINT),
        ("ArraySize", wintypes.UINT),
        ("Format", wintypes.UINT),
        ("SampleDesc", DXGI_SAMPLE_DESC),
        ("Usage", wintypes.UINT),
        ("BindFlags", wintypes.UINT),
        ("CPUAccessFlags", wintypes.UINT),
        ("MiscFlags", wintypes.UINT),
    ]


class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [
        ("pData", ctypes.c_void_p),
        ("RowPitch", wintypes.UINT),
        ("DepthPitch", wintypes.UINT),
    ]


class DXGI_OUTDUPL_FRAME_INFO(ctypes.Structure):
    _fields_ = [
        ("LastPresentTime", ctypes.c_int64),
        ("LastMouseUpdateTime", ctypes.c_int64),
        ("AccumulatedFrames", wintypes.UINT),
        ("RectsCoalesced", ctypes.c_int32),
        ("ProtectedContentMaskedOut", ctypes.c_int32),
        ("PointerPosition_x", ctypes.c_int32),
        ("PointerPosition_y", ctypes.c_int32),
        ("PointerPosition_Visible", ctypes.c_int32),
        ("TotalMetadataBufferSize", wintypes.UINT),
        ("PointerShapeBufferSize", wintypes.UINT),
    ]


DXGI_FORMAT_R16G16B16A16_FLOAT = 10
DXGI_FORMAT_R10G10B10A2_UNORM = 24
DXGI_FORMAT_R8G8B8A8_UNORM = 28
DXGI_FORMAT_B8G8R8A8_UNORM = 87

D3D_DRIVER_TYPE_UNKNOWN = 0
D3D_DRIVER_TYPE_HARDWARE = 1
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1
DXGI_ADAPTER_FLAG_SOFTWARE = 2

# Standard DXGI & Win32 HRESULTs (unsigned 32-bit representation)
S_OK = 0x00000000
E_ACCESSDENIED = 0x80070005
E_INVALIDARG = 0x80070057
E_OUTOFMEMORY = 0x8007000E
DXGI_ERROR_INVALID_CALL = 0x887A0001
DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ERROR_UNSUPPORTED = 0x887A0004
DXGI_ERROR_DEVICE_REMOVED = 0x887A0005
DXGI_ERROR_DEVICE_HUNG = 0x887A0006
DXGI_ERROR_DEVICE_RESET = 0x887A0007
DXGI_ERROR_WAS_STILL_DRAWING = 0x887A000A
DXGI_ERROR_DRIVER_INTERNAL_ERROR = 0x887A0020
DXGI_ERROR_NOT_CURRENTLY_AVAILABLE = 0x887A0022
DXGI_ERROR_ModeChangeInProgress = 0x887A0025
DXGI_ERROR_ACCESS_LOST = 0x887A0026
DXGI_ERROR_WAIT_TIMEOUT = 0x887A0027
DXGI_ERROR_SESSION_DISCONNECTED = 0x887A0028

DXGI_HRESULT_NAMES = {
    S_OK: "S_OK",
    E_ACCESSDENIED: "E_ACCESSDENIED (Fullscreen exclusive / UAC secure desktop transition)",
    E_INVALIDARG: "E_INVALIDARG",
    E_OUTOFMEMORY: "E_OUTOFMEMORY",
    DXGI_ERROR_INVALID_CALL: "DXGI_ERROR_INVALID_CALL",
    DXGI_ERROR_NOT_FOUND: "DXGI_ERROR_NOT_FOUND",
    DXGI_ERROR_UNSUPPORTED: "DXGI_ERROR_UNSUPPORTED",
    DXGI_ERROR_DEVICE_REMOVED: "DXGI_ERROR_DEVICE_REMOVED (GPU driver reset/TDR or adapter removed)",
    DXGI_ERROR_DEVICE_HUNG: "DXGI_ERROR_DEVICE_HUNG (GPU driver hung)",
    DXGI_ERROR_DEVICE_RESET: "DXGI_ERROR_DEVICE_RESET (GPU device reset)",
    DXGI_ERROR_WAS_STILL_DRAWING: "DXGI_ERROR_WAS_STILL_DRAWING",
    DXGI_ERROR_DRIVER_INTERNAL_ERROR: "DXGI_ERROR_DRIVER_INTERNAL_ERROR",
    DXGI_ERROR_NOT_CURRENTLY_AVAILABLE: "DXGI_ERROR_NOT_CURRENTLY_AVAILABLE",
    DXGI_ERROR_ModeChangeInProgress: "DXGI_ERROR_MODE_CHANGE_IN_PROGRESS",
    DXGI_ERROR_ACCESS_LOST: "DXGI_ERROR_ACCESS_LOST (Desktop duplication mode/HDR transition)",
    DXGI_ERROR_WAIT_TIMEOUT: "DXGI_ERROR_WAIT_TIMEOUT",
    DXGI_ERROR_SESSION_DISCONNECTED: "DXGI_ERROR_SESSION_DISCONNECTED",
}

# Terminal DXGI HRESULTs that should NEVER be retried in a loop
DXGI_TERMINAL_HRESULTS = frozenset(
    {
        E_ACCESSDENIED,
        DXGI_ERROR_INVALID_CALL,
        DXGI_ERROR_UNSUPPORTED,
        DXGI_ERROR_DEVICE_REMOVED,
        DXGI_ERROR_DEVICE_HUNG,
        DXGI_ERROR_DEVICE_RESET,
        DXGI_ERROR_DRIVER_INTERNAL_ERROR,
        DXGI_ERROR_NOT_CURRENTLY_AVAILABLE,
        DXGI_ERROR_ModeChangeInProgress,
        DXGI_ERROR_ACCESS_LOST,
        DXGI_ERROR_SESSION_DISCONNECTED,
    }
)


def format_hresult(hr: int) -> str:
    """Formats a signed or unsigned HRESULT into hex + symbolic DXGI name."""
    u32 = int(hr) & 0xFFFFFFFF
    name = DXGI_HRESULT_NAMES.get(u32, "UNKNOWN_HRESULT")
    return f"0x{u32:08X} ({name})"


IID_IDXGIFactory1 = GUID.from_str("770aae78-f26f-4dba-a829-253c83d1b387")
IID_IDXGIDevice = GUID.from_str("54ec77fa-1377-44e6-8c32-88fd5f44c84c")
IID_IDXGIOutput1 = GUID.from_str("00cddea8-939b-4b83-a340-a685226666cc")
IID_IDXGIOutput6 = GUID.from_str("068346e8-aaec-4b84-add7-137f513f77a1")
IID_ID3D11Texture2D = GUID.from_str("6f15aaf2-d208-4e89-9ab4-489535d34f9c")

_COM_PROTO_CACHE: dict = {}


def _com_vtable_call(
    obj_ptr: ctypes.c_void_p,
    method_index: int,
    restype: Any,
    argtypes: list,
    *args,
):
    """
    Calls a COM interface method by vtable index directly via ctypes.
    Validates non-NULL object, vtable, and method pointers before invocation and
    caches WINFUNCTYPE prototypes to avoid repeated ctypes type allocations.
    """
    if obj_ptr is None or not getattr(obj_ptr, "value", None):
        raise RuntimeError(
            f"Attempted COM vtable call (index={method_index}) on a NULL COM pointer."
        )
    if method_index < 0:
        raise ValueError(f"Invalid negative COM vtable index: {method_index}")

    vtbl_ptr = ctypes.cast(obj_ptr, ctypes.POINTER(ctypes.c_void_p)).contents.value
    if not vtbl_ptr:
        raise RuntimeError(
            f"COM object 0x{int(obj_ptr.value):X} has a NULL vtable pointer."
        )

    func_ptr = ctypes.cast(
        vtbl_ptr + method_index * ctypes.sizeof(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ).contents.value
    if not func_ptr:
        raise RuntimeError(
            f"COM object 0x{int(obj_ptr.value):X} has a NULL function pointer at vtable[{method_index}]."
        )

    cache_key = (restype, tuple(argtypes))
    proto = _COM_PROTO_CACHE.get(cache_key)
    if proto is None:
        functype_factory = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
        proto = functype_factory(restype, ctypes.c_void_p, *argtypes)
        _COM_PROTO_CACHE[cache_key] = proto

    func = proto(func_ptr)
    return func(obj_ptr, *args)


def _com_release(obj_ptr: Optional[ctypes.c_void_p]) -> int:
    """
    Safely releases a COM interface pointer via IUnknown::Release (vtable index 2)
    and immediately zeroes `obj_ptr.value = None` so the pointer can NEVER be
    double-released or accessed after release. Returns the remaining refcount (or 0).
    """
    if obj_ptr is None:
        return 0
    ptr_val = getattr(obj_ptr, "value", None)
    if not ptr_val:
        return 0
    # Zero the holder FIRST so even if an exception occurs or cleanup re-enters,
    # Release() is never invoked twice on the same native address.
    obj_ptr.value = None
    try:
        active_ptr = ctypes.c_void_p(ptr_val)
        ref_count = _com_vtable_call(active_ptr, 2, ctypes.c_uint32, [])
        return int(ref_count) if ref_count is not None else 0
    except Exception as exc:
        DIAG_LOG.warning(
            "COM_RELEASE",
            f"Exception while releasing COM pointer 0x{int(ptr_val):X}: {exc}",
        )
        return 0


def query_d3d11_device_removed_reason(d3d_device: Optional[ctypes.c_void_p]) -> str:
    """
    Queries ID3D11Device::GetDeviceRemovedReason() (vtable index 39) when a DXGI
    call fails with DXGI_ERROR_DEVICE_REMOVED / RESET / HUNG.
    """
    if d3d_device is None or not getattr(d3d_device, "value", None):
        return "device_null"
    try:
        reason_hr = _com_vtable_call(d3d_device, 39, ctypes.c_long, [])
        return format_hresult(reason_hr)
    except Exception as exc:
        return f"unavailable ({exc})"


_CAPTURE_LOCK = threading.Lock()


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", ctypes.c_uint32),
        ("szDevice", ctypes.c_wchar * 32),
    ]


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", wintypes.UINT),
        ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT),
        ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", LUID),
        ("Flags", wintypes.UINT),
    ]


MOUSEEVENTF_MOVE = 0x0001


def _normalize_hmonitor(handle: Any) -> int:
    """Converts a ctypes HMONITOR or integer handle into a canonical unsigned pointer integer."""
    if handle is None:
        return 0
    val = getattr(handle, "value", handle)
    if val is None:
        return 0
    try:
        return int(val) & 0xFFFFFFFFFFFFFFFF
    except Exception:
        return 0


@dataclass
class Win32MonitorInfo:
    """Authoritative physical monitor identity and bounds in Win32 virtual-desktop pixel space."""
    hmonitor: int
    device_name: str
    physical_rect: Tuple[int, int, int, int]  # (left, top, width, height) in physical pixels
    work_rect: Tuple[int, int, int, int] = (0, 0, 1920, 1080)
    is_primary: bool = False
    dpi_x: int = 96
    dpi_y: int = 96

    @property
    def dpi_scale(self) -> float:
        return max(0.5, float(self.dpi_x) / 96.0)

    def contains_physical_point(self, px: int, py: int) -> bool:
        x, y, w, h = self.physical_rect
        return x <= px < (x + w) and y <= py < (y + h)

    def distance_squared_to_point(self, px: int, py: int) -> int:
        x, y, w, h = self.physical_rect
        cx = max(x, min(x + w - 1, px))
        cy = max(y, min(y + h - 1, py))
        return (px - cx) ** 2 + (py - cy) ** 2


@dataclass
class DXGIOutputCandidate:
    """Represents an enumerated DXGI output on a specific GPU adapter."""
    adapter_idx: int
    output_idx: int
    adapter_name: str
    device_name: str
    desktop_rect: Tuple[int, int, int, int]  # (left, top, width, height) in physical pixels
    hmonitor: int
    rotation: int = 1
    adapter_ptr: Any = None
    output_ptr: Any = None


@dataclass
class CapturedFrame:
    """
    Stores both the raw HDR float16 data (if HDR was active) and the tone-mapped sRGB image,
    along with physical monitor identity, bounds, DPI, cursor metadata, and deterministic
    memory-release tracking so 4K HDR/SDR buffers are freed as soon as the overlay closes.
    """
    srgb_image: np.ndarray  # (H, W, 3) uint8
    raw_scrgb_float: Optional[np.ndarray] = None  # (H, W, 3) float16 if captured in HDR
    detected_white_scale: float = 2.5
    is_hdr_surface: bool = False
    display_device: str = ""
    virtual_rect: Tuple[int, int, int, int] = (0, 0, 1920, 1080)
    hmonitor: int = 0
    win32_device_name: str = ""
    adapter_description: str = ""
    adapter_index: int = -1
    output_index: int = -1
    cursor_physical: Optional[Tuple[int, int]] = None
    cursor_after_capture: Optional[Tuple[int, int]] = None
    monitor_dpi_scale: float = 1.0
    is_primary_monitor: bool = True
    win32_monitors_snapshot: List[Win32MonitorInfo] = field(default_factory=list)
    full_width: int = 1920
    full_height: int = 1080
    is_preview: bool = False
    preview_stride: int = 1
    created_at_sec: float = field(default_factory=time.perf_counter)
    released: bool = False
    _tracked_bytes: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._tracked_bytes = self.allocated_bytes()
        if self._tracked_bytes > 32:
            PERF_TELEMETRY.record_capture_allocated(self._tracked_bytes)

    def allocated_bytes(self) -> int:
        total = 0
        if isinstance(self.srgb_image, np.ndarray) and self.srgb_image.size > 3:
            total += int(self.srgb_image.nbytes)
        if isinstance(self.raw_scrgb_float, np.ndarray):
            total += int(self.raw_scrgb_float.nbytes)
        return total

    def release_buffers(self) -> int:
        """
        Releases large 4K HDR float16 and tone-mapped sRGB NumPy arrays immediately.
        Safe to call multiple times (idempotent).
        """
        if self.released:
            return 0
        freed = max(self._tracked_bytes, self.allocated_bytes())
        lifetime = max(0.0, time.perf_counter() - self.created_at_sec)
        self.raw_scrgb_float = None
        self.srgb_image = np.zeros((1, 1, 3), dtype=np.uint8)
        self.win32_monitors_snapshot.clear()
        self.released = True
        self._tracked_bytes = 0
        if freed > 32:
            PERF_TELEMETRY.record_capture_released(freed, lifetime)
        return freed


@dataclass
class DisplayCoordinateMapper:
    """
    Explicit coordinate-space converter for a single captured physical display.

    Coordinate Spaces:
      1. Win32 / DXGI Global Physical Coordinates:
         (phys_x, phys_y, phys_w, phys_h) in virtual-desktop physical pixels.
         Supports negative X/Y origins (monitors to the left of or above the primary display).
      2. Qt Target Screen Global Logical Coordinates:
         (logical_x, logical_y, logical_w, logical_h) from the target QScreen.geometry().
         Uses the monitor's own origin and scale factor rather than a single global DPI multiplier.
      3. Qt Overlay Widget-Local Logical Coordinates:
         (local_x, local_y) in [0, overlay_w] x [0, overlay_h], used by mouse events,
         selection_rect, and interactive annotations.
      4. Captured Framebuffer / Screenshot Image Pixel Coordinates:
         (img_x, img_y) in [0, image_w] x [0, image_h], used by DXGI textures,
         frosted-glass blur sampling, and final PNG/clipboard export cropping.
    """
    phys_x: int
    phys_y: int
    phys_w: int
    phys_h: int
    logical_x: int
    logical_y: int
    logical_w: int
    logical_h: int
    overlay_w: int
    overlay_h: int
    image_w: int
    image_h: int
    qt_dpr: float = 1.0
    win32_dpi_scale: float = 1.0

    @property
    def px_scale_x(self) -> float:
        return float(self.image_w) / max(1.0, float(self.overlay_w))

    @property
    def px_scale_y(self) -> float:
        return float(self.image_h) / max(1.0, float(self.overlay_h))

    def update_overlay_size(self, overlay_w: int, overlay_h: int) -> None:
        if overlay_w > 0 and overlay_h > 0:
            self.overlay_w = int(overlay_w)
            self.overlay_h = int(overlay_h)

    def physical_global_to_local_logical(
        self, phys_gx: float, phys_gy: float
    ) -> Tuple[float, float]:
        """Maps a Win32 global physical coordinate (e.g. GetCursorPos) to widget-local logical coords."""
        rel_x = (float(phys_gx) - float(self.phys_x)) / max(1.0, float(self.phys_w))
        rel_y = (float(phys_gy) - float(self.phys_y)) / max(1.0, float(self.phys_h))
        return (rel_x * float(self.overlay_w), rel_y * float(self.overlay_h))

    def local_logical_to_physical_global(
        self, local_x: float, local_y: float
    ) -> Tuple[float, float]:
        """Maps widget-local logical coordinates back to Win32 global physical coordinates."""
        rel_x = float(local_x) / max(1.0, float(self.overlay_w))
        rel_y = float(local_y) / max(1.0, float(self.overlay_h))
        return (
            float(self.phys_x) + rel_x * float(self.phys_w),
            float(self.phys_y) + rel_y * float(self.phys_h),
        )

    def physical_global_to_qt_global(
        self, phys_gx: float, phys_gy: float
    ) -> Tuple[float, float]:
        """Maps a Win32 global physical coordinate to the target QScreen's global logical space."""
        rel_x = (float(phys_gx) - float(self.phys_x)) / max(1.0, float(self.phys_w))
        rel_y = (float(phys_gy) - float(self.phys_y)) / max(1.0, float(self.phys_h))
        return (
            float(self.logical_x) + rel_x * float(self.logical_w),
            float(self.logical_y) + rel_y * float(self.logical_h),
        )

    def qt_global_to_local_logical(
        self, qt_gx: float, qt_gy: float
    ) -> Tuple[float, float]:
        """Maps a Qt global logical coordinate on the target QScreen to widget-local logical coords."""
        rel_x = (float(qt_gx) - float(self.logical_x)) / max(1.0, float(self.logical_w))
        rel_y = (float(qt_gy) - float(self.logical_y)) / max(1.0, float(self.logical_h))
        return (rel_x * float(self.overlay_w), rel_y * float(self.overlay_h))

    def local_logical_to_image_point(
        self, local_x: float, local_y: float
    ) -> Tuple[float, float]:
        """Maps an overlay widget-local logical point to screenshot framebuffer pixel coordinates."""
        return (float(local_x) * self.px_scale_x, float(local_y) * self.px_scale_y)

    def image_point_to_local_logical(
        self, img_x: float, img_y: float
    ) -> Tuple[float, float]:
        """Maps screenshot framebuffer pixel coordinates to overlay widget-local logical coordinates."""
        return (
            float(img_x) / max(1e-6, self.px_scale_x),
            float(img_y) / max(1e-6, self.px_scale_y),
        )

    def local_rect_to_image_crop_rect(
        self, local_rect: Tuple[float, float, float, float]
    ) -> Tuple[int, int, int, int]:
        """
        Converts a widget-local logical rectangle (left, top, width, height) into an exact,
        clamped screenshot framebuffer pixel rectangle (crop_x, crop_y, crop_w, crop_h).
        """
        lx, ly, lw, lh = local_rect
        x0_f = min(lx, lx + lw)
        x1_f = max(lx, lx + lw)
        y0_f = min(ly, ly + lh)
        y1_f = max(ly, ly + lh)

        px0 = max(0, min(self.image_w, int(round(x0_f * self.px_scale_x))))
        py0 = max(0, min(self.image_h, int(round(y0_f * self.px_scale_y))))
        px1 = max(px0, min(self.image_w, int(round(x1_f * self.px_scale_x))))
        py1 = max(py0, min(self.image_h, int(round(y1_f * self.px_scale_y))))
        return (px0, py0, px1 - px0, py1 - py0)


def get_physical_cursor_pos() -> Tuple[int, int]:
    """Returns the current physical cursor position (x, y) in Win32 virtual-desktop coordinates."""
    if sys.platform != "win32":
        return (0, 0)
    ensure_per_monitor_dpi_awareness()
    pt = wintypes.POINT()
    if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        return (int(pt.x), int(pt.y))
    return (0, 0)


def query_win32_monitor_info(hmonitor: int) -> Optional[Win32MonitorInfo]:
    """Queries GetMonitorInfoW and GetDpiForMonitor for a Win32 HMONITOR handle."""
    if sys.platform != "win32" or not hmonitor:
        return None
    _ensure_win32_ctypes_signatures()
    user32 = ctypes.windll.user32
    user32.GetMonitorInfoW.argtypes = [
        wintypes.HMONITOR,
        ctypes.POINTER(MONITORINFOEXW),
    ]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    mi = MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if not user32.GetMonitorInfoW(wintypes.HMONITOR(hmonitor), ctypes.byref(mi)):
        return None

    rc = mi.rcMonitor
    wk = mi.rcWork
    phys_rect = (
        int(rc.left),
        int(rc.top),
        int(rc.right - rc.left),
        int(rc.bottom - rc.top),
    )
    work_rect = (
        int(wk.left),
        int(wk.top),
        int(wk.right - wk.left),
        int(wk.bottom - wk.top),
    )
    is_primary = bool(mi.dwFlags & MONITORINFOF_PRIMARY)

    dpi_x = wintypes.UINT(96)
    dpi_y = wintypes.UINT(96)
    try:
        hr = ctypes.windll.shcore.GetDpiForMonitor(
            wintypes.HMONITOR(hmonitor),
            MDT_EFFECTIVE_DPI,
            ctypes.byref(dpi_x),
            ctypes.byref(dpi_y),
        )
        if hr != 0 or dpi_x.value == 0:
            dpi_x.value = 96
            dpi_y.value = 96
    except Exception:
        dpi_x.value = 96
        dpi_y.value = 96

    return Win32MonitorInfo(
        hmonitor=_normalize_hmonitor(hmonitor),
        device_name=str(mi.szDevice).split("\x00", 1)[0].strip(),
        physical_rect=phys_rect,
        work_rect=work_rect,
        is_primary=is_primary,
        dpi_x=int(dpi_x.value),
        dpi_y=int(dpi_y.value),
    )


def enumerate_win32_monitors() -> List[Win32MonitorInfo]:
    """Enumerates all active physical monitors via Win32 EnumDisplayMonitors + GetMonitorInfoW."""
    if sys.platform != "win32":
        return []
    ensure_per_monitor_dpi_awareness()
    user32 = ctypes.windll.user32
    monitors: List[Win32MonitorInfo] = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def _callback(hmon, _hdc, _lprect, _lparam):
        info = query_win32_monitor_info(_normalize_hmonitor(hmon))
        if info is not None and info.physical_rect[2] > 0 and info.physical_rect[3] > 0:
            monitors.append(info)
        return True

    cb = MONITORENUMPROC(_callback)
    try:
        user32.EnumDisplayMonitors.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            MONITORENUMPROC,
            wintypes.LPARAM,
        ]
        user32.EnumDisplayMonitors.restype = wintypes.BOOL
        user32.EnumDisplayMonitors(None, None, cb, 0)
    except Exception as exc:
        _debug_monitor_log(f"EnumDisplayMonitors warning: {exc}")
    return monitors


def resolve_physical_monitor_for_cursor(
    cursor_xy: Tuple[int, int],
    win32_monitors: Optional[Sequence[Win32MonitorInfo]] = None,
) -> Win32MonitorInfo:
    """
    Identifies the physical monitor containing `cursor_xy` using Win32 MonitorFromPoint,
    GetMonitorInfoW, and EnumDisplayMonitors.
    Supports injected `win32_monitors` for deterministic headless unit testing.
    """
    cx, cy = int(cursor_xy[0]), int(cursor_xy[1])
    monitors = (
        list(win32_monitors)
        if win32_monitors is not None
        else enumerate_win32_monitors()
    )

    # 1. If running on live Win32 without mock monitors, query MonitorFromPoint directly first
    if sys.platform == "win32" and win32_monitors is None:
        user32 = ctypes.windll.user32
        pt = wintypes.POINT(cx, cy)
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        hmon = _normalize_hmonitor(
            user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
        )
        direct_info = query_win32_monitor_info(hmon)
        if direct_info is not None:
            # Verify against EnumDisplayMonitors if available
            for m in monitors:
                if m.hmonitor == direct_info.hmonitor:
                    return m
            return direct_info

    # 2. Check exact point containment in enumerated monitors
    for m in monitors:
        if m.contains_physical_point(cx, cy):
            return m

    # 3. Nearest monitor by Euclidean distance to physical bounds (mirrors MONITOR_DEFAULTTONEAREST)
    if monitors:
        return min(monitors, key=lambda m: m.distance_squared_to_point(cx, cy))

    # 4. Fallback only when no monitor list is available (e.g. non-Windows headless environment)
    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        w = int(user32.GetSystemMetrics(0)) or 1920
        h = int(user32.GetSystemMetrics(1)) or 1080
    else:
        w, h = 1920, 1080
    return Win32MonitorInfo(
        hmonitor=0,
        device_name=r"\\.\DISPLAY1",
        physical_rect=(0, 0, w, h),
        work_rect=(0, 0, w, h),
        is_primary=True,
    )


def select_dxgi_output_for_monitor(
    target_monitor: Win32MonitorInfo,
    cursor_xy: Tuple[int, int],
    candidates: Sequence[DXGIOutputCandidate],
) -> Tuple[DXGIOutputCandidate, str]:
    """
    Matches the target physical Win32 monitor to the corresponding DXGI adapter and output
    without relying on enumeration order.
    Priority:
      1. Exact HMONITOR handle match
      2. Normalized GDI device name + exact physical desktop bounds match
      3. Normalized GDI device name match
      4. Exact physical desktop bounds match
      5. Physical cursor coordinate containment inside DXGI DesktopCoordinates
    Raises RuntimeError if no candidate matches the target monitor (never silently selects index 0).
    """
    if not candidates:
        raise RuntimeError("No attached DXGI desktop outputs found on any GPU adapter.")

    cx, cy = int(cursor_xy[0]), int(cursor_xy[1])
    target_hmon = _normalize_hmonitor(target_monitor.hmonitor)
    target_dev = normalize_display_device_name(target_monitor.device_name)
    target_rect = target_monitor.physical_rect

    # 1. Exact HMONITOR handle match
    if target_hmon != 0:
        for cand in candidates:
            if _normalize_hmonitor(cand.hmonitor) == target_hmon:
                return cand, "hmonitor_exact"

    # 2. Normalized GDI device name + exact physical bounds
    if target_dev:
        for cand in candidates:
            if (
                normalize_display_device_name(cand.device_name) == target_dev
                and cand.desktop_rect == target_rect
            ):
                return cand, "device_and_bounds_exact"

    # 3. Normalized GDI device name match
    if target_dev:
        for cand in candidates:
            if normalize_display_device_name(cand.device_name) == target_dev:
                return cand, "device_name_match"

    # 4. Exact physical desktop bounds match
    for cand in candidates:
        if cand.desktop_rect == target_rect:
            return cand, "physical_bounds_exact"

    # 5. Physical cursor containment
    for cand in candidates:
        rx, ry, rw, rh = cand.desktop_rect
        if rx <= cx < (rx + rw) and ry <= cy < (ry + rh):
            return cand, "cursor_bounds_containment"

    available_str = ", ".join(
        f"{c.device_name}@{c.desktop_rect} (hmon=0x{c.hmonitor:X}, gpu={c.adapter_name})"
        for c in candidates
    )
    raise RuntimeError(
        f"Target monitor {target_monitor.device_name} at {target_rect} "
        f"(hmon=0x{target_hmon:X}, cursor={cursor_xy}) did not match any DXGI output. "
        f"Available DXGI outputs: [{available_str}]"
    )


def resolve_qt_screen_for_frame(
    frame: CapturedFrame,
    qt_screens: Sequence[Any],
) -> Tuple[Any, str]:
    """
    Resolves the CapturedFrame's physical monitor to the corresponding Qt QScreen.
    Uses a multi-factor verification strategy combining:
      - Normalized GDI device name (verified against geometry/size)
      - Physical origin (px, py) and DPI-scaled physical size (round(gw * dpr), round(gh * dpr))
      - Scaled logical origin (round(gx * dpr), round(gy * dpr)) and physical size
      - Relative multi-monitor topological rank & direction for mixed-DPI tiled logical origins
    Never silently falls back to QGuiApplication.primaryScreen() when targeting a secondary monitor.
    """
    screens = list(qt_screens)
    if not screens:
        raise RuntimeError(
            "Qt reported zero available QScreens; cannot place screenshot overlay."
        )

    px, py, pw, ph = frame.virtual_rect
    target_dev = normalize_display_device_name(
        frame.display_device or frame.win32_device_name
    )
    target_dpi = max(0.5, float(frame.monitor_dpi_scale or 1.0))

    parsed = []
    for idx, scr in enumerate(screens):
        g = scr.geometry()
        gx, gy, gw, gh = int(g.x()), int(g.y()), int(g.width()), int(g.height())
        dpr = max(0.25, float(scr.devicePixelRatio()))
        scr_phys_w = int(round(gw * dpr))
        scr_phys_h = int(round(gh * dpr))
        scr_name = str(scr.name())
        scr_dev = normalize_display_device_name(scr_name)

        name_match = bool(target_dev and scr_dev and target_dev == scr_dev)
        direct_origin_match = abs(gx - px) <= 4 and abs(gy - py) <= 4
        scaled_origin_match = (
            abs(int(round(gx * dpr)) - px) <= 8 and abs(int(round(gy * dpr)) - py) <= 8
        )
        origin_match = direct_origin_match or scaled_origin_match
        phys_size_match = abs(scr_phys_w - pw) <= 6 and abs(scr_phys_h - ph) <= 6
        logical_size_match = abs(gw - pw) <= 4 and abs(gh - ph) <= 4
        size_match = phys_size_match or logical_size_match
        dpi_match = abs(dpr - target_dpi) <= 0.15

        parsed.append(
            {
                "idx": idx,
                "scr": scr,
                "name": scr_name,
                "dev": scr_dev,
                "gx": gx,
                "gy": gy,
                "gw": gw,
                "gh": gh,
                "dpr": dpr,
                "phys_w": scr_phys_w,
                "phys_h": scr_phys_h,
                "name_match": name_match,
                "direct_origin_match": direct_origin_match,
                "scaled_origin_match": scaled_origin_match,
                "origin_match": origin_match,
                "phys_size_match": phys_size_match,
                "size_match": size_match,
                "dpi_match": dpi_match,
            }
        )

    # Tier 1: Direct device name match verified by origin and size
    for item in parsed:
        if item["name_match"] and item["origin_match"] and item["size_match"]:
            return item["scr"], "name_and_geometry_verified"

    # Tier 2: Exact physical origin + DPI-scaled physical size match
    for item in parsed:
        if item["direct_origin_match"] and item["phys_size_match"]:
            return item["scr"], "physical_origin_and_dpi_size_verified"

    # Tier 3: DPI-scaled logical origin + DPI-scaled physical size match
    for item in parsed:
        if item["scaled_origin_match"] and item["phys_size_match"]:
            return item["scr"], "scaled_origin_and_dpi_size_verified"

    # Tier 4: Direct device name match verified by physical/logical size (when no conflicting origin match exists)
    for item in parsed:
        if item["name_match"] and item["size_match"]:
            return item["scr"], "name_and_size_verified"

    # Tier 5: Exact physical origin match (non-mirrored monitor origins are distinct)
    for item in parsed:
        if item["direct_origin_match"] and item["size_match"]:
            return item["scr"], "physical_origin_and_size_verified"
    for item in parsed:
        if item["direct_origin_match"]:
            return item["scr"], "physical_origin_verified"

    # Tier 6: Direct device name match (when Qt tiled logical origins on mixed-DPI setups)
    for item in parsed:
        if item["name_match"]:
            return item["scr"], "device_name_verified"

    # Tier 7: Relative topological & directional match for mixed-DPI tiled Qt geometries
    # (e.g. when QScreen.name() is a monitor model name AND Qt tiled logical origins by logical width)
    def _sign_tol(val: int, tol: int = 8) -> int:
        if val > tol:
            return 1
        if val < -tol:
            return -1
        return 0

    target_sx = _sign_tol(px)
    target_sy = _sign_tol(py)

    directional_candidates = [
        item
        for item in parsed
        if _sign_tol(item["gx"]) == target_sx
        and _sign_tol(item["gy"]) == target_sy
        and item["size_match"]
    ]
    if len(directional_candidates) == 1:
        return directional_candidates[0]["scr"], "directional_topology_and_size_verified"
    if len(directional_candidates) > 1:
        dpi_filtered = [c for c in directional_candidates if c["dpi_match"]]
        if len(dpi_filtered) == 1:
            return dpi_filtered[0]["scr"], "directional_topology_size_and_dpi_verified"

    # Topological rank matching using Win32 monitors snapshot when counts match
    if frame.win32_monitors_snapshot and len(frame.win32_monitors_snapshot) == len(parsed):
        win_sorted = sorted(
            frame.win32_monitors_snapshot,
            key=lambda m: (m.physical_rect[0], m.physical_rect[1]),
        )
        qt_sorted = sorted(parsed, key=lambda it: (it["gx"], it["gy"]))
        for w_mon, q_it in zip(win_sorted, qt_sorted):
            if (
                w_mon.physical_rect == frame.virtual_rect
                and q_it["size_match"]
                and _sign_tol(q_it["gx"]) == target_sx
                and _sign_tol(q_it["gy"]) == target_sy
            ):
                return q_it["scr"], "topological_rank_and_size_verified"

    # Single-screen desktop fallback ONLY when the captured frame is also the primary/origin display
    if len(parsed) == 1 and (frame.is_primary_monitor or (px == 0 and py == 0)):
        return parsed[0]["scr"], "single_primary_screen"

    qt_summary = ", ".join(
        f"'{it['name']}' geom=({it['gx']},{it['gy']} {it['gw']}x{it['gh']}) "
        f"dpr={it['dpr']:.2f} phys=({it['phys_w']}x{it['phys_h']})"
        for it in parsed
    )
    raise RuntimeError(
        f"Could not resolve target Qt QScreen for captured monitor '{frame.display_device}' "
        f"at physical bounds {frame.virtual_rect} (DPI scale={target_dpi:.2f}). "
        f"Refusing to open overlay on the wrong monitor. Available Qt screens: [{qt_summary}]"
    )


def capture_screen_dxgi_hdr(config: AppConfig) -> CapturedFrame:
    """
    Captures the physical monitor containing the mouse cursor across ALL GPU adapters via
    Direct3D11 + DXGI Desktop Duplication BEFORE any overlay window is shown.

    Stability & Native Lifecycle Guarantees:
      - Non-reentrant: protected by `_CAPTURE_LOCK` so overlapping hotkey/tray triggers
        never issue concurrent DXGI Desktop Duplication calls.
      - Explicit 64-bit ctypes `argtypes` and `restype` on `CreateDXGIFactory1` and
        `D3D11CreateDevice` to prevent stack-slot pointer truncation on 64-bit Windows.
      - Zero-leak enumeration: tracks every enumerated `IDXGIAdapter1` and `IDXGIOutput`
        COM pointer and guarantees all unselected pointers are released even if matching fails.
      - Guaranteed cleanup order in `finally:`:
        `Unmap(staging_tex)` -> `Release(staging_tex)` -> `Release(acquired_tex)` ->
        `Release(desktop_resource)` -> `ReleaseFrame()` -> `Release(duplication)` ->
        `Release(dxgi_output1/6/output)` -> `ClearState/Release(d3d_context)` ->
        `Release(d3d_device)` -> `Release(selected_adapter)` -> `Release(dxgi_factory)`.
      - Strict validation of `mapped.pData`, `RowPitch`, texture dimensions, and pixel format
        before constructing any NumPy buffer.
      - Non-aggressive error handling: never retries terminal DXGI errors (`DEVICE_REMOVED`,
        `DEVICE_RESET`, `ACCESS_LOST`, `MODE_CHANGE_IN_PROGRESS`, `E_ACCESSDENIED`).
    """
    if not _CAPTURE_LOCK.acquire(blocking=False):
        DIAG_LOG.warning(
            "CAPTURE",
            "Rejected concurrent capture_screen_dxgi_hdr() call while a capture is already in progress.",
        )
        raise RuntimeError("A screen capture is already in progress.")

    t_capture_start = time.perf_counter()
    try:
        ensure_per_monitor_dpi_awareness()
        _ensure_win32_ctypes_signatures()

        white_scale = (
            max(config.manual_sdr_nits / 80.0, 0.5)
            if config.manual_sdr_nits > 0
            else 2.5
        )

        orig_cursor = get_physical_cursor_pos()
        win32_monitors = enumerate_win32_monitors()
        target_monitor = resolve_physical_monitor_for_cursor(
            orig_cursor, win32_monitors
        )
        monitor_name = target_monitor.device_name
        monitor_rect = target_monitor.physical_rect

        DIAG_LOG.milestone(
            "CAPTURE_START",
            f"cursor={orig_cursor}, win32_monitor='{target_monitor.device_name}' "
            f"(hmon=0x{target_monitor.hmonitor:X}), rect={target_monitor.physical_rect}, "
            f"dpi={target_monitor.dpi_x} ({target_monitor.dpi_scale:.2f}x), "
            f"primary={target_monitor.is_primary}, safe_mode={config.is_safe_mode_active}, "
            f"disable_native_hdr={config.disable_native_hdr_capture}",
        )
        _debug_monitor_log(
            f"Capture triggered: original_cursor={orig_cursor}, "
            f"win32_monitor='{target_monitor.device_name}' (hmon=0x{target_monitor.hmonitor:X}), "
            f"physical_rect={target_monitor.physical_rect}, dpi={target_monitor.dpi_x} "
            f"({target_monitor.dpi_scale:.2f}x), primary={target_monitor.is_primary}"
        )

        # Explicit Diagnostic Isolation Bypass: if the user explicitly enabled
        # `disable_native_hdr_capture` in Settings to test whether DXGI/D3D11 is involved
        # in system freezes, skip native DXGI calls and make the SDR limitation explicit.
        if config.disable_native_hdr_capture:
            DIAG_LOG.warning(
                "CAPTURE_BYPASS",
                "Native DXGI/D3D11 capture bypassed because 'disable_native_hdr_capture' "
                "is enabled. Using diagnostic SDR-only ImageGrab (HDR surfaces will NOT be tone-mapped).",
            )
            from PIL import ImageGrab

            bbox = None
            if monitor_rect is not None:
                x, y, w, h = monitor_rect
                bbox = (x, y, x + w, y + h)
            grabbed = ImageGrab.grab(
                bbox=bbox, all_screens=(bbox is not None)
            ).convert("RGB")
            arr = np.ascontiguousarray(np.array(grabbed, dtype=np.uint8))
            post_cursor = get_physical_cursor_pos()
            dur_ms = (time.perf_counter() - t_capture_start) * 1000.0
            DIAG_LOG.milestone(
                "CAPTURE_DONE",
                f"Diagnostic SDR-only ImageGrab completed in {dur_ms:.1f} ms "
                f"(size={arr.shape[1]}x{arr.shape[0]}).",
            )
            PERF_TELEMETRY.record_stage("monitor_enum", dur_ms)
            PERF_TELEMETRY.record_stage("d3d_init", 0.0)
            PERF_TELEMETRY.record_stage("acquire_frame", 0.0)
            PERF_TELEMETRY.record_stage("texture_readback", dur_ms)
            PERF_TELEMETRY.record_stage("tone_mapping", 0.0)
            return CapturedFrame(
                srgb_image=arr,
                raw_scrgb_float=None,
                detected_white_scale=white_scale,
                is_hdr_surface=False,
                virtual_rect=monitor_rect or (0, 0, arr.shape[1], arr.shape[0]),
                display_device=monitor_name,
                hmonitor=target_monitor.hmonitor,
                win32_device_name=target_monitor.device_name,
                adapter_description="Diagnostic SDR Bypass (DXGI Disabled)",
                cursor_physical=orig_cursor,
                cursor_after_capture=post_cursor,
                monitor_dpi_scale=target_monitor.dpi_scale,
                is_primary_monitor=target_monitor.is_primary,
                win32_monitors_snapshot=win32_monitors,
                full_width=arr.shape[1],
                full_height=arr.shape[0],
                is_preview=False,
                preview_stride=1,
            )

        if sys.platform == "win32":
            dxgi_factory = ctypes.c_void_p()
            selected_adapter = ctypes.c_void_p()
            d3d_device = ctypes.c_void_p()
            d3d_context = ctypes.c_void_p()
            dxgi_output = ctypes.c_void_p()
            dxgi_output6 = ctypes.c_void_p()
            dxgi_output1 = ctypes.c_void_p()
            duplication = ctypes.c_void_p()
            desktop_resource = ctypes.c_void_p()
            acquired_tex = ctypes.c_void_p()
            staging_tex = ctypes.c_void_p()

            # Track all enumerated COM pointers so even if an exception occurs mid-enumeration,
            # every single IDXGIAdapter1 and IDXGIOutput reference is deterministically released.
            enumerated_adapter_ptrs: List[ctypes.c_void_p] = []
            enumerated_output_ptrs: List[ctypes.c_void_p] = []
            frame_acquired: bool = False
            staging_mapped: bool = False

            try:
                dxgi = ctypes.windll.dxgi
                d3d11 = ctypes.windll.d3d11

                # Explicit 64-bit ctypes signatures for DXGI and D3D11 entry points
                dxgi.CreateDXGIFactory1.argtypes = [
                    ctypes.POINTER(GUID),
                    ctypes.POINTER(ctypes.c_void_p),
                ]
                dxgi.CreateDXGIFactory1.restype = ctypes.c_long

                d3d11.D3D11CreateDevice.argtypes = [
                    ctypes.c_void_p,  # pAdapter
                    ctypes.c_int,  # DriverType
                    wintypes.HMODULE,  # Software
                    wintypes.UINT,  # Flags
                    ctypes.POINTER(wintypes.UINT),  # pFeatureLevels
                    wintypes.UINT,  # FeatureLevels
                    wintypes.UINT,  # SDKVersion
                    ctypes.POINTER(ctypes.c_void_p),  # ppDevice
                    ctypes.POINTER(wintypes.UINT),  # pFeatureLevel
                    ctypes.POINTER(ctypes.c_void_p),  # ppImmediateContext
                ]
                d3d11.D3D11CreateDevice.restype = ctypes.c_long

                candidates: List[DXGIOutputCandidate] = []
                hr = dxgi.CreateDXGIFactory1(
                    ctypes.byref(IID_IDXGIFactory1), ctypes.byref(dxgi_factory)
                )
                if hr != 0 or not dxgi_factory.value:
                    raise RuntimeError(
                        f"CreateDXGIFactory1 failed: {format_hresult(hr)}"
                    )

                for adapter_idx in range(16):
                    adapter_ptr = ctypes.c_void_p()
                    found_adapter = _com_vtable_call(
                        dxgi_factory,
                        12,  # IDXGIFactory1::EnumAdapters1
                        ctypes.c_long,
                        [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)],
                        adapter_idx,
                        ctypes.byref(adapter_ptr),
                    )
                    if found_adapter != 0 or not adapter_ptr.value:
                        break
                    enumerated_adapter_ptrs.append(adapter_ptr)

                    adapter_desc = DXGI_ADAPTER_DESC1()
                    adapter_name = f"Adapter {adapter_idx}"
                    adapter_flags = 0
                    vendor_id = 0
                    device_id = 0
                    if (
                        _com_vtable_call(
                            adapter_ptr,
                            10,  # IDXGIAdapter1::GetDesc1
                            ctypes.c_long,
                            [ctypes.POINTER(DXGI_ADAPTER_DESC1)],
                            ctypes.byref(adapter_desc),
                        )
                        == 0
                    ):
                        adapter_name = (
                            str(adapter_desc.Description).split("\x00", 1)[0].strip()
                            or adapter_name
                        )
                        adapter_flags = int(adapter_desc.Flags)
                        vendor_id = int(adapter_desc.VendorId)
                        device_id = int(adapter_desc.DeviceId)

                    # Skip Microsoft Basic Render Driver / software adapters if hardware outputs exist
                    if (adapter_flags & DXGI_ADAPTER_FLAG_SOFTWARE) and candidates:
                        DIAG_LOG.log(
                            "DXGI_ENUM",
                            f"Skipping software adapter[{adapter_idx}]='{adapter_name}' (flags=0x{adapter_flags:X})",
                        )
                        _com_release(adapter_ptr)
                        continue

                    adapter_used = False
                    for output_idx in range(16):
                        out_ptr = ctypes.c_void_p()
                        found_out = _com_vtable_call(
                            adapter_ptr,
                            7,  # IDXGIAdapter::EnumOutputs
                            ctypes.c_long,
                            [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)],
                            output_idx,
                            ctypes.byref(out_ptr),
                        )
                        if found_out != 0 or not out_ptr.value:
                            break
                        enumerated_output_ptrs.append(out_ptr)

                        desc = DXGI_OUTPUT_DESC()
                        if (
                            _com_vtable_call(
                                out_ptr,
                                7,  # IDXGIOutput::GetDesc
                                ctypes.c_long,
                                [ctypes.POINTER(DXGI_OUTPUT_DESC)],
                                ctypes.byref(desc),
                            )
                            == 0
                            and desc.AttachedToDesktop
                        ):
                            rc = desc.DesktopCoordinates
                            d_rect = (
                                int(rc.left),
                                int(rc.top),
                                int(rc.right - rc.left),
                                int(rc.bottom - rc.top),
                            )
                            out_dev_name = (
                                str(desc.DeviceName).split("\x00", 1)[0].strip()
                            )
                            DIAG_LOG.log(
                                "DXGI_ENUM",
                                f"Found attached output: adapter[{adapter_idx}]='{adapter_name}' "
                                f"(ven=0x{vendor_id:04X}, dev=0x{device_id:04X}), "
                                f"output[{output_idx}]='{out_dev_name}', bounds={d_rect}, "
                                f"hmon=0x{_normalize_hmonitor(desc.Monitor):X}, rot={int(desc.Rotation)}",
                            )
                            candidates.append(
                                DXGIOutputCandidate(
                                    adapter_idx=adapter_idx,
                                    output_idx=output_idx,
                                    adapter_name=adapter_name,
                                    device_name=out_dev_name,
                                    desktop_rect=d_rect,
                                    hmonitor=_normalize_hmonitor(desc.Monitor),
                                    rotation=int(desc.Rotation),
                                    adapter_ptr=adapter_ptr,
                                    output_ptr=out_ptr,
                                )
                            )
                            adapter_used = True
                        else:
                            _com_release(out_ptr)
                    if not adapter_used:
                        _com_release(adapter_ptr)

                selected_cand, dxgi_match_reason = select_dxgi_output_for_monitor(
                    target_monitor, orig_cursor, candidates
                )
                selected_adapter = selected_cand.adapter_ptr
                dxgi_output = selected_cand.output_ptr

                # Immediately release all non-selected outputs and adapters (idempotent _com_release)
                for out_p in enumerated_output_ptrs:
                    if out_p is not dxgi_output and out_p.value != dxgi_output.value:
                        _com_release(out_p)
                for ad_p in enumerated_adapter_ptrs:
                    if (
                        ad_p is not selected_adapter
                        and ad_p.value != selected_adapter.value
                    ):
                        _com_release(ad_p)

                monitor_name = selected_cand.device_name or target_monitor.device_name
                monitor_rect = selected_cand.desktop_rect
                white_scale = get_windows_sdr_white_level_scale(
                    config.manual_sdr_nits, monitor_name
                )
                t_enum_ms = (time.perf_counter() - t_capture_start) * 1000.0
                PERF_TELEMETRY.record_stage("monitor_enum", t_enum_ms)

                DIAG_LOG.milestone(
                    "DXGI_SELECT",
                    f"Selected adapter[{selected_cand.adapter_idx}]='{selected_cand.adapter_name}', "
                    f"output[{selected_cand.output_idx}]='{monitor_name}', bounds={monitor_rect}, "
                    f"match='{dxgi_match_reason}', sdr_white_scale={white_scale:.3f} ({white_scale * 80.0:.0f} nits)",
                )
                _debug_monitor_log(
                    f"Selected DXGI output: adapter[{selected_cand.adapter_idx}]='{selected_cand.adapter_name}', "
                    f"output[{selected_cand.output_idx}]='{monitor_name}', "
                    f"dxgi_bounds={monitor_rect}, hmon=0x{selected_cand.hmonitor:X}, "
                    f"match='{dxgi_match_reason}', sdr_white_scale={white_scale:.3f} ({white_scale * 80.0:.0f} nits)"
                )

                t_d3d = time.perf_counter()
                feature_levels = (wintypes.UINT * 4)(
                    0xB100,  # D3D_FEATURE_LEVEL_11_1
                    0xB000,  # D3D_FEATURE_LEVEL_11_0
                    0xA100,  # D3D_FEATURE_LEVEL_10_1
                    0xA000,  # D3D_FEATURE_LEVEL_10_0
                )
                chosen_fl = wintypes.UINT(0)
                hr = d3d11.D3D11CreateDevice(
                    selected_adapter,
                    D3D_DRIVER_TYPE_UNKNOWN,
                    None,
                    0x20,  # D3D11_CREATE_DEVICE_BGRA_SUPPORT
                    feature_levels,
                    4,
                    7,  # D3D11_SDK_VERSION
                    ctypes.byref(d3d_device),
                    ctypes.byref(chosen_fl),
                    ctypes.byref(d3d_context),
                )
                if hr != 0 or not d3d_device.value or not d3d_context.value:
                    raise RuntimeError(
                        f"D3D11CreateDevice failed: {format_hresult(hr)}"
                    )
                DIAG_LOG.milestone(
                    "D3D11_DEVICE",
                    f"Created D3D11Device (fl=0x{chosen_fl.value:X}) in "
                    f"{(time.perf_counter() - t_d3d) * 1000.0:.1f} ms",
                )

                # Prefer IDXGIOutput6::DuplicateOutput1 (supports explicit scRGB FP16 format list)
                t_dupl = time.perf_counter()
                hr_qi6 = _com_vtable_call(
                    dxgi_output,
                    0,  # IUnknown::QueryInterface
                    ctypes.c_long,
                    [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
                    ctypes.byref(IID_IDXGIOutput6),
                    ctypes.byref(dxgi_output6),
                )
                dupl1_hr = None
                if hr_qi6 == 0 and dxgi_output6.value:
                    supported_formats = (wintypes.UINT * 3)(
                        DXGI_FORMAT_R16G16B16A16_FLOAT,
                        DXGI_FORMAT_B8G8R8A8_UNORM,
                        DXGI_FORMAT_R8G8B8A8_UNORM,
                    )
                    dupl1_hr = _com_vtable_call(
                        dxgi_output6,
                        26,  # IDXGIOutput5::DuplicateOutput1 (inherited by IDXGIOutput6)
                        ctypes.c_long,
                        [
                            ctypes.c_void_p,
                            wintypes.UINT,
                            wintypes.UINT,
                            ctypes.POINTER(wintypes.UINT),
                            ctypes.POINTER(ctypes.c_void_p),
                        ],
                        d3d_device,
                        0,
                        3,
                        supported_formats,
                        ctypes.byref(duplication),
                    )
                    if dupl1_hr == 0 and duplication.value:
                        DIAG_LOG.milestone(
                            "DXGI_DUPLICATE",
                            f"DuplicateOutput1 succeeded in {(time.perf_counter() - t_dupl) * 1000.0:.1f} ms",
                        )
                    else:
                        u_dupl1 = int(dupl1_hr) & 0xFFFFFFFF
                        removed_info = (
                            f", removed_reason={query_d3d11_device_removed_reason(d3d_device)}"
                            if u_dupl1
                            in (
                                DXGI_ERROR_DEVICE_REMOVED,
                                DXGI_ERROR_DEVICE_RESET,
                                DXGI_ERROR_DEVICE_HUNG,
                            )
                            else ""
                        )
                        DIAG_LOG.warning(
                            "DXGI_DUPLICATE",
                            f"DuplicateOutput1 returned {format_hresult(dupl1_hr)}{removed_info}",
                        )
                        if u_dupl1 in (
                            DXGI_ERROR_DEVICE_REMOVED,
                            DXGI_ERROR_DEVICE_RESET,
                            DXGI_ERROR_DEVICE_HUNG,
                            E_ACCESSDENIED,
                            DXGI_ERROR_ModeChangeInProgress,
                            DXGI_ERROR_SESSION_DISCONNECTED,
                        ):
                            raise RuntimeError(
                                f"DuplicateOutput1 failed with terminal status: {format_hresult(dupl1_hr)}{removed_info}"
                            )

                if not duplication.value:
                    hr = _com_vtable_call(
                        dxgi_output,
                        0,  # IUnknown::QueryInterface
                        ctypes.c_long,
                        [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
                        ctypes.byref(IID_IDXGIOutput1),
                        ctypes.byref(dxgi_output1),
                    )
                    if hr != 0 or not dxgi_output1.value:
                        raise RuntimeError(
                            f"QueryInterface(IDXGIOutput1) failed: {format_hresult(hr)}"
                        )
                    hr = _com_vtable_call(
                        dxgi_output1,
                        22,  # IDXGIOutput1::DuplicateOutput
                        ctypes.c_long,
                        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
                        d3d_device,
                        ctypes.byref(duplication),
                    )
                    if hr != 0 or not duplication.value:
                        u_hr = int(hr) & 0xFFFFFFFF
                        removed_info = (
                            f", removed_reason={query_d3d11_device_removed_reason(d3d_device)}"
                            if u_hr
                            in (
                                DXGI_ERROR_DEVICE_REMOVED,
                                DXGI_ERROR_DEVICE_RESET,
                                DXGI_ERROR_DEVICE_HUNG,
                            )
                            else ""
                        )
                        raise RuntimeError(
                            f"DuplicateOutput failed: {format_hresult(hr)}{removed_info}"
                        )
                    DIAG_LOG.milestone(
                        "DXGI_DUPLICATE",
                        f"DuplicateOutput (IDXGIOutput1) succeeded in {(time.perf_counter() - t_dupl) * 1000.0:.1f} ms",
                    )
                t_d3d_ms = (time.perf_counter() - t_d3d) * 1000.0
                PERF_TELEMETRY.record_stage("d3d_init", t_d3d_ms)

                # Bounded frame acquisition:
                # Nudge DWM upfront with safe zero-delta relative mouse move so static desktops
                # compose immediately on the next refresh without 220ms timeout stalls.
                t_acq_start = time.perf_counter()
                ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, 0, 0, 0, 0)
                frame_info = DXGI_OUTDUPL_FRAME_INFO()
                max_attempts = 3
                last_acq_hr = -1
                for attempt in range(max_attempts):
                    # 45ms is more than 2 full frames at 60Hz (16.6ms) and ample at higher refresh rates
                    timeout_ms = 45 if attempt == 0 else 75
                    ctypes.memset(
                        ctypes.byref(frame_info),
                        0,
                        ctypes.sizeof(DXGI_OUTDUPL_FRAME_INFO),
                    )
                    hr = _com_vtable_call(
                        duplication,
                        8,  # IDXGIOutputDuplication::AcquireNextFrame
                        ctypes.c_long,
                        [
                            wintypes.UINT,
                            ctypes.POINTER(DXGI_OUTDUPL_FRAME_INFO),
                            ctypes.POINTER(ctypes.c_void_p),
                        ],
                        timeout_ms,
                        ctypes.byref(frame_info),
                        ctypes.byref(desktop_resource),
                    )
                    last_acq_hr = hr
                    u_hr = int(hr) & 0xFFFFFFFF

                    if hr == 0:
                        frame_acquired = True
                        if desktop_resource.value and (
                            frame_info.LastPresentTime != 0
                            or frame_info.AccumulatedFrames > 0
                            or attempt == max_attempts - 1
                        ):
                            DIAG_LOG.milestone(
                                "DXGI_ACQUIRE",
                                f"AcquireNextFrame succeeded on attempt {attempt + 1}/{max_attempts} "
                                f"(accumulated={frame_info.AccumulatedFrames}, "
                                f"last_present={frame_info.LastPresentTime})",
                            )
                            break
                        # Release frame lock cleanly before retrying
                        _com_release(desktop_resource)
                        _com_vtable_call(duplication, 14, ctypes.c_long, [])
                        frame_acquired = False
                        time.sleep(0.005)
                        continue

                    if u_hr in DXGI_TERMINAL_HRESULTS:
                        removed_info = (
                            f", removed_reason={query_d3d11_device_removed_reason(d3d_device)}"
                            if u_hr
                            in (
                                DXGI_ERROR_DEVICE_REMOVED,
                                DXGI_ERROR_DEVICE_RESET,
                                DXGI_ERROR_DEVICE_HUNG,
                            )
                            else ""
                        )
                        DIAG_LOG.warning(
                            "DXGI_ACQUIRE",
                            f"AcquireNextFrame terminal failure on attempt {attempt + 1}: "
                            f"{format_hresult(hr)}{removed_info} (aborting retries)",
                        )
                        break

                    # Retry on DXGI_ERROR_WAIT_TIMEOUT; nudge mouse again
                    DIAG_LOG.log(
                        "DXGI_ACQUIRE",
                        f"AcquireNextFrame attempt {attempt + 1}/{max_attempts} returned {format_hresult(hr)}",
                    )
                    ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, 0, 0, 0, 0)
                    time.sleep(0.005)

                t_acq_ms = (time.perf_counter() - t_acq_start) * 1000.0
                PERF_TELEMETRY.record_stage("acquire_frame", t_acq_ms)

                if not frame_acquired or not desktop_resource.value:
                    raise RuntimeError(
                        f"AcquireNextFrame did not yield a desktop frame: {format_hresult(last_acq_hr)}"
                    )

                hr = _com_vtable_call(
                    desktop_resource,
                    0,  # IUnknown::QueryInterface(ID3D11Texture2D)
                    ctypes.c_long,
                    [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
                    ctypes.byref(IID_ID3D11Texture2D),
                    ctypes.byref(acquired_tex),
                )
                if hr != 0 or not acquired_tex.value:
                    raise RuntimeError(
                        f"QueryInterface(ID3D11Texture2D) failed: {format_hresult(hr)}"
                    )

                tex_desc = D3D11_TEXTURE2D_DESC()
                _com_vtable_call(
                    acquired_tex,
                    10,  # ID3D11Texture2D::GetDesc
                    None,
                    [ctypes.POINTER(D3D11_TEXTURE2D_DESC)],
                    ctypes.byref(tex_desc),
                )

                tex_w = int(tex_desc.Width)
                tex_h = int(tex_desc.Height)
                tex_fmt = int(tex_desc.Format)
                if tex_w <= 0 or tex_h <= 0 or tex_w > 32768 or tex_h > 32768:
                    raise RuntimeError(
                        f"Invalid DXGI desktop texture dimensions: {tex_w}x{tex_h} (fmt={tex_fmt})"
                    )
                if tex_fmt not in (
                    DXGI_FORMAT_R16G16B16A16_FLOAT,
                    DXGI_FORMAT_B8G8R8A8_UNORM,
                    DXGI_FORMAT_R8G8B8A8_UNORM,
                ):
                    raise RuntimeError(
                        f"Unsupported DXGI pixel format {tex_fmt}; cannot safely read back HDR/SDR frame"
                    )

                t_readback_start = time.perf_counter()
                # Construct a clean CPU-readable staging texture description from scratch
                # (never copy DWM shared-resource MiscFlags such as SHARED_KEYEDMUTEX / NTHANDLE)
                staging_desc = D3D11_TEXTURE2D_DESC()
                staging_desc.Width = wintypes.UINT(tex_w)
                staging_desc.Height = wintypes.UINT(tex_h)
                staging_desc.MipLevels = wintypes.UINT(1)
                staging_desc.ArraySize = wintypes.UINT(1)
                staging_desc.Format = wintypes.UINT(tex_fmt)
                staging_desc.SampleDesc.Count = wintypes.UINT(1)
                staging_desc.SampleDesc.Quality = wintypes.UINT(0)
                staging_desc.Usage = wintypes.UINT(D3D11_USAGE_STAGING)
                staging_desc.BindFlags = wintypes.UINT(0)
                staging_desc.CPUAccessFlags = wintypes.UINT(D3D11_CPU_ACCESS_READ)
                staging_desc.MiscFlags = wintypes.UINT(0)

                hr = _com_vtable_call(
                    d3d_device,
                    5,  # ID3D11Device::CreateTexture2D
                    ctypes.c_long,
                    [
                        ctypes.POINTER(D3D11_TEXTURE2D_DESC),
                        ctypes.c_void_p,
                        ctypes.POINTER(ctypes.c_void_p),
                    ],
                    ctypes.byref(staging_desc),
                    None,
                    ctypes.byref(staging_tex),
                )
                if hr != 0 or not staging_tex.value:
                    raise RuntimeError(
                        f"CreateTexture2D(staging {tex_w}x{tex_h} fmt={tex_fmt}) failed: {format_hresult(hr)}"
                    )

                # Copy GPU desktop texture to CPU-readable staging texture
                _com_vtable_call(
                    d3d_context,
                    47,  # ID3D11DeviceContext::CopyResource
                    None,
                    [ctypes.c_void_p, ctypes.c_void_p],
                    staging_tex,
                    acquired_tex,
                )

                # Keep `acquired_tex`, `desktop_resource`, and the DXGI duplication frame lock held
                # until `Map(..., D3D11_MAP_READ)` completes GPU->CPU synchronization and `Unmap()`
                # finishes so DWM can never reclaim the shared desktop surface mid-copy.
                mapped = D3D11_MAPPED_SUBRESOURCE()
                hr = _com_vtable_call(
                    d3d_context,
                    14,  # ID3D11DeviceContext::Map
                    ctypes.c_long,
                    [
                        ctypes.c_void_p,
                        wintypes.UINT,
                        wintypes.UINT,
                        wintypes.UINT,
                        ctypes.POINTER(D3D11_MAPPED_SUBRESOURCE),
                    ],
                    staging_tex,
                    0,
                    D3D11_MAP_READ,
                    0,
                    ctypes.byref(mapped),
                )
                if hr != 0 or not mapped.pData:
                    removed_info = (
                        f", removed_reason={query_d3d11_device_removed_reason(d3d_device)}"
                        if (int(hr) & 0xFFFFFFFF)
                        in (
                            DXGI_ERROR_DEVICE_REMOVED,
                            DXGI_ERROR_DEVICE_RESET,
                            DXGI_ERROR_DEVICE_HUNG,
                        )
                        else ""
                    )
                    raise RuntimeError(
                        f"ID3D11DeviceContext::Map failed: {format_hresult(hr)}{removed_info}"
                    )
                staging_mapped = True

                bpp = 8 if tex_fmt == DXGI_FORMAT_R16G16B16A16_FLOAT else 4
                row_pitch = int(mapped.RowPitch)
                min_row_pitch = tex_w * bpp
                if (
                    row_pitch < min_row_pitch
                    or row_pitch > 524288
                    or (row_pitch % bpp) != 0
                ):
                    raise RuntimeError(
                        f"Invalid mapped RowPitch={row_pitch} for width={tex_w}, bpp={bpp} "
                        f"(expected >= {min_row_pitch} and divisible by {bpp})"
                    )

                total_bytes = row_pitch * tex_h
                raw_bytes = ctypes.string_at(mapped.pData, total_bytes)

                # Immediately unmap staging texture after copying bytes into owned Python memory
                _com_vtable_call(
                    d3d_context,
                    15,  # ID3D11DeviceContext::Unmap
                    None,
                    [ctypes.c_void_p, wintypes.UINT],
                    staging_tex,
                    0,
                )
                staging_mapped = False

                # Now that GPU->CPU readback is 100% complete, release the desktop surface and frame lock
                _com_release(acquired_tex)
                _com_release(desktop_resource)
                hr_rel_frame = _com_vtable_call(
                    duplication, 14, ctypes.c_long, []
                )  # IDXGIOutputDuplication::ReleaseFrame
                frame_acquired = False
                if hr_rel_frame != 0:
                    DIAG_LOG.warning(
                        "DXGI_RELEASE_FRAME",
                        f"ReleaseFrame returned {format_hresult(hr_rel_frame)}",
                    )

                post_cursor = get_physical_cursor_pos()
                if post_cursor != orig_cursor:
                    ctypes.windll.user32.SetCursorPos(orig_cursor[0], orig_cursor[1])
                    post_cursor = get_physical_cursor_pos()

                readback_ms = (time.perf_counter() - t_readback_start) * 1000.0
                PERF_TELEMETRY.record_dxgi_acquire(readback_ms)
                PERF_TELEMETRY.record_stage("texture_readback", readback_ms)
                DIAG_LOG.milestone(
                    "DXGI_READBACK",
                    f"Read back {tex_w}x{tex_h} framebuffer (fmt={tex_fmt}, row_pitch={row_pitch}, "
                    f"bytes={total_bytes}) in {readback_ms:.1f} ms",
                )
                _debug_monitor_log(
                    f"Captured framebuffer: size={tex_w}x{tex_h}, format={tex_fmt}, "
                    f"cursor_after_capture={post_cursor}"
                )

                t_tm_start = time.perf_counter()
                if tex_fmt == DXGI_FORMAT_R16G16B16A16_FLOAT:
                    pixels_per_row = row_pitch // 8
                    f16_buf = np.frombuffer(raw_bytes, dtype=np.float16).reshape(
                        (tex_h, pixels_per_row, 4)
                    )[:, :tex_w, :3].copy()

                    # Fast responsive preview generation:
                    # Select preview stride: target max dimension ~1280 to 1440 px
                    max_dim = max(tex_w, tex_h)
                    if max_dim >= 3840:
                        preview_stride = 3
                    elif max_dim >= 2560:
                        preview_stride = 2
                    elif max_dim >= 1920:
                        preview_stride = 2
                    else:
                        preview_stride = 1

                    preview_f16 = f16_buf[::preview_stride, ::preview_stride, :]
                    preview_srgb = tone_map_scrgb_to_srgb(
                        preview_f16,
                        white_scale=white_scale,
                        mode=config.tone_map_mode,
                        knee_start=config.knee_start,
                        max_headroom=config.max_headroom,
                        auto_hdr_gamma22_fix=config.auto_hdr_gamma22_fix,
                        boost_sdr_whites=config.boost_sdr_whites,
                    )
                    t_tm = (time.perf_counter() - t_tm_start) * 1000.0
                    PERF_TELEMETRY.record_stage("tone_mapping", t_tm)

                    DIAG_LOG.milestone(
                        "CAPTURE_DONE",
                        f"HDR FP16 capture + fast preview completed in "
                        f"{(time.perf_counter() - t_capture_start) * 1000.0:.1f} ms "
                        f"(stride={preview_stride}, preview_tone_map={t_tm:.1f} ms, "
                        f"monitor='{monitor_name}', white_scale={white_scale:.3f})",
                    )
                    return CapturedFrame(
                        srgb_image=preview_srgb,
                        raw_scrgb_float=f16_buf,
                        full_width=tex_w,
                        full_height=tex_h,
                        is_preview=(preview_stride > 1),
                        preview_stride=preview_stride,
                        detected_white_scale=white_scale,
                        is_hdr_surface=True,
                        virtual_rect=monitor_rect or (0, 0, tex_w, tex_h),
                        display_device=monitor_name,
                        hmonitor=target_monitor.hmonitor,
                        win32_device_name=target_monitor.device_name,
                        adapter_description=selected_cand.adapter_name,
                        adapter_index=selected_cand.adapter_idx,
                        output_index=selected_cand.output_idx,
                        cursor_physical=orig_cursor,
                        cursor_after_capture=post_cursor,
                        monitor_dpi_scale=target_monitor.dpi_scale,
                        is_primary_monitor=target_monitor.is_primary,
                        win32_monitors_snapshot=win32_monitors,
                    )

                elif tex_fmt in (
                    DXGI_FORMAT_B8G8R8A8_UNORM,
                    DXGI_FORMAT_R8G8B8A8_UNORM,
                ):
                    if (
                        windows_display_hdr_enabled(monitor_name) is not False
                        and not config.allow_sdr_fallback
                    ):
                        raise RuntimeError(
                            "HDR is enabled, but DirectX returned only 8-bit pixels. "
                            "Refusing to produce a potentially blown-out screenshot."
                        )
                    pixels_per_row = row_pitch // 4
                    u8_buf = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(
                        (tex_h, pixels_per_row, 4)
                    )[:, :tex_w, :]
                    if tex_fmt == DXGI_FORMAT_B8G8R8A8_UNORM:
                        rgb_img = np.ascontiguousarray(u8_buf[..., [2, 1, 0]])
                    else:
                        rgb_img = np.ascontiguousarray(u8_buf[..., :3])
                    t_tm = (time.perf_counter() - t_tm_start) * 1000.0
                    PERF_TELEMETRY.record_stage("tone_mapping", t_tm)

                    DIAG_LOG.milestone(
                        "CAPTURE_DONE",
                        f"SDR 8-bit DXGI capture completed in "
                        f"{(time.perf_counter() - t_capture_start) * 1000.0:.1f} ms "
                        f"(monitor='{monitor_name}')",
                    )
                    return CapturedFrame(
                        srgb_image=rgb_img,
                        raw_scrgb_float=None,
                        full_width=tex_w,
                        full_height=tex_h,
                        is_preview=False,
                        preview_stride=1,
                        detected_white_scale=white_scale,
                        is_hdr_surface=False,
                        virtual_rect=monitor_rect or (0, 0, tex_w, tex_h),
                        display_device=monitor_name,
                        hmonitor=target_monitor.hmonitor,
                        win32_device_name=target_monitor.device_name,
                        adapter_description=selected_cand.adapter_name,
                        adapter_index=selected_cand.adapter_idx,
                        output_index=selected_cand.output_idx,
                        cursor_physical=orig_cursor,
                        cursor_after_capture=post_cursor,
                        monitor_dpi_scale=target_monitor.dpi_scale,
                        is_primary_monitor=target_monitor.is_primary,
                        win32_monitors_snapshot=win32_monitors,
                    )

            except Exception as exc:
                DIAG_LOG.error(
                    "DXGI_CAPTURE_ERROR",
                    f"DXGI capture failed on monitor '{monitor_name}'",
                    exc,
                )
                if (
                    not config.allow_sdr_fallback
                    and windows_display_hdr_enabled(monitor_name) is not False
                ):
                    raise RuntimeError(
                        f"HDR DXGI capture failed on {monitor_name}: {exc}. "
                        "Enable SDR fallback in Settings if needed."
                    ) from exc
                print(
                    f"[HDRSnip Fusion] DXGI capture note ({exc}); using fallback capture."
                )
            finally:
                try:
                    cur_now = get_physical_cursor_pos()
                    if cur_now != orig_cursor:
                        ctypes.windll.user32.SetCursorPos(
                            orig_cursor[0], orig_cursor[1]
                        )
                except Exception:
                    pass

                # 1. Guaranteed Unmap() if staging_tex was mapped when an error occurred
                if staging_mapped and d3d_context.value and staging_tex.value:
                    try:
                        _com_vtable_call(
                            d3d_context,
                            15,  # ID3D11DeviceContext::Unmap
                            None,
                            [ctypes.c_void_p, wintypes.UINT],
                            staging_tex,
                            0,
                        )
                    except Exception as unmap_exc:
                        DIAG_LOG.warning(
                            "DXGI_CLEANUP", f"Unmap in finally note: {unmap_exc}"
                        )
                    staging_mapped = False

                # 2. Release texture resources before releasing frame lock / duplication
                _com_release(staging_tex)
                _com_release(acquired_tex)
                _com_release(desktop_resource)

                # 3. Guaranteed ReleaseFrame() if AcquireNextFrame succeeded before an error
                if frame_acquired and duplication.value:
                    try:
                        _com_vtable_call(duplication, 14, ctypes.c_long, [])
                    except Exception as rf_exc:
                        DIAG_LOG.warning(
                            "DXGI_CLEANUP", f"ReleaseFrame in finally note: {rf_exc}"
                        )
                    frame_acquired = False

                # 4. Release duplication & output interfaces in reverse-dependency order
                _com_release(duplication)
                _com_release(dxgi_output1)
                _com_release(dxgi_output6)
                _com_release(dxgi_output)

                # 5. Release any remaining enumerated outputs/adapters (idempotent)
                for out_p in enumerated_output_ptrs:
                    _com_release(out_p)
                for ad_p in enumerated_adapter_ptrs:
                    if (
                        ad_p is not selected_adapter
                        and ad_p.value != selected_adapter.value
                    ):
                        _com_release(ad_p)

                # 6. Clear D3D11 immediate context state before releasing context & device
                if d3d_context.value:
                    try:
                        _com_vtable_call(
                            d3d_context, 110, None, []
                        )  # ID3D11DeviceContext::ClearState
                    except Exception:
                        pass
                _com_release(d3d_context)
                _com_release(d3d_device)
                _com_release(selected_adapter)
                _com_release(dxgi_factory)

        # Fallback if running on a confirmed SDR display or non-Windows environment
        from PIL import ImageGrab

        bbox = None
        if monitor_rect is not None:
            x, y, w, h = monitor_rect
            bbox = (x, y, x + w, y + h)
        grabbed = ImageGrab.grab(
            bbox=bbox, all_screens=(bbox is not None)
        ).convert("RGB")
        arr = np.ascontiguousarray(np.array(grabbed, dtype=np.uint8))
        post_cursor = get_physical_cursor_pos()
        DIAG_LOG.milestone(
            "CAPTURE_DONE",
            f"Fallback ImageGrab capture completed in {(time.perf_counter() - t_capture_start) * 1000.0:.1f} ms",
        )
        return CapturedFrame(
            srgb_image=arr,
            raw_scrgb_float=None,
            full_width=arr.shape[1],
            full_height=arr.shape[0],
            is_preview=False,
            preview_stride=1,
            detected_white_scale=white_scale,
            is_hdr_surface=False,
            virtual_rect=monitor_rect or (0, 0, arr.shape[1], arr.shape[0]),
            display_device=monitor_name,
            hmonitor=target_monitor.hmonitor,
            win32_device_name=target_monitor.device_name,
            cursor_physical=orig_cursor,
            cursor_after_capture=post_cursor,
            monitor_dpi_scale=target_monitor.dpi_scale,
            is_primary_monitor=target_monitor.is_primary,
            win32_monitors_snapshot=win32_monitors,
        )
    finally:
        _CAPTURE_LOCK.release()


# =============================================================================
# 5. GLOBAL HOTKEY MANAGER (WIN32 RegisterHotKey - GAME & ANTI-CHEAT SAFE)
# =============================================================================

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_MAP = {
    "PRINTSCREEN": 0x2C,
    "PRINT": 0x2C,
    "SNAPSHOT": 0x2C,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PGUP": 0x21,
    "PGDOWN": 0x22,
    "SPACE": 0x20,
    "TAB": 0x09,
    "BACKSPACE": 0x08,
    "PAUSE": 0x13,
}
for _i in range(1, 25):
    VK_MAP[f"F{_i}"] = 0x70 + (_i - 1)


def parse_hotkey_string(hotkey_str: str) -> Tuple[int, int]:
    """Parses a Qt/human hotkey string like 'Ctrl+Shift+X' into Win32 (modifiers, vk_code)."""
    parts = [p.strip().upper() for p in hotkey_str.split("+") if p.strip()]
    mods = MOD_NOREPEAT
    vk = 0x2C  # Default PrintScreen

    for part in parts:
        if part in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif part == "SHIFT":
            mods |= MOD_SHIFT
        elif part == "ALT":
            mods |= MOD_ALT
        elif part in ("WIN", "META", "SUPER"):
            mods |= MOD_WIN
        elif part in VK_MAP:
            vk = VK_MAP[part]
        elif len(part) == 1 and ("A" <= part <= "Z" or "0" <= part <= "9"):
            vk = ord(part)

    return mods, vk


if HAS_QT:

    class Win32HotkeyListener(QObject):
        """Runs a lightweight Win32 GetMessage loop in a background thread for global hotkeys."""

        hotkey_triggered = pyqtSignal([float], [])
        hotkey_failed = pyqtSignal(str)

        def __init__(self, hotkey_str: str) -> None:
            super().__init__()
            self.hotkey_str = hotkey_str
            self._thread_id: Optional[int] = None
            self._thread: Optional[threading.Thread] = None
            self._running = False

        def start(self) -> None:
            if sys.platform != "win32":
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

        def stop(self) -> None:
            self._running = False
            if sys.platform == "win32" and self._thread_id is not None:
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, WM_QUIT, 0, 0
                )
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
            self._thread_id = None

        def update_hotkey(self, new_hotkey_str: str) -> None:
            self.stop()
            self.hotkey_str = new_hotkey_str
            self.start()

        def _run_loop(self) -> None:
            ensure_per_monitor_dpi_awareness()
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._thread_id = kernel32.GetCurrentThreadId()

            _ensure_win32_ctypes_signatures()
            mods, vk = parse_hotkey_string(self.hotkey_str)
            hotkey_id = 1
            if not user32.RegisterHotKey(None, hotkey_id, mods, vk):
                message = (
                    f"Couldn't register {self.hotkey_str}; another app may be using it."
                )
                print(f"[HDRSnip Fusion] {message}")
                DIAG_LOG.warning("HOTKEY", message)
                self.hotkey_failed.emit(message)
                return

            DIAG_LOG.log(
                "HOTKEY",
                f"Registered global hotkey '{self.hotkey_str}' (mods=0x{mods:X}, vk=0x{vk:X}, tid={self._thread_id})",
            )
            msg = wintypes.MSG()
            try:
                while self._running:
                    b_ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if b_ret <= 0:
                        break
                    if msg.message == WM_HOTKEY and msg.wParam == hotkey_id:
                        t_rx = time.perf_counter()
                        DIAG_LOG.log(
                            "HOTKEY", f"Global hotkey '{self.hotkey_str}' triggered"
                        )
                        try:
                            self.hotkey_triggered[float].emit(t_rx)
                        except Exception:
                            self.hotkey_triggered.emit()
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
            finally:
                user32.UnregisterHotKey(None, hotkey_id)
                DIAG_LOG.log(
                    "HOTKEY", f"Unregistered global hotkey '{self.hotkey_str}'"
                )


# =============================================================================
# 6. ASYNC BACKGROUND TONE-MAPPING WORKER FOR LIVE HDR SLIDER
# =============================================================================

if HAS_QT:

    class ToneRenderSignals(QObject):
        done = pyqtSignal(int, object, bool, float)

    class ToneRenderJob(QRunnable):
        def __init__(
            self,
            signals: ToneRenderSignals,
            frame: np.ndarray,
            revision: int,
            white_scale: float,
            full: bool,
            mode: str,
            knee: float,
            headroom: float,
            gamma_fix: bool,
            boost_whites: bool,
            cancel_event: Optional[threading.Event] = None,
        ) -> None:
            super().__init__()
            self.signals = signals
            self.frame: Optional[np.ndarray] = frame
            self.revision = revision
            self.white_scale = white_scale
            self.full = full
            self.mode = mode
            self.knee = knee
            self.headroom = headroom
            self.gamma_fix = gamma_fix
            self.boost_whites = boost_whites
            self.cancel_event = cancel_event
            _adjust_active_tone_workers(1)

        def _safe_emit_done(self, rgb: Optional[np.ndarray]) -> None:
            try:
                if self.signals is not None:
                    self.signals.done.emit(
                        self.revision, rgb, self.full, self.white_scale
                    )
            except RuntimeError:
                # QObject receiver was already deleted during shutdown
                pass

        def run(self) -> None:
            t_w0 = time.perf_counter()
            try:
                if (
                    self.frame is None
                    or (self.cancel_event is not None and self.cancel_event.is_set())
                ):
                    DIAG_LOG.log(
                        "TONE_WORKER",
                        f"Worker rev={self.revision} cancelled before start",
                    )
                    self._safe_emit_done(None)
                    return
                pixels = self.frame if self.full else self.frame[::2, ::2, :]
                rgb = tone_map_scrgb_to_srgb(
                    pixels,
                    white_scale=self.white_scale,
                    mode=self.mode,
                    knee_start=self.knee,
                    max_headroom=self.headroom,
                    auto_hdr_gamma22_fix=self.gamma_fix,
                    boost_sdr_whites=self.boost_whites,
                )
                if self.cancel_event is not None and self.cancel_event.is_set():
                    DIAG_LOG.log(
                        "TONE_WORKER",
                        f"Worker rev={self.revision} cancelled after compute",
                    )
                    self._safe_emit_done(None)
                    return
                DIAG_LOG.log(
                    "TONE_WORKER",
                    f"Worker rev={self.revision} (full={self.full}, white={self.white_scale:.2f}) "
                    f"finished in {(time.perf_counter() - t_w0) * 1000.0:.1f} ms",
                )
                self._safe_emit_done(rgb)
            except Exception as exc:
                print(f"[HDRSnip Fusion] Tone-mapping worker failed: {exc}")
                DIAG_LOG.error(
                    "TONE_WORKER", f"Worker rev={self.revision} failed", exc
                )
                self._safe_emit_done(None)
            finally:
                # Always drop the worker reference to the 50 MB raw HDR buffer immediately
                self.frame = None
                _adjust_active_tone_workers(-1)


    class InitialFullToneRenderSignals(QObject):
        done = pyqtSignal(object)


    class InitialFullToneRenderJob(QRunnable):
        """
        Asynchronous background worker that renders the full-resolution 4K HDR frame
        while the user is already interacting with the fast preview overlay.
        """

        def __init__(
            self,
            signals: InitialFullToneRenderSignals,
            frame: np.ndarray,
            white_scale: float,
            mode: str,
            knee: float,
            headroom: float,
            gamma_fix: bool,
            boost_whites: bool,
            cancel_event: Optional[threading.Event] = None,
        ) -> None:
            super().__init__()
            self.signals = signals
            self.frame: Optional[np.ndarray] = frame
            self.white_scale = white_scale
            self.mode = mode
            self.knee = knee
            self.headroom = headroom
            self.gamma_fix = gamma_fix
            self.boost_whites = boost_whites
            self.cancel_event = cancel_event
            _adjust_active_tone_workers(1)

        def run(self) -> None:
            try:
                if (
                    self.frame is None
                    or (self.cancel_event is not None and self.cancel_event.is_set())
                ):
                    return
                t0 = time.perf_counter()
                rgb = tone_map_scrgb_to_srgb(
                    self.frame,
                    white_scale=self.white_scale,
                    mode=self.mode,
                    knee_start=self.knee,
                    max_headroom=self.headroom,
                    auto_hdr_gamma22_fix=self.gamma_fix,
                    boost_sdr_whites=self.boost_whites,
                )
                if self.cancel_event is not None and self.cancel_event.is_set():
                    return
                t_tm = (time.perf_counter() - t0) * 1000.0
                PERF_TELEMETRY.record_stage("bg_full_tone_map", t_tm)
                DIAG_LOG.log(
                    "TONE_WORKER",
                    f"Background full-resolution tone-mapping completed in {t_tm:.1f} ms",
                )
                if self.signals is not None:
                    self.signals.done.emit(rgb)
            except Exception as exc:
                DIAG_LOG.error(
                    "TONE_WORKER", "Background full-resolution tone-mapping failed", exc
                )
            finally:
                self.frame = None
                _adjust_active_tone_workers(-1)


# =============================================================================
# 7. FRUTIGER AERO / AQUA LIQUID GLASS & SKEUOMORPHIC GEL ANIMATION ENGINE
# =============================================================================

class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attrib", ctypes.c_int),
        ("pvData", ctypes.c_void_p),
        ("cbData", ctypes.c_size_t),
    ]


def enable_windows_acrylic_blur(
    hwnd: int, abgr_tint: int = 0x55A8780A, *, disable_blur: bool = False
) -> None:
    """
    Enables or disables native Windows 10/11 DWM Acrylic Blur-Behind on a top-level
    translucent window (such as SettingsDialog) via SetWindowCompositionAttribute.
    When Diagnostic Safe Mode or `disable_dwm_acrylic_blur` is active, sets
    ACCENT_DISABLED (0) so undocumented DWM acrylic composition is bypassed cleanly.
    """
    if sys.platform != "win32" or not hwnd:
        return
    try:
        _ensure_win32_ctypes_signatures()
        user32 = ctypes.windll.user32
        user32.SetWindowCompositionAttribute.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(WINDOWCOMPOSITIONATTRIBDATA),
        ]
        user32.SetWindowCompositionAttribute.restype = wintypes.BOOL

        policy = ACCENT_POLICY()
        if disable_blur or ENV_SAFE_MODE:
            policy.AccentState = 0  # ACCENT_DISABLED
            policy.AccentFlags = 0
            policy.GradientColor = 0
        else:
            policy.AccentState = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND
            policy.AccentFlags = 2
            policy.GradientColor = int(abgr_tint) & 0xFFFFFFFF
        policy.AnimationId = 0

        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attrib = 19  # WCA_ACCENT_POLICY
        data.pvData = ctypes.cast(ctypes.byref(policy), ctypes.c_void_p)
        data.cbData = ctypes.sizeof(policy)
        user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(data))
    except Exception as exc:
        DIAG_LOG.warning("DWM_ACRYLIC", f"SetWindowCompositionAttribute note: {exc}")


def make_frosted_acrylic_pixmap(
    srgb_array: np.ndarray,
    crop_x: int,
    crop_y: int,
    crop_w: int,
    crop_h: int,
    blur_radius: int = 12,
) -> Optional["QPixmap"]:
    """
    Samples the actual screen region behind a UI element, applies a fast Gaussian
    acrylic blur via Pillow, and returns a QPixmap for true refractive glass rendering.
    """
    if not HAS_QT:
        return None
    h, w, _ = srgb_array.shape
    x0 = max(0, min(w - 1, crop_x))
    y0 = max(0, min(h - 1, crop_y))
    x1 = max(x0 + 1, min(w, crop_x + crop_w))
    y1 = max(y0 + 1, min(h, crop_y + crop_h))

    sub = srgb_array[y0:y1, x0:x1]
    if sub.size == 0:
        return None

    pil_img = Image.fromarray(sub, mode="RGB")
    # Downscale 4x before Gaussian blur for <0.5ms real-time 60fps dragging performance
    small_w = max(1, (x1 - x0) // 4)
    small_h = max(1, (y1 - y0) // 4)
    pil_small = pil_img.resize((small_w, small_h), Image.Resampling.BILINEAR)
    pil_blur = pil_small.filter(ImageFilter.GaussianBlur(radius=max(2, blur_radius // 3)))
    pil_out = pil_blur.resize((x1 - x0, y1 - y0), Image.Resampling.BICUBIC)

    arr = np.ascontiguousarray(np.array(pil_out, dtype=np.uint8))
    qimg = QImage(
        arr.data, arr.shape[1], arr.shape[0], 3 * arr.shape[1], QImage.Format.Format_RGB888
    ).copy()
    return QPixmap.fromImage(qimg)


def compute_damped_jelly_rebound(
    progress: float,
    start_strain: float = -1.0,
    initial_velocity: float = 0.0,
    intensity_scale: float = 1.0,
) -> float:
    """
    Computes a physically inspired underdamped elastic gel rebound curve for u in [0.0, 1.0]
    (Frutiger Aqua 3.1 expressive tuning):
      1. Starts at exact `start_strain` at u=0.0 with initial derivative `initial_velocity`
         (guaranteeing C0 position and C1 velocity continuity with zero teleportation).
      2. Quick-Click Impulse Follow-Through: When a click releases early (`start_strain > -0.85`
         with downward momentum `initial_velocity < -0.15`), smoothly carries the gel capsule
         down through a full tactile compression dip (`-0.90..-0.97` around u=0.18, ~73ms)
         so brief taps remain clearly visible across multiple 30 FPS frames before rebounding.
      3. Springs upward past 0.0 to a ~38-40% primary strain overshoot (~3.4-3.6% vertical
         height overshoot at Medium intensity's 9.0% compression scale) around u=0.35..0.48.
      4. Follows with a restrained opposing secondary settle (~-7.5% to -8.5% of strain,
         or ~-0.7% vertical height) around u=0.72..0.79.
      5. Decays smoothly to exact 0.0 at u=1.0 over ~390-425ms without continuous bouncing.
    """
    u = max(0.0, min(1.0, float(progress)))
    if u <= 0.0:
        return float(start_strain)
    if u >= 1.0:
        return 0.0

    eff = max(0.35, min(1.60, float(intensity_scale)))
    s0 = float(start_strain)
    v0 = float(initial_velocity)

    # Quick-click follow-through branch: if released while still compressing before reaching
    # deep strain, complete the downward compression impulse over ~70-75ms (u_dip=0.18)
    # so quick clicks remain clearly readable at 30 FPS before springing into overshoot.
    if s0 > -0.85 and v0 < -0.15:
        target_dip = -min(0.97, max(0.90, abs(s0) + 0.76 * min(1.25, eff)))
        u_dip = 0.18
        omega = (2.68 + 0.10 * (eff - 1.0)) * math.pi
        decay = 1.16 - 0.10 * (eff - 1.0)
        if u <= u_dip:
            # Cubic Hermite segment on [0, u_dip] matching (s0, v0) at u=0 and (target_dip, 0) at u=u_dip
            t = u / u_dip
            t2 = t * t
            t3 = t2 * t
            h00 = 2.0 * t3 - 3.0 * t2 + 1.0
            h10 = t3 - 2.0 * t2 + t
            h01 = -2.0 * t3 + 3.0 * t2
            v_clamped = max(-12.5, min(-1.5, v0))
            return h00 * s0 + h10 * (u_dip * v_clamped) + h01 * target_dip
        w = (u - u_dip) / (1.0 - u_dip)
        env = ((1.0 - w) ** 1.18) * math.exp(-decay * w)
        # Zero derivative at w=0 (u=u_dip) guarantees C1 smoothness across the dip apex
        vel_c = ((decay + 1.18) * target_dip) / omega
        return env * (target_dip * math.cos(omega * w) + vel_c * math.sin(omega * w))

    omega = (2.62 + 0.12 * (eff - 1.0)) * math.pi
    decay = 1.18 - 0.12 * (eff - 1.0)
    envelope = ((1.0 - u) ** 1.18) * math.exp(-decay * u)
    vel_coeff = (v0 + (decay + 1.18) * s0) / omega
    return envelope * (s0 * math.cos(omega * u) + vel_coeff * math.sin(omega * u))


def evaluate_water_wave_displacement(
    x: float, t_sec: float, layer: int, amplitude: float
) -> float:
    """
    Evaluates organic, non-repeating multi-harmonic wave height at position `x`
    and elapsed time `t_sec` (in seconds) using incommensurate 5-12s overlapping cycles.
    Retained for backward compatibility and 1D meniscus undulation sampling.
    """
    if layer == 0:
        w1 = math.sin(x * 0.0135 + t_sec * 0.58)
        w2 = 0.45 * math.sin(x * 0.0260 - t_sec * 0.93 + 1.65)
        w3 = 0.22 * math.cos(x * 0.0085 + t_sec * 0.37 + 0.80)
        return amplitude * (w1 + w2 + w3) / 1.67
    elif layer == 1:
        w1 = math.sin(x * 0.0195 - t_sec * 0.85 + 0.90)
        w2 = 0.48 * math.cos(x * 0.0112 + t_sec * 1.18 + 2.35)
        w3 = 0.25 * math.sin(x * 0.0310 + t_sec * 0.64 - 0.55)
        return amplitude * (w1 + w2 + w3) / 1.73
    else:
        w1 = math.cos(x * 0.0225 + t_sec * 1.12 + 0.40)
        w2 = 0.52 * math.sin(x * 0.0148 - t_sec * 0.68 + 1.95)
        return amplitude * (w1 + w2) / 1.52


# Aspect-true physical coordinate ratio for Frutiger Aqua 3.3 caustics.
# The floating toolbar is ~980-1210 x 44-46 px (~21:1 to ~26:1 wide). Using an aspect-true
# physical coordinate domain [0, _AQUA3_ASPECT] x [0, 1] (dynamically adapted to actual
# widget geometry & DPI via AquaOpticalFieldRenderer.ensure_geometry) preserves the true
# physical proportions of curved refractive ribbons instead of stretching them horizontally.
_AQUA3_ASPECT: float = 19.8
_AQUA3_COLS: int = 9
_AQUA3_ROWS: int = 3


def _build_aqua3_voronoi_nuclei(aspect: float = _AQUA3_ASPECT) -> List[Tuple[float, ...]]:
    """
    Generates quasi-random staggered 2D refractive water lens nuclei across
    [0, aspect] x [0, 1.0] with incommensurate 4.5s - 15.0s orbital frequencies.
    """
    cells: List[Tuple[float, ...]] = []
    idx = 0
    for r in range(_AQUA3_ROWS):
        for c in range(_AQUA3_COLS):
            idx += 1
            jx = ((idx * 0.61803398875) % 1.0 - 0.5) * 0.42
            jy = ((idx * 0.38196601125) % 1.0 - 0.5) * 0.34
            bx = ((c + 0.5 * (r % 2) + 0.22 + jx) / float(_AQUA3_COLS)) * float(aspect)
            by = (r + 0.38 + jy) / float(_AQUA3_ROWS)
            fx1 = 0.41 + 0.35 * ((idx * 0.754877666) % 1.0)
            fy1 = 0.45 + 0.38 * ((idx * 0.569840291) % 1.0)
            fx2 = 0.66 + 0.40 * ((idx * 0.324717957) % 1.0)
            fy2 = 0.62 + 0.42 * ((idx * 0.819172513) % 1.0)
            p1 = (idx * 2.399963229) % (2.0 * math.pi)
            p2 = (idx * 3.883222077) % (2.0 * math.pi)
            p3 = (idx * 1.718281828) % (2.0 * math.pi)
            cw = 0.90 + 0.20 * ((idx * 0.414213562) % 1.0)
            cells.append((bx, by, fx1, fy1, fx2, fy2, p1, p2, p3, cw))
    return cells


_AQUA3_BASE_CELLS: List[Tuple[float, ...]] = _build_aqua3_voronoi_nuclei(_AQUA3_ASPECT)


def evaluate_aqua_water_field_2d(
    u: float, v: float, t_sec: float, aspect: float = _AQUA3_ASPECT
) -> Tuple[float, float, float, float]:
    """
    Evaluates the Frutiger Aqua 3.3 aspect-true continuous 2D refractive wave-interference
    caustic and submerged light-diffusion field at normalized capsule coordinates
    (u, v) in [0, 1]^2 and time `t_sec` (seconds).

    Shared analytically with `AquaOpticalFieldRenderer` so deep submerged turquoise/mint
    billows and refractive highlights move in exact spatial and temporal lockstep with
    the continuous caustic field.

    Returns:
      (flow_dx, flow_dy, caustic_intensity, depth_luminance)
      - flow_dx, flow_dy: 2D refractive slope / displacement vector in [-1, 1]
      - caustic_intensity: local continuous caustic ribbon concentration in [0, 1]
      - depth_luminance: local submerged turquoise/cobalt water brightness in [-1, 1]
    """
    X = float(u) * float(aspect)
    Y = float(v)
    t = float(t_sec)

    sx1 = math.sin(X * 0.74 + t * 0.41)
    cx1 = math.cos(X * 0.74 + t * 0.41)
    sy1 = math.sin(Y * 2.30 - t * 0.31)
    cy1 = math.cos(Y * 2.30 - t * 0.31)

    sx2 = math.sin(X * 1.38 - t * 0.52 + 1.3)
    cx2 = math.cos(X * 1.38 - t * 0.52 + 1.3)
    sy2 = math.sin(Y * 3.20 + t * 0.46)
    cy2 = math.cos(Y * 3.20 + t * 0.46)

    sx3 = math.sin(X * 2.12 + t * 0.63 + 2.7)
    cx3 = math.cos(X * 2.12 + t * 0.63 + 2.7)
    sy3 = math.sin(Y * 2.60 - t * 0.56)
    cy3 = math.cos(Y * 2.60 - t * 0.56)

    curl_x = (
        0.42 * (sx1 * cy1 + cx1 * sy1)
        + 0.28 * (cx2 * cy2 - sx2 * sy2)
        + 0.16 * (sx3 * sy3)
    )
    curl_y = (
        0.36 * (cx1 * cy1 - sx1 * sy1)
        + 0.24 * (sx2 * cy2 + cx2 * sy2)
        + 0.14 * (cx3 * cy3)
    )

    Xw = X + curl_x + 0.26 * (sx2 * sy1 - cx3 * cy2) + 0.15 * (cx1 * sy3)
    Yw = Y + curl_y + 0.22 * (cx2 * cy1 + sx3 * sy2) - 0.14 * (sx1 * cy3)

    sA = math.sin(Xw * 2.22 + Yw * 1.48 + t * 0.62 + 0.42 * curl_y)
    sB = math.sin(Xw * 1.52 - Yw * 1.75 - t * 0.54 + 1.6 + 0.42 * curl_x)
    sC = math.sin(-Xw * 1.92 + Yw * 1.42 + t * 0.69 + 3.1 - 0.38 * curl_y)
    sD = math.sin(Xw * 1.02 + Yw * 2.18 - t * 0.48 + 4.5 + 0.38 * curl_x)
    sE = math.sin(-Xw * 2.48 - Yw * 1.22 + t * 0.58 + 5.4 - 0.35 * curl_y)

    F1 = 0.52 * sA + 0.46 * sB + 0.38 * sD + 0.30 * (sA * sC - sB * sE) - 0.24
    F2 = 0.50 * sC + 0.45 * sE - 0.38 * sB + 0.30 * (sB * sD + sC * sA) - 0.26

    u1 = abs(F1) / 0.085
    u2 = abs(F2) / 0.090
    c1 = 1.0 / (1.0 + u1 * u1 * (1.14 + 0.44 * u1 * u1))
    c2 = 0.62 / (1.0 + u2 * u2 * (1.14 + 0.44 * u2 * u2))
    caustic = max(0.0, min(1.0, c1 + c2 + 1.8 * c1 * c2))
    depth_luma = max(-1.0, min(1.0, 0.45 * (curl_x + curl_y) + 0.35 * (F1 + F2)))
    flow_dx = max(-1.0, min(1.0, curl_x * 0.85 + 0.25 * (sA - sC)))
    flow_dy = max(-1.0, min(1.0, curl_y * 0.85 + 0.25 * (sB - sD)))
    return flow_dx, flow_dy, caustic, depth_luma


# Precompute candidate cell pairs for backward-compatible topology queries
_AQUA3_CANDIDATE_PAIRS: List[Tuple[int, int]] = [
    (i, j)
    for i in range(len(_AQUA3_BASE_CELLS))
    for j in range(i + 1, len(_AQUA3_BASE_CELLS))
    if math.hypot(
        (_AQUA3_BASE_CELLS[j][0] - _AQUA3_BASE_CELLS[i][0]) * (5.4 / _AQUA3_ASPECT),
        _AQUA3_BASE_CELLS[j][1] - _AQUA3_BASE_CELLS[i][1],
    )
    <= 2.65
]


def _eval_readability_attenuation(
    u: float,
    v: float,
    readability_zones: Optional[Sequence[Tuple[float, float, float, float, float]]],
) -> float:
    """
    Evaluates a smooth, feathered highlight attenuation factor in [0.44, 1.0] at normalized
    toolbar coordinates (u, v) in [0, 1]^2 so bright caustic intersections gently soften
    directly behind informational text labels and slider tracks without hard edges.
    """
    if not readability_zones:
        return 1.0
    max_atten = 0.0
    for u0, v0, u1, v1, strength in readability_zones:
        uc = 0.5 * (u0 + u1)
        vc = 0.5 * (v0 + v1)
        rx = max(0.018, 0.5 * (u1 - u0) + 0.016)
        ry = max(0.12, 0.5 * (v1 - v0) + 0.14)
        dx = (u - uc) / rx
        dy = (v - vc) / ry
        d2 = dx * dx + dy * dy
        if d2 < 1.85:
            w_z = math.exp(-d2 * 1.65) * float(strength)
            if w_z > max_atten:
                max_atten = w_z
    return max(0.44, 1.0 - max_atten)


def compute_voronoi_caustic_topology(
    t_sec: float,
    eff: float,
    left: float,
    top: float,
    w: float,
    h: float,
    readability_zones: Optional[Sequence[Tuple[float, float, float, float, float]]] = None,
) -> Tuple[
    List[Tuple[float, float, float, float, float, float, float, float]],
    List[Tuple[float, float, float, float]],
]:
    """
    Computes a geometrically valid, deduplicated, temporally continuous 2D Delaunay/Voronoi
    dual graph when queried directly by external callers or unit tests.

    Frutiger Aqua 3.3 Topology Fixes:
      1. Strict `i < j < k` triangle enumeration so each Delaunay triangle is evaluated
         once rather than 3 times across index permutations.
      2. Exact empty-circumcircle Delaunay validation (`min_other_d2 >= r_sq`) with a
         smooth boundary clearance fade (`del_fade`) instead of the relaxed `r_sq * 0.91`
         threshold that previously admitted non-Delaunay crossing diagonals.
      3. Strict 2-face Voronoi ridge construction (`len(v_list) == 2`) with smooth
         distance and radius fade envelopes (`pair_fade * rad_fade * del_fade`) so
         segments never pop abruptly into or out of existence.
      4. Note: `draw_frutiger_glass_Dynamic_Overlay()` no longer draws a separate vector
         node-and-wire overlay on top of the toolbar; instead, all caustic ribbons,
         branches, cores, and intersections emerge directly from the high-resolution
         continuous optical field in `AquaOpticalFieldRenderer`.
    """
    prof = resolve_aqua_intensity_profile(eff)
    if not prof.is_active or w <= 4.0 or h <= 4.0:
        return [], []
    t = float(t_sec)
    orb = prof.motion_scale
    true_aspect = max(1.2, min(26.0, (float(w) / float(h)) * 0.84))
    scale_x = true_aspect / _AQUA3_ASPECT

    n = len(_AQUA3_BASE_CELLS)
    pts_x = [0.0] * n
    pts_y = [0.0] * n
    pts_s = [0.0] * n
    for idx, (bx, by, fx1, fy1, fx2, fy2, p1, p2, p3, _cw) in enumerate(
        _AQUA3_BASE_CELLS
    ):
        px = (bx + orb * (0.34 * math.sin(t * fx1 + p1) + 0.19 * math.cos(t * fx2 - p2))) * scale_x
        py = by + orb * (0.25 * math.cos(t * fy1 + p2) + 0.15 * math.sin(t * fy2 + p3))
        pts_x[idx] = px
        pts_y[idx] = py
        pts_s[idx] = px * px + py * py

    max_d2 = (1.85 + 0.16 * max(0.0, prof.secondary_structure - 1.0)) * (scale_x * scale_x + 0.25)
    adj: List[set] = [set() for _ in range(n)]
    pair_fade_map: dict = {}
    for i in range(n):
        for j in range(i + 1, n):
            dx = pts_x[j] - pts_x[i]
            dy = (pts_y[j] - pts_y[i]) * 1.06
            d2 = dx * dx + dy * dy
            if d2 <= max_d2:
                adj[i].add(j)
                adj[j].add(i)
                pair_fade_map[(i, j)] = max(
                    0.0, min(1.0, (max_d2 - d2) / (0.32 * max_d2))
                )

    vertices: List[Tuple[float, float, float, int, int, int]] = []
    edge_to_verts: dict = {}
    max_r_sq = 0.72 * max(1.0, scale_x * 0.55)

    for i in range(n):
        ai = adj[i]
        if len(ai) < 2:
            continue
        xi, yi, si = pts_x[i], pts_y[i], pts_s[i]
        for j in sorted(x for x in ai if x > i):
            common_k = [x for x in ai.intersection(adj[j]) if x > j]
            if not common_k:
                continue
            xj, yj, sj = pts_x[j], pts_y[j], pts_s[j]
            pf_ij = pair_fade_map.get((i, j), 1.0)
            for k in sorted(common_k):
                xk, yk, sk = pts_x[k], pts_y[k], pts_s[k]
                denom = 2.0 * (xi * (yj - yk) + xj * (yk - yi) + xk * (yi - yj))
                if abs(denom) < 1e-4:
                    continue
                vx = (si * (yj - yk) + sj * (yk - yi) + sk * (yi - yj)) / denom
                vy = (si * (xk - xj) + sj * (xi - xk) + sk * (xj - xi)) / denom
                if not (-0.05 <= vx <= true_aspect + 0.05 and -0.05 <= vy <= 1.05):
                    continue
                r_sq = (vx - xi) ** 2 + (vy - yi) ** 2
                if r_sq >= max_r_sq or r_sq <= 1e-6:
                    continue

                # Exact Delaunay empty-circumcircle test + smooth boundary clearance fade
                min_other_d2 = 1e9
                is_delaunay = True
                for m_idx in range(n):
                    if m_idx in (i, j, k):
                        continue
                    d2_m = (vx - pts_x[m_idx]) ** 2 + (vy - pts_y[m_idx]) ** 2
                    if d2_m < r_sq - 1e-6:
                        is_delaunay = False
                        break
                    if d2_m < min_other_d2:
                        min_other_d2 = d2_m
                if not is_delaunay:
                    continue

                del_fade = max(0.0, min(1.0, (min_other_d2 - r_sq) / (0.18 * r_sq + 1e-5)))
                rad_fade = max(0.0, min(1.0, (max_r_sq - r_sq) / (0.30 * max_r_sq)))
                pf_tri = min(
                    pf_ij,
                    pair_fade_map.get((j, k), 1.0),
                    pair_fade_map.get((i, k), 1.0),
                )

                curl_x = math.sin(vx * 0.74 + vy * 2.30 + t * 0.41)
                curl_y = math.cos(vx * 1.38 - vy * 3.20 - t * 0.52 + 0.6)
                w_vx = max(0.02, min(true_aspect - 0.02, vx + 0.065 * curl_x))
                w_vy = max(0.08, min(0.92, vy + 0.065 * curl_y))

                u_norm = w_vx / true_aspect
                end_taper = min(1.0, min(u_norm, 1.0 - u_norm) / 0.065)
                v_Pad = min(1.0, min(w_vy, 1.0 - w_vy) / 0.14)
                v_strength = del_fade * rad_fade * pf_tri * end_taper * v_Pad
                if v_strength <= 0.02:
                    continue

                v_idx = len(vertices)
                vertices.append((w_vx, w_vy, v_strength, i, j, k))
                for e_pair in ((i, j), (j, k), (i, k)):
                    edge_to_verts.setdefault(e_pair, []).append(v_idx)

    filaments: List[Tuple[float, float, float, float, float, float, float, float]] = []
    inv_aspect = 1.0 / true_aspect
    var_scale = prof.filament_variance

    # Connect ONLY valid 2-triangle Delaunay dual edges (never arbitrary 3+ vertex lists)
    for (i, j), v_list in edge_to_verts.items():
        if len(v_list) == 2:
            v0, v1 = vertices[v_list[0]], vertices[v_list[1]]
            x0 = left + (v0[0] * inv_aspect) * w
            y0 = top + v0[1] * h
            x1 = left + (v1[0] * inv_aspect) * w
            y1 = top + v1[1] * h
            seg_len = math.hypot(x1 - x0, y1 - y0)
            max_len = min(w * 0.18, h * 3.2)
            if 4.0 <= seg_len <= max_len:
                len_fade = max(0.0, min(1.0, (max_len - seg_len) / (0.28 * max_len)))
                mx = 0.5 * (v0[0] + v1[0])
                my = 0.5 * (v0[1] + v1[1])
                u_mid = mx * inv_aspect
                read_mult = _eval_readability_attenuation(
                    u_mid, my, readability_zones
                )
                bend = 0.18 * math.sin(mx * 1.85 - my * 3.6 + t * 0.62 + (i + j))
                nx = -(y1 - y0)
                ny = x1 - x0
                cx_pt = 0.5 * (x0 + x1) + nx * bend
                cy_pt = max(top + 2.0, min(top + h - 2.0, 0.5 * (y0 + y1) + ny * bend))
                strength = min(1.0, math.sqrt(v0[2] * v1[2]) * len_fade * read_mult)
                if strength > 0.04:
                    thick = max(0.48, 0.58 + 0.55 * var_scale * strength)
                    filaments.append((x0, y0, cx_pt, cy_pt, x1, y1, strength, thick))

    glints: List[Tuple[float, float, float, float]] = []
    glint_thresh = max(0.24, 0.30 - 0.05 * max(0.0, prof.glint_specificity - 1.0))
    for vx, vy, v_str, _i, _j, _k in vertices:
        if v_str > glint_thresh:
            u_g = vx * inv_aspect
            read_mult_g = _eval_readability_attenuation(
                u_g, vy, readability_zones
            )
            gx = left + u_g * w
            gy = top + vy * h
            g_intensity = (v_str ** 1.2) * (read_mult_g ** 1.25)
            if g_intensity > 0.24:
                rad_scale = 0.46 + 0.36 * g_intensity
                glints.append((gx, gy, min(1.0, g_intensity), rad_scale))

    return filaments, glints


class AquaOpticalFieldRenderer:
    """
    Frutiger Aqua 3.3 High-Resolution Aspect-True Continuous Refractive Caustic Synthesizer.

    Replaces the former 112x22 low-resolution stretched Voronoi grid and separate vector
    node-network lines with a single, coherent, geometry- & DPI-adaptive optical model:
      - Dynamic Geometry & DPI Adaptation (`ensure_geometry`):
        Adapts working resolution (`384..544 x 30..38`, default `416 x 32` on the floating
        toolbar) and physical aspect ratio (`aspect ≈ (w / h) * 0.84`, ~19.8 on a 1040x44
        toolbar instead of 5.4) so refractive structures are never horizontally stretched.
      - Signed-Potential Euclidean Distance Caustics (`_signed_euclidean_dist`):
        Evaluates smooth signed wave-interference potentials (F1, F2, F3) across twice-refracted
        (2D rotational curl + oblique Snell wave-refraction) isotropic coordinates (Xw, Yw).
        Divides |F_m| by the analytical spatial gradient magnitude sqrt(dF/dX^2 + dF/dY^2 + g0^2)
        computed on the SIGNED field F_m BEFORE taking abs(F_m), producing organic curved
        branching ribbons with continuous width modulation, soft outer turquoise diffusion,
        delicate bright inner cores, and natural localized intersections—with zero polygonal
        Voronoi cells, zero straight connecting wires, zero blobs at wave extrema, and zero
        sub-pixel beading.
      - Fast 2D Planar Bilinear Background Refraction:
        Derives 1-3 logical pixel 2D background refraction and High-mode R/B chromatic prism
        dispersion directly from the same continuous wave-normal slopes (_gx1, _gy1, _gx2, _gy2)
        using pre-allocated float32 planar buffers (~3.6-4.5 ms per frame on CPU).
    """

    def __init__(
        self,
        grid_w: int = 416,
        grid_h: int = 32,
        aspect: float = _AQUA3_ASPECT,
    ) -> None:
        self.grid_w = max(48, int(grid_w))
        self.grid_h = max(16, int(grid_h))
        self._backdrop_source_qimg: Optional["QImage"] = None
        self._readability_zones_key: Optional[
            Tuple[Tuple[float, float, float, float, float], ...]
        ] = None
        self._backdrop_rgb_internal: Optional[np.ndarray] = None
        self._backdrop_flat: Optional[np.ndarray] = None
        self._bg_r: Optional[np.ndarray] = None
        self._bg_g: Optional[np.ndarray] = None
        self._bg_b: Optional[np.ndarray] = None
        self._init_grids(self.grid_w, self.grid_h, aspect)

    @property
    def _backdrop_rgb(self) -> Optional[np.ndarray]:
        return self._backdrop_rgb_internal

    @_backdrop_rgb.setter
    def _backdrop_rgb(self, arr: Optional[np.ndarray]) -> None:
        self._backdrop_rgb_internal = arr
        if (
            arr is not None
            and isinstance(arr, np.ndarray)
            and arr.ndim == 3
            and arr.shape[2] >= 3
        ):
            f32_arr = np.asarray(arr[..., :3], dtype=np.float32)
            self._backdrop_rgb_internal = f32_arr
            self._backdrop_flat = f32_arr.reshape((-1, 3))
            self._bg_r = np.ascontiguousarray(f32_arr[..., 0]).ravel()
            self._bg_g = np.ascontiguousarray(f32_arr[..., 1]).ravel()
            self._bg_b = np.ascontiguousarray(f32_arr[..., 2]).ravel()
        else:
            self._backdrop_flat = None
            self._bg_r = None
            self._bg_g = None
            self._bg_b = None

    def ensure_geometry(
        self, target_w: int, target_h: int, dpr: float = 1.0
    ) -> None:
        """
        Adapts the internal optical synthesis grid `(grid_w, grid_h)` and physical aspect
        ratio `self.aspect` to match the actual toolbar/panel geometry and display DPI.
        """
        tw = max(48, int(target_w))
        th = max(20, int(target_h))
        true_aspect = float(tw) / float(th)
        dpi_boost = min(1.25, max(1.0, math.sqrt(max(1.0, float(dpr)))))

        if true_aspect >= 6.0:
            # Wide floating toolbar (~980-1210 x 44-46): 384..544 wide x 30..38 high
            gw = max(384, min(544, int(round(tw * 0.40 * dpi_boost / 8.0)) * 8))
            gh = max(30, min(38, int(round(th * 0.72 * dpi_boost / 2.0)) * 2))
            phys_aspect = max(8.0, min(26.0, true_aspect * 0.84))
        else:
            # Dialogs & compact glass capsules
            gw = max(96, min(256, int(round(tw * 0.36 * dpi_boost / 8.0)) * 8))
            gh = max(24, min(64, int(round(th * 0.36 * dpi_boost / 2.0)) * 2))
            phys_aspect = max(1.2, min(8.0, true_aspect * 0.90))

        if (
            gw != self.grid_w
            or gh != self.grid_h
            or abs(float(self.aspect) - phys_aspect) > 0.35
        ):
            saved_zones = self._readability_zones_key
            saved_qimg = self._backdrop_source_qimg
            self._init_grids(gw, gh, phys_aspect)
            if saved_zones:
                self._readability_zones_key = None
                self.set_readability_zones(saved_zones)
            if saved_qimg is not None:
                self.set_backdrop_qimage(saved_qimg)

    def _init_grids(
        self, gw: int, gh: int, aspect: float = _AQUA3_ASPECT
    ) -> None:
        f32 = np.float32
        self.grid_w = max(48, int(gw))
        self.grid_h = max(16, int(gh))
        self.aspect = f32(max(1.2, float(aspect)))

        u_1d = np.linspace(0.0, 1.0, self.grid_w, dtype=f32)
        v_1d = np.linspace(0.0, 1.0, self.grid_h, dtype=f32)
        self.u_row = u_1d[None, :]
        self.v_col = v_1d[:, None]
        self.u = np.broadcast_to(self.u_row, (self.grid_h, self.grid_w)).copy()
        self.v = np.broadcast_to(self.v_col, (self.grid_h, self.grid_w)).copy()
        self.X_row = (self.u_row * self.aspect).astype(f32)
        self.Y_col = self.v_col.astype(f32)
        self.X = np.broadcast_to(self.X_row, (self.grid_h, self.grid_w)).copy()
        self.Y = np.broadcast_to(self.Y_col, (self.grid_h, self.grid_w)).copy()
        self.x_idx = np.broadcast_to(
            np.arange(self.grid_w, dtype=f32)[None, :], (self.grid_h, self.grid_w)
        ).copy()
        self.y_idx = np.broadcast_to(
            np.arange(self.grid_h, dtype=f32)[:, None], (self.grid_h, self.grid_w)
        ).copy()

        # Precompute capsule boundary meniscus, rounded-corner vignette & depth masks in float32
        dx_edge = np.minimum(self.u, f32(1.0) - self.u) * f32(2.0)
        dy_edge = np.minimum(self.v, f32(1.0) - self.v) * f32(2.0)
        edge_scale = max(3.2, float(self.aspect) * 0.52)
        edge_dist = np.minimum(dx_edge * f32(edge_scale), dy_edge)
        self.meniscus_mask = (
            np.clip(f32(1.0) - edge_dist / f32(0.28), 0.0, 1.0) ** 1.8
        ).astype(f32)
        self.meniscus_nx = (
            np.where(self.u < 0.5, 1.0, -1.0).astype(f32)
            * (np.clip(1.0 - dx_edge / 0.14, 0.0, 1.0) ** 1.6)
        ).astype(f32)
        self.meniscus_ny = (
            np.where(self.v < 0.5, 1.0, -1.0).astype(f32)
            * (np.clip(1.0 - dy_edge / 0.36, 0.0, 1.0) ** 1.6)
        ).astype(f32)
        end_cap_taper = np.clip(dx_edge / f32(0.09), 0.24, 1.0).astype(f32)
        self.interior_env = (
            np.clip(0.32 + 0.68 * np.sin(self.v * math.pi), 0.0, 1.0).astype(f32)
            * end_cap_taper
        ).astype(f32)
        self.refract_edge_taper = np.clip(
            np.minimum(dx_edge / 0.07, dy_edge / 0.16), 0.15, 1.0
        ).astype(f32)
        self.lower_depth_mask = np.clip((self.v - 0.52) / 0.48, 0.0, 1.0).astype(f32)
        self.bottom_bounce_mask = (
            np.clip((self.v - 0.70) / 0.30, 0.0, 1.0) ** 1.6
        ).astype(f32)

        # Precomputed readability protection masks
        sh = (self.grid_h, self.grid_w)
        self._readability_caustic_mult = np.ones(sh, dtype=f32)
        self._readability_depth_boost = np.zeros(sh, dtype=f32)
        self._readability_zones_key = None

        # Pre-allocated float32 scratch, wave-potential, gradient & output buffers (zero per-frame heap churn)
        self._curl_x = np.empty(sh, dtype=f32)
        self._curl_y = np.empty(sh, dtype=f32)
        self._Xw = np.empty(sh, dtype=f32)
        self._Yw = np.empty(sh, dtype=f32)
        self._sA = np.empty(sh, dtype=f32)
        self._sB = np.empty(sh, dtype=f32)
        self._sC = np.empty(sh, dtype=f32)
        self._sD = np.empty(sh, dtype=f32)
        self._sE = np.empty(sh, dtype=f32)
        self._F1 = np.empty(sh, dtype=f32)
        self._F2 = np.empty(sh, dtype=f32)
        self._F3 = np.empty(sh, dtype=f32)
        self._gx1 = np.zeros(sh, dtype=f32)
        self._gy1 = np.zeros(sh, dtype=f32)
        self._gx2 = np.zeros(sh, dtype=f32)
        self._gy2 = np.zeros(sh, dtype=f32)
        self._gx3 = np.zeros(sh, dtype=f32)
        self._gy3 = np.zeros(sh, dtype=f32)
        self._rgba_buf = np.zeros((self.grid_h, self.grid_w, 4), dtype=np.uint8)
        self._backdrop_rgb_internal = None
        self._backdrop_flat = None
        self._bg_r = None
        self._bg_g = None
        self._bg_b = None

    def set_readability_zones(
        self,
        zones: Optional[Sequence[Tuple[float, float, float, float, float]]],
    ) -> None:
        """
        Precomputes a smooth, feathered 2D caustic-highlight attenuation mask on the
        optical grid from normalized widget zones `(u0, v0, u1, v1, strength)`.
        Recomputed ONLY when toolbar layout/geometry changes (zero per-frame cost).
        """
        key = tuple(zones) if zones else ()
        if key == self._readability_zones_key:
            return
        self._readability_zones_key = key
        if not key:
            self._readability_caustic_mult.fill(1.0)
            self._readability_depth_boost.fill(0.0)
            return

        f32 = np.float32
        atten = np.zeros((self.grid_h, self.grid_w), dtype=f32)
        for u0, v0, u1, v1, strength in key:
            uc = f32(0.5 * (u0 + u1))
            vc = f32(0.5 * (v0 + v1))
            rx = f32(max(0.018, 0.5 * (u1 - u0) + 0.016))
            ry = f32(max(0.12, 0.5 * (v1 - v0) + 0.14))
            dx = (self.u - uc) / rx
            dy = (self.v - vc) / ry
            d2 = dx * dx + dy * dy
            zone_w = np.exp(-d2 * f32(1.65)).astype(f32) * f32(strength)
            np.maximum(atten, zone_w, out=atten)

        np.clip(f32(1.0) - atten, f32(0.44), f32(1.0), out=self._readability_caustic_mult)
        np.clip(atten * f32(0.52), f32(0.0), f32(0.32), out=self._readability_depth_boost)

    def clear_backdrop(self) -> None:
        """Releases cached backdrop float32 arrays when the toolbar/overlay closes."""
        self._backdrop_source_qimg = None
        self._backdrop_rgb = None

    def set_backdrop_qimage(self, qimg: Optional["QImage"]) -> None:
        """Caches planar float32 RGB channels of the static backdrop for real-time 2D refraction."""
        if qimg is None or qimg.isNull():
            self._backdrop_source_qimg = None
            self._backdrop_rgb = None
            return
        self._backdrop_source_qimg = qimg
        scaled = qimg.scaled(
            self.grid_w,
            self.grid_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).convertToFormat(QImage.Format.Format_RGB888)
        ptr = scaled.bits()
        ptr.setsize(scaled.height() * scaled.bytesPerLine())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
            (scaled.height(), scaled.bytesPerLine())
        )[:, : self.grid_w * 3]
        self._backdrop_rgb = arr.reshape((self.grid_h, self.grid_w, 3)).astype(
            np.float32
        )

    def _signed_euclidean_dist(
        self, F: np.ndarray, gx: np.ndarray, gy: np.ndarray, g_floor_sq: float
    ) -> np.ndarray:
        """
        Computes physical Euclidean distance `|F| / sqrt((dF/dX)^2 + (dF/dY)^2 + g_floor_sq)`
        using central differences on the smooth SIGNED wave potential `F` BEFORE taking `abs(F)`.
        Eliminates both wave-peak blob expansion and V-fold derivative dark-ring artifacts.
        """
        f32 = np.float32
        inv_2dx = f32(0.5 * float(self.grid_w) / float(self.aspect))
        inv_2dy = f32(0.5 * float(self.grid_h))

        gx[:, 1:-1] = (F[:, 2:] - F[:, :-2]) * inv_2dx
        gx[:, 0] = (F[:, 1] - F[:, 0]) * (inv_2dx * f32(2.0))
        gx[:, -1] = (F[:, -1] - F[:, -2]) * (inv_2dx * f32(2.0))

        gy[1:-1, :] = (F[2:, :] - F[:-2, :]) * inv_2dy
        gy[0, :] = (F[1, :] - F[0, :]) * (inv_2dy * f32(2.0))
        gy[-1, :] = (F[-1, :] - F[-2, :]) * (inv_2dy * f32(2.0))

        grad_mag = np.sqrt(gx * gx + gy * gy + f32(g_floor_sq))
        return np.abs(F) / grad_mag

    def synthesize_rgba_field(
        self,
        t_sec: float,
        intensity_scale: float,
        opacity_factor: float,
        disturbances: Optional[Sequence["ToolbarWaterDisturbance"]] = None,
    ) -> np.ndarray:
        """
        Computes a single frame of the Frutiger Aqua 3.3 continuous refractive water volume:
          - Evaluates smooth 2D rotational curl + oblique Snell wave-refraction on isotropic
            aspect-true coordinates `(Xw, Yw)`.
          - Computes signed wave-interference potentials `F1, F2` (plus tertiary capillary
            potential `F3` in High) and normalizes by their analytical spatial gradients so
            caustic ribbons maintain delicate, organically varying widths (~1.7-3.4 px)
            with soft outer turquoise diffusion, subtle bright cores, and natural localized
            intersections where ribbons cross.
          - Uses fast 2D planar bilinear lookup on `_bg_r, _bg_g, _bg_b` for real-time
            1-3 px background refraction and High-mode R/B chromatic prism dispersion.
        """
        prof = resolve_aqua_intensity_profile(intensity_scale)
        if not prof.is_active:
            self._rgba_buf.fill(0)
            return self._rgba_buf

        f32 = np.float32
        motion = f32(prof.motion_scale)
        h_gain = f32(prof.highlight_gain)
        shoulder = f32(prof.highlight_shoulder)
        sec_struct = f32(prof.secondary_structure)
        var_scale = f32(prof.filament_variance)
        depth_sep = f32(prof.depth_separation)
        op = f32(max(0.22, min(1.35, float(opacity_factor))))
        t = f32(t_sec) * motion

        X_r = self.X_row
        Y_c = self.Y_col
        curl_x = self._curl_x
        curl_y = self._curl_y
        Xw = self._Xw
        Yw = self._Yw

        # 1. Smooth 2D rotational curl advection (evaluated on 1D row/col vectors first)
        sx1 = np.sin(X_r * f32(0.74) + t * f32(0.41))
        cx1 = np.cos(X_r * f32(0.74) + t * f32(0.41))
        sy1 = np.sin(Y_c * f32(2.30) - t * f32(0.31))
        cy1 = np.cos(Y_c * f32(2.30) - t * f32(0.31))

        sx2 = np.sin(X_r * f32(1.38) - t * f32(0.52) + f32(1.3))
        cx2 = np.cos(X_r * f32(1.38) - t * f32(0.52) + f32(1.3))
        sy2 = np.sin(Y_c * f32(3.20) + t * f32(0.46))
        cy2 = np.cos(Y_c * f32(3.20) + t * f32(0.46))

        sx3 = np.sin(X_r * f32(2.12) + t * f32(0.63) + f32(2.7))
        cx3 = np.cos(X_r * f32(2.12) + t * f32(0.63) + f32(2.7))
        sy3 = np.sin(Y_c * f32(2.60) - t * f32(0.56))
        cy3 = np.cos(Y_c * f32(2.60) - t * f32(0.56))

        curl_x[:] = (
            f32(0.42) * (sx1 * cy1 + cx1 * sy1)
            + f32(0.28) * (cx2 * cy2 - sx2 * sy2)
            + f32(0.16) * (sx3 * sy3)
        )
        curl_y[:] = (
            f32(0.36) * (cx1 * cy1 - sx1 * sy1)
            + f32(0.24) * (sx2 * cy2 + cx2 * sy2)
            + f32(0.14) * (cx3 * cy3)
        )

        # Optional localized toolbar water disturbance from nearby button/slider clicks
        disturb_caustic_boost = None
        if disturbances:
            eff_d = min(1.35, max(0.45, float(intensity_scale)))
            t_float = float(t_sec)
            u_row = self.u_row
            v_col = self.v_col
            for d_item in disturbances:
                age = t_float - d_item.start_sec
                if 0.0 <= age < d_item.duration_sec:
                    p_d = age / max(0.05, d_item.duration_sec)
                    env_d = f32(
                        math.sin(math.pi * (p_d ** 0.65))
                        * ((1.0 - p_d) ** 0.75)
                        * d_item.strength
                        * eff_d
                    )
                    if env_d > 1e-3:
                        du = (u_row - f32(d_item.u_center)) * f32(2.85)
                        dv = (v_col - f32(d_item.v_center)) * f32(0.85)
                        dist_sq_d = du * du + dv * dv
                        loc_mask = np.exp(-dist_sq_d * f32(23.8)).astype(f32)
                        dist_r = np.sqrt(dist_sq_d + f32(1e-5))
                        wave_ring = (
                            np.sin(dist_r * f32(26.0) - f32(p_d * 10.5))
                            * loc_mask
                            * env_d
                        )
                        inv_r = f32(0.85) / (dist_r + f32(0.08))
                        curl_x += (du * inv_r) * wave_ring
                        curl_y += (dv * inv_r) * wave_ring
                        ring_glow = (
                            np.maximum(f32(0.0), wave_ring) * f32(0.85)
                            + loc_mask * (env_d * f32(0.22))
                        )
                        if disturb_caustic_boost is None:
                            disturb_caustic_boost = ring_glow
                        else:
                            disturb_caustic_boost = disturb_caustic_boost + ring_glow

        # 2. Second-pass oblique Snell wave-refraction displacement
        Xw[:] = (
            self.X
            + curl_x
            + f32(0.26) * (sx2 * sy1 - cx3 * cy2)
            + f32(0.15) * (cx1 * sy3)
        )
        Yw[:] = (
            self.Y
            + curl_y
            + f32(0.22) * (cx2 * cy1 + sx3 * sy2)
            - f32(0.14) * (sx1 * cy3)
        )

        # 3. 5 Oblique Refracted Wave Harmonics in Isotropic Space
        sA = self._sA
        sB = self._sB
        sC = self._sC
        sD = self._sD
        sE = self._sE
        np.sin(
            Xw * f32(2.22) + Yw * f32(1.48) + t * f32(0.62) + f32(0.42) * curl_y,
            out=sA,
        )
        np.sin(
            Xw * f32(1.52) - Yw * f32(1.75) - t * f32(0.54) + f32(1.6) + f32(0.42) * curl_x,
            out=sB,
        )
        np.sin(
            -Xw * f32(1.92) + Yw * f32(1.42) + t * f32(0.69) + f32(3.1) - f32(0.38) * curl_y,
            out=sC,
        )
        np.sin(
            Xw * f32(1.02) + Yw * f32(2.18) - t * f32(0.48) + f32(4.5) + f32(0.38) * curl_x,
            out=sD,
        )
        np.sin(
            -Xw * f32(2.48) - Yw * f32(1.22) + t * f32(0.58) + f32(5.4) - f32(0.35) * curl_y,
            out=sE,
        )

        F1 = self._F1
        F2 = self._F2
        F1[:] = (
            f32(0.52) * sA
            + f32(0.46) * sB
            + f32(0.38) * sD
            + f32(0.30) * (sA * sC - sB * sE)
            - f32(0.24)
        )
        F2[:] = (
            f32(0.50) * sC
            + f32(0.45) * sE
            - f32(0.38) * sB
            + f32(0.30) * (sB * sD + sC * sA)
            - f32(0.26)
        )

        # 4. Signed-Potential Euclidean Distance Estimation
        d1_phys = self._signed_euclidean_dist(
            F1, self._gx1, self._gy1, g_floor_sq=0.62
        )
        d2_phys = self._signed_euclidean_dist(
            F2, self._gx2, self._gy2, g_floor_sq=0.62
        )

        env1 = np.clip(
            f32(0.58) + f32(0.46) * sD + f32(0.28) * (sx1 * cy2 - cx2 * sy1),
            f32(0.12),
            f32(1.14),
        )
        env2 = np.clip(
            f32(0.54) + f32(0.46) * sA - f32(0.28) * (cx1 * sy2 + sx2 * cy1),
            f32(0.10),
            f32(1.10),
        )

        width_mod = np.clip(
            f32(0.74) + f32(0.36) * (sx1 * sy2 + cx2 * cy3),
            f32(0.46),
            f32(1.24),
        )
        w1 = f32(0.038) + f32(0.030 * float(var_scale)) * width_mod * np.clip(
            f32(1.26) - env1 * f32(0.48), f32(0.44), f32(1.12)
        )
        w2 = f32(0.041) + f32(0.030 * float(var_scale)) * (
            f32(1.50) - width_mod
        ) * np.clip(f32(1.24) - env2 * f32(0.45), f32(0.44), f32(1.12))

        u1 = d1_phys / w1
        u1_sq = np.minimum(u1 * u1, f32(36.0))
        u2 = d2_phys / w2
        u2_sq = np.minimum(u2 * u2, f32(36.0))

        caustic_halo = (
            (env1 * f32(0.34)) / (f32(1.0) + f32(0.28) * u1_sq)
            + (env2 * f32(0.28)) / (f32(1.0) + f32(0.28) * u2_sq)
        )
        caustic_main = (env1 * env1) / (
            f32(1.0) + u1_sq * (f32(1.14) + f32(0.44) * u1_sq)
        )
        branch_gain = f32(0.62 * min(1.48, float(sec_struct)))
        caustic_branch = (branch_gain * env2 * env2) / (
            f32(1.0) + u2_sq * (f32(1.14) + f32(0.44) * u2_sq)
        )

        # High-intensity tertiary capillary caustic branches
        if prof.secondary_structure > 1.12:
            F3 = self._F3
            F3[:] = (
                f32(0.48) * sD
                - f32(0.46) * sA
                + f32(0.42) * sE
                + f32(0.28) * (sC * sD - sA * sB)
                - f32(0.22)
            )
            d3_phys = self._signed_euclidean_dist(
                F3, self._gx3, self._gy3, g_floor_sq=0.68
            )
            w3 = f32(0.035) + f32(0.024) * width_mod
            u3 = d3_phys / w3
            u3_sq = np.minimum(u3 * u3, f32(36.0))
            sub_scale = f32(min(0.48, (prof.secondary_structure - 1.0) * 0.62))
            env3 = np.clip(f32(0.55) + f32(0.42) * sB, f32(0.18), f32(1.05))
            caustic_branch = caustic_branch + (
                (sub_scale * env3 * env3)
                / (f32(1.0) + u3_sq * (f32(1.16) + f32(0.46) * u3_sq))
            )

        read_mult = self._readability_caustic_mult
        caustic_cores = (
            caustic_main * caustic_main * f32(0.72)
            + caustic_branch * caustic_branch * f32(0.48)
            + caustic_main * caustic_branch * f32(2.45)
        ) * self.interior_env
        caustic_web = (
            caustic_halo + (caustic_main + caustic_branch) * f32(0.86)
        ) * self.interior_env

        if disturb_caustic_boost is not None:
            caustic_web = caustic_web + disturb_caustic_boost * f32(0.34)
            caustic_cores = caustic_cores + disturb_caustic_boost * f32(0.28)

        caustic_web = caustic_web * read_mult
        caustic_cores = caustic_cores * (read_mult * read_mult)

        raw_caustic = caustic_web + caustic_cores
        caustic_total = np.clip(
            raw_caustic / (f32(1.0) + shoulder * raw_caustic), f32(0.0), f32(1.28)
        )

        # Gentle deep-basin optical contrast only in the open water far from ribbons (u_min_sq > 2.8)
        u_min_sq = np.minimum(u1_sq, u2_sq)
        basin_depth = np.clip(
            f32(0.52) - f32(0.26) * (F1 + F2), f32(0.0), f32(1.0)
        )
        basin_dark = (
            np.clip(
                (u_min_sq - f32(2.8)) / (f32(7.0) + u_min_sq), f32(0.0), f32(0.34)
            )
            * basin_depth
            * self.interior_env
            * f32(0.85 + 0.30 * float(depth_sep - 1.0))
        )

        # 5. Fast 2D Planar Bilinear Background Refraction & Water Volume Synthesis
        out = self._rgba_buf
        if (
            self._bg_r is not None
            and self._bg_g is not None
            and self._bg_b is not None
            and self._backdrop_rgb_internal is not None
            and self._backdrop_rgb_internal.shape[0] == self.grid_h
            and self._backdrop_rgb_internal.shape[1] == self.grid_w
        ):
            refract_scale = f32(prof.refraction_scale) * self.refract_edge_taper
            ridge_lens = (
                f32(0.48) + f32(1.18) * caustic_main + f32(0.42) * caustic_branch
            )
            norm_gx = (self._gx1 + f32(0.65) * self._gx2) * f32(0.22)
            norm_gy = (self._gy1 + f32(0.65) * self._gy2) * f32(0.22)
            dx_grid = (
                norm_gx * ridge_lens + curl_x * f32(0.30)
            ) * refract_scale + self.meniscus_nx * f32(0.55)
            dy_grid = (
                norm_gy * f32(1.18) * ridge_lens + curl_y * f32(0.35)
            ) * refract_scale + self.meniscus_ny * f32(0.75)

            gw = self.grid_w
            sx = np.clip(self.x_idx + dx_grid, f32(0.0), f32(gw - 1.001))
            sy = np.clip(self.y_idx + dy_grid, f32(0.0), f32(self.grid_h - 1.001))

            x0 = sx.astype(np.int32)
            y0 = sy.astype(np.int32)
            fx = sx - x0
            fy = sy - y0
            om_fx = f32(1.0) - fx
            om_fy = f32(1.0) - fy

            w00 = om_fx * om_fy
            w01 = fx * om_fy
            w10 = om_fx * fy
            w11 = fx * fy

            idx00 = y0 * gw + x0
            idx01 = idx00 + 1
            idx10 = idx00 + gw
            idx11 = idx10 + 1

            bg_r = self._bg_r
            bg_g = self._bg_g
            bg_b = self._bg_b
            ref_r = (
                bg_r[idx00] * w00
                + bg_r[idx01] * w01
                + bg_r[idx10] * w10
                + bg_r[idx11] * w11
            )
            ref_g = (
                bg_g[idx00] * w00
                + bg_g[idx01] * w01
                + bg_g[idx10] * w10
                + bg_g[idx11] * w11
            )

            # Subtle chromatic prism dispersion along steep caustic lenses in High intensity
            if prof.chromatic_refraction > 0.12:
                chr_shift = (
                    norm_gx
                    * (caustic_main + f32(0.5) * caustic_branch)
                    * f32(prof.chromatic_refraction)
                    * self.refract_edge_taper
                )
                sx_b = np.clip(sx + chr_shift, f32(0.0), f32(gw - 1.001))
                xb0 = sx_b.astype(np.int32)
                fxb = sx_b - xb0
                om_fxb = f32(1.0) - fxb
                idx_b00 = y0 * gw + xb0
                idx_b01 = idx_b00 + 1
                ref_b = (
                    bg_b[idx_b00] * (om_fxb * om_fy)
                    + bg_b[idx_b01] * (fxb * om_fy)
                    + bg_b[idx_b00 + gw] * (om_fxb * fy)
                    + bg_b[idx_b01 + gw] * (fxb * fy)
                )
            else:
                ref_b = (
                    bg_b[idx00] * w00
                    + bg_b[idx01] * w01
                    + bg_b[idx10] * w10
                    + bg_b[idx11] * w11
                )

            flow_luma = (
                f32(0.48)
                + f32(0.18) * (curl_x + curl_y)
                - f32(0.25 * float(depth_sep)) * basin_depth
                - f32(0.35) * basin_dark
            )
            depth_absorb = (
                basin_depth * self.lower_depth_mask * depth_sep
                + self._readability_depth_boost
            )
            water_r = f32(8.0) + f32(22.0) * flow_luma
            water_g = (
                f32(82.0)
                + f32(86.0) * flow_luma
                - f32(36.0) * depth_absorb
                - f32(24.0) * basin_dark
            )
            water_b = (
                f32(152.0)
                + f32(64.0) * flow_luma
                - f32(22.0) * depth_absorb
                - f32(16.0) * basin_dark
            )

            tint_mix = np.clip(
                (
                    f32(0.22)
                    + f32(0.16) * basin_depth * f32(min(1.25, float(depth_sep)))
                    + f32(0.13) * self.lower_depth_mask
                    + self._readability_depth_boost * f32(0.32)
                )
                * (op * f32(1.10)),
                f32(0.08),
                f32(0.76),
            )
            inv_tint = f32(1.0) - tint_mix

            comp_r = ref_r * inv_tint + water_r * tint_mix
            comp_g = ref_g * inv_tint + water_g * tint_mix
            comp_b = ref_b * inv_tint + water_b * tint_mix

            # Subtle deep-aqua optical cushion inside readability zones preserves text contrast
            read_cush = self._readability_depth_boost * f32(0.55)
            inv_cush = f32(1.0) - read_cush
            comp_r = comp_r * inv_cush + f32(6.0) * read_cush
            comp_g = comp_g * inv_cush + f32(84.0) * read_cush
            comp_b = comp_b * inv_cush + f32(142.0) * read_cush

            comp_luma = (
                f32(0.2126) * comp_r + f32(0.7152) * comp_g + f32(0.0722) * comp_b
            )
            headroom_mult = (
                np.clip((f32(248.0) - comp_luma) / f32(96.0), f32(0.30), f32(1.0))
                * read_mult
            )

            c_boost = (
                caustic_total * (h_gain * (f32(84.0) + f32(30.0) * op)) * headroom_mult
                + self.meniscus_mask * (f32(18.0) + f32(14.0) * h_gain) * read_mult
            )
            c_white = (
                np.clip(caustic_cores * h_gain, f32(0.0), f32(1.20))
                * f32(88.0)
                * headroom_mult
            )
            b_glow = (
                self.bottom_bounce_mask
                * (f32(22.0) * h_gain)
                * read_mult
            )

            out[..., 0] = np.clip(
                comp_r + c_boost * f32(0.54) + c_white * f32(0.92),
                f32(0.0),
                f32(255.0),
            ).astype(np.uint8)
            out[..., 1] = np.clip(
                comp_g + c_boost * f32(1.06) + c_white * f32(0.98) + b_glow,
                f32(0.0),
                f32(255.0),
            ).astype(np.uint8)
            out[..., 2] = np.clip(
                comp_b + c_boost * f32(1.14) + c_white + b_glow * f32(0.80),
                f32(0.0),
                f32(255.0),
            ).astype(np.uint8)
            out[..., 3] = 255
            return out

        # Standalone translucent RGBA water overlay when no backdrop QImage is set (e.g. SettingsDialog)
        c_strength = np.clip(caustic_total * h_gain, f32(0.0), f32(1.30))
        glint_s = np.clip(caustic_cores * h_gain, f32(0.0), f32(1.20))
        flow_mod = np.clip(
            f32(0.48)
            + f32(0.18) * (curl_x + curl_y)
            - f32(0.24 * float(depth_sep)) * basin_depth
            - f32(0.32) * basin_dark,
            f32(0.0),
            f32(1.0),
        )

        out[..., 0] = np.clip(
            f32(8.0)
            + f32(34.0) * flow_mod
            + f32(120.0) * c_strength
            + f32(78.0) * glint_s
            + f32(30.0) * self.meniscus_mask,
            f32(0.0),
            f32(255.0),
        ).astype(np.uint8)
        out[..., 1] = np.clip(
            f32(96.0)
            + f32(58.0) * flow_mod
            + f32(78.0) * c_strength
            + f32(48.0) * glint_s
            + f32(22.0) * self.bottom_bounce_mask
            - f32(36.0) * basin_depth * self.lower_depth_mask * depth_sep,
            f32(0.0),
            f32(255.0),
        ).astype(np.uint8)
        out[..., 2] = np.clip(
            f32(160.0)
            + f32(40.0) * flow_mod
            + f32(48.0) * c_strength
            + f32(34.0) * glint_s
            + f32(16.0) * self.meniscus_mask
            - f32(22.0) * basin_depth * self.lower_depth_mask * depth_sep,
            f32(0.0),
            f32(255.0),
        ).astype(np.uint8)
        out[..., 3] = np.clip(
            (
                f32(16.0) * flow_mod
                + f32(94.0) * c_strength
                + f32(44.0) * glint_s
                + f32(18.0) * self.lower_depth_mask * depth_sep
                + f32(24.0) * self.meniscus_mask
                + f32(20.0) * self.bottom_bounce_mask
            )
            * f32(max(0.45, min(1.22, float(op) * 1.10)) * max(0.42, float(h_gain) * 0.84)),
            f32(0.0),
            f32(208.0),
        ).astype(np.uint8)
        return out


@dataclass
class WaterRippleState:
    """Lightweight localized pressure-wave state inside an AeroGelButton or AeroLiquidSlider."""
    origin_x: float
    origin_y: float
    start_sec: float
    duration_sec: float = 0.48
    strength: float = 1.0
    norm_x: float = 0.0
    norm_y: float = 0.0


@dataclass
class ToolbarWaterDisturbance:
    """
    Spatially localized water disturbance in AeroGlassToolbar triggered when an adjacent
    gel button or liquid slider is pressed/clicked. Much weaker than the button's internal
    ripple so the surrounding toolbar water responds organically without global waves.
    """
    u_center: float
    v_center: float
    center_x: float
    center_y: float
    start_sec: float
    duration_sec: float = 0.62
    strength: float = 0.35


if HAS_QT:

    def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
        """Smoothly interpolates two QColors in RGBA space."""
        u = max(0.0, min(1.0, float(t)))
        inv = 1.0 - u
        return QColor(
            int(round(c1.red() * inv + c2.red() * u)),
            int(round(c1.green() * inv + c2.green() * u)),
            int(round(c1.blue() * inv + c2.blue() * u)),
            int(round(c1.alpha() * inv + c2.alpha() * u)),
        )

    class AeroAnimationDirector(QObject):
        """
        Shared frame-independent animation clock (~30 FPS) for living water inside
        the Frutiger Aero glass toolbar and Settings window.
        Automatically pauses when no animated surfaces are visible or when intensity is 'off',
        guaranteeing zero CPU usage while HDRSnip Fusion is idle in the system tray.
        """

        _instance: Optional["AeroAnimationDirector"] = None

        @classmethod
        def instance(cls) -> "AeroAnimationDirector":
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

        def __init__(self) -> None:
            super().__init__()
            self._elapsed = QElapsedTimer()
            self._elapsed.start()
            self._intensity: str = "medium"
            self._scale: float = 1.00
            self._safe_mode: bool = bool(ENV_SAFE_MODE)
            self._disable_continuous: bool = False
            self._transparency: int = 72  # 10..95% transparent (default 72% crystal-clear)
            self._surfaces: List[weakref.ReferenceType] = []

            self._timer = QTimer(self)
            self._timer.setInterval(33)  # ~30.3 FPS target for continuous water movement
            self._timer.timeout.connect(self._on_tick)

        @property
        def safe_mode(self) -> bool:
            return self._safe_mode

        @property
        def disable_continuous(self) -> bool:
            return self._disable_continuous

        @property
        def intensity(self) -> str:
            if self._safe_mode or self._disable_continuous:
                return "off"
            return self._intensity

        @property
        def scale(self) -> float:
            if self._safe_mode or self._disable_continuous:
                return 0.0
            return self._scale

        @property
        def interactive_scale(self) -> float:
            """Scale for short interactive button/slider effects (0.0 in Safe Mode or when intensity is 'off')."""
            if self._safe_mode:
                return 0.0
            return self._scale

        def apply_config_flags(self, config: AppConfig) -> None:
            """Synchronizes Diagnostic Safe Mode, continuous animation isolation, intensity, and transparency."""
            self._safe_mode = bool(config.is_safe_mode_active)
            self._disable_continuous = bool(config.disable_continuous_animations)
            norm = str(config.animation_intensity).strip().lower()
            if norm not in ANIMATION_INTENSITY_LEVELS:
                norm = "medium"
            self._intensity = norm
            self._scale = get_animation_intensity_scale(norm)
            self._transparency = max(10, min(95, int(config.glass_transparency)))
            self._sync_timer()
            for ref in list(self._surfaces):
                w = ref()
                if w is not None:
                    if self.scale <= 0.0 and hasattr(w, "on_animations_disabled"):
                        w.on_animations_disabled()
                    if hasattr(w, "on_transparency_changed"):
                        w.on_transparency_changed()
                    elif w.isVisible():
                        w.update()

        @property
        def transparency(self) -> int:
            return self._transparency

        @property
        def opacity_factor(self) -> float:
            """
            Maps transparency (10%..95%) to an opacity multiplier (1.45 down to 0.12).
            At the default 72% transparency, opacity_factor is ~0.42 (over 2.3x more
            see-through than before so desktop/game details shine clearly through).
            """
            t = max(10, min(95, self._transparency)) / 100.0
            return max(0.10, pow(1.0 - t, 0.82) * 1.55)

        def set_transparency(self, transparency_pct: int) -> None:
            clamped = max(10, min(95, int(transparency_pct)))
            if self._transparency == clamped:
                return
            self._transparency = clamped
            for ref in list(self._surfaces):
                w = ref()
                if w is not None:
                    if hasattr(w, "on_transparency_changed"):
                        w.on_transparency_changed()
                    elif w.isVisible():
                        w.update()

        def elapsed_seconds(self) -> float:
            if self._elapsed.isValid():
                return self._elapsed.nsecsElapsed() * 1e-9
            return time.perf_counter()

        def is_timer_active(self) -> bool:
            return self._timer.isActive()

        def count_active_timers(self) -> int:
            """Returns the exact number of active QTimers and QVariantAnimations across registered UI surfaces."""
            count = 1 if self._timer.isActive() else 0
            for ref in list(self._surfaces):
                w = ref()
                if w is not None and w.isVisible():
                    for child in w.findChildren(QWidget):
                        for attr in (
                            "_hover_anim",
                            "_jelly_anim",
                            "_energy_anim",
                            "_thumb_anim",
                        ):
                            anim = getattr(child, attr, None)
                            if (
                                anim is not None
                                and anim.state()
                                == QVariantAnimation.State.Running
                            ):
                                count += 1
                        rt = getattr(child, "_ripple_timer", None)
                        if rt is not None and rt.isActive():
                            count += 1
            return count

        def set_intensity(self, level: str) -> None:
            norm = str(level).strip().lower()
            if norm not in ANIMATION_INTENSITY_LEVELS:
                norm = "medium"
            self._intensity = norm
            self._scale = get_animation_intensity_scale(norm)
            self._sync_timer()
            for ref in list(self._surfaces):
                w = ref()
                if w is not None:
                    if hasattr(w, "_water_dirty"):
                        w._water_dirty = True
                    if self.scale <= 0.0 and hasattr(w, "on_animations_disabled"):
                        w.on_animations_disabled()
                    if w.isVisible():
                        if hasattr(w, "on_animation_tick"):
                            w.on_animation_tick()
                        else:
                            w.update()

        def register_surface(self, widget: QWidget) -> None:
            for ref in list(self._surfaces):
                w = ref()
                if w is widget:
                    self._sync_timer()
                    return
            self._surfaces.append(weakref.ref(widget))
            self._sync_timer()

        def unregister_surface(self, widget: QWidget) -> None:
            self._surfaces = [
                ref for ref in self._surfaces if ref() is not None and ref() is not widget
            ]
            self._sync_timer()

        def notify_visibility_changed(self) -> None:
            self._sync_timer()

        def stop_all(self) -> None:
            self._timer.stop()
            for ref in list(self._surfaces):
                w = ref()
                if w is not None and hasattr(w, "on_animations_disabled"):
                    w.on_animations_disabled()

        def _sync_timer(self) -> None:
            if self.scale <= 0.0:
                if self._timer.isActive():
                    self._timer.stop()
                    DIAG_LOG.log_animation_state(
                        f"Stopped shared animation timer (scale=0.0, safe_mode={self._safe_mode}, "
                        f"disable_continuous={self._disable_continuous})"
                    )
                return

            has_visible = False
            alive: List[weakref.ReferenceType] = []
            for ref in self._surfaces:
                w = ref()
                if w is not None:
                    alive.append(ref)
                    if w.isVisible():
                        has_visible = True
            self._surfaces = alive

            if has_visible:
                if not self._timer.isActive():
                    self._timer.start()
                    DIAG_LOG.log_animation_state(
                        f"Started shared 30 FPS animation timer (intensity={self._intensity}, "
                        f"surfaces={len(self._surfaces)})"
                    )
            else:
                if self._timer.isActive():
                    self._timer.stop()
                    DIAG_LOG.log_animation_state(
                        "Paused shared animation timer (no visible surfaces; idle in tray)"
                    )

        def _on_tick(self) -> None:
            if self.scale <= 0.0:
                self._timer.stop()
                return

            PERF_TELEMETRY.record_director_tick(self.elapsed_seconds())
            any_visible = False
            alive: List[weakref.ReferenceType] = []
            for ref in self._surfaces:
                w = ref()
                if w is not None:
                    alive.append(ref)
                    if w.isVisible():
                        any_visible = True
                        if hasattr(w, "on_animation_tick"):
                            w.on_animation_tick()
                        else:
                            w.update()
            self._surfaces = alive
            if not any_visible:
                self._timer.stop()


    def draw_frutiger_glass_base(
        painter: QPainter,
        rect: QRectF,
        radius: float = 16.0,
        frosted_pixmap: Optional[QPixmap] = None,
        tint_style: str = "aqua",
        clear_pixmap: Optional[QPixmap] = None,
    ) -> None:
        """
        Renders the static base layers of a Frutiger Aero / Aqua glass panel
        (drop shadow, refractive screen backdrop, translucent aqua/emerald tint, and base bokeh).
        Automatically scales tint opacity and frost blend from AeroAnimationDirector.opacity_factor.
        """
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        director = AeroAnimationDirector.instance()
        op = director.opacity_factor  # ~0.42 at default 72% transparency
        trans_norm = max(0.0, min(1.0, (director.transparency - 10) / 85.0))

        panel_path = QPainterPath()
        panel_path.addRoundedRect(rect, radius, radius)

        # Soft outer drop shadow glow (scales gently with glass opacity)
        sh_scale = max(0.35, min(1.0, op * 1.15))
        for i in range(3, 0, -1):
            sh_rect = rect.adjusted(-i * 1.5, -i * 1.0, i * 1.5, i * 2.0)
            sh_path = QPainterPath()
            sh_path.addRoundedRect(sh_rect, radius + i, radius + i)
            painter.fillPath(
                sh_path, QColor(0, 35, 75, int(round(22 * (4 - i) * sh_scale)))
            )

        painter.setClipPath(panel_path)

        # 1. Refractive backdrop: blend clear screen pixels with frosted blur based on transparency
        target_r = rect.toRect()
        if clear_pixmap is not None and not clear_pixmap.isNull():
            painter.drawPixmap(target_r, clear_pixmap)
            if frosted_pixmap is not None and not frosted_pixmap.isNull():
                frost_opacity = max(0.12, min(0.92, 0.85 - 0.58 * trans_norm))
                painter.save()
                painter.setOpacity(frost_opacity)
                painter.drawPixmap(target_r, frosted_pixmap)
                painter.restore()
        elif frosted_pixmap is not None and not frosted_pixmap.isNull():
            painter.save()
            painter.setOpacity(max(0.20, min(1.0, 0.92 - 0.50 * trans_norm)))
            painter.drawPixmap(target_r, frosted_pixmap)
            painter.restore()

        # 2. Translucent Frutiger Aqua / Aurora glass tint (scaled by opacity_factor)
        bg_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if tint_style == "dialog":
            a0 = max(18, min(225, int(round(145 * op))))
            a1 = max(20, min(230, int(round(152 * op))))
            a2 = max(22, min(235, int(round(158 * op))))
            a3 = max(18, min(225, int(round(145 * op))))
            bg_grad.setColorAt(0.0, QColor(16, 132, 205, a0))
            bg_grad.setColorAt(0.50, QColor(12, 102, 175, a1))
            bg_grad.setColorAt(0.85, QColor(14, 135, 190, a2))
            bg_grad.setColorAt(1.0, QColor(35, 205, 170, a3))
        else:
            a0 = max(12, min(210, int(round(115 * op))))
            a1 = max(16, min(220, int(round(132 * op))))
            a2 = max(14, min(215, int(round(122 * op))))
            a3 = max(12, min(210, int(round(115 * op))))
            bg_grad.setColorAt(0.0, QColor(20, 145, 215, a0))
            bg_grad.setColorAt(0.50, QColor(8, 72, 135, a1))
            bg_grad.setColorAt(0.85, QColor(14, 160, 215, a2))
            bg_grad.setColorAt(1.0, QColor(45, 220, 180, a3))
        painter.fillPath(panel_path, QBrush(bg_grad))

        # 3. Static base Frutiger Aero bokeh light spheres
        bk_scale = max(0.35, min(1.15, op * 1.1))
        bokeh_specs = [
            (0.12, 0.28, 0.42, QColor(120, 245, 255, int(round(32 * bk_scale)))),
            (0.38, 0.78, 0.50, QColor(80, 255, 185, int(round(26 * bk_scale)))),
            (0.68, 0.22, 0.36, QColor(255, 255, 255, int(round(30 * bk_scale)))),
            (0.88, 0.68, 0.46, QColor(0, 215, 255, int(round(32 * bk_scale)))),
        ]
        for bx_rel, by_rel, br_rel, b_col in bokeh_specs:
            cx = rect.left() + rect.width() * bx_rel
            cy = rect.top() + rect.height() * by_rel
            rad = max(18.0, min(rect.width(), rect.height()) * br_rel)
            rg = QRadialGradient(QPointF(cx, cy), rad)
            rg.setColorAt(0.0, b_col)
            rg.setColorAt(
                0.65, QColor(b_col.red(), b_col.green(), b_col.blue(), b_col.alpha() // 2)
            )
            rg.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(QBrush(rg))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx, cy), rad, rad)

        painter.restore()


    # Shared adaptive 2D optical field renderer & reusable QPainterPaths for standalone panels
    _SHARED_DIALOG_OPTICAL_RENDERER = AquaOpticalFieldRenderer(
        grid_w=176, grid_h=48, aspect=3.6
    )
    _SHARED_OVERLAY_CLIP_PATH = QPainterPath()
    _SHARED_OVERLAY_SHINE_PATH = QPainterPath()
    _SHARED_CAPILLARY_PATH = QPainterPath()
    _SHARED_SCULPTED_RIB_PATH = QPainterPath()
    _SHARED_SURFACE_ARCH_PATH = QPainterPath()


    def draw_frutiger_glass_Dynamic_Overlay(
        painter: QPainter,
        rect: QRectF,
        radius: float = 16.0,
        t_sec: float = 0.0,
        intensity_scale: float = 0.0,
        wave_paths: Optional[Tuple[QPainterPath, QPainterPath, QPainterPath, QPainterPath]] = None,
        optical_qimage: Optional[QImage] = None,
        disturbances: Optional[Sequence[ToolbarWaterDisturbance]] = None,
        readability_zones: Optional[Sequence[Tuple[float, float, float, float, float]]] = None,
    ) -> None:
        """
        Renders the Frutiger Aqua 3.3 coherent multi-depth optical water & living glass simulation:
          - Single Coherent Optical Model (`AquaOpticalFieldRenderer`):
            * All curved caustic ribbons, branching light concentrations, subtle bright cores,
              softer outer turquoise diffusion, localized ribbon intersections, and 1-3 px
              background refraction emerge directly from the high-resolution aspect-true
              continuous optical field (`optical_qimage`), with SmoothPixmapTransform presentation.
            * Eliminates the former independent vector Voronoi node-and-wire overlay (`p_soft_branches`,
              `p_med_branches`, `p_bright_cores`, and isolated pinpoint `glints`) that previously
              created abrupt white connecting lines between dots.
          - Decoupled Intensity Profiles (`resolve_aqua_intensity_profile`):
            * `Off`: Clean, static Frutiger Aqua glass with zero procedural caustics.
            * `Subtle`: Calm atmospheric water movement and gentle caustics.
            * `Medium`: Balanced crystal-clear water and branching caustics with smooth
              highlight compression so caustics never clip or compete with toolbar text.
            * `High`: Greater optical depth and complexity rather than higher brightness —
              tertiary capillary sub-branches, wider ribbon width variation, stronger 2D
              refraction with R/B chromatic prism dispersion, and multi-rib surface reflections.
          - Geometry-aware readability protection (`readability_zones`): gently attenuates
            bright caustic intersections directly behind toolbar labels and sliders.
        """
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        panel_path = _SHARED_OVERLAY_CLIP_PATH
        panel_path.clear()
        panel_path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(panel_path)

        w = rect.width()
        h = rect.height()
        left = rect.left()
        top = rect.top()
        right = rect.right()
        bottom = rect.bottom()
        is_tall_panel = (h > 120.0 and (w / max(1.0, h)) < 3.0)

        director = AeroAnimationDirector.instance()
        op = director.opacity_factor
        eff = max(0.0, float(intensity_scale))
        prof = resolve_aqua_intensity_profile(eff)
        t = float(t_sec) if prof.is_active else 0.0
        vis = prof.highlight_gain
        depth_sep = prof.depth_separation
        surf_gain = prof.surface_reflection_gain

        # ---------------------------------------------------------------------
        # 1. High-Resolution Aspect-True Continuous Caustic & Refraction Field
        #    (Skipped completely when Animation Intensity is Off so static glass
        #     never displays a frozen procedural caustic texture)
        # ---------------------------------------------------------------------
        if prof.is_active:
            if optical_qimage is not None and not optical_qimage.isNull():
                painter.drawImage(rect, optical_qimage)
            elif w > 40.0 and h > 18.0:
                _SHARED_DIALOG_OPTICAL_RENDERER.ensure_geometry(int(w), int(h))
                rgba_arr = _SHARED_DIALOG_OPTICAL_RENDERER.synthesize_rgba_field(
                    t, eff, op
                )
                gh, gw, _ = rgba_arr.shape
                field_img = QImage(
                    rgba_arr.data,
                    gw,
                    gh,
                    gw * 4,
                    QImage.Format.Format_RGBA8888,
                )
                painter.drawImage(rect, field_img)

        # ---------------------------------------------------------------------
        # 2. Deep Layer: Submerged Light Diffusion & Multi-Depth Turquoise Billows
        # ---------------------------------------------------------------------
        if w > 24.0 and h > 14.0:
            if is_tall_panel:
                depth_h = min(140.0, h * 0.22)
                depth_rect = QRectF(left, bottom - depth_h, w, depth_h)
            else:
                depth_rect = QRectF(left, top + h * 0.42, w, h * 0.58)
            depth_grad = QLinearGradient(depth_rect.topLeft(), depth_rect.bottomLeft())
            depth_alpha = min(
                92, int(round((15 + 14 * vis * depth_sep) * max(0.45, op)))
            )
            depth_grad.setColorAt(0.0, QColor(0, 34, 78, 0))
            depth_grad.setColorAt(0.62, QColor(0, 44, 94, depth_alpha))
            depth_grad.setColorAt(1.0, QColor(2, 74, 124, int(depth_alpha * 0.88)))
            painter.fillRect(depth_rect, QBrush(depth_grad))

            # Coherent 2D submerged turquoise & mint diffusion volumes driven by the
            # same continuous wave field & aspect ratio (only when animated)
            if prof.is_active:
                painter.setPen(Qt.PenStyle.NoPen)
                panel_aspect = max(1.2, min(26.0, (w / max(1.0, h)) * 0.84))
                num_billows = (
                    (5 if prof.secondary_structure > 1.25 else 4)
                    if w > 180.0
                    else 2
                )
                for b_idx in range(num_billows):
                    u0 = (b_idx + 0.5) / float(num_billows)
                    v0 = 0.50 + 0.16 * math.sin(b_idx * 2.1 + 0.4)
                    vx_b, vy_b, c_b, luma_b = evaluate_aqua_water_field_2d(
                        u0,
                        v0,
                        t * (0.68 + 0.06 * (b_idx % 2)),
                        aspect=panel_aspect,
                    )
                    bx = left + w * max(
                        0.06,
                        min(0.94, u0 + 0.06 * vx_b * prof.motion_scale),
                    )
                    by = top + h * max(
                        0.22,
                        min(0.84, v0 + 0.16 * vy_b * prof.motion_scale),
                    )
                    rx = max(22.0, (w / float(num_billows)) * (0.52 + 0.16 * luma_b))
                    ry = max(8.5, h * (0.32 + 0.11 * c_b))

                    billow_a = min(
                        52,
                        int(
                            round(
                                (10 + 12 * vis * (0.5 + 0.5 * luma_b))
                                * max(0.42, op)
                            )
                        ),
                    )
                    if billow_a > 3:
                        bg_rg = QRadialGradient(QPointF(bx, by), rx)
                        if b_idx % 2 == 0:
                            bg_rg.setColorAt(0.0, QColor(64, 232, 255, billow_a))
                            bg_rg.setColorAt(0.48, QColor(0, 172, 224, billow_a // 2))
                        else:
                            bg_rg.setColorAt(0.0, QColor(88, 246, 214, billow_a))
                            bg_rg.setColorAt(0.48, QColor(8, 190, 180, billow_a // 2))
                        bg_rg.setColorAt(1.0, QColor(0, 140, 200, 0))
                        painter.setBrush(QBrush(bg_rg))
                        painter.drawEllipse(QPointF(bx, by), rx, ry)

        # ---------------------------------------------------------------------
        # 3. Middle Layer: Soft Oblique Subsurface Refracted Sunbeams
        #    (Note: All fine caustic ribbons, branches, cores & intersections are
        #     synthesized directly inside the high-res continuous optical field
        #     in Section 1, avoiding any separate vector node-network lines.)
        # ---------------------------------------------------------------------
        if prof.is_active and w > 36.0 and h > 16.0:
            p_oblique_shafts = wave_paths[3] if wave_paths else QPainterPath()
            p_oblique_shafts.clear()

            num_shafts = 3 if w > 160.0 else 2
            for sh_i in range(num_shafts):
                u_sh = 0.20 + 0.30 * sh_i + 0.06 * math.sin(t * 0.37 + sh_i * 2.1)
                x_top = left + w * max(0.08, min(0.92, u_sh))
                x_bot = (
                    x_top
                    + h * (0.62 - 0.28 * (sh_i % 2))
                    + 5.0 * math.cos(t * 0.33 + sh_i)
                )
                ctrl_x = 0.5 * (x_top + x_bot) + 4.5 * math.sin(t * 0.47 + sh_i)
                ctrl_y = top + h * 0.48
                p_oblique_shafts.moveTo(x_top, top + 2.0)
                p_oblique_shafts.quadTo(ctrl_x, ctrl_y, x_bot, bottom - 3.0)

            shaft_grad = QLinearGradient(QPointF(left, top), QPointF(left, bottom))
            sh_a = min(32, int(round((8 + 9 * vis) * max(0.42, op))))
            shaft_grad.setColorAt(0.0, QColor(205, 255, 255, sh_a))
            shaft_grad.setColorAt(0.50, QColor(90, 248, 238, sh_a // 2))
            shaft_grad.setColorAt(1.0, QColor(40, 220, 255, 0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(
                    QBrush(shaft_grad),
                    max(4.5, h * 0.16),
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawPath(p_oblique_shafts)

        # ---------------------------------------------------------------------
        # 4. Surface Layer: Curved Upper Specular Glass Cap & Layered Reflections
        # ---------------------------------------------------------------------
        if is_tall_panel:
            shine_h = min(38.0, h * 0.07)
            curve_arch = min(3.0, h * 0.015)
        else:
            shine_h = h * 0.45
            curve_arch = min(5.5, h * 0.11) + (
                0.85 * math.sin(t * 0.44) if prof.is_active else 0.0
            )
        shine_left = left + 1.8
        shine_right = right - 1.8
        shine_top = top + 1.6
        shine_bot = shine_top + shine_h

        shine_path = _SHARED_OVERLAY_SHINE_PATH
        shine_path.clear()
        cap_r = max(4.0, radius - 2.0)
        shine_path.moveTo(shine_left + cap_r, shine_top)
        shine_path.lineTo(shine_right - cap_r, shine_top)
        shine_path.quadTo(shine_right, shine_top, shine_right, shine_top + cap_r)
        shine_path.lineTo(shine_right, shine_bot)
        shine_path.cubicTo(
            shine_left + (shine_right - shine_left) * 0.68,
            shine_bot - curve_arch,
            shine_left + (shine_right - shine_left) * 0.32,
            shine_bot - curve_arch * 0.65,
            shine_left,
            shine_bot,
        )
        shine_path.lineTo(shine_left, shine_top + cap_r)
        shine_path.quadTo(shine_left, shine_top, shine_left + cap_r, shine_top)
        shine_path.closeSubpath()

        op_shine = max(0.45, min(1.18, op * 1.25))
        shine_grad = QLinearGradient(
            QPointF(left, shine_top), QPointF(left, shine_bot)
        )
        shine_grad.setColorAt(
            0.0, QColor(255, 255, 255, min(186, int(round(122 * op_shine))))
        )
        shine_grad.setColorAt(
            0.55, QColor(225, 252, 255, min(88, int(round(38 * op_shine))))
        )
        shine_grad.setColorAt(1.0, QColor(255, 255, 255, 5))
        painter.fillPath(shine_path, QBrush(shine_grad))

        # Slow, subtle surface reflections (move much more gently than underlying caustics;
        # static clean diagonal reflection panes when Animation Intensity is Off)
        if w > 24.0:
            refl1_u = (
                0.5 + 0.40 * math.sin(t * 0.31 + 0.35)
                if prof.is_active
                else 0.28
            )
            refl1_cx = shine_left + (shine_right - shine_left) * refl1_u
            refl1_w = max(48.0, w * 0.24)
            refl1_grad = QLinearGradient(
                QPointF(refl1_cx - refl1_w, shine_top),
                QPointF(refl1_cx + refl1_w * 0.85, shine_bot),
            )
            r1_alpha = min(98, int(round(34 * surf_gain)))
            refl1_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            refl1_grad.setColorAt(0.5, QColor(242, 255, 255, r1_alpha))
            refl1_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(shine_path, QBrush(refl1_grad))

            refl2_u = (
                0.5 - 0.38 * math.cos(t * 0.23 + 1.8)
                if prof.is_active
                else 0.74
            )
            refl2_cx = shine_left + (shine_right - shine_left) * refl2_u
            refl2_w = max(36.0, w * 0.18)
            refl2_grad = QLinearGradient(
                QPointF(refl2_cx - refl2_w, shine_top),
                QPointF(refl2_cx + refl2_w, shine_bot),
            )
            r2_alpha = min(82, int(round(26 * surf_gain)))
            refl2_grad.setColorAt(0.0, QColor(170, 255, 245, 0))
            refl2_grad.setColorAt(0.5, QColor(185, 255, 250, r2_alpha))
            refl2_grad.setColorAt(1.0, QColor(170, 255, 245, 0))
            painter.fillPath(shine_path, QBrush(refl2_grad))

            # High intensity optical layering: crisp curved specular meniscus rib along the
            # lower boundary of the cylindrical glass cap + secondary counter-drifting sheen
            if prof.is_active and surf_gain > 1.12:
                arch_rib_path = _SHARED_SURFACE_ARCH_PATH
                arch_rib_path.clear()
                arch_rib_path.moveTo(shine_left + 8.0, shine_bot - 0.5)
                arch_rib_path.cubicTo(
                    shine_left + (shine_right - shine_left) * 0.32,
                    shine_bot - curve_arch * 0.65,
                    shine_left + (shine_right - shine_left) * 0.68,
                    shine_bot - curve_arch,
                    shine_right - 8.0,
                    shine_bot - 0.5,
                )
                rib_grad = QLinearGradient(
                    QPointF(shine_left, shine_bot), QPointF(shine_right, shine_bot)
                )
                rib_u = max(0.15, min(0.85, 0.5 - 0.32 * math.sin(t * 0.29 + 0.9)))
                rib_a = min(112, int(round(48 * (surf_gain - 0.85) * op_shine)))
                rib_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
                rib_grad.setColorAt(max(0.05, rib_u - 0.22), QColor(165, 250, 255, rib_a // 2))
                rib_grad.setColorAt(rib_u, QColor(250, 255, 255, rib_a))
                rib_grad.setColorAt(min(0.95, rib_u + 0.22), QColor(165, 250, 255, rib_a // 2))
                rib_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(
                    QPen(QBrush(rib_grad), 1.15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                )
                painter.drawPath(arch_rib_path)

        # Localized curved dome catch-lights at left and right capsule ends
        dome_r = max(14.0, min(w * 0.12, h * 0.75))
        for dome_x in (left + dome_r * 0.45, right - dome_r * 0.45):
            dome_rg = QRadialGradient(QPointF(dome_x, top + h * 0.38), dome_r)
            dome_a = min(95, int(round((30 + 16 * vis) * op_shine)))
            dome_rg.setColorAt(0.0, QColor(230, 255, 255, dome_a))
            dome_rg.setColorAt(0.6, QColor(120, 245, 255, dome_a // 3))
            dome_rg.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(dome_rg))
            painter.drawEllipse(QPointF(dome_x, top + h * 0.38), dome_r, h * 0.45)

        # ---------------------------------------------------------------------
        # 5. Edge Layer (Liquid Containment): Bottom Bounce Glow & Interaction Ripples
        # ---------------------------------------------------------------------
        if is_tall_panel:
            bot_h = min(40.0, h * 0.08)
            bot_rect = QRectF(left + 4.0, bottom - bot_h, max(2.0, w - 8.0), bot_h)
        else:
            bot_rect = QRectF(
                left + 4.0,
                bottom - h * 0.26,
                max(2.0, w - 8.0),
                h * 0.26,
            )
        bot_grad = QLinearGradient(bot_rect.topLeft(), bot_rect.bottomLeft())
        bot_grad.setColorAt(0.0, QColor(0, 255, 235, 0))
        bounce_alpha = min(
            135,
            int(
                round(
                    (58 + 26 * vis + (14 * vis * math.sin(t * 0.67) if eff > 0.0 else 0.0))
                    * max(0.55, op * 1.15)
                )
            ),
        )
        bot_grad.setColorAt(1.0, QColor(105, 255, 240, max(38, bounce_alpha)))
        painter.fillRect(bot_rect, QBrush(bot_grad))

        # Localized Toolbar Water Disturbances around clicked buttons/sliders
        if disturbances and eff > 0.0:
            painter.setPen(Qt.PenStyle.NoPen)
            eff_d = min(1.45, max(0.45, eff))
            for d_item in disturbances:
                age = t - d_item.start_sec
                if 0.0 <= age < d_item.duration_sec:
                    p_d = age / max(0.05, d_item.duration_sec)
                    p_ease = 1.0 - pow(1.0 - p_d, 2.2)
                    env_d = (
                        math.sin(math.pi * pow(p_d, 0.65))
                        * pow(1.0 - p_d, 0.72)
                        * d_item.strength
                        * eff_d
                    )
                    rad_x = 18.0 + 54.0 * p_ease
                    rad_y = min(h * 0.72, 12.0 + 24.0 * p_ease)
                    d_pt = QPointF(d_item.center_x, d_item.center_y)
                    halo_a = min(120, int(round(92 * env_d)))
                    if halo_a > 2:
                        d_rg = QRadialGradient(d_pt, rad_x)
                        d_rg.setColorAt(0.0, QColor(255, 255, 255, 0))
                        d_rg.setColorAt(0.55, QColor(0, 45, 95, halo_a // 3))
                        d_rg.setColorAt(0.78, QColor(185, 255, 255, halo_a))
                        d_rg.setColorAt(0.92, QColor(70, 245, 255, halo_a // 2))
                        d_rg.setColorAt(1.0, QColor(0, 210, 255, 0))
                        painter.setBrush(QBrush(d_rg))
                        painter.drawEllipse(d_pt, rad_x, rad_y)

        painter.restore()

        # ---------------------------------------------------------------------
        # 6. Edge Layer (Borders): Manufactured Outer Glass Shell & Inner Liquid Meniscus
        # ---------------------------------------------------------------------
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # 6a. Inner concave liquid meniscus rim (separates interior water from glass wall)
        meniscus_rect = rect.adjusted(3.0, 2.8, -3.0, -2.8)
        meniscus_rad = max(2.0, radius - 2.8)
        men_grad = QLinearGradient(meniscus_rect.topLeft(), meniscus_rect.bottomRight())
        men_a = min(145, int(round((48 + 28 * vis) * max(0.55, op * 1.15))))
        men_grad.setColorAt(0.0, QColor(175, 255, 255, men_a))
        men_grad.setColorAt(0.5, QColor(0, 195, 235, int(men_a * 0.55)))
        men_grad.setColorAt(1.0, QColor(120, 255, 230, int(men_a * 0.90)))
        painter.setPen(QPen(QBrush(men_grad), 1.15))
        painter.drawRoundedRect(meniscus_rect, meniscus_rad, meniscus_rad)

        # 6b. Inner frosted glass wall bevel
        inner_rect = rect.adjusted(1.3, 1.3, -1.3, -1.3)
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1.1))
        painter.drawRoundedRect(
            inner_rect, max(2.0, radius - 1.2), max(2.0, radius - 1.2)
        )

        # 6c. Outer manufactured electric-cyan glass rim
        painter.setPen(QPen(QColor(95, 235, 255, 218), 1.5))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        # 6d. Bright curved grazing reflection along part of the top edge
        if w > 30.0:
            graze_u = 0.48 + (0.26 * math.sin(t * 0.33 + 0.5) if eff > 0.0 else 0.0)
            graze_cx = left + w * graze_u
            graze_span = max(42.0, w * 0.26)
            top_edge_rect = QRectF(
                left + radius * 0.6, top + 0.6, max(10.0, w - radius * 1.2), 2.2
            )
            graze_grad = QLinearGradient(
                QPointF(graze_cx - graze_span, top_edge_rect.top()),
                QPointF(graze_cx + graze_span, top_edge_rect.top()),
            )
            graze_a = min(245, int(round(155 + 55 * vis)))
            graze_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            graze_grad.setColorAt(0.5, QColor(255, 255, 255, graze_a))
            graze_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(graze_grad))
            painter.drawRoundedRect(top_edge_rect, 1.1, 1.1)

        painter.restore()


    def draw_frutiger_glass_panel(
        painter: QPainter,
        rect: QRectF,
        radius: float = 16.0,
        frosted_pixmap: Optional[QPixmap] = None,
        tint_style: str = "aqua",
        t_sec: float = 0.0,
        intensity_scale: float = 0.0,
    ) -> None:
        """
        Renders a complete Frutiger Aero / Frutiger Aqua translucent glass panel,
        combining the frosted acrylic base with optional living water & caustic layers.
        """
        draw_frutiger_glass_base(
            painter,
            rect,
            radius=radius,
            frosted_pixmap=frosted_pixmap,
            tint_style=tint_style,
        )
        draw_frutiger_glass_Dynamic_Overlay(
            painter,
            rect,
            radius=radius,
            t_sec=t_sec,
            intensity_scale=intensity_scale,
        )


    class AeroGelButton(QPushButton):
        """
        Custom-painted 3D Skeuomorphic Frutiger Aqua Gel / Silicone Capsule Button:
          - Centered Inward Gel Cushion Press (`_build_deformed_gel_pill_path`):
            When pressed, the button stays anchored in place around its center `(cx, cy)`
            and caves gently inward toward the center along both its upper and lower middle
            spans (`top_indent`, `bot_indent`), while the left and right semicircular end-caps
            remain rounded, plump, and softly inflated (`left_swell`, `right_swell`).
            Eliminates the previous bottom-anchored top-down vertical flatten/drop.
          - Deformable Optical Reflections:
            * The upper specular highlight (`_cap_path`) dips inward along its top edge and
              pinches upward along its lower arch to form a concave lens around the pressed center.
            * A centered concave gel contact dimple (`dep_rg`) and bilateral end-cap cushion
              catch-lights bloom inside the capsule under finger pressure.
            * The inner liquid meniscus rim (`_meniscus_path`) deforms with the capsule contour.
            * The text label stays centered and subtly recesses into the gel (`text_scale`)
              rather than sliding downward.
          - Quick-click impulse follow-through (~102ms OutCubic press + ~395ms C1-continuous
            underdamped elastic rebound) + variant-tinted dual-wave refractive water ripples
            + localized parent toolbar water disturbance.
        """

        _instance_seq: int = 0
        MAX_ACTIVE_RIPPLES: int = 4
        _LABEL_FONT: Optional[QFont] = None

        PALETTES = {
            # (top_color, mid_color, bottom_glow_color, border_color)
            "glass": (
                QColor(65, 165, 225, 155),
                QColor(22, 90, 150, 175),
                QColor(90, 225, 255, 195),
                QColor(185, 245, 255, 200),
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

        def __init__(
            self,
            text: str,
            variant: str = "glass",
            custom_swatch: Optional[QColor] = None,
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(text, parent)
            AeroGelButton._instance_seq += 1
            # Staggered per-button phase so idle reflections never shimmer in unison
            self._phase_offset: float = (AeroGelButton._instance_seq * 1.73) % (
                2.0 * math.pi
            )
            self.variant = variant
            self.custom_swatch = custom_swatch
            self._hovered = False

            # Smooth hover animation state (0.0 = idle, 1.0 = hovered)
            self._hover_progress: float = 0.0
            self._hover_sweep: float = 0.0
            self._hover_anim = QVariantAnimation(self)
            self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._hover_anim.valueChanged.connect(self._on_hover_anim_tick)

            # Physically inspired jelly press/rebound state:
            #   _jelly_strain < 0.0: inward cushion compression (down to -1.0)
            #   _jelly_strain > 0.0: elastic rebound overshoot (~+0.36)
            #   _jelly_strain == 0.0: resting capsule
            self._jelly_strain: float = 0.0
            self._jelly_velocity: float = 0.0
            self._last_strain_sample_sec: float = 0.0
            self._press_started_sec: float = 0.0
            self._rebound_start_strain: float = -1.0
            self._rebound_initial_velocity: float = 0.0
            self._jelly_mode: str = "idle"
            self._press_norm_x: float = 0.0
            self._press_norm_y: float = 0.0
            self._jelly_anim = QVariantAnimation(self)
            self._jelly_anim.valueChanged.connect(self._on_jelly_anim_tick)
            self._jelly_anim.finished.connect(self._on_jelly_anim_finished)

            # Localized water ripples (bounded list + single reusable 60 FPS timer)
            self._ripples: List[WaterRippleState] = []
            self._ripple_timer = QTimer(self)
            self._ripple_timer.setInterval(16)
            self._ripple_timer.timeout.connect(self._on_ripple_tick)

            # Reusable QPainterPaths for zero-allocation deformed gel body, meniscus & specular cap
            self._pill_clip_path = QPainterPath()
            self._meniscus_path = QPainterPath()
            self._cap_path = QPainterPath()

            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setMinimumHeight(32)
            fm = self.fontMetrics()
            pad = 24 if len(text) > 2 else 18
            self.setMinimumWidth(max(34, fm.horizontalAdvance(text) + pad))

        def set_swatch_color(self, color: QColor) -> None:
            self.custom_swatch = color
            self.update()

        def _notify_parent_toolbar_water(
            self, local_pt: QPointF, strength: float = 0.36
        ) -> None:
            """Propagates a subtle, spatially localized water disturbance to the parent toolbar."""
            parent_w = self.parentWidget()
            while parent_w is not None:
                if hasattr(parent_w, "trigger_local_disturbance"):
                    mapped_pt = self.mapTo(parent_w, local_pt.toPoint())
                    parent_w.trigger_local_disturbance(
                        QPointF(float(mapped_pt.x()), float(mapped_pt.y())),
                        strength=strength,
                    )
                    break
                parent_w = parent_w.parentWidget()

        def _spawn_ripple(
            self, origin_x: float, origin_y: float, strength: float = 1.0
        ) -> None:
            director = AeroAnimationDirector.instance()
            if director.scale <= 0.0:
                return
            now = director.elapsed_seconds()
            w = max(1.0, float(self.width()))
            h = max(1.0, float(self.height()))
            nx = max(-1.0, min(1.0, (origin_x - w * 0.5) / (w * 0.5)))
            ny = max(-1.0, min(1.0, (origin_y - h * 0.5) / (h * 0.5)))
            if len(self._ripples) >= self.MAX_ACTIVE_RIPPLES:
                self._ripples.pop(0)
            self._ripples.append(
                WaterRippleState(
                    origin_x=float(origin_x),
                    origin_y=float(origin_y),
                    start_sec=now,
                    duration_sec=0.48,
                    strength=float(strength),
                    norm_x=nx,
                    norm_y=ny,
                )
            )
            if not self._ripple_timer.isActive():
                self._ripple_timer.start()

        def _start_gel_press(
            self,
            press_x: float,
            press_y: float,
            ripple_strength: float = 1.0,
            toolbar_strength: float = 0.36,
        ) -> None:
            director = AeroAnimationDirector.instance()
            scale = director.scale
            w = max(1.0, float(self.width()))
            h = max(1.0, float(self.height()))
            self._press_norm_x = max(-1.0, min(1.0, (press_x - w * 0.5) / (w * 0.5)))
            self._press_norm_y = max(-1.0, min(1.0, (press_y - h * 0.5) / (h * 0.5)))

            if scale > 0.0:
                now = director.elapsed_seconds()
                self._press_started_sec = now
                self._last_strain_sample_sec = now
                self._jelly_anim.stop()
                self._jelly_mode = "compress"

                # Immediate tactile contact response on frame 1 without teleporting an active rebound
                start_s = float(self._jelly_strain)
                if -0.22 < start_s <= 0.10:
                    start_s = min(start_s, -0.24 * min(1.22, max(0.55, scale)))
                    self._jelly_strain = start_s
                self._jelly_velocity = -8.2

                comp_ms = int(round(100 * max(0.90, min(1.10, 1.0 / max(0.75, scale)))))
                self._jelly_anim.setDuration(max(90, min(112, comp_ms)))
                self._jelly_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self._jelly_anim.setStartValue(start_s)
                self._jelly_anim.setEndValue(-1.0)
                self._jelly_anim.start()

                self._spawn_ripple(press_x, press_y, strength=ripple_strength)
                self._notify_parent_toolbar_water(
                    QPointF(press_x, press_y), strength=toolbar_strength
                )
                self.update()
            else:
                self.update()

        def _start_gel_release(self) -> None:
            director = AeroAnimationDirector.instance()
            scale = director.scale
            if scale > 0.0:
                was_compressing = self._jelly_mode == "compress"
                curr_strain = float(self._jelly_strain)
                self._jelly_anim.stop()

                # Preserve exact current strain at u=0.0 so releasing early NEVER teleports!
                self._rebound_start_strain = curr_strain
                if was_compressing and curr_strain > -0.85:
                    rem = max(0.28, 1.0 + curr_strain)
                    self._rebound_initial_velocity = -6.4 * rem
                else:
                    self._rebound_initial_velocity = max(
                        -3.2, min(3.2, self._jelly_velocity * 0.14)
                    )

                self._jelly_mode = "rebound"
                reb_ms = int(round(380 + 25 * min(1.45, max(0.45, scale))))
                self._jelly_anim.setDuration(max(365, min(435, reb_ms)))
                self._jelly_anim.setEasingCurve(QEasingCurve.Type.Linear)
                self._jelly_anim.setStartValue(0.0)
                self._jelly_anim.setEndValue(1.0)
                self._jelly_anim.start()
            else:
                self._jelly_strain = 0.0
                self._jelly_velocity = 0.0
                self._jelly_mode = "idle"
                self.update()

        def _on_hover_anim_tick(self, value: object) -> None:
            val = float(value)
            self._hover_progress = val
            self._hover_sweep = val
            self.update()

        def _on_jelly_anim_tick(self, value: object) -> None:
            director = AeroAnimationDirector.instance()
            now = director.elapsed_seconds()
            dt = max(1e-3, now - self._last_strain_sample_sec)
            prev_strain = self._jelly_strain

            u = float(value)
            if self._jelly_mode == "compress":
                self._jelly_strain = u
            elif self._jelly_mode == "rebound":
                self._jelly_strain = compute_damped_jelly_rebound(
                    u,
                    self._rebound_start_strain,
                    self._rebound_initial_velocity,
                    director.scale,
                )
            self._jelly_velocity = (self._jelly_strain - prev_strain) / dt
            self._last_strain_sample_sec = now
            self.update()

        def _on_jelly_anim_finished(self) -> None:
            if self._jelly_mode == "rebound":
                self._jelly_strain = 0.0
                self._jelly_velocity = 0.0
                self._jelly_mode = "idle"
                self.update()

        def _on_ripple_tick(self) -> None:
            director = AeroAnimationDirector.instance()
            if director.scale <= 0.0:
                self._ripples.clear()
                self._ripple_timer.stop()
                self.update()
                return

            now = director.elapsed_seconds()
            self._ripples = [
                r for r in self._ripples if (now - r.start_sec) < r.duration_sec
            ]
            if not self._ripples:
                self._ripple_timer.stop()
            self.update()

        def enterEvent(self, event) -> None:
            self._hovered = True
            scale = AeroAnimationDirector.instance().scale
            self._hover_anim.stop()
            if scale <= 0.0:
                self._hover_progress = 1.0
                self._hover_sweep = 1.0
                self.update()
            else:
                self._hover_anim.setDuration(240)
                self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self._hover_anim.setStartValue(float(self._hover_progress))
                self._hover_anim.setEndValue(1.0)
                self._hover_anim.start()
            super().enterEvent(event)

        def leaveEvent(self, event) -> None:
            self._hovered = False
            scale = AeroAnimationDirector.instance().scale
            self._hover_anim.stop()
            if scale <= 0.0:
                self._hover_progress = 0.0
                self._hover_sweep = 0.0
                self.update()
            else:
                self._hover_anim.setDuration(265)
                self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self._hover_anim.setStartValue(float(self._hover_progress))
                self._hover_anim.setEndValue(0.0)
                self._hover_anim.start()
            super().leaveEvent(event)

        def mousePressEvent(self, event) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                pos = event.position()
                self._start_gel_press(float(pos.x()), float(pos.y()))
            super().mousePressEvent(event)

        def mouseReleaseEvent(self, event) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._start_gel_release()
            super().mouseReleaseEvent(event)

        def keyPressEvent(self, event) -> None:
            if (
                event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not event.isAutoRepeat()
            ):
                self._start_gel_press(
                    float(self.width()) * 0.5,
                    float(self.height()) * 0.5,
                    ripple_strength=0.95,
                    toolbar_strength=0.32,
                )
            super().keyPressEvent(event)

        def keyReleaseEvent(self, event) -> None:
            if (
                event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not event.isAutoRepeat()
            ):
                self._start_gel_release()
            super().keyReleaseEvent(event)

        def reset_animation_state(self) -> None:
            """Immediately stops active animations/ripples and returns the button to resting geometry."""
            self._hover_anim.stop()
            self._jelly_anim.stop()
            self._ripple_timer.stop()
            self._ripples.clear()
            self._jelly_strain = 0.0
            self._jelly_velocity = 0.0
            self._jelly_mode = "idle"
            self._hover_progress = 1.0 if self._hovered else 0.0
            self._hover_sweep = self._hover_progress
            self.update()

        def hideEvent(self, event) -> None:
            self._hovered = False
            self.reset_animation_state()
            super().hideEvent(event)

        @staticmethod
        def _build_deformed_gel_pill_path(
            path: QPainterPath,
            rect: QRectF,
            pressure: float,
            overshoot: float,
            press_nx: float,
            press_ny: float,
        ) -> None:
            """
            Populates `path` with a centered, inward-compressing silicone-gel capsule contour.
            Under compression (`pressure > 0`):
              - Both the upper and lower middle spans curve gently inward toward the capsule's
                centerline (`top_indent` downward and `bot_indent` upward), creating a soft
                centered cushion dimple rather than flattening the button from the top.
              - The left and right semicircular end-caps remain rounded, plump, and softly
                inflated (`left_swell`, `right_swell`, and `shoulder_lift`).
            During elastic rebound (`overshoot > 0`):
              - The center waist springs gently outward past flat and settles smoothly to rest.
            """
            path.clear()
            left = rect.left()
            right = rect.right()
            top = rect.top()
            bottom = rect.bottom()
            w = rect.width()
            h = rect.height()
            r = min(w * 0.5, h * 0.5)
            straight_w = max(0.0, w - 2.0 * r)

            if straight_w < 1.5 or (pressure < 1e-3 and overshoot < 1e-3):
                path.addRoundedRect(rect, r, r)
                return

            x_l = left + r
            x_r = right - r
            # Bias the inward waist indentation slightly toward the horizontal click point
            bias_u = max(0.22, min(0.78, 0.5 + 0.24 * press_nx))

            # Symmetrical inward cushion pinch toward the horizontal centerline:
            # top middle dips inward (+top_indent), bottom middle draws inward (-bot_indent)
            top_indent = (
                pressure * (1.42 + 0.24 * max(0.0, -press_ny))
                - overshoot * 0.78
            )
            bot_indent = (
                pressure * (1.28 + 0.24 * max(0.0, press_ny))
                - overshoot * 0.72
            )
            # Keep the rounded left/right shoulders plump and softly inflated
            shoulder_lift = pressure * 0.26 - overshoot * 0.14
            y_top_end = top - shoulder_lift
            y_bot_end = bottom + shoulder_lift

            base_swell = pressure * 0.82 - overshoot * 0.36
            left_swell = base_swell * (1.0 + 0.35 * max(0.0, -press_nx))
            right_swell = base_swell * (1.0 + 0.35 * max(0.0, press_nx))

            path.moveTo(x_l, y_top_end)
            c1_x = x_l + straight_w * (bias_u * 0.58)
            c2_x = x_l + straight_w * (bias_u + (1.0 - bias_u) * 0.42)
            path.cubicTo(
                c1_x,
                top + top_indent,
                c2_x,
                top + top_indent,
                x_r,
                y_top_end,
            )
            # Right semicircular dome cap stays rounded, plump, and inflated
            k = 0.55228475 * r
            k_y = k * (1.0 + 0.04 * pressure - 0.02 * overshoot)
            mid_y = top + h * (0.5 + 0.025 * press_ny * pressure)
            path.cubicTo(
                x_r + k + right_swell * 0.65,
                y_top_end,
                right + right_swell,
                mid_y - k_y,
                right + right_swell,
                mid_y,
            )
            path.cubicTo(
                right + right_swell,
                mid_y + k_y,
                x_r + k + right_swell * 0.65,
                y_bot_end,
                x_r,
                y_bot_end,
            )
            # Lower gel surface curves symmetrically inward toward the capsule center
            path.cubicTo(
                c2_x,
                bottom - bot_indent,
                c1_x,
                bottom - bot_indent,
                x_l,
                y_bot_end,
            )
            # Left semicircular dome cap stays rounded, plump, and inflated
            path.cubicTo(
                x_l - k - left_swell * 0.65,
                y_bot_end,
                left - left_swell,
                mid_y + k_y,
                left - left_swell,
                mid_y,
            )
            path.cubicTo(
                left - left_swell,
                mid_y - k_y,
                x_l - k - left_swell * 0.65,
                y_top_end,
                x_l,
                y_top_end,
            )
            path.closeSubpath()

        def paintEvent(self, event) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            director = AeroAnimationDirector.instance()
            anim_scale = director.scale
            t_sec = director.elapsed_seconds() if anim_scale > 0.0 else 0.0

            # Generous unclipped margin inside QWidget bounds so lateral end-cap cushion
            # and rebound aura never clip at the widget edges
            base_rect = QRectF(self.rect()).adjusted(3.2, 2.8, -3.2, -2.4)
            cx = base_rect.center().x()
            cy = base_rect.center().y()

            # -----------------------------------------------------------------
            # 1. Centered Inward Gel Cushion Physics (stays centered in place;
            #    caves inward at the center while keeping rounded ends inflated)
            # -----------------------------------------------------------------
            strain = (
                self._jelly_strain
                if anim_scale > 0.0
                else (-0.55 if self.isDown() else 0.0)
            )
            eff_scale = (
                min(1.42, max(0.50, anim_scale))
                if anim_scale > 0.0
                else (0.85 if self.isDown() else 0.0)
            )
            # Symmetrical centered cushion scale (~3.2% vertical waist cushion + ~2.2% lateral
            # end-cap volume conservation around the capsule center `(cx, cy)`)
            max_comp_y = 0.032 * eff_scale
            max_expand_x = 0.022 * eff_scale
            pressure = max(0.0, -strain)
            overshoot = max(0.0, strain)

            sx = 1.0
            sy = 1.0
            x_offset = 0.0
            y_offset = 0.0
            tilt_deg = 0.0
            if abs(strain) > 1e-4 and eff_scale > 0.0:
                if strain < 0.0:
                    # Pressing inward into the center of the soft gel capsule:
                    # stays centered vertically (zero downward chop!) with a subtle
                    # inward cushion around the center pivot
                    sy = 1.0 + strain * max_comp_y
                    sx = 1.0 - strain * max_expand_x
                    x_offset = self._press_norm_x * pressure * 0.28 * eff_scale
                    y_offset = self._press_norm_y * pressure * 0.24 * eff_scale
                    tilt_deg = self._press_norm_x * pressure * 0.42 * min(1.15, eff_scale)
                else:
                    # Soft elastic rebound around the capsule center
                    sy = 1.0 + strain * (max_comp_y * 0.94)
                    sx = 1.0 - strain * (max_expand_x * 0.84)
                    x_offset = -self._press_norm_x * overshoot * 0.12 * eff_scale
                    y_offset = -self._press_norm_y * overshoot * 0.12 * eff_scale
                    tilt_deg = -self._press_norm_x * overshoot * 0.22 * min(1.15, eff_scale)

                painter.save()
                # Anchor at the true center of the capsule (never at the bottom edge!)
                pivot_x = cx + self._press_norm_x * base_rect.width() * 0.12
                pivot_y = cy + self._press_norm_y * base_rect.height() * 0.12
                painter.translate(pivot_x + x_offset, pivot_y + y_offset)
                if abs(tilt_deg) > 0.02:
                    painter.rotate(tilt_deg)
                painter.scale(sx, sy)
                painter.translate(-pivot_x, -pivot_y)
                rect = base_rect
                has_transform = True
            else:
                rect = base_rect
                has_transform = False

            radius = rect.height() / 2.0

            # Pick base palette based on state & variant
            if self.custom_swatch is not None:
                c = self.custom_swatch
                top_c = QColor(c.lighter(135))
                mid_c = QColor(c.darker(135))
                bot_c = QColor(c.lighter(165))
                top_c.setAlpha(210)
                mid_c.setAlpha(220)
                bot_c.setAlpha(230)
                bdr_c = QColor(255, 255, 255, 235)
                ripple_tint = QColor(c.lighter(175))
            elif self.isCheckable() and self.isChecked():
                t0, m0, b0, bd0 = self.PALETTES["aqua_active"]
                top_c, mid_c, bot_c, bdr_c = (
                    QColor(t0),
                    QColor(m0),
                    QColor(b0),
                    QColor(bd0),
                )
                ripple_tint = QColor(145, 255, 255)
            else:
                t0, m0, b0, bd0 = self.PALETTES.get(
                    self.variant, self.PALETTES["glass"]
                )
                top_c, mid_c, bot_c, bdr_c = (
                    QColor(t0),
                    QColor(m0),
                    QColor(b0),
                    QColor(bd0),
                )
                if self.variant == "emerald":
                    ripple_tint = QColor(175, 255, 190)
                elif self.variant == "ruby":
                    ripple_tint = QColor(255, 195, 185)
                elif self.variant == "sapphire":
                    ripple_tint = QColor(150, 242, 255)
                else:
                    ripple_tint = QColor(135, 250, 255)

            # Scale gel body translucency with user's Glass Transparency setting
            op_btn = max(0.24, min(1.25, director.opacity_factor * 1.18))
            if (
                self.variant == "glass"
                and not (self.isCheckable() and self.isChecked())
                and self.custom_swatch is None
            ):
                top_c.setAlpha(max(24, min(220, int(round(top_c.alpha() * op_btn)))))
                mid_c.setAlpha(max(28, min(230, int(round(mid_c.alpha() * op_btn)))))
                bot_c.setAlpha(max(34, min(240, int(round(bot_c.alpha() * op_btn)))))
            else:
                op_jewel = max(0.45, min(1.0, 0.38 + op_btn * 0.55))
                top_c.setAlpha(max(70, min(248, int(round(top_c.alpha() * op_jewel)))))
                mid_c.setAlpha(max(80, min(252, int(round(mid_c.alpha() * op_jewel)))))
                bot_c.setAlpha(max(95, min(255, int(round(bot_c.alpha() * op_jewel)))))

            # Smooth hover color interpolation (240ms OutCubic entry / 265ms exit)
            hover_t = (
                self._hover_progress
                if anim_scale > 0.0
                else (1.0 if self._hovered else 0.0)
            )
            if hover_t > 1e-3:
                top_c = _lerp_color(top_c, top_c.lighter(122), hover_t)
                mid_c = _lerp_color(mid_c, mid_c.lighter(112), hover_t * 0.78)
                bot_c = _lerp_color(bot_c, bot_c.lighter(120), hover_t)
                bdr_c = _lerp_color(bdr_c, QColor(240, 255, 255, 252), hover_t)

            # Optical response to inward center compression: center deepens slightly while
            # internal subsurface glow intensifies inside the compressed gel cushion
            if pressure > 1e-3:
                bot_c = _lerp_color(
                    bot_c,
                    QColor(ripple_tint.red(), ripple_tint.green(), ripple_tint.blue(), 255),
                    min(1.0, pressure * 0.68),
                )
                mid_c = _lerp_color(
                    mid_c, mid_c.darker(116), min(1.0, pressure * 0.42)
                )
                bdr_c = _lerp_color(
                    bdr_c, QColor(255, 255, 255, 255), min(1.0, pressure * 0.55)
                )
            elif overshoot > 1e-3:
                top_c = _lerp_color(
                    top_c,
                    QColor(210, 255, 255, top_c.alpha()),
                    min(1.0, overshoot * 0.60),
                )

            # Build inward-caving gel capsule contour (symmetrical waist pinch + plump rounded ends)
            self._build_deformed_gel_pill_path(
                self._pill_clip_path,
                rect,
                pressure=pressure * eff_scale,
                overshoot=overshoot * eff_scale,
                press_nx=self._press_norm_x,
                press_ny=self._press_norm_y,
            )

            # 1b. Outer hover / active / compression aqua luminous aura (follows deformed contour)
            active_aura = max(
                hover_t * 0.88,
                1.0 if (self.isCheckable() and self.isChecked()) else 0.0,
                pressure * 0.78,
            )
            if active_aura > 0.01:
                glow_alpha = min(220, int(round(175 * active_aura)))
                painter.setPen(
                    QPen(
                        QColor(
                            ripple_tint.red(),
                            ripple_tint.green(),
                            ripple_tint.blue(),
                            glow_alpha,
                        ),
                        2.3,
                    )
                )
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(self._pill_clip_path)

            # 2. Liquid Gel 4-Stop Gradient Body
            grad_top_pt = QPointF(
                rect.center().x() + self._press_norm_x * rect.width() * 0.10 * pressure,
                rect.top() + rect.height() * (0.04 * pressure - 0.02 * overshoot),
            )
            grad_bot_pt = QPointF(
                rect.center().x() - self._press_norm_x * rect.width() * 0.08 * pressure,
                rect.bottom() - rect.height() * (0.04 * pressure - 0.02 * overshoot),
            )
            body_grad = QLinearGradient(grad_top_pt, grad_bot_pt)
            body_grad.setColorAt(0.0, top_c)
            mid_stop = max(0.32, min(0.62, 0.46 + 0.06 * pressure - 0.04 * overshoot))
            body_grad.setColorAt(mid_stop, mid_c)
            mid_dark = mid_c.darker(116)
            mid_dark.setAlpha(mid_c.alpha())
            dark_stop = max(0.56, min(0.84, 0.72 - 0.06 * pressure + 0.04 * overshoot))
            body_grad.setColorAt(dark_stop, mid_dark)
            body_grad.setColorAt(1.0, bot_c)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(body_grad))
            painter.drawPath(self._pill_clip_path)

            # Clip all internal optical layers, pressure redistribution, ripples & reflections
            painter.save()
            painter.setClipPath(self._pill_clip_path)

            # 2a. Internal Gel Subsurface Bloom + Inflated Left/Right End-Cap Cushion Lobes
            if hover_t > 0.01 or pressure > 0.01 or overshoot > 0.01:
                gel_cx = (
                    rect.center().x()
                    + self._press_norm_x * rect.width() * (0.20 * pressure + 0.06 * hover_t)
                )
                gel_cy = (
                    rect.top()
                    + rect.height() * (0.60 + 0.08 * pressure - 0.05 * overshoot)
                )
                gel_rx = max(14.0, rect.width() * (0.46 + 0.16 * pressure))
                gel_ry = max(8.0, rect.height() * (0.46 + 0.16 * pressure))
                bloom_a = min(
                    205,
                    int(
                        round(
                            (40 * hover_t + 96 * pressure + 42 * overshoot)
                            * max(0.55, op_btn)
                        )
                    ),
                )
                if bloom_a > 3:
                    gel_rg = QRadialGradient(QPointF(gel_cx, gel_cy), gel_rx)
                    gel_rg.setColorAt(
                        0.0,
                        QColor(
                            min(255, ripple_tint.red() + 40),
                            255,
                            255,
                            bloom_a,
                        ),
                    )
                    gel_rg.setColorAt(
                        0.54,
                        QColor(
                            ripple_tint.red(),
                            ripple_tint.green(),
                            ripple_tint.blue(),
                            int(bloom_a * 0.56),
                        ),
                    )
                    gel_rg.setColorAt(1.0, QColor(0, 180, 235, 0))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(gel_rg))
                    painter.drawEllipse(QPointF(gel_cx, gel_cy), gel_rx, gel_ry)

                # Bilateral inflated end-cap cushion blooms when the center is pressed inward
                if pressure > 0.02:
                    lobe_a = min(
                        175,
                        int(round(92 * pressure * eff_scale * max(0.58, op_btn))),
                    )
                    lobe_rx = max(8.0, rect.width() * 0.25)
                    lobe_ry = max(7.0, rect.height() * 0.44)
                    for side_sign in (-1.0, 1.0):
                        side_boost = 1.0 + 0.22 * max(0.0, side_sign * self._press_norm_x)
                        lobe_pt = QPointF(
                            rect.center().x() + side_sign * rect.width() * 0.34,
                            rect.center().y() + rect.height() * 0.04,
                        )
                        lobe_rg = QRadialGradient(lobe_pt, lobe_rx)
                        la = min(210, int(round(lobe_a * side_boost)))
                        lobe_rg.setColorAt(
                            0.0,
                            QColor(
                                min(255, ripple_tint.red() + 50),
                                255,
                                255,
                                la,
                            ),
                        )
                        lobe_rg.setColorAt(
                            0.58,
                            QColor(
                                ripple_tint.red(),
                                ripple_tint.green(),
                                ripple_tint.blue(),
                                la // 2,
                            ),
                        )
                        lobe_rg.setColorAt(1.0, QColor(0, 195, 245, 0))
                        painter.setBrush(QBrush(lobe_rg))
                        painter.drawEllipse(lobe_pt, lobe_rx, lobe_ry)

            # 2b. Lower-Edge Subsurface Gel Pool Glow
            bulge_glow_h = rect.height() * (0.28 + 0.12 * pressure)
            bulge_rect = QRectF(
                rect.left() + 2.0,
                rect.bottom() - bulge_glow_h,
                max(2.0, rect.width() - 4.0),
                bulge_glow_h + 2.0,
            )
            bulge_grad = QLinearGradient(bulge_rect.topLeft(), bulge_rect.bottomLeft())
            bulge_a = min(
                235,
                int(
                    round(
                        (50 + 30 * hover_t + 98 * pressure + 30 * overshoot)
                        * max(0.58, op_btn)
                    )
                ),
            )
            bulge_grad.setColorAt(0.0, QColor(60, 245, 255, 0))
            bulge_grad.setColorAt(
                0.52,
                QColor(
                    ripple_tint.red(),
                    ripple_tint.green(),
                    ripple_tint.blue(),
                    bulge_a // 2,
                ),
            )
            bulge_grad.setColorAt(1.0, QColor(215, 255, 252, bulge_a))
            painter.fillRect(bulge_rect, QBrush(bulge_grad))

            # 2c. Centered Concave Gel Cushion Indentation Well + Luminous Refractive Rim
            if pressure > 0.02 and eff_scale > 0.0:
                press_pt = QPointF(
                    rect.center().x() + self._press_norm_x * rect.width() * 0.22,
                    rect.center().y() + self._press_norm_y * rect.height() * 0.16,
                )
                dep_rx = max(12.0, rect.width() * (0.34 + 0.06 * pressure))
                dep_ry = max(7.5, rect.height() * (0.40 + 0.05 * pressure))
                dep_a = min(118, int(round(78 * pressure * eff_scale)))
                rim_c_a = min(155, int(round(88 * pressure * eff_scale)))
                dep_rg = QRadialGradient(press_pt, dep_rx)
                dep_rg.setColorAt(0.0, QColor(0, 24, 66, dep_a))
                dep_rg.setColorAt(0.52, QColor(0, 46, 102, int(dep_a * 0.44)))
                dep_rg.setColorAt(
                    0.82,
                    QColor(
                        min(255, ripple_tint.red() + 45),
                        255,
                        255,
                        rim_c_a,
                    ),
                )
                dep_rg.setColorAt(1.0, QColor(0, 55, 115, 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(dep_rg))
                painter.drawEllipse(press_pt, dep_rx, dep_ry)

            # -----------------------------------------------------------------
            # 3. High-Contrast, Variant-Tinted Refractive Water Ripples
            # -----------------------------------------------------------------
            ripple_refract_dx = 0.0
            ripple_refract_dy = 0.0
            ripple_arch_bend = 0.0
            active_ripple_energy = 0.0
            if self._ripples and anim_scale > 0.0:
                eff_r = min(1.52, max(0.52, anim_scale))
                max_rad = math.hypot(rect.width(), rect.height()) * 0.98

                for r_state in self._ripples:
                    elapsed = max(0.0, t_sec - r_state.start_sec)
                    p = min(1.0, elapsed / max(0.05, r_state.duration_sec))
                    p_ease = 1.0 - pow(1.0 - p, 2.35)
                    curr_r = max(4.0, max_rad * p_ease)
                    env = (
                        math.sin(math.pi * pow(p, 0.58))
                        * pow(1.0 - p, 0.48)
                        * r_state.strength
                    )
                    active_ripple_energy = max(active_ripple_energy, env)

                    center_pt = QPointF(r_state.origin_x, r_state.origin_y)
                    aspect_y = 0.82

                    # 3a. Click-origin concave depression & rebound droplet flash (p < 0.46)
                    if p < 0.46:
                        imp_u = p / 0.46
                        imp_env = pow(1.0 - imp_u, 1.35) * eff_r * r_state.strength
                        imp_r = max(5.5, min(18.0, rect.height() * (0.20 + 0.42 * imp_u)))
                        imp_rg = QRadialGradient(center_pt, imp_r)
                        imp_a = min(242, int(round(175 * imp_env)))
                        trough_imp_a = min(145, int(round(88 * imp_env)))
                        imp_rg.setColorAt(0.0, QColor(255, 255, 255, imp_a))
                        imp_rg.setColorAt(
                            0.48,
                            QColor(
                                ripple_tint.red(),
                                ripple_tint.green(),
                                ripple_tint.blue(),
                                int(imp_a * 0.72),
                            ),
                        )
                        imp_rg.setColorAt(0.78, QColor(0, 28, 74, trough_imp_a))
                        imp_rg.setColorAt(1.0, QColor(0, 180, 235, 0))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QBrush(imp_rg))
                        painter.drawEllipse(center_pt, imp_r, imp_r * aspect_y)

                    # 3b. Primary Refractive Pressure Wavefront
                    crest_a = min(250, int(round(212 * env * eff_r)))
                    trough_a = min(205, int(round(118 * env * eff_r)))
                    rim_a = min(220, int(round(138 * env * eff_r)))
                    if crest_a > 4:
                        rg1 = QRadialGradient(center_pt, curr_r)
                        rg1.setColorAt(0.0, QColor(255, 255, 255, 0))
                        rg1.setColorAt(0.42, QColor(0, 30, 78, 0))
                        rg1.setColorAt(0.60, QColor(0, 22, 66, trough_a))
                        rg1.setColorAt(0.76, QColor(252, 255, 255, crest_a))
                        rg1.setColorAt(
                            0.88,
                            QColor(
                                ripple_tint.red(),
                                ripple_tint.green(),
                                ripple_tint.blue(),
                                rim_a,
                            ),
                        )
                        rg1.setColorAt(0.96, QColor(0, 26, 72, int(trough_a * 0.68)))
                        rg1.setColorAt(1.0, QColor(255, 255, 255, 0))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QBrush(rg1))
                        painter.drawEllipse(center_pt, curr_r, curr_r * aspect_y)

                        ring_rx = curr_r * 0.77
                        ring_ry = ring_rx * aspect_y
                        ring_grad = QLinearGradient(
                            QPointF(center_pt.x() - ring_rx * 0.7, center_pt.y() - ring_ry),
                            QPointF(center_pt.x() + ring_rx * 0.7, center_pt.y() + ring_ry),
                        )
                        ring_hi_a = min(248, int(round(168 * env * eff_r)))
                        ring_lo_a = min(195, int(round(96 * env * eff_r)))
                        ring_grad.setColorAt(0.0, QColor(255, 255, 255, ring_hi_a))
                        ring_grad.setColorAt(
                            0.55,
                            QColor(
                                ripple_tint.red(),
                                ripple_tint.green(),
                                ripple_tint.blue(),
                                ring_lo_a,
                            ),
                        )
                        ring_grad.setColorAt(1.0, QColor(255, 255, 255, ring_hi_a // 3))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.setPen(QPen(QBrush(ring_grad), 1.55))
                        painter.drawEllipse(center_pt, ring_rx, ring_ry)

                    # 3c. Secondary Trailing Interference Wavelet at 54% radius
                    if 0.06 < p < 0.95:
                        sec_r = max(3.2, curr_r * 0.54)
                        sec_crest_a = min(225, int(round(142 * env * eff_r)))
                        sec_trough_a = min(165, int(round(78 * env * eff_r)))
                        if sec_crest_a > 4:
                            rg2 = QRadialGradient(center_pt, sec_r)
                            rg2.setColorAt(0.0, QColor(255, 255, 255, 0))
                            rg2.setColorAt(0.46, QColor(0, 30, 78, 0))
                            rg2.setColorAt(0.64, QColor(0, 24, 68, sec_trough_a))
                            rg2.setColorAt(0.81, QColor(235, 255, 255, sec_crest_a))
                            rg2.setColorAt(
                                0.93,
                                QColor(
                                    ripple_tint.red(),
                                    ripple_tint.green(),
                                    ripple_tint.blue(),
                                    int(sec_crest_a * 0.65),
                                ),
                            )
                            rg2.setColorAt(1.0, QColor(255, 255, 255, 0))
                            painter.setPen(Qt.PenStyle.NoPen)
                            painter.setBrush(QBrush(rg2))
                            painter.drawEllipse(center_pt, sec_r, sec_r * aspect_y)

                    ripple_refract_dx += (
                        (r_state.origin_x - cx) * 0.14 * env * math.cos(p * 8.6)
                    )
                    ripple_refract_dy += 1.45 * env * math.sin(p * 9.0)
                    ripple_arch_bend += 2.15 * env * math.cos(p * 7.8)

            # -----------------------------------------------------------------
            # 4. Inward-Deforming Upper Specular Shine Cap & Hover Shimmer
            # -----------------------------------------------------------------
            cap_shift_x = (
                self._press_norm_x * 0.65 * pressure
                - self._press_norm_x * 0.25 * overshoot
                + ripple_refract_dx
                if eff_scale > 0.0
                else 0.0
            )
            cap_shift_y = (
                -0.12 * pressure * eff_scale + ripple_refract_dy * 0.35
                if eff_scale > 0.0
                else 0.0
            )
            cap_h_ratio = max(
                0.34, min(0.52, 0.44 - 0.035 * pressure + 0.035 * overshoot)
            )
            cap_inset_x = max(1.4, 2.4 - 0.45 * pressure + 0.30 * overshoot)
            cap_rect = QRectF(
                rect.left() + cap_inset_x + cap_shift_x,
                rect.top() + 1.35 + cap_shift_y,
                max(2.0, rect.width() - 2.0 * cap_inset_x),
                rect.height() * cap_h_ratio,
            )
            cap_r = cap_rect.height() * 0.48

            # Build inward-curved upper specular cap path:
            # Top edge dips gently inward with the upper capsule contour while the lower
            # arch pinches upward across the pressed center like a concave gel lens!
            self._cap_path.clear()
            cl = cap_rect.left()
            cr = cap_rect.right()
            ct = cap_rect.top()
            cb = cap_rect.bottom()
            cw = cap_rect.width()
            top_dip_cap = (
                (pressure * 1.24 - overshoot * 0.65) * eff_scale
                if eff_scale > 0.0
                else 0.0
            )
            arch_pinch = (
                1.85 + (2.65 * pressure - 1.10 * overshoot) * eff_scale + ripple_arch_bend
                if eff_scale > 0.0
                else 1.65
            )
            bias_u_cap = max(0.22, min(0.78, 0.5 + 0.24 * self._press_norm_x))
            if cw > 2.0 * cap_r + 2.0:
                self._cap_path.moveTo(cl + cap_r, ct)
                self._cap_path.cubicTo(
                    cl + cw * (bias_u_cap * 0.58),
                    ct + top_dip_cap,
                    cl + cw * (bias_u_cap + (1.0 - bias_u_cap) * 0.42),
                    ct + top_dip_cap,
                    cr - cap_r,
                    ct,
                )
                self._cap_path.quadTo(cr, ct, cr, ct + cap_r)
                self._cap_path.cubicTo(
                    cl + cw * (0.68 + 0.10 * self._press_norm_x * pressure),
                    cb - arch_pinch,
                    cl + cw * (0.32 + 0.10 * self._press_norm_x * pressure),
                    cb - arch_pinch * 0.85,
                    cl,
                    ct + cap_r,
                )
                self._cap_path.quadTo(cl, ct, cl + cap_r, ct)
                self._cap_path.closeSubpath()
            else:
                self._cap_path.addRoundedRect(cap_rect, cap_r, cap_r)

            cap_grad = QLinearGradient(cap_rect.topLeft(), cap_rect.bottomLeft())
            cap_op = max(0.52, min(1.08, 0.48 + director.opacity_factor * 0.65))
            top_shine_alpha = min(
                254,
                int(round((190 + 50 * hover_t - 18 * pressure + 18 * overshoot) * cap_op)),
            )
            mid_shine_alpha = min(
                152,
                int(round((54 + 34 * hover_t + 36 * pressure) * cap_op)),
            )
            cap_grad.setColorAt(0.0, QColor(255, 255, 255, top_shine_alpha))
            cap_grad.setColorAt(0.74, QColor(235, 252, 255, mid_shine_alpha))
            cap_grad.setColorAt(1.0, QColor(255, 255, 255, 12))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(cap_grad))
            painter.drawPath(self._cap_path)

            # 4b. Staggered Idle Reflection + Traveling Hover Shimmer
            if anim_scale > 0.0:
                eff_s = min(1.48, max(0.45, anim_scale))
                idle_u = (
                    0.5
                    + (0.38 + 0.06 * hover_t)
                    * math.sin(t_sec * (0.58 + 0.35 * hover_t) + self._phase_offset)
                    + 0.18 * self._press_norm_x * pressure
                )
                idle_x = cap_rect.left() + cap_rect.width() * idle_u
                idle_rad = max(14.0, cap_rect.width() * (0.36 + 0.12 * pressure))
                idle_alpha = min(96, int(round((26 + 22 * hover_t + 18 * pressure) * eff_s)))
                idle_rg = QRadialGradient(
                    QPointF(idle_x, cap_rect.top() + cap_rect.height() * 0.36),
                    idle_rad,
                )
                idle_rg.setColorAt(0.0, QColor(255, 255, 255, idle_alpha))
                idle_rg.setColorAt(0.65, QColor(190, 252, 255, idle_alpha // 3))
                idle_rg.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.setBrush(QBrush(idle_rg))
                painter.drawPath(self._cap_path)

                if hover_t > 0.01:
                    hover_atten = max(
                        0.20, 1.0 - 0.72 * max(pressure, active_ripple_energy * 0.85)
                    )
                    sweep_u = (
                        -0.16
                        + 1.32 * self._hover_sweep
                        + 0.04 * math.sin(t_sec * 2.1 + self._phase_offset)
                    )
                    sweep_x = (
                        rect.left()
                        + rect.width() * sweep_u
                        + self._press_norm_x * 2.5 * pressure
                    )
                    sweep_band = max(20.0, rect.width() * 0.33)
                    sweep_grad = QLinearGradient(
                        QPointF(sweep_x - sweep_band, rect.top()),
                        QPointF(sweep_x + sweep_band * 0.85, rect.bottom()),
                    )
                    sw_alpha = min(
                        160,
                        int(round(88 * hover_t * hover_atten * max(0.68, eff_s))),
                    )
                    sweep_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
                    sweep_grad.setColorAt(0.32, QColor(180, 252, 255, sw_alpha // 2))
                    sweep_grad.setColorAt(0.50, QColor(250, 255, 255, sw_alpha))
                    sweep_grad.setColorAt(
                        0.68, QColor(120, 255, 235, int(sw_alpha * 0.55))
                    )
                    sweep_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
                    painter.setBrush(QBrush(sweep_grad))
                    painter.drawPath(self._pill_clip_path)

            # 4c. Inner Concave Gel Meniscus Rim (follows the deformed inward-caving contour!)
            men_rect = rect.adjusted(1.45, 1.40, -1.45, -1.40)
            self._build_deformed_gel_pill_path(
                self._meniscus_path,
                men_rect,
                pressure=pressure * eff_scale,
                overshoot=overshoot * eff_scale,
                press_nx=self._press_norm_x,
                press_ny=self._press_norm_y,
            )
            men_alpha = min(
                210, int(round(78 + 52 * hover_t + 62 * pressure))
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(
                    QColor(
                        min(255, ripple_tint.red() + 45),
                        255,
                        255,
                        men_alpha,
                    ),
                    1.05,
                )
            )
            painter.drawPath(self._meniscus_path)

            painter.restore()  # End pill clip path

            # Subtle dark outer refractive edge under-shadow
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 22, 52, 118), 2.2))
            painter.drawPath(self._pill_clip_path)

            # Outer glossy capsule border (drawn over the deformed pill contour)
            border_pen = QPen(bdr_c, 1.35 + 0.25 * hover_t + 0.20 * pressure)
            painter.setPen(border_pen)
            painter.drawPath(self._pill_clip_path)

            if has_transform:
                painter.restore()

            # 5. Crisp Humanist Sans Text rendered with centered inward cushion recess
            #    (never slides downward toward the bottom edge!)
            if AeroGelButton._LABEL_FONT is None:
                AeroGelButton._LABEL_FONT = QFont("Segoe UI", 9, QFont.Weight.Bold)
            painter.setFont(AeroGelButton._LABEL_FONT)
            text_dx = (
                self._press_norm_x * (pressure * 0.35 - overshoot * 0.14) * eff_scale
                if (abs(strain) > 1e-4 and eff_scale > 0.0)
                else 0.0
            )
            text_dy = (
                self._press_norm_y * (pressure * 0.28 - overshoot * 0.12) * eff_scale
                if (abs(strain) > 1e-4 and eff_scale > 0.0)
                else 0.0
            )
            text_scale = (
                1.0 - 0.025 * pressure * eff_scale + 0.012 * overshoot * eff_scale
                if (abs(strain) > 1e-4 and eff_scale > 0.0)
                else 1.0
            )
            painter.save()
            painter.translate(cx + text_dx, cy + text_dy)
            if abs(text_scale - 1.0) > 1e-4:
                painter.scale(text_scale, text_scale)
            painter.translate(-cx, -cy)
            text_rect = base_rect
            painter.setPen(QColor(0, 18, 42, 165))
            painter.drawText(
                text_rect.translated(0.8, 0.0),
                Qt.AlignmentFlag.AlignCenter,
                self.text(),
            )
            painter.setPen(QColor(0, 22, 48, 225))
            painter.drawText(
                text_rect.translated(0.0, 1.25),
                Qt.AlignmentFlag.AlignCenter,
                self.text(),
            )
            painter.setPen(QColor(255, 255, 255, 254))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text())
            painter.restore()


    class AeroLiquidSlider(QSlider):
        """
        Frutiger Aqua Liquid Glass Horizontal Slider with Phase 3 Tactile Gel Physics:
          - Preserves exact QSlider geometry, range, and signals so async HDR tone-mapping
            and live Glass Transparency updates are never delayed or altered.
          - On press: the 3D glossy aqua orb thumb immediately begins compressing (~7.2%
            vertical squash + ~4.2% horizontal volume-conserving expansion over 52ms OutCubic),
            its upper specular highlight flattens and widens, the active track brightens,
            and the parent toolbar water receives a subtle localized disturbance.
          - During dragging: the thumb tracks the cursor with zero lag while a restrained
            luminous wake trails behind the thumb along the active track.
          - On release: the thumb rebounds with a 340ms C1-continuous underdamped elastic
            spring (including quick-click impulse follow-through), its specular highlight
            settles, and a localized refractive pressure ripple expands around the thumb.
        """

        def __init__(
            self, orientation: Qt.Orientation, parent: Optional[QWidget] = None
        ) -> None:
            super().__init__(orientation, parent)
            self._hovered = False
            self._energy: float = 0.0  # 0.0 = idle, 0.45 = hover, 1.0 = dragging
            self._energy_anim = QVariantAnimation(self)
            self._energy_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._energy_anim.valueChanged.connect(self._on_energy_tick)

            # Thumb jelly compression & elastic rebound state
            self._thumb_strain: float = 0.0
            self._thumb_velocity: float = 0.0
            self._last_thumb_sample_sec: float = 0.0
            self._thumb_rebound_start: float = -1.0
            self._thumb_rebound_vel: float = 0.0
            self._thumb_mode: str = "idle"
            self._thumb_anim = QVariantAnimation(self)
            self._thumb_anim.valueChanged.connect(self._on_thumb_anim_tick)
            self._thumb_anim.finished.connect(self._on_thumb_anim_finished)

            # Short trailing light wake during dragging & release pressure ripples
            self._last_norm_val: float = 0.0
            self._drag_wake_delta: float = 0.0
            self._thumb_ripples: List[WaterRippleState] = []
            self._ripple_timer = QTimer(self)
            self._ripple_timer.setInterval(16)
            self._ripple_timer.timeout.connect(self._on_ripple_tick)

            self.setCursor(Qt.CursorShape.PointingHandCursor)

        def _current_thumb_x(self) -> float:
            w = float(self.width())
            margin_x = 9.0
            groove_w = max(10.0, w - 2.0 * margin_x)
            span = max(1, self.maximum() - self.minimum())
            norm = max(0.0, min(1.0, (self.value() - self.minimum()) / float(span)))
            return margin_x + groove_w * norm

        def _notify_parent_toolbar_water(self, strength: float = 0.24) -> None:
            parent_w = self.parentWidget()
            while parent_w is not None:
                if hasattr(parent_w, "trigger_local_disturbance"):
                    pt = self.mapTo(
                        parent_w,
                        QPoint(int(round(self._current_thumb_x())), self.height() // 2),
                    )
                    parent_w.trigger_local_disturbance(
                        QPointF(float(pt.x()), float(pt.y())), strength=strength
                    )
                    break
                parent_w = parent_w.parentWidget()

        def _spawn_thumb_ripple(self, strength: float = 0.75) -> None:
            director = AeroAnimationDirector.instance()
            if director.scale <= 0.0:
                return
            now = director.elapsed_seconds()
            if len(self._thumb_ripples) >= 3:
                self._thumb_ripples.pop(0)
            self._thumb_ripples.append(
                WaterRippleState(
                    origin_x=self._current_thumb_x(),
                    origin_y=float(self.height()) * 0.5,
                    start_sec=now,
                    duration_sec=0.42,
                    strength=strength,
                )
            )
            if not self._ripple_timer.isActive():
                self._ripple_timer.start()

        def _on_energy_tick(self, value: object) -> None:
            self._energy = float(value)
            self._drag_wake_delta *= 0.88
            self.update()

        def _on_thumb_anim_tick(self, value: object) -> None:
            director = AeroAnimationDirector.instance()
            now = director.elapsed_seconds()
            dt = max(1e-3, now - self._last_thumb_sample_sec)
            prev = self._thumb_strain
            u = float(value)
            if self._thumb_mode == "compress":
                self._thumb_strain = u
            elif self._thumb_mode == "rebound":
                self._thumb_strain = compute_damped_jelly_rebound(
                    u,
                    self._thumb_rebound_start,
                    self._thumb_rebound_vel,
                    director.scale,
                )
            self._thumb_velocity = (self._thumb_strain - prev) / dt
            self._last_thumb_sample_sec = now
            self.update()

        def _on_thumb_anim_finished(self) -> None:
            if self._thumb_mode == "rebound":
                self._thumb_strain = 0.0
                self._thumb_velocity = 0.0
                self._thumb_mode = "idle"
                self._drag_wake_delta = 0.0
                self.update()

        def _on_ripple_tick(self) -> None:
            director = AeroAnimationDirector.instance()
            if director.scale <= 0.0:
                self._thumb_ripples.clear()
                self._ripple_timer.stop()
                self.update()
                return
            now = director.elapsed_seconds()
            self._thumb_ripples = [
                r for r in self._thumb_ripples if (now - r.start_sec) < r.duration_sec
            ]
            if not self._thumb_ripples:
                self._ripple_timer.stop()
            self.update()

        def _animate_energy_to(self, target: float, duration_ms: int) -> None:
            scale = AeroAnimationDirector.instance().scale
            self._energy_anim.stop()
            if scale <= 0.0:
                self._energy = target
                self.update()
            else:
                self._energy_anim.setDuration(duration_ms)
                self._energy_anim.setStartValue(float(self._energy))
                self._energy_anim.setEndValue(float(target))
                self._energy_anim.start()

        def enterEvent(self, event) -> None:
            self._hovered = True
            if not self.isSliderDown():
                self._animate_energy_to(0.45, 220)
            super().enterEvent(event)

        def leaveEvent(self, event) -> None:
            self._hovered = False
            if not self.isSliderDown():
                self._animate_energy_to(0.0, 260)
            super().leaveEvent(event)

        def mousePressEvent(self, event) -> None:
            super().mousePressEvent(event)
            if event.button() == Qt.MouseButton.LeftButton:
                self._animate_energy_to(1.0, 68)
                director = AeroAnimationDirector.instance()
                if director.scale > 0.0:
                    self._last_thumb_sample_sec = director.elapsed_seconds()
                    self._thumb_anim.stop()
                    self._thumb_mode = "compress"
                    start_s = float(self._thumb_strain)
                    if -0.18 < start_s <= 0.08:
                        start_s = min(start_s, -0.22 * min(1.2, max(0.55, director.scale)))
                        self._thumb_strain = start_s
                    self._thumb_velocity = -8.0
                    self._thumb_anim.setDuration(96)
                    self._thumb_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                    self._thumb_anim.setStartValue(start_s)
                    self._thumb_anim.setEndValue(-1.0)
                    self._thumb_anim.start()
                    self._spawn_thumb_ripple(strength=0.68)
                    self._notify_parent_toolbar_water(strength=0.25)
                    self.update()

        def mouseMoveEvent(self, event) -> None:
            prev_val = self.value()
            super().mouseMoveEvent(event)
            span = max(1, self.maximum() - self.minimum())
            delta_norm = (self.value() - prev_val) / float(span)
            if abs(delta_norm) > 1e-4:
                self._drag_wake_delta = max(
                    -0.18, min(0.18, 0.55 * self._drag_wake_delta + delta_norm * 1.35)
                )
                self.update()

        def mouseReleaseEvent(self, event) -> None:
            super().mouseReleaseEvent(event)
            if event.button() == Qt.MouseButton.LeftButton:
                target = 0.45 if self._hovered else 0.0
                self._animate_energy_to(target, 390)
                director = AeroAnimationDirector.instance()
                if director.scale > 0.0:
                    was_comp = self._thumb_mode == "compress"
                    curr_s = float(self._thumb_strain)
                    self._thumb_anim.stop()
                    self._thumb_rebound_start = curr_s
                    if was_comp and curr_s > -0.85:
                        self._thumb_rebound_vel = -6.2 * max(0.28, 1.0 + curr_s)
                    else:
                        self._thumb_rebound_vel = max(
                            -3.0, min(3.0, self._thumb_velocity * 0.14)
                        )
                    self._thumb_mode = "rebound"
                    self._thumb_anim.setDuration(390)
                    self._thumb_anim.setEasingCurve(QEasingCurve.Type.Linear)
                    self._thumb_anim.setStartValue(0.0)
                    self._thumb_anim.setEndValue(1.0)
                    self._thumb_anim.start()
                    self._spawn_thumb_ripple(strength=0.82)
                    self._notify_parent_toolbar_water(strength=0.22)
                else:
                    self._thumb_strain = 0.0
                    self._thumb_mode = "idle"
                    self.update()

        def reset_animation_state(self) -> None:
            """Immediately stops slider thumb/ripple animations and returns thumb to resting shape."""
            self._energy_anim.stop()
            self._thumb_anim.stop()
            self._ripple_timer.stop()
            self._thumb_ripples.clear()
            self._thumb_strain = 0.0
            self._thumb_velocity = 0.0
            self._thumb_mode = "idle"
            self._drag_wake_delta = 0.0
            self._energy = 0.45 if self._hovered else 0.0
            self.update()

        def hideEvent(self, event) -> None:
            self._hovered = False
            self.reset_animation_state()
            super().hideEvent(event)

        def paintEvent(self, event) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            director = AeroAnimationDirector.instance()
            anim_scale = director.scale
            t_sec = director.elapsed_seconds() if anim_scale > 0.0 else 0.0
            energy = (
                self._energy
                if anim_scale > 0.0
                else (
                    1.0
                    if self.isSliderDown()
                    else (0.4 if self._hovered else 0.0)
                )
            )
            strain = (
                self._thumb_strain
                if anim_scale > 0.0
                else (-0.55 if self.isSliderDown() else 0.0)
            )
            pressure = max(0.0, -strain)
            overshoot = max(0.0, strain)
            eff_s = min(1.48, max(0.48, anim_scale)) if anim_scale > 0.0 else 0.0

            w = float(self.width())
            h = float(self.height())
            cy = h * 0.5
            groove_h = 8.0
            margin_x = 9.0
            groove_rect = QRectF(
                margin_x, cy - groove_h * 0.5, max(10.0, w - 2.0 * margin_x), groove_h
            )
            groove_rad = groove_h * 0.5

            # 1. Frosted deep-aqua groove track
            groove_grad = QLinearGradient(
                groove_rect.topLeft(), groove_rect.bottomLeft()
            )
            groove_grad.setColorAt(0.0, QColor(8, 55, 105, 205))
            groove_grad.setColorAt(1.0, QColor(35, 165, 230, 215))
            painter.setPen(QPen(QColor(255, 255, 255, 185), 1.0))
            painter.setBrush(QBrush(groove_grad))
            painter.drawRoundedRect(groove_rect, groove_rad, groove_rad)

            # Calculate normalized value position
            span = max(1, self.maximum() - self.minimum())
            norm = max(0.0, min(1.0, (self.value() - self.minimum()) / float(span)))
            thumb_x = groove_rect.left() + groove_rect.width() * norm

            # 2. Active sub-page liquid track (brightens on press/drag) + short trailing wake
            active_w = max(groove_rad * 2.0, thumb_x - groove_rect.left())
            sub_rect = QRectF(
                groove_rect.left(), groove_rect.top(), active_w, groove_h
            )
            sub_grad = QLinearGradient(sub_rect.topLeft(), sub_rect.topRight())
            c_start = _lerp_color(QColor("#00C6FF"), QColor("#48E5FF"), pressure * 0.50)
            c_mid = _lerp_color(QColor("#00F2FE"), QColor("#A8FFFF"), pressure * 0.55)
            c_end = _lerp_color(QColor("#76FF03"), QColor("#C4FF70"), pressure * 0.50)
            sub_grad.setColorAt(0.0, c_start)
            sub_grad.setColorAt(0.62, c_mid)
            sub_grad.setColorAt(1.0, c_end)
            painter.setPen(QPen(QColor(255, 255, 255, 215 + int(38 * pressure)), 1.0))
            painter.setBrush(QBrush(sub_grad))
            painter.drawRoundedRect(sub_rect, groove_rad, groove_rad)

            # Luminous trail & short drag wake along the active track
            if energy > 0.02 or abs(self._drag_wake_delta) > 1e-3:
                trail_glow_rect = sub_rect.adjusted(-1.0, -1.6, 2.0, 1.6)
                trail_grad = QLinearGradient(
                    trail_glow_rect.topLeft(), trail_glow_rect.topRight()
                )
                trail_a = min(225, int(round((135 * energy + 58 * pressure))))
                shimmer = (
                    0.55 + 0.32 * math.sin(t_sec * 3.0) if anim_scale > 0.0 else 0.72
                )
                trail_grad.setColorAt(0.0, QColor(0, 230, 255, trail_a // 4))
                trail_grad.setColorAt(
                    max(0.1, min(0.9, shimmer)),
                    QColor(215, 255, 255, trail_a),
                )
                trail_grad.setColorAt(1.0, QColor(180, 255, 205, trail_a))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(trail_grad))
                painter.drawRoundedRect(
                    trail_glow_rect, groove_rad + 1.0, groove_rad + 1.0
                )

                # Short localized wake right behind the thumb while dragging
                if abs(self._drag_wake_delta) > 0.002 and anim_scale > 0.0:
                    wake_len = min(
                        30.0,
                        max(8.0, abs(self._drag_wake_delta) * groove_rect.width() * 1.45),
                    )
                    wake_x0 = (
                        thumb_x - wake_len
                        if self._drag_wake_delta > 0
                        else thumb_x
                    )
                    wake_rect = QRectF(
                        wake_x0, cy - groove_h * 0.68, wake_len, groove_h * 1.36
                    )
                    wake_grad = QLinearGradient(
                        QPointF(thumb_x, cy),
                        QPointF(
                            thumb_x - wake_len
                            if self._drag_wake_delta > 0
                            else thumb_x + wake_len,
                            cy,
                        ),
                    )
                    wake_a = min(
                        205,
                        int(round(158 * min(1.0, abs(self._drag_wake_delta) * 12.0))),
                    )
                    wake_grad.setColorAt(0.0, QColor(245, 255, 255, wake_a))
                    wake_grad.setColorAt(1.0, QColor(0, 235, 255, 0))
                    painter.setBrush(QBrush(wake_grad))
                    painter.drawRoundedRect(wake_rect, groove_rad, groove_rad)

            # 2b. Localized refractive pressure ripples on press/release around the thumb
            thumb_center = QPointF(thumb_x, cy + 0.72 * pressure - 0.38 * overshoot)
            if self._thumb_ripples and anim_scale > 0.0:
                for r_state in self._thumb_ripples:
                    elapsed = max(0.0, t_sec - r_state.start_sec)
                    p = min(1.0, elapsed / max(0.05, r_state.duration_sec))
                    p_ease = 1.0 - pow(1.0 - p, 2.3)
                    rad_r = 6.2 + 14.5 * p_ease
                    env = (
                        math.sin(math.pi * pow(p, 0.60))
                        * pow(1.0 - p, 0.50)
                        * r_state.strength
                    )
                    r_pt = QPointF(thumb_x, r_state.origin_y)
                    crest_a = min(220, int(round(155 * env * eff_s)))
                    trough_a = min(155, int(round(82 * env * eff_s)))
                    if crest_a > 3:
                        rg_t = QRadialGradient(r_pt, rad_r)
                        rg_t.setColorAt(0.0, QColor(255, 255, 255, 0))
                        rg_t.setColorAt(0.56, QColor(0, 28, 76, trough_a))
                        rg_t.setColorAt(0.79, QColor(245, 255, 255, crest_a))
                        rg_t.setColorAt(0.92, QColor(90, 248, 255, crest_a // 2))
                        rg_t.setColorAt(1.0, QColor(0, 225, 255, 0))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QBrush(rg_t))
                        painter.drawEllipse(r_pt, rad_r, rad_r * 0.88)

            # 3. 3D Glossy Aqua Gel Orb Thumb with squash/rebound deformation & highlight shift
            base_r = 8.0 + 0.65 * energy
            comp_y = 0.092 * eff_s
            exp_x = 0.052 * eff_s
            thumb_rx = base_r * (1.0 - strain * exp_x)
            thumb_ry = base_r * (1.0 + strain * comp_y)

            if energy > 0.02 or pressure > 0.02:
                halo_rx = thumb_rx + 3.8 * max(energy, pressure)
                halo_ry = thumb_ry + 3.4 * max(energy, pressure)
                halo_grad = QRadialGradient(thumb_center, max(halo_rx, halo_ry))
                halo_grad.setColorAt(
                    0.0,
                    QColor(
                        165,
                        255,
                        255,
                        min(210, int(round(155 * max(energy, pressure)))),
                    ),
                )
                halo_grad.setColorAt(1.0, QColor(0, 225, 255, 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(halo_grad))
                painter.drawEllipse(thumb_center, halo_rx, halo_ry)

            # Shift internal radial gradient focal point when thumb compresses or rebounds
            focal_shift_y = (-0.34 + 0.18 * pressure - 0.10 * overshoot) * thumb_ry
            orb_grad = QRadialGradient(
                thumb_center + QPointF(-thumb_rx * 0.28, focal_shift_y),
                max(thumb_rx, thumb_ry) * 1.38,
            )
            orb_grad.setColorAt(0.0, QColor("#FFFFFF"))
            orb_grad.setColorAt(
                0.42,
                _lerp_color(
                    QColor("#68F0FF"),
                    QColor("#D8FFFF"),
                    min(1.0, energy * 0.50 + pressure * 0.55),
                ),
            )
            orb_grad.setColorAt(
                0.80,
                _lerp_color(QColor("#0088EE"), QColor("#00B4FF"), pressure * 0.48),
            )
            orb_grad.setColorAt(1.0, QColor("#004499"))

            painter.setPen(QPen(QColor("#FFFFFF"), 1.5 + 0.2 * pressure))
            painter.setBrush(QBrush(orb_grad))
            painter.drawEllipse(thumb_center, thumb_rx, thumb_ry)

            # Top glossy specular crescent on the slider thumb (flattens & broadens on press)
            cap_pt = thumb_center + QPointF(
                -thumb_rx * 0.24,
                -thumb_ry * (0.31 - 0.10 * pressure + 0.05 * overshoot),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                QColor(
                    255,
                    255,
                    255,
                    min(255, int(round(224 + 31 * max(energy, pressure)))),
                )
            )
            painter.drawEllipse(
                cap_pt,
                thumb_rx * (0.36 + 0.07 * pressure),
                thumb_ry * (0.25 - 0.05 * pressure),
            )


    class AeroToolbarLabel(QLabel):
        """
        Crisp Frutiger Aqua informational toolbar label (`Glass:`, `80%`, `SDR White:`, `200n`).
        Renders a subtle multi-directional deep-ocean refractive text shadow beneath the
        luminous ice-white glyphs so small labels stay effortlessly readable over both
        bright and dark screenshot backgrounds at 72-95% glass transparency without
        requiring opaque boxes or rectangular masks.
        """

        _FONT: Optional[QFont] = None

        def __init__(
            self,
            text: str = "",
            tint_hex: str = "#FFFFFF",
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(text, parent)
            self._text_color = QColor(tint_hex)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        def paintEvent(self, event) -> None:
            txt = self.text()
            if not txt:
                return
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            if AeroToolbarLabel._FONT is None:
                AeroToolbarLabel._FONT = QFont("Segoe UI", 9, QFont.Weight.Bold)
            painter.setFont(AeroToolbarLabel._FONT)

            pad_left = 4.0 if txt.endswith(":") else 1.0
            rc = QRectF(self.rect()).adjusted(pad_left, 0.0, -1.0, 0.0)
            align = int(self.alignment()) or int(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            )

            # Soft deep-ocean optical halo + crisp lower drop shadow
            painter.setPen(QColor(0, 18, 44, 155))
            for dx, dy in ((-0.85, 0.0), (0.85, 0.0), (0.0, -0.75)):
                painter.drawText(rc.translated(dx, dy), align, txt)
            painter.setPen(QColor(0, 22, 52, 232))
            painter.drawText(rc.translated(0.0, 1.2), align, txt)

            painter.setPen(self._text_color)
            painter.drawText(rc, align, txt)


    class AeroGlassToolbar(QWidget):
        """
        Translucent Frutiger Aqua 3.3 floating toolbar that caches its static frosted-glass
        backdrop and renders a real-time high-resolution aspect-true optical water flow,
        continuous signed-potential Euclidean distance caustics, 1-3 px background refraction
        lensing, dimensional glass reflections, and localized button-interaction water
        disturbances at ~30 FPS.
        Frutiger Aqua 3.3 Refinements:
          - Dynamically adapts its internal optical rendering resolution (`384..544 x 30..38`,
            default `416 x 32`) and physical aspect ratio (`~19.8`) to the actual toolbar
            geometry and display DPI via `_optical_renderer.ensure_geometry(w, h, dpr)`.
          - Automatically tracks the normalized widget geometry of child informational
            `QLabel`s and `AeroLiquidSlider`s (`_readability_zones`), gently attenuating
            bright caustic intersections directly behind text labels and sliders.
          - Caches the composite 30 FPS water frame (`_cached_water_frame`) so 60 FPS child
            button/slider hover, jelly, and ripple repaints blit only the dirty sub-rectangle
            in <0.03 ms without re-running NumPy caustic synthesis between 30 FPS ticks.
          - When Animation Intensity is Off (`scale == 0.0`), renders `_cached_water_frame` once
            and reuses it with zero procedural CPU overhead.
        """

        MAX_DISTURBANCES: int = 4

        def __init__(
            self,
            parent: QWidget,
            backdrop_provider: Callable[[QRect], Optional[QPixmap]],
            parent_patch_provider: Optional[Callable[[QRect], Optional[QPixmap]]] = None,
        ) -> None:
            super().__init__(parent)
            self._backdrop_provider = backdrop_provider
            self._parent_patch_provider = parent_patch_provider
            self._cached_geom: Optional[QRect] = None
            self._cached_frosted: Optional[QPixmap] = None
            self._cached_parent_patch: Optional[QPixmap] = None
            self._cached_static_base: Optional[QPixmap] = None
            self._cached_water_frame: Optional[QPixmap] = None
            self._water_dirty: bool = True
            self._cached_transparency: int = -1
            self._cached_scale: float = -1.0
            self._readability_zones: List[Tuple[float, float, float, float, float]] = []

            # High-resolution aspect-true 2D optical water, caustic & refraction synthesizer
            self._optical_renderer = AquaOpticalFieldRenderer(
                grid_w=416, grid_h=32, aspect=_AQUA3_ASPECT
            )

            # Bounded list of localized water disturbances from nearby button/slider clicks
            self._disturbances: List[ToolbarWaterDisturbance] = []

            # Pre-allocated QPainterPaths for zero-allocation 30 FPS subsurface & reflection rendering
            self._wave_paths = (
                QPainterPath(),
                QPainterPath(),
                QPainterPath(),
                QPainterPath(),
            )

            if parent_patch_provider is not None:
                self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
            else:
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        def trigger_local_disturbance(
            self, local_pt: QPointF, strength: float = 0.35
        ) -> None:
            """
            Registers a spatially localized water disturbance in the toolbar glass around
            a clicked button or pressed slider without creating large global waves.
            """
            director = AeroAnimationDirector.instance()
            if director.scale <= 0.0:
                return
            w = max(1.0, float(self.width()))
            h = max(1.0, float(self.height()))
            u_c = max(0.02, min(0.98, float(local_pt.x()) / w))
            v_c = max(0.05, min(0.95, float(local_pt.y()) / h))
            now = director.elapsed_seconds()

            if len(self._disturbances) >= self.MAX_DISTURBANCES:
                self._disturbances.pop(0)
            self._disturbances.append(
                ToolbarWaterDisturbance(
                    u_center=u_c,
                    v_center=v_c,
                    center_x=float(local_pt.x()),
                    center_y=float(local_pt.y()),
                    start_sec=now,
                    duration_sec=0.62,
                    strength=max(0.10, min(0.55, float(strength))),
                )
            )
            self._water_dirty = True
            self.update()

        def invalidate_backdrop(self) -> None:
            self._cached_geom = None
            self._cached_frosted = None
            self._cached_parent_patch = None
            self._cached_static_base = None
            self._cached_water_frame = None
            self._water_dirty = True
            self.update()

        def on_animation_tick(self) -> None:
            """
            Called by AeroAnimationDirector (~30 FPS) when visible.
            Marks the 30 FPS water composite dirty, schedules a toolbar repaint, and notifies
            visible child AeroGelButtons so their staggered idle reflections update in sync.
            """
            if not self.isVisible():
                return
            self._water_dirty = True
            self.update()
            if AeroAnimationDirector.instance().scale > 0.0:
                for child in self.children():
                    if isinstance(child, AeroGelButton) and child.isVisible():
                        child.update()

        def on_animations_disabled(self) -> None:
            """Immediately stops and resets all toolbar and child control animations when switched to 'Off'."""
            self._disturbances.clear()
            self._water_dirty = True
            for child in self.findChildren(QWidget):
                if hasattr(child, "reset_animation_state"):
                    child.reset_animation_state()
            if self.isVisible():
                self.update()

        def cleanup_resources(self) -> None:
            """Releases all cached pixmaps, backdrop arrays, and active animations when the overlay closes."""
            self._disturbances.clear()
            AeroAnimationDirector.instance().unregister_surface(self)
            for child in self.findChildren(QWidget):
                if hasattr(child, "reset_animation_state"):
                    child.reset_animation_state()
            self._cached_geom = None
            self._cached_frosted = None
            self._cached_parent_patch = None
            self._cached_static_base = None
            self._cached_water_frame = None
            self._water_dirty = True
            self._optical_renderer.clear_backdrop()

        def on_transparency_changed(self) -> None:
            """Rebuilds only the static glass tint composite (reusing cached blur & patch) when transparency slider moves."""
            self._cached_static_base = None
            self._water_dirty = True
            if self.isVisible():
                self.update()
                for child in self.children():
                    if isinstance(child, (AeroGelButton, AeroLiquidSlider)) and child.isVisible():
                        child.update()

        def showEvent(self, event) -> None:
            self._water_dirty = True
            super().showEvent(event)
            director = AeroAnimationDirector.instance()
            director.register_surface(self)
            director.notify_visibility_changed()

        def hideEvent(self, event) -> None:
            self.on_animations_disabled()
            super().hideEvent(event)
            AeroAnimationDirector.instance().notify_visibility_changed()

        def closeEvent(self, event) -> None:
            self.cleanup_resources()
            super().closeEvent(event)

        def _rebuild_static_base_cache(self, geom: QRect) -> None:
            w = max(1, self.width())
            h = max(1, self.height())
            dpr = float(self.devicePixelRatioF()) if hasattr(self, "devicePixelRatioF") else 1.0
            self._optical_renderer.ensure_geometry(w, h, dpr=dpr)

            if self._cached_frosted is None:
                self._cached_frosted = self._backdrop_provider(geom)
            if self._cached_parent_patch is None and self._parent_patch_provider is not None:
                self._cached_parent_patch = self._parent_patch_provider(geom)

            director = AeroAnimationDirector.instance()
            trans_norm = max(0.0, min(1.0, (director.transparency - 10) / 85.0))

            backdrop_pix = QPixmap(w, h)
            backdrop_pix.fill(Qt.GlobalColor.transparent)
            bp = QPainter(backdrop_pix)
            bp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if self._cached_parent_patch is not None and not self._cached_parent_patch.isNull():
                bp.drawPixmap(0, 0, self._cached_parent_patch)
                if self._cached_frosted is not None and not self._cached_frosted.isNull():
                    frost_opacity = max(0.12, min(0.92, 0.85 - 0.58 * trans_norm))
                    bp.save()
                    bp.setOpacity(frost_opacity)
                    bp.drawPixmap(0, 0, self._cached_frosted)
                    bp.restore()
            elif self._cached_frosted is not None and not self._cached_frosted.isNull():
                bp.drawPixmap(0, 0, self._cached_frosted)
            bp.end()
            self._optical_renderer.set_backdrop_qimage(backdrop_pix.toImage())

            base_pix = QPixmap(w, h)
            base_pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(base_pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            if self._cached_parent_patch is not None and not self._cached_parent_patch.isNull():
                p.drawPixmap(0, 0, self._cached_parent_patch)

            rect = QRectF(0.0, 0.0, float(w), float(h)).adjusted(2.0, 2.0, -2.0, -2.0)
            draw_frutiger_glass_base(
                p,
                rect,
                radius=19.0,
                frosted_pixmap=self._cached_frosted,
                tint_style="aqua",
                clear_pixmap=self._cached_parent_patch,
            )
            p.end()
            self._cached_static_base = base_pix
            self._cached_transparency = director.transparency
            self._water_dirty = True

        def _sync_readability_zones(self) -> None:
            """
            Computes normalized [0, 1]^2 soft attenuation zones from actual child QLabel
            and AeroLiquidSlider widget geometries (respecting DPI scaling and layout).
            """
            w = max(1.0, float(self.width()))
            h = max(1.0, float(self.height()))
            zones: List[Tuple[float, float, float, float, float]] = []
            for child in self.children():
                if not isinstance(child, QWidget) or not child.isVisible():
                    continue
                cg = child.geometry()
                if cg.width() <= 2 or cg.height() <= 2:
                    continue
                u0 = max(0.0, min(1.0, float(cg.left()) / w))
                v0 = max(0.0, min(1.0, float(cg.top()) / h))
                u1 = max(0.0, min(1.0, float(cg.right()) / w))
                v1 = max(0.0, min(1.0, float(cg.bottom()) / h))
                if isinstance(child, QLabel):
                    zones.append((u0, v0, u1, v1, 0.45))
                elif isinstance(child, AeroLiquidSlider):
                    zones.append((u0, v0, u1, v1, 0.22))
            self._readability_zones = zones
            self._optical_renderer.set_readability_zones(zones)

        def _rebuild_water_frame_cache(self, director: AeroAnimationDirector) -> None:
            t_caustic_start = time.perf_counter()
            w = max(1, self.width())
            h = max(1, self.height())
            dpr = float(self.devicePixelRatioF()) if hasattr(self, "devicePixelRatioF") else 1.0
            self._optical_renderer.ensure_geometry(w, h, dpr=dpr)

            if (
                self._cached_water_frame is None
                or self._cached_water_frame.size() != self.size()
            ):
                self._cached_water_frame = QPixmap(w, h)
            self._cached_water_frame.fill(Qt.GlobalColor.transparent)

            fp = QPainter(self._cached_water_frame)
            fp.setRenderHint(QPainter.RenderHint.Antialiasing)
            fp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            if self._cached_static_base is not None:
                fp.drawPixmap(0, 0, self._cached_static_base)

            scale = director.scale
            t_sec = director.elapsed_seconds() if scale > 0.0 else 0.0
            optical_qimg: Optional[QImage] = None

            if scale > 0.0:
                self._sync_readability_zones()
                if self._disturbances:
                    self._disturbances = [
                        d
                        for d in self._disturbances
                        if 0.0 <= (t_sec - d.start_sec) < d.duration_sec
                    ]
                rgba_arr = self._optical_renderer.synthesize_rgba_field(
                    t_sec=t_sec,
                    intensity_scale=scale,
                    opacity_factor=director.opacity_factor,
                    disturbances=self._disturbances,
                )
                gh, gw, _ = rgba_arr.shape
                optical_qimg = QImage(
                    rgba_arr.data,
                    gw,
                    gh,
                    gw * 4,
                    QImage.Format.Format_RGBA8888,
                )
            else:
                self._disturbances.clear()

            rect = QRectF(0.0, 0.0, float(w), float(h)).adjusted(2.0, 2.0, -2.0, -2.0)
            draw_frutiger_glass_Dynamic_Overlay(
                fp,
                rect,
                radius=19.0,
                t_sec=t_sec,
                intensity_scale=scale,
                wave_paths=self._wave_paths if scale > 0.0 else None,
                optical_qimage=optical_qimg,
                disturbances=self._disturbances if scale > 0.0 else None,
                readability_zones=self._readability_zones if scale > 0.0 else None,
            )
            fp.end()
            self._cached_scale = scale
            self._water_dirty = False
            if scale > 0.0:
                PERF_TELEMETRY.record_caustic_synth(
                    (time.perf_counter() - t_caustic_start) * 1000.0
                )

        def paintEvent(self, event) -> None:
            t_paint_start = time.perf_counter()
            painter = QPainter(self)

            director = AeroAnimationDirector.instance()
            g = self.geometry()
            if self._cached_geom != g:
                self._cached_geom = QRect(g)
                self._cached_frosted = None
                self._cached_parent_patch = None
                self._cached_static_base = None
                self._water_dirty = True

            if (
                self._cached_static_base is None
                or self._cached_static_base.size() != self.size()
                or self._cached_transparency != director.transparency
            ):
                self._rebuild_static_base_cache(g)

            if (
                self._water_dirty
                or self._cached_water_frame is None
                or self._cached_water_frame.size() != self.size()
                or self._cached_scale != director.scale
            ):
                self._rebuild_water_frame_cache(director)

            if self._cached_water_frame is not None:
                dirty_rc = event.rect()
                painter.drawPixmap(dirty_rc, self._cached_water_frame, dirty_rc)

            PERF_TELEMETRY.record_toolbar_paint(
                (time.perf_counter() - t_paint_start) * 1000.0
            )


# =============================================================================
# 8. ANNOTATIONS & FRUTIGER AERO INTERACTIVE OVERLAY
# =============================================================================

@dataclass
class AnnotationItem:
    tool: str  # "pen", "rect", "ellipse", "line", "arrow", "text"
    color: str
    thickness: int
    points: List[Tuple[float, float]] = field(default_factory=list)
    text: str = ""


_SCREENSHOT_PATH_LOCK = threading.Lock()
_RESERVED_SCREENSHOT_PATHS: set = set()
_ATOMIC_TMP_SEQ: int = 0


def _unique_screenshot_path(save_dir: Path, prefix: str = "HDRSnipFusion") -> Path:
    """
    Generates a collision-proof millisecond filename and reserves it in-memory under
    `_SCREENSHOT_PATH_LOCK` so concurrent or same-millisecond calls never return the
    same path even before the file is flushed to disk.
    """
    if not str(save_dir).strip():
        raise OSError("Configured screenshot save directory path is empty.")
    save_dir = Path(save_dir).expanduser()
    if save_dir.exists() and not save_dir.is_dir():
        raise NotADirectoryError(
            f"Save location '{save_dir}' exists but is a file, not a directory."
        )
    save_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3]
    with _SCREENSHOT_PATH_LOCK:
        if len(_RESERVED_SCREENSHOT_PATHS) > 4096:
            _RESERVED_SCREENSHOT_PATHS.clear()
        counter = 0
        while True:
            name = (
                f"{prefix}_{stamp}.png"
                if counter == 0
                else f"{prefix}_{stamp}_{counter}.png"
            )
            candidate = save_dir / name
            norm_key = os.path.normcase(str(candidate.resolve()))
            if not candidate.exists() and norm_key not in _RESERVED_SCREENSHOT_PATHS:
                _RESERVED_SCREENSHOT_PATHS.add(norm_key)
                return candidate
            counter += 1


def _claim_non_overwriting_destination(preferred_dest: Path) -> Path:
    """
    Atomically claims a destination file path on disk using `os.O_CREAT | os.O_EXCL`
    so two concurrent threads or processes can NEVER overwrite an existing screenshot.
    If `preferred_dest` already exists on disk, increments `_1`, `_2`, ... until an
    exclusive slot is atomically created.
    """
    parent_dir = preferred_dest.parent
    stem = preferred_dest.stem
    suffix = preferred_dest.suffix
    # Strip trailing _<digits> if preferred_dest already had a collision counter from _unique_screenshot_path
    base_stem = stem
    counter = 1
    candidate = preferred_dest
    while True:
        try:
            fd = os.open(
                str(candidate),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o666,
            )
            os.close(fd)
            with _SCREENSHOT_PATH_LOCK:
                _RESERVED_SCREENSHOT_PATHS.add(
                    os.path.normcase(str(candidate.resolve()))
                )
            return candidate
        except FileExistsError:
            candidate = parent_dir / f"{base_stem}_{counter}{suffix}"
            counter += 1


def save_pixmap_or_image_atomically(
    image_obj: Any,
    target_path: Path,
    fmt: Optional[str] = None,
    *,
    allow_overwrite: bool = False,
) -> Path:
    """
    Writes a QPixmap, QImage, PIL.Image, or RGB NumPy array to `target_path` via a
    temporary sibling file in the destination directory and atomically replaces the target.
    When `allow_overwrite=False` (the default for all automatic/hotkey saves), uses
    `os.O_CREAT | os.O_EXCL` reservation via `_claim_non_overwriting_destination()` so
    concurrent or closely spaced saves can NEVER overwrite an existing screenshot file.
    When `allow_overwrite=True` (used only after explicit user confirmation in Save As),
    replaces `target_path` atomically.
    """
    global _ATOMIC_TMP_SEQ
    dest = Path(target_path).expanduser()
    parent_dir = dest.parent
    if not str(parent_dir).strip():
        raise OSError("Target save directory is empty.")
    if parent_dir.exists() and not parent_dir.is_dir():
        raise NotADirectoryError(
            f"Save path parent '{parent_dir}' is not a valid directory."
        )
    parent_dir.mkdir(parents=True, exist_ok=True)

    ext = dest.suffix.lower()
    if fmt is None:
        if ext in (".jpg", ".jpeg"):
            fmt = "JPEG"
        elif ext == ".bmp":
            fmt = "BMP"
        else:
            fmt = "PNG"
            if not ext:
                dest = dest.with_suffix(".png")

    with _SCREENSHOT_PATH_LOCK:
        _ATOMIC_TMP_SEQ += 1
        seq = _ATOMIC_TMP_SEQ

    tmp_name = (
        f".{dest.name}.{os.getpid()}.{threading.get_ident()}."
        f"{time.perf_counter_ns()}.{seq}.tmp"
    )
    tmp_path = parent_dir / tmp_name
    claimed_dest: Optional[Path] = None
    try:
        if HAS_QT and isinstance(image_obj, (QPixmap, QImage)):
            if image_obj.isNull():
                raise RuntimeError("Rendered screenshot image is empty (null QPixmap/QImage).")
            qimg = (
                image_obj.toImage()
                if isinstance(image_obj, QPixmap)
                else image_obj
            )
            ok = qimg.save(str(tmp_path), fmt)
            if not ok:
                with open(tmp_path, "wb") as fh:
                    fh.write(b"")
                raise OSError(
                    f"Qt image encoder failed to write {fmt} image to '{dest}'."
                )
        elif isinstance(image_obj, Image.Image):
            image_obj.save(str(tmp_path), format=fmt)
        elif isinstance(image_obj, np.ndarray):
            pil_img = Image.fromarray(np.ascontiguousarray(image_obj, dtype=np.uint8))
            pil_img.save(str(tmp_path), format=fmt)
        else:
            raise TypeError(f"Unsupported image object type for saving: {type(image_obj)!r}")

        if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
            raise OSError(f"Saved file at '{tmp_path}' was empty or not created on disk.")

        try:
            with open(tmp_path, "r+b") as fh:
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            pass

        if allow_overwrite:
            final_dest = dest
        else:
            claimed_dest = _claim_non_overwriting_destination(dest)
            final_dest = claimed_dest

        os.replace(str(tmp_path), str(final_dest))
        return final_dest
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        if claimed_dest is not None:
            try:
                if claimed_dest.exists() and claimed_dest.stat().st_size == 0:
                    claimed_dest.unlink()
            except OSError:
                pass
        raise


def save_screenshot_to_directory(
    image_obj: Any,
    save_dir_str: str,
    prefix: str = "HDRSnipFusion",
) -> Path:
    """
    Shared one-click screenshot saving implementation used by both ordinary Save (Ctrl+S)
    and Quick Save (Ctrl+Shift+S). Validates the configured folder, generates a unique
    collision-safe PNG filename via `_unique_screenshot_path()`, and writes atomically
    with `allow_overwrite=False` so existing files are never overwritten.
    """
    cleaned = str(save_dir_str or "").strip()
    if not cleaned:
        raise OSError("Default screenshot save location is not configured.")
    if "\x00" in cleaned:
        raise OSError("Default screenshot save location contains invalid characters.")
    save_dir = Path(cleaned).expanduser()
    out_path = _unique_screenshot_path(save_dir, prefix=prefix)
    return save_pixmap_or_image_atomically(
        image_obj, out_path, fmt="PNG", allow_overwrite=False
    )


if HAS_QT:

    class SnipOverlayWindow(QWidget):
        """
        Frutiger Aero / Aqua Glass frozen screen overlay:
          - Freezes the already-captured HDR-tone-mapped frame
          - Glowing fiber-optic Aqua selection frame with 8 3D Water-Droplet / Pearl resize orbs
          - Frosted Acrylic dimensions capsule with glowing status orb & top specular shine
          - Frosted Acrylic floating toolbar with living water, 3D Gel Pill buttons & glossy Aqua slider
          - Copy to Clipboard (Ctrl+C / Enter), Save As (Ctrl+S), or Quick-Save (Ctrl+Shift+S)
        """

        HANDLE_SIZE = 12  # 3D glossy water-droplet orb diameter
        BORDER_GRAB_MARGIN = 6.0
        overlay_closed = pyqtSignal(object)

        HANDLE_CURSORS = [
            Qt.CursorShape.SizeFDiagCursor,
            Qt.CursorShape.SizeVerCursor,
            Qt.CursorShape.SizeBDiagCursor,
            Qt.CursorShape.SizeHorCursor,
            Qt.CursorShape.SizeFDiagCursor,
            Qt.CursorShape.SizeVerCursor,
            Qt.CursorShape.SizeBDiagCursor,
            Qt.CursorShape.SizeHorCursor,
        ]

        def __init__(
            self,
            frame: CapturedFrame,
            config: AppConfig,
            t_trigger_start: Optional[float] = None,
        ) -> None:
            super().__init__(None)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            _LIVE_OVERLAY_INSTANCES.add(self)
            self.frame = frame
            self.config = config
            self._t_trigger_start = (
                float(t_trigger_start)
                if t_trigger_start is not None
                else time.perf_counter()
            )
            self._first_paint_recorded = False
            self._initial_render_running = False

            # Sync global animation director with user's configured intensity, transparency & Safe Mode flags
            director = AeroAnimationDirector.instance()
            director.apply_config_flags(config)

            # Use FramelessWindowHint | WindowStaysOnTopHint | Tool (without BypassWindowManagerHint)
            # so Qt's QWindowsWindow properly binds per-monitor DPI and target QScreen geometry.
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setMouseTracking(True)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

            self.current_white_scale = frame.detected_white_scale
            self._rebuild_pixmap()

            qt_screens = QGuiApplication.screens()
            if DEBUG_MONITORS:
                qt_list_str = ", ".join(
                    f"name='{s.name()}' geom=({s.geometry().x()},{s.geometry().y()} "
                    f"{s.geometry().width()}x{s.geometry().height()}) dpr={s.devicePixelRatio():.2f}"
                    for s in qt_screens
                )
                _debug_monitor_log(f"Available Qt screens ({len(qt_screens)}): [{qt_list_str}]")

            target_screen, screen_match_reason = resolve_qt_screen_for_frame(
                frame, qt_screens
            )
            self.target_screen = target_screen
            self._screen_match_reason = screen_match_reason

            # Associate widget & native QWindow with target_screen BEFORE setting geometry
            try:
                self.setScreen(target_screen)
            except Exception:
                pass
            _ = self.winId()
            if self.windowHandle() is not None:
                try:
                    self.windowHandle().setScreen(target_screen)
                except Exception:
                    pass

            scr_geom = target_screen.geometry()
            self.setGeometry(scr_geom)
            if self.windowHandle() is not None:
                try:
                    self.windowHandle().setGeometry(scr_geom)
                except Exception:
                    pass

            px, py, pw, ph = frame.virtual_rect
            self.coord_mapper = DisplayCoordinateMapper(
                phys_x=px,
                phys_y=py,
                phys_w=pw,
                phys_h=ph,
                logical_x=scr_geom.x(),
                logical_y=scr_geom.y(),
                logical_w=scr_geom.width(),
                logical_h=scr_geom.height(),
                overlay_w=max(1, self.width()),
                overlay_h=max(1, self.height()),
                image_w=int(frame.full_width),
                image_h=int(frame.full_height),
                qt_dpr=float(target_screen.devicePixelRatio()),
                win32_dpi_scale=float(frame.monitor_dpi_scale),
            )
            self._px_scale_x = self.coord_mapper.px_scale_x
            self._px_scale_y = self.coord_mapper.px_scale_y

            cur_phys = frame.cursor_physical or get_physical_cursor_pos()
            init_lx, init_ly = self.coord_mapper.physical_global_to_local_logical(
                cur_phys[0], cur_phys[1]
            )
            self.initial_cursor_local = QPointF(init_lx, init_ly)

            # Async background tone-mapping state for smooth 4K slider dragging
            self._render_signals = ToneRenderSignals()
            self._render_signals.done.connect(self._on_tone_render_ready)
            self._tone_pool = QThreadPool.globalInstance()
            self._render_revision = 0
            self._render_running = False
            self._pending_tone_request = None
            self._display_is_preview = False
            self._last_full_scale = frame.detected_white_scale
            self._closed = False
            self._resources_released = False
            self._cancel_tone_event = threading.Event()
            self._render_debounce = QTimer(self)
            self._render_debounce.setSingleShot(True)
            self._render_debounce.setInterval(90)
            self._render_debounce.timeout.connect(self._request_tone_render)

            # Selection state
            self.selection_rect: QRectF = QRectF()
            self.has_selection = False
            self.interaction_mode: str = "none"  # "creating", "moving", "resizing", "drawing"
            self.active_handle: int = -1
            self.drag_start_pos: QPointF = QPointF()
            self.rect_at_drag_start: QRectF = QRectF()
            self.space_held: bool = False

            # Cached frosted backdrop for top-left dimensions badge
            self._badge_cached_rect: Optional[QRect] = None
            self._badge_frosted_pix: Optional[QPixmap] = None

            # Tool state ("move", "pen", "rect", "ellipse", "line", "arrow", "text")
            self.active_tool: str = "move"
            self.stroke_color: QColor = QColor(config.default_color)
            self.stroke_width: int = config.default_thickness
            self.annotations: List[AnnotationItem] = []
            self.redo_stack: List[AnnotationItem] = []
            self.current_annotation: Optional[AnnotationItem] = None

            self._build_floating_toolbar()
            self.setCursor(Qt.CursorShape.CrossCursor)

            if getattr(self.frame, "is_preview", False) and self.frame.raw_scrgb_float is not None:
                self._start_initial_full_render()

        def _sync_coordinate_scales(self) -> None:
            """Keeps DisplayCoordinateMapper and _px_scale_x/_px_scale_y synchronized with widget size."""
            fw = getattr(self.frame, "full_width", self.frame.srgb_image.shape[1])
            fh = getattr(self.frame, "full_height", self.frame.srgb_image.shape[0])
            if hasattr(self, "coord_mapper"):
                self.coord_mapper.image_w = int(fw)
                self.coord_mapper.image_h = int(fh)
                self.coord_mapper.update_overlay_size(
                    max(1, self.width()), max(1, self.height())
                )
                self._px_scale_x = self.coord_mapper.px_scale_x
                self._px_scale_y = self.coord_mapper.px_scale_y
            else:
                self._px_scale_x = float(fw) / max(1.0, float(self.width()))
                self._px_scale_y = float(fh) / max(1.0, float(self.height()))

        def show_on_target_screen(self) -> None:
            """
            Shows the overlay on the resolved target QScreen and verifies that the native
            Win32 HWND is placed on the exact physical monitor bounds without minimizing games.
            """
            if self.target_screen is not None:
                try:
                    self.setScreen(self.target_screen)
                except Exception:
                    pass
                if self.windowHandle() is not None:
                    try:
                        self.windowHandle().setScreen(self.target_screen)
                        self.windowHandle().setGeometry(self.target_screen.geometry())
                    except Exception:
                        pass
                self.setGeometry(self.target_screen.geometry())

            self.show()

            # Verify native Win32 HWND physical placement on multi-monitor / mixed-DPI desktops
            if sys.platform == "win32":
                try:
                    hwnd = int(self.winId())
                    if hwnd:
                        user32 = ctypes.windll.user32
                        win_rc = wintypes.RECT()
                        px, py, pw, ph = self.frame.virtual_rect
                        if user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(win_rc)):
                            actual_w = win_rc.right - win_rc.left
                            actual_h = win_rc.bottom - win_rc.top
                            if (
                                abs(win_rc.left - px) > 4
                                or abs(win_rc.top - py) > 4
                                or abs(actual_w - pw) > 4
                                or abs(actual_h - ph) > 4
                            ):
                                HWND_TOPMOST = -1
                                SWP_NOACTIVATE = 0x0010
                                SWP_NOOWNERZORDER = 0x0200
                                SWP_SHOWWINDOW = 0x0040
                                user32.SetWindowPos(
                                    wintypes.HWND(hwnd),
                                    wintypes.HWND(HWND_TOPMOST),
                                    int(px),
                                    int(py),
                                    int(pw),
                                    int(ph),
                                    SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW,
                                )
                except Exception as exc:
                    _debug_monitor_log(f"Native HWND placement check note: {exc}")

            self._sync_coordinate_scales()
            self.raise_()
            self.activateWindow()
            self.setFocus()

            if DEBUG_MONITORS:
                cur_phys = get_physical_cursor_pos()
                rel_x, rel_y = self.coord_mapper.physical_global_to_local_logical(
                    cur_phys[0], cur_phys[1]
                )
                g = self.geometry()
                _debug_monitor_log(
                    f"Target QScreen='{self.target_screen.name()}' (reason='{self._screen_match_reason}', "
                    f"dpr={self.target_screen.devicePixelRatio():.2f}), "
                    f"final_overlay_geometry=({g.x()},{g.y()} {g.width()}x{g.height()}), "
                    f"scale=({self._px_scale_x:.4f}, {self._px_scale_y:.4f}), "
                    f"cursor_local=({rel_x:.1f}, {rel_y:.1f})"
                )

        def resizeEvent(self, event) -> None:
            super().resizeEvent(event)
            self._sync_coordinate_scales()
            self._badge_cached_rect = None
            if hasattr(self, "toolbar"):
                self.toolbar.invalidate_backdrop()

        def _sample_frosted_region(self, logical_rect: QRect) -> Optional[QPixmap]:
            """Samples physical pixels from the captured screenshot and returns a blurred acrylic QPixmap."""
            if self.config.is_safe_mode_active:
                return None
            self._sync_coordinate_scales()
            px_x, px_y, px_w, px_h = self.coord_mapper.local_rect_to_image_crop_rect(
                (
                    float(logical_rect.x()),
                    float(logical_rect.y()),
                    float(logical_rect.width()),
                    float(logical_rect.height()),
                )
            )
            px_w = max(8, px_w)
            px_h = max(8, px_h)
            sample_buf = self.frame.srgb_image
            if (
                getattr(self.frame, "is_preview", False)
                and getattr(self.frame, "preview_stride", 1) > 1
            ):
                st = self.frame.preview_stride
                px_x = px_x // st
                px_y = px_y // st
                px_w = max(4, px_w // st)
                px_h = max(4, px_h // st)
            return make_frosted_acrylic_pixmap(
                sample_buf, px_x, px_y, px_w, px_h, blur_radius=14
            )

        def _sample_parent_patch(self, logical_rect: QRect) -> Optional[QPixmap]:
            """
            Renders the exact static overlay background behind `logical_rect` once into a small
            QPixmap so AeroGlassToolbar can paint opaquely without ever triggering a fullscreen
            SnipOverlayWindow repaint during 30 FPS water/button animations.
            """
            w = max(1, logical_rect.width())
            h = max(1, logical_rect.height())
            patch = QPixmap(w, h)
            patch.fill(Qt.GlobalColor.black)
            p = QPainter(patch)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.translate(-logical_rect.x(), -logical_rect.y())

            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(self.rect(), self.bg_pixmap)

            overlay_path = QPainterPath()
            overlay_path.addRect(QRectF(logical_rect))
            if self.has_selection:
                sel_path = QPainterPath()
                sel_path.addRect(self.selection_rect.normalized())
                overlay_path = overlay_path.subtracted(sel_path)
            p.fillPath(overlay_path, QColor(4, 22, 42, 138))

            self._draw_all_annotations(p)
            p.end()
            return patch

        def _rebuild_pixmap(self, buffer: Optional[np.ndarray] = None) -> None:
            """Creates the Qt QPixmap on the GUI thread from a contiguous RGB uint8 buffer."""
            t_pix_start = time.perf_counter()
            img_arr = np.ascontiguousarray(
                self.frame.srgb_image if buffer is None else buffer, dtype=np.uint8
            )
            h, w, _ = img_arr.shape
            bytes_per_line = 3 * w
            qimg = QImage(
                img_arr.data, w, h, bytes_per_line, QImage.Format.Format_RGB888
            ).copy()
            self.bg_pixmap = QPixmap.fromImage(qimg)
            self._badge_cached_rect = None
            if hasattr(self, "toolbar"):
                self.toolbar.invalidate_backdrop()
            PERF_TELEMETRY.record_stage("pixmap_creation", (time.perf_counter() - t_pix_start) * 1000.0)

        def _build_floating_toolbar(self) -> None:
            self.toolbar = AeroGlassToolbar(
                self, self._sample_frosted_region, self._sample_parent_patch
            )
            self.toolbar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.toolbar.setStyleSheet(
                """
                QLabel {
                    color: #FFFFFF;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 12px;
                    font-weight: bold;
                    background: transparent;
                }
                """
            )
            layout = QHBoxLayout(self.toolbar)
            layout.setContentsMargins(12, 7, 12, 7)
            layout.setSpacing(6)

            self.tool_buttons = {}
            tools = [
                ("move", "Move (V)"),
                ("pen", "Pen (P)"),
                ("rect", "Rect (R)"),
                ("ellipse", "Circle (E)"),
                ("line", "Line (L)"),
                ("arrow", "Arrow (A)"),
                ("text", "Text (T)"),
            ]
            for tool_id, label in tools:
                btn = AeroGelButton(label, variant="glass", parent=self.toolbar)
                btn.setToolTip(
                    f"{label} • Hold Shift for square/circle/45° snap • Hold Space to move box"
                )
                btn.setCheckable(True)
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                btn.setChecked(tool_id == self.active_tool)
                btn.clicked.connect(lambda checked, t=tool_id: self.set_tool(t))
                layout.addWidget(btn)
                self.tool_buttons[tool_id] = btn

            layout.addSpacing(3)

            # Color swatch gel button
            self.color_btn = AeroGelButton(
                "Color",
                variant="glass",
                custom_swatch=self.stroke_color,
                parent=self.toolbar,
            )
            self.color_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.color_btn.clicked.connect(self.pick_color)
            layout.addWidget(self.color_btn)

            # Live HDR SDR-White exposure slider if captured from an HDR surface
            # (Note: Glass Transparency is now configured cleanly inside SettingsDialog)
            if self.frame.raw_scrgb_float is not None:
                layout.addSpacing(6)
                hdr_lbl = AeroToolbarLabel(
                    "SDR White:", tint_hex="#E4FFFF", parent=self.toolbar
                )
                hdr_lbl.setMinimumWidth(72)
                layout.addWidget(hdr_lbl)

                self.hdr_slider = AeroLiquidSlider(
                    Qt.Orientation.Horizontal, self.toolbar
                )
                self.hdr_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self.hdr_slider.setRange(80, 1000)
                self.hdr_slider.setFixedWidth(112)
                self.hdr_slider.setValue(int(round(self.current_white_scale * 80.0)))
                self.hdr_slider.setToolTip(
                    "Live SDR paper-white level (nits) for this capture. Exports always use full resolution."
                )
                self.hdr_slider.valueChanged.connect(self._on_hdr_slider_changed)
                self.hdr_slider.sliderReleased.connect(self._on_hdr_slider_released)
                layout.addWidget(self.hdr_slider)

                self.nits_value_label = AeroToolbarLabel(
                    f"{self.hdr_slider.value()}n", tint_hex="#FFFFFF", parent=self.toolbar
                )
                self.nits_value_label.setFixedWidth(42)
                layout.addWidget(self.nits_value_label)

            layout.addSpacing(6)

            # Undo
            undo_btn = AeroGelButton("Undo", variant="glass", parent=self.toolbar)
            undo_btn.setToolTip(
                "Undo (Ctrl+Z) • Redo (Ctrl+Y) • Scroll wheel adjusts stroke thickness"
            )
            undo_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            undo_btn.clicked.connect(self.undo_annotation)
            layout.addWidget(undo_btn)

            # Save (Frutiger Emerald Gel Pill)
            self.save_btn = AeroGelButton("Save", variant="emerald", parent=self.toolbar)
            self.save_btn.setToolTip(
                "Save to default folder (Ctrl+S) • Quick Save + Copy (Ctrl+Shift+S) • Save As... (Ctrl+Alt+S)"
            )
            self.save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.save_btn.clicked.connect(self.save_snip)
            layout.addWidget(self.save_btn)

            # Copy (Frutiger Sapphire Gel Pill)
            copy_btn = AeroGelButton("Copy", variant="sapphire", parent=self.toolbar)
            copy_btn.setToolTip("Copy to clipboard (Ctrl+C or Enter)")
            copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            copy_btn.clicked.connect(self.copy_snip)
            layout.addWidget(copy_btn)

            # Close (Vista Ruby Glass Orb)
            close_btn = AeroGelButton("✕", variant="ruby", parent=self.toolbar)
            close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            close_btn.clicked.connect(self.close)
            layout.addWidget(close_btn)

            self.toolbar.adjustSize()
            self.toolbar.hide()

        def set_tool(self, tool_id: str) -> None:
            self.active_tool = tool_id
            for tid, btn in self.tool_buttons.items():
                btn.setChecked(tid == tool_id)
                btn.update()
            self.setFocus()

        def pick_color(self) -> None:
            col = QColorDialog.getColor(
                self.stroke_color, self, "Choose Annotation Color"
            )
            if col.isValid():
                self.stroke_color = col
                self.config.default_color = col.name()
                self.config.save()
                self.color_btn.set_swatch_color(col)
            self.setFocus()

        def _on_hdr_slider_changed(self, nits: int) -> None:
            if self.frame.raw_scrgb_float is None:
                return
            self.current_white_scale = max(nits / 80.0, 0.5)
            self.nits_value_label.setText(f"{nits}n")
            self._render_revision += 1
            self._render_debounce.start()
            if self._badge_cached_rect is not None:
                self.update(self._badge_cached_rect.adjusted(-4, -4, 4, 4))

        def _on_hdr_slider_released(self) -> None:
            self._render_debounce.stop()
            self._request_tone_render(full=True)

        def _request_tone_render(self, full: Optional[bool] = None) -> None:
            if self._closed or self.frame.raw_scrgb_float is None:
                return
            if full is None:
                full = not self.hdr_slider.isSliderDown()
            # When Diagnostic Safe Mode or `disable_async_tone_workers` is enabled,
            # perform tone-mapping synchronously on the GUI thread without spawning QThreadPool jobs.
            if self.config.effective_async_workers_disabled:
                pixels = (
                    self.frame.raw_scrgb_float
                    if full
                    else self.frame.raw_scrgb_float[::2, ::2, :]
                )
                rgb = tone_map_scrgb_to_srgb(
                    pixels,
                    white_scale=self.current_white_scale,
                    mode=self.config.tone_map_mode,
                    knee_start=self.config.knee_start,
                    max_headroom=self.config.max_headroom,
                    auto_hdr_gamma22_fix=self.config.auto_hdr_gamma22_fix,
                    boost_sdr_whites=self.config.boost_sdr_whites,
                )
                self._display_is_preview = not bool(full)
                if full:
                    self.frame.srgb_image = rgb
                    self._last_full_scale = self.current_white_scale
                self._rebuild_pixmap(rgb)
                self.update()
                return
            request = (self._render_revision, self.current_white_scale, bool(full))
            if self._render_running:
                self._pending_tone_request = request
            else:
                self._start_tone_job(request)

        def _start_tone_job(self, request: Tuple[int, float, bool]) -> None:
            if self._closed or self.frame.raw_scrgb_float is None:
                return
            revision, white_scale, full = request
            self._render_running = True
            job = ToneRenderJob(
                self._render_signals,
                self.frame.raw_scrgb_float,
                revision,
                white_scale,
                full,
                self.config.tone_map_mode,
                self.config.knee_start,
                self.config.max_headroom,
                self.config.auto_hdr_gamma22_fix,
                self.config.boost_sdr_whites,
                cancel_event=self._cancel_tone_event,
            )
            self._tone_pool.start(job)

        def _on_tone_render_ready(
            self,
            revision: int,
            rgb: Optional[np.ndarray],
            full: bool,
            white_scale: float,
        ) -> None:
            self._render_running = False
            if self._closed:
                self._pending_tone_request = None
                try:
                    self._render_signals.done.disconnect(self._on_tone_render_ready)
                except Exception:
                    pass
                # Now that the background worker has finished reading raw_scrgb_float,
                # safely release any deferred screenshot buffers.
                freed = self.frame.release_buffers()
                DIAG_LOG.milestone(
                    "OVERLAY_CLOSE_DEFERRED",
                    f"Deferred tone worker completed; released {freed / (1024 * 1024):.2f} MB",
                )
                return
            pending = self._pending_tone_request
            self._pending_tone_request = None
            if pending is not None:
                self._start_tone_job(pending)
            if rgb is None:
                return
            if revision == self._render_revision:
                self._display_is_preview = not full
                if full:
                    self.frame.srgb_image = rgb
                    self._last_full_scale = white_scale
                self._rebuild_pixmap(rgb)
                self.update()

        def _start_initial_full_render(self) -> None:
            if self._closed or self.frame.raw_scrgb_float is None:
                return
            if self.config.effective_async_workers_disabled:
                self._ensure_full_resolution_export()
                return

            self._initial_render_running = True
            self._initial_render_signals = InitialFullToneRenderSignals()
            self._initial_render_signals.done.connect(self._on_initial_full_tone_ready)
            job = InitialFullToneRenderJob(
                self._initial_render_signals,
                self.frame.raw_scrgb_float,
                self.current_white_scale,
                self.config.tone_map_mode,
                self.config.knee_start,
                self.config.max_headroom,
                self.config.auto_hdr_gamma22_fix,
                self.config.boost_sdr_whites,
                cancel_event=self._cancel_tone_event,
            )
            self._tone_pool.start(job)

        def _on_initial_full_tone_ready(self, full_rgb: Optional[np.ndarray]) -> None:
            self._initial_render_running = False
            if self._closed:
                try:
                    if hasattr(self, "_initial_render_signals"):
                        self._initial_render_signals.done.disconnect(self._on_initial_full_tone_ready)
                except Exception:
                    pass
                if not self._render_running:
                    freed = self.frame.release_buffers()
                    DIAG_LOG.milestone(
                        "OVERLAY_CLOSE_DEFERRED",
                        f"Deferred initial tone worker completed; released {freed / (1024 * 1024):.2f} MB",
                    )
                return
            if full_rgb is None:
                return
            if abs(self.current_white_scale - self.frame.detected_white_scale) < 1e-4:
                self.frame.srgb_image = full_rgb
                self.frame.is_preview = False
                self._display_is_preview = False
                self._rebuild_pixmap(full_rgb)
                self._badge_cached_rect = None
                if hasattr(self, "toolbar") and self.toolbar is not None:
                    self.toolbar.invalidate_backdrop()
                self.update()
                DIAG_LOG.log(
                    "OVERLAY",
                    "Seamlessly promoted screenshot overlay from fast preview to full-resolution image",
                )

        def _log_latency_breakdown(self) -> None:
            snap = PERF_TELEMETRY
            lines = [
                f"Latency Breakdown (Hotkey to First Visible Paint: {snap.last_time_to_first_paint_ms:.1f} ms):",
                f"  1. Hotkey -> Qt Handler:        {snap.last_hotkey_to_handler_ms:6.1f} ms",
                f"  2. Monitor & DXGI Enum:         {snap.last_monitor_enum_ms:6.1f} ms",
                f"  3. D3D11 Device & Dupl Init:    {snap.last_d3d_device_init_ms:6.1f} ms",
                f"  4. AcquireNextFrame Wait:       {snap.last_acquire_frame_ms:6.1f} ms",
                f"  5. GPU->CPU Texture Readback:   {snap.last_texture_readback_ms:6.1f} ms",
                f"  6. Fast Preview Tone Mapping:   {snap.last_tone_mapping_ms:6.1f} ms",
                f"  7. QImage / QPixmap Creation:   {snap.last_pixmap_creation_ms:6.1f} ms",
                f"  8. Overlay Window Init:         {snap.last_overlay_init_ms:6.1f} ms",
                f"  9. Time to First Visible Paint: {snap.last_time_to_first_paint_ms:6.1f} ms",
            ]
            msg = chr(10).join(lines)
            DIAG_LOG.milestone("LATENCY_BREAKDOWN", msg, flush_disk=False)
            _debug_perf_log(msg)

        def _ensure_full_resolution_export(self) -> None:
            """Guarantees clipboard/saved output always uses full-resolution tone-mapped pixels."""
            if self.frame.raw_scrgb_float is None:
                return
            if (
                getattr(self.frame, "is_preview", False)
                or self._display_is_preview
                or abs(self._last_full_scale - self.current_white_scale) > 1e-5
            ):
                t0 = time.perf_counter()
                rgb = tone_map_scrgb_to_srgb(
                    self.frame.raw_scrgb_float,
                    white_scale=self.current_white_scale,
                    mode=self.config.tone_map_mode,
                    knee_start=self.config.knee_start,
                    max_headroom=self.config.max_headroom,
                    auto_hdr_gamma22_fix=self.config.auto_hdr_gamma22_fix,
                    boost_sdr_whites=self.config.boost_sdr_whites,
                )
                self.frame.srgb_image = rgb
                self.frame.is_preview = False
                self._last_full_scale = self.current_white_scale
                self._display_is_preview = False
                self._rebuild_pixmap(rgb)
                DIAG_LOG.log(
                    "EXPORT",
                    f"Full-resolution tone-map ensured for export in {(time.perf_counter() - t0)*1000:.1f} ms",
                )

        def undo_annotation(self) -> None:
            if self.annotations:
                self.redo_stack.append(self.annotations.pop())
                self.toolbar.invalidate_backdrop()
                self.update()

        def _get_handle_rects(self, r: QRectF) -> List[QRectF]:
            s = self.HANDLE_SIZE
            hs = s / 2.0
            cx = r.center().x()
            cy = r.center().y()
            pts = [
                (r.left(), r.top()),
                (cx, r.top()),
                (r.right(), r.top()),
                (r.right(), cy),
                (r.right(), r.bottom()),
                (cx, r.bottom()),
                (r.left(), r.bottom()),
                (r.left(), cy),
            ]
            return [QRectF(px - hs, py - hs, s, s) for px, py in pts]

        def _hit_test_handles(self, pos: QPointF) -> int:
            if not self.has_selection:
                return -1
            for idx, hrect in enumerate(
                self._get_handle_rects(self.selection_rect.normalized())
            ):
                if hrect.adjusted(-5, -5, 5, 5).contains(pos):
                    return idx
            return -1

        def _hit_test_border(self, pos: QPointF) -> bool:
            """Allows dragging the selection border itself to move the box even when a drawing tool is active."""
            if not self.has_selection:
                return False
            r = self.selection_rect.normalized()
            m = self.BORDER_GRAB_MARGIN
            outer = r.adjusted(-m, -m, m, m)
            inner = r.adjusted(m, m, -m, -m)
            return outer.contains(pos) and not inner.contains(pos)

        @staticmethod
        def _apply_shift_constraint(
            tool: str, start: Tuple[float, float], end: Tuple[float, float]
        ) -> Tuple[float, float]:
            """Locks Rect/Ellipse to 1:1 aspect ratio and Line/Arrow to 45° increments when Shift is held."""
            x0, y0 = start
            dx = end[0] - x0
            dy = end[1] - y0
            if tool in ("rect", "ellipse"):
                side = max(abs(dx), abs(dy))
                sx = 1.0 if dx >= 0 else -1.0
                sy = 1.0 if dy >= 0 else -1.0
                return (x0 + sx * side, y0 + sy * side)
            elif tool in ("line", "arrow"):
                dist = math.hypot(dx, dy)
                if dist < 1e-4:
                    return end
                angle = math.atan2(dy, dx)
                snapped = round(angle / (math.pi / 4.0)) * (math.pi / 4.0)
                return (x0 + dist * math.cos(snapped), y0 + dist * math.sin(snapped))
            return end

        def _reposition_toolbar(self) -> None:
            if not self.has_selection or self.selection_rect.width() < 10:
                self.toolbar.hide()
                return
            r = self.selection_rect.normalized()
            tb_w = self.toolbar.width()
            tb_h = self.toolbar.height()

            tx = int(r.right() - tb_w)
            if tx < 10:
                tx = int(r.left())
            if tx + tb_w > self.width() - 10:
                tx = self.width() - tb_w - 10

            ty = int(r.bottom() + 12)
            if ty + tb_h > self.height() - 10:
                ty = int(r.top() - tb_h - 12)
                if ty < 10:
                    ty = int(r.bottom() - tb_h - 12)

            new_pos = QPoint(max(10, tx), max(10, ty))
            if self.toolbar.pos() != new_pos:
                self.toolbar.move(new_pos)
            self.toolbar.invalidate_backdrop()
            self.toolbar.show()
            self.toolbar.raise_()

        # ---------------------------------------------------------------------
        # Painting (Frozen Image + Deep Aqua Dim Mask + Aero Frame & Orbs)
        # ---------------------------------------------------------------------
        def paintEvent(self, event) -> None:
            if not self._first_paint_recorded:
                self._first_paint_recorded = True
                t_first_paint = (time.perf_counter() - self._t_trigger_start) * 1000.0
                PERF_TELEMETRY.record_stage("first_visible_paint", t_first_paint)
                self._log_latency_breakdown()

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setClipRegion(event.region())

            # 1. Draw full screen frozen capture
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(self.rect(), self.bg_pixmap)

            # 2. Draw subtle deep ocean-tinted dim mask outside selection
            overlay_path = QPainterPath()
            overlay_path.addRect(QRectF(self.rect()))
            if self.has_selection:
                sel_norm = self.selection_rect.normalized()
                sel_path = QPainterPath()
                sel_path.addRect(sel_norm)
                overlay_path = overlay_path.subtracted(sel_path)

            painter.fillPath(overlay_path, QColor(4, 22, 42, 138))

            # 3. Draw annotations (anchored to screen coordinates!)
            self._draw_all_annotations(painter)

            # 4. Draw Frutiger Aero glowing selection border, 3D Water-Droplet Orbs, and Frosted Badge
            if self.has_selection:
                r = self.selection_rect.normalized()

                # Outer soft cyan-aqua aura glow around crop box
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(0, 230, 255, 75), 5.0, Qt.PenStyle.SolidLine))
                painter.drawRect(r)
                painter.setPen(QPen(QColor(80, 245, 255, 185), 2.2, Qt.PenStyle.SolidLine))
                painter.drawRect(r)
                painter.setPen(QPen(QColor(255, 255, 255, 235), 1.0, Qt.PenStyle.SolidLine))
                painter.drawRect(r)

                # 8 Glossy 3D Frutiger Aqua Water-Droplet / Pearl Resize Orbs
                for hrect in self._get_handle_rects(r):
                    center = hrect.center()
                    rad = hrect.width() / 2.0
                    # Drop shadow under orb
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(0, 25, 55, 130))
                    painter.drawEllipse(center + QPointF(0.0, 1.5), rad + 0.8, rad + 0.8)

                    # Radial aqua-pearl sphere gradient
                    orb_grad = QRadialGradient(
                        center - QPointF(rad * 0.3, rad * 0.3), rad * 1.35
                    )
                    orb_grad.setColorAt(0.0, QColor(255, 255, 255, 255))
                    orb_grad.setColorAt(0.38, QColor(125, 245, 255, 255))
                    orb_grad.setColorAt(0.78, QColor(0, 145, 235, 255))
                    orb_grad.setColorAt(1.0, QColor(0, 75, 155, 255))
                    painter.setBrush(QBrush(orb_grad))
                    painter.setPen(QPen(QColor(255, 255, 255, 240), 1.3))
                    painter.drawEllipse(center, rad, rad)

                    # Tiny top-left specular shine dot on each orb
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(255, 255, 255, 235))
                    painter.drawEllipse(
                        center - QPointF(rad * 0.32, rad * 0.32), rad * 0.28, rad * 0.22
                    )

                # Top-left Frosted Acrylic Dimensions & HDR Status Capsule
                self._sync_coordinate_scales()
                _, _, phys_w, phys_h = self.coord_mapper.local_rect_to_image_crop_rect(
                    (r.left(), r.top(), r.width(), r.height())
                )
                hdr_tag = (
                    f"  •  HDR @ {int(round(self.current_white_scale * 80))} nits"
                    if self.frame.is_hdr_surface
                    else (
                        "  •  DIAGNOSTIC SDR-ONLY (DXGI BYPASSED)"
                        if self.config.disable_native_hdr_capture
                        else "  •  SDR"
                    )
                )
                safe_tag = (
                    "  •  [SAFE MODE]" if self.config.is_safe_mode_active else ""
                )
                dim_text = f"{phys_w} × {phys_h} px{hdr_tag}  •  Stroke: {self.stroke_width}px{safe_tag}" 
                font = QFont("Segoe UI", 9, QFont.Weight.Bold)
                painter.setFont(font)
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(dim_text) + 34
                th = fm.height() + 12
                bx = max(6.0, min(float(self.width() - tw - 6), r.left()))
                by = r.top() - th - 9.0
                if by < 6.0:
                    by = r.top() + 9.0
                badge_rect = QRectF(bx, by, tw, th)
                badge_int_rect = badge_rect.toRect()

                if (
                    self._badge_cached_rect != badge_int_rect
                    or self._badge_frosted_pix is None
                ):
                    self._badge_cached_rect = QRect(badge_int_rect)
                    self._badge_frosted_pix = self._sample_frosted_region(badge_int_rect)

                draw_frutiger_glass_panel(
                    painter,
                    badge_rect,
                    radius=th / 2.0,
                    frosted_pixmap=self._badge_frosted_pix,
                    tint_style="aqua",
                )

                # Glowing emerald/aqua status orb inside the left of the capsule
                orb_c = QPointF(badge_rect.left() + 14.0, badge_rect.center().y())
                orb_g = QRadialGradient(orb_c - QPointF(1.5, 1.5), 6.0)
                orb_g.setColorAt(0.0, QColor("#FFFFFF"))
                orb_g.setColorAt(0.45, QColor("#69F0AE"))
                orb_g.setColorAt(1.0, QColor("#00C853"))
                painter.setPen(QPen(QColor(255, 255, 255, 220), 1.0))
                painter.setBrush(QBrush(orb_g))
                painter.drawEllipse(orb_c, 4.8, 4.8)

                text_area = badge_rect.adjusted(22.0, 0.0, -6.0, 0.0)
                painter.setFont(font)
                painter.setPen(QColor(0, 25, 55, 200))
                painter.drawText(
                    text_area.translated(0.0, 1.2),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    dim_text,
                )
                painter.setPen(QColor(255, 255, 255, 252))
                painter.drawText(
                    text_area,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    dim_text,
                )

        def _draw_all_annotations(self, painter: QPainter) -> None:
            items = list(self.annotations)
            if self.current_annotation is not None:
                items.append(self.current_annotation)

            for item in items:
                col = QColor(item.color)
                pen = QPen(
                    col,
                    item.thickness,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)

                if item.tool == "pen" and len(item.points) >= 2:
                    path = QPainterPath(QPointF(*item.points[0]))
                    for pt in item.points[1:]:
                        path.lineTo(QPointF(*pt))
                    painter.drawPath(path)

                elif item.tool == "rect" and len(item.points) >= 2:
                    p1 = QPointF(*item.points[0])
                    p2 = QPointF(*item.points[-1])
                    painter.drawRect(QRectF(p1, p2).normalized())

                elif item.tool == "ellipse" and len(item.points) >= 2:
                    p1 = QPointF(*item.points[0])
                    p2 = QPointF(*item.points[-1])
                    painter.drawEllipse(QRectF(p1, p2).normalized())

                elif item.tool == "line" and len(item.points) >= 2:
                    painter.drawLine(
                        QPointF(*item.points[0]), QPointF(*item.points[-1])
                    )

                elif item.tool == "arrow" and len(item.points) >= 2:
                    p1 = QPointF(*item.points[0])
                    p2 = QPointF(*item.points[-1])
                    painter.drawLine(p1, p2)
                    angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
                    head_len = max(12.0, item.thickness * 4.0)
                    wing1 = QPointF(
                        p2.x() - head_len * math.cos(angle - math.pi / 6),
                        p2.y() - head_len * math.sin(angle - math.pi / 6),
                    )
                    wing2 = QPointF(
                        p2.x() - head_len * math.cos(angle + math.pi / 6),
                        p2.y() - head_len * math.sin(angle + math.pi / 6),
                    )
                    painter.setBrush(QBrush(col))
                    painter.drawPolygon(QPolygonF([p2, wing1, wing2]))

                elif item.tool == "text" and item.points and item.text:
                    pt = QPointF(*item.points[0])
                    font = QFont(
                        "Segoe UI", max(11, item.thickness * 4), QFont.Weight.Bold
                    )
                    painter.setFont(font)
                    painter.setPen(QColor(0, 0, 0, 200))
                    painter.drawText(QPointF(pt.x() + 1.5, pt.y() + 1.5), item.text)
                    painter.setPen(col)
                    painter.drawText(pt, item.text)

        # ---------------------------------------------------------------------
        # Mouse & Keyboard Interaction
        # ---------------------------------------------------------------------
        def mousePressEvent(self, event) -> None:
            if event.button() == Qt.MouseButton.RightButton:
                self.close()
                return
            if event.button() != Qt.MouseButton.LeftButton:
                return

            pos = event.position()

            # 1. Always allow grabbing the 8 resize handles of the selection box
            h_idx = self._hit_test_handles(pos)
            if h_idx != -1:
                self.interaction_mode = "resizing"
                self.active_handle = h_idx
                self.drag_start_pos = pos
                self.rect_at_drag_start = QRectF(self.selection_rect.normalized())
                self.toolbar.hide()
                return

            # 2. If no selection yet, drag creates the selection box
            if not self.has_selection:
                self.has_selection = True
                self.interaction_mode = "creating"
                self.drag_start_pos = pos
                self.selection_rect = QRectF(pos, pos)
                self.toolbar.hide()
                self.update()
                return

            # 3. Allow grabbing the border of the selection box to move it at any time
            if self._hit_test_border(pos):
                self.interaction_mode = "moving"
                self.drag_start_pos = pos
                self.rect_at_drag_start = QRectF(self.selection_rect.normalized())
                self.toolbar.hide()
                return

            # 4. Inside selection box: either move the box or draw with the selected tool
            sel_norm = self.selection_rect.normalized()
            if sel_norm.contains(pos):
                if self.active_tool == "move" or self.space_held:
                    self.interaction_mode = "moving"
                    self.drag_start_pos = pos
                    self.rect_at_drag_start = QRectF(sel_norm)
                    self.toolbar.hide()
                elif self.active_tool == "text":
                    text, ok = QInputDialog.getText(
                        self, "Add Text Annotation", "Enter text:"
                    )
                    if ok and text.strip():
                        self.annotations.append(
                            AnnotationItem(
                                tool="text",
                                color=self.stroke_color.name(),
                                thickness=self.stroke_width,
                                points=[(pos.x(), pos.y())],
                                text=text.strip(),
                            )
                        )
                        self.redo_stack.clear()
                        self.toolbar.invalidate_backdrop()
                        self.update()
                    self.setFocus()
                else:
                    self.interaction_mode = "drawing"
                    self.current_annotation = AnnotationItem(
                        tool=self.active_tool,
                        color=self.stroke_color.name(),
                        thickness=self.stroke_width,
                        points=[(pos.x(), pos.y())],
                    )
                    self.update()
            else:
                self.interaction_mode = "creating"
                self.drag_start_pos = pos
                self.selection_rect = QRectF(pos, pos)
                self.toolbar.hide()
                self.update()

        def mouseMoveEvent(self, event) -> None:
            pos = event.position()

            if self.interaction_mode == "none":
                h_idx = self._hit_test_handles(pos)
                if h_idx != -1:
                    self.setCursor(self.HANDLE_CURSORS[h_idx])
                elif self._hit_test_border(pos):
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                elif (
                    self.has_selection
                    and self.selection_rect.normalized().contains(pos)
                ):
                    if self.active_tool == "move" or self.space_held:
                        self.setCursor(Qt.CursorShape.SizeAllCursor)
                    else:
                        self.setCursor(Qt.CursorShape.CrossCursor)
                else:
                    self.setCursor(Qt.CursorShape.CrossCursor)
                return

            if self.interaction_mode == "creating":
                self.selection_rect = QRectF(self.drag_start_pos, pos).normalized()
                self.update()

            elif self.interaction_mode == "moving":
                delta = pos - self.drag_start_pos
                new_r = self.rect_at_drag_start.translated(delta)
                dx = 0.0
                dy = 0.0
                if new_r.left() < 0:
                    dx = -new_r.left()
                elif new_r.right() > self.width():
                    dx = self.width() - new_r.right()
                if new_r.top() < 0:
                    dy = -new_r.top()
                elif new_r.bottom() > self.height():
                    dy = self.height() - new_r.bottom()
                self.selection_rect = new_r.translated(dx, dy)
                self.update()

            elif self.interaction_mode == "resizing":
                r = QRectF(self.rect_at_drag_start)
                h = self.active_handle
                if h in (0, 6, 7):
                    r.setLeft(pos.x())
                if h in (2, 3, 4):
                    r.setRight(pos.x())
                if h in (0, 1, 2):
                    r.setTop(pos.y())
                if h in (4, 5, 6):
                    r.setBottom(pos.y())
                self.selection_rect = r.normalized()
                self.update()

            elif (
                self.interaction_mode == "drawing"
                and self.current_annotation is not None
            ):
                target_pt = (pos.x(), pos.y())
                if self.current_annotation.tool == "pen":
                    self.current_annotation.points.append(target_pt)
                else:
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        target_pt = self._apply_shift_constraint(
                            self.current_annotation.tool,
                            self.current_annotation.points[0],
                            target_pt,
                        )
                    if len(self.current_annotation.points) == 1:
                        self.current_annotation.points.append(target_pt)
                    else:
                        self.current_annotation.points[-1] = target_pt
                self.update()

        def mouseReleaseEvent(self, event) -> None:
            if event.button() != Qt.MouseButton.LeftButton:
                return

            if (
                self.interaction_mode == "drawing"
                and self.current_annotation is not None
            ):
                if len(self.current_annotation.points) >= 2:
                    self.annotations.append(self.current_annotation)
                    self.redo_stack.clear()
                self.current_annotation = None

            self.interaction_mode = "none"
            self.active_handle = -1
            self._reposition_toolbar()
            self.update()

        def wheelEvent(self, event) -> None:
            delta = event.angleDelta().y()
            if delta > 0:
                self.stroke_width = min(20, self.stroke_width + 1)
            elif delta < 0:
                self.stroke_width = max(1, self.stroke_width - 1)
            if self._badge_cached_rect is not None:
                self.update(self._badge_cached_rect.adjusted(-4, -4, 4, 4))
            else:
                self.update()

        def keyPressEvent(self, event) -> None:
            key = event.key()
            mods = event.modifiers()

            if key == Qt.Key.Key_Space and not event.isAutoRepeat():
                self.space_held = True
                self.update()
            elif key == Qt.Key.Key_Escape:
                self.close()
            elif (
                key == Qt.Key.Key_C and (mods & Qt.KeyboardModifier.ControlModifier)
            ) or key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.copy_snip()
            elif (
                key == Qt.Key.Key_S
                and (mods & Qt.KeyboardModifier.ControlModifier)
                and (mods & Qt.KeyboardModifier.AltModifier)
            ):
                self.save_snip_as()
            elif (
                key == Qt.Key.Key_S
                and (mods & Qt.KeyboardModifier.ControlModifier)
                and (mods & Qt.KeyboardModifier.ShiftModifier)
            ):
                self.quick_save_snip()
            elif key == Qt.Key.Key_S and (mods & Qt.KeyboardModifier.ControlModifier):
                self.save_snip()
            elif key == Qt.Key.Key_Z and (mods & Qt.KeyboardModifier.ControlModifier):
                self.undo_annotation()
            elif key == Qt.Key.Key_Y and (mods & Qt.KeyboardModifier.ControlModifier):
                if self.redo_stack:
                    self.annotations.append(self.redo_stack.pop())
                    self.toolbar.invalidate_backdrop()
                    self.update()
            elif key == Qt.Key.Key_V:
                self.set_tool("move")
            elif key == Qt.Key.Key_P:
                self.set_tool("pen")
            elif key == Qt.Key.Key_R:
                self.set_tool("rect")
            elif key == Qt.Key.Key_E:
                self.set_tool("ellipse")
            elif key == Qt.Key.Key_L:
                self.set_tool("line")
            elif key == Qt.Key.Key_A:
                self.set_tool("arrow")
            elif key == Qt.Key.Key_T:
                self.set_tool("text")

        def keyReleaseEvent(self, event) -> None:
            if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
                self.space_held = False
                self.update()

        def on_config_updated(self) -> None:
            """Synchronizes an already-open SnipOverlayWindow when SettingsDialog saves changes."""
            if self._closed:
                return
            director = AeroAnimationDirector.instance()
            director.apply_config_flags(self.config)
            self._badge_cached_rect = None
            self._badge_frosted_pix = None
            if hasattr(self, "toolbar") and self.toolbar is not None:
                self.toolbar.invalidate_backdrop()
            if self.frame.raw_scrgb_float is not None:
                self._render_revision += 1
                self._request_tone_render(full=True)
            else:
                self.update()
            self.setFocus()

        # ---------------------------------------------------------------------
        # Export (Render Cropped Region + Annotations to Clipboard or PNG)
        # ---------------------------------------------------------------------
        def render_final_cropped_pixmap(self) -> QPixmap:
            self._ensure_full_resolution_export()
            self._sync_coordinate_scales()
            img_w = int(self.frame.srgb_image.shape[1])
            img_h = int(self.frame.srgb_image.shape[0])
            full_rect = QRect(0, 0, img_w, img_h)

            if self.has_selection and self.selection_rect.width() > 2:
                r = self.selection_rect.normalized()
                cx, cy, cw, ch = self.coord_mapper.local_rect_to_image_crop_rect(
                    (r.left(), r.top(), r.width(), r.height())
                )
                crop_rect = QRect(cx, cy, cw, ch).intersected(full_rect)
                if crop_rect.isEmpty():
                    crop_rect = full_rect
            else:
                crop_rect = full_rect

            # Fast path when no annotations exist: copy the exact cropped region directly
            # without allocating a second 33 MB 4K full-screen QPixmap.
            if not self.annotations and self.bg_pixmap.size() == full_rect.size():
                return (
                    self.bg_pixmap.copy(crop_rect)
                    if crop_rect != full_rect
                    else self.bg_pixmap.copy()
                )

            out_canvas = QPixmap(crop_rect.size())
            painter = QPainter(out_canvas)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(
                QRect(0, 0, crop_rect.width(), crop_rect.height()),
                self.bg_pixmap,
                crop_rect,
            )
            painter.translate(-float(crop_rect.x()), -float(crop_rect.y()))
            painter.scale(self._px_scale_x, self._px_scale_y)
            self._draw_all_annotations(painter)
            painter.end()
            return out_canvas

        def copy_snip(self) -> None:
            pix = self.render_final_cropped_pixmap()
            QApplication.clipboard().setPixmap(pix)
            self.close()

        def _handle_save_error(
            self,
            target_desc: str,
            exc: BaseException,
            rendered_pixmap: QPixmap,
        ) -> Optional[Path]:
            """
            Handles screenshot save failures without closing the overlay or losing the
            user's selected crop region or annotations. Offers Retry, Save As..., or Cancel.
            """
            DIAG_LOG.error("SAVE_SNIP", f"Failed to save screenshot to '{target_desc}'", exc)
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("HDRSnip Fusion — Screenshot Save Failed")
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setText(
                f"Could not save the screenshot to:\n{target_desc}\n\n"
                f"Reason: {exc}\n\n"
                "Your screenshot selection and annotations are still preserved."
            )
            retry_btn = msg_box.addButton(
                "Retry", QMessageBox.ButtonRole.AcceptRole
            )
            save_as_btn = msg_box.addButton(
                "Choose Another Folder (Save As...)", QMessageBox.ButtonRole.ActionRole
            )
            msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            msg_box.exec()

            clicked = msg_box.clickedButton()
            if clicked == retry_btn:
                return Path("__RETRY__")
            if clicked == save_as_btn:
                return self.save_snip_as(pre_rendered_pixmap=rendered_pixmap)
            self.setFocus()
            return None

        def _save_to_default_directory(
            self, *, copy_to_clipboard: bool = False
        ) -> Optional[Path]:
            """
            Shared implementation for ordinary Save (Ctrl+S / green Save button) and
            Quick Save (Ctrl+Shift+S). Writes directly into `config.save_directory`
            using `_unique_screenshot_path()` and closes the overlay ONLY after saving succeeds.
            """
            pix = self.render_final_cropped_pixmap()
            while True:
                target_dir_str = str(self.config.save_directory or "").strip()
                try:
                    out_path = save_screenshot_to_directory(
                        pix, target_dir_str, prefix="HDRSnipFusion"
                    )
                    if copy_to_clipboard:
                        QApplication.clipboard().setPixmap(pix)
                    DIAG_LOG.milestone(
                        "SAVE_SNIP",
                        f"Saved full-resolution screenshot to '{out_path}' "
                        f"(copy_to_clipboard={copy_to_clipboard})",
                    )
                    self.close()
                    return out_path
                except Exception as exc:
                    recovery = self._handle_save_error(
                        target_dir_str or "<empty path>", exc, pix
                    )
                    if recovery is not None and str(recovery) == "__RETRY__":
                        continue
                    return recovery

        def save_snip(self) -> Optional[Path]:
            """Saves directly to the configured default folder (Ctrl+S or green Save button)."""
            return self._save_to_default_directory(copy_to_clipboard=False)

        def quick_save_snip(self) -> Optional[Path]:
            """Saves directly to the configured default folder AND copies to clipboard (Ctrl+Shift+S)."""
            return self._save_to_default_directory(copy_to_clipboard=True)

        def save_snip_as(
            self, pre_rendered_pixmap: Optional[QPixmap] = None
        ) -> Optional[Path]:
            """
            Opens a Save As dialog (Ctrl+Alt+S or fallback from failed save) allowing the
            user to choose a custom folder, filename, and format (PNG or JPEG).
            Closes the overlay only after the file is verified written to disk.
            """
            pix = (
                pre_rendered_pixmap
                if pre_rendered_pixmap is not None
                else self.render_final_cropped_pixmap()
            )
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3]
            fallback_name = f"HDRSnipFusion_{stamp}.png"
            try:
                cfg_dir = Path(self.config.save_directory).expanduser()
                if cfg_dir.exists() and cfg_dir.is_dir():
                    default_path = str(cfg_dir / fallback_name)
                elif cfg_dir.parent.exists() and cfg_dir.parent.is_dir():
                    default_path = str(cfg_dir.parent / fallback_name)
                else:
                    default_path = str(Path.home() / fallback_name)
            except Exception:
                default_path = str(Path.home() / fallback_name)

            while True:
                file_path, selected_filter = QFileDialog.getSaveFileName(
                    self,
                    "Save HDR-Corrected Screenshot As",
                    default_path,
                    "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg)",
                )
                if not file_path:
                    self.setFocus()
                    return None

                chosen_path = Path(file_path)
                if not chosen_path.suffix:
                    if "JPEG" in str(selected_filter).upper():
                        chosen_path = chosen_path.with_suffix(".jpg")
                    else:
                        chosen_path = chosen_path.with_suffix(".png")

                try:
                    saved_path = save_pixmap_or_image_atomically(pix, chosen_path, allow_overwrite=True)
                    # Update default directory in memory if user had an invalid directory?
                    # No: keep configured default save_directory unchanged unless changed in Settings.
                    DIAG_LOG.milestone(
                        "SAVE_SNIP_AS",
                        f"Saved screenshot via Save As dialog to '{saved_path}'",
                    )
                    self.close()
                    return saved_path
                except Exception as exc:
                    DIAG_LOG.error(
                        "SAVE_SNIP_AS",
                        f"Save As failed for path '{chosen_path}'",
                        exc,
                    )
                    retry_ans = QMessageBox.warning(
                        self,
                        "HDRSnip Fusion — Save As Failed",
                        f"Could not write screenshot to:\n{chosen_path}\n\n"
                        f"Reason: {exc}\n\n"
                        "Would you like to choose a different location?",
                        QMessageBox.StandardButton.Retry
                        | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Retry,
                    )
                    if retry_ans == QMessageBox.StandardButton.Retry:
                        default_path = str(Path.home() / chosen_path.name)
                        continue
                    self.setFocus()
                    return None

        def cleanup_resources(self) -> int:
            """
            Releases all large screenshot NumPy arrays, full-screen QPixmaps, frosted acrylic
            caches, annotations, and active timers when the overlay closes.
            If an async ToneRenderJob is currently running in the thread pool, sets the
            cancellation event and defers `frame.release_buffers()` until the worker finishes.
            """
            if self._resources_released:
                return 0
            self._closed = True
            self._resources_released = True
            self._cancel_tone_event.set()
            self._render_debounce.stop()
            self._pending_tone_request = None

            if hasattr(self, "toolbar") and self.toolbar is not None:
                self.toolbar.hide()
                self.toolbar.cleanup_resources()

            self._badge_frosted_pix = None
            self._badge_cached_rect = None
            self.bg_pixmap = QPixmap()
            self.target_screen = None
            self.annotations.clear()
            self.redo_stack.clear()
            self.current_annotation = None

            if not self._render_running and not getattr(self, "_initial_render_running", False):
                try:
                    self._render_signals.done.disconnect(self._on_tone_render_ready)
                except Exception:
                    pass
                try:
                    if hasattr(self, "_initial_render_signals"):
                        self._initial_render_signals.done.disconnect(self._on_initial_full_tone_ready)
                except Exception:
                    pass
                freed = self.frame.release_buffers()
                snap = PERF_TELEMETRY.snapshot()
                DIAG_LOG.milestone(
                    "OVERLAY_CLOSE",
                    f"Overlay closed and released {freed / (1024 * 1024):.2f} MB "
                    f"(fps={snap['measured_fps']:.1f}, avg_paint={snap['avg_toolbar_paint_ms']:.3f} ms, "
                    f"avg_caustic={snap['avg_caustic_synth_ms']:.3f} ms, "
                    f"retained_overlays={snap['retained_overlay_instances']}, "
                    f"active_timers={snap['active_animation_timers']})",
                )
                return freed
            DIAG_LOG.log(
                "OVERLAY_CLOSE",
                "Overlay closed while async tone worker active; buffer release deferred to worker completion",
            )
            return 0

        def closeEvent(self, event) -> None:
            self.cleanup_resources()
            self.overlay_closed.emit(self)
            super().closeEvent(event)


def set_windows_autostart(enabled: bool) -> None:
    """HKCU startup setting, requiring no administrator elevation."""
    if sys.platform != "win32":
        return
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}"'
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        cmd = f'"{pythonw if pythonw.exists() else sys.executable}" "{Path(__file__).resolve()}"'
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, "HDRSnipFusion", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "HDRSnipFusion")
            except FileNotFoundError:
                pass


# =============================================================================
# 8B. GITHUB AUTOMATIC UPDATER, INTEGRITY VALIDATOR & SAFE EXE REPLACEMENT
# =============================================================================

_PACKAGED_EXE_OVERRIDE: Optional[bool] = None
_CURRENT_EXE_PATH_OVERRIDE: Optional[Path] = None
_ALLOW_LOCALHOST_UPDATE_URLS: bool = False
_UPDATE_TRANSACTION_LOCK = threading.Lock()
_SEVEN_DAYS_SEC: float = 7.0 * 86400.0


class UpdateVerificationError(RuntimeError):
    """Raised when a release asset or staged update fails security or integrity validation."""


@dataclass
class UpdateCheckResult:
    """Structured result from checking the official GitHub Releases API."""

    status: str  # "up_to_date", "update_available", "asset_pending", "offline", "rate_limited", "error"
    current_version: str = APP_VERSION
    latest_version: str = APP_VERSION
    release_title: str = ""
    release_notes: str = ""
    release_url: str = GITHUB_RELEASES_PAGE_URL
    download_url: str = ""
    asset_name: str = ""
    asset_size: int = 0
    expected_sha256: str = ""
    published_at: str = ""
    message: str = ""
    checked_at_epoch: float = field(default_factory=time.time)

    @property
    def is_update_ready(self) -> bool:
        return (
            self.status == "update_available"
            and bool(self.download_url)
            and len(self.expected_sha256) == 64
            and self.asset_size > 0
        )


def parse_semver(version_str: str) -> Optional[Tuple[int, ...]]:
    """
    Parses a stable semantic version string such as '0.1.1' or 'v0.1.2' into an
    integer tuple `(major, minor, patch)`.
    Strictly rejects pre-release tags (e.g. 'v0.1.2-beta.1', 'v0.1.2-rc1'), build
    metadata suffixes, or non-numeric components so unstable tags are never installed.
    """
    if not isinstance(version_str, str):
        return None
    cleaned = version_str.strip()
    if cleaned.startswith(("v", "V")):
        cleaned = cleaned[1:].strip()
    if not cleaned or "-" in cleaned or "+" in cleaned:
        return None
    parts = cleaned.split(".")
    if len(parts) < 2 or len(parts) > 4:
        return None
    nums: List[int] = []
    for p in parts:
        if not p.isdigit():
            return None
        nums.append(int(p))
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def format_semver(version_str: str) -> str:
    """Normalizes a version string into 'X.Y.Z' format (without leading 'v')."""
    parsed = parse_semver(version_str)
    if parsed is None:
        return str(version_str).strip().lstrip("vV")
    return ".".join(str(x) for x in parsed)


def is_newer_semver(
    candidate_version: str, current_version: str = APP_VERSION
) -> bool:
    """
    Compares two semantic version strings numerically.
    Examples:
      - is_newer_semver('0.1.2', '0.1.1') -> True
      - is_newer_semver('0.2.0', '0.1.9') -> True
      - is_newer_semver('1.0.0', '0.9.9') -> True
      - is_newer_semver('0.1.1', '0.1.1') -> False
    """
    cand = parse_semver(candidate_version)
    curr = parse_semver(current_version)
    if cand is None or curr is None:
        return False
    max_len = max(len(cand), len(curr))
    cand_pad = cand + (0,) * (max_len - len(cand))
    curr_pad = curr + (0,) * (max_len - len(curr))
    return cand_pad > curr_pad


def is_packaged_exe() -> bool:
    """
    Returns True only when running as a packaged PyInstaller Windows executable
    (never True when running from Python source `.py` with `python.exe` / `pythonw.exe`).
    """
    if _PACKAGED_EXE_OVERRIDE is not None:
        return bool(_PACKAGED_EXE_OVERRIDE)
    if not getattr(sys, "frozen", False):
        return False
    exe_name = Path(sys.executable).name.lower()
    if exe_name in ("python.exe", "pythonw.exe", "python", "python3"):
        return False
    return True


def get_current_executable_path() -> Path:
    """Returns the resolved filesystem path of the currently running executable."""
    if _CURRENT_EXE_PATH_OVERRIDE is not None:
        return Path(_CURRENT_EXE_PATH_OVERRIDE).resolve()
    return Path(sys.executable).resolve()


def is_protected_install_location(
    exe_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """
    Checks whether `exe_path` resides in a directory that requires Administrator
    elevation (such as `Program Files`, `Program Files (x86)`, or `Windows`) or
    is not writable by the current user.
    Never attempts privilege escalation or UAC bypass.
    """
    target = Path(exe_path or get_current_executable_path()).resolve()
    parent_dir = target.parent

    # Check standard Windows protected system roots
    protected_roots: List[Path] = []
    for env_key in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "SystemRoot", "WINDIR"):
        val = os.environ.get(env_key, "").strip()
        if val:
            try:
                protected_roots.append(Path(val).resolve())
            except Exception:
                pass

    target_str_norm = str(parent_dir).replace("/", "\\").casefold()
    for p_root in protected_roots:
        root_norm = str(p_root).replace("/", "\\").casefold()
        if root_norm and (
            target_str_norm == root_norm
            or target_str_norm.startswith(root_norm + "\\")
        ):
            return (
                True,
                f"Installation folder '{parent_dir}' is inside a protected Windows system directory ({p_root}).",
            )

    # Also check common protected folder names if path contains 'Program Files'
    raw_exe_str = str(exe_path or get_current_executable_path())
    lower_parts = [
        pt.strip().casefold()
        for pt in raw_exe_str.replace("\\", "/").split("/")[:-1]
        if pt.strip()
    ] + [pt.casefold() for pt in parent_dir.parts]
    if "program files" in lower_parts or "program files (x86)" in lower_parts:
        return (
            True,
            f"Installation folder '{parent_dir}' is inside Program Files and requires administrator permissions.",
        )

    if not parent_dir.exists():
        return (True, f"Installation folder '{parent_dir}' does not exist.")

    # Perform a safe non-destructive write probe in the installation directory
    probe_name = f".hdrsnip_write_probe_{os.getpid()}_{int(time.perf_counter() * 1e6) % 1000000}.tmp"
    probe_path = parent_dir / probe_name
    try:
        with open(probe_path, "wb") as fh:
            fh.write(b"ok")
        probe_path.unlink()
    except Exception as exc:
        try:
            if probe_path.exists():
                probe_path.unlink()
        except OSError:
            pass
        return (
            True,
            f"Installation folder '{parent_dir}' is not writable by the current user ({exc}).",
        )

    return (False, "writable")


def compute_file_sha256(file_path: Path) -> str:
    """Computes the lowercase 64-character hexadecimal SHA-256 digest of a file on disk."""
    h = hashlib.sha256()
    with open(file_path, "rb") as fh:
        while True:
            chunk = fh.read(131072)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def validate_windows_pe_executable(
    file_path: Path,
    min_size: int = MIN_EXE_SIZE_BYTES,
    max_size: int = MAX_EXE_SIZE_BYTES,
) -> Tuple[bool, str]:
    """
    Validates that `file_path` is a structurally valid 64-bit Windows Portable Executable
    (PE32+ / AMD64 `.exe`, not a DLL, HTML error page, ZIP archive, or truncated file).
    """
    try:
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return (False, f"File does not exist: {p}")
        file_size = p.stat().st_size
        if file_size < min_size:
            return (
                False,
                f"Executable size ({file_size:,} bytes) is smaller than minimum expected ({min_size:,} bytes).",
            )
        if file_size > max_size:
            return (
                False,
                f"Executable size ({file_size:,} bytes) exceeds maximum allowed ({max_size:,} bytes).",
            )

        with open(p, "rb") as fh:
            dos_hdr = fh.read(64)
            if len(dos_hdr) < 64 or dos_hdr[:2] != b"MZ":
                return (False, "Missing Windows MZ DOS header signature.")
            e_lfanew = struct.unpack_from("<I", dos_hdr, 0x3C)[0]
            if e_lfanew < 64 or e_lfanew + 264 > file_size:
                return (
                    False,
                    f"Invalid PE header offset e_lfanew=0x{e_lfanew:X} for file size {file_size}.",
                )
            fh.seek(e_lfanew)
            pe_block = fh.read(264)
            if len(pe_block) < 120 or pe_block[:4] != b"PE\x00\x00":
                return (False, "Missing PE\\0\\0 signature at e_lfanew offset.")

            (
                machine,
                num_sections,
                _timestamp,
                _ptr_sym,
                _num_sym,
                size_opt_hdr,
                characteristics,
            ) = struct.unpack_from("<HHIIIHH", pe_block, 4)

            # 0x8664 = IMAGE_FILE_MACHINE_AMD64 (x86_64 Windows)
            if machine != 0x8664:
                return (
                    False,
                    f"Unsupported PE target architecture 0x{machine:04X} (expected x86_64 AMD64 0x8664).",
                )
            if num_sections < 1:
                return (False, "PE executable contains zero sections.")
            # 0x0002 = IMAGE_FILE_EXECUTABLE_IMAGE, 0x2000 = IMAGE_FILE_DLL
            if not (characteristics & 0x0002):
                return (False, "PE image is not marked as executable.")
            if characteristics & 0x2000:
                return (False, "PE image is a DLL, not a standalone EXE.")
            if size_opt_hdr < 112:
                return (False, f"PE Optional Header is too small ({size_opt_hdr} bytes).")

            opt_magic = struct.unpack_from("<H", pe_block, 24)[0]
            # 0x020B = PE32+ (64-bit executable)
            if opt_magic != 0x020B:
                return (
                    False,
                    f"PE Optional Header magic 0x{opt_magic:04X} is not 64-bit PE32+ (0x020B).",
                )
            subsystem = struct.unpack_from("<H", pe_block, 24 + 68)[0]
            # 2 = IMAGE_SUBSYSTEM_WINDOWS_GUI, 3 = IMAGE_SUBSYSTEM_WINDOWS_CUI
            if subsystem not in (2, 3):
                return (
                    False,
                    f"Unexpected Windows PE subsystem {subsystem} (expected GUI=2 or CUI=3).",
                )

        return (True, "valid_pe64_exe")
    except Exception as exc:
        return (False, f"PE validation exception: {exc}")


class _WINTRUST_FILE_INFO(ctypes.Structure):
    _fields_ = [
        ("cbStruct", wintypes.DWORD),
        ("pcwszFilePath", wintypes.LPCWSTR),
        ("hFile", wintypes.HANDLE),
        ("pgKnownSubject", ctypes.c_void_p),
    ]


class _WINTRUST_DATA(ctypes.Structure):
    _fields_ = [
        ("cbStruct", wintypes.DWORD),
        ("pPolicyCallbackData", ctypes.c_void_p),
        ("pSIPClientData", ctypes.c_void_p),
        ("dwUIChoice", wintypes.DWORD),
        ("fdwRevocationChecks", wintypes.DWORD),
        ("dwUnionChoice", wintypes.DWORD),
        ("pFile", ctypes.POINTER(_WINTRUST_FILE_INFO)),
        ("dwStateAction", wintypes.DWORD),
        ("hWVTStateData", wintypes.HANDLE),
        ("pwszURLReference", wintypes.LPCWSTR),
        ("dwProvFlags", wintypes.DWORD),
        ("dwUIContext", wintypes.DWORD),
        ("pSignatureSettings", ctypes.c_void_p),
    ]


def verify_authenticode_signature(
    file_path: Path,
    require_signature: bool = REQUIRE_AUTHENTICODE_SIGNATURE,
) -> Tuple[bool, str]:
    """
    Extension point for Windows Authenticode code-signing verification via `WinVerifyTrust`.
    Currently `REQUIRE_AUTHENTICODE_SIGNATURE` is False because official builds are unsigned
    and verified via GitHub Release asset SHA-256 digests. If the project adopts a code-signing
    certificate in the future, setting `REQUIRE_AUTHENTICODE_SIGNATURE = True` enforces OS-level
    Authenticode chain trust before staging or replacing any executable.
    """
    if not require_signature:
        return (
            True,
            "Authenticode enforcement not required for unsigned release (verified via SHA-256).",
        )
    if sys.platform != "win32":
        return (False, "Authenticode verification requires Windows WinVerifyTrust.")
    try:
        wintrust = ctypes.WinDLL("wintrust", use_last_error=True)
        # WINTRUST_ACTION_GENERIC_VERIFY_V2 = {00AAC56B-CD44-11d0-8CC2-00C04FC295EE}
        action_guid = GUID.from_str("00aac56b-cd44-11d0-8cc2-00c04fc295ee")

        file_info = _WINTRUST_FILE_INFO()
        file_info.cbStruct = ctypes.sizeof(_WINTRUST_FILE_INFO)
        file_info.pcwszFilePath = str(Path(file_path).resolve())
        file_info.hFile = None
        file_info.pgKnownSubject = None

        wt_data = _WINTRUST_DATA()
        wt_data.cbStruct = ctypes.sizeof(_WINTRUST_DATA)
        wt_data.dwUIChoice = 2          # WTD_UI_NONE
        wt_data.fdwRevocationChecks = 0 # WTD_REVOKE_NONE
        wt_data.dwUnionChoice = 1       # WTD_CHOICE_FILE
        wt_data.pFile = ctypes.pointer(file_info)
        wt_data.dwStateAction = 0       # WTD_STATEACTION_IGNORE
        wt_data.dwProvFlags = 0x00000010  # WTD_CACHE_ONLY_URL_RETRIEVAL

        wintrust.WinVerifyTrust.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(GUID),
            ctypes.POINTER(_WINTRUST_DATA),
        ]
        wintrust.WinVerifyTrust.restype = wintypes.LONG
        status = wintrust.WinVerifyTrust(
            None, ctypes.byref(action_guid), ctypes.byref(wt_data)
        )
        if status == 0:
            return (True, "Valid trusted Windows Authenticode signature.")
        return (
            False,
            f"WinVerifyTrust rejected Authenticode signature (status=0x{int(status) & 0xFFFFFFFF:08X}).",
        )
    except Exception as exc:
        return (False, f"Authenticode verification error: {exc}")


def is_valid_github_url(
    url: str,
    *,
    require_repo_prefix: bool = False,
) -> bool:
    """
    Validates that `url` uses HTTPS and points to an allowed official GitHub host
    (and optionally belongs to `shadow728270/HDRScreenshot-FrutigerAqua`).
    """
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return False

    if _ALLOW_LOCALHOST_UPDATE_URLS and parsed.hostname in ("127.0.0.1", "localhost"):
        return parsed.scheme in ("http", "https")

    if parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    host_ok = host in ALLOWED_GITHUB_HOSTS or host.endswith(".githubusercontent.com")
    if not host_ok:
        return False

    if require_repo_prefix:
        expected_prefix = f"/{GITHUB_REPO_OWNER.lower()}/{GITHUB_REPO_NAME.lower()}/"
        if not parsed.path.lower().startswith(expected_prefix):
            return False
    return True


class _SafeGitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    Ensures HTTP redirects during GitHub API queries or release asset downloads
    only follow HTTPS URLs on official GitHub / GitHubusercontent domains.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        resolved_url = urllib.parse.urljoin(req.full_url, newurl)
        if not is_valid_github_url(resolved_url, require_repo_prefix=False):
            raise urllib.error.URLError(
                f"Blocked unsafe redirect to untrusted URL: {resolved_url}"
            )
        return super().redirect_request(req, fp, code, msg, headers, resolved_url)


def _extract_asset_sha256(
    asset_dict: Dict[str, Any],
    release_body: str = "",
    asset_name: str = EXPECTED_RELEASE_ASSET_NAME,
) -> Tuple[Optional[str], str]:
    """
    Extracts and validates the expected 64-character hex SHA-256 digest for `HDRSnipFusion.exe`.
    Checks GitHub's native `asset["digest"]` field (`"sha256:<hex>"`) and cross-checks
    against any SHA-256 checksum listed in the release notes body.
    """
    api_sha256: Optional[str] = None
    raw_digest = str(asset_dict.get("digest") or "").strip()
    if raw_digest:
        if raw_digest.lower().startswith("sha256:"):
            cand = raw_digest[7:].strip().lower()
        else:
            cand = raw_digest.strip().lower()
        if len(cand) == 64 and all(c in "0123456789abcdef" for c in cand):
            api_sha256 = cand
        else:
            return (
                None,
                f"Invalid SHA-256 digest format in GitHub asset metadata: '{raw_digest}'",
            )

    body_sha256: Optional[str] = None
    if release_body:
        # Match patterns like: `<64-hex>  HDRSnipFusion.exe` or `SHA-256: <64-hex>`
        pat_named = re.search(
            r"\b([0-9a-fA-F]{64})\b[^\n\r]{0,40}" + re.escape(asset_name),
            release_body,
            re.IGNORECASE,
        )
        if pat_named:
            body_sha256 = pat_named.group(1).lower()
        else:
            pat_label = re.search(
                r"(?:sha-?256|digest)[:\s=`*]+([0-9a-fA-F]{64})\b",
                release_body,
                re.IGNORECASE,
            )
            if pat_label:
                body_sha256 = pat_label.group(1).lower()

    if api_sha256 and body_sha256 and not hmac.compare_digest(api_sha256, body_sha256):
        return (
            None,
            "SHA-256 digest mismatch between GitHub asset metadata and release notes.",
        )

    final_sha = api_sha256 or body_sha256
    if not final_sha:
        return (
            None,
            f"Release asset '{asset_name}' is missing required SHA-256 digest metadata.",
        )
    return (final_sha, "ok")


def parse_github_release_payload(
    payload: Any,
    current_version: str = APP_VERSION,
) -> UpdateCheckResult:
    """
    Validates a parsed JSON object from `/repos/shadow728270/HDRScreenshot-FrutigerAqua/releases/latest`
    and returns a structured `UpdateCheckResult`.
    Strictly ignores draft releases, pre-releases, releases from other repositories,
    source archives, and releases where `HDRSnipFusion.exe` is not yet uploaded.
    """
    if not isinstance(payload, dict):
        return UpdateCheckResult(
            status="error",
            current_version=current_version,
            message="Invalid release metadata format from GitHub API.",
        )

    if bool(payload.get("draft")) or bool(payload.get("prerelease")):
        return UpdateCheckResult(
            status="up_to_date",
            current_version=current_version,
            latest_version=current_version,
            message="You're running the latest stable version (ignoring draft/pre-release).",
        )

    html_url = str(payload.get("html_url") or GITHUB_RELEASES_PAGE_URL).strip()
    if not is_valid_github_url(html_url, require_repo_prefix=True):
        return UpdateCheckResult(
            status="error",
            current_version=current_version,
            message=f"Rejected release metadata from unexpected repository URL: {html_url}",
        )

    raw_tag = str(payload.get("tag_name") or "").strip()
    parsed_ver = parse_semver(raw_tag)
    if parsed_ver is None:
        return UpdateCheckResult(
            status="up_to_date",
            current_version=current_version,
            latest_version=current_version,
            release_url=html_url,
            message=f"You're running the latest stable version (v{current_version}).",
        )

    clean_latest = format_semver(raw_tag)
    release_title = str(payload.get("name") or f"HDRSnip Fusion v{clean_latest}").strip()
    release_body = str(payload.get("body") or "").strip()
    published_at = str(payload.get("published_at") or "").strip()

    if not is_newer_semver(clean_latest, current_version):
        return UpdateCheckResult(
            status="up_to_date",
            current_version=current_version,
            latest_version=clean_latest,
            release_title=release_title,
            release_notes=release_body,
            release_url=html_url,
            published_at=published_at,
            message=f"You're running the latest version (v{current_version}).",
        )

    assets = payload.get("assets")
    if not isinstance(assets, list):
        assets = []

    matched_asset: Optional[Dict[str, Any]] = None
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name == EXPECTED_RELEASE_ASSET_NAME:
            matched_asset = item
            break

    if matched_asset is None:
        return UpdateCheckResult(
            status="asset_pending",
            current_version=current_version,
            latest_version=clean_latest,
            release_title=release_title,
            release_notes=release_body,
            release_url=html_url,
            published_at=published_at,
            message=(
                f"Release v{clean_latest} is published, but {EXPECTED_RELEASE_ASSET_NAME} "
                "is still being built and attached by GitHub Actions."
            ),
        )

    asset_state = str(matched_asset.get("state") or "uploaded").strip().lower()
    if asset_state != "uploaded":
        return UpdateCheckResult(
            status="asset_pending",
            current_version=current_version,
            latest_version=clean_latest,
            release_title=release_title,
            release_notes=release_body,
            release_url=html_url,
            published_at=published_at,
            message=(
                f"Release v{clean_latest} asset {EXPECTED_RELEASE_ASSET_NAME} is still uploading "
                f"(state='{asset_state}')."
            ),
        )

    dl_url = str(matched_asset.get("browser_download_url") or "").strip()
    if not is_valid_github_url(dl_url, require_repo_prefix=True) or not dl_url.endswith(
        "/" + EXPECTED_RELEASE_ASSET_NAME
    ):
        return UpdateCheckResult(
            status="error",
            current_version=current_version,
            latest_version=clean_latest,
            release_url=html_url,
            message=f"Rejected invalid download URL for {EXPECTED_RELEASE_ASSET_NAME}: {dl_url}",
        )

    try:
        asset_size = int(matched_asset.get("size") or 0)
    except Exception:
        asset_size = 0

    if asset_size < MIN_EXE_SIZE_BYTES or asset_size > MAX_EXE_SIZE_BYTES:
        return UpdateCheckResult(
            status="error",
            current_version=current_version,
            latest_version=clean_latest,
            release_url=html_url,
            message=(
                f"Release asset {EXPECTED_RELEASE_ASSET_NAME} has invalid size "
                f"({asset_size:,} bytes)."
            ),
        )

    sha256_hex, sha_reason = _extract_asset_sha256(
        matched_asset, release_body=release_body, asset_name=EXPECTED_RELEASE_ASSET_NAME
    )
    if not sha256_hex:
        return UpdateCheckResult(
            status="error",
            current_version=current_version,
            latest_version=clean_latest,
            release_url=html_url,
            message=sha_reason,
        )

    return UpdateCheckResult(
        status="update_available",
        current_version=current_version,
        latest_version=clean_latest,
        release_title=release_title,
        release_notes=release_body,
        release_url=html_url,
        download_url=dl_url,
        asset_name=EXPECTED_RELEASE_ASSET_NAME,
        asset_size=asset_size,
        expected_sha256=sha256_hex,
        published_at=published_at,
        message=f"HDRSnip Fusion v{clean_latest} is available.",
    )


def fetch_latest_github_release(
    api_url: str = GITHUB_LATEST_RELEASE_API_URL,
    current_version: str = APP_VERSION,
    timeout: float = 12.0,
) -> UpdateCheckResult:
    """
    Queries the official GitHub Releases API over HTTPS with bounded timeout and response size.
    Handles offline networks, DNS failures, and HTTP 403/429 rate limits gracefully.
    """
    if not is_valid_github_url(api_url, require_repo_prefix=False):
        return UpdateCheckResult(
            status="error",
            current_version=current_version,
            message=f"Refusing to query untrusted update URL: {api_url}",
        )

    opener = urllib.request.build_opener(_SafeGitHubRedirectHandler())
    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"HDRSnipFusion/{current_version} (Windows; +https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME})",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )

    try:
        with opener.open(req, timeout=timeout) as resp:
            raw_bytes = resp.read(MAX_API_RESPONSE_BYTES + 1)
            if len(raw_bytes) > MAX_API_RESPONSE_BYTES:
                return UpdateCheckResult(
                    status="error",
                    current_version=current_version,
                    message="GitHub API response exceeded maximum allowed size (2 MB).",
                )
            data = json.loads(raw_bytes.decode("utf-8", errors="replace"))
            return parse_github_release_payload(data, current_version=current_version)
    except urllib.error.HTTPError as http_err:
        code = int(getattr(http_err, "code", 0) or 0)
        if code == 404:
            return UpdateCheckResult(
                status="up_to_date",
                current_version=current_version,
                latest_version=current_version,
                message=f"You're running the latest version (v{current_version}).",
            )
        if code in (403, 429):
            return UpdateCheckResult(
                status="rate_limited",
                current_version=current_version,
                message="GitHub API rate limit reached. Please try again later.",
            )
        return UpdateCheckResult(
            status="error",
            current_version=current_version,
            message=f"GitHub API returned HTTP {code}.",
        )
    except urllib.error.URLError as url_err:
        return UpdateCheckResult(
            status="offline",
            current_version=current_version,
            message=f"Unable to reach GitHub Releases ({url_err.reason}).",
        )
    except Exception as exc:
        return UpdateCheckResult(
            status="error",
            current_version=current_version,
            message=f"Update check failed: {exc}",
        )


def download_and_stage_release_asset(
    check_result: UpdateCheckResult,
    staging_root: Path = LOCAL_UPDATE_ROOT_DIR,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout: float = 25.0,
    min_exe_size: int = MIN_EXE_SIZE_BYTES,
) -> Path:
    r"""
    Downloads `HDRSnipFusion.exe` over HTTPS into `%LOCALAPPDATA%\HDRSnip Fusion\updates\v<ver>\`:
      1. Uses a temporary `.part` file during streaming.
      2. Enforces expected file size and maximum byte bounds.
      3. Computes SHA-256 while streaming and re-verifies the finished file on disk.
      4. Validates 64-bit Windows PE executable headers (`MZ`, `PE\0\0`, `AMD64`, `PE32+`).
      5. Calls `verify_authenticode_signature()`.
      6. Atomically renames `.part` -> `HDRSnipFusion.exe` and writes `staged_metadata.json`
         only after every check passes. Rejects and deletes partial files on any failure.
    """
    if not check_result.is_update_ready:
        raise UpdateVerificationError("UpdateCheckResult does not contain a downloadable verified release.")
    if check_result.asset_name != EXPECTED_RELEASE_ASSET_NAME:
        raise UpdateVerificationError(
            f"Unexpected release asset name '{check_result.asset_name}' (expected '{EXPECTED_RELEASE_ASSET_NAME}')."
        )
    if not is_valid_github_url(check_result.download_url, require_repo_prefix=True):
        raise UpdateVerificationError(
            f"Refusing to download from untrusted URL: {check_result.download_url}"
        )

    expected_sha = check_result.expected_sha256.strip().lower()
    if len(expected_sha) != 64 or not all(c in "0123456789abcdef" for c in expected_sha):
        raise UpdateVerificationError("Missing or malformed expected SHA-256 digest.")

    clean_ver = format_semver(check_result.latest_version)
    version_dir = Path(staging_root).resolve() / f"v{clean_ver}"
    version_dir.mkdir(parents=True, exist_ok=True)

    final_staged_exe = version_dir / EXPECTED_RELEASE_ASSET_NAME
    part_path = version_dir / f"{EXPECTED_RELEASE_ASSET_NAME}.{os.getpid()}.part"

    # If already staged and verified on disk with exact SHA-256 and valid PE64 structure, reuse it
    if final_staged_exe.exists():
        try:
            existing_sha = compute_file_sha256(final_staged_exe)
            pe_ok, _ = validate_windows_pe_executable(
                final_staged_exe, min_size=min_exe_size, max_size=MAX_EXE_SIZE_BYTES
            )
            if hmac.compare_digest(existing_sha, expected_sha) and pe_ok:
                if progress_callback is not None:
                    sz = final_staged_exe.stat().st_size
                    progress_callback(sz, sz)
                return final_staged_exe
        except Exception:
            pass
        try:
            final_staged_exe.unlink()
        except OSError:
            pass

    opener = urllib.request.build_opener(_SafeGitHubRedirectHandler())
    req = urllib.request.Request(
        check_result.download_url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": f"HDRSnipFusion/{APP_VERSION} (+https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME})",
        },
        method="GET",
    )

    hasher = hashlib.sha256()
    bytes_read = 0
    expected_total = int(check_result.asset_size)

    try:
        with opener.open(req, timeout=timeout) as resp, open(part_path, "wb") as out_fh:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise UpdateVerificationError("Update download was cancelled.")
                chunk = resp.read(65536)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > MAX_EXE_SIZE_BYTES or (
                    expected_total > 0 and bytes_read > expected_total
                ):
                    raise UpdateVerificationError(
                        f"Downloaded data ({bytes_read:,} bytes) exceeded expected asset size ({expected_total:,} bytes)."
                    )
                hasher.update(chunk)
                out_fh.write(chunk)
                if progress_callback is not None:
                    progress_callback(bytes_read, expected_total)

            out_fh.flush()
            try:
                os.fsync(out_fh.fileno())
            except OSError:
                pass

        if expected_total > 0 and bytes_read != expected_total:
            raise UpdateVerificationError(
                f"Incomplete download: received {bytes_read:,} of {expected_total:,} bytes."
            )

        stream_sha = hasher.hexdigest().lower()
        if not hmac.compare_digest(stream_sha, expected_sha):
            raise UpdateVerificationError(
                f"SHA-256 verification failed (expected {expected_sha[:16]}..., got {stream_sha[:16]}...)."
            )

        disk_sha = compute_file_sha256(part_path)
        if not hmac.compare_digest(disk_sha, expected_sha):
            raise UpdateVerificationError(
                "On-disk SHA-256 verification failed after writing staging file."
            )

        pe_ok, pe_reason = validate_windows_pe_executable(
            part_path, min_size=min_exe_size, max_size=MAX_EXE_SIZE_BYTES
        )
        if not pe_ok:
            raise UpdateVerificationError(
                f"Downloaded file failed Windows PE executable validation: {pe_reason}"
            )

        auth_ok, auth_reason = verify_authenticode_signature(part_path)
        if not auth_ok:
            raise UpdateVerificationError(
                f"Authenticode signature verification failed: {auth_reason}"
            )

        os.replace(str(part_path), str(final_staged_exe))

        meta_path = version_dir / "staged_metadata.json"
        meta_payload = {
            "version": clean_ver,
            "asset_name": EXPECTED_RELEASE_ASSET_NAME,
            "asset_size": bytes_read,
            "sha256": expected_sha,
            "release_url": check_result.release_url,
            "download_url": check_result.download_url,
            "staged_at_epoch": time.time(),
        }
        meta_path.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
        DIAG_LOG.milestone(
            "UPDATE_STAGE",
            f"Staged and verified HDRSnip Fusion v{clean_ver} at '{final_staged_exe}' "
            f"(size={bytes_read:,} bytes, sha256={expected_sha})",
        )
        return final_staged_exe
    except Exception:
        try:
            if part_path.exists():
                part_path.unlink()
        except OSError:
            pass
        raise


ACTIVE_TRANSACTION_LOCK_FILENAME: str = ".active_update_transaction.lock"
ACTIVE_TRANSACTION_MAX_AGE_SEC: float = 1800.0  # 30 minutes protection window


def _is_updater_transaction_mutex_active() -> bool:
    """
    Returns True if a Windows `Local\HDRSnipFusion_UpdaterTransaction` mutex
    is currently held by an active updater helper process.
    """
    if sys.platform != "win32":
        return False
    try:
        _ensure_win32_ctypes_signatures()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        SYNCHRONIZE = 0x00100000
        kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.OpenMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = wintypes.BOOL
        h_mutex = kernel32.OpenMutexW(
            SYNCHRONIZE, False, r"Local\HDRSnipFusion_UpdaterTransaction"
        )
        if h_mutex:
            kernel32.CloseHandle(ctypes.c_void_p(h_mutex))
            return True
    except Exception:
        pass
    return False


def _directory_has_active_update_transaction(
    version_dir: Path,
    now_epoch: Optional[float] = None,
    max_age_sec: float = ACTIVE_TRANSACTION_MAX_AGE_SEC,
) -> bool:
    """
    Returns True if `version_dir` contains an active update transaction lock,
    a recent `update_manifest.json`, or any pending `startup_confirm_*.json` file.
    Prevents premature staging cleanup while the updater helper or restarted child
    is still completing startup verification or rollback.
    """
    now = time.time() if now_epoch is None else float(now_epoch)
    try:
        if not version_dir.exists() or not version_dir.is_dir():
            return False

        lock_file = version_dir / ACTIVE_TRANSACTION_LOCK_FILENAME
        if lock_file.exists():
            try:
                age = now - lock_file.stat().st_mtime
                if age <= max_age_sec:
                    try:
                        lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
                        helper_pid = int(lock_data.get("helper_pid") or lock_data.get("pid") or 0)
                        if helper_pid <= 0 or _is_process_alive(helper_pid) or age <= 60.0:
                            return True
                    except Exception:
                        return True
            except OSError:
                return True

        manifest_file = version_dir / "update_manifest.json"
        if manifest_file.exists():
            try:
                if (now - manifest_file.stat().st_mtime) <= max_age_sec:
                    return True
            except OSError:
                return True

        for confirm_candidate in version_dir.glob("startup_confirm_*.json"):
            try:
                if (now - confirm_candidate.stat().st_mtime) <= max_age_sec:
                    return True
            except OSError:
                return True
    except Exception:
        return True
    return False


def cleanup_stale_update_staging(
    current_version: str = APP_VERSION,
    staging_root: Path = LOCAL_UPDATE_ROOT_DIR,
    protect_confirm_file: Optional[Path] = None,
) -> None:
    r"""
    Removes staging subdirectories for versions `<= current_version`, leftover `.part`
    files, or stale helper binaries so `%LOCALAPPDATA%\HDRSnip Fusion\updates` stays clean.
    Strictly protects any staging directory that has an active update transaction
    (`.active_update_transaction.lock`, `update_manifest.json`, `startup_confirm_*.json`,
    or `Local\HDRSnipFusion_UpdaterTransaction` mutex) so active verification or rollback
    files are never deleted mid-transaction.
    """
    try:
        root = Path(staging_root)
        if not root.exists() or not root.is_dir():
            return
        if _is_updater_transaction_mutex_active():
            DIAG_LOG.log(
                "UPDATE_CLEANUP",
                "Skipping staging cleanup because Local\HDRSnipFusion_UpdaterTransaction is active.",
            )
            return

        protected_dir: Optional[Path] = None
        if protect_confirm_file is not None:
            try:
                protected_dir = Path(protect_confirm_file).resolve().parent
            except Exception:
                protected_dir = None

        now = time.time()
        for child in list(root.iterdir()):
            try:
                if child.is_dir() and child.name.lower().startswith("v"):
                    child_resolved = child.resolve()
                    if protected_dir is not None and child_resolved == protected_dir:
                        continue
                    if _directory_has_active_update_transaction(child_resolved, now_epoch=now):
                        DIAG_LOG.log(
                            "UPDATE_CLEANUP",
                            f"Preserving active update transaction directory '{child_resolved}'.",
                        )
                        continue

                    ver_str = child.name[1:]
                    if not is_newer_semver(ver_str, current_version):
                        shutil.rmtree(child, ignore_errors=True)
                        continue
                    # Clean up any leftover helper copy inside newer staging dirs only when idle
                    helper_copy = child / "HDRSnipFusion_UpdaterHelper.exe"
                    if helper_copy.exists():
                        try:
                            helper_copy.unlink()
                        except OSError:
                            pass
                elif child.is_file():
                    if (
                        child.suffix.lower() in (".part", ".tmp")
                        and (now - child.stat().st_mtime) > 300.0
                    ) or (now - child.stat().st_mtime) > _SEVEN_DAYS_SEC:
                        child.unlink()
            except Exception:
                pass
    except Exception as exc:
        DIAG_LOG.warning("UPDATE_CLEANUP", f"Staging cleanup note: {exc}")


def prepare_staged_update_transaction(
    staged_exe: Path,
    target_version: str,
    expected_sha256: str,
    target_exe: Optional[Path] = None,
    restart_after_update: bool = True,
    staging_root: Path = LOCAL_UPDATE_ROOT_DIR,
    min_exe_size: int = MIN_EXE_SIZE_BYTES,
) -> Tuple[Path, Path]:
    """
    Prepares a safe, self-contained update replacement transaction:
      1. Re-verifies `staged_exe` SHA-256 and 64-bit Windows PE headers.
      2. Verifies `target_exe` is not in a protected / read-only directory.
      3. Creates an independent helper executable copy (`HDRSnipFusion_UpdaterHelper.exe`)
         from the currently installed, known-good `target_exe` (whenever it exists on disk,
         falling back to `staged_exe` only if `target_exe` does not yet exist) so the helper
         process is guaranteed to boot Python and perform rollback even if `staged_exe` is
         corrupt or fails to start Python.
      4. Writes `.active_update_transaction.lock` and `update_manifest.json` inside the
         staging folder to protect all transaction files from premature cleanup.
    Returns `(helper_exe_path, manifest_path)`.
    """
    staged_resolved = Path(staged_exe).resolve()
    root_resolved = Path(staging_root).resolve()
    try:
        staged_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise UpdateVerificationError(
            f"Staged executable '{staged_resolved}' is outside staging root '{root_resolved}'."
        ) from exc

    expected_sha = str(expected_sha256 or "").strip().lower()
    if len(expected_sha) != 64 or not all(c in "0123456789abcdef" for c in expected_sha):
        raise UpdateVerificationError("Invalid expected SHA-256 for staged transaction.")

    actual_sha = compute_file_sha256(staged_resolved)
    if not hmac.compare_digest(actual_sha, expected_sha):
        raise UpdateVerificationError(
            "Staged executable SHA-256 does not match expected digest."
        )

    pe_ok, pe_reason = validate_windows_pe_executable(
        staged_resolved, min_size=min_exe_size, max_size=MAX_EXE_SIZE_BYTES
    )
    if not pe_ok:
        raise UpdateVerificationError(
            f"Staged executable failed PE validation: {pe_reason}"
        )

    dest_exe = Path(target_exe or get_current_executable_path()).resolve()
    if dest_exe.suffix.lower() != ".exe":
        raise UpdateVerificationError(
            f"Refusing to replace non-EXE target path: '{dest_exe}'"
        )

    is_prot, prot_reason = is_protected_install_location(dest_exe)
    if is_prot:
        raise PermissionError(prot_reason)

    version_dir = staged_resolved.parent
    lock_path = version_dir / ACTIVE_TRANSACTION_LOCK_FILENAME
    write_atomic_json_file(
        lock_path,
        {
            "status": "preparing",
            "source_version": APP_VERSION,
            "target_version": format_semver(target_version),
            "pid": os.getpid(),
            "created_at_epoch": time.time(),
        },
    )

    # Copy the updater helper from the currently running, known-good executable (`dest_exe`)
    # whenever available so recovery/rollback never depends on the untested `staged_resolved`
    # being able to start Python!
    helper_source = dest_exe if dest_exe.exists() else staged_resolved
    expected_helper_sha = compute_file_sha256(helper_source)
    helper_exe = version_dir / "HDRSnipFusion_UpdaterHelper.exe"
    shutil.copy2(helper_source, helper_exe)
    helper_sha = compute_file_sha256(helper_exe)
    if not hmac.compare_digest(helper_sha, expected_helper_sha):
        raise UpdateVerificationError("Failed to verify helper executable copy.")

    manifest_path = version_dir / "update_manifest.json"
    manifest_data = {
        "schema_version": 2,
        "source_version": APP_VERSION,
        "target_version": format_semver(target_version),
        "target_exe": str(dest_exe),
        "staged_exe": str(staged_resolved),
        "helper_exe": str(helper_exe),
        "helper_source_exe": str(helper_source),
        "helper_sha256": helper_sha,
        "expected_sha256": expected_sha,
        "min_exe_size": int(min_exe_size),
        "parent_pid": os.getpid(),
        "restart_after_update": bool(restart_after_update),
        "created_at_epoch": time.time(),
    }
    write_atomic_json_file(manifest_path, manifest_data)
    return (helper_exe, manifest_path)


def _build_clean_pyinstaller_env() -> Dict[str, str]:
    """
    Constructs a clean environment dictionary for spawning an independent PyInstaller
    `--onefile` process. Sets `PYINSTALLER_RESET_ENVIRONMENT=1` and removes inherited
    `_MEIPASS2` variables so the child bootloader creates its own temporary extraction
    directory instead of colliding with the exiting parent's `_MEIxxxxxx` folder.
    """
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for k in list(env.keys()):
        if k.upper().startswith("_MEI"):
            env.pop(k, None)
    return env


def launch_staged_update_helper(
    helper_exe: Path,
    manifest_path: Path,
) -> subprocess.Popen:
    """
    Launches the independent updater helper process with `shell=False` and clean
    PyInstaller environment reset flags.
    """
    env = _build_clean_pyinstaller_env()
    creationflags = 0
    if sys.platform == "win32":
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

    cmd = [
        str(Path(helper_exe).resolve()),
        "--apply-staged-update",
        str(Path(manifest_path).resolve()),
    ]
    DIAG_LOG.milestone(
        "UPDATE_LAUNCH_HELPER",
        f"Spawning updater helper: {cmd}",
        flush_disk=True,
    )
    return subprocess.Popen(
        cmd,
        env=env,
        cwd=str(Path(helper_exe).resolve().parent),
        close_fds=True,
        creationflags=creationflags,
        shell=False,
    )


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _enumerate_process_parent_map() -> Dict[int, int]:
    """
    Returns a snapshot mapping `{pid: parent_pid}` for active OS processes.
    Uses Win32 `CreateToolhelp32Snapshot` on Windows and `/proc/<pid>/stat` (with `ps`
    fallback) on POSIX systems. Used to verify PyInstaller `--onefile` bootloader->child
    process ancestry and to terminate entire process trees on rollback.
    """
    parent_map: Dict[int, int] = {}
    if sys.platform == "win32":
        TH32CS_SNAPPROCESS = 0x00000002
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
            kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
            kernel32.Process32FirstW.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_PROCESSENTRY32W),
            ]
            kernel32.Process32FirstW.restype = wintypes.BOOL
            kernel32.Process32NextW.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_PROCESSENTRY32W),
            ]
            kernel32.Process32NextW.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = wintypes.BOOL

            h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if not h_snap or h_snap == INVALID_HANDLE_VALUE:
                return parent_map
            try:
                pe = _PROCESSENTRY32W()
                pe.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
                if kernel32.Process32FirstW(ctypes.c_void_p(h_snap), ctypes.byref(pe)):
                    while True:
                        parent_map[int(pe.th32ProcessID)] = int(pe.th32ParentProcessID)
                        if not kernel32.Process32NextW(
                            ctypes.c_void_p(h_snap), ctypes.byref(pe)
                        ):
                            break
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(h_snap))
        except Exception:
            pass
        return parent_map

    proc_root = Path("/proc")
    if proc_root.exists():
        for entry in proc_root.iterdir():
            if entry.name.isdigit():
                try:
                    stat_text = (entry / "stat").read_text(encoding="utf-8", errors="replace")
                    rpar = stat_text.rfind(")")
                    if rpar != -1:
                        fields = stat_text[rpar + 2 :].split()
                        state = fields[0] if fields else ""
                        if state != "Z" and len(fields) >= 2:
                            parent_map[int(entry.name)] = int(fields[1])
                except Exception:
                    pass
    return parent_map


def _is_pid_descendant_of(
    child_pid: int,
    ancestor_pid: int,
    parent_map: Optional[Dict[int, int]] = None,
    max_depth: int = 12,
) -> bool:
    """
    Returns True if `child_pid == ancestor_pid` or `child_pid` is a child/descendant
    of `ancestor_pid` in `parent_map` (such as a PyInstaller `--onefile` Python child
    spawned by the `ancestor_pid` native bootloader process).
    """
    if child_pid <= 0 or ancestor_pid <= 0:
        return False
    if int(child_pid) == int(ancestor_pid):
        return True
    pmap = _enumerate_process_parent_map() if parent_map is None else parent_map
    curr = int(child_pid)
    visited = set()
    for _ in range(max_depth):
        if curr in visited:
            break
        visited.add(curr)
        parent = pmap.get(curr)
        if parent is None or parent <= 0:
            break
        if int(parent) == int(ancestor_pid):
            return True
        curr = int(parent)
    return False


def _query_process_executable_path(pid: int) -> Optional[Path]:
    """
    Queries the OS for the executable image path of `pid`.
    Uses `QueryFullProcessImageNameW` on Windows and `/proc/<pid>/exe` on Linux.
    Returns `None` if the process has already exited or cannot be queried.
    """
    if pid <= 0:
        return None
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.QueryFullProcessImageNameW.argtypes = [
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = wintypes.BOOL

            h_proc = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not h_proc:
                return None
            try:
                buf_len = wintypes.DWORD(1024)
                buf = ctypes.create_unicode_buffer(1024)
                if kernel32.QueryFullProcessImageNameW(
                    ctypes.c_void_p(h_proc), 0, buf, ctypes.byref(buf_len)
                ):
                    raw_path = buf.value.strip()
                    if raw_path:
                        return Path(raw_path).resolve()
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(h_proc))
        except Exception:
            pass
        return None

    proc_exe = Path(f"/proc/{int(pid)}/exe")
    try:
        if proc_exe.exists():
            return proc_exe.resolve()
    except Exception:
        pass
    return None


def _is_process_alive(pid: int) -> bool:
    """Returns True if process `pid` is currently running (and not a zombie on POSIX)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x00000102
        try:
            kernel32 = ctypes.windll.kernel32
            h_proc = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if not h_proc:
                return False
            try:
                res = kernel32.WaitForSingleObject(ctypes.c_void_p(h_proc), 0)
                return res == WAIT_TIMEOUT
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(h_proc))
        except Exception:
            return False

    stat_path = Path(f"/proc/{int(pid)}/stat")
    if stat_path.exists():
        try:
            txt = stat_path.read_text(encoding="utf-8", errors="replace")
            rpar = txt.rfind(")")
            if rpar != -1:
                fields = txt[rpar + 2 :].split()
                if fields and fields[0] == "Z":
                    return False
        except Exception:
            pass
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _collect_process_tree_pids(
    root_pid: int,
    extra_pids: Optional[Sequence[int]] = None,
) -> List[int]:
    """
    Discovers all child and descendant PIDs of `root_pid` (plus any `extra_pids`,
    such as the child Python PID reported in `startup_confirm_*.json`) in bottom-up
    order (deepest descendants first, `root_pid` last).
    """
    pmap = _enumerate_process_parent_map()
    children_of: Dict[int, List[int]] = {}
    for pid, ppid in pmap.items():
        children_of.setdefault(ppid, []).append(pid)

    seeds: List[int] = []
    if root_pid and root_pid > 0:
        seeds.append(int(root_pid))
    if extra_pids:
        for ep in extra_pids:
            if ep and int(ep) > 0 and int(ep) not in seeds:
                seeds.append(int(ep))

    ordered: List[int] = []
    visited = set()

    def _dfs(pid: int) -> None:
        if pid in visited or pid <= 0 or pid == os.getpid():
            return
        visited.add(pid)
        for ch in children_of.get(pid, []):
            _dfs(ch)
        ordered.append(pid)

    for s_pid in seeds:
        _dfs(s_pid)
    return ordered


def _terminate_Single_pid(pid: int, force: bool = False) -> None:
    """Sends a termination signal to a single `pid` (excluding our own process)."""
    if pid <= 0 or pid == os.getpid():
        return
    if sys.platform == "win32":
        PROCESS_TERMINATE = 0x0001
        try:
            kernel32 = ctypes.windll.kernel32
            h_proc = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
            if h_proc:
                try:
                    kernel32.TerminateProcess(ctypes.c_void_p(h_proc), 1)
                finally:
                    kernel32.CloseHandle(ctypes.c_void_p(h_proc))
        except Exception:
            pass
    else:
        import signal as _signal

        sig = _signal.SIGKILL if force else _signal.SIGTERM
        try:
            os.kill(int(pid), sig)
        except OSError:
            pass


def _terminate_process_tree_safely(
    proc: Optional[subprocess.Popen],
    timeout_sec: float = 5.0,
    extra_pids: Optional[Sequence[int]] = None,
) -> List[int]:
    """
    Terminates an entire PyInstaller `--onefile` process tree—including the separate
    Python child process and any grandchildren as well as the bootloader parent `proc`—
    and waits for all of them to exit so all file locks on `target_exe` and `_MEIxxxxxx`
    are released before rollback.
    """
    root_pid = int(proc.pid) if (proc is not None and proc.pid) else 0
    tree_pids = _collect_process_tree_pids(root_pid, extra_pids=extra_pids)
    if not tree_pids and proc is None:
        return []

    # 1. Terminate all descendant/child processes first, then the root bootloader
    for pid in tree_pids:
        _terminate_Single_pid(pid, force=False)
    if proc is not None:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

    deadline = time.monotonic() + max(0.5, float(timeout_sec))
    while time.monotonic() < deadline:
        # Re-scan in case the bootloader spawned a child just as we were terminating
        current_tree = _collect_process_tree_pids(root_pid, extra_pids=tree_pids)
        for pid in current_tree:
            if pid not in tree_pids:
                tree_pids.append(pid)
                _terminate_Single_pid(pid, force=False)
        alive = [pid for pid in tree_pids if _is_process_alive(pid)]
        if not alive and (proc is None or proc.poll() is not None):
            break
        time.sleep(0.05)

    # 2. Force-kill any remaining processes in the tree
    for pid in tree_pids:
        if _is_process_alive(pid):
            _terminate_Single_pid(pid, force=True)
    if proc is not None:
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=1.5)
        except Exception:
            pass

    for pid in tree_pids:
        if _is_process_alive(pid):
            _wait_for_process_exit(pid, timeout_sec=1.5)

    return tree_pids


def _terminate_process_safely(
    proc: Optional[subprocess.Popen],
    timeout_sec: float = 4.0,
    extra_pids: Optional[Sequence[int]] = None,
) -> List[int]:
    """Alias for `_terminate_process_tree_safely` ensuring child + bootloader termination."""
    return _terminate_process_tree_safely(
        proc, timeout_sec=timeout_sec, extra_pids=extra_pids
    )


def _wait_for_process_exit(pid: int, timeout_sec: float = 25.0) -> bool:
    """Waits for process `pid` to terminate."""
    if pid <= 0 or pid == os.getpid():
        return True
    deadline = time.monotonic() + max(0.5, float(timeout_sec))
    if sys.platform == "win32":
        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0x00000000
        kernel32 = ctypes.windll.kernel32
        h_proc = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if h_proc:
            try:
                wait_ms = int(max(100.0, (deadline - time.monotonic()) * 1000.0))
                res = kernel32.WaitForSingleObject(ctypes.c_void_p(h_proc), wait_ms)
                return res == WAIT_OBJECT_0
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(h_proc))
        return True

    while time.monotonic() < deadline:
        if not _is_process_alive(pid):
            return True
        time.sleep(0.06)
    return False


def _wait_for_file_unlocked(target_exe: Path, timeout_sec: float = 30.0) -> bool:
    """
    Polls until `target_exe` is no longer locked by the exiting application or its
    PyInstaller `--onefile` parent bootloader.
    """
    deadline = time.monotonic() + max(0.5, float(timeout_sec))
    while time.monotonic() < deadline:
        if not target_exe.exists():
            return True
        try:
            with open(target_exe, "r+b"):
                return True
        except OSError:
            time.sleep(0.12)
    return False


STARTUP_CONFIRM_TIMEOUT_SEC: float = 15.0


def get_backup_executable_path(target_exe: Optional[Path] = None) -> Path:
    """Returns the sibling `.bak` path for `target_exe`."""
    t = Path(target_exe or get_current_executable_path()).resolve()
    return t.with_name(t.name + ".bak")


def get_pending_update_marker_path(target_exe: Optional[Path] = None) -> Path:
    """
    Returns the sibling `.pending_verify.json` marker path used by the independent
    updater helper while startup verification is in progress.
    """
    t = Path(target_exe or get_current_executable_path()).resolve()
    return t.with_name(t.name + ".pending_verify.json")


def write_atomic_json_file(target_file: Path, payload: Dict[str, Any]) -> None:
    """Writes `payload` as UTF-8 JSON to a `.tmp` sibling, flushes + fsyncs, and atomically replaces `target_file`."""
    dest = Path(target_file).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{time.perf_counter_ns()}.tmp")
    try:
        raw = json.dumps(payload, indent=2)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(str(tmp), str(dest))
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def write_startup_confirmation_file(
    confirm_file_path: Path,
    version: str = APP_VERSION,
    pid: Optional[int] = None,
    ppid: Optional[int] = None,
    token: str = "",
    executable_path: Optional[Path] = None,
) -> None:
    """
    Writes an explicit startup readiness confirmation payload to `confirm_file_path`
    after the application has initialized its Qt event loop, tray icon, and hotkey listener.
    Includes the per-update cryptographic `token`, `pid` (`os.getpid()`), `ppid`
    (`os.getppid()`, which equals the PyInstaller `--onefile` bootloader PID), and
    resolved `executable` path.
    """
    eff_token = str(
        token or os.environ.get("HDRSNIP_STARTUP_CONFIRM_TOKEN", "")
    ).strip()
    exe_resolved = str(
        Path(executable_path or get_current_executable_path()).resolve()
    )
    payload = {
        "status": "ready",
        "app": "HDRSnip Fusion",
        "version": format_semver(version),
        "tag": f"v{format_semver(version)}",
        "token": eff_token,
        "pid": int(os.getpid() if pid is None else pid),
        "ppid": int(os.getppid() if ppid is None else ppid),
        "executable": exe_resolved,
        "packaged": is_packaged_exe(),
        "timestamp": time.time(),
    }
    write_atomic_json_file(Path(confirm_file_path), payload)


def _restore_backup_executable(target_exe: Path, backup_exe: Path) -> bool:
    """
    Restores `backup_exe` -> `target_exe` safely via an atomic temporary copy so
    `backup_exe` is never lost if the restore itself is interrupted.
    """
    target_exe = Path(target_exe).resolve()
    backup_exe = Path(backup_exe).resolve()
    if not backup_exe.exists():
        return False
    restore_tmp = target_exe.with_name(f".{target_exe.name}.restore.{os.getpid()}.tmp")
    try:
        shutil.copy2(backup_exe, restore_tmp)
        with open(restore_tmp, "r+b") as fh:
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(str(restore_tmp), str(target_exe))
        return True
    except Exception as exc:
        DIAG_LOG.error(
            "UPDATE_RESTORE",
            f"Failed to restore backup '{backup_exe}' -> '{target_exe}'",
            exc,
        )
        try:
            if restore_tmp.exists():
                restore_tmp.unlink()
        except OSError:
            pass
        return False


def recover_interrupted_update_if_needed(
    target_exe: Optional[Path] = None,
    current_version: str = APP_VERSION,
) -> bool:
    """
    Checks whether `target_exe` is missing while `backup_exe` exists (for example,
    when invoked by an external tool or test).
    Note: Actual update verification and automatic rollback are ALWAYS performed
    out-of-process by the independent `HDRSnipFusion_UpdaterHelper.exe` (copied from
    the known-good previous version), never by relying on a potentially broken updated
    EXE starting Python or replacing itself while running.
    """
    dest = Path(target_exe or get_current_executable_path()).resolve()
    backup_exe = get_backup_executable_path(dest)
    if not dest.exists() and backup_exe.exists():
        if _restore_backup_executable(dest, backup_exe):
            DIAG_LOG.milestone(
                "UPDATE_RECOVERY",
                f"Restored missing executable '{dest}' from backup '{backup_exe}'",
                flush_disk=True,
            )
            return True
    return False


def finalize_pending_update_verification(
    target_exe: Optional[Path] = None,
    current_version: str = APP_VERSION,
) -> bool:
    """
    Cleans up any leftover `.pending_verify.json` or `.bak` sibling files once startup
    confirmation has completed and no updater helper transaction is active.
    """
    if _is_updater_transaction_mutex_active():
        return False
    dest = Path(target_exe or get_current_executable_path()).resolve()
    backup_exe = get_backup_executable_path(dest)
    marker_path = get_pending_update_marker_path(dest)
    cleaned_any = False

    if marker_path.exists():
        try:
            marker_path.unlink()
            cleaned_any = True
        except OSError:
            pass

    if backup_exe.exists():
        try:
            backup_exe.unlink()
            cleaned_any = True
        except OSError:
            pass

    if cleaned_any:
        DIAG_LOG.milestone(
            "UPDATE_VERIFIED_HEALTHY",
            f"Cleaned residual update backup/marker files for v{current_version} at '{dest}'.",
            flush_disk=True,
        )
    return cleaned_any


def perform_atomic_exe_replacement(
    target_exe: Path,
    staged_exe: Path,
    expected_sha256: str,
    min_exe_size: int = MIN_EXE_SIZE_BYTES,
) -> Tuple[bool, str, Optional[Path]]:
    """
    Safely backs up `target_exe` to `target_exe.bak` and atomically replaces `target_exe`
    with a verified copy of `staged_exe`:
      1. If `target_exe` is missing while `target_exe.bak` exists from an interrupted update,
         restores `target_exe` from `target_exe.bak` first.
      2. Preserves the previous working version in `target_exe.bak` via atomic copy
         (`.bak.tmp` -> `fsync` -> `os.replace` to `.bak`) BEFORE modifying `target_exe`,
         so `target_exe` is never missing on disk even if power is lost mid-update, and
         an existing valid `.bak` is never destroyed if `target_exe` already holds an
         unverified retry binary.
      3. Copies and verifies `staged_exe` into `target_exe.new` (`fsync` + SHA-256 readback).
      4. Atomically replaces `target_exe.new` -> `target_exe` via `os.replace` and verifies
         the post-swap SHA-256 of `target_exe`.
      5. Never deletes `target_exe.bak` — the caller preserves `target_exe.bak` until the
         newly installed executable explicitly confirms healthy startup!
    Returns `(success, message, backup_path)`.
    """
    target_exe = Path(target_exe).resolve()
    staged_exe = Path(staged_exe).resolve()
    expected_sha = str(expected_sha256 or "").strip().lower()

    if not staged_exe.exists():
        return (False, f"Staged executable not found: {staged_exe}", None)
    if not hmac.compare_digest(compute_file_sha256(staged_exe), expected_sha):
        return (
            False,
            "Staged executable failed SHA-256 verification before replacement.",
            None,
        )
    pe_ok, pe_reason = validate_windows_pe_executable(
        staged_exe, min_size=min_exe_size, max_size=MAX_EXE_SIZE_BYTES
    )
    if not pe_ok:
        return (False, f"Staged executable failed PE check: {pe_reason}", None)

    backup_exe = get_backup_executable_path(target_exe)
    backup_tmp = target_exe.with_name(target_exe.name + ".bak.tmp")
    temp_new_exe = target_exe.with_name(target_exe.name + ".new")

    # 0. If target_exe is missing due to a previously interrupted swap, restore from backup_exe first
    if not target_exe.exists() and backup_exe.exists():
        _restore_backup_executable(target_exe, backup_exe)

    # 1. Stage and verify `.new` alongside target_exe before touching target_exe or backup_exe
    try:
        shutil.copy2(staged_exe, temp_new_exe)
        with open(temp_new_exe, "r+b") as fh:
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        if not hmac.compare_digest(compute_file_sha256(temp_new_exe), expected_sha):
            raise UpdateVerificationError(
                "Copied .new executable failed SHA-256 readback check."
            )
    except Exception as exc:
        try:
            if temp_new_exe.exists():
                temp_new_exe.unlink()
        except OSError:
            pass
        return (
            False,
            f"Failed to stage temporary .new executable in target folder: {exc}",
            backup_exe if backup_exe.exists() else None,
        )

    # 2. Create or preserve a verified backup of the previous working executable in `backup_exe`
    has_backup = backup_exe.exists()
    try:
        if target_exe.exists():
            current_target_sha = compute_file_sha256(target_exe)
            # Only overwrite backup_exe if target_exe is not already the staged target binary
            # OR if no backup_exe exists yet. This prevents a retry from clobbering the good backup!
            if not has_backup or not hmac.compare_digest(
                current_target_sha, expected_sha
            ):
                shutil.copy2(target_exe, backup_tmp)
                with open(backup_tmp, "r+b") as fh:
                    fh.flush()
                    try:
                        os.fsync(fh.fileno())
                    except OSError:
                        pass
                if not hmac.compare_digest(
                    compute_file_sha256(backup_tmp), current_target_sha
                ):
                    raise UpdateVerificationError(
                        "Backup .bak.tmp copy failed SHA-256 verification."
                    )
                os.replace(str(backup_tmp), str(backup_exe))
                has_backup = True
    except Exception as exc:
        try:
            if backup_tmp.exists():
                backup_tmp.unlink()
        except OSError:
            pass
        try:
            if temp_new_exe.exists():
                temp_new_exe.unlink()
        except OSError:
            pass
        return (
            False,
            f"Failed to create verified backup executable '{backup_exe}': {exc}",
            backup_exe if has_backup else None,
        )

    # 3. Atomically replace target_exe with temp_new_exe (target_exe is never missing on disk)
    try:
        os.replace(str(temp_new_exe), str(target_exe))
        if not hmac.compare_digest(compute_file_sha256(target_exe), expected_sha):
            raise UpdateVerificationError(
                "Replaced target executable failed post-swap SHA-256 check."
            )
        return (
            True,
            "Executable replaced and verified.",
            backup_exe if has_backup else None,
        )
    except Exception as exc:
        try:
            if temp_new_exe.exists():
                temp_new_exe.unlink()
        except OSError:
            pass
        if has_backup and backup_exe.exists():
            if _restore_backup_executable(target_exe, backup_exe):
                return (
                    False,
                    f"Executable replacement failed and was rolled back to previous version: {exc}",
                    backup_exe,
                )
            return (
                False,
                f"Replacement failed ({exc}) AND rollback encountered an error. Backup remains at {backup_exe}.",
                backup_exe,
            )
        return (
            False,
            f"Executable replacement failed: {exc}",
            None,
        )


def _read_reported_pid_from_confirm_file(confirm_file: Path) -> int:
    """Reads the child `pid` field from `confirm_file` if present, or returns 0."""
    try:
        if confirm_file.exists():
            data = json.loads(confirm_file.read_text(encoding="utf-8"))
            return int(data.get("pid") or 0)
    except Exception:
        pass
    return 0


def _wait_for_startup_confirmation(
    proc: subprocess.Popen,
    confirm_file: Path,
    expected_version: str,
    expected_token: str = "",
    expected_executable: Optional[Path] = None,
    timeout_sec: float = STARTUP_CONFIRM_TIMEOUT_SEC,
    verify_executable_path: bool = True,
    allow_clean_exit_after_confirm: bool = False,
) -> Tuple[bool, str]:
    """
    Waits up to `timeout_sec` for the newly launched executable `proc` (or its
    PyInstaller `--onefile` Python child process) to write a valid JSON startup
    confirmation payload to `confirm_file`:
      1. Cryptographic per-update token validation (`hmac.compare_digest(rep_token, expected_token)`).
      2. Semantic version validation (`rep_ver == format_semver(expected_version)`).
      3. PyInstaller `--onefile` Process Ancestry validation:
         - In PyInstaller `--onefile`, `proc.pid` is the native C bootloader parent while
           Python executes in a child process (`rep_pid != proc.pid`, `rep_ppid == proc.pid`).
         - Accepts `rep_pid == proc.pid` (single-process mode) OR `rep_ppid == proc.pid`
           (verified against the OS process parent table when `rep_pid` is alive) OR
           `_is_pid_descendant_of(rep_pid, proc.pid, parent_map)`.
      4. Executable Identity validation:
         - When `verify_executable_path=True` and `expected_executable` is provided, verifies
           that the reported `executable` path (and the OS image path of `rep_pid` when
           queryable via Win32 `QueryFullProcessImageNameW`) matches `expected_executable`.
      5. Liveness check:
         - Verifies the process did not crash immediately after writing the confirmation file.
    Returns `(confirmed_ok, reason_message)`.
    """
    clean_expected = format_semver(expected_version)
    clean_token = str(expected_token or "").strip()
    expected_exe_norm: Optional[str] = None
    if verify_executable_path and expected_executable is not None:
        try:
            expected_exe_norm = os.path.normcase(str(Path(expected_executable).resolve()))
        except Exception:
            expected_exe_norm = None

    deadline = time.monotonic() + max(0.15, float(timeout_sec))
    last_reported_pid: int = 0

    while time.monotonic() < deadline:
        if confirm_file.exists():
            try:
                raw = confirm_file.read_text(encoding="utf-8").strip()
                if raw:
                    data = json.loads(raw)
                    status = str(data.get("status") or "").strip().lower()
                    rep_ver = format_semver(str(data.get("version") or ""))
                    rep_token = str(data.get("token") or "").strip()
                    rep_pid = int(data.get("pid") or 0)
                    rep_ppid = int(data.get("ppid") or 0)
                    rep_exe = str(data.get("executable") or "").strip()
                    last_reported_pid = rep_pid

                    if status == "ready":
                        # 1. Verify per-update cryptographic confirmation token
                        if clean_token:
                            if not rep_token or not hmac.compare_digest(rep_token, clean_token):
                                return (
                                    False,
                                    "Startup confirmation token mismatch or missing token.",
                                )

                        # 2. Verify reported version matches expected target_version
                        if clean_expected and rep_ver != clean_expected:
                            return (
                                False,
                                f"Updated executable reported version '{rep_ver}' instead of expected '{clean_expected}'.",
                            )

                        # 3. Verify PyInstaller --onefile process ancestry (bootloader parent -> Python child)
                        if rep_pid <= 0:
                            return (
                                False,
                                f"Startup confirmation reported invalid PID ({rep_pid}).",
                            )
                        if proc.pid:
                            boot_pid = int(proc.pid)
                            pmap = _enumerate_process_parent_map()
                            is_direct = rep_pid == boot_pid
                            is_os_descendant = _is_pid_descendant_of(
                                rep_pid, boot_pid, parent_map=pmap
                            )
                            # If rep_pid is still in the OS process table, its actual OS parent chain
                            # MUST lead to boot_pid. If rep_pid already exited cleanly (only allowed in
                            # allow_clean_exit_after_confirm mode), accept rep_ppid == boot_pid.
                            if rep_pid in pmap:
                                ancestry_ok = is_direct or is_os_descendant
                            else:
                                ancestry_ok = (
                                    is_direct
                                    or is_os_descendant
                                    or (rep_ppid == boot_pid)
                                )
                            if not ancestry_ok:
                                return (
                                    False,
                                    f"Startup confirmation process ancestry mismatch: reported pid={rep_pid} "
                                    f"(ppid={rep_ppid}) is neither bootloader pid={boot_pid} nor its child/descendant.",
                                )

                        # 4. Verify executable identity (reported executable + OS process image path)
                        if expected_exe_norm is not None:
                            if rep_exe:
                                try:
                                    rep_exe_norm = os.path.normcase(
                                        str(Path(rep_exe).resolve())
                                    )
                                except Exception:
                                    rep_exe_norm = os.path.normcase(rep_exe)
                                if rep_exe_norm != expected_exe_norm:
                                    return (
                                        False,
                                        f"Startup confirmation executable mismatch: expected '{expected_exe_norm}', got '{rep_exe_norm}'.",
                                    )
                            os_img = _query_process_executable_path(rep_pid)
                            if os_img is not None and sys.platform == "win32":
                                os_img_norm = os.path.normcase(str(os_img))
                                if os_img_norm != expected_exe_norm:
                                    return (
                                        False,
                                        f"OS process image path '{os_img_norm}' for PID {rep_pid} does not match expected '{expected_exe_norm}'.",
                                    )

                        # 5. Verify process liveness
                        if not allow_clean_exit_after_confirm:
                            if proc.poll() is not None:
                                return (
                                    False,
                                    f"Updated executable exited immediately after writing startup signal (exit code {proc.poll()}).",
                                )
                            if not _is_process_alive(rep_pid):
                                return (
                                    False,
                                    f"Updated Python child process (PID {rep_pid}) exited immediately after writing startup signal.",
                                )

                        rel_desc = (
                            f"child_pid={rep_pid}, bootloader_pid={proc.pid}"
                            if (proc.pid and rep_pid != int(proc.pid))
                            else f"pid={rep_pid}"
                        )
                        return (
                            True,
                            f"Confirmed healthy startup of v{rep_ver} ({rel_desc}).",
                        )
            except (json.JSONDecodeError, OSError, ValueError):
                # File may still be mid-write if not yet replaced; poll again briefly
                pass

        exit_code = proc.poll()
        if exit_code is not None and not confirm_file.exists():
            return (
                False,
                f"Updated executable exited prematurely before confirming startup (exit code {exit_code}).",
            )
        time.sleep(0.05)

    return (
        False,
        f"Timed out after {timeout_sec:.1f}s waiting for explicit startup confirmation signal from updated executable.",
    )


def run_staged_update_helper(
    manifest_path_str: str,
    allowed_staging_root: Optional[Path] = None,
    post_launch_verify_sec: float = STARTUP_CONFIRM_TIMEOUT_SEC,
    launch_command_override: Optional[Callable[..., subprocess.Popen]] = None,
) -> int:
    r"""
    Executes the out-of-process `--apply-staged-update <manifest>` helper workflow BEFORE
    Qt, hotkeys, or the single-instance mutex are initialized:
      1. Acquires `Local\HDRSnipFusion_UpdaterTransaction` mutex and refreshes
         `.active_update_transaction.lock` inside the staging directory so staging files
         are protected until verification or rollback completes.
      2. Validates that `manifest_path` resides inside the trusted update staging directory.
      3. Waits for `parent_pid` and PyInstaller bootloader file locks on `target_exe` to release.
      4. Writes `.pending_verify.json` and performs non-destructive atomic replacement
         (`target_exe` copied to `.bak`, `.new` swapped into `target_exe`).
      5. Generates a cryptographic per-update confirmation token (`secrets.token_hex(32)`)
         and launches the updated executable to verify startup health:
         - When `restart_after_update=True`, launches the normal tray app with
           `--restarted-after-update --confirm-startup-file <path> --confirm-startup-token <token>`.
         - When `restart_after_update=False`, launches with `--verify-startup-only` so the
           independent helper STILL verifies that the new binary boots Python + Qt cleanly
           before letting it exit (never leaving an unverified binary installed on disk).
      6. Validates the cryptographic token, target version, PyInstaller `--onefile`
         bootloader->child process ancestry, and executable identity.
      7. If startup confirmation fails or times out, terminates the ENTIRE PyInstaller
         process tree (both the Python child process and the bootloader parent) via
         `_terminate_process_tree_safely()`, waits for file locks to release, restores
         `.bak` -> `target_exe`, and (if `restart_after_update=True`) relaunches the
         restored previous version!
      8. Only removes `.bak`, `.pending_verify.json`, `update_manifest.json`, and
         `.active_update_transaction.lock` AFTER verification or rollback is complete.
    """
    updater_mutex = None
    kernel32_err = None
    lock_file: Optional[Path] = None
    if sys.platform == "win32":
        try:
            _ensure_win32_ctypes_signatures()
            kernel32_err = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32_err.CreateMutexW.argtypes = [
                ctypes.c_void_p,
                wintypes.BOOL,
                ctypes.c_wchar_p,
            ]
            kernel32_err.CreateMutexW.restype = ctypes.c_void_p
            kernel32_err.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32_err.CloseHandle.restype = wintypes.BOOL
            updater_mutex = kernel32_err.CreateMutexW(
                None, False, r"Local\HDRSnipFusion_UpdaterTransaction"
            )
            if ctypes.get_last_error() == 183:
                DIAG_LOG.warning(
                    "UPDATE_HELPER",
                    "Another updater helper transaction is already active; exiting.",
                )
                if updater_mutex:
                    kernel32_err.CloseHandle(ctypes.c_void_p(updater_mutex))
                return 1
        except Exception:
            pass

    try:
        m_path = Path(manifest_path_str).resolve()
        trusted_root = Path(allowed_staging_root or LOCAL_UPDATE_ROOT_DIR).resolve()
        try:
            m_path.relative_to(trusted_root)
        except ValueError:
            DIAG_LOG.error(
                "UPDATE_HELPER",
                f"Rejected manifest path outside trusted staging directory: '{m_path}'",
            )
            return 2

        if m_path.name != "update_manifest.json" or not m_path.exists():
            DIAG_LOG.error(
                "UPDATE_HELPER", f"Manifest file missing or invalid name: '{m_path}'"
            )
            return 2

        lock_file = m_path.parent / ACTIVE_TRANSACTION_LOCK_FILENAME
        try:
            write_atomic_json_file(
                lock_file,
                {
                    "status": "running_helper",
                    "helper_pid": os.getpid(),
                    "manifest": str(m_path),
                    "updated_at_epoch": time.time(),
                },
            )
        except Exception:
            pass

        manifest = json.loads(m_path.read_text(encoding="utf-8"))
        target_exe = Path(manifest["target_exe"]).resolve()
        staged_exe = Path(manifest["staged_exe"]).resolve()
        expected_sha = str(manifest["expected_sha256"]).strip().lower()
        target_version = format_semver(
            str(manifest.get("target_version") or APP_VERSION)
        )
        source_version = format_semver(
            str(manifest.get("source_version") or APP_VERSION)
        )
        min_exe_size = int(manifest.get("min_exe_size", MIN_EXE_SIZE_BYTES))
        parent_pid = int(manifest.get("parent_pid", 0))
        restart_after = bool(manifest.get("restart_after_update", True))
        created_at = float(manifest.get("created_at_epoch", 0.0))

        # Reject stale manifests older than 15 minutes
        if abs(time.time() - created_at) > 900.0:
            DIAG_LOG.error("UPDATE_HELPER", "Rejected expired update_manifest.json.")
            return 3

        # Ensure staged_exe is inside the same staging folder
        if staged_exe.parent != m_path.parent:
            DIAG_LOG.error(
                "UPDATE_HELPER",
                f"Staged executable '{staged_exe}' does not match manifest directory '{m_path.parent}'.",
            )
            return 3

        if target_exe.suffix.lower() != ".exe":
            DIAG_LOG.error(
                "UPDATE_HELPER", f"Rejected non-EXE target path: '{target_exe}'"
            )
            return 3

        DIAG_LOG.milestone(
            "UPDATE_HELPER_START",
            f"Waiting for parent PID {parent_pid} and file lock on '{target_exe}'",
            flush_disk=True,
        )
        _wait_for_process_exit(parent_pid, timeout_sec=25.0)
        if not _wait_for_file_unlocked(target_exe, timeout_sec=30.0):
            DIAG_LOG.error(
                "UPDATE_HELPER",
                f"Timed out waiting for '{target_exe}' file lock to release.",
            )
            return 4

        ok, msg, backup_exe = perform_atomic_exe_replacement(
            target_exe,
            staged_exe,
            expected_sha,
            min_exe_size=min_exe_size,
        )
        if not ok:
            DIAG_LOG.error("UPDATE_HELPER", f"Replacement failed: {msg}")
            return 5

        pending_marker = get_pending_update_marker_path(target_exe)
        try:
            write_atomic_json_file(
                pending_marker,
                {
                    "source_version": source_version,
                    "target_version": target_version,
                    "target_exe": str(target_exe),
                    "backup_exe": str(backup_exe) if backup_exe else "",
                    "expected_sha256": expected_sha,
                    "restart_after_update": restart_after,
                    "helper_pid": os.getpid(),
                    "updated_at_epoch": time.time(),
                },
            )
        except Exception as mk_exc:
            DIAG_LOG.warning(
                "UPDATE_HELPER", f"Could not write pending marker: {mk_exc}"
            )

        DIAG_LOG.milestone(
            "UPDATE_HELPER_REPLACED",
            f"Replaced '{target_exe}' with v{target_version} (backup preserved at '{backup_exe}')",
            flush_disk=True,
        )

        # Preserve Windows startup registry path if already enabled
        try:
            cfg = AppConfig.load()
            if cfg.start_with_windows and sys.platform == "win32":
                import winreg

                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.SetValueEx(
                        key, "HDRSnipFusion", 0, winreg.REG_SZ, f'"{target_exe}"'
                    )
        except Exception as reg_exc:
            DIAG_LOG.warning("UPDATE_HELPER", f"Startup registry sync note: {reg_exc}")

        # Always verify that the newly installed executable can boot Python + Qt and write
        # a valid cryptographic startup confirmation token (even if restart_after is False,
        # in which case we pass --verify-startup-only so the child exits cleanly right after
        # confirming readiness). This guarantees recovery never depends on a broken EXE!
        confirm_token = secrets.token_hex(32)
        env = _build_clean_pyinstaller_env()
        env["HDRSNIP_STARTUP_CONFIRM_TOKEN"] = confirm_token
        confirm_file = (
            m_path.parent
            / f"startup_confirm_{os.getpid()}_{int(time.time() * 1000)}.json"
        )
        proc: Optional[subprocess.Popen] = None
        reported_child_pid: int = 0
        try:
            if confirm_file.exists():
                try:
                    confirm_file.unlink()
                except OSError:
                    pass

            if launch_command_override is not None:
                try:
                    proc = launch_command_override(
                        target_exe, confirm_file, confirm_token
                    )
                except TypeError:
                    try:
                        proc = launch_command_override(target_exe, confirm_file)
                    except TypeError:
                        proc = launch_command_override(target_exe)
            else:
                creationflags = 0
                if sys.platform == "win32":
                    creationflags = 0x00000200  # CREATE_NEW_PROCESS_GROUP
                launch_args = [
                    str(target_exe),
                    "--restarted-after-update",
                    "--confirm-startup-file",
                    str(confirm_file),
                    "--confirm-startup-token",
                    confirm_token,
                ]
                if not restart_after:
                    launch_args.append("--verify-startup-only")
                proc = subprocess.Popen(
                    launch_args,
                    env=env,
                    cwd=str(target_exe.parent),
                    close_fds=True,
                    creationflags=creationflags,
                    shell=False,
                )

            confirmed, confirm_reason = _wait_for_startup_confirmation(
                proc,
                confirm_file=confirm_file,
                expected_version=target_version,
                expected_token=confirm_token,
                expected_executable=target_exe,
                timeout_sec=post_launch_verify_sec,
                verify_executable_path=(launch_command_override is None),
                allow_clean_exit_after_confirm=(not restart_after),
            )
            reported_child_pid = _read_reported_pid_from_confirm_file(confirm_file)
            if not confirmed:
                raise RuntimeError(confirm_reason)

            if not restart_after and proc is not None:
                # Ensure the verify-only process exits cleanly
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    _terminate_process_tree_safely(
                        proc,
                        timeout_sec=2.0,
                        extra_pids=[reported_child_pid] if reported_child_pid else None,
                    )

            DIAG_LOG.milestone(
                "UPDATE_HELPER_CONFIRMED",
                confirm_reason,
                flush_disk=True,
            )
        except Exception as start_exc:
            if not reported_child_pid:
                reported_child_pid = _read_reported_pid_from_confirm_file(confirm_file)
            DIAG_LOG.error(
                "UPDATE_HELPER_ROLLBACK",
                f"Updated executable failed startup confirmation ({start_exc}); "
                "terminating PyInstaller process tree and rolling back to backup!",
                start_exc,
            )
            extra_kill_pids = [reported_child_pid] if reported_child_pid > 0 else []
            _terminate_process_tree_safely(
                proc, timeout_sec=5.0, extra_pids=extra_kill_pids
            )
            if backup_exe is not None and backup_exe.exists():
                try:
                    _wait_for_file_unlocked(target_exe, timeout_sec=15.0)
                    if _restore_backup_executable(target_exe, backup_exe):
                        try:
                            if pending_marker.exists():
                                pending_marker.unlink()
                        except OSError:
                            pass
                        try:
                            backup_exe.unlink()
                        except OSError:
                            pass
                        DIAG_LOG.milestone(
                            "UPDATE_HELPER_ROLLBACK_OK",
                            f"Restored previous working version at '{target_exe}'",
                            flush_disk=True,
                        )
                        if restart_after:
                            if launch_command_override is not None:
                                try:
                                    launch_command_override(target_exe, None, "")
                                except TypeError:
                                    try:
                                        launch_command_override(target_exe, None)
                                    except TypeError:
                                        launch_command_override(target_exe)
                            else:
                                subprocess.Popen(
                                    [str(target_exe), "--restarted-after-update"],
                                    env=_build_clean_pyinstaller_env(),
                                    cwd=str(target_exe.parent),
                                    close_fds=True,
                                    shell=False,
                                )
                except Exception as rb_err:
                    DIAG_LOG.error(
                        "UPDATE_HELPER_ROLLBACK_ERR",
                        "Failed to restore backup executable after startup failure",
                        rb_err,
                    )
            return 6
        finally:
            try:
                if confirm_file.exists():
                    confirm_file.unlink()
            except OSError:
                pass

        # Startup confirmation succeeded! Now safe to remove backup_exe, pending_marker, and manifest
        try:
            if pending_marker.exists():
                pending_marker.unlink()
        except OSError:
            pass
        try:
            if backup_exe is not None and backup_exe.exists():
                backup_exe.unlink()
        except OSError:
            pass
        try:
            if m_path.exists():
                m_path.unlink()
        except OSError:
            pass

        DIAG_LOG.milestone(
            "UPDATE_HELPER_DONE",
            f"Update to v{target_version} confirmed usable and finalized cleanly.",
            flush_disk=True,
        )
        return 0
    except Exception as exc:
        DIAG_LOG.error(
            "UPDATE_HELPER", "Unhandled error in run_staged_update_helper", exc
        )
        return 1
    finally:
        if lock_file is not None:
            try:
                if lock_file.exists():
                    lock_file.unlink()
            except OSError:
                pass
        if updater_mutex and kernel32_err is not None:
            try:
                kernel32_err.CloseHandle(ctypes.c_void_p(updater_mutex))
            except Exception:
                pass


# =============================================================================
# 9. FRUTIGER AERO GLASS SETTINGS DIALOG & 3D AQUA BUBBLE TRAY ICON
# =============================================================================

if HAS_QT:

    class UpdateWorkerSignals(QObject):
        """GUI-thread signals emitted by background GitHub update check & download jobs."""

        check_completed = pyqtSignal(object, bool)  # (UpdateCheckResult, manual_user_request)
        download_progress = pyqtSignal(int, int)    # (bytes_downloaded, total_bytes)
        download_completed = pyqtSignal(str, str, str, object, bool)  # (version, staged_path, sha256, check_result, install_immediately)
        download_failed = pyqtSignal(str, bool, object)  # (error_msg, manual_user_request, check_result)


    class UpdateCheckJob(QRunnable):
        """Runs `fetch_latest_github_release` in a background thread without blocking Qt."""

        def __init__(
            self,
            signals: UpdateWorkerSignals,
            manual_request: bool = False,
            api_url: str = GITHUB_LATEST_RELEASE_API_URL,
        ) -> None:
            super().__init__()
            self.signals = signals
            self.manual_request = bool(manual_request)
            self.api_url = api_url

        def run(self) -> None:
            try:
                res = fetch_latest_github_release(
                    api_url=self.api_url, current_version=APP_VERSION
                )
                self.signals.check_completed.emit(res, self.manual_request)
            except Exception as exc:
                err_res = UpdateCheckResult(
                    status="error",
                    current_version=APP_VERSION,
                    message=f"Update check error: {exc}",
                )
                try:
                    self.signals.check_completed.emit(err_res, self.manual_request)
                except RuntimeError:
                    pass


    class UpdateDownloadJob(QRunnable):
        """Downloads and SHA-256 + PE64 validates `HDRSnipFusion.exe` in a background worker thread."""

        def __init__(
            self,
            signals: UpdateWorkerSignals,
            check_result: UpdateCheckResult,
            install_immediately: bool = False,
            manual_request: bool = False,
            cancel_event: Optional[threading.Event] = None,
        ) -> None:
            super().__init__()
            self.signals = signals
            self.check_result = check_result
            self.install_immediately = bool(install_immediately)
            self.manual_request = bool(manual_request)
            self.cancel_event = cancel_event

        def _on_progress(self, done: int, total: int) -> None:
            try:
                self.signals.download_progress.emit(int(done), int(total))
            except RuntimeError:
                pass

        def run(self) -> None:
            try:
                staged_path = download_and_stage_release_asset(
                    self.check_result,
                    staging_root=LOCAL_UPDATE_ROOT_DIR,
                    progress_callback=self._on_progress,
                    cancel_event=self.cancel_event,
                )
                self.signals.download_completed.emit(
                    format_semver(self.check_result.latest_version),
                    str(staged_path),
                    self.check_result.expected_sha256,
                    self.check_result,
                    self.install_immediately,
                )
            except Exception as exc:
                DIAG_LOG.error("UPDATE_DOWNLOAD", "Background update download/validation failed", exc)
                try:
                    self.signals.download_failed.emit(
                        str(exc), self.manual_request, self.check_result
                    )
                except RuntimeError:
                    pass


    class UpdatePromptDialog(QDialog):
        """
        Frutiger Aqua Glass Update Notification & Progress Dialog:
          - Shows `HDRSnip Fusion v<version> is available` and release notes from GitHub.
          - Offers `[Update Now]`, `[Later]`, and `[View Release]`.
          - Displays real-time download & SHA-256 verification progress when `[Update Now]`
            is clicked in packaged EXE mode.
          - Clearly explains source-Python mode or protected installation folder limitations
            with a direct `[View Release]` link when automatic replacement is not applicable.
        """

        def __init__(
            self,
            check_result: UpdateCheckResult,
            controller: "HDRSnipFusionApplication",
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)
            self.check_result = check_result
            self.controller = controller
            self._drag_offset: Optional[QPoint] = None
            self._cached_base_pix: Optional[QPixmap] = None
            self._water_dirty: bool = True
            self._wave_paths = (
                QPainterPath(),
                QPainterPath(),
                QPainterPath(),
                QPainterPath(),
            )
            self._downloading: bool = False

            self.setWindowTitle(
                f"HDRSnip Fusion v{check_result.latest_version} is available"
            )
            self.setMinimumWidth(500)
            self.setWindowFlags(
                Qt.WindowType.Dialog
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

            self.setStyleSheet(
                """
                QLabel {
                    color: #F4FFFF;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 12px;
                    font-weight: 600;
                    background: transparent;
                }
                QFrame#AquaUpdateCard {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 44),
                        stop:0.5 rgba(205, 248, 255, 28),
                        stop:1 rgba(160, 238, 255, 38));
                    border: 1px solid rgba(215, 252, 255, 155);
                    border-radius: 13px;
                }
                QTextEdit#ReleaseNotesBox {
                    background: rgba(6, 44, 86, 175);
                    color: #EAFFFF;
                    border: 1px solid rgba(155, 245, 255, 165);
                    border-radius: 9px;
                    padding: 6px 8px;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 12px;
                }
                QProgressBar {
                    background: rgba(6, 48, 92, 190);
                    color: #FFFFFF;
                    border: 1px solid rgba(165, 248, 255, 195);
                    border-radius: 8px;
                    text-align: center;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 11px;
                    font-weight: bold;
                    min-height: 18px;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #00C6FF,
                        stop:0.6 #00F2FE,
                        stop:1 #69F0AE);
                    border-radius: 7px;
                }
                """
            )

            outer = QVBoxLayout(self)
            outer.setContentsMargins(18, 14, 18, 16)
            outer.setSpacing(10)

            title_row = QHBoxLayout()
            title_lbl = QLabel(
                f"✦  HDRSnip Fusion v{check_result.latest_version} is available"
            )
            title_lbl.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: #FFFFFF;"
            )
            title_row.addWidget(title_lbl)
            title_row.addStretch()
            close_x = AeroGelButton("✕", variant="ruby", parent=self)
            close_x.setFixedSize(30, 26)
            close_x.clicked.connect(self._on_later_clicked)
            title_row.addWidget(close_x)
            outer.addLayout(title_row)

            card = QFrame(self)
            card.setObjectName("AquaUpdateCard")
            card_vbox = QVBoxLayout(card)
            card_vbox.setContentsMargins(14, 11, 14, 12)
            card_vbox.setSpacing(8)

            packaged = is_packaged_exe()
            is_prot, prot_reason = (
                is_protected_install_location() if packaged else (False, "")
            )

            if not packaged:
                sub_text = (
                    f"Installed version: v{APP_VERSION} (Python Source Mode)  •  "
                    f"Latest stable release: v{check_result.latest_version}\n"
                    "You are running from Python source (.py). Automatic EXE replacement "
                    "is only active in packaged HDRSnipFusion.exe builds."
                )
            elif is_prot:
                sub_text = (
                    f"Installed version: v{APP_VERSION}  •  "
                    f"Latest stable release: v{check_result.latest_version}\n"
                    f"Note: {prot_reason} Please download the update from the official release page."
                )
            else:
                sub_text = (
                    f"A new stable version (v{check_result.latest_version}) is ready to install "
                    f"(currently running v{APP_VERSION}).\n"
                    "Your hotkey, default screenshot folder, and HDR settings will be preserved."
                )

            self.subtitle_lbl = QLabel(sub_text, card)
            self.subtitle_lbl.setWordWrap(True)
            card_vbox.addWidget(self.subtitle_lbl)

            notes_box = QTextEdit(card)
            notes_box.setObjectName("ReleaseNotesBox")
            notes_box.setReadOnly(True)
            notes_box.setFixedHeight(130)
            notes_content = (
                check_result.release_notes.strip()
                or f"HDRSnip Fusion v{check_result.latest_version} stable release."
            )
            notes_box.setPlainText(notes_content)
            card_vbox.addWidget(notes_box)

            self.progress_bar = QProgressBar(card)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.hide()
            card_vbox.addWidget(self.progress_bar)

            self.status_lbl = QLabel("", card)
            self.status_lbl.setWordWrap(True)
            self.status_lbl.setStyleSheet("color: #A8FAFF; font-size: 11px;")
            self.status_lbl.hide()
            card_vbox.addWidget(self.status_lbl)

            outer.addWidget(card)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(8)
            self.view_release_btn = AeroGelButton(
                "View Release", variant="sapphire", parent=self
            )
            self.view_release_btn.clicked.connect(self._on_view_release_clicked)
            btn_row.addWidget(self.view_release_btn)
            btn_row.addStretch()

            self.later_btn = AeroGelButton("Later", variant="glass", parent=self)
            self.later_btn.clicked.connect(self._on_later_clicked)
            btn_row.addWidget(self.later_btn)

            self.update_now_btn = AeroGelButton(
                "Update Now", variant="emerald", parent=self
            )
            if not packaged or is_prot:
                self.update_now_btn.setText("Open Release Page")
            self.update_now_btn.clicked.connect(self._on_update_now_clicked)
            btn_row.addWidget(self.update_now_btn)

            outer.addLayout(btn_row)

        def _on_view_release_clicked(self) -> None:
            url = self.check_result.release_url or GITHUB_RELEASES_PAGE_URL
            if is_valid_github_url(url, require_repo_prefix=True):
                webbrowser.open(url)

        def _on_later_clicked(self) -> None:
            if self._downloading:
                self.controller.cancel_active_update_download()
            self.controller.config.declined_update_version = format_semver(
                self.check_result.latest_version
            )
            self.controller.config.save()
            self.reject()

        def _on_update_now_clicked(self) -> None:
            if not is_packaged_exe():
                self._on_view_release_clicked()
                self.accept()
                return
            is_prot, prot_reason = is_protected_install_location()
            if is_prot:
                QMessageBox.information(
                    self,
                    "Manual Update Required",
                    f"{prot_reason}\n\nOpening the official GitHub Release page so you can download "
                    f"{EXPECTED_RELEASE_ASSET_NAME} manually.",
                )
                self._on_view_release_clicked()
                return

            self._downloading = True
            self.update_now_btn.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            self.status_lbl.setText(
                f"Downloading and verifying {EXPECTED_RELEASE_ASSET_NAME} (SHA-256)..."
            )
            self.status_lbl.show()
            self.controller.start_update_download(
                self.check_result, install_immediately=True, manual_request=True
            )

        def on_download_progress(self, done: int, total: int) -> None:
            if total > 0:
                pct = max(0, min(100, int(round((done / float(total)) * 100.0))))
                self.progress_bar.setValue(pct)
                self.status_lbl.setText(
                    f"Downloading {EXPECTED_RELEASE_ASSET_NAME}: "
                    f"{done / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB ({pct}%)"
                )

        def on_download_failed(self, err_msg: str) -> None:
            self._downloading = False
            self.update_now_btn.setEnabled(True)
            self.status_lbl.setText(f"Update verification/download failed: {err_msg}")
            self.status_lbl.show()

        def paintEvent(self, event) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.rect()).adjusted(6.0, 6.0, -6.0, -6.0)
            draw_frutiger_glass_panel(
                painter,
                rect,
                radius=20.0,
                frosted_pixmap=None,
                tint_style="dialog",
                t_sec=AeroAnimationDirector.instance().elapsed_seconds(),
                intensity_scale=AeroAnimationDirector.instance().scale,
            )

        def mousePressEvent(self, event) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:
            if (
                self._drag_offset is not None
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                self.move(event.globalPosition().toPoint() - self._drag_offset)
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:
            self._drag_offset = None
            super().mouseReleaseEvent(event)


    class SettingsDialog(QDialog):
        """
        Polished Frutiger Aqua Glass Control Panel Settings Dialog (v0.1.1):
          - Organized into six scannable frosted glass section cards inside a smooth,
            high-DPI-safe transparent scroll area:
            1. Capture & Startup (Hotkey + Windows Startup & SDR Fallback)
            2. Screenshot Saving (Default Save Location read-only path + Browse...)
            3. Frutiger Aqua Glass & Animation (Live Animation Intensity & Glass Transparency)
            4. HDR Capture & Tone Mapping (Curve, SDR White Level, Highlight Knee, Gamma 2.2 & White Boost)
            5. Application Updates (Current Version: v0.1.1, Auto-check, Auto-install, Check for Updates)
            6. Stability & Diagnostics (Subordinated deep-ocean card with status pill, Safe Mode & Isolation grid)
          - Preserves genuinely rounded transparent corners (native rectangular Acrylic disabled),
            living water glass backdrop, custom draggable glass title bar, and tactile 3D gel buttons.
        """

        LABEL_COL_WIDTH: int = 154

        def __init__(
            self,
            config: AppConfig,
            parent: Optional[QWidget] = None,
            controller: Optional["HDRSnipFusionApplication"] = None,
        ) -> None:
            super().__init__(parent)
            self.config = config
            self.controller = controller
            self._original_intensity = config.animation_intensity
            self._original_transparency = config.glass_transparency
            self._selected_save_directory: str = str(
                config.save_directory or DEFAULT_SAVE_DIR
            )
            self._drag_offset: Optional[QPoint] = None
            self._wave_paths = (
                QPainterPath(),
                QPainterPath(),
                QPainterPath(),
                QPainterPath(),
            )
            self._cached_base_pix: Optional[QPixmap] = None
            self._local_update_signals = UpdateWorkerSignals()
            self._local_update_signals.check_completed.connect(
                self._on_local_update_check_done
            )
            self._latest_check_result: Optional[UpdateCheckResult] = (
                getattr(controller, "_last_update_result", None)
                if controller is not None
                else None
            )

            self.setWindowTitle(
                f"HDRSnip Fusion v{APP_VERSION} • Frutiger Aqua Settings"
            )
            self.setMinimumWidth(568)
            self.setWindowFlags(
                Qt.WindowType.Dialog
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

            self.setStyleSheet(
                """
                QLabel {
                    color: #F4FFFF;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 12px;
                    font-weight: 600;
                    background: transparent;
                }
                QLabel#SectionHeader {
                    color: #A8FAFF;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 11px;
                    font-weight: bold;
                    letter-spacing: 0.6px;
                    padding-bottom: 1px;
                }
                QLabel#DiagSectionHeader {
                    color: #88E8FF;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 11px;
                    font-weight: bold;
                    letter-spacing: 0.6px;
                }
                QLabel#ValueBadge {
                    background: rgba(6, 58, 108, 175);
                    color: #ECFFFF;
                    border: 1px solid rgba(165, 248, 255, 195);
                    border-radius: 9px;
                    padding: 3px 6px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QLabel#UpdateStatusLabel {
                    background: rgba(6, 48, 92, 168);
                    color: #CCF8FF;
                    border: 1px solid rgba(145, 240, 255, 155);
                    border-radius: 8px;
                    padding: 4px 9px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QFrame#AquaSectionCard {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 44),
                        stop:0.5 rgba(205, 248, 255, 28),
                        stop:1 rgba(160, 238, 255, 38));
                    border: 1px solid rgba(215, 252, 255, 155);
                    border-radius: 13px;
                }
                QFrame#AquaDiagCard {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(6, 46, 88, 108),
                        stop:1 rgba(4, 32, 66, 128));
                    border: 1px solid rgba(130, 232, 255, 115);
                    border-radius: 13px;
                }
                QFrame#SectionDivider {
                    background: rgba(195, 248, 255, 58);
                    max-height: 1px;
                    min-height: 1px;
                    border: none;
                }
                QScrollArea#AquaScrollArea {
                    background: transparent;
                    border: none;
                }
                QWidget#AquaScrollContents {
                    background: transparent;
                }
                QScrollBar:vertical {
                    background: rgba(6, 46, 88, 95);
                    width: 9px;
                    margin: 2px 0 2px 2px;
                    border-radius: 4px;
                }
                QScrollBar::handle:vertical {
                    background: rgba(145, 244, 255, 185);
                    min-height: 28px;
                    border-radius: 4px;
                }
                QScrollBar::handle:vertical:hover {
                    background: rgba(210, 255, 255, 235);
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                QKeySequenceEdit, QComboBox, QDoubleSpinBox, QLineEdit#SavePathEdit {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 232),
                        stop:0.48 rgba(218, 246, 255, 222),
                        stop:0.52 rgba(186, 235, 252, 226),
                        stop:1 rgba(238, 253, 255, 238));
                    color: #002E5C;
                    border: 1.5px solid rgba(255, 255, 255, 242);
                    border-radius: 9px;
                    padding: 4px 10px;
                    min-height: 20px;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 12px;
                    font-weight: bold;
                }
                QKeySequenceEdit:hover, QComboBox:hover, QDoubleSpinBox:hover, QLineEdit#SavePathEdit:hover {
                    border: 1.5px solid #84FAFF;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 248),
                        stop:0.5 rgba(228, 251, 255, 238),
                        stop:1 rgba(242, 255, 255, 250));
                }
                QDoubleSpinBox {
                    padding-right: 24px;
                }
                QComboBox QAbstractItemView {
                    background-color: #0B4A84;
                    color: #FFFFFF;
                    selection-background-color: #00C6FF;
                    selection-color: #002244;
                    border: 1px solid #90F4FF;
                    border-radius: 8px;
                    padding: 4px;
                }
                QCheckBox {
                    color: #F0FFFF;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 12px;
                    font-weight: 600;
                    spacing: 7px;
                    background: transparent;
                }
                QCheckBox#DiagIsoCheck {
                    color: #D2F6FF;
                    font-size: 11px;
                    font-weight: 600;
                    spacing: 6px;
                }
                QCheckBox::indicator {
                    width: 17px;
                    height: 17px;
                    border-radius: 8px;
                    border: 1.5px solid #FFFFFF;
                    background: qradialgradient(cx:0.35, cy:0.35, radius:0.8,
                        stop:0 rgba(255, 255, 255, 205),
                        stop:1 rgba(10, 95, 160, 192));
                }
                QCheckBox::indicator:hover {
                    border: 1.5px solid #84FFFF;
                }
                QCheckBox::indicator:checked {
                    border: 1.5px solid #FFFFFF;
                    background: qradialgradient(cx:0.35, cy:0.3, radius:0.8,
                        stop:0 #FFFFFF,
                        stop:0.4 #69F0AE,
                        stop:1 #00B248);
                }
                """
            )

            outer_layout = QVBoxLayout(self)
            outer_layout.setContentsMargins(18, 14, 18, 16)
            outer_layout.setSpacing(9)

            # -----------------------------------------------------------------
            # Draggable Frutiger Aqua Title Bar (shows installed version v0.1.1)
            # -----------------------------------------------------------------
            title_row = QHBoxLayout()
            title_row.setContentsMargins(2, 0, 2, 2)
            title_lbl = QLabel(
                f"✦  HDRSnip Fusion v{APP_VERSION} — Frutiger Aqua Settings"
            )
            title_lbl.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: #FFFFFF;"
            )
            title_row.addWidget(title_lbl)
            title_row.addStretch()

            close_x = AeroGelButton("✕", variant="ruby", parent=self)
            close_x.setFixedSize(30, 26)
            close_x.clicked.connect(self.reject)
            title_row.addWidget(close_x)
            outer_layout.addLayout(title_row)

            # Transparent Scroll Area so all 6 cards remain responsive on high-DPI displays
            self.scroll_area = QScrollArea(self)
            self.scroll_area.setObjectName("AquaScrollArea")
            self.scroll_area.setWidgetResizable(True)
            self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            self.scroll_area.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self.scroll_contents = QWidget(self.scroll_area)
            self.scroll_contents.setObjectName("AquaScrollContents")
            cards_layout = QVBoxLayout(self.scroll_contents)
            cards_layout.setContentsMargins(0, 0, 4, 0)
            cards_layout.setSpacing(9)

            # Helper for aligned label + control rows
            def _add_labeled_row(
                parent_vbox: QVBoxLayout, label_text: str, field_widget: QWidget
            ) -> None:
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(10)
                lbl = QLabel(label_text)
                lbl.setFixedWidth(self.LABEL_COL_WIDTH)
                lbl.setAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                row.addWidget(lbl)
                row.addWidget(field_widget, 1)
                parent_vbox.addLayout(row)

            def _make_divider(parent_widget: QWidget) -> QFrame:
                div = QFrame(parent_widget)
                div.setObjectName("SectionDivider")
                div.setFrameShape(QFrame.Shape.HLine)
                return div

            # -----------------------------------------------------------------
            # Card 1: Capture & Startup
            # -----------------------------------------------------------------
            capture_card = QFrame(self.scroll_contents)
            capture_card.setObjectName("AquaSectionCard")
            cap_vbox = QVBoxLayout(capture_card)
            cap_vbox.setContentsMargins(14, 9, 14, 10)
            cap_vbox.setSpacing(7)

            cap_hdr = QLabel("◆  CAPTURE & STARTUP", capture_card)
            cap_hdr.setObjectName("SectionHeader")
            cap_vbox.addWidget(cap_hdr)

            self.key_edit = QKeySequenceEdit(QKeySequence(config.hotkey_str))
            self.key_edit.setToolTip(
                "Global capture shortcut registered via Win32 RegisterHotKey (game & anti-cheat safe)"
            )
            _add_labeled_row(cap_vbox, "Capture Hotkey:", self.key_edit)

            cap_vbox.addWidget(_make_divider(capture_card))

            cap_chk_row = QHBoxLayout()
            cap_chk_row.setContentsMargins(2, 0, 2, 0)
            cap_chk_row.setSpacing(16)
            self.startup_chk = QCheckBox("Start in tray when Windows starts")
            self.startup_chk.setChecked(config.start_with_windows)
            self.fallback_chk = QCheckBox(
                "Allow SDR fallback if HDR capture is unavailable"
            )
            self.fallback_chk.setToolTip(
                "Explicit opt-in for ordinary 8-bit SDR capture fallback (may overexpose active HDR displays)"
            )
            self.fallback_chk.setChecked(config.allow_sdr_fallback)
            cap_chk_row.addWidget(self.startup_chk)
            cap_chk_row.addWidget(self.fallback_chk, 1)
            cap_vbox.addLayout(cap_chk_row)
            cards_layout.addWidget(capture_card)

            # -----------------------------------------------------------------
            # Card 2: Screenshot Saving (Part 1 — Default Save Location)
            # -----------------------------------------------------------------
            saving_card = QFrame(self.scroll_contents)
            saving_card.setObjectName("AquaSectionCard")
            sav_vbox = QVBoxLayout(saving_card)
            sav_vbox.setContentsMargins(14, 9, 14, 10)
            sav_vbox.setSpacing(7)

            sav_hdr = QLabel("◆  SCREENSHOT SAVING", saving_card)
            sav_hdr.setObjectName("SectionHeader")
            sav_vbox.addWidget(sav_hdr)

            save_loc_row = QWidget(saving_card)
            save_loc_layout = QHBoxLayout(save_loc_row)
            save_loc_layout.setContentsMargins(0, 0, 0, 0)
            save_loc_layout.setSpacing(8)

            self.save_dir_edit = QLineEdit(self._selected_save_directory, save_loc_row)
            self.save_dir_edit.setObjectName("SavePathEdit")
            self.save_dir_edit.setReadOnly(True)
            self.save_dir_edit.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self.save_dir_edit.setToolTip(
                f"Default Save Location: {self._selected_save_directory}\n"
                "Clicking Save (Ctrl+S) or Quick Save (Ctrl+Shift+S) writes PNGs directly here. "
                "Press Ctrl+Alt+S in the overlay to Save As to a custom path."
            )
            self.save_dir_edit.setCursorPosition(len(self._selected_save_directory))

            self.browse_save_dir_btn = AeroGelButton(
                "Browse...", variant="sapphire", parent=save_loc_row
            )
            self.browse_save_dir_btn.setToolTip(
                "Choose the default folder where screenshots are saved when pressing Save or Ctrl+S"
            )
            self.browse_save_dir_btn.clicked.connect(self._on_browse_save_directory)

            save_loc_layout.addWidget(self.save_dir_edit, 1)
            save_loc_layout.addWidget(self.browse_save_dir_btn)
            _add_labeled_row(sav_vbox, "Default Save Location:", save_loc_row)
            cards_layout.addWidget(saving_card)

            # -----------------------------------------------------------------
            # Card 3: Frutiger Aqua Glass & Animation
            # -----------------------------------------------------------------
            visuals_card = QFrame(self.scroll_contents)
            visuals_card.setObjectName("AquaSectionCard")
            vis_vbox = QVBoxLayout(visuals_card)
            vis_vbox.setContentsMargins(14, 9, 14, 10)
            vis_vbox.setSpacing(7)

            vis_hdr = QLabel("◆  FRUTIGER AQUA GLASS & ANIMATION", visuals_card)
            vis_hdr.setObjectName("SectionHeader")
            vis_vbox.addWidget(vis_hdr)

            self.anim_combo = QComboBox()
            self.anim_combo.addItem("Off — Static Frutiger Aqua Glass", "off")
            self.anim_combo.addItem("Subtle — Calm Water & Gentle Gel", "subtle")
            self.anim_combo.addItem(
                "Medium — Living Water & Tactile Gel (Default)", "medium"
            )
            self.anim_combo.addItem(
                "High — Deep Optical Caustics & Rich Refraction", "high"
            )
            anim_idx = self.anim_combo.findData(config.animation_intensity)
            if anim_idx >= 0:
                self.anim_combo.setCurrentIndex(anim_idx)
            self.anim_combo.currentIndexChanged.connect(
                self._on_anim_intensity_preview
            )
            _add_labeled_row(vis_vbox, "Animation Intensity:", self.anim_combo)

            trans_row = QWidget(visuals_card)
            trans_layout = QHBoxLayout(trans_row)
            trans_layout.setContentsMargins(0, 0, 0, 0)
            trans_layout.setSpacing(10)
            self.trans_slider = AeroLiquidSlider(Qt.Orientation.Horizontal, trans_row)
            self.trans_slider.setRange(10, 95)
            self.trans_slider.setValue(int(config.glass_transparency))
            self.trans_slider.setToolTip(
                "Adjust how transparent the Frutiger Aqua glass toolbar, badges, and gel buttons are (10% - 95%)"
            )
            self.trans_val_lbl = QLabel(f"{self.trans_slider.value()}%", trans_row)
            self.trans_val_lbl.setObjectName("ValueBadge")
            self.trans_val_lbl.setFixedWidth(46)
            self.trans_val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trans_slider.valueChanged.connect(self._on_transparency_preview)
            trans_layout.addWidget(self.trans_slider, 1)
            trans_layout.addWidget(self.trans_val_lbl)
            _add_labeled_row(vis_vbox, "Glass Transparency:", trans_row)
            cards_layout.addWidget(visuals_card)

            # -----------------------------------------------------------------
            # Card 4: HDR Capture & Tone Mapping
            # -----------------------------------------------------------------
            hdr_card = QFrame(self.scroll_contents)
            hdr_card.setObjectName("AquaSectionCard")
            hdr_vbox = QVBoxLayout(hdr_card)
            hdr_vbox.setContentsMargins(14, 9, 14, 10)
            hdr_vbox.setSpacing(7)

            hdr_hdr = QLabel("◆  HDR CAPTURE & TONE MAPPING", hdr_card)
            hdr_hdr.setObjectName("SectionHeader")
            hdr_vbox.addWidget(hdr_hdr)

            self.mode_combo = QComboBox()
            self.mode_combo.addItem(
                "Balanced SDR White + Highlight Roll-Off (Recommended)",
                "sdr_exact_knee",
            )
            self.mode_combo.addItem(
                "Extended Reinhard Luminance", "reinhard_luma"
            )
            self.mode_combo.addItem("ACES Filmic Curve", "aces_filmic")
            idx = self.mode_combo.findData(config.tone_map_mode)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
            _add_labeled_row(hdr_vbox, "Tone Mapping Curve:", self.mode_combo)

            self.nits_spin = QDoubleSpinBox()
            self.nits_spin.setRange(0.0, 1000.0)
            self.nits_spin.setSingleStep(10.0)
            self.nits_spin.setDecimals(0)
            self.nits_spin.setSpecialValueText("Auto-Detect (DisplayConfig)")
            self.nits_spin.setSuffix(" nits")
            self.nits_spin.setValue(config.manual_sdr_nits)
            self.nits_spin.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self.nits_spin.setToolTip(
                "Target display SDR reference white level in nits (0 = Auto-detect via Windows DisplayConfig)"
            )
            _add_labeled_row(hdr_vbox, "SDR White Level:", self.nits_spin)

            self.knee_spin = QDoubleSpinBox()
            self.knee_spin.setRange(0.50, 0.98)
            self.knee_spin.setSingleStep(0.05)
            self.knee_spin.setDecimals(2)
            self.knee_spin.setValue(config.knee_start)
            self.knee_spin.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self.knee_spin.setToolTip(
                "Threshold where highlight roll-off compression begins (e.g. 0.80 = 80% linear SDR white)"
            )
            _add_labeled_row(hdr_vbox, "Highlight Roll-Off Knee:", self.knee_spin)

            hdr_vbox.addWidget(_make_divider(hdr_card))

            self.gamma_chk = QCheckBox(
                "Apply Gamma 2.2 TRC correction (fixes washed-out Auto-HDR dark shadows)"
            )
            self.gamma_chk.setChecked(config.auto_hdr_gamma22_fix)
            hdr_vbox.addWidget(self.gamma_chk)

            self.white_boost_chk = QCheckBox(
                "Lift neutral SDR whites to 255 (may clip the brightest HDR highlights)"
            )
            self.white_boost_chk.setChecked(config.boost_sdr_whites)
            hdr_vbox.addWidget(self.white_boost_chk)
            cards_layout.addWidget(hdr_card)

            # -----------------------------------------------------------------
            # Card 5: Application Updates (Part 2 — Built-in GitHub Updater)
            # -----------------------------------------------------------------
            updates_card = QFrame(self.scroll_contents)
            updates_card.setObjectName("AquaSectionCard")
            upd_vbox = QVBoxLayout(updates_card)
            upd_vbox.setContentsMargins(14, 9, 14, 10)
            upd_vbox.setSpacing(7)

            upd_hdr = QLabel("◆  APPLICATION UPDATES", updates_card)
            upd_hdr.setObjectName("SectionHeader")
            upd_vbox.addWidget(upd_hdr)

            ver_row = QHBoxLayout()
            ver_row.setContentsMargins(0, 0, 0, 0)
            ver_row.setSpacing(10)
            mode_tag = "Packaged EXE" if is_packaged_exe() else "Python Source"
            self.current_version_lbl = QLabel(
                f"Current Version: v{APP_VERSION}  ({mode_tag})", updates_card
            )
            self.current_version_lbl.setStyleSheet(
                "color: #FFFFFF; font-weight: bold;"
            )
            ver_row.addWidget(self.current_version_lbl, 1)

            self.install_update_btn = AeroGelButton(
                "Update Now...", variant="emerald", parent=updates_card
            )
            self.install_update_btn.hide()
            self.install_update_btn.clicked.connect(self._on_install_available_update)
            ver_row.addWidget(self.install_update_btn)

            self.check_updates_btn = AeroGelButton(
                "Check for Updates", variant="sapphire", parent=updates_card
            )
            self.check_updates_btn.setToolTip(
                f"Check official GitHub Releases ({GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}) for a newer stable version"
            )
            self.check_updates_btn.clicked.connect(self._on_check_for_updates_clicked)
            ver_row.addWidget(self.check_updates_btn)
            upd_vbox.addLayout(ver_row)

            upd_chk_row = QHBoxLayout()
            upd_chk_row.setContentsMargins(2, 0, 2, 0)
            upd_chk_row.setSpacing(16)
            self.auto_check_updates_chk = QCheckBox(
                "Automatically check for updates", updates_card
            )
            self.auto_check_updates_chk.setChecked(config.auto_check_updates)
            self.auto_install_updates_chk = QCheckBox(
                "Automatically download updates in background", updates_card
            )
            self.auto_install_updates_chk.setToolTip(
                "Downloads and SHA-256 verifies stable updates in the background, then prompts to restart and install with helper verification"
            )
            self.auto_install_updates_chk.setChecked(config.auto_install_updates)
            upd_chk_row.addWidget(self.auto_check_updates_chk)
            upd_chk_row.addWidget(self.auto_install_updates_chk, 1)
            upd_vbox.addLayout(upd_chk_row)

            self.update_status_lbl = QLabel(
                "You're running the latest version.", updates_card
            )
            self.update_status_lbl.setObjectName("UpdateStatusLabel")
            self.update_status_lbl.setWordWrap(True)
            upd_vbox.addWidget(self.update_status_lbl)
            self._refresh_update_status_display()
            cards_layout.addWidget(updates_card)

            # -----------------------------------------------------------------
            # Card 6: Stability & Diagnostics (Lower-Priority Subordinated Card)
            # -----------------------------------------------------------------
            diag_card = QFrame(self.scroll_contents)
            diag_card.setObjectName("AquaDiagCard")
            diag_vbox = QVBoxLayout(diag_card)
            diag_vbox.setContentsMargins(14, 8, 14, 9)
            diag_vbox.setSpacing(6)

            diag_hdr_row = QHBoxLayout()
            diag_hdr_row.setContentsMargins(0, 0, 0, 0)
            diag_hdr_lbl = QLabel("◆  STABILITY & DIAGNOSTICS", diag_card)
            diag_hdr_lbl.setObjectName("DiagSectionHeader")
            diag_hdr_row.addWidget(diag_hdr_lbl)
            diag_hdr_row.addStretch()
            diag_vbox.addLayout(diag_hdr_row)

            self.safe_mode_banner = QLabel(diag_card)
            self.safe_mode_banner.setWordWrap(True)
            self.safe_mode_banner.setStyleSheet(
                """
                QLabel {
                    background: rgba(0, 42, 84, 195);
                    color: #98FFFF;
                    border: 1px solid rgba(0, 229, 255, 185);
                    border-radius: 8px;
                    padding: 5px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
                """
            )
            diag_vbox.addWidget(self.safe_mode_banner)

            # Primary Diagnostic Safe Mode & Persistent Logging row
            diag_top_row = QHBoxLayout()
            diag_top_row.setContentsMargins(0, 0, 0, 0)
            diag_top_row.setSpacing(14)
            self.safe_mode_chk = QCheckBox("Enable Diagnostic Safe Mode")
            self.safe_mode_chk.setToolTip(
                "Pauses continuous water animations, decorative ripples, Win32 DWM Acrylic blur, and async workers"
            )
            self.safe_mode_chk.setChecked(config.is_safe_mode_active)
            self.safe_mode_chk.toggled.connect(self._on_safe_mode_toggled)

            self.diag_log_chk = QCheckBox("Write persistent diagnostic log")
            self.diag_log_chk.setToolTip(
                r"Writes bounded milestone logs to %APPDATA%\HDRSnip Fusion\diagnostics.log"
            )
            self.diag_log_chk.setChecked(config.enable_diagnostic_logging)
            diag_top_row.addWidget(self.safe_mode_chk)
            diag_top_row.addWidget(self.diag_log_chk, 1)
            diag_vbox.addLayout(diag_top_row)

            diag_vbox.addWidget(_make_divider(diag_card))

            # Compact 2x2 Subsystem Isolation Grid (keeps advanced flags tidy & accessible)
            iso_grid = QGridLayout()
            iso_grid.setContentsMargins(0, 0, 0, 0)
            iso_grid.setHorizontalSpacing(14)
            iso_grid.setVerticalSpacing(5)

            self.disable_cont_anim_chk = QCheckBox(
                "Isolate: Pause continuous water animation"
            )
            self.disable_cont_anim_chk.setObjectName("DiagIsoCheck")
            self.disable_cont_anim_chk.setChecked(
                config.disable_continuous_animations
            )
            self.disable_cont_anim_chk.toggled.connect(self._on_safe_mode_toggled)

            self.disable_workers_chk = QCheckBox(
                "Isolate: Disable async tone-map workers"
            )
            self.disable_workers_chk.setObjectName("DiagIsoCheck")
            self.disable_workers_chk.setChecked(config.disable_async_tone_workers)
            self.disable_workers_chk.toggled.connect(self._on_safe_mode_toggled)

            self.disable_acrylic_chk = QCheckBox(
                "Isolate: Disable Win32 DWM Acrylic blur"
            )
            self.disable_acrylic_chk.setObjectName("DiagIsoCheck")
            self.disable_acrylic_chk.setChecked(config.disable_dwm_acrylic_blur)
            self.disable_acrylic_chk.toggled.connect(self._on_safe_mode_toggled)

            self.disable_hdr_dxgi_chk = QCheckBox(
                "Isolate: Bypass native DXGI (SDR-only)"
            )
            self.disable_hdr_dxgi_chk.setObjectName("DiagIsoCheck")
            self.disable_hdr_dxgi_chk.setToolTip(
                "Bypasses native DXGI/D3D11 Desktop Duplication and uses SDR ImageGrab (inaccurate for HDR displays)"
            )
            self.disable_hdr_dxgi_chk.setChecked(config.disable_native_hdr_capture)
            self.disable_hdr_dxgi_chk.toggled.connect(self._on_safe_mode_toggled)

            iso_grid.addWidget(self.disable_cont_anim_chk, 0, 0)
            iso_grid.addWidget(self.disable_workers_chk, 0, 1)
            iso_grid.addWidget(self.disable_acrylic_chk, 1, 0)
            iso_grid.addWidget(self.disable_hdr_dxgi_chk, 1, 1)
            diag_vbox.addLayout(iso_grid)

            self._update_safe_mode_banner()
            cards_layout.addWidget(diag_card)
            cards_layout.addStretch(1)

            self.scroll_area.setWidget(self.scroll_contents)
            outer_layout.addWidget(self.scroll_area, 1)

            # -----------------------------------------------------------------
            # Bottom Action Bar (Always Pinned & Visible)
            # -----------------------------------------------------------------
            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(0, 2, 0, 0)
            btn_row.setSpacing(8)
            open_log_btn = AeroGelButton(
                "Open Diagnostics Log", variant="sapphire", parent=self
            )
            open_log_btn.setToolTip(str(DIAGNOSTIC_LOG_FILE))
            open_log_btn.clicked.connect(self._open_diagnostic_log)
            save_btn = AeroGelButton("Save & Apply", variant="emerald", parent=self)
            save_btn.clicked.connect(self.accept)
            cancel_btn = AeroGelButton("Cancel", variant="glass", parent=self)
            cancel_btn.clicked.connect(self.reject)
            btn_row.addWidget(open_log_btn)
            btn_row.addStretch()
            btn_row.addWidget(cancel_btn)
            btn_row.addWidget(save_btn)
            outer_layout.addLayout(btn_row)

        def set_selected_save_directory(self, folder_path: str) -> None:
            """Updates the pending save directory in the dialog without committing to AppConfig until Save & Apply."""
            cleaned = str(folder_path or "").strip()
            if not cleaned:
                return
            self._selected_save_directory = cleaned
            self.save_dir_edit.setText(cleaned)
            self.save_dir_edit.setToolTip(
                f"Default Save Location: {cleaned}\n"
                "Clicking Save (Ctrl+S) or Quick Save (Ctrl+Shift+S) writes PNGs directly here. "
                "Press Ctrl+Alt+S in the overlay to Save As to a custom path."
            )
            self.save_dir_edit.setCursorPosition(len(cleaned))

        def _on_browse_save_directory(self) -> None:
            start_dir = self._selected_save_directory
            try:
                p = Path(start_dir).expanduser()
                if not p.exists():
                    if p.parent.exists():
                        start_dir = str(p.parent)
                    else:
                        start_dir = str(Path.home())
            except Exception:
                start_dir = str(Path.home())

            chosen = QFileDialog.getExistingDirectory(
                self,
                "Select Default Screenshot Save Location",
                start_dir,
                QFileDialog.Option.ShowDirsOnly
                | QFileDialog.Option.DontResolveSymlinks,
            )
            if chosen:
                self.set_selected_save_directory(chosen)

        def _refresh_update_status_display(self) -> None:
            res = self._latest_check_result
            if res is None:
                if (
                    self.config.staged_update_version
                    and is_newer_semver(self.config.staged_update_version, APP_VERSION)
                    and self.config.staged_update_path
                    and Path(self.config.staged_update_path).exists()
                ):
                    self.update_status_lbl.setText(
                        f"Update v{self.config.staged_update_version} is downloaded and verified. Click Restart & Install to apply."
                    )
                    if is_packaged_exe() and self.controller is not None:
                        self.install_update_btn.setText(
                            f"Restart & Install v{self.config.staged_update_version}..."
                        )
                        self.install_update_btn.show()
                    else:
                        self.install_update_btn.hide()
                else:
                    self.update_status_lbl.setText("You're running the latest version.")
                    self.install_update_btn.hide()
                return

            self.update_status_lbl.setText(res.message or "You're running the latest version.")
            if res.status == "update_available":
                self.install_update_btn.setText(
                    f"Update to v{res.latest_version}..."
                    if is_packaged_exe()
                    else f"View v{res.latest_version} Release"
                )
                self.install_update_btn.show()
            else:
                self.install_update_btn.hide()

        def _on_check_for_updates_clicked(self) -> None:
            self.check_updates_btn.setEnabled(False)
            self.update_status_lbl.setText("Checking GitHub Releases for updates...")
            if self.controller is not None:
                self.controller.check_for_updates(
                    manual_request=True, notify_dialog_callback=self._on_local_update_check_done
                )
            else:
                job = UpdateCheckJob(self._local_update_signals, manual_request=True)
                QThreadPool.globalInstance().start(job)

        def _on_local_update_check_done(
            self, result: UpdateCheckResult, _manual: bool = True
        ) -> None:
            self.check_updates_btn.setEnabled(True)
            self._latest_check_result = result
            self._refresh_update_status_display()

        def _on_install_available_update(self) -> None:
            if self._latest_check_result is None:
                if (
                    self.controller is not None
                    and is_packaged_exe()
                    and self.config.staged_update_version
                    and is_newer_semver(self.config.staged_update_version, APP_VERSION)
                    and self.config.staged_update_path
                    and self.config.staged_update_sha256
                ):
                    staged_p = Path(self.config.staged_update_path)
                    if staged_p.exists():
                        self.accept()
                        self.controller._execute_staged_update_and_exit(
                            self.config.staged_update_version,
                            staged_p,
                            self.config.staged_update_sha256,
                            restart_after_update=True,
                        )
                return
            if self.controller is not None:
                self.controller.present_update_prompt(
                    self._latest_check_result, parent=self
                )
            else:
                url = self._latest_check_result.release_url or GITHUB_RELEASES_PAGE_URL
                if is_valid_github_url(url, require_repo_prefix=True):
                    webbrowser.open(url)

        def _update_safe_mode_banner(self) -> None:
            sm = bool(self.safe_mode_chk.isChecked() or ENV_SAFE_MODE)
            hdr_bypass = bool(self.disable_hdr_dxgi_chk.isChecked())
            if sm:
                extra = (
                    " | WARNING: Native DXGI HDR capture is ALSO bypassed (SDR-only)."
                    if hdr_bypass
                    else " | Native DXGI HDR capture remains active."
                )
                self.safe_mode_banner.setText(
                    f"🛡️ DIAGNOSTIC SAFE MODE ENABLED: Continuous water animations, decorative ripples, "
                    f"DWM Acrylic blur, and background workers are paused.{extra}"
                )
            elif (
                self.disable_cont_anim_chk.isChecked()
                or self.disable_workers_chk.isChecked()
                or self.disable_acrylic_chk.isChecked()
                or hdr_bypass
            ):
                active_flags = []
                if self.disable_cont_anim_chk.isChecked():
                    active_flags.append("No Continuous Anim")
                if self.disable_workers_chk.isChecked():
                    active_flags.append("No Async Workers")
                if self.disable_acrylic_chk.isChecked():
                    active_flags.append("No DWM Acrylic")
                if hdr_bypass:
                    active_flags.append("DXGI Bypassed (SDR-Only)")
                self.safe_mode_banner.setText(
                    "🔍 Diagnostic Isolation Active: " + ", ".join(active_flags)
                )
            else:
                self.safe_mode_banner.setText(
                    "Standard Frutiger Aqua Mode (Diagnostic Safe Mode is OFF; persistent logging ready)."
                )

        def _on_safe_mode_toggled(self, _checked: bool = False) -> None:
            self._update_safe_mode_banner()
            self._water_dirty = True
            director = AeroAnimationDirector.instance()
            director._safe_mode = bool(self.safe_mode_chk.isChecked() or ENV_SAFE_MODE)
            director._disable_continuous = bool(self.disable_cont_anim_chk.isChecked())
            director._sync_timer()
            enable_windows_acrylic_blur(
                int(self.winId()),
                0,
                disable_blur=True,
            )
            self.update()

        def _open_diagnostic_log(self) -> None:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            if not DIAGNOSTIC_LOG_FILE.exists():
                DIAG_LOG.milestone("LOG_VIEW", "Created diagnostic log file on user request")
            if sys.platform == "win32":
                try:
                    os.startfile(str(DIAGNOSTIC_LOG_FILE if DIAGNOSTIC_LOG_FILE.exists() else CONFIG_DIR))
                except Exception:
                    os.startfile(str(CONFIG_DIR))

        def _on_anim_intensity_preview(self) -> None:
            level = self.anim_combo.currentData()
            if level:
                self._water_dirty = True
                AeroAnimationDirector.instance().set_intensity(str(level))
                self.update()

        def _on_transparency_preview(self, pct: int) -> None:
            clamped = max(10, min(95, int(pct)))
            self.trans_val_lbl.setText(f"{clamped}%")
            self._cached_base_pix = None
            self._water_dirty = True
            AeroAnimationDirector.instance().set_transparency(clamped)
            enable_windows_acrylic_blur(
                int(self.winId()),
                0,
                disable_blur=True,
            )
            self.update()

        def on_transparency_changed(self) -> None:
            self._cached_base_pix = None
            self._water_dirty = True
            self.update()
            for child in self.findChildren((AeroGelButton, AeroLiquidSlider)):
                if child.isVisible():
                    child.update()

        def showEvent(self, event) -> None:
            self._water_dirty = True
            # Size dialog comfortably to fit all 6 cards without exceeding high-DPI display bounds
            try:
                scr = self.screen() or QGuiApplication.primaryScreen()
                if scr is not None:
                    avail = scr.availableGeometry()
                    ideal_h = min(845, max(540, avail.height() - 44))
                    self.resize(max(568, self.width()), ideal_h)
            except Exception:
                pass
            super().showEvent(event)
            pct = int(self.trans_slider.value())
            enable_windows_acrylic_blur(
                int(self.winId()),
                0,
                disable_blur=True,
            )
            director = AeroAnimationDirector.instance()
            director.apply_config_flags(self.config)
            director.set_intensity(
                str(self.anim_combo.currentData() or self.config.animation_intensity)
            )
            director.set_transparency(pct)
            director.register_surface(self)
            director.notify_visibility_changed()

        def on_animation_tick(self) -> None:
            if not self.isVisible():
                return
            self._water_dirty = True
            self.update()
            if AeroAnimationDirector.instance().scale > 0.0:
                for child in self.findChildren(AeroGelButton):
                    if child.isVisible():
                        child.update()

        def on_animations_disabled(self) -> None:
            self._water_dirty = True
            for child in self.findChildren(QWidget):
                if hasattr(child, "reset_animation_state"):
                    child.reset_animation_state()
            if self.isVisible():
                self.update()

        def cleanup_resources(self) -> None:
            AeroAnimationDirector.instance().unregister_surface(self)
            self.on_animations_disabled()
            self._cached_base_pix = None
            self._cached_water_frame = None
            _SHARED_DIALOG_OPTICAL_RENDERER.clear_backdrop()

        def hideEvent(self, event) -> None:
            self.on_animations_disabled()
            super().hideEvent(event)
            AeroAnimationDirector.instance().unregister_surface(self)

        def reject(self) -> None:
            # Restore original animation intensity, transparency & Safe Mode flags if user cancels;
            # unsaved changes to _selected_save_directory or update checkboxes are discarded.
            director = AeroAnimationDirector.instance()
            director.apply_config_flags(self.config)
            director.set_intensity(self._original_intensity)
            director.set_transparency(self._original_transparency)
            super().reject()

        def paintEvent(self, event) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            rect = QRectF(self.rect()).adjusted(6.0, 6.0, -6.0, -6.0)
            w = max(1, self.width())
            h = max(1, self.height())

            if (
                self._cached_base_pix is None
                or self._cached_base_pix.size() != self.size()
            ):
                base_pix = QPixmap(w, h)
                base_pix.fill(Qt.GlobalColor.transparent)
                bp = QPainter(base_pix)
                bp.setRenderHint(QPainter.RenderHint.Antialiasing)
                draw_frutiger_glass_base(
                    bp, rect, radius=20.0, frosted_pixmap=None, tint_style="dialog"
                )
                bp.end()
                self._cached_base_pix = base_pix
                self._water_dirty = True

            director = AeroAnimationDirector.instance()
            eff_dlg = director.scale
            if (
                getattr(self, "_water_dirty", True)
                or getattr(self, "_cached_water_frame", None) is None
                or self._cached_water_frame.size() != self.size()
                or getattr(self, "_cached_dlg_scale", -1.0) != eff_dlg
            ):
                if (
                    getattr(self, "_cached_water_frame", None) is None
                    or self._cached_water_frame.size() != self.size()
                ):
                    self._cached_water_frame = QPixmap(w, h)
                self._cached_water_frame.fill(Qt.GlobalColor.transparent)
                fp = QPainter(self._cached_water_frame)
                fp.setRenderHint(QPainter.RenderHint.Antialiasing)
                fp.drawPixmap(0, 0, self._cached_base_pix)
                draw_frutiger_glass_Dynamic_Overlay(
                    fp,
                    rect,
                    radius=20.0,
                    t_sec=director.elapsed_seconds(),
                    intensity_scale=eff_dlg,
                    wave_paths=self._wave_paths,
                )
                fp.end()
                self._cached_dlg_scale = eff_dlg
                self._water_dirty = False

            if self._cached_water_frame is not None:
                dirty_rc = event.rect()
                painter.drawPixmap(dirty_rc, self._cached_water_frame, dirty_rc)

        def mousePressEvent(self, event) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:
            if (
                self._drag_offset is not None
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                self.move(event.globalPosition().toPoint() - self._drag_offset)
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:
            self._drag_offset = None
            super().mouseReleaseEvent(event)

        def apply_to_config(self) -> None:
            seq = self.key_edit.keySequence().toString()
            if seq:
                self.config.hotkey_str = seq
            chosen_save_dir = str(self._selected_save_directory or "").strip()
            if chosen_save_dir:
                self.config.save_directory = chosen_save_dir
            anim_level = str(self.anim_combo.currentData() or "medium")
            self.config.animation_intensity = anim_level
            trans_pct = max(10, min(95, int(self.trans_slider.value())))
            self.config.glass_transparency = trans_pct
            director = AeroAnimationDirector.instance()
            director.set_intensity(anim_level)
            director.set_transparency(trans_pct)
            self.config.tone_map_mode = self.mode_combo.currentData()
            self.config.manual_sdr_nits = float(self.nits_spin.value())
            self.config.knee_start = float(self.knee_spin.value())
            self.config.auto_hdr_gamma22_fix = bool(self.gamma_chk.isChecked())
            self.config.allow_sdr_fallback = bool(self.fallback_chk.isChecked())
            self.config.start_with_windows = bool(self.startup_chk.isChecked())
            self.config.boost_sdr_whites = bool(self.white_boost_chk.isChecked())
            self.config.auto_check_updates = bool(
                self.auto_check_updates_chk.isChecked()
            )
            self.config.auto_install_updates = bool(
                self.auto_install_updates_chk.isChecked()
            )
            self.config.diagnostic_safe_mode = bool(self.safe_mode_chk.isChecked())
            self.config.disable_continuous_animations = bool(
                self.disable_cont_anim_chk.isChecked()
            )
            self.config.disable_async_tone_workers = bool(
                self.disable_workers_chk.isChecked()
            )
            self.config.disable_dwm_acrylic_blur = bool(
                self.disable_acrylic_chk.isChecked()
            )
            self.config.disable_native_hdr_capture = bool(
                self.disable_hdr_dxgi_chk.isChecked()
            )
            self.config.enable_diagnostic_logging = bool(self.diag_log_chk.isChecked())
            director.apply_config_flags(self.config)
            self.config.save()
            set_windows_autostart(self.config.start_with_windows)


    def create_tray_icon_pixmap() -> QIcon:
        """
        Generates a 3D Skeuomorphic Frutiger Aqua Glass Orb / Water-Bubble Tray Icon
        with ocean-to-cyan radial depth, aurora green inner lens, and glossy white crescent.
        """
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(32.0, 32.0)
        radius = 27.0

        # Outer aqua sphere radial gradient
        sphere_grad = QRadialGradient(QPointF(22.0, 18.0), 38.0)
        sphere_grad.setColorAt(0.0, QColor(215, 255, 255, 255))
        sphere_grad.setColorAt(0.32, QColor(0, 210, 255, 255))
        sphere_grad.setColorAt(0.72, QColor(0, 105, 205, 255))
        sphere_grad.setColorAt(1.0, QColor(0, 45, 110, 255))

        p.setBrush(QBrush(sphere_grad))
        p.setPen(QPen(QColor(215, 252, 255, 245), 2.2))
        p.drawEllipse(center, radius, radius)

        # Bottom subsurface emerald-aqua bounce glow crescent
        bounce_grad = QRadialGradient(QPointF(32.0, 50.0), 20.0)
        bounce_grad.setColorAt(0.0, QColor(115, 255, 185, 210))
        bounce_grad.setColorAt(1.0, QColor(0, 255, 200, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bounce_grad))
        p.drawEllipse(center, radius - 1.5, radius - 1.5)

        # Inner glowing viewfinder reticle
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 240), 3.0))
        p.drawRoundedRect(QRectF(19.0, 19.0, 26.0, 26.0), 6.0, 6.0)

        # Top glossy white specular reflection cap (classic Frutiger Aero orb shine)
        cap_grad = QLinearGradient(QPointF(32.0, 7.0), QPointF(32.0, 31.0))
        cap_grad.setColorAt(0.0, QColor(255, 255, 255, 235))
        cap_grad.setColorAt(0.7, QColor(255, 255, 255, 65))
        cap_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(cap_grad))
        p.drawEllipse(QRectF(13.0, 8.0, 38.0, 22.0))

        p.end()
        return QIcon(pix)


    class HDRSnipFusionApplication:
        """Main System Tray controller living in the Windows Taskbar Hidden Icons area."""

        def __init__(
            self,
            startup_confirm_file: Optional[Path] = None,
            startup_confirm_token: str = "",
            verify_startup_only: bool = False,
        ) -> None:
            self._startup_confirm_file: Optional[Path] = (
                Path(startup_confirm_file).resolve()
                if startup_confirm_file is not None
                else None
            )
            self._startup_confirm_token: str = str(
                startup_confirm_token
                or os.environ.get("HDRSNIP_STARTUP_CONFIRM_TOKEN", "")
            ).strip()
            self._verify_startup_only: bool = bool(verify_startup_only)
            ensure_per_monitor_dpi_awareness()
            QApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
            self.app = QApplication(sys.argv)
            self.app.setApplicationName("HDRSnip Fusion")
            self.app.setApplicationVersion(APP_VERSION)
            self.app.setQuitOnLastWindowClosed(False)
            self.config = AppConfig.load()
            self._snip_in_progress: bool = False
            self._shutting_down: bool = False

            # NOTE: Do NOT call cleanup_stale_update_staging() synchronously during __init__!
            # When launched by the updater helper, the helper's manifest and confirmation
            # files reside in updates/v<APP_VERSION>/. Stale staging cleanup is deferred until
            # after startup verification has completed and the helper transaction has finished.
            if self.config.staged_update_version and not is_newer_semver(
                self.config.staged_update_version, APP_VERSION
            ):
                self.config.staged_update_version = ""
                self.config.staged_update_path = ""
                self.config.staged_update_sha256 = ""
                self.config.save()

            DIAG_LOG.milestone(
                "APP_START",
                f"HDRSnip Fusion v{APP_VERSION} started (packaged={is_packaged_exe()}, "
                f"python={sys.version.split()[0]}, platform={sys.platform}, "
                f"safe_mode={self.config.is_safe_mode_active}, anim={self.config.animation_intensity}, "
                f"save_dir='{self.config.save_directory}')",
            )
            director = AeroAnimationDirector.instance()
            director.apply_config_flags(self.config)
            self.overlay: Optional[SnipOverlayWindow] = None

            # Background GitHub Release Updater state
            self._update_signals = UpdateWorkerSignals()
            self._update_signals.check_completed.connect(self._on_update_check_completed)
            self._update_signals.download_progress.connect(
                self._on_update_download_progress
            )
            self._update_signals.download_completed.connect(
                self._on_update_download_completed
            )
            self._update_signals.download_failed.connect(self._on_update_download_failed)
            self._update_check_in_progress: bool = False
            self._update_download_in_progress: bool = False
            self._update_cancel_event = threading.Event()
            self._last_update_result: Optional[UpdateCheckResult] = None
            self._pending_update_prompt_result: Optional[UpdateCheckResult] = None
            self._pending_immediate_install: Optional[Tuple[str, Path, str]] = None
            self._active_update_dialog: Optional[UpdatePromptDialog] = None
            self._settings_check_callback: Optional[
                Callable[[UpdateCheckResult, bool], None]
            ] = None

            self.tray = QSystemTrayIcon(create_tray_icon_pixmap(), self.app)
            self._update_tray_tooltip()

            self.menu = QMenu()
            self.menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.menu.setStyleSheet(
                """
                QMenu {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(22, 130, 195, 235),
                        stop:0.5 rgba(10, 68, 128, 242),
                        stop:1 rgba(18, 155, 195, 238));
                    color: #FFFFFF;
                    border: 1.5px solid rgba(175, 245, 255, 230);
                    border-radius: 12px;
                    padding: 6px;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 12px;
                    font-weight: bold;
                }
                QMenu::item {
                    padding: 7px 20px;
                    border-radius: 8px;
                }
                QMenu::item:selected {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(160, 245, 255, 210),
                        stop:0.5 rgba(0, 165, 245, 220),
                        stop:1 rgba(90, 255, 220, 215));
                    color: #002244;
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(255, 255, 255, 120);
                    margin: 4px 10px;
                }
                """
            )
            self.snip_action = QAction(
                f"✦ Take HDR Snip ({self.config.hotkey_str})", self.menu
            )
            self.snip_action.triggered.connect(self.trigger_snip)
            self.menu.addAction(self.snip_action)

            self.folder_action = QAction("Open Screenshots Folder", self.menu)
            self.folder_action.triggered.connect(self.open_screenshots_folder)
            self.menu.addAction(self.folder_action)

            self.check_updates_action = QAction(
                f"Check for Updates... (v{APP_VERSION})", self.menu
            )
            self.check_updates_action.triggered.connect(
                lambda: self.check_for_updates(manual_request=True)
            )
            self.menu.addAction(self.check_updates_action)

            self.diag_log_action = QAction("Open Diagnostic Log...", self.menu)
            self.diag_log_action.triggered.connect(self.open_diagnostic_log)
            self.menu.addAction(self.diag_log_action)

            self.settings_action = QAction(
                "Change Hotkey, Save Folder & HDR Settings...", self.menu
            )
            self.settings_action.triggered.connect(self.open_settings)
            self.menu.addAction(self.settings_action)

            self.menu.addSeparator()
            quit_action = QAction("Exit HDRSnip Fusion", self.menu)
            quit_action.triggered.connect(self.quit_app)
            self.menu.addAction(quit_action)

            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(self._on_tray_activated)
            self.tray.messageClicked.connect(self._on_tray_message_clicked)
            self.tray.show()

            self.hotkey_listener = Win32HotkeyListener(self.config.hotkey_str)
            self.hotkey_listener.hotkey_triggered.connect(self.trigger_snip)
            self.hotkey_listener.hotkey_failed.connect(
                lambda msg: self.tray.showMessage(
                    "HDRSnip Fusion Hotkey",
                    msg,
                    QSystemTrayIcon.MessageIcon.Warning,
                    7000,
                )
            )
            self.hotkey_listener.start()

            self.tray.showMessage(
                f"HDRSnip Fusion v{APP_VERSION} (Frutiger Aqua Edition)",
                f"Press {self.config.hotkey_str} to capture an HDR-corrected snip.",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )

            # Periodic background update scheduler (checks ~once per 24 hours after tray init)
            self._update_periodic_timer = QTimer(self.app)
            self._update_periodic_timer.setInterval(3600 * 1000)  # 1-hour low-overhead poll
            self._update_periodic_timer.timeout.connect(
                self._on_periodic_update_timer
            )
            self._update_periodic_timer.start()
            QTimer.singleShot(150, self._confirm_post_update_startup_ready)
            QTimer.singleShot(UPDATE_STARTUP_DELAY_MS, self._on_startup_update_check)

        def _confirm_post_update_startup_ready(self) -> None:
            """
            Emits the explicit post-update readiness signal from the active Qt event loop
            once QApplication, QSystemTrayIcon, and Win32HotkeyListener are initialized,
            and schedules deferred staging cleanup after the helper finishes verification.
            """
            if self._shutting_down:
                return
            if self._startup_confirm_file is not None:
                try:
                    write_startup_confirmation_file(
                        self._startup_confirm_file,
                        version=APP_VERSION,
                        pid=os.getpid(),
                        ppid=os.getppid(),
                        token=self._startup_confirm_token,
                    )
                    DIAG_LOG.milestone(
                        "STARTUP_CONFIRMED",
                        f"Wrote startup readiness confirmation to '{self._startup_confirm_file}' "
                        f"(pid={os.getpid()}, ppid={os.getppid()})",
                        flush_disk=True,
                    )
                except Exception as exc:
                    DIAG_LOG.error(
                        "STARTUP_CONFIRMED",
                        f"Failed to write startup confirmation file '{self._startup_confirm_file}'",
                        exc,
                    )
            if self._verify_startup_only:
                self._verify_quit_deadline = time.monotonic() + 5.0
                self._poll_verify_startup_quit()
                return
            # Defer staging cleanup so any active updater helper finishes reading confirmation
            # and cleaning up its transaction lock before stale directories are pruned.
            QTimer.singleShot(8000, self._run_deferred_staging_cleanup)

        def _poll_verify_startup_quit(self) -> None:
            if self._shutting_down:
                return
            confirm_consumed = (
                self._startup_confirm_file is None
                or not self._startup_confirm_file.exists()
            )
            if confirm_consumed or time.monotonic() >= getattr(
                self, "_verify_quit_deadline", 0.0
            ):
                self.quit_app(skip_auto_update_on_exit=True)
            else:
                QTimer.singleShot(60, self._poll_verify_startup_quit)

        def _run_deferred_staging_cleanup(self) -> None:
            if self._shutting_down:
                return
            cleanup_stale_update_staging(
                APP_VERSION,
                LOCAL_UPDATE_ROOT_DIR,
                protect_confirm_file=self._startup_confirm_file,
            )
            if is_packaged_exe():
                finalize_pending_update_verification(
                    get_current_executable_path(), current_version=APP_VERSION
                )

        def is_snip_session_active(self) -> bool:
            """Returns True when a screenshot capture or overlay annotation session is open."""
            return bool(
                self._snip_in_progress
                or (self.overlay is not None and self.overlay.isVisible())
            )

        def _on_startup_update_check(self) -> None:
            if self._shutting_down or not self.config.auto_check_updates:
                return
            self.check_for_updates(manual_request=False)

        def _on_periodic_update_timer(self) -> None:
            if self._shutting_down or not self.config.auto_check_updates:
                return
            elapsed = time.time() - float(self.config.last_update_check_epoch or 0.0)
            if elapsed >= UPDATE_CHECK_INTERVAL_SEC:
                self.check_for_updates(manual_request=False)

        def check_for_updates(
            self,
            *,
            manual_request: bool = False,
            notify_dialog_callback: Optional[
                Callable[[UpdateCheckResult, bool], None]
            ] = None,
        ) -> None:
            """Starts a non-blocking GitHub Releases check on the worker thread pool."""
            if self._shutting_down:
                return
            if notify_dialog_callback is not None:
                self._settings_check_callback = notify_dialog_callback
            if self._update_check_in_progress:
                return
            self._update_check_in_progress = True
            DIAG_LOG.log(
                "UPDATER",
                f"Starting GitHub update check (manual={manual_request}, current=v{APP_VERSION})",
            )
            job = UpdateCheckJob(self._update_signals, manual_request=manual_request)
            QThreadPool.globalInstance().start(job)

        def _on_update_check_completed(
            self, result: UpdateCheckResult, manual_request: bool
        ) -> None:
            self._update_check_in_progress = False
            self._last_update_result = result
            if result.status in ("up_to_date", "update_available", "asset_pending"):
                self.config.last_update_check_epoch = time.time()
                self.config.save()

            DIAG_LOG.log(
                "UPDATER",
                f"Update check finished: status={result.status}, latest=v{result.latest_version}, "
                f"manual={manual_request}, msg='{result.message}'",
            )

            cb = self._settings_check_callback
            self._settings_check_callback = None
            if cb is not None:
                try:
                    cb(result, manual_request)
                except Exception:
                    pass

            if self._shutting_down:
                return

            if result.status == "update_available":
                self.check_updates_action.setText(
                    f"✦ Update Available: v{result.latest_version}..."
                )
                # If automatic download & install is enabled in packaged EXE mode,
                # stage the verified executable quietly in the background
                if (
                    self.config.auto_install_updates
                    and is_packaged_exe()
                    and not manual_request
                ):
                    is_prot, _ = is_protected_install_location()
                    if not is_prot:
                        self.start_update_download(
                            result, install_immediately=False, manual_request=False
                        )
                        return

                # Respect user's declined version during automatic checks (unless manual)
                if (
                    not manual_request
                    and self.config.declined_update_version
                    and not is_newer_semver(
                        result.latest_version, self.config.declined_update_version
                    )
                ):
                    DIAG_LOG.log(
                        "UPDATER",
                        f"Suppressing automatic notification for previously declined version v{result.latest_version}",
                    )
                    return

                # Never interrupt an active screenshot or annotation session!
                if self.is_snip_session_active():
                    self._pending_update_prompt_result = result
                    return

                if manual_request:
                    self.present_update_prompt(result)
                else:
                    self._pending_update_prompt_result = result
                    self.tray.showMessage(
                        f"HDRSnip Fusion v{result.latest_version} is available",
                        "A new stable version is ready. Click here or open Settings to review and install.",
                        QSystemTrayIcon.MessageIcon.Information,
                        7500,
                    )
            elif manual_request and cb is None:
                # Manual check invoked from tray menu
                QMessageBox.information(
                    None,
                    f"HDRSnip Fusion v{APP_VERSION} — Updates",
                    result.message or f"You're running the latest version (v{APP_VERSION}).",
                )

        def _on_tray_message_clicked(self) -> None:
            if (
                self._pending_update_prompt_result is not None
                and not self.is_snip_session_active()
            ):
                res = self._pending_update_prompt_result
                self._pending_update_prompt_result = None
                self.present_update_prompt(res)

        def present_update_prompt(
            self,
            result: UpdateCheckResult,
            parent: Optional[QWidget] = None,
        ) -> None:
            if self._shutting_down or self.is_snip_session_active():
                self._pending_update_prompt_result = result
                return
            if (
                self._active_update_dialog is not None
                and self._active_update_dialog.isVisible()
            ):
                self._active_update_dialog.raise_()
                self._active_update_dialog.activateWindow()
                return

            dlg = UpdatePromptDialog(result, self, parent=parent)
            self._active_update_dialog = dlg
            try:
                dlg.exec()
            finally:
                if self._active_update_dialog is dlg:
                    self._active_update_dialog = None
                dlg.deleteLater()

        def start_update_download(
            self,
            check_result: UpdateCheckResult,
            *,
            install_immediately: bool = False,
            manual_request: bool = False,
        ) -> None:
            if self._shutting_down or self._update_download_in_progress:
                return
            self._update_download_in_progress = True
            self._update_cancel_event.clear()
            job = UpdateDownloadJob(
                self._update_signals,
                check_result,
                install_immediately=install_immediately,
                manual_request=manual_request,
                cancel_event=self._update_cancel_event,
            )
            QThreadPool.globalInstance().start(job)

        def cancel_active_update_download(self) -> None:
            self._update_cancel_event.set()

        def _on_update_download_progress(self, done: int, total: int) -> None:
            if (
                self._active_update_dialog is not None
                and self._active_update_dialog.isVisible()
            ):
                self._active_update_dialog.on_download_progress(done, total)

        def _on_update_download_completed(
            self,
            version: str,
            staged_path: str,
            sha256: str,
            check_result: object,
            install_immediately: bool,
        ) -> None:
            self._update_download_in_progress = False
            self.config.staged_update_version = version
            self.config.staged_update_path = staged_path
            self.config.staged_update_sha256 = sha256
            self.config.save()

            if (
                self._active_update_dialog is not None
                and self._active_update_dialog.isVisible()
            ):
                self._active_update_dialog.accept()

            if install_immediately:
                if self.is_snip_session_active():
                    # Defer actual restart until the active screenshot overlay closes
                    self._pending_immediate_install = (
                        version,
                        Path(staged_path),
                        sha256,
                    )
                    self.tray.showMessage(
                        f"HDRSnip Fusion v{version} Ready",
                        "Update verified and will install as soon as you finish your current screenshot.",
                        QSystemTrayIcon.MessageIcon.Information,
                        5000,
                    )
                else:
                    self._execute_staged_update_and_exit(
                        version,
                        Path(staged_path),
                        sha256,
                        restart_after_update=True,
                    )
            else:
                DIAG_LOG.milestone(
                    "UPDATE_STAGED_READY",
                    f"Verified update v{version} staged at '{staged_path}'; prompting user when idle to restart and install.",
                )
                if isinstance(check_result, UpdateCheckResult):
                    self._pending_update_prompt_result = check_result
                    if not self.is_snip_session_active():
                        self.tray.showMessage(
                            f"HDRSnip Fusion v{version} Downloaded & Verified",
                            "Click here or open Settings to restart and install the verified update.",
                            QSystemTrayIcon.MessageIcon.Information,
                            7500,
                        )

        def _on_update_download_failed(
            self,
            err_msg: str,
            manual_request: bool,
            check_result: object,
        ) -> None:
            self._update_download_in_progress = False
            if (
                self._active_update_dialog is not None
                and self._active_update_dialog.isVisible()
            ):
                self._active_update_dialog.on_download_failed(err_msg)
            elif manual_request:
                rel_url = (
                    getattr(check_result, "release_url", GITHUB_RELEASES_PAGE_URL)
                    or GITHUB_RELEASES_PAGE_URL
                )
                ans = QMessageBox.warning(
                    None,
                    "HDRSnip Fusion — Update Failed",
                    f"Could not download or verify the update automatically:\n{err_msg}\n\n"
                    f"Would you like to open the official GitHub Release page ({rel_url})?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if ans == QMessageBox.StandardButton.Yes and is_valid_github_url(
                    rel_url, require_repo_prefix=True
                ):
                    webbrowser.open(rel_url)

        def _execute_staged_update_and_exit(
            self,
            target_version: str,
            staged_exe: Path,
            expected_sha256: str,
            *,
            restart_after_update: bool = True,
        ) -> bool:
            """
            Prepares the verified update manifest, launches the independent updater helper,
            and triggers a clean application exit so the running EXE can be replaced safely.
            """
            if not is_packaged_exe():
                return False
            if not _UPDATE_TRANSACTION_LOCK.acquire(blocking=False):
                return False
            try:
                helper_exe, manifest_path = prepare_staged_update_transaction(
                    staged_exe=staged_exe,
                    target_version=target_version,
                    expected_sha256=expected_sha256,
                    target_exe=get_current_executable_path(),
                    restart_after_update=restart_after_update,
                    staging_root=LOCAL_UPDATE_ROOT_DIR,
                )
                launch_staged_update_helper(helper_exe, manifest_path)
                # Clear staged config markers now that helper transaction is launched
                self.config.staged_update_version = ""
                self.config.staged_update_path = ""
                self.config.staged_update_sha256 = ""
                self.config.save()
                self.quit_app(skip_auto_update_on_exit=True)
                return True
            except Exception as exc:
                DIAG_LOG.error(
                    "UPDATE_INSTALL",
                    f"Failed to launch staged update v{target_version}",
                    exc,
                )
                if restart_after_update:
                    ans = QMessageBox.warning(
                        None,
                        "HDRSnip Fusion — Automatic Update Failed",
                        f"Could not replace the installed executable automatically:\n{exc}\n\n"
                        "Would you like to open the official GitHub Releases page to download manually?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if ans == QMessageBox.StandardButton.Yes:
                        webbrowser.open(GITHUB_RELEASES_PAGE_URL)
                return False
            finally:
                _UPDATE_TRANSACTION_LOCK.release()

        def _on_tray_activated(
            self, reason: QSystemTrayIcon.ActivationReason
        ) -> None:
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                self.trigger_snip()

        def _update_tray_tooltip(self) -> None:
            sm_tag = " • [SAFE MODE]" if self.config.is_safe_mode_active else ""
            self.tray.setToolTip(
                f"HDRSnip Fusion v{APP_VERSION} ({self.config.hotkey_str}){sm_tag}"
            )

        def open_screenshots_folder(self) -> None:
            save_dir = Path(self.config.save_directory).expanduser()
            try:
                save_dir.mkdir(parents=True, exist_ok=True)
                if sys.platform == "win32":
                    os.startfile(str(save_dir))
            except Exception as exc:
                DIAG_LOG.error("OPEN_FOLDER", f"Could not open folder '{save_dir}'", exc)
                QMessageBox.warning(
                    None,
                    "HDRSnip Fusion — Folder Error",
                    f"Could not open screenshots folder:\n{save_dir}\n\nReason: {exc}",
                )

        def open_diagnostic_log(self) -> None:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            if not DIAGNOSTIC_LOG_FILE.exists():
                DIAG_LOG.milestone(
                    "LOG_VIEW", "Created diagnostic log file on tray menu request"
                )
            if sys.platform == "win32":
                try:
                    os.startfile(
                        str(
                            DIAGNOSTIC_LOG_FILE
                            if DIAGNOSTIC_LOG_FILE.exists()
                            else CONFIG_DIR
                        )
                    )
                except Exception:
                    os.startfile(str(CONFIG_DIR))

        def _on_overlay_closed(self, closed_overlay: object) -> None:
            """Drops the controller reference to the closed overlay and reclaims 4K screenshot memory."""
            if self.overlay is closed_overlay:
                self.overlay = None
            AeroAnimationDirector.instance().notify_visibility_changed()
            gc.collect()

            # If a user-approved immediate update finished downloading while the overlay was open,
            # or a background update notification was deferred during the snip, process it now.
            if self._pending_immediate_install is not None and not self._shutting_down:
                ver, st_path, sha = self._pending_immediate_install
                self._pending_immediate_install = None
                QTimer.singleShot(
                    250,
                    lambda: self._execute_staged_update_and_exit(
                        ver, st_path, sha, restart_after_update=True
                    ),
                )
            elif (
                self._pending_update_prompt_result is not None
                and not self._shutting_down
            ):
                res = self._pending_update_prompt_result
                self.tray.showMessage(
                    f"HDRSnip Fusion v{res.latest_version} is available",
                    "A new stable version is ready. Click here or open Settings to review and install.",
                    QSystemTrayIcon.MessageIcon.Information,
                    7500,
                )

        def trigger_snip(self, t_trigger: Any = None) -> None:
            t_now = time.perf_counter()
            if isinstance(t_trigger, (int, float)):
                t_hotkey_rx = float(t_trigger)
                t_hotkey_to_handler = (t_now - t_hotkey_rx) * 1000.0
            else:
                t_hotkey_rx = t_now
                t_hotkey_to_handler = 0.0
            PERF_TELEMETRY.record_stage("hotkey_to_handler", t_hotkey_to_handler)

            if getattr(self, "_shutting_down", False) or self._snip_in_progress:
                DIAG_LOG.warning(
                    "TRIGGER_SNIP",
                    "Ignored re-entrant trigger_snip() while capture/overlay initialization or shutdown is running.",
                )
                return
            if self.overlay is not None:
                if self.overlay.isVisible():
                    DIAG_LOG.log(
                        "TRIGGER_SNIP",
                        "Ignored trigger_snip() because an overlay is already active and visible.",
                    )
                    return
                self.overlay.cleanup_resources()
                self.overlay = None

            self._snip_in_progress = True
            captured_frame: Optional[CapturedFrame] = None
            try:
                if self.config.overlay_delay_ms > 0:
                    time.sleep(min(2.0, float(self.config.overlay_delay_ms) / 1000.0))
                captured_frame = capture_screen_dxgi_hdr(self.config)

                t_ov_start = time.perf_counter()
                self.overlay = SnipOverlayWindow(
                    captured_frame, self.config, t_trigger_start=t_hotkey_rx
                )
                self.overlay.overlay_closed.connect(self._on_overlay_closed)
                self.overlay.show_on_target_screen()
                t_ov_ms = (time.perf_counter() - t_ov_start) * 1000.0
                PERF_TELEMETRY.record_stage("overlay_init", t_ov_ms)

                total_ms = (time.perf_counter() - t_hotkey_rx) * 1000.0
                PERF_TELEMETRY.record_capture_to_overlay(total_ms)
                scr_name = (
                    self.overlay.target_screen.name()
                    if self.overlay.target_screen is not None
                    else "unknown"
                )
                DIAG_LOG.milestone(
                    "OVERLAY_OPEN",
                    f"Overlay opened on screen '{scr_name}' "
                    f"geom={self.overlay.geometry().getRect()} in {total_ms:.1f} ms "
                    f"(preview={captured_frame.is_preview})",
                )
            except Exception as exc:
                if captured_frame is not None and self.overlay is None:
                    captured_frame.release_buffers()
                print(f"[HDRSnip Fusion] Capture error: {exc}")
                DIAG_LOG.error("TRIGGER_SNIP", "Failed to capture and open overlay", exc)
                self.tray.showMessage(
                    "HDRSnip Fusion Capture Failed",
                    str(exc),
                    QSystemTrayIcon.MessageIcon.Warning,
                    7500,
                )
            finally:
                self._snip_in_progress = False

        def open_settings(self) -> None:
            if getattr(self, "_shutting_down", False):
                return
            DIAG_LOG.log("SETTINGS", "Opening SettingsDialog")
            parent_w = (
                self.overlay
                if (self.overlay is not None and self.overlay.isVisible())
                else None
            )
            dlg = SettingsDialog(self.config, parent=parent_w, controller=self)
            try:
                dlg.raise_()
                dlg.activateWindow()
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    dlg.apply_to_config()
                    self.hotkey_listener.update_hotkey(self.config.hotkey_str)
                    self.snip_action.setText(
                        f"✦ Take HDR Snip ({self.config.hotkey_str})"
                    )
                    self._update_tray_tooltip()
                    if self.overlay is not None and not self.overlay._closed:
                        self.overlay.on_config_updated()
                elif self.overlay is not None and not self.overlay._closed:
                    self.overlay.setFocus()
            finally:
                self._settings_check_callback = None
                dlg.cleanup_resources()
                dlg.deleteLater()
                AeroAnimationDirector.instance().notify_visibility_changed()

        def quit_app(self, *, skip_auto_update_on_exit: bool = False) -> None:
            # Note: Unattended deferred installation on application exit is intentionally
            # disabled so updates are only installed via user-confirmed immediate restart
            # with live independent-helper verification and automatic rollback.
            _ = skip_auto_update_on_exit
            self._shutting_down = True
            self._update_cancel_event.set()
            if hasattr(self, "_update_periodic_timer"):
                self._update_periodic_timer.stop()
            DIAG_LOG.milestone("APP_SHUTDOWN", "Shutting down HDRSnip Fusion cleanly")
            self.hotkey_listener.stop()
            if self.overlay is not None:
                self.overlay.cleanup_resources()
                self.overlay = None
            for ov in list(_LIVE_OVERLAY_INSTANCES):
                if ov is not None and not getattr(ov, "_resources_released", True):
                    ov.cleanup_resources()
            AeroAnimationDirector.instance().stop_all()
            # Wait briefly for any cancelled ToneRenderJob or active capture to finish
            # so background worker threads never emit signals during Python teardown
            try:
                QThreadPool.globalInstance().waitForDone(500)
            except Exception:
                pass
            acquired = _CAPTURE_LOCK.acquire(timeout=0.5)
            if acquired:
                _CAPTURE_LOCK.release()
            self.tray.hide()
            self.app.quit()

        def run(self) -> int:
            return self.app.exec()


def _extract_cli_option_value(args: Sequence[str], flag: str) -> Optional[str]:
    """Extracts `<value>` from `[..., flag, value]` or `[..., f"{flag}={value}"]`."""
    prefix = flag + "="
    for idx, item in enumerate(args):
        if item == flag:
            if idx + 1 < len(args):
                return str(args[idx + 1]).strip()
            return ""
        if item.startswith(prefix):
            return item[len(prefix) :].strip()
    return None


def write_compiled_version_file(target_file: Path) -> None:
    """
    Writes structured version metadata directly to `target_file` for CI and
    `PyInstaller --windowed` verification where `sys.stdout` is unavailable.
    """
    payload = {
        "app": "HDRSnip Fusion",
        "version": APP_VERSION,
        "tag": f"v{APP_VERSION}",
        "packaged": is_packaged_exe(),
        "executable": str(get_current_executable_path()),
    }
    write_atomic_json_file(Path(target_file), payload)


def main(argv: Optional[Sequence[str]] = None) -> int:
    _ensure_safe_stdio()
    args = list(sys.argv[1:] if argv is None else argv)

    # 1. Windowed-safe file-based version verification (`--write-version-file <path>`)
    #    Works reliably in PyInstaller `--onefile --windowed` builds where stdout is None.
    version_file_arg = _extract_cli_option_value(args, "--write-version-file")
    if version_file_arg is not None:
        if not version_file_arg:
            return 2
        try:
            write_compiled_version_file(Path(version_file_arg))
            return 0
        except Exception as exc:
            DIAG_LOG.error("VERSION_CHECK", f"Failed to write version file '{version_file_arg}'", exc)
            return 2

    # 2. Lightweight CLI version query (exits before Qt/hotkey/mutex initialization)
    if "--version" in args or "-V" in args:
        env_ver_file = os.environ.get("HDRSNIP_VERSION_FILE", "").strip()
        if env_ver_file:
            try:
                write_compiled_version_file(Path(env_ver_file))
            except Exception:
                return 2
        print(f"HDRSnip Fusion v{APP_VERSION}")
        return 0

    # 3. Early out-of-process staged updater helper mode (exits before Qt/hotkey/mutex init)
    if len(args) >= 2 and args[0] == "--apply-staged-update":
        return run_staged_update_helper(args[1])

    # 4. Simulated startup failure/hang hooks for automated CI / Windows two-EXE rollback testing
    if "--simulate-broken-startup" in args or os.environ.get(
        "HDRSNIP_SIMULATE_BROKEN_STARTUP", ""
    ).strip().lower() in ("1", "true", "yes"):
        DIAG_LOG.error(
            "SIMULATED_FAILURE",
            "Exiting before startup confirmation due to --simulate-broken-startup",
        )
        return 13

    if "--simulate-hung-startup" in args or os.environ.get(
        "HDRSNIP_SIMULATE_HUNG_STARTUP", ""
    ).strip().lower() in ("1", "true", "yes"):
        DIAG_LOG.error(
            "SIMULATED_HUNG_STARTUP",
            "Sleeping without writing startup confirmation due to --simulate-hung-startup",
        )
        time.sleep(30.0)
        return 14

    if not HAS_QT:
        print(
            "PyQt6 is required to run the HDRSnip Fusion GUI.\n"
            "Install dependencies with:\n"
            "    pip install PyQt6 numpy Pillow"
        )
        return 1

    confirm_startup_arg = _extract_cli_option_value(args, "--confirm-startup-file")
    confirm_startup_path = (
        Path(confirm_startup_arg).resolve()
        if confirm_startup_arg
        else None
    )
    confirm_token_arg = (
        _extract_cli_option_value(args, "--confirm-startup-token")
        or os.environ.get("HDRSNIP_STARTUP_CONFIRM_TOKEN", "")
    ).strip()
    verify_startup_only = ("--verify-startup-only" in args) or (
        os.environ.get("HDRSNIP_VERIFY_STARTUP_ONLY", "").strip().lower()
        in ("1", "true", "yes")
    )

    restarted_after_update = "--restarted-after-update" in args
    mutex = None
    kernel32_err = None
    if sys.platform == "win32":
        _ensure_win32_ctypes_signatures()
        kernel32_err = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32_err.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            ctypes.c_wchar_p,
        ]
        kernel32_err.CreateMutexW.restype = ctypes.c_void_p
        kernel32_err.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32_err.CloseHandle.restype = wintypes.BOOL

        max_mutex_tries = 35 if restarted_after_update else 1
        for attempt in range(max_mutex_tries):
            mutex = kernel32_err.CreateMutexW(
                None, False, r"Local\HDRSnipFusion_SingleInstance"
            )
            if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
                break
            if mutex:
                kernel32_err.CloseHandle(ctypes.c_void_p(mutex))
                mutex = None
            if attempt + 1 < max_mutex_tries:
                time.sleep(0.12)
            else:
                print("HDRSnip Fusion is already running in the system tray.")
                DIAG_LOG.log(
                    "SINGLE_INSTANCE",
                    "Another instance of HDRSnip Fusion is already running; exiting.",
                )
                return 0
    try:
        controller = HDRSnipFusionApplication(
            startup_confirm_file=confirm_startup_path,
            startup_confirm_token=confirm_token_arg,
            verify_startup_only=verify_startup_only,
        )
        return controller.run()
    except Exception as exc:
        DIAG_LOG.error("MAIN_STARTUP_FAILURE", "Fatal error during application startup", exc)
        return 1
    finally:
        if mutex and kernel32_err is not None:
            kernel32_err.CloseHandle(ctypes.c_void_p(mutex))


if __name__ == "__main__":
    sys.exit(main())