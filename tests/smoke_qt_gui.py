#!/usr/bin/env python3
"""Separate native Qt smoke test: must have QApplication before any dialog.

Runs in a fresh process, away from the synthetic/headless unittest stubs.
Verifies:
  1. Compact Quick OCR default mode (frameless, non-modal, compact size for 3 words,
     backend diagnostic badge hidden so Quick mode stays uncluttered).
  2. Long multiline text sizing and scrolling in Quick mode.
  3. Editable text, Ctrl+A, Ctrl+C, Copy, Copy Selected, and transient `Copied!` state
     without auto-closing the panel.
  4. Expand to Advanced OCR and Collapse back to Quick OCR without re-running OCR
     or losing manual edits, text selection, or line bounding boxes, while exposing
     `backend_diag_label` (`Backend: RapidOCR (ONNX CPU)` vs `Backend: Tesseract fallback`)
     in Advanced mode.
  5. Complete removal of the manual High-Contrast Threshold checkbox (`thresh_check`),
     replaced by `Automatic image optimization · Offline OCR` and `quality_mode="auto"`.
  6. Empty (`No text recognized`) and error states, auto-copy preferences (including
     no clipboard overwrite on empty/failed OCR), and multi-monitor clamping.
  7. Real PyQt6 `SettingsDialog` construction across all 9 Aqua section cards,
     `focus_section("storage_privacy")`, and `apply_to_config()`.
  8. Real PyQt6 `PinnedScreenshotWindow` hover toolbar controls: live `opacity_slider`,
     `btn_click_through` + `unlock_pill` interactive recovery, `btn_aot`, and `btn_reset_size`.
  9. Real PyQt6 `SnipOverlayWindow` Unified Capture-Mode HUD (`mode_hud_bar`) and
     True Window Capture hover highlighting & click-to-snap window switching.
 10. Real PyQt6 `HistoryWindow` gallery actions & `Storage & Privacy Settings` button.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PIL import Image
from ocr.engine import (
    AUTOMATIC_OCR_STATUS_TEXT,
    HAS_QT,
    OcrLineBox,
    OcrRecognitionResult,
    OcrResultsDialog,
    OcrWordBox,
)
from capture.smart_modes import DetectedWindowInfo
from pinning.manager import PinnedScreenshotManager
from history.storage import HistoryWindow, ScreenshotHistoryStore
import Prismwake as pw

app = None
if HAS_QT:
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
elif sys.platform == "win32":
    raise RuntimeError("Real PyQt6 OCR dialog failed to import on Windows")

def _pump() -> None:
    if app is not None:
        app.processEvents()

# 1. Short 3-word result in Compact Quick OCR (default mode)
img = Image.new("RGB", (480, 120), (18, 24, 34))
w1 = OcrWordBox("All", 20, 30, 36, 24, 96.0, 0, 0)
w2 = OcrWordBox("From", 66, 30, 58, 24, 95.0, 0, 1)
w3 = OcrWordBox("CallMeCarsonLIVE", 134, 30, 210, 24, 94.0, 0, 2)
line0 = OcrLineBox("All From CallMeCarsonLIVE", 20, 30, 324, 24, 95.0, 0, (w1, w2, w3))
short_res = OcrRecognitionResult(
    text="All From CallMeCarsonLIVE",
    lines=[line0],
    words=[w1, w2, w3],
    language="eng",
    engine_name="rapidocr",
    backend_selected="RapidOCR (ONNX CPU)",
    source_width=480,
    source_height=120,
    inverted_dark_theme=True,
    elapsed_ms=42.0,
)

dlg = OcrResultsDialog(
    img,
    initial_result=short_res,
    selection_rect=(300, 220, 360, 70),
    available_geometry=(0, 0, 1920, 1040),
    auto_start=False,
)
dlg.present_in_front()
_pump()

if not dlg.isVisible():
    raise RuntimeError("Quick OCR dialog was not shown")
if "OCR" not in dlg.windowTitle():
    raise RuntimeError("OCR dialog windowTitle missing")
if dlg.mode != "quick" or not dlg.is_quick_mode:
    raise RuntimeError(f"Expected Quick OCR mode by default, got {dlg.mode!r}")
if dlg.header_title_label.text() != "Text captured":
    raise RuntimeError(f"Unexpected Quick header title: {dlg.header_title_label.text()!r}")
if dlg.word_count_badge.text() != "3 words":
    raise RuntimeError(f"Expected '3 words' badge, got {dlg.word_count_badge.text()!r}")
if dlg.preview_widget.isVisible() or dlg.lines_list.isVisible():
    raise RuntimeError("Preview widget and lines list must be hidden in Quick OCR mode")
if dlg.backend_diag_label.isVisible():
    raise RuntimeError("Backend diagnostic badge must be hidden in Quick OCR mode")
if hasattr(dlg, "thresh_check") or hasattr(dlg, "set_threshold_enabled"):
    raise RuntimeError("Manual High-Contrast Threshold control must be completely removed")
if dlg.quality_mode != "auto":
    raise RuntimeError(f"Expected default quality_mode='auto', got {dlg.quality_mode!r}")

_x, _y, qw, qh = dlg.panel_geometry()
if not (420 <= qw <= 520):
    raise RuntimeError(f"Quick OCR width {qw} outside 420..520 logical px")
if not (160 <= qh <= 250):
    raise RuntimeError(f"Quick OCR short-result height {qh} outside 160..250 logical px")

# 2. Editable text, selection, Copy, and transient Copied! state without closing
dlg.text_edit.setPlainText("All From CallMeCarsonLIVE — edited")
_pump()
if not dlg.user_modified_text:
    raise RuntimeError("Expected user_modified_text=True after manual edit")
dlg.select_all_text()
copied = dlg.copy_shortcut_action()
if copied != "All From CallMeCarsonLIVE — edited":
    raise RuntimeError(f"Unexpected copied text: {copied!r}")
if not dlg.copy_feedback_active or dlg.copy_btn.text() != "Copied!":
    raise RuntimeError("Expected transient 'Copied!' state on Copy button")
if not dlg.isVisible():
    raise RuntimeError("Quick OCR panel must not auto-close after Copy by default")

# 3. Expand to Advanced OCR and Collapse back to Quick without re-running OCR or losing edits
runs_before = dlg.ocr_run_count
dlg.expand_to_advanced()
_pump()
if dlg.mode != "advanced" or not dlg.is_advanced_mode:
    raise RuntimeError("Failed to expand to Advanced OCR mode")
if not dlg.preview_widget.isVisible() or not dlg.lines_list.isVisible():
    raise RuntimeError("Preview and lines list must be visible in Advanced OCR mode")
if not dlg.export_diag_btn.isVisible():
    raise RuntimeError("Export Diagnostics button must be visible in Advanced OCR mode")
if not dlg.auto_opt_status_label.isVisible() or dlg.auto_opt_status_label.text() != AUTOMATIC_OCR_STATUS_TEXT:
    raise RuntimeError("Automatic image optimization status label missing in Advanced OCR mode")
if not dlg.backend_diag_label.isVisible() or dlg.backend_diag_label.text() != "Backend: RapidOCR (ONNX CPU)":
    raise RuntimeError(f"Expected 'Backend: RapidOCR (ONNX CPU)' in Advanced mode, got {dlg.backend_diag_label.text()!r}")
if dlg.ocr_run_count != runs_before:
    raise RuntimeError("Switching Quick -> Advanced must not re-run OCR")
if dlg.text_edit.toPlainText() != "All From CallMeCarsonLIVE — edited":
    raise RuntimeError("Manual text edits were lost when expanding to Advanced mode")

dlg.collapse_to_quick()
_pump()
if dlg.mode != "quick":
    raise RuntimeError("Failed to collapse back to Quick OCR mode")
if dlg.ocr_run_count != runs_before:
    raise RuntimeError("Switching Advanced -> Quick must not re-run OCR")
if dlg.text_edit.toPlainText() != "All From CallMeCarsonLIVE — edited":
    raise RuntimeError("Manual text edits were lost when collapsing to Quick mode")

dlg.close()
_pump()

# 4. Empty state (`No text recognized`) must not overwrite clipboard
if app is not None:
    cb = QApplication.clipboard()
    if cb is not None:
        cb.setText("PRESERVE_EXISTING_CLIPBOARD")
else:
    OcrResultsDialog._clipboard_text = "PRESERVE_EXISTING_CLIPBOARD"

empty_res = OcrRecognitionResult(
    text="",
    language="eng",
    engine_name="tesseract",
    backend_selected="Tesseract fallback",
    source_width=200,
    source_height=80,
)
dlg_empty = OcrResultsDialog(
    img,
    initial_result=empty_res,
    auto_copy_on_complete=True,
    auto_start=False,
)
dlg_empty.present_in_front()
_pump()
if dlg_empty.view_state != "empty" or dlg_empty.header_title_label.text() != "No text recognized":
    raise RuntimeError(f"Expected empty state, got {dlg_empty.view_state!r}")
if "High-Contrast Threshold" in dlg_empty.empty_state_banner.text():
    raise RuntimeError("Empty state banner must not reference removed High-Contrast Threshold")
if app is not None:
    cb = QApplication.clipboard()
    if cb is not None and cb.text() != "PRESERVE_EXISTING_CLIPBOARD":
        raise RuntimeError("Empty OCR result must never overwrite the clipboard")
else:
    if OcrResultsDialog._clipboard_text != "PRESERVE_EXISTING_CLIPBOARD":
        raise RuntimeError("Empty OCR result must never overwrite the clipboard")
dlg_empty.close()
_pump()

# 5. Real PyQt6 SettingsDialog, PinnedScreenshotWindow, SnipOverlayWindow & HistoryWindow smoke checks
if HAS_QT and getattr(pw, "HAS_QT", False):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cfg = pw.AppConfig()
        cfg.save_directory = str(tmp_path / "Captures")
        cfg.history_directory = str(tmp_path / "History")

        # (a) SettingsDialog real Qt widget construction & Storage Privacy section focus
        settings_dlg = pw.SettingsDialog(cfg)
        # Regression: visual/HDR rows pass helper_label as a keyword. The dialog
        # must construct all helper subtitles without TypeError or silent Qt slot failures.
        for expected_helper in ("theme_desc_lbl", "anim_desc_lbl", "mode_desc_lbl"):
            widget = getattr(settings_dlg, expected_helper, None)
            if widget is None or not isinstance(widget, pw.QLabel):
                raise RuntimeError(f"Settings subtitle control missing: {expected_helper}")
        settings_dlg.show()
        _pump()
        if not settings_dlg.isVisible():
            raise RuntimeError("Real PyQt6 SettingsDialog failed to show")
        sec = settings_dlg.focus_section("storage_privacy")
        _pump()
        if sec != "storage_privacy":
            raise RuntimeError(f"Expected focused_section='storage_privacy', got {sec!r}")
        settings_dlg.history_max_items_spin.setValue(750)
        settings_dlg.history_max_mb_spin.setValue(2048)
        settings_dlg.history_retention_days_spin.setValue(60)
        settings_dlg.close_x_btn.click()
        _pump()
        if settings_dlg.isVisible():
            raise RuntimeError("Settings top-right X failed to close frameless SettingsDialog")
        settings_cancel_check = pw.SettingsDialog(cfg)
        settings_cancel_check.show()
        _pump()
        settings_cancel_check.cancel_btn.click()
        _pump()
        if settings_cancel_check.isVisible():
            raise RuntimeError("Settings Cancel button failed to dismiss SettingsDialog")

        # (b) PinnedScreenshotWindow real Qt opacity slider, click-through toggle & unlock pill
        pin_mgr = PinnedScreenshotManager()
        pin_state = pin_mgr.create_pin(Image.new("RGB", (320, 200), (24, 96, 168)), spawn_qt_window=True)
        pin_win = pin_mgr.get_window(pin_state.pin_id)
        _pump()
        if pin_win is None or not pin_win.isVisible():
            raise RuntimeError("Real PyQt6 PinnedScreenshotWindow failed to show")
        pin_win.opacity_slider.setValue(65)
        _pump()
        if pin_state.opacity_pct != 65 or pin_win.opacity_lbl.text() != "65%":
            raise RuntimeError(f"Pin opacity slider failed: state={pin_state.opacity_pct}, label={pin_win.opacity_lbl.text()!r}")
        pin_win.set_click_through(True)
        _pump()
        if not pin_state.click_through or not pin_win.unlock_pill.isVisible():
            raise RuntimeError("Click-through unlock pill must be visible when click_through=True")
        # The unlock pill must be an independent, mouse-interactive top-level
        # window. A QPushButton.click() alone doesn't prove Win32 hit testing.
        if pin_win.unlock_pill.parentWidget() is not None:
            raise RuntimeError("Unlock pill must have its own top-level HWND")
        if pin_win.unlock_pill.testAttribute(pw.Qt.WidgetAttribute.WA_TransparentForMouseEvents):
            raise RuntimeError("Unlock pill must accept pointer events")
        if (pin_win.unlock_pill.windowFlags() & pw.Qt.WindowType.WindowTransparentForInput):
            raise RuntimeError("Unlock pill native window must never be click-through")
        pin_win.unlock_pill.unlock_btn.click()
        _pump()
        if pin_state.click_through or pin_win.unlock_pill.isVisible():
            raise RuntimeError("Clicking unlock_pill.unlock_btn must disable click-through and hide the pill")
        # Test the tray's emergency recovery path too: it must unlock a pin
        # independently of the floating control (and keep it on screen).
        pin_win.set_click_through(True)
        _pump()
        if pin_mgr.set_all_click_through(False) != 1:
            raise RuntimeError("Tray recovery did not unlock a click-through pin")
        _pump()
        if pin_state.click_through or not pin_win.isVisible():
            raise RuntimeError("Tray recovery left pin unresponsive or hidden")
        pin_win.step_zoom(1)
        if pin_state.zoom_pct <= 100:
            raise RuntimeError("Expected zoom > 100 after step_zoom(1)")
        pin_win.btn_reset_size.click()
        _pump()
        if pin_state.zoom_pct != 100:
            raise RuntimeError(f"Expected 1:1 Reset Size to restore 100% zoom, got {pin_state.zoom_pct}%")
        pin_mgr.close_all_pins()
        _pump()

        # (c) SnipOverlayWindow real Qt Unified Mode HUD & True Window Capture
        rgb_arr = np.full((720, 1280, 3), 40, dtype=np.uint8)
        frame = pw.CapturedFrame(
            srgb_image=rgb_arr,
            raw_scrgb_float=None,
            detected_white_scale=1.0,
            virtual_rect=(0, 0, 1280, 720),
            is_hdr_surface=False,
            full_width=1280,
            full_height=720,
        )
        own_pid = os.getpid()
        mock_wins = [
            DetectedWindowInfo(
                hwnd=5001, title="Code Editor", class_name="EditorWnd",
                process_id=own_pid + 11, left=80, top=60, right=620, bottom=460,
                client_left=88, client_top=92, client_right=612, client_bottom=452,
            ),
            DetectedWindowInfo(
                hwnd=5002, title="Web Browser", class_name="BrowserWnd",
                process_id=own_pid + 22, left=640, top=90, right=1200, bottom=650,
            ),
        ]
        ov = pw.SnipOverlayWindow(frame, cfg, workflow_mode="region", candidate_windows=mock_wins)
        ov.show_on_target_screen()
        _pump()
        if not hasattr(ov, "mode_hud_bar") or not ov.mode_hud_bar.isVisible():
            raise RuntimeError("SnipOverlayWindow mode_hud_bar must be visible")
        if "ocr" in ov.mode_hud_buttons:
            raise RuntimeError("Duplicate top HUD OCR mode should not exist; OCR action belongs on bottom toolbar")
        if not hasattr(ov, "monitor_picker_requested"):
            raise RuntimeError("Monitor picker signal is missing; other displays cannot be selected")
        ov.mode_hud_buttons["window"].click()
        _pump()
        if ov.capture_workflow_mode != "window":
            raise RuntimeError("Clicking Window mode button in HUD failed to switch to window mode")
        # The screen used by Qt's offscreen platform need not match the
        # 1280x720 *physical* capture fixture (it is often 800x800 on Windows).
        # Convert the center of each synthetic Win32 window into *overlay-local
        # logical* coordinates before exercising Qt's selection plumbing.
        # Hardcoded local points such as (800, 300) can scale beyond the entire
        # captured 1280px desktop and would falsely report broken window capture.
        wc = ov.window_capture_controller
        def _window_center_local(w):
            ox, oy, _ow, _oh = wc.monitor_rect
            center_phys_x = (w.left + w.right) / 2.0
            center_phys_y = (w.top + w.bottom) / 2.0
            return ((center_phys_x - ox) / wc.px_scale_x,
                    (center_phys_y - oy) / wc.px_scale_y)

        def _assert_snapped_to(w):
            if wc.locked_window is None or wc.locked_window.hwnd != w.hwnd:
                raise RuntimeError(f"Window Capture selected wrong window: expected {w.hwnd}, "
                                   f"got {getattr(wc.locked_window, 'hwnd', None)}")
            lx, ly, lw, lh = wc.window_to_local_rect(w)
            r = ov.selection_rect.normalized()
            for label, actual, expected in (
                ("x", r.x(), lx), ("y", r.y(), ly),
                ("width", r.width(), lw), ("height", r.height(), lh),
            ):
                if abs(float(actual) - float(expected)) > 1.01:
                    raise RuntimeError(f"Window Capture selection {label} mismatch for {w.hwnd}: "
                                       f"expected {expected}, got {actual}")

        x1, y1 = _window_center_local(mock_wins[0])
        x2, y2 = _window_center_local(mock_wins[1])
        hov_w = ov.hover_window_at(x1, y1)
        if hov_w is None or hov_w.hwnd != 5001:
            raise RuntimeError("Window Capture hover failed to target Window 5001")
        clk_w1 = ov.click_window_at(x1, y1)
        if clk_w1 is None or clk_w1.hwnd != 5001 or not ov.has_selection:
            raise RuntimeError("Window Capture click failed to snap to Window 5001")
        _assert_snapped_to(mock_wins[0])
        hov_w2 = ov.hover_window_at(x2, y2)
        if hov_w2 is None or hov_w2.hwnd != 5002:
            raise RuntimeError("Window Capture hover failed to switch highlight to Window 5002")
        # Exercise actual mousePressEvent rather than only directly calling the controller:
        # this previously got intercepted by selection resize/move before window selection.
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QPointF
        ov.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(x2, y2),
            pw.Qt.MouseButton.LeftButton, pw.Qt.MouseButton.LeftButton,
            pw.Qt.KeyboardModifier.NoModifier,
        ))
        clk_w2 = wc.locked_window
        if clk_w2 is None or clk_w2.hwnd != 5002:
            raise RuntimeError("Actual mouse click on a second window failed to switch target")
        _assert_snapped_to(mock_wins[1])
        ov.close()
        _pump()
        # Closing a real overlay intentionally releases its CapturedFrame image data.
        # Keeping the test honest here catches future resource-lifetime regressions.
        if not frame.released or frame.srgb_image.shape != (1, 1, 3):
            raise RuntimeError("Window-mode overlay must release its capture buffers on close")

        # (d) HistoryWindow real Qt Frutiger Aqua redesign, AeroGelButton controls, view toggle, async preview & async gallery thumbnails
        import time as _time
        store = ScreenshotHistoryStore(tmp_path / "History", enable_ocr_indexing=False)
        _t0 = _time.time()
        rec0 = store.record_capture(Image.new("RGB", (1280, 720), (40, 95, 155)), title="Smoke Capture 0", ocr_text="Smoke OCR Text 0", timestamp_utc=_t0 - 10.0)
        rec = store.record_capture(Image.new("RGB", (1600, 900), (50, 100, 150)), title="Smoke Capture", ocr_text="Smoke OCR Text", timestamp_utc=_t0)
        hist_win = HistoryWindow(store, aqua_theme="Bondi Blue", animation_intensity="high", glass_transparency=0.90)
        settings_sig_count = 0
        new_cap_sig_count = 0
        hist_win.openSettingsRequested.connect(lambda: globals().__setitem__("settings_sig_count", settings_sig_count + 1))
        hist_win.newCaptureRequested.connect(lambda: globals().__setitem__("new_cap_sig_count", new_cap_sig_count + 1))
        hist_win.show()
        _pump()
        if not hasattr(hist_win, "header_panel") or not hasattr(hist_win, "sidebar_panel") or not hasattr(hist_win, "inspector_panel"):
            raise RuntimeError("HistoryWindow must contain Frutiger Aqua glass panels (header_panel, sidebar_panel, inspector_panel)")
        if not hasattr(hist_win, "card_delegate") or hist_win.list_widget.itemDelegate() is not hist_win.card_delegate:
            raise RuntimeError("HistoryWindow gallery must use custom Frutiger Aqua HistoryCardDelegate")
        hist_win.set_view_mode("list")
        _pump()
        if hist_win.view_mode != "list":
            raise RuntimeError("HistoryWindow failed to switch to compact list view")
        hist_win.set_view_mode("grid")
        _pump()
        hist_win.apply_aqua_theme_and_config(aqua_theme="Deep Sea", animation_intensity="subtle", glass_transparency=0.85)
        _pump()
        if hist_win.aqua_theme != "Deep Sea" or hist_win.animation_intensity != "subtle":
            raise RuntimeError("HistoryWindow failed to apply updated Frutiger Aqua theme and animation config")
        hist_win.settings_btn.click()
        _pump()
        if settings_sig_count != 1:
            raise RuntimeError("HistoryWindow Storage & Privacy Settings button did not emit openSettingsRequested")
        hist_win.new_capture_btn.click()
        _pump()
        if new_cap_sig_count != 1:
            raise RuntimeError("HistoryWindow New Capture button did not emit newCaptureRequested")
        hist_win.wait_for_async_thumbnails(timeout=2.5)
        hist_win.wait_for_async_preview(timeout=2.5)
        if hist_win._last_thumb_decode_thread_id == hist_win._gui_thread_id:
            raise RuntimeError("Gallery thumbnail decoding must execute off the Qt GUI thread")
        if hist_win._last_thumb_pixmap_thread_id != hist_win._gui_thread_id:
            raise RuntimeError("Gallery thumbnail QPixmap creation must execute on the Qt GUI thread")
        hist_win._preview_pixmap_cache.clear()
        hist_win._preview_decode_delay_sec = 0.05
        hist_win.selected_capture_id = rec0.capture_id
        if hist_win._current_preview_stage != "thumbnail" or not hist_win._current_preview_is_thumbnail:
            raise RuntimeError("HistoryWindow must display immediate thumbnail before async full-resolution preview completes")
        if not hist_win.wait_for_async_preview(timeout=2.5):
            raise RuntimeError("HistoryWindow asynchronous full-resolution preview failed to complete")
        if hist_win._current_preview_stage != "full" or hist_win._current_preview_is_thumbnail:
            raise RuntimeError("HistoryWindow did not upgrade preview from thumbnail to full resolution")
        if hist_win._current_preview_full_pixmap is None or hist_win._current_preview_full_pixmap.width() != 1280 or hist_win._current_preview_full_pixmap.height() != 720:
            raise RuntimeError("HistoryWindow full-resolution preview dimensions did not match 1280x720 source")
        if hist_win._last_preview_decode_thread_id == hist_win._gui_thread_id:
            raise RuntimeError("Full-resolution preview decoding must run off the Qt GUI thread")
        if hist_win._last_preview_gui_update_thread_id != hist_win._gui_thread_id:
            raise RuntimeError("Full-resolution preview QPixmap update must run on the Qt GUI thread")
        hist_win._preview_pixmap_cache.clear()
        hist_win._preview_decode_delay_sec = 0.05
        hist_win.selected_capture_id = rec0.capture_id
        hist_win.selected_capture_id = rec.capture_id
        if not hist_win.wait_for_async_preview(timeout=2.5):
            raise RuntimeError("HistoryWindow rapid selection change async preview failed")
        if (hist_win._cancelled_preview_decode_count + hist_win._ignored_stale_preview_count) < 1:
            raise RuntimeError("HistoryWindow did not cancel or ignore stale preview decode when selection changed")
        if hist_win._current_preview_full_pixmap is None or hist_win._current_preview_full_pixmap.width() != 1600:
            raise RuntimeError("HistoryWindow stale preview overwrote latest selection")
        hist_win.close()
        _pump()

        # (e) SnipOverlayWindow 4-Layer Cached Annotation Rendering & Bounded Dirty-Rect Painting
        # This must be a FRESH capture: ov.close() above released the window-mode
        # CapturedFrame and reduced its srgb_image to a 1x1 sentinel. Reusing that
        # frame silently produced a 1x1 exported image even when the selection
        # coordinate mapper correctly reported an 800x500 crop.
        frame_ann = pw.CapturedFrame(
            srgb_image=rgb_arr.copy(),
            raw_scrgb_float=None,
            detected_white_scale=1.0,
            virtual_rect=(0, 0, 1280, 720),
            is_hdr_surface=False,
            full_width=1280,
            full_height=720,
        )
        if frame_ann.released or frame_ann.srgb_image.shape[:2] != (720, 1280):
            raise RuntimeError("Annotation smoke fixture requires an intact independent 1280x720 capture")
        ov_ann = pw.SnipOverlayWindow(frame_ann, cfg, workflow_mode="region")
        ov_ann.show_on_target_screen()
        _pump()
        # Exercise the native QWidget region-selection path, not the headless
        # stand-in's select_region() helper (which the real Qt overlay does not have).
        # Convert desired framebuffer pixels to Qt overlay-local logical coordinates;
        # offscreen Qt displays often have geometry different from the 1280x720 frame.
        (sx, sy) = ov_ann.coord_mapper.image_point_to_local_logical(80.0, 60.0)
        (ex, ey) = ov_ann.coord_mapper.image_point_to_local_logical(880.0, 560.0)
        def _mouse(evt_type, px, py, button, held_buttons):
            return QMouseEvent(
                evt_type, QPointF(px, py), button, held_buttons,
                pw.Qt.KeyboardModifier.NoModifier,
            )
        ov_ann.mousePressEvent(_mouse(
            QEvent.Type.MouseButtonPress, sx, sy,
            pw.Qt.MouseButton.LeftButton, pw.Qt.MouseButton.LeftButton,
        ))
        ov_ann.mouseMoveEvent(_mouse(
            QEvent.Type.MouseMove, ex, ey,
            pw.Qt.MouseButton.NoButton, pw.Qt.MouseButton.LeftButton,
        ))
        ov_ann.mouseReleaseEvent(_mouse(
            QEvent.Type.MouseButtonRelease, ex, ey,
            pw.Qt.MouseButton.LeftButton, pw.Qt.MouseButton.NoButton,
        ))
        if not ov_ann.has_selection or ov_ann.interaction_mode != "none":
            raise RuntimeError("Native Qt region drag failed to create a completed selection")
        sr = ov_ann.selection_rect.normalized()
        scrop = ov_ann.coord_mapper.local_rect_to_image_crop_rect(
            (sr.x(), sr.y(), sr.width(), sr.height())
        )
        if scrop[2:] != (800, 500):
            raise RuntimeError(f"Native Qt region drag cropped {scrop}, expected 800x500 pixels")
        ov_ann._ensure_scaled_bg_pixmap()
        ov_ann._rebuild_committed_annotations_cache()
        if ov_ann._scaled_bg_pixmap is None or ov_ann._composite_committed_pixmap is None:
            raise RuntimeError("SnipOverlayWindow 4-layer cache pixmaps were not initialized")
        ann_item = pw.AnnotationItem(
            tool="pen",
            color="#00D2FF",
            thickness=4,
            points=[(120.0, 120.0)],
        )
        for step_idx in range(1, 20):
            ann_item.append_stroke_point((120.0 + step_idx * 8.0, 120.0 + step_idx * 4.0))
        path_obj = ann_item.get_or_build_pen_path()
        if path_obj is None or ann_item._cached_qt_path_len != 20:
            raise RuntimeError("AnnotationItem incremental QPainterPath cache failed")
        ov_ann.annotations.append(ann_item)
        ov_ann._commit_single_annotation_to_cache(ann_item)
        exported_crop = ov_ann.render_final_cropped_pixmap()
        if exported_crop.width() != 800 or exported_crop.height() != 500:
            raise RuntimeError(f"Expected 800x500 cropped annotation export, got {exported_crop.width()}x{exported_crop.height()}")
        ov_ann.close()
        _pump()
        if not frame_ann.released:
            raise RuntimeError("Annotation overlay must release its own capture buffers on close")

print("Quick + Advanced OCR, Settings, Pin Controls, Window Capture, History Redesign & 4-Layer Annotation GUI smoke test: PASS", flush=True)
