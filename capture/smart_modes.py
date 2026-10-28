"""
Prismwake v0.2.0 — Win32 Window Detection, Multi-Monitor Selector, Delayed Capture & Hotkey Validation
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

try:
    from PyQt6.QtCore import (
        QObject,
        QPoint,
        QRect,
        Qt,
        QTimer,
        pyqtSignal,
    )
    from PyQt6.QtGui import (
        QColor,
        QFont,
        QKeySequence,
        QPainter,
        QPainterPath,
        QPen,
        QShortcut,
    )
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
    HAS_QT = True
except Exception:
    HAS_QT = False


VALID_CAPTURE_MODES: Tuple[str, ...] = (
    "region",
    "window",
    "fullscreen",
    "delayed",
    "ocr",
)
DELAY_PRESET_SECONDS: Tuple[int, ...] = (0, 3, 5, 10)

# Windows OS-reserved shortcuts that applications must never silently override
RESERVED_WINDOWS_SHORTCUTS: Set[str] = {
    "WIN+L",
    "WIN+D",
    "WIN+E",
    "WIN+R",
    "WIN+TAB",
    "WIN+X",
    "WIN+I",
    "CTRL+ALT+DEL",
    "CTRL+SHIFT+ESC",
    "ALT+TAB",
    "ALT+F4",
}

GA_ROOT: int = 2
DWMWA_EXTENDED_FRAME_BOUNDS: int = 9
DWMWA_CLOAKED: int = 14
GWL_EXSTYLE: int = -20
WS_EX_TOOLWINDOW: int = 0x00000080
WS_EX_TRANSPARENT: int = 0x00000020
WS_EX_LAYERED: int = 0x00080000
WS_EX_NOACTIVATE: int = 0x08000000

SHELL_AND_OVERLAY_CLASSES: Set[str] = {
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow",
    "Windows.UI.Core.CoreWindow",
    "XamlExplorerHostIslandWindow",
    "ForegroundStaging",
    "ApplicationManager_DesktopShellWindow",
    "DummyDWMListenerWindow",
    "IME",
    "MSCTFIME UI",
}


def normalize_capture_mode(value: Any) -> str:
    s = str(value or "region").strip().lower()
    if s == "monitor":
        return "fullscreen"
    if s in ("text", "text_capture"):
        return "ocr"
    if s in VALID_CAPTURE_MODES:
        return s
    return "region"


def clamp_capture_delay_seconds(value: Any) -> int:
    try:
        v = int(round(float(value)))
    except Exception:
        v = 0
    return max(0, min(60, v))


@dataclass(frozen=True)
class DetectedWindowInfo:
    """Metadata and physical pixel bounds for a detected desktop application window."""
    hwnd: int
    title: str
    class_name: str
    process_id: int
    left: int
    top: int
    right: int
    bottom: int
    is_minimized: bool = False
    is_maximized: bool = False
    is_visible: bool = True
    is_cloaked: bool = False
    used_dwm_frame_bounds: bool = True
    client_left: Optional[int] = None
    client_top: Optional[int] = None
    client_right: Optional[int] = None
    client_bottom: Optional[int] = None

    @property
    def width(self) -> int:
        return max(0, int(self.right - self.left))

    @property
    def height(self) -> int:
        return max(0, int(self.bottom - self.top))

    @property
    def has_valid_client_bounds(self) -> bool:
        if (
            self.client_left is None
            or self.client_top is None
            or self.client_right is None
            or self.client_bottom is None
        ):
            return False
        return (self.client_right - self.client_left) >= 16 and (self.client_bottom - self.client_top) >= 16

    def effective_bounds(self, client_only: bool = False) -> Tuple[int, int, int, int]:
        if client_only and self.has_valid_client_bounds:
            return (
                int(self.client_left),  # type: ignore[arg-type]
                int(self.client_top),   # type: ignore[arg-type]
                int(self.client_right), # type: ignore[arg-type]
                int(self.client_bottom),# type: ignore[arg-type]
            )
        return int(self.left), int(self.top), int(self.right), int(self.bottom)

    @property
    def is_capturable(self) -> bool:
        return (
            self.is_visible
            and not self.is_minimized
            and not self.is_cloaked
            and self.width >= 16
            and self.height >= 16
        )

    @property
    def unavailable_reason(self) -> str:
        if self.is_minimized:
            return f"Window '{self.title or self.hwnd}' is currently minimized and cannot be captured."
        if not self.is_visible or self.is_cloaked:
            return f"Window '{self.title or self.hwnd}' is hidden or cloaked on another virtual desktop."
        if self.width < 16 or self.height < 16:
            return f"Window '{self.title or self.hwnd}' has zero/invalid visible bounds ({self.width}×{self.height})."
        return ""

    def display_badge_text(self, client_only: bool = False) -> str:
        bx0, by0, bx1, by1 = self.effective_bounds(client_only=client_only)
        bw = max(0, bx1 - bx0)
        bh = max(0, by1 - by0)
        label = (self.title or self.class_name or f"Window 0x{self.hwnd:X}").strip()
        if len(label) > 54:
            label = label[:51] + "..."
        area_tag = "Client Area" if (client_only and self.has_valid_client_bounds) else "Full Window"
        return f"▣ {label}  •  {bw} × {bh} px ({area_tag})"

    def contains_physical_point(self, px: int, py: int, *, client_only: bool = False) -> bool:
        if not self.is_capturable:
            return False
        bx0, by0, bx1, by1 = self.effective_bounds(client_only=client_only)
        return bx0 <= int(px) < bx1 and by0 <= int(py) < by1

    def to_local_monitor_rect(
        self,
        monitor_left: int,
        monitor_top: int,
        monitor_width: int,
        monitor_height: int,
        dpi_scale: float = 1.0,
        *,
        client_only: bool = False,
    ) -> Tuple[int, int, int, int]:
        """
        Convert physical desktop window bounds into local logical coordinates inside
        a captured monitor frame, clipping cleanly at monitor boundaries.
        """
        bx0, by0, bx1, by1 = self.effective_bounds(client_only=client_only)
        cx0, cy0, cx1, cy1 = clip_window_bounds_to_monitor(
            bx0,
            by0,
            bx1,
            by1,
            monitor_left,
            monitor_top,
            monitor_width,
            monitor_height,
        )
        inv_dpi = 1.0 / max(dpi_scale, 1e-6)
        lx = int(round((cx0 - monitor_left) * inv_dpi))
        ly = int(round((cy0 - monitor_top) * inv_dpi))
        lw = max(1, int(round((cx1 - cx0) * inv_dpi)))
        lh = max(1, int(round((cy1 - cy0) * inv_dpi)))
        return lx, ly, lw, lh


def clip_window_bounds_to_monitor(
    win_left: int,
    win_top: int,
    win_right: int,
    win_bottom: int,
    mon_left: int,
    mon_top: int,
    mon_width: int,
    mon_height: int,
) -> Tuple[int, int, int, int]:
    """
    Clip physical window coordinates `(win_left, win_top, win_right, win_bottom)`
    against a monitor's physical bounds `(mon_left, mon_top, mon_left+mon_width, mon_top+mon_height)`.
    Essential for maximized windows (whose standard Win32 rect extends 8px past monitor edges)
    and windows straddling multiple displays.
    """
    mon_right = mon_left + max(1, int(mon_width))
    mon_bottom = mon_top + max(1, int(mon_height))
    cx0 = max(int(mon_left), min(int(mon_right), int(win_left)))
    cy0 = max(int(mon_top), min(int(mon_bottom), int(win_top)))
    cx1 = max(cx0, min(int(mon_right), int(win_right)))
    cy1 = max(cy0, min(int(mon_bottom), int(win_bottom)))
    return cx0, cy0, cx1, cy1


def _query_win32_window_info(hwnd: int, *, use_dwm_bounds: bool = True) -> Optional[DetectedWindowInfo]:
    """Query Win32 & DWM attributes (including client-area bounds) for a top-level HWND on Windows."""
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi

        is_vis = bool(user32.IsWindowVisible(wintypes.HWND(hwnd)))
        is_min = bool(user32.IsIconic(wintypes.HWND(hwnd)))
        is_max = bool(user32.IsZoomed(wintypes.HWND(hwnd)))

        # Check extended style to ignore transparent click-through overlays or untitled tool windows
        ex_style = int(user32.GetWindowLongW(wintypes.HWND(hwnd), ctypes.c_int(GWL_EXSTYLE)))
        if (ex_style & WS_EX_TRANSPARENT) and (ex_style & WS_EX_LAYERED):
            return None

        # Title
        length = int(user32.GetWindowTextLengthW(wintypes.HWND(hwnd)))
        title = ""
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 2)
            user32.GetWindowTextW(wintypes.HWND(hwnd), buf, length + 2)
            title = buf.value.strip()

        if not title and (ex_style & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)):
            return None

        # Class name
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(wintypes.HWND(hwnd), cls_buf, 256)
        class_name = cls_buf.value.strip()

        # Process ID
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))

        # Check DWM cloaked state (e.g., suspended UWP apps or other virtual desktops)
        cloaked_val = wintypes.DWORD(0)
        hr_cloak = dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMWA_CLOAKED),
            ctypes.byref(cloaked_val),
            ctypes.sizeof(cloaked_val),
        )
        is_cloaked = bool(hr_cloak == 0 and cloaked_val.value != 0)

        # Prefer DWMWA_EXTENDED_FRAME_BOUNDS so invisible drop-shadow borders are excluded
        rect = wintypes.RECT()
        used_dwm = False
        if use_dwm_bounds:
            hr_bounds = dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            used_dwm = (hr_bounds == 0)
        if not used_dwm:
            user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))

        # Query client area in physical screen coordinates
        c_left: Optional[int] = None
        c_top: Optional[int] = None
        c_right: Optional[int] = None
        c_bottom: Optional[int] = None
        try:
            crect = wintypes.RECT()
            if user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(crect)):
                cw = int(crect.right - crect.left)
                ch = int(crect.bottom - crect.top)
                if cw >= 16 and ch >= 16:
                    pt_tl = wintypes.POINT(int(crect.left), int(crect.top))
                    if user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(pt_tl)):
                        c_left = int(pt_tl.x)
                        c_top = int(pt_tl.y)
                        c_right = int(pt_tl.x + cw)
                        c_bottom = int(pt_tl.y + ch)
        except Exception:
            pass

        return DetectedWindowInfo(
            hwnd=int(hwnd),
            title=title,
            class_name=class_name,
            process_id=int(pid.value),
            left=int(rect.left),
            top=int(rect.top),
            right=int(rect.right),
            bottom=int(rect.bottom),
            is_minimized=is_min,
            is_maximized=is_max,
            is_visible=is_vis,
            is_cloaked=is_cloaked,
            used_dwm_frame_bounds=used_dwm,
            client_left=c_left,
            client_top=c_top,
            client_right=c_right,
            client_bottom=c_bottom,
        )
    except Exception:
        return None


def enumerate_capturable_windows(
    *,
    exclude_hwnds: Optional[Set[int]] = None,
    exclude_pid: Optional[int] = None,
    mock_windows: Optional[Sequence[DetectedWindowInfo]] = None,
    use_dwm_bounds: bool = True,
) -> List[DetectedWindowInfo]:
    """
    Return top-level windows in Z-order (front-to-back), excluding Prismwake's own
    overlay/toolbar/pin windows and system shell clutter.
    """
    excluded_h = set(exclude_hwnds or set())
    own_pid = os.getpid() if exclude_pid is None else int(exclude_pid)

    if mock_windows is not None:
        out: List[DetectedWindowInfo] = []
        for w in mock_windows:
            if w.hwnd in excluded_h or w.process_id == own_pid:
                continue
            if w.class_name in SHELL_AND_OVERLAY_CLASSES:
                continue
            if not w.is_capturable:
                continue
            out.append(w)
        return out

    if sys.platform != "win32":
        return []

    results: List[DetectedWindowInfo] = []
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _enum_cb(hwnd: int, _lparam: int) -> bool:
        h_int = int(hwnd)
        if h_int in excluded_h:
            return True
        info = _query_win32_window_info(h_int, use_dwm_bounds=use_dwm_bounds)
        if info is None:
            return True
        if info.process_id == own_pid:
            return True
        if info.class_name in SHELL_AND_OVERLAY_CLASSES:
            return True
        if not info.title and not info.class_name:
            return True
        if info.is_capturable:
            results.append(info)
        return True

    cb_func = WNDENUMPROC(_enum_cb)
    user32.EnumWindows(cb_func, 0)
    return results


def detect_window_at_physical_point(
    px: int,
    py: int,
    *,
    exclude_hwnds: Optional[Set[int]] = None,
    exclude_pid: Optional[int] = None,
    candidate_windows: Optional[Sequence[DetectedWindowInfo]] = None,
    client_only: bool = False,
    use_dwm_bounds: bool = True,
) -> Optional[DetectedWindowInfo]:
    """
    Find the topmost capturable application window under physical cursor `(px, py)`.
    Because Prismwake's fullscreen capture overlay covers the screen while the user
    moves the cursor, walking Z-ordered `candidate_windows` (or `EnumWindows`) while
    excluding Prismwake's own HWNDs and PID reliably finds the exact underlying window
    under the cursor without ever capturing Prismwake's own toolbar or overlay.
    """
    windows = (
        list(candidate_windows)
        if candidate_windows is not None
        else enumerate_capturable_windows(
            exclude_hwnds=exclude_hwnds,
            exclude_pid=exclude_pid,
            use_dwm_bounds=use_dwm_bounds,
        )
    )
    excluded_h = set(exclude_hwnds or set())
    own_pid = os.getpid() if exclude_pid is None else int(exclude_pid)

    for w in windows:
        if w.hwnd in excluded_h or w.process_id == own_pid:
            continue
        if w.class_name in SHELL_AND_OVERLAY_CLASSES:
            continue
        if not w.is_capturable:
            continue
        if w.contains_physical_point(px, py, client_only=client_only):
            return w

    # Fallback direct Win32 WindowFromPoint + GetAncestor(GA_ROOT) when overlay is hidden
    if sys.platform == "win32" and candidate_windows is None:
        try:
            user32 = ctypes.windll.user32
            pt = wintypes.POINT(int(px), int(py))
            raw_hwnd = user32.WindowFromPoint(pt)
            if raw_hwnd:
                root_hwnd = user32.GetAncestor(wintypes.HWND(raw_hwnd), ctypes.c_uint(GA_ROOT))
                target_h = int(root_hwnd or raw_hwnd)
                if target_h not in excluded_h:
                    info = _query_win32_window_info(target_h, use_dwm_bounds=use_dwm_bounds)
                    if (
                        info is not None
                        and info.process_id != own_pid
                        and info.class_name not in SHELL_AND_OVERLAY_CLASSES
                        and info.contains_physical_point(px, py, client_only=client_only)
                    ):
                        return info
        except Exception:
            pass
    return None


class WindowCaptureSessionController:
    """
    Deterministic controller for True Window Capture inside the capture overlay:
      - Holds a Z-ordered snapshot of capturable desktop windows (`candidate_windows`).
      - Maps local overlay cursor movement `(local_x, local_y)` to physical desktop coordinates
        and dynamically highlights the topmost window under the cursor (`hovered_window`).
      - Clicking any window snaps the capture selection to that window's exact bounds
        (`locked_window` / `locked_local_rect`).
      - Clicking a different window immediately moves the capture selection to the newly
        clicked window instead of falling back to freehand drag-region selection.
      - Supports toggling between full window bounds (DWM extended frame) and client area.
    """

    def __init__(
        self,
        *,
        monitor_rect: Tuple[int, int, int, int] = (0, 0, 1920, 1080),
        dpi_scale: float = 1.0,
        px_scale_x: float = 1.0,
        px_scale_y: float = 1.0,
        client_only: bool = False,
        use_dwm_bounds: bool = True,
        candidate_windows: Optional[Sequence[DetectedWindowInfo]] = None,
        exclude_hwnds: Optional[Set[int]] = None,
        exclude_pid: Optional[int] = None,
    ) -> None:
        self.monitor_rect: Tuple[int, int, int, int] = (
            int(monitor_rect[0]),
            int(monitor_rect[1]),
            max(1, int(monitor_rect[2])),
            max(1, int(monitor_rect[3])),
        )
        self.dpi_scale: float = max(1e-4, float(dpi_scale or 1.0))
        self.px_scale_x: float = max(1e-4, float(px_scale_x or self.dpi_scale))
        self.px_scale_y: float = max(1e-4, float(px_scale_y or self.dpi_scale))
        self.client_only: bool = bool(client_only)
        self.use_dwm_bounds: bool = bool(use_dwm_bounds)
        self.exclude_hwnds: Set[int] = set(exclude_hwnds or set())
        self.exclude_pid: int = os.getpid() if exclude_pid is None else int(exclude_pid)

        self.candidate_windows: List[DetectedWindowInfo] = []
        self.hovered_window: Optional[DetectedWindowInfo] = None
        self.hovered_local_rect: Optional[Tuple[int, int, int, int]] = None
        self.locked_window: Optional[DetectedWindowInfo] = None
        self.locked_local_rect: Optional[Tuple[int, int, int, int]] = None
        self._last_local_pos: Optional[Tuple[float, float]] = None

        self.refresh_candidates(candidate_windows=candidate_windows)

    def refresh_candidates(
        self,
        *,
        candidate_windows: Optional[Sequence[DetectedWindowInfo]] = None,
        exclude_hwnds: Optional[Set[int]] = None,
    ) -> List[DetectedWindowInfo]:
        if exclude_hwnds is not None:
            self.exclude_hwnds = set(exclude_hwnds)
        self.candidate_windows = enumerate_capturable_windows(
            exclude_hwnds=self.exclude_hwnds,
            exclude_pid=self.exclude_pid,
            mock_windows=candidate_windows,
            use_dwm_bounds=self.use_dwm_bounds,
        )
        return self.candidate_windows

    def local_to_physical(self, local_x: float, local_y: float) -> Tuple[int, int]:
        mon_x, mon_y, _mon_w, _mon_h = self.monitor_rect
        px = int(round(mon_x + float(local_x) * self.px_scale_x))
        py = int(round(mon_y + float(local_y) * self.px_scale_y))
        return px, py

    def window_to_local_rect(self, win: DetectedWindowInfo) -> Tuple[int, int, int, int]:
        mon_x, mon_y, mon_w, mon_h = self.monitor_rect
        bx0, by0, bx1, by1 = win.effective_bounds(client_only=self.client_only)
        cx0, cy0, cx1, cy1 = clip_window_bounds_to_monitor(
            bx0, by0, bx1, by1, mon_x, mon_y, mon_w, mon_h
        )
        lx = int(round((cx0 - mon_x) / self.px_scale_x))
        ly = int(round((cy0 - mon_y) / self.px_scale_y))
        lw = max(1, int(round((cx1 - cx0) / self.px_scale_x)))
        lh = max(1, int(round((cy1 - cy0) / self.px_scale_y)))
        return lx, ly, lw, lh

    def update_hover_local(
        self, local_x: float, local_y: float
    ) -> Optional[Tuple[DetectedWindowInfo, Tuple[int, int, int, int]]]:
        """Update the hovered target window under local overlay coordinates `(local_x, local_y)`."""
        self._last_local_pos = (float(local_x), float(local_y))
        px, py = self.local_to_physical(local_x, local_y)
        det = detect_window_at_physical_point(
            px,
            py,
            exclude_hwnds=self.exclude_hwnds,
            exclude_pid=self.exclude_pid,
            candidate_windows=self.candidate_windows,
            client_only=self.client_only,
            use_dwm_bounds=self.use_dwm_bounds,
        )
        if det is None:
            self.hovered_window = None
            self.hovered_local_rect = None
            return None
        rect = self.window_to_local_rect(det)
        self.hovered_window = det
        self.hovered_local_rect = rect
        return det, rect

    def click_select_local(
        self, local_x: float, local_y: float
    ) -> Optional[Tuple[DetectedWindowInfo, Tuple[int, int, int, int]]]:
        """
        Select and snap to the window under `(local_x, local_y)`.
        Always updates `locked_window` and `locked_local_rect` to the clicked window
        so clicking a different window moves the capture region to that window.
        """
        res = self.update_hover_local(local_x, local_y)
        if res is None:
            return None
        win, rect = res
        self.locked_window = win
        self.locked_local_rect = rect
        return win, rect

    def set_client_only(self, client_only: bool) -> None:
        self.client_only = bool(client_only)
        if self.hovered_window is not None:
            self.hovered_local_rect = self.window_to_local_rect(self.hovered_window)
        if self.locked_window is not None:
            self.locked_local_rect = self.window_to_local_rect(self.locked_window)
        elif self._last_local_pos is not None:
            self.update_hover_local(self._last_local_pos[0], self._last_local_pos[1])

    def clear_locked_selection(self) -> None:
        self.locked_window = None
        self.locked_local_rect = None


@dataclass(frozen=True)
class MonitorCaptureTarget:
    """Describes a physical display available for single-action Fullscreen / Monitor Capture."""
    index: int
    device_name: str
    friendly_name: str
    left: int
    top: int
    width: int
    height: int
    dpi_scale: float = 1.0
    is_primary: bool = False
    hdr_enabled: Optional[bool] = None
    sdr_white_nits: float = 203.0

    @property
    def summary_label(self) -> str:
        pri = " [Primary]" if self.is_primary else ""
        hdr = " • HDR" if self.hdr_enabled else (" • SDR" if self.hdr_enabled is False else "")
        return (
            f"Display {self.index + 1}: {self.friendly_name or self.device_name}{pri} — "
            f"{self.width}×{self.height} @ ({self.left}, {self.top}){hdr}"
        )


@dataclass(frozen=True)
class HotkeyConflictReport:
    """Result of validating all configured global shortcuts for internal duplicates or OS conflicts."""
    valid: bool
    conflicts: Tuple[str, ...] = ()
    reserved_violations: Tuple[str, ...] = ()
    normalized_map: Dict[str, str] = field(default_factory=dict)


def _canonicalize_hotkey(hk: str) -> str:
    raw = (hk or "").strip().upper()
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split("+") if p.strip()]
    mods: List[str] = []
    key_token = ""
    for p in parts:
        if p in ("CTRL", "CONTROL"):
            if "CTRL" not in mods:
                mods.append("CTRL")
        elif p in ("SHIFT",):
            if "SHIFT" not in mods:
                mods.append("SHIFT")
        elif p in ("ALT",):
            if "ALT" not in mods:
                mods.append("ALT")
        elif p in ("WIN", "WINDOWS", "META", "SUPER"):
            if "WIN" not in mods:
                mods.append("WIN")
        else:
            key_token = p
    ordered_mods = [m for m in ("CTRL", "ALT", "SHIFT", "WIN") if m in mods]
    if key_token:
        ordered_mods.append(key_token)
    return "+".join(ordered_mods)


def validate_hotkey_assignments(assignments: Dict[str, str]) -> HotkeyConflictReport:
    """
    Validate a mapping of `action_name -> hotkey_string` (for Region, Window, Fullscreen,
    OCR, and History shortcuts). Detects duplicate hotkeys and Windows-reserved combinations.
    """
    seen: Dict[str, str] = {}
    conflicts: List[str] = []
    reserved: List[str] = []
    norm_map: Dict[str, str] = {}

    for action, raw_hk in assignments.items():
        canon = _canonicalize_hotkey(raw_hk)
        norm_map[action] = canon
        if not canon:
            continue
        if canon in RESERVED_WINDOWS_SHORTCUTS:
            reserved.append(f"'{canon}' ({action}) is a Windows-reserved system shortcut.")
        if canon in seen:
            other_action = seen[canon]
            conflicts.append(f"Shortcut '{canon}' is assigned to both '{other_action}' and '{action}'.")
        else:
            seen[canon] = action

    return HotkeyConflictReport(
        valid=(len(conflicts) == 0 and len(reserved) == 0),
        conflicts=tuple(conflicts),
        reserved_violations=tuple(reserved),
        normalized_map=norm_map,
    )


class DelayedCaptureController:
    """
    Non-blocking countdown state machine for Delayed Screenshots (`3s`, `5s`, `10s`, custom).
    Can be driven deterministically in unit tests via `tick()` or by a `QTimer` in the GUI.
    Always hides the countdown overlay and processes events BEFORE the GPU framebuffer is captured.
    """

    def __init__(
        self,
        delay_seconds: int,
        target_mode: str = "region",
        *,
        on_tick: Optional[Callable[[int], None]] = None,
        on_ready_to_capture: Optional[Callable[[str], None]] = None,
        on_cancelled: Optional[Callable[[], None]] = None,
    ) -> None:
        self.total_seconds: int = clamp_capture_delay_seconds(delay_seconds)
        self.remaining_seconds: int = self.total_seconds
        self.target_mode: str = normalize_capture_mode(target_mode)
        self.on_tick = on_tick
        self.on_ready_to_capture = on_ready_to_capture
        self.on_cancelled = on_cancelled
        self.is_running: bool = False
        self.is_cancelled: bool = False
        self.overlay_visible: bool = False

    def start(self) -> None:
        self.is_cancelled = False
        self.remaining_seconds = self.total_seconds
        if self.remaining_seconds <= 0:
            self.is_running = False
            self.overlay_visible = False
            if self.on_ready_to_capture is not None:
                self.on_ready_to_capture(self.target_mode)
            return
        self.is_running = True
        self.overlay_visible = True
        if self.on_tick is not None:
            self.on_tick(self.remaining_seconds)

    def tick(self) -> int:
        if not self.is_running or self.is_cancelled:
            return self.remaining_seconds
        self.remaining_seconds = max(0, self.remaining_seconds - 1)
        if self.remaining_seconds > 0:
            if self.on_tick is not None:
                self.on_tick(self.remaining_seconds)
            return self.remaining_seconds

        # Countdown reached 0: hide overlay FIRST so it never appears in the captured screenshot
        self.overlay_visible = False
        self.is_running = False
        if self.on_ready_to_capture is not None:
            self.on_ready_to_capture(self.target_mode)
        return 0

    def cancel(self) -> None:
        if not self.is_running:
            return
        self.is_cancelled = True
        self.is_running = False
        self.overlay_visible = False
        if self.on_cancelled is not None:
            self.on_cancelled()


if HAS_QT:
    class DelayedCountdownOverlay(QWidget):
        """
        Small floating Frutiger Aqua countdown pill for Delayed Capture.
        Never blocks the GUI thread, supports Escape or Cancel button, and hides
        itself completely before the desktop capture occurs.
        """

        captureReady = pyqtSignal(str)  # target_mode
        cancelled = pyqtSignal()

        def __init__(
            self,
            delay_seconds: int,
            target_mode: str = "region",
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)
            self.controller = DelayedCaptureController(
                delay_seconds=delay_seconds,
                target_mode=target_mode,
                on_tick=self._on_tick,
                on_ready_to_capture=self._on_ready,
                on_cancelled=self._on_cancelled,
            )

            self.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setFixedSize(310, 64)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(16, 10, 16, 10)
            layout.setSpacing(10)

            self.lbl = QLabel("")
            self.lbl.setStyleSheet("color: #f0fbff; font-size: 13px; font-weight: 600;")
            layout.addWidget(self.lbl, 1)

            self.cancel_btn = QPushButton("Cancel (Esc)")
            self.cancel_btn.setStyleSheet(
                """
                QPushButton {
                    background: rgba(195, 42, 62, 220);
                    color: white;
                    border: 1px solid rgba(255, 180, 190, 190);
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: rgba(225, 58, 78, 240);
                }
                """
            )
            self.cancel_btn.clicked.connect(self.cancel_countdown)
            layout.addWidget(self.cancel_btn)

            esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
            esc.activated.connect(self.cancel_countdown)

            self._timer = QTimer(self)
            self._timer.setInterval(1000)
            self._timer.timeout.connect(self.controller.tick)

        def start_countdown(self) -> None:
            scr = QApplication.primaryScreen()
            if scr is not None:
                avail = scr.availableGeometry()
                self.move(avail.x() + (avail.width() - self.width()) // 2, avail.y() + 28)
            self.show()
            self.raise_()
            self.controller.start()
            if self.controller.is_running:
                self._timer.start()

        def cancel_countdown(self) -> None:
            self._timer.stop()
            self.controller.cancel()

        def _on_tick(self, remaining: int) -> None:
            mode_label = self.controller.target_mode.capitalize()
            self.lbl.setText(f"{mode_label} Capture in {remaining}s...")
            self.update()

        def _on_ready(self, mode: str) -> None:
            self._timer.stop()
            self.hide()
            QApplication.processEvents()
            # Give DWM 35ms after hiding the countdown pill before firing GPU capture
            QTimer.singleShot(35, lambda: self.captureReady.emit(mode))

        def _on_cancelled(self) -> None:
            self._timer.stop()
            self.hide()
            self.cancelled.emit()

        def paintEvent(self, _event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            path = QPainterPath()
            path.addRoundedRect(2.0, 2.0, float(self.width() - 4), float(self.height() - 4), 14.0, 14.0)
            painter.fillPath(path, QColor(8, 34, 62, 230))
            painter.setPen(QPen(QColor(115, 232, 255, 210), 1.5))
            painter.drawPath(path)
            painter.end()

    class MonitorSelectorDialog(QDialog):
        """Frutiger Aqua monitor picker for multi-monitor Fullscreen Capture."""

        def __init__(
            self,
            monitors: Sequence[MonitorCaptureTarget],
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)
            self._monitors = list(monitors)
            self.selected_monitor: Optional[MonitorCaptureTarget] = (
                self._monitors[0] if self._monitors else None
            )
            self.setWindowTitle("Prismwake — Select Display to Capture")
            self.resize(520, 310)
            self.setStyleSheet(
                """
                QDialog {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #0b2b4c, stop:1 #051324);
                    color: #eaf8ff;
                }
                QLabel { color: #dff6ff; font-size: 13px; }
                QListWidget {
                    background: rgba(7, 22, 42, 220);
                    color: #f2fbff;
                    border: 1px solid rgba(110, 225, 255, 145);
                    border-radius: 8px;
                    padding: 6px;
                    font-size: 12px;
                }
                QPushButton {
                    background: rgba(24, 138, 208, 225);
                    color: white;
                    border: 1px solid rgba(155, 238, 255, 185);
                    border-radius: 7px;
                    padding: 6px 14px;
                    font-weight: 600;
                }
                """
            )
            root = QVBoxLayout(self)
            root.addWidget(QLabel("<b>Select a monitor for Fullscreen HDR/SDR Capture:</b>"))
            self.list_widget = QListWidget()
            for m in self._monitors:
                it = QListWidgetItem(m.summary_label)
                it.setData(Qt.ItemDataRole.UserRole, m.index)
                self.list_widget.addItem(it)
            if self.list_widget.count() > 0:
                self.list_widget.setCurrentRow(0)
            self.list_widget.itemDoubleClicked.connect(lambda _it: self._accept_current())
            root.addWidget(self.list_widget, 1)

            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            cap_btn = QPushButton("Capture Display")
            cap_btn.clicked.connect(self._accept_current)
            btn_row.addWidget(cap_btn)
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(self.reject)
            btn_row.addWidget(cancel_btn)
            root.addLayout(btn_row)

        def _accept_current(self) -> None:
            row = self.list_widget.currentRow()
            if 0 <= row < len(self._monitors):
                self.selected_monitor = self._monitors[row]
            self.accept()

else:
    DelayedCountdownOverlay = None  # type: ignore[assignment,misc]
    MonitorSelectorDialog = None  # type: ignore[assignment,misc]
