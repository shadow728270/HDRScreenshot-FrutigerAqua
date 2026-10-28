"""
Prismwake v0.2.0 — Pinned Screenshot Geometry, Multi-Monitor Recovery & Floating Aqua Window
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

try:
    from PyQt6.QtCore import (
        QPoint,
        QRect,
        QSize,
        Qt,
        QTimer,
        pyqtSignal,
    )
    from PyQt6.QtGui import (
        QAction,
        QColor,
        QCursor,
        QFont,
        QGuiApplication,
        QImage,
        QKeySequence,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
        QShortcut,
    )
    from PyQt6.QtWidgets import (
        QApplication,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QMenu,
        QMessageBox,
        QPushButton,
        QSlider,
        QVBoxLayout,
        QWidget,
    )
    HAS_QT = True
except Exception:
    HAS_QT = False


PIN_ZOOM_PRESETS: Tuple[int, ...] = (25, 50, 75, 100, 150, 200, 300)
PIN_OPACITY_PRESETS: Tuple[int, ...] = (100, 90, 75, 60, 45, 30, 20)
MIN_PIN_OPACITY_PCT: int = 15
MAX_PIN_OPACITY_PCT: int = 100
MIN_PIN_DIMENSION: int = 48
WDA_NONE: int = 0x00000000
WDA_EXCLUDEFROMCAPTURE: int = 0x00000011
GWL_EXSTYLE: int = -20
WS_EX_LAYERED: int = 0x00080000
WS_EX_TRANSPARENT: int = 0x00000020
SWP_NOSIZE: int = 0x0001
SWP_NOMOVE: int = 0x0002
SWP_NOZORDER: int = 0x0004
SWP_NOACTIVATE: int = 0x0010
SWP_FRAMECHANGED: int = 0x0020
HWND_TOPMOST: int = -1


def clamp_pin_opacity_pct(value: Any) -> int:
    try:
        v = int(round(float(value)))
    except Exception:
        v = 100
    return max(MIN_PIN_OPACITY_PCT, min(MAX_PIN_OPACITY_PCT, v))


def clamp_pin_zoom_pct(value: Any) -> int:
    try:
        v = int(round(float(value)))
    except Exception:
        v = 100
    return max(25, min(400, v))


@dataclass(frozen=True)
class VirtualMonitorRect:
    """Represents a physical or logical monitor work area (supports negative coordinates and mixed DPI)."""
    x: int
    y: int
    width: int
    height: int
    dpi_scale: float = 1.0
    is_primary: bool = False
    device_name: str = ""

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains_point(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def intersection_area(self, rx: int, ry: int, rw: int, rh: int) -> int:
        ix0 = max(self.x, rx)
        iy0 = max(self.y, ry)
        ix1 = min(self.right, rx + rw)
        iy1 = min(self.bottom, ry + rh)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0
        return int((ix1 - ix0) * (iy1 - iy0))


def compute_aspect_locked_size(
    source_w: int,
    source_h: int,
    target_w: int,
    target_h: int,
    *,
    anchor_axis: str = "width",
    min_dim: int = MIN_PIN_DIMENSION,
) -> Tuple[int, int]:
    """
    Compute `(new_w, new_h)` preserving `source_w / source_h` aspect ratio
    while respecting `min_dim`.
    """
    sw = max(1, int(source_w))
    sh = max(1, int(source_h))
    aspect = sw / float(sh)

    if anchor_axis == "height":
        nh = max(min_dim, int(round(target_h)))
        nw = max(min_dim, int(round(nh * aspect)))
    else:
        nw = max(min_dim, int(round(target_w)))
        nh = max(min_dim, int(round(nw / aspect)))
    return nw, nh


def compute_fit_zoom_pct(
    source_w: int,
    source_h: int,
    monitor: VirtualMonitorRect,
    margin_ratio: float = 0.82,
) -> int:
    """Compute the zoom percentage (`25..300`) that fits `source_w x source_h` comfortably inside `monitor`."""
    sw = max(1, int(source_w))
    sh = max(1, int(source_h))
    avail_w = max(MIN_PIN_DIMENSION, int(monitor.width * margin_ratio))
    avail_h = max(MIN_PIN_DIMENSION, int(monitor.height * margin_ratio))
    scale = min(avail_w / float(sw), avail_h / float(sh))
    return clamp_pin_zoom_pct(int(round(scale * 100.0)))


def recover_offscreen_pin_rect(
    x: int,
    y: int,
    width: int,
    height: int,
    monitors: Sequence[VirtualMonitorRect],
    *,
    min_visible_px: int = 44,
) -> Tuple[int, int, int, int]:
    """
    Ensure a pinned screenshot window at `(x, y, width, height)` remains accessible
    across arbitrary multi-monitor arrangements (including negative coordinates left/above
    primary and monitor disconnects). If insufficient area is visible on any monitor,
    relocates/clamps the pin onto the nearest available monitor work area.
    """
    w = max(MIN_PIN_DIMENSION, int(width))
    h = max(MIN_PIN_DIMENSION, int(height))
    if not monitors:
        return int(x), int(y), w, h

    # Check if at least a grab-handle strip is visible on any connected monitor
    req_area = min(w * h, min_visible_px * min_visible_px)
    best_mon = monitors[0]
    best_area = -1
    for mon in monitors:
        area = mon.intersection_area(x, y, w, h)
        if area > best_area:
            best_area = area
            best_mon = mon

    if best_area >= req_area:
        if y < best_mon.y:
            y = best_mon.y
        return int(x), int(y), w, h

    cx = x + w // 2
    cy = y + h // 2
    target_mon = monitors[0]
    best_dist = float("inf")
    for mon in monitors:
        mcx = mon.x + mon.width // 2
        mcy = mon.y + mon.height // 2
        dist = (cx - mcx) ** 2 + (cy - mcy) ** 2
        if dist < best_dist:
            best_dist = dist
            target_mon = mon

    if w > target_mon.width - 16 or h > target_mon.height - 16:
        fit_pct = compute_fit_zoom_pct(w, h, target_mon, margin_ratio=0.90)
        w = max(MIN_PIN_DIMENSION, int(round(w * (fit_pct / 100.0))))
        h = max(MIN_PIN_DIMENSION, int(round(h * (fit_pct / 100.0))))

    nx = max(target_mon.x + 8, min(target_mon.right - w - 8, x))
    ny = max(target_mon.y + 8, min(target_mon.bottom - h - 8, y))
    return int(nx), int(ny), int(w), int(h)


def apply_win32_window_capture_exclusion(hwnd: int, exclude: bool = True) -> bool:
    """
    Attempt to set `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)` on Windows 10 2004+ / 11.
    Returns True only when the Win32 API call genuinely succeeds.
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        affinity = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
        res = user32.SetWindowDisplayAffinity(wintypes.HWND(int(hwnd)), wintypes.DWORD(affinity))
        return bool(res != 0)
    except Exception:
        return False


