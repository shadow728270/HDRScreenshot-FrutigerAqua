"""
Prismwake v0.2.0 — Pinned Floating Screenshots Subsystem (`pinning`)
====================================================================
Provides independent floating screenshot windows (`PinnedScreenshotWindow`) and
headless geometry/DPI/multi-monitor/capture-exclusion management (`PinnedScreenshotManager`):
  - Independent top-level windows (`WindowStaysOnTopHint`, frameless Frutiger Aqua thin border,
    subtle shadow, rounded corners, and auto-hiding hover toolbar).
  - Draggable and 8-edge/corner resizable with aspect-ratio preservation by default (`Shift`
    allows free resize).
  - Sharp high-DPI rendering at any zoom (`25%`, `50%`, `75%`, `100%`, `150%`, `200%`, `300%`,
    `Fit`, `1:1` Reset Size, plus `Ctrl+Wheel`).
  - Live Opacity control (`15%–100%` slider, presets, and `Alt+Wheel`), Click-Through toggle
    (`WindowTransparentForInput` + Win32 `WS_EX_TRANSPARENT | WS_EX_LAYERED` + corner unlock pill
    and tray/modifier unlock), Lock Position, Toggle Always-on-Top, Duplicate Pin,
    Copy (`Ctrl+C`), Save As (`Ctrl+S`), Reopen in Editor, and `Esc` to close only the focused pin.
  - Multi-monitor & negative virtual-desktop coordinate support (`100%`, `125%`, `150%`, `200%` DPI),
    offscreen/disconnected-monitor recovery, and capture interaction (`SetWindowDisplayAffinity`
    `WDA_EXCLUDEFROMCAPTURE` + automatic temporary hide/restore around captures).
"""

from .manager import (
    PIN_ZOOM_PRESETS,
    PIN_OPACITY_PRESETS,
    MIN_PIN_OPACITY_PCT,
    MAX_PIN_OPACITY_PCT,
    MIN_PIN_DIMENSION,
    VirtualMonitorRect,
    PinnedScreenshotState,
    PinnedScreenshotManager,
    clamp_pin_opacity_pct,
    clamp_pin_zoom_pct,
    compute_aspect_locked_size,
    compute_fit_zoom_pct,
    recover_offscreen_pin_rect,
    apply_win32_window_capture_exclusion,
    apply_win32_window_click_through,
)

__all__ = [
    "PIN_ZOOM_PRESETS",
    "PIN_OPACITY_PRESETS",
    "MIN_PIN_OPACITY_PCT",
    "MAX_PIN_OPACITY_PCT",
    "MIN_PIN_DIMENSION",
    "VirtualMonitorRect",
    "PinnedScreenshotState",
    "PinnedScreenshotManager",
    "clamp_pin_opacity_pct",
    "clamp_pin_zoom_pct",
    "compute_aspect_locked_size",
    "compute_fit_zoom_pct",
    "recover_offscreen_pin_rect",
    "apply_win32_window_capture_exclusion",
    "apply_win32_window_click_through",
]
