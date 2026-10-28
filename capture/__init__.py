"""
Prismwake v0.2.0 — Smart Capture Modes & Intelligent Window Detection (`capture`)
=================================================================================
Implements the five distinct capture workflows and hotkey conflict validation:
  1. `region`: Interactive region selection with annotation/pin/OCR toolbar.
  2. `window`: Intelligent Win32 window detection (`EnumWindows`, `WindowFromPoint`,
     `GetAncestor(GA_ROOT)`, `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`,
     `DWMWA_CLOAKED`, `IsIconic`, `IsWindowVisible`, `GetClientRect` + `ClientToScreen`,
     excluding Prismwake's own HWNDs/PID) with live hover highlight and deterministic
     click-to-snap window capture (`WindowCaptureSessionController`).
  3. `fullscreen`: Single-action monitor capture with multi-monitor selector preserving
     the DXGI scRGB HDR pipeline, per-monitor SDR white level, and tone-mapping settings.
  4. `delayed`: Configurable non-blocking countdown (`3s`, `5s`, `10s`, or custom `1–60s`)
     with a cancellable floating countdown pill that hides before GPU capture.
  5. `ocr`: Dedicated Text Capture region workflow that launches offline OCR directly.
"""

from .smart_modes import (
    VALID_CAPTURE_MODES,
    DELAY_PRESET_SECONDS,
    RESERVED_WINDOWS_SHORTCUTS,
    DetectedWindowInfo,
    WindowCaptureSessionController,
    MonitorCaptureTarget,
    DelayedCaptureController,
    HotkeyConflictReport,
    clamp_capture_delay_seconds,
    normalize_capture_mode,
    detect_window_at_physical_point,
    enumerate_capturable_windows,
    clip_window_bounds_to_monitor,
    validate_hotkey_assignments,
)

__all__ = [
    "VALID_CAPTURE_MODES",
    "DELAY_PRESET_SECONDS",
    "RESERVED_WINDOWS_SHORTCUTS",
    "DetectedWindowInfo",
    "WindowCaptureSessionController",
    "MonitorCaptureTarget",
    "DelayedCaptureController",
    "HotkeyConflictReport",
    "clamp_capture_delay_seconds",
    "normalize_capture_mode",
    "detect_window_at_physical_point",
    "enumerate_capturable_windows",
    "clip_window_bounds_to_monitor",
    "validate_hotkey_assignments",
]