def apply_win32_window_click_through(hwnd: int, click_through: bool = True) -> bool:
    """Enable/disable native Win32 mouse pass-through, with a frame-style refresh.

    Relying on Qt.WindowTransparentForInput *and* WS_EX_TRANSPARENT made the pin
    difficult to recover: on Windows, recreating a Qt HWND can preserve stale
    input-transparent state. Use just the Win32 input style for the pin instead.
    The unlock control has its own HWND and must ALWAYS have transparency off.
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd_arg = wintypes.HWND(int(hwnd))
        get_style = user32.GetWindowLongPtrW if hasattr(user32, "GetWindowLongPtrW") else user32.GetWindowLongW
        set_style = user32.SetWindowLongPtrW if hasattr(user32, "SetWindowLongPtrW") else user32.SetWindowLongW
        # GetWindowLongPtrW returns LONG_PTR: without the correct ctypes restype a
        # 64-bit extended style may get truncated/sign-extended unexpectedly.
        if hasattr(user32, "GetWindowLongPtrW"):
            get_style.argtypes = (wintypes.HWND, ctypes.c_int)
            get_style.restype = ctypes.c_ssize_t
            set_style.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
            set_style.restype = ctypes.c_ssize_t
        else:
            get_style.argtypes = (wintypes.HWND, ctypes.c_int)
            get_style.restype = ctypes.c_long
            set_style.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
            set_style.restype = ctypes.c_long
        current = int(get_style(hwnd_arg, GWL_EXSTYLE))
        desired = (current | WS_EX_LAYERED | WS_EX_TRANSPARENT) if click_through else (current & ~WS_EX_TRANSPARENT)
        if desired != current:
            ctypes.set_last_error(0)
            prior = set_style(hwnd_arg, GWL_EXSTYLE, desired)
            if prior == 0 and ctypes.get_last_error() != 0:
                return False
        # Windows caches portions of the style until SWP_FRAMECHANGED.
        # Leaving it out can make unlocking a pin appear to do nothing.
        user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
        user32.SetWindowPos.restype = wintypes.BOOL
        ok = bool(user32.SetWindowPos(
            hwnd_arg, wintypes.HWND(0), 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        ))
        final_style = int(get_style(hwnd_arg, GWL_EXSTYLE))
        return ok and bool(final_style & WS_EX_TRANSPARENT) == bool(click_through)
    except Exception:
        return False


def make_win32_pin_unlock_control_interactive(hwnd: int) -> bool:
    """Ensure the unlock pill is above the pinned image and accepts input."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        if not apply_win32_window_click_through(hwnd, False):
            return False
        user32 = ctypes.windll.user32
        return bool(user32.SetWindowPos(
            wintypes.HWND(int(hwnd)), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        ))
    except Exception:
        return False


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


@dataclass
class PinnedScreenshotState:
    """
    Stateful model for a single pinned screenshot window.
    Can be manipulated directly in headless unit tests or bound to a live `PinnedScreenshotWindow`.
    """
    pin_id: str
    pil_image: Image.Image
    title: str = "Pinned Screenshot"
    x: int = 100
    y: int = 100
    width: int = 320
    height: int = 200
    zoom_pct: int = 100
    opacity_pct: int = 100
    always_on_top: bool = True
    click_through: bool = False
    locked: bool = False
    show_border: bool = True
    exclude_from_capture: bool = True
    source_key: str = ""
    is_closed: bool = False
    hidden_for_capture: bool = False

    @property
    def source_width(self) -> int:
        return max(1, int(self.pil_image.width))

    @property
    def source_height(self) -> int:
        return max(1, int(self.pil_image.height))

    def set_zoom(self, zoom_pct: int) -> None:
        self.zoom_pct = clamp_pin_zoom_pct(zoom_pct)
        scale = self.zoom_pct / 100.0
        self.width = max(MIN_PIN_DIMENSION, int(round(self.source_width * scale)))
        self.height = max(MIN_PIN_DIMENSION, int(round(self.source_height * scale)))

    def reset_size(self) -> int:
        self.set_zoom(100)
        return self.zoom_pct

    def zoom_step(self, direction: int) -> int:
        cur = self.zoom_pct
        if direction > 0:
            for p in PIN_ZOOM_PRESETS:
                if p > cur:
                    self.set_zoom(p)
                    return self.zoom_pct
            self.set_zoom(min(300, cur + 25))
        elif direction < 0:
            for p in reversed(PIN_ZOOM_PRESETS):
                if p < cur:
                    self.set_zoom(p)
                    return self.zoom_pct
            self.set_zoom(max(25, cur - 25))
        return self.zoom_pct

    def fit_to_monitor(self, monitor: VirtualMonitorRect) -> int:
        pct = compute_fit_zoom_pct(self.source_width, self.source_height, monitor)
        self.set_zoom(pct)
        return self.zoom_pct

    def set_opacity(self, opacity_pct: int) -> int:
        self.opacity_pct = clamp_pin_opacity_pct(opacity_pct)
        return self.opacity_pct

    def step_opacity(self, direction: int, step: int = 10) -> int:
        delta = int(step) if direction > 0 else -int(step)
        self.set_opacity(self.opacity_pct + delta)
        return self.opacity_pct

    def set_click_through(self, enabled: bool) -> bool:
        self.click_through = bool(enabled)
        return self.click_through

    def toggle_click_through(self) -> bool:
        self.click_through = not self.click_through
        return self.click_through

    def move_to(self, new_x: int, new_y: int) -> bool:
        if self.locked or self.click_through:
            return False
        self.x = int(new_x)
        self.y = int(new_y)
        return True

    def resize_to(
        self,
        target_w: int,
        target_h: int,
        *,
        preserve_aspect: bool = True,
        anchor_axis: str = "width",
    ) -> bool:
        if self.locked or self.click_through:
            return False
        if preserve_aspect:
            nw, nh = compute_aspect_locked_size(
                self.source_width,
                self.source_height,
                target_w,
                target_h,
                anchor_axis=anchor_axis,
            )
        else:
            nw = max(MIN_PIN_DIMENSION, int(target_w))
            nh = max(MIN_PIN_DIMENSION, int(target_h))
        self.width = nw
        self.height = nh
        self.zoom_pct = clamp_pin_zoom_pct(int(round((nw / float(self.source_width)) * 100.0)))
        return True

    def ensure_on_screen(self, monitors: Sequence[VirtualMonitorRect]) -> None:
        self.x, self.y, self.width, self.height = recover_offscreen_pin_rect(
            self.x, self.y, self.width, self.height, monitors
        )

    def save_to_file(self, dest_path: Path) -> Path:
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_str = tempfile.mkstemp(prefix=".pin_save_", suffix=".png", dir=str(dest.parent))
        os.close(fd)
        tmp = Path(tmp_str)
        try:
            self.pil_image.save(str(tmp), format="PNG")
            os.replace(str(tmp), str(dest))
            return dest
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise


class PinnedScreenshotManager:
    """
    Manages all active pinned screenshots in the current Prismwake session.
    Coordinates creation, duplicate pinning, re-pinning focus from History,
    click-through management, monitor disconnection recovery, Escape-key focused closure,
    and pre/post-capture visibility so existing pins never pollute new desktop captures.
    """

    def __init__(
        self,
        *,
        default_opacity_pct: int = 100,
        default_zoom_pct: int = 100,
        default_always_on_top: bool = True,
        default_show_border: bool = True,
        exclude_pins_from_capture: bool = True,
        reopen_in_editor_callback: Optional[Callable[[Image.Image, str], None]] = None,
    ) -> None:
        self.default_opacity_pct = clamp_pin_opacity_pct(default_opacity_pct)
        self.default_zoom_pct = clamp_pin_zoom_pct(default_zoom_pct)
        self.default_always_on_top = bool(default_always_on_top)
        self.default_show_border = bool(default_show_border)
        self.exclude_pins_from_capture = bool(exclude_pins_from_capture)
        self.reopen_in_editor_callback = reopen_in_editor_callback

        self._states: Dict[str, PinnedScreenshotState] = {}
        self._windows: Dict[str, Any] = {}

    @property
    def active_states(self) -> List[PinnedScreenshotState]:
        return [s for s in self._states.values() if not s.is_closed]

    @property
    def active_count(self) -> int:
        return len(self.active_states)

    def get_window(self, pin_id: str) -> Optional[Any]:
        return self._windows.get(pin_id)

    def find_pin_by_source_key(self, source_key: str) -> Optional[PinnedScreenshotState]:
        key = str(source_key or "").strip()
        if not key:
            return None
        for state in self.active_states:
            if state.source_key == key:
                return state
        return None

    def focus_pin(self, pin_id: str, *, unlock_click_through: bool = False) -> bool:
        state = self._states.get(pin_id)
        if state is None or state.is_closed:
            return False
        if unlock_click_through and state.click_through:
            state.set_click_through(False)
        monitors = self._query_qt_monitors()
        if monitors:
            state.ensure_on_screen(monitors)
        win = self._windows.get(pin_id)
        if win is not None:
            try:
                win.sync_from_state()
                win.show()
                win.raise_()
                win.activateWindow()
                if hasattr(win, "flash_highlight"):
                    win.flash_highlight()
            except Exception:
                pass
        return True

    def pin_or_focus(
        self,
        image_source: Any,
        *,
        source_key: str = "",
        title: str = "Pinned Screenshot",
        initial_x: Optional[int] = None,
        initial_y: Optional[int] = None,
        zoom_pct: Optional[int] = None,
        opacity_pct: Optional[int] = None,
        always_on_top: Optional[bool] = None,
        click_through: bool = False,
        show_border: Optional[bool] = None,
        monitors: Optional[Sequence[VirtualMonitorRect]] = None,
        spawn_qt_window: bool = True,
    ) -> Tuple[PinnedScreenshotState, bool]:
        """
        If an active pinned screenshot with `source_key` already exists, bring it to the front
        (and unlock click-through so the user can interact with it) and return `(existing_state, False)`.
        Otherwise create a new pinned screenshot and return `(new_state, True)`.
        """
        existing = self.find_pin_by_source_key(source_key) if source_key else None
        if existing is not None:
            self.focus_pin(existing.pin_id, unlock_click_through=True)
            return existing, False
        created = self.create_pin(
            image_source,
            title=title,
            initial_x=initial_x,
            initial_y=initial_y,
            zoom_pct=zoom_pct,
            opacity_pct=opacity_pct,
            always_on_top=always_on_top,
            click_through=click_through,
            show_border=show_border,
            source_key=source_key,
            monitors=monitors,
            spawn_qt_window=spawn_qt_window,
        )
        return created, True

    def create_pin(
        self,
        image_source: Any,
        *,
        title: str = "Pinned Screenshot",
        initial_x: Optional[int] = None,
        initial_y: Optional[int] = None,
        zoom_pct: Optional[int] = None,
        opacity_pct: Optional[int] = None,
        always_on_top: Optional[bool] = None,
        click_through: bool = False,
        show_border: Optional[bool] = None,
        source_key: str = "",
        monitors: Optional[Sequence[VirtualMonitorRect]] = None,
        spawn_qt_window: bool = True,
    ) -> PinnedScreenshotState:
        pil_rgb = _to_pil_rgb(image_source)
        pin_id = f"pin_{secrets.token_hex(5)}"
        z_pct = clamp_pin_zoom_pct(zoom_pct if zoom_pct is not None else self.default_zoom_pct)
        op_pct = clamp_pin_opacity_pct(opacity_pct if opacity_pct is not None else self.default_opacity_pct)
        aot = self.default_always_on_top if always_on_top is None else bool(always_on_top)
        bdr = self.default_show_border if show_border is None else bool(show_border)

        cascade_offset = (len(self.active_states) % 8) * 26
        px = int(initial_x) if initial_x is not None else (120 + cascade_offset)
        py = int(initial_y) if initial_y is not None else (120 + cascade_offset)

        state = PinnedScreenshotState(
            pin_id=pin_id,
            pil_image=pil_rgb,
            title=title or "Pinned Screenshot",
            x=px,
            y=py,
            width=max(MIN_PIN_DIMENSION, int(round(pil_rgb.width * (z_pct / 100.0)))),
            height=max(MIN_PIN_DIMENSION, int(round(pil_rgb.height * (z_pct / 100.0)))),
            zoom_pct=z_pct,
            opacity_pct=op_pct,
            always_on_top=aot,
            click_through=bool(click_through),
            show_border=bdr,
            exclude_from_capture=self.exclude_pins_from_capture,
            source_key=str(source_key or "").strip(),
        )

        resolved_monitors = list(monitors) if monitors is not None else self._query_qt_monitors()
        if resolved_monitors:
            state.ensure_on_screen(resolved_monitors)

        self._states[pin_id] = state

        if HAS_QT and spawn_qt_window and QApplication.instance() is not None:
            win = PinnedScreenshotWindow(state, manager=self)
            self._windows[pin_id] = win
            win.show()
            win.raise_()

        return state

    def duplicate_pin(
        self,
        pin_id: str,
        *,
        monitors: Optional[Sequence[VirtualMonitorRect]] = None,
        spawn_qt_window: bool = True,
    ) -> Optional[PinnedScreenshotState]:
        src = self._states.get(pin_id)
        if src is None or src.is_closed:
            return None
        return self.create_pin(
            src.pil_image.copy(),
            title=f"{src.title} (Copy)",
            initial_x=src.x + 28,
            initial_y=src.y + 28,
            zoom_pct=src.zoom_pct,
            opacity_pct=src.opacity_pct,
            always_on_top=src.always_on_top,
            click_through=False,
            show_border=src.show_border,
            source_key="",
            monitors=monitors,
            spawn_qt_window=spawn_qt_window,
        )

    def set_all_click_through(self, enabled: bool = False) -> int:
        count = 0
        for state in self.active_states:
            if state.click_through != bool(enabled):
                state.set_click_through(enabled)
                count += 1
            win = self._windows.get(state.pin_id)
            if win is not None:
                try:
                    win.sync_from_state()
                except Exception:
                    pass
        return count

    def close_pin(self, pin_id: str) -> bool:
        state = self._states.get(pin_id)
        if state is None or state.is_closed:
            return False
        state.is_closed = True
        win = self._windows.pop(pin_id, None)
        if win is not None:
            try:
                if hasattr(win, "unlock_pill") and win.unlock_pill is not None:
                    win.unlock_pill.close()
                    win.unlock_pill.deleteLater()
                win.close()
                win.deleteLater()
            except Exception:
                pass
        return True

    def close_all_pins(self) -> int:
        ids = [s.pin_id for s in self.active_states]
        count = 0
        for pid in ids:
            if self.close_pin(pid):
                count += 1
        return count

    def recover_all_offscreen_pins(self, monitors: Optional[Sequence[VirtualMonitorRect]] = None) -> None:
        resolved = list(monitors) if monitors is not None else self._query_qt_monitors()
        if not resolved:
            return
        for state in self.active_states:
            state.ensure_on_screen(resolved)
            win = self._windows.get(state.pin_id)
            if win is not None:
                try:
                    win.sync_from_state()
                except Exception:
                    pass

    def prepare_for_desktop_capture(self) -> List[str]:
        """
        Temporarily hide active pinned windows before taking a new desktop screenshot
        when `exclude_pins_from_capture` is enabled, guaranteeing pins do not pollute
        DXGI Desktop Duplication captures even on drivers that ignore `WDA_EXCLUDEFROMCAPTURE`.
        """
        hidden_ids: List[str] = []
        if not self.exclude_pins_from_capture:
            return hidden_ids
        for state in self.active_states:
            state.hidden_for_capture = True
            hidden_ids.append(state.pin_id)
            win = self._windows.get(state.pin_id)
            if win is not None:
                try:
                    if hasattr(win, "unlock_pill") and win.unlock_pill is not None:
                        win.unlock_pill.setVisible(False)
                    win.setVisible(False)
                except Exception:
                    pass
        if HAS_QT and QApplication.instance() is not None:
            QApplication.processEvents()
        return hidden_ids

    def restore_after_desktop_capture(self, hidden_ids: Optional[Sequence[str]] = None) -> None:
        target_ids = set(hidden_ids) if hidden_ids is not None else set(self._states.keys())
        for state in self.active_states:
            if state.pin_id in target_ids and state.hidden_for_capture:
                state.hidden_for_capture = False
                win = self._windows.get(state.pin_id)
                if win is not None:
                    try:
                        win.setVisible(True)
                        win.sync_from_state()
                    except Exception:
                        pass

    @staticmethod
    def _query_qt_monitors() -> List[VirtualMonitorRect]:
        if not HAS_QT or QGuiApplication.instance() is None:
            return []
        out: List[VirtualMonitorRect] = []
        primary = QGuiApplication.primaryScreen()
        for scr in QGuiApplication.screens():
            avail = scr.availableGeometry()
            out.append(
                VirtualMonitorRect(
                    x=avail.x(),
                    y=avail.y(),
                    width=avail.width(),
                    height=avail.height(),
                    dpi_scale=float(scr.devicePixelRatio() or 1.0),
                    is_primary=(scr == primary),
                    device_name=scr.name() or "",
                )
            )
        return out


if HAS_QT:
    class PinClickThroughControlPill(QWidget):
        """
        Tiny floating Frutiger Aqua control pill anchored at the top-right corner of a
        pinned screenshot while Click-Through mode is active.
        Because the pinned image window itself ignores mouse events in Click-Through mode,
        this compact corner pill stays interactive so the user can always disable
        Click-Through or close the pin with a single click.
        """

        def __init__(self, pin_window: "PinnedScreenshotWindow") -> None:
            super().__init__(None)
            self.pin_window = pin_window
            self.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            # An opaque top-level HWND is much more reliable for mouse hit tests
            # than a layered, translucent tool window over a click-through pin.
            self.setObjectName("PinClickThroughControlPill")
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.setStyleSheet(
                """
                QWidget#PinClickThroughControlPill {
                    background: #102b45;
                    border: 1px solid rgba(120, 238, 255, 210);
                    border-radius: 8px;
                }
                QPushButton {
                    background: rgba(24, 128, 196, 220);
                    color: #f4fcff;
                    border: 1px solid rgba(155, 242, 255, 175);
                    border-radius: 5px;
                    padding: 2px 7px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: rgba(58, 174, 240, 245);
                }
                """
            )
            lay = QHBoxLayout(self)
            lay.setContentsMargins(5, 3, 5, 3)
            lay.setSpacing(4)

            self.unlock_btn = QPushButton("👻 Click-Thru ON (Click to Control)")
            self.unlock_btn.setToolTip("Disable Click-Through and restore interactive pin controls")
            self.unlock_btn.clicked.connect(lambda: self.pin_window.set_click_through(False))
            lay.addWidget(self.unlock_btn)

            self.close_btn = QPushButton("✕")
            self.close_btn.setToolTip("Close / Unpin Screenshot")
            self.close_btn.setStyleSheet(
                "background: rgba(195, 42, 62, 225); color: white; border: 1px solid rgba(255, 175, 185, 190);"
            )
            self.close_btn.clicked.connect(self.pin_window.close_this_pin)
            lay.addWidget(self.close_btn)

            self.adjustSize()

        def ensure_interactive(self) -> None:
            """Restore native mouse hit testing on this INDEPENDENT top-level window."""
            if not self.isVisible() or self.pin_window.state.is_closed:
                return
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.unlock_btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.close_btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.raise_()
            if sys.platform == "win32" and QGuiApplication.platformName().lower().startswith("windows"):
                make_win32_pin_unlock_control_interactive(int(self.winId()))

        def sync_position(self) -> None:
            self.adjustSize()
            pw = self.width()
            ph = self.height()
            gx = self.pin_window.state.x + max(0, self.pin_window.state.width - pw - 6)
            gy = max(4, self.pin_window.state.y - ph - 4)
            if gy < 8:
                gy = self.pin_window.state.y + 6
            self.setGeometry(gx, gy, pw, ph)
            if self.pin_window.state.exclude_from_capture:
                try:
                    apply_win32_window_capture_exclusion(int(self.winId()), True)
                except Exception:
                    pass

    class PinnedScreenshotWindow(QWidget):
        """
        Independent Frutiger Aqua floating screenshot window:
          - Thin cyan/sapphire outline, subtle shadow, rounded corners, no permanent bulky title bar.
          - Subtle translucent Aqua control bar appears on hover with live Opacity slider (`15%–100%`),
            Click-Through toggle, Always-on-Top toggle, `1:1` Reset Size, Zoom `−/+`, Copy, Save, Lock, and Close.
          - Supports dragging, 8-edge/corner resizing (preserving aspect ratio by default),
            Ctrl+Wheel zoom, Alt+Wheel opacity, Escape to close when focused, and full right-click context menu.
          - When Click-Through is active, ignores mouse input on the screenshot while providing
            a compact corner `PinClickThroughControlPill` and `Alt+Shift` hover auto-unlock.
        """

        EDGE_NONE = 0
        EDGE_LEFT = 1
        EDGE_RIGHT = 2
        EDGE_TOP = 4
        EDGE_BOTTOM = 8

        def __init__(
            self,
            state: PinnedScreenshotState,
            *,
            manager: Optional[PinnedScreenshotManager] = None,
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)
            self.state = state
            self.manager = manager
            self._qpixmap = self._pil_to_qpixmap(state.pil_image)

            self._hovered: bool = False
            self._flash_active: bool = False
            self._dragging: bool = False
            self._resizing_edges: int = self.EDGE_NONE
            self._drag_start_global = QPoint()
            self._start_geom = QRect()
            self._applied_click_through_flag: Optional[bool] = None
            self._applied_aot_flag: Optional[bool] = None

            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setMouseTracking(True)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

            self.unlock_pill = PinClickThroughControlPill(self)
            self.unlock_pill.hide()

            self._modifier_unlock_timer = QTimer(self)
            self._modifier_unlock_timer.setInterval(120)
            self._modifier_unlock_timer.timeout.connect(self._poll_click_through_modifier)

            self._build_hover_toolbar()
            self._apply_window_flags(force=True)
            self.sync_from_state()

            esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
            esc.setContext(Qt.ShortcutContext.WindowShortcut)
            esc.activated.connect(self.close_this_pin)

            copy_sc = QShortcut(QKeySequence.StandardKey.Copy, self)
            copy_sc.setContext(Qt.ShortcutContext.WindowShortcut)
            copy_sc.activated.connect(self.copy_to_clipboard)

            save_sc = QShortcut(QKeySequence.StandardKey.Save, self)
            save_sc.setContext(Qt.ShortcutContext.WindowShortcut)
            save_sc.activated.connect(self.save_as_dialog)

        @staticmethod
        def _pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
            rgba = pil_img.convert("RGBA")
            data = rgba.tobytes("raw", "RGBA")
            qimg = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
            return QPixmap.fromImage(qimg)

        def _apply_window_flags(self, *, force: bool = False) -> None:
            want_ct = bool(self.state.click_through)
            want_aot = bool(self.state.always_on_top)
            # Qt's offscreen smoke-test plugin does not create real Win32 HWNDs.
            native_win32 = sys.platform == "win32" and QGuiApplication.platformName().lower().startswith("windows")
            # On Windows, click-through is a native style flip, NOT a Qt flag
            # transition. Avoid destroying/recreating the HWND on each toggle.
            flags_changed = (
                force or self._applied_aot_flag != want_aot
                or (not native_win32 and self._applied_click_through_flag != want_ct)
            )
            was_vis = self.isVisible()
            self._applied_click_through_flag = want_ct
            self._applied_aot_flag = want_aot

            flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            if want_aot:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            # Qt's WindowTransparentForInput can remain in effect across native
            # style changes on Windows. Use the reversible Win32 flag there.
            if want_ct and not native_win32:
                flags |= Qt.WindowType.WindowTransparentForInput
            if flags_changed:
                self.setWindowFlags(flags)
            self.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                want_ct if not native_win32 else False,
            )

            if was_vis and flags_changed:
                self.show()

            try:
                hwnd = int(self.winId())
                if hwnd and native_win32:
                    if not apply_win32_window_click_through(hwnd, want_ct):
                        # Never leave a pin in click-through mode if Windows has
                        # not confirmed the native style transition.
                        if want_ct:
                            self.state.set_click_through(False)
                            self._applied_click_through_flag = False
                            apply_win32_window_click_through(hwnd, False)
                    if self.state.exclude_from_capture:
                        apply_win32_window_capture_exclusion(hwnd, True)
            except Exception:
                if want_ct and native_win32:
                    self.state.set_click_through(False)
                    self._applied_click_through_flag = False

        def _build_hover_toolbar(self) -> None:
            self.toolbar = QWidget(self)
            self.toolbar.setStyleSheet(
                """
                QWidget {
                    background: rgba(8, 32, 58, 226);
                    border: 1px solid rgba(125, 232, 255, 195);
                    border-radius: 9px;
                }
                QPushButton {
                    background: rgba(24, 118, 184, 205);
                    color: #f2fbff;
                    border: 1px solid rgba(150, 238, 255, 165);
                    border-radius: 5px;
                    padding: 2px 6px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: rgba(54, 168, 235, 240);
                }
                QPushButton:checked {
                    background: rgba(0, 195, 165, 230);
                    color: #021b2b;
                    border: 1px solid rgba(190, 255, 245, 230);
                }
                QLabel {
                    color: #dff6ff;
                    border: none;
                    background: transparent;
                    font-size: 11px;
                    font-weight: 600;
                }
                QSlider {
                    background: transparent;
                    border: none;
                }
                QSlider::groove:horizontal {
                    height: 5px;
                    background: rgba(15, 65, 110, 210);
                    border-radius: 2px;
                }
                QSlider::sub-page:horizontal {
                    background: rgba(95, 235, 255, 230);
                    border-radius: 2px;
                }
                QSlider::handle:horizontal {
                    width: 11px;
                    height: 11px;
                    margin: -3px 0;
                    background: #ffffff;
                    border: 1px solid #00d4ff;
                    border-radius: 5px;
                }
                """
            )
            tb_layout = QHBoxLayout(self.toolbar)
            tb_layout.setContentsMargins(6, 3, 6, 3)
            tb_layout.setSpacing(4)

            self.zoom_lbl = QLabel("100%")
            self.zoom_lbl.setToolTip("Current Pin Zoom")
            tb_layout.addWidget(self.zoom_lbl)

            btn_z_out = QPushButton("−")
            btn_z_out.setToolTip("Zoom Out (Ctrl+Wheel Down)")
            btn_z_out.clicked.connect(lambda: self.step_zoom(-1))
            tb_layout.addWidget(btn_z_out)

            btn_z_in = QPushButton("+")
            btn_z_in.setToolTip("Zoom In (Ctrl+Wheel Up)")
            btn_z_in.clicked.connect(lambda: self.step_zoom(1))
            tb_layout.addWidget(btn_z_in)

            self.btn_reset_size = QPushButton("1:1")
            self.btn_reset_size.setToolTip("Reset Size to 100% Original Dimensions")
            self.btn_reset_size.clicked.connect(self.reset_size_to_100)
            tb_layout.addWidget(self.btn_reset_size)

            # Live Opacity Slider + Percentage Badge
            op_icon = QLabel("◐")
            op_icon.setToolTip("Pin Opacity (15%–100% • Alt+Wheel)")
            tb_layout.addWidget(op_icon)

            self.opacity_slider = QSlider(Qt.Orientation.Horizontal, self.toolbar)
            self.opacity_slider.setRange(MIN_PIN_OPACITY_PCT, MAX_PIN_OPACITY_PCT)
            self.opacity_slider.setValue(self.state.opacity_pct)
            self.opacity_slider.setFixedWidth(64)
            self.opacity_slider.setToolTip("Adjust Pinned Screenshot Opacity Live (15%–100%)")
            self.opacity_slider.valueChanged.connect(self.set_opacity_preset)
            tb_layout.addWidget(self.opacity_slider)

            self.opacity_lbl = QLabel(f"{self.state.opacity_pct}%")
            self.opacity_lbl.setFixedWidth(32)
            tb_layout.addWidget(self.opacity_lbl)

            # Click-through toggle button
            self.btn_click_through = QPushButton("Click-Thru")
            self.btn_click_through.setCheckable(True)
            self.btn_click_through.setChecked(self.state.click_through)
            self.btn_click_through.setToolTip(
                "Toggle Click-Through (make pinned image ignore mouse input; use top-right pill or Alt+Shift to unlock)"
            )
            self.btn_click_through.clicked.connect(lambda checked: self.set_click_through(checked))
            tb_layout.addWidget(self.btn_click_through)

            # Always-on-top toggle button
            self.btn_aot = QPushButton("📌 Top")
            self.btn_aot.setCheckable(True)
            self.btn_aot.setChecked(self.state.always_on_top)
            self.btn_aot.setToolTip("Toggle Always on Top")
            self.btn_aot.clicked.connect(self.toggle_always_on_top)
            tb_layout.addWidget(self.btn_aot)

            btn_copy = QPushButton("Copy")
            btn_copy.setToolTip("Copy Pinned Image (Ctrl+C)")
            btn_copy.clicked.connect(self.copy_to_clipboard)
            tb_layout.addWidget(btn_copy)

            btn_save = QPushButton("Save")
            btn_save.setToolTip("Save Pinned Image As (Ctrl+S)")
            btn_save.clicked.connect(self.save_as_dialog)
            tb_layout.addWidget(btn_save)

            self.btn_lock = QPushButton("Lock")
            self.btn_lock.setCheckable(True)
            self.btn_lock.setToolTip("Lock / Unlock Position & Size")
            self.btn_lock.clicked.connect(self.toggle_lock)
            tb_layout.addWidget(self.btn_lock)

            btn_close = QPushButton("✕")
            btn_close.setToolTip("Close / Unpin (Esc)")
            btn_close.setStyleSheet(
                "background: rgba(195, 42, 62, 220); color: white; border: 1px solid rgba(255, 175, 185, 190);"
            )
            btn_close.clicked.connect(self.close_this_pin)
            tb_layout.addWidget(btn_close)

            self.toolbar.adjustSize()
            self.toolbar.setVisible(False)

        def sync_from_state(self) -> None:
            self._apply_window_flags()
            self.setGeometry(self.state.x, self.state.y, self.state.width, self.state.height)
            self.setWindowOpacity(self.state.opacity_pct / 100.0)
            self.zoom_lbl.setText(f"{self.state.zoom_pct}%")
            if self.opacity_slider.value() != self.state.opacity_pct:
                self.opacity_slider.blockSignals(True)
                self.opacity_slider.setValue(self.state.opacity_pct)
                self.opacity_slider.blockSignals(False)
            self.opacity_lbl.setText(f"{self.state.opacity_pct}%")
            self.btn_click_through.blockSignals(True)
            self.btn_click_through.setChecked(self.state.click_through)
            self.btn_click_through.blockSignals(False)
            self.btn_aot.blockSignals(True)
            self.btn_aot.setChecked(self.state.always_on_top)
            self.btn_aot.blockSignals(False)
            self.btn_lock.blockSignals(True)
            self.btn_lock.setChecked(self.state.locked)
            self.btn_lock.setText("Unlock" if self.state.locked else "Lock")
            self.btn_lock.blockSignals(False)

            if self.state.click_through and not self.state.is_closed and not self.state.hidden_for_capture:
                self.toolbar.setVisible(False)
                self.unlock_pill.sync_position()
                if self.isVisible():
                    self.unlock_pill.show()
                    self.unlock_pill.ensure_interactive()
                    # Qt can recreate a native Tool HWND during show. Reassert
                    # native input style once its event loop is idle as well.
                    QTimer.singleShot(0, self.unlock_pill.ensure_interactive)
                if not self._modifier_unlock_timer.isActive():
                    self._modifier_unlock_timer.start()
            else:
                self.unlock_pill.hide()
                if self._modifier_unlock_timer.isActive():
                    self._modifier_unlock_timer.stop()

            self._reposition_toolbar()
            self.update()

        def _poll_click_through_modifier(self) -> None:
            """Allow holding Alt+Shift while hovering a click-through pin to immediately unlock controls."""
            if not self.state.click_through or self.state.is_closed:
                self._modifier_unlock_timer.stop()
                return
            try:
                if sys.platform == "win32":
                    user32 = ctypes.windll.user32
                    both_down = bool(user32.GetAsyncKeyState(0x12) & 0x8000) and bool(user32.GetAsyncKeyState(0x10) & 0x8000)
                else:
                    mods = QGuiApplication.queryKeyboardModifiers()
                    both_down = bool(mods & Qt.KeyboardModifier.AltModifier) and bool(mods & Qt.KeyboardModifier.ShiftModifier)
                if both_down and self.geometry().contains(QCursor.pos()):
                    self.set_click_through(False)
            except Exception:
                pass

        def flash_highlight(self) -> None:
            self._flash_active = True
            self.update()
            QTimer.singleShot(650, self._clear_flash_highlight)

        def _clear_flash_highlight(self) -> None:
            self._flash_active = False
            self.update()

        def _reposition_toolbar(self) -> None:
            self.toolbar.adjustSize()
            tw = min(max(60, self.width() - 8), self.toolbar.sizeHint().width())
            th = self.toolbar.sizeHint().height()
            tx = max(4, (self.width() - tw) // 2)
            ty = 6
            self.toolbar.setGeometry(tx, ty, tw, th)

        def enterEvent(self, event: Any) -> None:
            if not self.state.click_through:
                self._hovered = True
                self._reposition_toolbar()
                self.toolbar.setVisible(True)
                self.update()
            super().enterEvent(event)

        def leaveEvent(self, event: Any) -> None:
            self._hovered = False
            self.toolbar.setVisible(False)
            self.update()
            super().leaveEvent(event)

        def resizeEvent(self, event: Any) -> None:
            self._reposition_toolbar()
            if self.state.click_through:
                self.unlock_pill.sync_position()
            super().resizeEvent(event)

        def moveEvent(self, event: Any) -> None:
            if self.state.click_through:
                self.unlock_pill.sync_position()
            super().moveEvent(event)

        def _hit_test_edges(self, pos: QPoint, margin: int = 8) -> int:
            if self.state.locked or self.state.click_through:
                return self.EDGE_NONE
            edges = self.EDGE_NONE
            if pos.x() <= margin:
                edges |= self.EDGE_LEFT
            elif pos.x() >= self.width() - margin:
                edges |= self.EDGE_RIGHT
            if pos.y() <= margin:
                edges |= self.EDGE_TOP
            elif pos.y() >= self.height() - margin:
                edges |= self.EDGE_BOTTOM
            return edges

        def _update_cursor_for_edges(self, edges: int) -> None:
            if edges in (self.EDGE_LEFT | self.EDGE_TOP, self.EDGE_RIGHT | self.EDGE_BOTTOM):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif edges in (self.EDGE_RIGHT | self.EDGE_TOP, self.EDGE_LEFT | self.EDGE_BOTTOM):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif edges in (self.EDGE_LEFT, self.EDGE_RIGHT):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif edges in (self.EDGE_TOP, self.EDGE_BOTTOM):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        def mousePressEvent(self, event: Any) -> None:
            if self.state.click_through:
                event.ignore()
                return
            self.setFocus()
            if event.button() == Qt.MouseButton.LeftButton and not self.state.locked:
                pos = event.position().toPoint()
                edges = self._hit_test_edges(pos)
                self._drag_start_global = event.globalPosition().toPoint()
                self._start_geom = self.geometry()
                if edges != self.EDGE_NONE:
                    self._resizing_edges = edges
                else:
                    self._dragging = True
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event: Any) -> None:
            if self.state.click_through:
                event.ignore()
                return
            pos = event.position().toPoint()
            if self._resizing_edges != self.EDGE_NONE:
                delta = event.globalPosition().toPoint() - self._drag_start_global
                rect = QRect(self._start_geom)
                if self._resizing_edges & self.EDGE_RIGHT:
                    rect.setWidth(max(MIN_PIN_DIMENSION, self._start_geom.width() + delta.x()))
                elif self._resizing_edges & self.EDGE_LEFT:
                    nw = max(MIN_PIN_DIMENSION, self._start_geom.width() - delta.x())
                    rect.setLeft(self._start_geom.right() - nw)
                if self._resizing_edges & self.EDGE_BOTTOM:
                    rect.setHeight(max(MIN_PIN_DIMENSION, self._start_geom.height() + delta.y()))
                elif self._resizing_edges & self.EDGE_TOP:
                    nh = max(MIN_PIN_DIMENSION, self._start_geom.height() - delta.y())
                    rect.setTop(self._start_geom.bottom() - nh)

                preserve = not bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                anchor = "height" if (self._resizing_edges in (self.EDGE_TOP, self.EDGE_BOTTOM)) else "width"
                self.state.x = rect.x()
                self.state.y = rect.y()
                self.state.resize_to(rect.width(), rect.height(), preserve_aspect=preserve, anchor_axis=anchor)
                self.sync_from_state()
                return

            if self._dragging:
                delta = event.globalPosition().toPoint() - self._drag_start_global
                self.state.move_to(self._start_geom.x() + delta.x(), self._start_geom.y() + delta.y())
                self.sync_from_state()
                return

            self._update_cursor_for_edges(self._hit_test_edges(pos))
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event: Any) -> None:
            self._dragging = False
            self._resizing_edges = self.EDGE_NONE
            super().mouseReleaseEvent(event)

        def wheelEvent(self, event: Any) -> None:
            if self.state.click_through:
                event.ignore()
                return
            delta = event.angleDelta().y()
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                if delta > 0:
                    self.step_opacity(1)
                elif delta < 0:
                    self.step_opacity(-1)
                event.accept()
                return
            if not self.state.locked and (
                (event.modifiers() & Qt.KeyboardModifier.ControlModifier) or self._hovered
            ):
                if delta > 0:
                    self.step_zoom(1)
                elif delta < 0:
                    self.step_zoom(-1)
                event.accept()
                return
            super().wheelEvent(event)

        def contextMenuEvent(self, event: Any) -> None:
            menu = QMenu(self)
            menu.addAction("Copy Image (Ctrl+C)", self.copy_to_clipboard)
            menu.addAction("Save As... (Ctrl+S)", self.save_as_dialog)
            menu.addSeparator()

            opacity_menu = menu.addMenu(f"Opacity ({self.state.opacity_pct}%)")
            for op in PIN_OPACITY_PRESETS:
                act = opacity_menu.addAction(f"{op}%")
                act.setCheckable(True)
                act.setChecked(abs(self.state.opacity_pct - op) <= 4)
                act.triggered.connect(lambda _c, o=op: self.set_opacity_preset(o))

            zoom_menu = menu.addMenu(f"Zoom ({self.state.zoom_pct}%)")
            for preset in PIN_ZOOM_PRESETS:
                act = zoom_menu.addAction(f"{preset}%")
                act.setCheckable(True)
                act.setChecked(self.state.zoom_pct == preset)
                act.triggered.connect(lambda _c, p=preset: self.set_zoom_preset(p))
            zoom_menu.addSeparator()
            zoom_menu.addAction("Fit to Screen", self.fit_to_current_screen)
            zoom_menu.addAction("Reset Size (100%)", self.reset_size_to_100)

            menu.addSeparator()
            ct_act = menu.addAction("Click-Through (Ignore Mouse Input)")
            ct_act.setCheckable(True)
            ct_act.setChecked(self.state.click_through)
            ct_act.triggered.connect(self.toggle_click_through)

            aot_act = menu.addAction("Always on Top")
            aot_act.setCheckable(True)
            aot_act.setChecked(self.state.always_on_top)
            aot_act.triggered.connect(self.toggle_always_on_top)

            lock_act = menu.addAction("Lock Position & Size")
            lock_act.setCheckable(True)
            lock_act.setChecked(self.state.locked)
            lock_act.triggered.connect(self.toggle_lock)

            bdr_act = menu.addAction("Show Aqua Border")
            bdr_act.setCheckable(True)
            bdr_act.setChecked(self.state.show_border)
            bdr_act.triggered.connect(self.toggle_border)

            menu.addSeparator()
            menu.addAction("Reset Size (100%)", self.reset_size_to_100)
            menu.addAction("Duplicate Pin", self.duplicate_this_pin)
            menu.addAction("Open Source in Editor", self.reopen_in_editor)
            menu.addSeparator()
            menu.addAction("Close / Unpin (Esc)", self.close_this_pin)
            menu.exec(event.globalPos())

        def step_zoom(self, direction: int) -> None:
            if self.state.locked:
                return
            self.state.zoom_step(direction)
            self.sync_from_state()

        def set_zoom_preset(self, pct: int) -> None:
            if self.state.locked:
                return
            self.state.set_zoom(pct)
            self.sync_from_state()

        def reset_size_to_100(self) -> None:
            if self.state.locked:
                return
            self.state.reset_size()
            self.sync_from_state()

        def fit_to_current_screen(self) -> None:
            if self.state.locked:
                return
            monitors = PinnedScreenshotManager._query_qt_monitors()
            if monitors:
                self.state.fit_to_monitor(monitors[0])
                self.sync_from_state()

        def set_opacity_preset(self, op_pct: int) -> None:
            self.state.set_opacity(op_pct)
            self.sync_from_state()

        def step_opacity(self, direction: int, step: int = 10) -> None:
            self.state.step_opacity(direction, step=step)
            self.sync_from_state()

        def set_click_through(self, enabled: bool) -> None:
            self.state.set_click_through(enabled)
            self.sync_from_state()

        def toggle_click_through(self) -> None:
            self.state.toggle_click_through()
            self.sync_from_state()

        def toggle_lock(self) -> None:
            self.state.locked = not self.state.locked
            self.sync_from_state()

        def toggle_always_on_top(self) -> None:
            self.state.always_on_top = not self.state.always_on_top
            self.sync_from_state()

        def toggle_border(self) -> None:
            self.state.show_border = not self.state.show_border
            self.update()

        def duplicate_this_pin(self) -> None:
            if self.manager is not None:
                self.manager.duplicate_pin(self.state.pin_id)

        def reopen_in_editor(self) -> None:
            if self.manager is not None and self.manager.reopen_in_editor_callback is not None:
                self.manager.reopen_in_editor_callback(self.state.pil_image.copy(), self.state.title)

        def copy_to_clipboard(self) -> None:
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setPixmap(self._qpixmap)

        def save_as_dialog(self, dest_path: Optional[Path] = None) -> Optional[Path]:
            if dest_path is not None:
                return self.state.save_to_file(Path(dest_path))
            dest_str, _ = QFileDialog.getSaveFileName(
                self,
                "Save Pinned Screenshot As",
                str(Path.home() / "Pictures" / "Prismwake" / "Pinned_Screenshot.png"),
                "PNG Image (*.png);;All Files (*.*)",
            )
            if not dest_str:
                return None
            try:
                return self.state.save_to_file(Path(dest_str))
            except Exception as exc:
                QMessageBox.warning(self, "Save Error", f"Failed to save pinned screenshot:\n{exc}")
                return None

        def close_this_pin(self) -> None:
            if self.manager is not None:
                self.manager.close_pin(self.state.pin_id)
            else:
                self.state.is_closed = True
                self.unlock_pill.close()
                self.close()

        def paintEvent(self, _event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            rect_f = self.rect().adjusted(2, 2, -2, -2)
            clip_path = QPainterPath()
            clip_path.addRoundedRect(
                float(rect_f.x()),
                float(rect_f.y()),
                float(rect_f.width()),
                float(rect_f.height()),
                8.0,
                8.0,
            )

            # Subtle outer shadow
            shadow_path = QPainterPath()
            shadow_path.addRoundedRect(1.0, 1.0, float(self.width() - 2), float(self.height() - 2), 9.0, 9.0)
            painter.fillPath(shadow_path, QColor(0, 12, 28, 95))

            painter.save()
            painter.setClipPath(clip_path)
            painter.drawPixmap(rect_f, self._qpixmap)
            painter.restore()

            if self._flash_active:
                painter.setPen(QPen(QColor(105, 255, 215, 250), 3.0))
                painter.drawPath(clip_path)
            elif self.state.show_border or self._hovered:
                border_col = (
                    QColor(130, 220, 255, 130)
                    if self.state.click_through
                    else QColor(90, 232, 255, 235 if self._hovered else 175)
                )
                pen_style = Qt.PenStyle.DashLine if self.state.click_through else Qt.PenStyle.SolidLine
                painter.setPen(QPen(border_col, 1.6 if self._hovered else 1.2, pen_style))
                painter.drawPath(clip_path)

            painter.end()
