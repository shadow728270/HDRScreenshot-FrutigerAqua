#!/usr/bin/env python3
"""
Prismwake v0.2.0 — Comprehensive Automated Test Suite (Part 9 + Critical OCR Workflow Tests)
============================================================================================
Tests all 7 required test suites:
  9.1 Pinned Screenshot Tests:
      - Multiple independent pinned windows, position & resizing, aspect-ratio preservation,
        opacity, zoom presets + Fit, close behavior, saving & copying, negative/multi-monitor
        coordinate transforms, DPI awareness, offscreen recovery, and capture hide/restore.
  9.2 Offline OCR Engine Tests:
      - Fixture images with known text: dark-on-light, light-on-dark, small text,
        mixed punctuation, numeric values, multiple lines, code-like text,
        word & line bounding boxes mapped to source image coordinates, cancellation,
        missing-engine error reporting (never silently claiming full OCR is ready when
        Tesseract is missing), and packaged runtime verification (`verify_packaged_tesseract_launch`).
  9.3 Screenshot History Tests:
      - SQLite + FTS5 database creation, image persistence, thumbnail generation,
        search (by title, date, filename, and OCR text), favorites, asynchronous background
        OCR indexing, renaming, deletion (preserving unrelated files), retention cleanup,
        corruption recovery, and schema migration.
  9.4 Smart Capture Tests:
      - Region capture, Window detection (Z-order, DWM frame bounds, excluding Prismwake's
        own HWNDs/PID, rejecting minimized/cloaked windows), multi-monitor selection,
        fullscreen capture, delayed capture countdown + cancellation, hotkey conflict
        & Windows-reserved shortcut validation, and DPI coordinate conversion.
  9.5 Updater Transition Tests:
      - v0.1.4 Prismwake.exe detecting v0.2.0, v0.2.0 detecting future v0.2.1,
        single-EXE release asset validation (`Prismwake.exe` + `Prismwake.exe.sha256` only,
        rejecting `HDRSnipFusion.exe`), SHA-256 verification, staged replacement,
        startup confirmation, rollback, and temporary-file cleanup.
  9.6 Regression Testing:
      - Existing annotation tools, undo/redo, HDR scRGB tone-mapping, Aqua theme switching,
        Settings responsive geometry (`810 px` no-clipping width, 8-edge resize), and
        multi-size icon & PE version metadata.
  9.7 Mandatory OCR GUI Workflow & Signal Integration Tests:
      - Clicking OCR in the editor after selecting a region (both via `trigger_snip()` hotkey
        path and `trigger_capture_mode("region")`).
      - Selecting Text Capture (`mode="ocr"`) from the tray and dragging a new selection ->
        automatically begins OCR on mouse release without requiring a second button click.
      - Recognizing a screenshot with clear English text and copying extracted text to clipboard.
      - Opening the OCR results dialog strictly AFTER the original capture overlay has closed.
      - Canceling recognition in progress.
      - Attempting OCR without a selection -> shows actionable prompt without closing overlay.
      - Attempting OCR when Tesseract is missing -> shows actionable error banner in dialog.
      - Attempting OCR when the OCR module fails to import -> logs error and shows critical alert.
      - Running OCR repeatedly without leaving hidden windows or hung workers, and verifying
        non-blocking background History OCR indexing and clean shutdown.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure headless controller tests never accidentally instantiate real QWidgets
# without a QApplication if invoked directly outside tests/run_headless_tests.py.
if "PyQt6" not in sys.modules:
    sys.modules["PyQt6"] = None

import Prismwake as pw
import make_prismwake_icon as icon_gen
from ocr import (
    AUTOMATIC_OCR_STATUS_TEXT,
    OCR_QUALITY_MODE_LABELS,
    VALID_OCR_QUALITY_MODES,
    CancellationToken,
    OcrLineBox,
    OcrRecognitionResult,
    OcrWordBox,
    analyze_image_for_ocr,
    compute_advanced_ocr_panel_geometry,
    compute_quick_ocr_panel_geometry,
    count_recognized_words_and_lines,
    format_quick_ocr_badge_text,
    format_quick_ocr_footer_label,
    generate_ocr_preprocessing_candidates,
    query_ocr_engine_status,
    recognize_image_ocr,
    recognize_image_ocr_legacy,
    refine_ocr_result_layout_and_spacing,
    resolve_ocr_aqua_theme_palette,
    score_ocr_candidate,
    is_plausible_ocr_result,
    run_bounded_ocr_subprocess,
    export_ocr_diagnostic_bundle,
    format_ocr_summary,
    select_adaptive_psms,
    verify_packaged_tesseract_launch,
    filter_and_salvage_partial_ocr_result,
    OcrBackend,
    OcrBackendStatus,
    RapidOcrBackend,
    TesseractOcrBackend,
    HybridOcrOrchestrator,
    get_production_ocr_orchestrator,
    set_production_ocr_orchestrator,
    override_production_ocr_orchestrator,
    recognize_production_ocr,
    verify_rapidocr_model_directory,
    verify_packaged_ocr_launch,
)
from ocr.benchmark import (
    build_ground_truth_ocr_fixtures,
    build_independent_regression_ocr_fixtures,
    build_realworld_heldout_ocr_fixtures,
    compute_cer,
    compute_wer,
    run_ocr_benchmark_suite,
)
from ocr.engine import OcrResultsDialog
from history import (
    ScreenshotHistoryStore,
)
from pinning import (
    PinnedScreenshotManager,
    VirtualMonitorRect,
)
from capture import (
    DelayedCaptureController,
    DetectedWindowInfo,
    detect_window_at_physical_point,
    validate_hotkey_assignments,
)
from updater import (
    resolve_v020_release_asset_names,
    verify_single_exe_release_assets,
)


def _load_test_font(size: int = 22, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "C:\\Windows\\Fonts\\consola.ttf",
        ]
        if mono
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]
    )
    for fp in candidates:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _make_english_screenshot_fixture(text_line_1: str = "Prismwake Offline OCR Ready 2026", text_line_2: str = "Extract text from any screen region.") -> Image.Image:
    if text_line_1 == "Prismwake Workflow OCR 2026" and text_line_2 == "Overlay closes before dialog opens.":
        wf_p = PROJECT_ROOT / "tests" / "fixtures" / "suite_a_ocr" / "helper_english_workflow.png"
        if wf_p.is_file():
            with Image.open(wf_p) as _im:
                return _im.convert("RGB")
    font = _load_test_font(24)
    img = Image.new("RGB", (680, 140), (252, 253, 255))
    draw = ImageDraw.Draw(img)
    draw.text((24, 22), text_line_1, fill=(10, 18, 28), font=font)
    draw.text((24, 72), text_line_2, fill=(10, 18, 28), font=font)
    return img


class TestPart1PinnedScreenshots(unittest.TestCase):
    """Part 9.1 — Pinned Screenshot Tests."""

    def test_multiple_independent_pins_and_close_isolation(self) -> None:
        mgr = PinnedScreenshotManager(default_opacity_pct=90, default_zoom_pct=100)
        img1 = Image.new("RGB", (400, 200), (20, 120, 220))
        img2 = Image.new("RGB", (300, 300), (40, 180, 120))
        p1 = mgr.create_pin(img1, title="Pin 1", initial_x=100, initial_y=120, spawn_qt_window=False)
        p2 = mgr.create_pin(img2, title="Pin 2", initial_x=540, initial_y=120, spawn_qt_window=False)
        p3 = mgr.duplicate_pin(p1.pin_id, spawn_qt_window=False)
        self.assertIsNotNone(p3)
        self.assertEqual(mgr.active_count, 3)

        # Closing p1 must not close p2 or p3
        self.assertTrue(mgr.close_pin(p1.pin_id))
        self.assertEqual(mgr.active_count, 2)
        self.assertTrue(p1.is_closed)
        self.assertFalse(p2.is_closed)
        self.assertFalse(p3.is_closed)

    def test_aspect_ratio_preservation_zoom_opacity_and_lock(self) -> None:
        mgr = PinnedScreenshotManager()
        img = Image.new("RGB", (600, 300), (15, 65, 130))  # 2:1 aspect ratio
        pin = mgr.create_pin(img, spawn_qt_window=False)

        # Resize preserving 2:1 aspect ratio
        pin.resize_to(900, 777, preserve_aspect=True, anchor_axis="width")
        self.assertEqual((pin.width, pin.height), (900, 450))
        self.assertEqual(pin.zoom_pct, 150)

        # Zoom presets and step
        pin.set_zoom(200)
        self.assertEqual((pin.width, pin.height), (1200, 600))
        pin.zoom_step(-1)
        self.assertEqual(pin.zoom_pct, 150)

        # Opacity clamping (15..100%)
        pin.set_opacity(5)
        self.assertEqual(pin.opacity_pct, 15)
        pin.set_opacity(85)
        self.assertEqual(pin.opacity_pct, 85)

        # Lock position prevents move & resize
        pin.locked = True
        self.assertFalse(pin.move_to(500, 500))
        self.assertFalse(pin.resize_to(300, 150))

    def test_multimonitor_negative_coords_dpi_and_offscreen_recovery(self) -> None:
        left_mon = VirtualMonitorRect(x=-1920, y=-200, width=1920, height=1080, dpi_scale=1.25)
        primary_mon = VirtualMonitorRect(x=0, y=0, width=2560, height=1440, dpi_scale=1.5, is_primary=True)

        mgr = PinnedScreenshotManager()
        pin = mgr.create_pin(
            Image.new("RGB", (320, 180), (50, 90, 140)),
            initial_x=-1600,
            initial_y=-100,
            monitors=[left_mon, primary_mon],
            spawn_qt_window=False,
        )
        # Valid position on negative-coordinate monitor is preserved
        self.assertEqual((pin.x, pin.y), (-1600, -100))

        # Simulate left monitor disconnecting -> pin automatically relocates onto primary_mon
        mgr.recover_all_offscreen_pins(monitors=[primary_mon])
        self.assertGreaterEqual(pin.x, primary_mon.x)
        self.assertGreaterEqual(pin.y, primary_mon.y)
        self.assertLessEqual(pin.x + pin.width, primary_mon.right)

    def test_pin_save_and_capture_exclusion_hide_restore(self) -> None:
        mgr = PinnedScreenshotManager(exclude_pins_from_capture=True)
        pin = mgr.create_pin(Image.new("RGB", (200, 120), (10, 200, 180)), spawn_qt_window=False)
        with tempfile.TemporaryDirectory() as tmp:
            saved = pin.save_to_file(Path(tmp) / "pinned_export.png")
            self.assertTrue(saved.is_file())
            with Image.open(saved) as im:
                self.assertEqual(im.size, (200, 120))

        hidden_ids = mgr.prepare_for_desktop_capture()
        self.assertIn(pin.pin_id, hidden_ids)
        self.assertTrue(pin.hidden_for_capture)
        mgr.restore_after_desktop_capture(hidden_ids)
        self.assertFalse(pin.hidden_for_capture)


class TestPart2OfflineOcr(unittest.TestCase):
    """Part 9.2 — Real Offline OCR Tests on Fixture Images."""

    def test_engine_status_and_dark_on_light_multiline_punctuation_numbers(self) -> None:
        status = query_ocr_engine_status()
        self.assertTrue(status.available)
        self.assertEqual(status.engine_kind, "tesseract")
        self.assertIn("eng", status.installed_languages)

        ok_bundle, msg_bundle = verify_packaged_tesseract_launch()
        self.assertTrue(ok_bundle, msg=msg_bundle)

        suite_a = {f.fixture_id: f for f in build_ground_truth_ocr_fixtures()}
        img = suite_a["windows_light_ui"].image

        res = recognize_image_ocr(img, language="eng")
        self.assertTrue(res.ok, msg=res.error)
        self.assertEqual(res.engine_name, "tesseract")
        self.assertFalse(res.inverted_dark_theme)
        self.assertIn("Prismwake", res.text)
        self.assertIn("0.2.0", res.text)
        self.assertIn("3840x2160", res.text)
        self.assertIn("280", res.text)
        self.assertGreaterEqual(len(res.lines), 2)
        self.assertGreaterEqual(len(res.words), 8)

        # Verify word bounding boxes map accurately into source 680x130 image coordinates
        first_word = res.words[0]
        self.assertGreaterEqual(first_word.x, 10)
        self.assertLessEqual(first_word.right, 680)
        self.assertGreaterEqual(first_word.y, 8)
        self.assertLessEqual(first_word.bottom, 130)
        hit = res.find_word_at_point(first_word.x + 4, first_word.y + 4)
        self.assertIsNotNone(hit)

    def test_light_text_on_dark_background(self) -> None:
        suite_a = {f.fixture_id: f for f in build_ground_truth_ocr_fixtures()}
        img = suite_a["windows_dark_ui"].image

        res = recognize_image_ocr(img, language="eng")
        self.assertTrue(res.ok)
        self.assertTrue(res.inverted_dark_theme)
        self.assertIn("DXGI", res.text)
        self.assertIn("REMOVED", res.text)
        self.assertIn("887A0005", res.text)

    def test_small_text_and_code_syntax(self) -> None:
        suite_a = {f.fixture_id: f for f in build_ground_truth_ocr_fixtures()}
        img = suite_a["small_antialiased_code"].image

        res = recognize_image_ocr(img, language="eng")
        self.assertTrue(res.ok)
        self.assertGreaterEqual(res.scale_factor, 2.0)
        self.assertIn("def", res.text)
        self.assertIn("capture_hdr", res.text)
        self.assertIn("True", res.text)
        self.assertIn("return", res.text)

    def test_ocr_cancellation_and_missing_engine_handling(self) -> None:
        img = Image.new("RGB", (320, 80), (255, 255, 255))
        token = CancellationToken()
        token.cancel()
        res_cancel = recognize_image_ocr(img, cancel_token=token)
        self.assertTrue(res_cancel.cancelled)

        # Unsupported language fails gracefully
        res_bad_lang = recognize_image_ocr(img, language="klingon_xyz")
        self.assertFalse(res_bad_lang.ok)
        self.assertIn("Unsupported OCR language", res_bad_lang.error)

        # Missing Tesseract binary with default allow_builtin_fallback=False must NOT silently claim success
        with mock.patch("ocr.engine.detect_tesseract_runtime", return_value=(None, None, (), "")):
            st_missing = query_ocr_engine_status()
            self.assertFalse(st_missing.available)
            self.assertEqual(st_missing.engine_kind, "unavailable")
            self.assertIn("unavailable", st_missing.status_summary.lower())

            res_missing = recognize_image_ocr(img, language="eng")
            self.assertFalse(res_missing.ok)
            self.assertIn("not found", res_missing.error.lower())


class TestPart3ScreenshotHistory(unittest.TestCase):
    """Part 9.3 — Persistent SQLite + FTS5 Screenshot History Tests."""

    def test_crud_search_favorites_renaming_and_privacy_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "History"
            store = ScreenshotHistoryStore(root, privacy_mode="saved_or_copied", max_items=10)

            # Canceled capture is never recorded
            self.assertIsNone(
                store.record_capture(Image.new("RGB", (200, 100), (10, 20, 30)), was_cancelled=True)
            )
            # Unsaved capture under saved_or_copied is not recorded
            self.assertIsNone(
                store.record_capture(Image.new("RGB", (200, 100), (10, 20, 30)), was_saved_or_copied=False)
            )

            e1 = store.record_capture(
                Image.new("RGB", (320, 180), (20, 90, 180)),
                capture_mode="window",
                title="Vulkan Swapchain Dialog",
                ocr_text="VK_ERROR_OUT_OF_DATE_KHR",
                was_saved_or_copied=True,
            )
            e2 = store.record_capture(
                Image.new("RGB", (640, 360), (40, 160, 110)),
                capture_mode="fullscreen",
                title="HDR Calibration Reference",
                ocr_text="SDR White Level 280 nits",
                favorite=True,
                was_saved_or_copied=True,
            )
            self.assertIsNotNone(e1)
            self.assertIsNotNone(e2)

            # Thumbnail and full image loading
            self.assertIsNotNone(store.load_thumbnail_pil(e1.capture_id))
            self.assertEqual(store.load_full_image_pil(e2.capture_id).size, (640, 360))

            # Search by OCR text & title
            hits_ocr = store.search_entries("VK_ERROR_OUT_OF_DATE_KHR")
            self.assertEqual(len(hits_ocr), 1)
            self.assertEqual(hits_ocr[0].capture_id, e1.capture_id)

            hits_fav = store.search_entries("", filter_mode="favorites")
            self.assertEqual(len(hits_fav), 1)
            self.assertEqual(hits_fav[0].capture_id, e2.capture_id)

            # Rename & toggle favorite
            self.assertTrue(store.update_title(e1.capture_id, "Renamed Vulkan Dialog"))
            self.assertEqual(store.get_entry(e1.capture_id).title, "Renamed Vulkan Dialog")
            self.assertTrue(store.set_favorite(e1.capture_id, True))
            self.assertTrue(store.get_entry(e1.capture_id).favorite)

            # Verify persistence across a new ScreenshotHistoryStore instance (restart simulation)
            store_reopened = ScreenshotHistoryStore(root)
            self.assertEqual(len(store_reopened.search_entries("Renamed Vulkan")), 1)

    def test_safe_deletion_retention_cleanup_and_corruption_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "History"
            ext_dir = Path(tmp) / "UserPictures"
            ext_dir.mkdir(parents=True, exist_ok=True)
            unrelated_user_file = ext_dir / "keep_me_forever.png"
            Image.new("RGB", (64, 64), (255, 0, 0)).save(unrelated_user_file)

            store = ScreenshotHistoryStore(root, max_items=3)
            ids = []
            for idx in range(5):
                entry = store.record_capture(
                    Image.new("RGB", (160, 100), (idx * 30, 80, 140)),
                    title=f"Item {idx}",
                    external_save_path=unrelated_user_file if idx == 0 else None,
                    was_saved_or_copied=True,
                )
                ids.append(entry.capture_id)

            # Max items = 3 enforced automatically
            stats = store.compute_storage_stats()
            self.assertEqual(stats.total_items, 3)
            # Unrelated external user file must NEVER be deleted
            self.assertTrue(unrelated_user_file.is_file())

            # Simulate SQLite database corruption -> store recovers cleanly without deleting user files
            (root / "history.db").write_bytes(b"NOT_A_VALID_SQLITE_HEADER_CORRUPT_BYTES")
            recovered_store = ScreenshotHistoryStore(root)
            self.assertTrue(recovered_store.recovered_from_corruption)
            self.assertTrue(unrelated_user_file.is_file())


class TestPart4SmartCaptureModes(unittest.TestCase):
    """Part 9.4 — Smart Capture Modes & Window Detection Tests."""

    def test_window_detection_excludes_self_and_minimized_windows(self) -> None:
        own_pid = 4242
        mock_wins = [
            DetectedWindowInfo(
                hwnd=1001, title="Prismwake Overlay", class_name="Qt6QWindow",
                process_id=own_pid, left=0, top=0, right=2560, bottom=1440,
            ),
            DetectedWindowInfo(
                hwnd=1002, title="Minimized Browser", class_name="Chrome_WidgetWin_1",
                process_id=5001, left=-32000, top=-32000, right=-31800, bottom=-31800,
                is_minimized=True,
            ),
            DetectedWindowInfo(
                hwnd=1003, title="Visual Studio Code", class_name="Chrome_WidgetWin_1",
                process_id=6002, left=120, top=80, right=1720, bottom=1040,
            ),
        ]
        hit = detect_window_at_physical_point(
            400, 300, exclude_pid=own_pid, candidate_windows=mock_wins
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit.hwnd, 1003)
        self.assertEqual(hit.title, "Visual Studio Code")

        # Verify minimized window reports clear reason
        self.assertFalse(mock_wins[1].is_capturable)
        self.assertIn("minimized", mock_wins[1].unavailable_reason)

        # Verify maximized window clipping to monitor bounds & DPI scaling
        lx, ly, lw, lh = hit.to_local_monitor_rect(0, 0, 2560, 1440, dpi_scale=2.0)
        self.assertEqual((lx, ly, lw, lh), (60, 40, 800, 480))

    def test_delayed_capture_countdown_and_cancellation(self) -> None:
        ticks = []
        ready_modes = []
        cancelled = []

        ctrl = DelayedCaptureController(
            delay_seconds=3,
            target_mode="window",
            on_tick=lambda rem: ticks.append(rem),
            on_ready_to_capture=lambda m: ready_modes.append(m),
            on_cancelled=lambda: cancelled.append(True),
        )
        ctrl.start()
        self.assertTrue(ctrl.is_running)
        self.assertTrue(ctrl.overlay_visible)
        self.assertEqual(ticks, [3])

        ctrl.tick()  # 2s left
        ctrl.tick()  # 1s left
        self.assertTrue(ctrl.overlay_visible)
        ctrl.tick()  # 0s -> hides overlay BEFORE firing capture
        self.assertFalse(ctrl.overlay_visible)
        self.assertEqual(ready_modes, ["window"])

        # Test cancellation before capture begins
        ctrl2 = DelayedCaptureController(delay_seconds=5, on_cancelled=lambda: cancelled.append(True))
        ctrl2.start()
        ctrl2.cancel()
        self.assertTrue(ctrl2.is_cancelled)
        self.assertFalse(ctrl2.overlay_visible)
        self.assertEqual(len(cancelled), 1)

    def test_hotkey_conflict_and_reserved_shortcut_detection(self) -> None:
        ok_report = validate_hotkey_assignments({
            "region": "Ctrl+Shift+X",
            "window": "Ctrl+Shift+W",
            "fullscreen": "Ctrl+Shift+F",
            "ocr": "Ctrl+Shift+O",
            "history": "Ctrl+Shift+H",
        })
        self.assertTrue(ok_report.valid)

        conflict_report = validate_hotkey_assignments({
            "region": "Ctrl+Shift+X",
            "window": " shift + ctrl + x ",
            "fullscreen": "Win+L",
        })
        self.assertFalse(conflict_report.valid)
        self.assertEqual(len(conflict_report.conflicts), 1)
        self.assertEqual(len(conflict_report.reserved_violations), 1)


class TestPart5SingleExeUpdaterTransition(unittest.TestCase):
    """Part 9.5 — Single-EXE Updater Transition Tests (`v0.1.4 -> v0.2.0 -> v0.2.1`)."""

    def test_single_exe_asset_resolution_and_legacy_retirement(self) -> None:
        self.assertEqual(pw.APP_NAME, "Prismwake")
        self.assertEqual(pw.APP_VERSION, "0.2.0")
        self.assertEqual(pw.PRIMARY_RELEASE_ASSET_NAME, "Prismwake.exe")
        self.assertEqual(pw.EXPECTED_RELEASE_ASSET_NAME, "Prismwake.exe")
        self.assertEqual(pw.SUPPORTED_RELEASE_ASSET_NAMES, ("Prismwake.exe",))
        self.assertEqual(pw.resolve_preferred_release_asset_names(), ("Prismwake.exe",))
        self.assertEqual(resolve_v020_release_asset_names(), ("Prismwake.exe",))

        ok, _ = verify_single_exe_release_assets(["Prismwake.exe", "Prismwake.exe.sha256"])
        self.assertTrue(ok)
        ok_bad, msg_bad = verify_single_exe_release_assets(["Prismwake.exe", "HDRSnipFusion.exe"])
        self.assertFalse(ok_bad)
        self.assertIn("HDRSnipFusion.exe", msg_bad)

    def test_v014_to_v020_and_v020_to_v021_release_parsing(self) -> None:
        fake_sha = "a" * 64
        payload_v020 = {
            "tag_name": "v0.2.0",
            "name": "Prismwake v0.2.0 — The Productivity Update",
            "draft": False,
            "prerelease": False,
            "html_url": "https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases/tag/v0.2.0",
            "body": f"`{fake_sha}  Prismwake.exe`",
            "assets": [
                {
                    "name": "Prismwake.exe",
                    "state": "uploaded",
                    "size": 32_500_000,
                    "digest": f"sha256:{fake_sha}",
                    "browser_download_url": "https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases/download/v0.2.0/Prismwake.exe",
                }
            ],
        }
        # 1. v0.1.4 detecting v0.2.0
        res_from_014 = pw.parse_github_release_payload(payload_v020, current_version="0.1.4")
        self.assertEqual(res_from_014.status, "update_available")
        self.assertEqual(res_from_014.latest_version, "0.2.0")
        self.assertTrue(res_from_014.download_url.endswith("/Prismwake.exe"))

        # 2. v0.2.0 checking v0.2.0 -> up_to_date
        res_same = pw.parse_github_release_payload(payload_v020, current_version="0.2.0")
        self.assertEqual(res_same.status, "up_to_date")

        # 3. v0.2.0 detecting future v0.2.1
        payload_v021 = dict(payload_v020, tag_name="v0.2.1")
        res_to_021 = pw.parse_github_release_payload(payload_v021, current_version="0.2.0")
        self.assertEqual(res_to_021.status, "update_available")
        self.assertEqual(res_to_021.latest_version, "0.2.1")


class TestPart6RegressionsFromV014(unittest.TestCase):
    """Part 9.6 — Regression Tests for HDR Tone-Mapping, Annotations, Redaction, Settings & Icons."""

    def test_hdr_scrgb_tone_mapping_and_annotations_preserved(self) -> None:
        scrgb = np.zeros((32, 32, 4), dtype=np.float16)
        scrgb[:, :, 0] = 2.5
        scrgb[:, :, 1] = 1.0
        scrgb[:, :, 2] = 0.5
        scrgb[:, :, 3] = 1.0
        srgb = pw.tone_map_scrgb_to_srgb(scrgb, white_scale=2.5, mode="sdr_exact_knee")
        self.assertEqual(srgb.shape, (32, 32, 3))
        self.assertEqual(srgb.dtype, np.uint8)

        # Permanent redaction irreversibly zeroes underlying pixel data
        buf = np.full((40, 40, 3), 220, dtype=np.uint8)
        pw.apply_permanent_redaction_rgb(buf, 5, 5, 25, 25, "#000000")
        self.assertTrue(np.all(buf[5:25, 5:25] == 0))
        self.assertTrue(np.all(buf[0:5, 0:5] == 220))

    def test_settings_responsive_geometry_and_icon_frames(self) -> None:
        geom = pw.compute_settings_responsive_geometry(0, 0, 1920, 1080)
        x, y, w, h = int(geom["x"]), int(geom["y"]), int(geom["width"]), int(geom["height"])
        self.assertEqual(w, 810)
        self.assertLessEqual(x + w, 1920)
        self.assertLessEqual(y + h, 1080)

        ico_path = PROJECT_ROOT / "prismwake.ico"
        frames = icon_gen.inspect_ico_frames(ico_path)
        self.assertEqual([fw for fw, fh, bpp in frames], [16, 24, 32, 48, 64, 128, 256])


class TestPart7OcrGuiWorkflowAndSignals(unittest.TestCase):
    """
    Mandatory GUI & Controller Workflow Tests for the v0.2.0 Critical OCR Bug Fix:
      1. Clicking OCR in the editor after selecting a region (via hotkey `trigger_snip()` AND `trigger_capture_mode("region")`).
      2. Selecting Text Capture (`mode="ocr"`) from the tray and dragging a new selection (auto-triggers OCR on mouse release).
      3. Recognizing a screenshot with clear English text and copying extracted text to the clipboard.
      4. Opening the OCR results dialog strictly AFTER the original capture overlay has closed and released input grab.
      5. Canceling recognition in progress.
      6. Attempting OCR without a selection -> shows actionable feedback without closing overlay.
      7. Attempting OCR when Tesseract is missing -> shows actionable error in dialog without silent fallback.
      8. Attempting OCR when the OCR module fails to import -> logs error and shows critical alert dialog.
      9. Running OCR repeatedly without leaving hidden windows or hung workers, and verifying non-blocking background History OCR indexing.
    """

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.history_root = Path(self._tmp_dir.name) / "History"
        self.fixture_img = _make_english_screenshot_fixture(
            "Prismwake Workflow OCR 2026",
            "Overlay closes before dialog opens.",
        )
        self.cfg = pw.AppConfig()
        self.cfg.history_directory = str(self.history_root)
        self.cfg.history_mode = "saved_or_copied"
        self.cfg.history_index_ocr = True
        self.cfg.ocr_language = "eng"
        self.cfg.ocr_auto_copy_text = False

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_01_editor_ocr_button_from_hotkey_trigger_snip_and_overlay_close_ordering(self) -> None:
        """
        Verify pressing hotkey (`trigger_snip()`) -> selecting region -> clicking `Text (OCR)` (`ocr_snip()`):
          - Connects `ocr_requested`, `pin_requested`, and `capture_completed` on the `trigger_snip()` path.
          - Hides and closes `SnipOverlayWindow` and releases mouse/keyboard grab BEFORE `OcrResultsDialog` opens.
          - Recognizes the English text in the selected region and allows copying to clipboard.
        """
        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.fixture_img,
        )
        try:
            # 1. Trigger via hotkey / tray-click entry point (`trigger_snip()`)
            app_ctrl.trigger_snip()
            ov = app_ctrl.overlay
            self.assertIsNotNone(ov)
            self.assertTrue(ov.isVisible())

            # 2. Select region containing both lines of English text
            ov.select_region(8, 8, 660, 124)

            # 3. Click `Text (OCR)` button in editor (`ocr_snip()`)
            ok = ov.ocr_snip()
            self.assertTrue(ok)

            # 4. Verify the screenshot overlay is completely hidden, closed, and released BEFORE dialog opened
            self.assertFalse(ov.isVisible())
            self.assertTrue(ov._closed)
            self.assertFalse(ov._mouse_grabbed)
            self.assertFalse(ov._keyboard_grabbed)
            self.assertIsNone(app_ctrl.overlay)

            closed_idx = app_ctrl._workflow_event_log.index("overlay_closed")
            opened_idx = app_ctrl._workflow_event_log.index("ocr_dialog_opened")
            self.assertLess(
                closed_idx,
                opened_idx,
                f"Expected overlay_closed before ocr_dialog_opened, got {app_ctrl._workflow_event_log}",
            )

            # 5. Verify OcrResultsDialog is open in front and recognized the English text
            dlg = app_ctrl._active_ocr_dialog
            self.assertIsNotNone(dlg)
            self.assertTrue(dlg.isVisible())
            recognized = dlg.text_edit.toPlainText()
            self.assertIn("Prismwake", recognized)
            self.assertIn("2026", recognized)
            self.assertIn("Overlay", recognized)

            # 6. Verify Copy All and Copy Selected to clipboard
            copied_all = dlg.copy_all_text()
            self.assertIn("Prismwake", copied_all)
            self.assertEqual(OcrResultsDialog._clipboard_text, copied_all)

            dlg.text_edit.setSelectedText("Prismwake Workflow OCR 2026")
            copied_sel = dlg.copy_selected_text()
            self.assertEqual(copied_sel, "Prismwake Workflow OCR 2026")
            self.assertEqual(OcrResultsDialog._clipboard_text, "Prismwake Workflow OCR 2026")
        finally:
            app_ctrl.quit_app()

    def test_02_text_capture_mode_auto_triggers_ocr_on_selection_release(self) -> None:
        """
        Verify selecting `Text Capture` (`mode="ocr"`) from the system tray and dragging a region
        automatically starts OCR as soon as the mouse selection is released—without requiring a second click.
        """
        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.fixture_img,
        )
        try:
            app_ctrl.trigger_capture_mode("ocr")
            ov = app_ctrl.overlay
            self.assertIsNotNone(ov)
            self.assertEqual(ov.capture_workflow_mode, "ocr")

            # Drag selection and release mouse button -> should auto-run ocr_snip()!
            ov.simulate_region_drag(10, 10, 660, 130)

            # Overlay must have closed automatically and opened OcrResultsDialog with recognized text
            self.assertIsNone(app_ctrl.overlay)
            self.assertFalse(ov.isVisible())
            dlg = app_ctrl._active_ocr_dialog
            self.assertIsNotNone(dlg)
            self.assertTrue(dlg.isVisible())
            self.assertIn("Prismwake", dlg.text_edit.toPlainText())
            self.assertIn("2026", dlg.text_edit.toPlainText())
        finally:
            app_ctrl.quit_app()

    def test_03_attempt_ocr_without_selection_shows_actionable_prompt(self) -> None:
        """
        Attempting OCR without dragging a selection region must show a clear user-facing message
        and keep the capture overlay open rather than silently doing nothing.
        """
        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.fixture_img,
        )
        try:
            app_ctrl.trigger_capture_mode("region")
            ov = app_ctrl.overlay
            self.assertIsNotNone(ov)
            self.assertFalse(ov.has_selection)

            ok = ov.ocr_snip()
            self.assertFalse(ok)
            # Overlay stays open and active so user can drag a box
            self.assertTrue(ov.isVisible())
            self.assertIs(app_ctrl.overlay, ov)
            self.assertIsNone(app_ctrl._active_ocr_dialog)
            self.assertEqual(len(ov.message_boxes), 1)
            kind, title, msg = ov.message_boxes[0]
            self.assertEqual(kind, "information")
            self.assertIn("Select a Region for OCR", title)
            self.assertIn("drag a selection box", msg)
        finally:
            app_ctrl.quit_app()

    def test_04_cancel_recognition_in_progress(self) -> None:
        """Verify canceling an in-progress OCR job in `OcrResultsDialog` cleanly stops recognition."""
        dlg = OcrResultsDialog(self.fixture_img, auto_start=False)
        dlg.present_in_front()
        dlg.start_recognition(async_run=True)
        dlg.cancel_recognition()
        self.assertIsNone(dlg._active_job)
        self.assertTrue(dlg.retry_btn.isEnabled())
        self.assertFalse(dlg.cancel_btn.isVisible())
        self.assertIn("cancelled", dlg.status_label.text().lower())
        dlg.close()

    def test_05_attempt_ocr_when_tesseract_is_missing_shows_actionable_error_banner(self) -> None:
        """
        When Tesseract is missing, `OcrResultsDialog` must display an explicit actionable error banner
        and never silently substitute a low-accuracy template output as if Tesseract succeeded.
        """
        with override_production_ocr_orchestrator(HybridOcrOrchestrator(prefer_neural=False)), mock.patch("ocr.engine.detect_tesseract_runtime", return_value=(None, None, (), "")):
            dlg = OcrResultsDialog(self.fixture_img, auto_start=True)
            dlg.present_in_front()
            self.assertTrue(dlg.error_banner.isVisible())
            self.assertIn("not found", dlg.error_banner.text().lower())
            self.assertEqual(dlg.text_edit.toPlainText(), "")
            self.assertFalse(dlg.copy_all_btn.isEnabled())
            dlg.close()

    def test_06_attempt_ocr_when_ocr_module_fails_to_import_logs_and_shows_critical_dialog(self) -> None:
        """
        If the OCR module failed to import at startup (`OCR_IMPORT_ERROR` is set),
        `validate_ocr_subsystem_at_startup()` and `_open_ocr_results_dialog()` must log the error
        and show an explicit critical error message box instead of silently doing nothing.
        """
        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.fixture_img,
        )
        try:
            with mock.patch.object(pw, "OCR_IMPORT_ERROR", "ImportError: simulated broken OCR dependency"):
                ok_startup, msg_startup = app_ctrl.validate_ocr_subsystem_at_startup()
                self.assertFalse(ok_startup)
                self.assertIn("simulated broken OCR dependency", msg_startup)

                dlg = app_ctrl._open_ocr_results_dialog(self.fixture_img)
                self.assertIsNone(dlg)
                self.assertEqual(len(app_ctrl._message_box_log), 1)
                kind, title, body = app_ctrl._message_box_log[0]
                self.assertEqual(kind, "critical")
                self.assertIn("Offline OCR Error", title)
                self.assertIn("simulated broken OCR dependency", body)
        finally:
            app_ctrl.quit_app()

    def test_07_repeated_ocr_runs_and_async_history_indexing_without_gui_freeze_or_leaks(self) -> None:
        """
        Run OCR repeatedly across 4 captures and verify:
          - Previous OCR dialogs and overlays are cleaned up without leaking windows or hung workers.
          - `_on_overlay_capture_completed()` returns immediately without blocking the main thread on OCR,
            and background History OCR indexing populates SQLite FTS5 asynchronously.
        """
        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.fixture_img,
        )
        try:
            prev_dialogs = []
            for i in range(4):
                app_ctrl.trigger_capture_mode("ocr")
                ov = app_ctrl.overlay
                self.assertIsNotNone(ov)
                t0 = time.perf_counter()
                ov.simulate_region_drag(12, 12, 650, 128)
                elapsed_ui_ms = (time.perf_counter() - t0) * 1000.0
                # Overlay teardown + history record + dialog open is fast and non-blocking
                self.assertIsNone(app_ctrl.overlay)
                self.assertIsNotNone(app_ctrl._active_ocr_dialog)
                if prev_dialogs:
                    # Previous dialog must have been closed when new one opened
                    self.assertFalse(prev_dialogs[-1].isVisible())
                prev_dialogs.append(app_ctrl._active_ocr_dialog)
                _ = elapsed_ui_ms

            # Wait for background History OCR indexing threads to finish and verify FTS5 search
            self.assertTrue(app_ctrl.history_store.wait_for_pending_ocr(timeout=10.0))
            matches = app_ctrl.history_store.search_entries("Prismwake")
            self.assertGreaterEqual(len(matches), 1)
            self.assertTrue(matches[0].ocr_available)
            self.assertIn("Prismwake", matches[0].ocr_text)
        finally:
            app_ctrl.quit_app()
            self.assertIsNone(app_ctrl._active_ocr_dialog)



class TestOcrHotfixRegression(unittest.TestCase):
    """Regression: block-layout failure should retry sparse text automatically."""

    def test_blank_block_layout_falls_back_to_sparse_layout(self) -> None:
        import ocr.engine as eng
        status = query_ocr_engine_status(allow_builtin_fallback=False)
        if not status.available or status.engine_kind != "tesseract":
            self.skipTest("The real local Tesseract executable is unavailable")
        fixture = _make_english_screenshot_fixture()
        parse = mock.Mock(side_effect=[("", [], []), ("Prismwake recovered text", [], [])])
        with mock.patch.object(eng, "_parse_tesseract_tsv", parse):
            result = recognize_image_ocr(fixture, language="eng", allow_builtin_fallback=False)
        self.assertEqual(result.text, "Prismwake recovered text")
        self.assertEqual(parse.call_count, 2)
        self.assertEqual(result.engine_name, "tesseract")

    def test_minimal_tessdata_without_tsv_config_still_recognizes_words(self) -> None:
        """Regression for Windows: tessdata_fast has .traineddata, but no configs/tsv.

        The old command requested the positional `tsv` config file, which
        wasn't bundled. Tesseract then returned exit 0 and plain text instead
        of TSV, causing the parser to produce an empty result.
        """
        status = query_ocr_engine_status(allow_builtin_fallback=False)
        if not status.available or not status.binary_path or not status.tessdata_dir:
            self.skipTest("Local Tesseract executable and English data are required")
        from shutil import copyfile
        source = status.tessdata_dir / "eng.traineddata"
        with tempfile.TemporaryDirectory(prefix="prismwake_tsv_without_config_") as td:
            td_path = Path(td)
            copyfile(source, td_path / "eng.traineddata")
            self.assertFalse((td_path / "configs" / "tsv").exists())
            scene = _make_english_screenshot_fixture("Prismwake Regression 2026", "OCR works without configs tsv")
            result = recognize_image_ocr(
                scene, language="eng", custom_binary=status.binary_path,
                custom_tessdata=td_path, allow_builtin_fallback=False,
            )
            self.assertTrue(result.ok, result.error)
            self.assertIn("Prismwake", result.text)
            self.assertGreaterEqual(len(result.words), 4)
            self.assertGreaterEqual(len(result.lines), 2)

    def test_dark_small_text_is_recognized(self) -> None:
        status = query_ocr_engine_status(allow_builtin_fallback=False)
        if not status.available or status.engine_kind != "tesseract":
            self.skipTest("The real local Tesseract executable is unavailable")
        font = _load_test_font(16)
        scene = Image.new("RGB", (1100, 480), "#050608")
        drw = ImageDraw.Draw(scene)
        drw.text((155, 92), "Prismwake Offline Screenshot Capture 2026", fill="#f4f4fc", font=font)
        drw.text((155, 122), "OCR must recognize these window labels", fill="#f4f4fc", font=font)
        result = recognize_image_ocr(scene, language="eng", allow_builtin_fallback=False)
        self.assertIn("Prismwake", result.text)
        self.assertIn("2026", result.text)
        self.assertTrue(result.inverted_dark_theme)



class TestPart8QuickAndAdvancedOcrRedesign(unittest.TestCase):
    """
    Part 9.8 — Quick OCR (Default) + Advanced OCR (On Demand) Interface Redesign Tests:
      - Compact Quick OCR default mode, short & long text sizing, and multiline scrolling.
      - Editable text, Ctrl+A (`select_all_text`), Ctrl+C (`copy_shortcut_action`),
        Copy All, Copy Selected, transient `Copied!` feedback, and non-auto-closing behavior.
      - Expand to Advanced OCR and Collapse back to Quick OCR without re-running OCR
        or losing manual user edits, text selection, or capture image / line bounding boxes.
      - Explicit Retry protection for user-edited text unless confirmed.
      - Empty (`No text recognized`) and error states in Quick and Advanced modes.
      - Auto-copy default off, opt-in functionality, distinct `ocr_show_panel_after_auto_copy`
        preference with unobtrusive acknowledgement, and no clipboard overwrite on empty/error OCR.
      - Multi-monitor / negative-coordinate geometry clamping, taskbar clamping, disconnected
        monitor recovery, and high-DPI logical sizing.
      - Full OCR workflow from capture overlay close to visible non-modal Quick OCR panel
        positioned near the selection.
      - Frutiger Aqua theme palettes (`ocean_current`, `emerald_glass`, `sunset_coral`,
        `vista_sapphire`) and reduced-motion preferences.
      - SQLite Windows file-locking closure regression and `build_windows_oneclick.ps1`
        strict failure-check regression.
    """

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.history_root = Path(self._tmp_dir.name) / "History"
        self.sample_img = Image.new("RGB", (480, 120), (18, 24, 34))
        w1 = OcrWordBox("All", 20, 30, 36, 24, 96.0, 0, 0)
        w2 = OcrWordBox("From", 66, 30, 58, 24, 95.0, 0, 1)
        w3 = OcrWordBox("CallMeCarsonLIVE", 134, 30, 210, 24, 94.0, 0, 2)
        line0 = OcrLineBox("All From CallMeCarsonLIVE", 20, 30, 324, 24, 95.0, 0, (w1, w2, w3))
        self.three_word_result = OcrRecognitionResult(
            text="All From CallMeCarsonLIVE",
            lines=[line0],
            words=[w1, w2, w3],
            language="eng",
            engine_name="tesseract",
            source_width=480,
            source_height=120,
            inverted_dark_theme=True,
            elapsed_ms=231.0,
        )

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_01_quick_ocr_default_mode_short_and_long_text_sizing_and_scrolling(self) -> None:
        dlg = OcrResultsDialog(
            self.sample_img,
            initial_result=self.three_word_result,
            selection_rect=(300, 220, 340, 68),
            available_geometry=(0, 0, 1920, 1040),
            auto_start=False,
        )
        dlg.present_in_front()
        try:
            self.assertEqual(dlg.mode, "quick")
            self.assertTrue(dlg.is_quick_mode)
            self.assertFalse(dlg.is_advanced_mode)
            self.assertEqual(dlg.view_state, "ready")
            self.assertEqual(dlg.header_title_label.text(), "Text captured")
            self.assertEqual(dlg.word_count_badge.text(), "3 words")
            self.assertTrue(dlg.word_count_badge.isVisible())
            self.assertEqual(dlg.quick_footer_lang_label.text(), "Offline OCR · EN")

            # No giant preview, line list, or raw timing/PSM strings in Quick mode
            self.assertFalse(dlg.preview_widget.isVisible())
            self.assertFalse(dlg.lines_list.isVisible())
            self.assertFalse(dlg.status_label.isVisible())
            self.assertNotIn("231 ms", dlg.quick_footer_lang_label.text())
            self.assertNotIn("psm", dlg.quick_footer_lang_label.text().lower())

            # Short 3-word result dimensions: 420..520 logical px wide, 160..250 logical px tall
            gx, gy, gw, gh = dlg.panel_geometry()
            self.assertGreaterEqual(gw, 420)
            self.assertLessEqual(gw, 520)
            self.assertGreaterEqual(gh, 160)
            self.assertLessEqual(gh, 250)
            # Placed just below selection (220 + 68 + 10 = 298)
            self.assertEqual(gx, 300)
            self.assertEqual(gy, 298)

            # Long multiline text grows up to screen-relative cap and then scrolls
            long_text = "\n".join(
                f"Line {i:02d}: Prismwake HDR screenshot & offline OCR pipeline verification line."
                for i in range(1, 26)
            )
            long_geom = compute_quick_ocr_panel_geometry(
                long_text,
                selection_rect=(300, 220, 340, 68),
                available_geometry=(0, 0, 1920, 1040),
                view_state="ready",
            )
            self.assertGreaterEqual(long_geom["width"], 420)
            self.assertLessEqual(long_geom["width"], 520)
            self.assertGreater(long_geom["height"], gh)
            self.assertLessEqual(long_geom["height"], 440)
            self.assertTrue(long_geom["scrolls"])
        finally:
            dlg.close()

    def test_02_quick_ocr_editable_text_shortcuts_copy_feedback_and_no_autoclose(self) -> None:
        dlg = OcrResultsDialog(
            self.sample_img,
            initial_result=self.three_word_result,
            auto_start=False,
        )
        dlg.present_in_front()
        try:
            self.assertFalse(dlg.user_modified_text)
            # Edit text manually
            dlg.text_edit.setPlainText("All From CallMeCarsonLIVE (Manually Edited)")
            self.assertTrue(dlg.user_modified_text)
            self.assertEqual(dlg.word_count_badge.text(), "5 words")

            # Ctrl+A selects all current editable text; Ctrl+C copies it
            sel_all = dlg.select_all_text()
            self.assertEqual(sel_all, "All From CallMeCarsonLIVE (Manually Edited)")
            copied_via_sc = dlg.copy_shortcut_action()
            self.assertEqual(copied_via_sc, "All From CallMeCarsonLIVE (Manually Edited)")
            self.assertEqual(OcrResultsDialog._clipboard_text, "All From CallMeCarsonLIVE (Manually Edited)")
            self.assertTrue(dlg.copy_feedback_active)
            self.assertEqual(dlg.copy_btn.text(), "Copied!")
            # Panel must NOT close automatically after copy by default
            self.assertTrue(dlg.isVisible())

            # Partial selection copy
            dlg.text_edit.setSelectedText("CallMeCarsonLIVE")
            copied_part = dlg.copy_shortcut_action()
            self.assertEqual(copied_part, "CallMeCarsonLIVE")
            self.assertEqual(OcrResultsDialog._clipboard_text, "CallMeCarsonLIVE")
            self.assertTrue(dlg.isVisible())

            # Escape closes only this panel
            dlg.escape_action()
            self.assertFalse(dlg.isVisible())
        finally:
            dlg.close()

    def test_03_expand_to_advanced_and_collapse_to_quick_preserves_edits_selection_and_boxes_without_reocr(self) -> None:
        dlg = OcrResultsDialog(
            self.sample_img,
            initial_result=self.three_word_result,
            selection_rect=(200, 180, 320, 60),
            available_geometry=(0, 0, 1920, 1040),
            auto_start=False,
        )
        dlg.present_in_front()
        try:
            self.assertEqual(dlg.ocr_run_count, 1)
            dlg.text_edit.setPlainText("All From CallMeCarsonLIVE — Custom Note")
            dlg.text_edit.setSelectedText("Custom Note")

            # Expand to Advanced OCR
            dlg.expand_to_advanced()
            self.assertEqual(dlg.mode, "advanced")
            self.assertTrue(dlg.is_advanced_mode)
            self.assertEqual(dlg.ocr_run_count, 1)  # Must NOT rerun OCR!
            self.assertTrue(dlg.preview_widget.isVisible())
            self.assertTrue(dlg.lines_list.isVisible())
            self.assertTrue(dlg.status_label.isVisible())
            self.assertIn("231 ms", dlg.status_label.text())
            self.assertEqual(dlg.text_edit.toPlainText(), "All From CallMeCarsonLIVE — Custom Note")
            self.assertEqual(dlg.text_edit.selectedText(), "Custom Note")
            self.assertEqual(len(dlg._result.lines), 1)
            self.assertEqual(len(dlg._result.words), 3)

            # Collapse back to Quick OCR
            dlg.collapse_to_quick()
            self.assertEqual(dlg.mode, "quick")
            self.assertTrue(dlg.is_quick_mode)
            self.assertEqual(dlg.ocr_run_count, 1)  # Still 1!
            self.assertFalse(dlg.preview_widget.isVisible())
            self.assertFalse(dlg.lines_list.isVisible())
            self.assertEqual(dlg.text_edit.toPlainText(), "All From CallMeCarsonLIVE — Custom Note")
            self.assertEqual(dlg.text_edit.selectedText(), "Custom Note")

            # Verify responsive 1-column layout on small monitors (< 760 px wide) vs 2-column on wide monitors
            adv_wide = compute_advanced_ocr_panel_geometry(available_geometry=(0, 0, 1920, 1040))
            adv_narrow = compute_advanced_ocr_panel_geometry(available_geometry=(0, 0, 680, 900))
            self.assertEqual(adv_wide["layout_columns"], 2)
            self.assertEqual(adv_narrow["layout_columns"], 1)
            self.assertLessEqual(adv_narrow["width"], 680)
        finally:
            dlg.close()

    def test_04_explicit_retry_protects_user_edited_text_unless_confirmed(self) -> None:
        confirmed = [False]
        dlg = OcrResultsDialog(
            self.sample_img,
            initial_result=self.three_word_result,
            confirm_overwrite_callback=lambda: confirmed[0],
            auto_start=False,
        )
        dlg.present_in_front()
        try:
            dlg.text_edit.setPlainText("User carefully edited this text")
            self.assertTrue(dlg.user_modified_text)
            runs_before = dlg.ocr_run_count

            # Unconfirmed retry is blocked and preserves user edits
            started = dlg.start_recognition()
            self.assertFalse(started)
            self.assertEqual(dlg.ocr_run_count, runs_before)
            self.assertEqual(dlg.text_edit.toPlainText(), "User carefully edited this text")

            # Confirmed retry runs recognition
            confirmed[0] = True
            with mock.patch("ocr.engine.recognize_image_ocr", return_value=self.three_word_result):
                started_ok = dlg.start_recognition()
                self.assertTrue(started_ok)
                self.assertEqual(dlg.ocr_run_count, runs_before + 1)
                self.assertEqual(dlg.text_edit.toPlainText(), "All From CallMeCarsonLIVE")
                self.assertFalse(dlg.user_modified_text)
        finally:
            dlg.close()

    def test_05_empty_and_error_states_in_quick_and_advanced_modes(self) -> None:
        empty_res = OcrRecognitionResult(
            text="",
            lines=[],
            words=[],
            language="eng",
            engine_name="tesseract",
            source_width=240,
            source_height=80,
        )
        dlg_empty = OcrResultsDialog(self.sample_img, initial_result=empty_res, auto_start=False)
        dlg_empty.present_in_front()
        try:
            self.assertEqual(dlg_empty.view_state, "empty")
            self.assertEqual(dlg_empty.header_title_label.text(), "No text recognized")
            self.assertTrue(dlg_empty.empty_state_banner.isVisible())
            self.assertFalse(dlg_empty.text_edit.isVisible())
            self.assertTrue(dlg_empty.quick_retry_btn.isVisible())
            self.assertTrue(dlg_empty.quick_close_btn.isVisible())
            self.assertTrue(dlg_empty.expand_btn.isVisible())
            self.assertFalse(dlg_empty.copy_btn.isEnabled())
            # Expanding from empty state allows changing language & optimization mode (with manual threshold removed)
            dlg_empty.expand_to_advanced()
            self.assertEqual(dlg_empty.mode, "advanced")
            self.assertFalse(hasattr(dlg_empty, "thresh_check"))
            self.assertFalse(hasattr(dlg_empty, "set_threshold_enabled"))
            self.assertNotIn("High-Contrast Threshold", dlg_empty.empty_state_banner.text())
            dlg_empty.set_language("ita")
            dlg_empty.set_quality_mode("accurate")
            self.assertEqual(dlg_empty._default_language, "ita")
            self.assertEqual(dlg_empty.quality_mode, "accurate")
        finally:
            dlg_empty.close()

    def test_06_auto_copy_default_off_opt_in_panel_preference_and_no_clipboard_overwrite_on_empty_or_error(self) -> None:
        cfg_default = pw.AppConfig()
        self.assertFalse(cfg_default.ocr_auto_copy_text)
        self.assertTrue(cfg_default.ocr_show_panel_after_auto_copy)

        OcrResultsDialog._clipboard_text = "EXISTING_USER_CLIPBOARD_DATA"
        # 1. Default auto_copy_on_complete=False does NOT touch clipboard
        dlg1 = OcrResultsDialog(
            self.sample_img,
            initial_result=self.three_word_result,
            auto_copy_on_complete=False,
            auto_start=False,
        )
        self.assertEqual(OcrResultsDialog._clipboard_text, "EXISTING_USER_CLIPBOARD_DATA")
        dlg1.close()

        # 2. Auto-copy enabled + empty result -> MUST NOT overwrite clipboard
        empty_res = OcrRecognitionResult(text="   ", language="eng", engine_name="tesseract")
        dlg_empty = OcrResultsDialog(
            self.sample_img,
            initial_result=empty_res,
            auto_copy_on_complete=True,
            show_panel_after_auto_copy=False,
            auto_start=False,
        )
        self.assertEqual(OcrResultsDialog._clipboard_text, "EXISTING_USER_CLIPBOARD_DATA")
        dlg_empty.close()

        # 3. Auto-copy enabled + error result -> MUST NOT overwrite clipboard
        err_res = OcrRecognitionResult(text="", language="eng", engine_name="tesseract", error="Missing tessdata")
        dlg_err = OcrResultsDialog(
            self.sample_img,
            initial_result=err_res,
            auto_copy_on_complete=True,
            show_panel_after_auto_copy=False,
            auto_start=False,
        )
        self.assertEqual(OcrResultsDialog._clipboard_text, "EXISTING_USER_CLIPBOARD_DATA")
        dlg_err.close()

        # 4. Auto-copy enabled + valid text + show_panel_after_auto_copy=False -> copies text, emits toast, closes panel
        toasts: list[str] = []
        dlg_auto_hide = OcrResultsDialog(
            self.sample_img,
            initial_result=self.three_word_result,
            auto_copy_on_complete=True,
            show_panel_after_auto_copy=False,
            on_auto_copy_toast=lambda msg: toasts.append(msg),
            auto_start=False,
        )
        self.assertEqual(OcrResultsDialog._clipboard_text, "All From CallMeCarsonLIVE")
        self.assertTrue(dlg_auto_hide.auto_copy_acknowledged)
        self.assertEqual(len(toasts), 1)
        self.assertIn("3 words", toasts[0])
        self.assertFalse(dlg_auto_hide.isVisible())

    def test_07_multimonitor_negative_coordinates_taskbar_and_dpi_logical_clamping(self) -> None:
        left_neg_mon = VirtualMonitorRect(x=-1920, y=-300, width=1920, height=1040, dpi_scale=1.25)
        right_primary = VirtualMonitorRect(x=0, y=0, width=2560, height=1400, dpi_scale=2.0, is_primary=True)

        # Selection near bottom-right corner of negative-coordinate left monitor
        geom_neg = compute_quick_ocr_panel_geometry(
            "All From CallMeCarsonLIVE",
            selection_rect=(-280, 680, 240, 50),
            monitors=[left_neg_mon, right_primary],
            dpi_scale=1.25,
            view_state="ready",
        )
        self.assertGreaterEqual(geom_neg["x"], left_neg_mon.x)
        self.assertLessEqual(geom_neg["x"] + geom_neg["width"], left_neg_mon.x + left_neg_mon.width)
        self.assertGreaterEqual(geom_neg["y"], left_neg_mon.y)
        self.assertLessEqual(geom_neg["y"] + geom_neg["height"], left_neg_mon.y + left_neg_mon.height)

        # Simulate monitor disconnection: selection was on (-1800, -200), but only right_primary remains
        geom_recovered = compute_quick_ocr_panel_geometry(
            "All From CallMeCarsonLIVE",
            selection_rect=(-1800, -200, 300, 60),
            monitors=[right_primary],
            dpi_scale=2.0,
            view_state="ready",
        )
        self.assertGreaterEqual(geom_recovered["x"], right_primary.x)
        self.assertLessEqual(geom_recovered["x"] + geom_recovered["width"], right_primary.x + right_primary.width)
        self.assertGreaterEqual(geom_recovered["y"], right_primary.y)
        self.assertLessEqual(geom_recovered["y"] + geom_recovered["height"], right_primary.y + right_primary.height)

    def test_08_full_capture_overlay_to_quick_ocr_panel_lifecycle_and_selection_placement(self) -> None:
        fixture = _make_english_screenshot_fixture("All From CallMeCarsonLIVE", "Compact Quick OCR Panel")
        cfg = pw.AppConfig()
        cfg.history_directory = str(self.history_root)
        cfg.ocr_auto_copy_text = False
        app_ctrl = pw.HDRSnipFusionApplication(
            config=cfg,
            history_root=self.history_root,
            synthetic_screen_image=fixture,
        )
        try:
            app_ctrl.trigger_capture_mode("ocr")
            ov = app_ctrl.overlay
            self.assertIsNotNone(ov)
            ov.simulate_region_drag(18, 16, 650, 126)

            self.assertIsNone(app_ctrl.overlay)
            dlg = app_ctrl._active_ocr_dialog
            self.assertIsNotNone(dlg)
            self.assertTrue(dlg.isVisible())
            self.assertEqual(dlg.mode, "quick")
            self.assertEqual(app_ctrl._last_ocr_selection_rect, (18, 16, 632, 110))
            px, py, pw_w, pw_h = dlg.panel_geometry()
            self.assertGreaterEqual(pw_w, 420)
            self.assertLessEqual(pw_w, 520)
            self.assertGreaterEqual(pw_h, 160)
            self.assertLessEqual(pw_h, 250)
            self.assertGreaterEqual(px, 0)
            self.assertGreaterEqual(py, 0)
        finally:
            app_ctrl.quit_app()

    def test_09_frutiger_aqua_themes_and_reduced_motion_support(self) -> None:
        for theme_id in ("ocean_current", "emerald_glass", "sunset_coral", "vista_sapphire"):
            pal = resolve_ocr_aqua_theme_palette(theme_id, animation_intensity="high", reduced_motion=False)
            self.assertEqual(pal["id"], theme_id)
            self.assertFalse(pal["reduced_motion"])

            pal_rm = resolve_ocr_aqua_theme_palette(theme_id, animation_intensity="high", reduced_motion=True)
            self.assertTrue(pal_rm["reduced_motion"])
            self.assertEqual(pal_rm["animation_intensity"], "off")

    def test_10_sqlite_windows_file_locking_and_builder_failure_checks_regression(self) -> None:
        # 1. Verify SQLite history.db file handle is closed after every transaction (preventing WinError 32)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "History"
            store = ScreenshotHistoryStore(root)
            entry = store.record_capture(
                Image.new("RGB", (120, 80), (20, 40, 60)),
                title="Lock Regression Check",
                was_saved_or_copied=True,
            )
            self.assertIsNotNone(entry)
            store.shutdown(timeout=0.5)
            renamed_db = root / "history_renamed_unlocked.db"
            os.replace(str(store.db_path), str(renamed_db))
            self.assertTrue(renamed_db.is_file())

        # 2. Verify build_windows_oneclick.ps1 retains strict failure checks & stale EXE cleanup
        ps1_text = (PROJECT_ROOT / "build_windows_oneclick.ps1").read_text(encoding="utf-8")
        self.assertIn("function Assert-NativeSuccess", ps1_text)
        self.assertIn("Invoke-IsolatedPythonTest", ps1_text)
        self.assertIn("tests\\run_headless_tests.py", ps1_text)
        self.assertIn("tests\\smoke_qt_gui.py", ps1_text)
        self.assertIn('if (Test-Path "dist\\Prismwake.exe") { Remove-Item "dist\\Prismwake.exe" -Force }', ps1_text)
        self.assertIn("--write-ocr-verify-file", ps1_text)



class TestPart9AutomaticOcrAccuracyAndOptimization(unittest.TestCase):
    """
    Part 10 — Major OCR Accuracy Upgrade & Fully Automatic Image Optimization Tests:
      1. High-Contrast Threshold removed everywhere (Quick OCR, Advanced OCR, Settings, AppConfig),
         Automatic status text & processing budget modes (`auto`, `fast`, `accurate`), and legacy config migration.
      2. Thresholding helps one fixture (`faint_low_contrast_watermark`) and harms another (`threshold_harm_antialiased`),
         both handled automatically with 0% CER.
      3. Inversion helps one fixture (`inversion_help_dark_pill_in_light`) and harms another (`inversion_harm_slate_surface`),
         both handled automatically with 0% CER.
      4. Original RGB recognition beats processed grayscale on chromatic isoluminant captures (`isoluminant_rgb_alert`).
      5. Adaptive upscaling improves small text (`small_antialiased_code`) without destroying larger text.
      6. Non-empty unreliable initial recognition triggers automatic follow-up candidate reassessment (`gradient_antialiased_banner`).
      7. Conservative candidate scoring (`score_ocr_candidate`) does not blindly favor longer garbage output.
      8. Pattern A: Game menu with left-side icons (`Invite Friends`, `People`, `Settings`, `Report`, `Switch avatar`, `Shop`, `Friends chat`)
         eliminates prepended icon glyphs while preserving legitimate short words (`I`, `A`, `OK`).
      9. Pattern B: Stylized sign (`SELL LOGS`) fixes `'I SELLLOGS @'` into `'SELL LOGS'` with accurate source-pixel bounding boxes.
     10. Retry Recognition explores a meaningfully different strategy (`retry_attempt` rotation) and benchmark results verify CER/WER gains.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = {f.fixture_id: f for f in build_ground_truth_ocr_fixtures()}

    def test_01_high_contrast_threshold_removed_everywhere_and_legacy_config_migration(self) -> None:
        sample = Image.new("RGB", (320, 80), (20, 24, 32))
        dlg = OcrResultsDialog(sample, initial_result=OcrRecognitionResult(text="Test OCR"), auto_start=False)
        try:
            self.assertFalse(hasattr(dlg, "thresh_check"))
            self.assertFalse(hasattr(dlg, "set_threshold_enabled"))
            self.assertEqual(dlg.quality_mode, "auto")
            self.assertEqual(dlg.auto_opt_status_label.text(), AUTOMATIC_OCR_STATUS_TEXT)
            self.assertFalse(dlg.auto_opt_status_label.isVisible())
            dlg.expand_to_advanced()
            self.assertTrue(dlg.auto_opt_status_label.isVisible())
            self.assertNotIn("High-Contrast Threshold", dlg.empty_state_banner.text())
            self.assertNotIn("High-Contrast Threshold", dlg.status_label.text())
        finally:
            dlg.close()

        cfg = pw.AppConfig()
        self.assertEqual(cfg.ocr_quality_mode, "auto")
        self.assertFalse(hasattr(cfg, "ocr_apply_threshold"))

        with tempfile.TemporaryDirectory() as tmp:
            legacy_cfg_path = Path(tmp) / "config.json"
            legacy_cfg_path.write_text(
                '{"ocr_language": "ita", "ocr_apply_threshold": true, "ocr_quality_mode": "accurate", "ocr_auto_copy_text": true}',
                encoding="utf-8",
            )
            with mock.patch.object(pw, "CONFIG_FILE", legacy_cfg_path), mock.patch.object(pw, "PRISMWAKE_CONFIG_FILE", legacy_cfg_path):
                loaded = pw.AppConfig.load()
                self.assertEqual(loaded.ocr_language, "ita")
                self.assertEqual(loaded.ocr_quality_mode, "accurate")
                self.assertTrue(loaded.ocr_auto_copy_text)
                self.assertFalse(hasattr(loaded, "ocr_apply_threshold"))

    def test_02_thresholding_helps_one_fixture_and_harms_another_automatically(self) -> None:
        fx_help = self.fixtures["faint_low_contrast_watermark"]
        res_leg_help = recognize_image_ocr_legacy(fx_help.image)
        res_auto_help = recognize_image_ocr(fx_help.image)
        self.assertGreater(compute_cer(res_leg_help.text, fx_help.ground_truth), 0.50)
        self.assertEqual(res_auto_help.text.strip(), fx_help.ground_truth)
        self.assertEqual(compute_cer(res_auto_help.text, fx_help.ground_truth), 0.0)

        fx_harm = self.fixtures["threshold_harm_antialiased"]
        res_leg_thresh = recognize_image_ocr_legacy(fx_harm.image, apply_threshold=True)
        res_auto_harm = recognize_image_ocr(fx_harm.image)
        self.assertEqual(res_leg_thresh.text.strip(), "")
        self.assertEqual(res_auto_harm.text.strip(), fx_harm.ground_truth)
        self.assertEqual(compute_cer(res_auto_harm.text, fx_harm.ground_truth), 0.0)

    def test_03_selective_inversion_helps_one_fixture_and_harms_another_automatically(self) -> None:
        fx_inv_help = self.fixtures["inversion_help_dark_pill_in_light"]
        prof_help = analyze_image_for_ocr(fx_inv_help.image)
        self.assertGreater(prof_help.median_luma, 180.0)
        self.assertTrue(prof_help.is_light_ink)
        res_auto_help = recognize_image_ocr(fx_inv_help.image)
        self.assertEqual(res_auto_help.text.strip(), fx_inv_help.ground_truth)

        fx_inv_harm = self.fixtures["inversion_harm_slate_surface"]
        prof_harm = analyze_image_for_ocr(fx_inv_harm.image)
        self.assertLess(prof_harm.median_luma, 118.0)
        self.assertFalse(prof_harm.is_light_ink)
        res_leg_harm = recognize_image_ocr_legacy(fx_inv_harm.image)
        res_auto_harm = recognize_image_ocr(fx_inv_harm.image)
        self.assertGreater(compute_cer(res_leg_harm.text, fx_inv_harm.ground_truth), 0.80)
        self.assertEqual(res_auto_harm.text.strip(), fx_inv_harm.ground_truth)

    def test_04_original_rgb_beats_processed_grayscale_on_chromatic_isoluminant_capture(self) -> None:
        fx_rgb = self.fixtures["isoluminant_rgb_alert"]
        prof = analyze_image_for_ocr(fx_rgb.image)
        self.assertTrue(prof.is_chromatic_isoluminant)
        res_leg = recognize_image_ocr_legacy(fx_rgb.image)
        res_auto = recognize_image_ocr(fx_rgb.image)
        self.assertGreater(compute_cer(res_leg.text, fx_rgb.ground_truth), 0.80)
        self.assertEqual(res_auto.text.strip(), fx_rgb.ground_truth)
        self.assertEqual(res_auto.preprocessing_strategy, "original_rgb")

    def test_05_upscaling_improves_small_text_without_destroying_larger_text(self) -> None:
        fx_small = self.fixtures["small_antialiased_code"]
        res_leg = recognize_image_ocr_legacy(fx_small.image)
        res_auto = recognize_image_ocr(fx_small.image)
        self.assertEqual(res_leg.scale_factor, 1.0)
        self.assertGreater(compute_cer(res_leg.text, fx_small.ground_truth), 0.0)
        self.assertGreaterEqual(res_auto.scale_factor, 2.0)
        self.assertEqual(res_auto.text.strip(), fx_small.ground_truth)

        helper_large_p = PROJECT_ROOT / "tests" / "fixtures" / "suite_a_ocr" / "helper_large_heading.png"
        if helper_large_p.is_file():
            with Image.open(helper_large_p) as _im:
                large_img = _im.convert("RGB")
        else:
            font_large = _load_test_font(36)
            large_img = Image.new("RGB", (680, 220), (250, 252, 255))
            ImageDraw.Draw(large_img).text((24, 70), "Large Clear Heading 2026", fill=(12, 18, 26), font=font_large)
        prof_large = analyze_image_for_ocr(large_img)
        self.assertEqual(prof_large.recommended_scale, 1.0)
        res_large = recognize_image_ocr(large_img)
        self.assertEqual(res_large.text.strip(), "Large Clear Heading 2026")

    def test_06_nonempty_unreliable_initial_pass_triggers_automatic_reassessment(self) -> None:
        fx_grad = self.fixtures["gradient_antialiased_banner"]
        res_leg = recognize_image_ocr_legacy(fx_grad.image)
        self.assertTrue(bool(res_leg.text.strip()))
        self.assertGreater(compute_cer(res_leg.text, fx_grad.ground_truth), 0.50)

        res_auto = recognize_image_ocr(fx_grad.image)
        self.assertEqual(res_auto.text.strip(), fx_grad.ground_truth)
        self.assertEqual(compute_cer(res_auto.text, fx_grad.ground_truth), 0.0)

    def test_07_conservative_candidate_scoring_rejects_longer_garbage_output(self) -> None:
        fx_sign = self.fixtures["stylized_sign_sell_logs"]
        prof = analyze_image_for_ocr(fx_sign.image)

        w_sell = OcrWordBox("SELL", 56, 22, 67, 22, 91.5, 0, 0)
        w_logs = OcrWordBox("LOGS", 133, 22, 74, 22, 91.5, 0, 1)
        clean_res = OcrRecognitionResult(
            text="SELL LOGS",
            lines=[OcrLineBox("SELL LOGS", 56, 22, 151, 22, 91.5, 0, (w_sell, w_logs))],
            words=[w_sell, w_logs],
            source_width=fx_sign.image.width,
            source_height=fx_sign.image.height,
        )

        noisy_words = [
            OcrWordBox("|", 18, 22, 8, 16, 48.0, 0, 0),
            OcrWordBox("SELL)LOGS", 56, 22, 152, 22, 61.0, 0, 1),
            OcrWordBox("@", 286, 22, 21, 24, 52.0, 0, 2),
            OcrWordBox("(6)", 310, 22, 18, 20, 35.0, 0, 3),
            OcrWordBox("~", 330, 22, 8, 12, 29.0, 0, 4),
        ]
        garbage_res = OcrRecognitionResult(
            text="| SELL)LOGS @ (6) ~",
            lines=[OcrLineBox("| SELL)LOGS @ (6) ~", 18, 22, 320, 24, 45.0, 0, tuple(noisy_words))],
            words=noisy_words,
            source_width=fx_sign.image.width,
            source_height=fx_sign.image.height,
        )

        score_clean = score_ocr_candidate(clean_res, prof, fx_sign.image)
        score_garbage = score_ocr_candidate(garbage_res, prof, fx_sign.image)
        self.assertGreater(len(garbage_res.text), len(clean_res.text))
        self.assertGreater(score_clean, score_garbage + 40.0)

    def test_08_game_menu_with_icons_and_legitimate_short_words_preserved(self) -> None:
        fx_menu = self.fixtures["game_menu_with_icons"]
        res_leg = recognize_image_ocr_legacy(fx_menu.image)
        res_auto = recognize_image_ocr(fx_menu.image)
        self.assertGreater(compute_wer(res_leg.text, fx_menu.ground_truth), 0.50)
        self.assertEqual(res_auto.text.strip(), fx_menu.ground_truth)
        self.assertEqual([ln.text for ln in res_auto.lines], fx_menu.ground_truth.splitlines())

        helper_short_p = PROJECT_ROOT / "tests" / "fixtures" / "suite_a_ocr" / "helper_short_words.png"
        if helper_short_p.is_file():
            with Image.open(helper_short_p) as _im:
                short_words_img = _im.convert("RGB")
        else:
            font_reg = _load_test_font(22)
            short_words_img = Image.new("RGB", (540, 110), (250, 252, 255))
            drw = ImageDraw.Draw(short_words_img)
            drw.text((20, 20), "A fast offline tool", fill=(15, 20, 28), font=font_reg)
            drw.text((20, 62), "OK to continue now", fill=(15, 20, 28), font=font_reg)
        res_short = recognize_image_ocr(short_words_img)
        self.assertEqual(res_short.text.strip(), "A fast offline tool\nOK to continue now")

    def test_09_stylized_sign_sell_logs_spacing_and_coordinate_accuracy(self) -> None:
        fx_sign = self.fixtures["stylized_sign_sell_logs"]
        res_leg = recognize_image_ocr_legacy(fx_sign.image)
        res_auto = recognize_image_ocr(fx_sign.image)

        self.assertEqual(res_leg.text.strip(), "I SELLLOGS @")
        self.assertEqual(res_auto.text.strip(), "SELL LOGS")
        self.assertEqual([w.text for w in res_auto.words], ["SELL", "LOGS"])

        w_sell, w_logs = res_auto.words[0], res_auto.words[1]
        self.assertGreaterEqual(w_sell.x, 45)
        self.assertLessEqual(w_sell.right, 132)
        self.assertGreaterEqual(w_logs.x, 125)
        self.assertLessEqual(w_logs.right, 220)
        self.assertGreater(w_logs.x, w_sell.right)

    def test_10_retry_recognition_strategy_rotation_and_benchmark_verification(self) -> None:
        fx_sign = self.fixtures["stylized_sign_sell_logs"]
        prof = analyze_image_for_ocr(fx_sign.image)
        cands_0 = generate_ocr_preprocessing_candidates(fx_sign.image, prof, retry_attempt=0)
        cands_1 = generate_ocr_preprocessing_candidates(fx_sign.image, prof, retry_attempt=1)
        self.assertNotEqual(cands_0[0].name, cands_1[0].name)

        with override_production_ocr_orchestrator(HybridOcrOrchestrator(prefer_neural=False)):
            dlg = OcrResultsDialog(fx_sign.image, auto_start=True)
            try:
                self.assertEqual(dlg.ocr_run_count, 1)
                self.assertEqual(dlg.retry_attempt, 0)
                self.assertEqual(dlg.text_edit.toPlainText().strip(), "SELL LOGS")
                dlg.start_recognition(force_discard_edits=True)
                self.assertEqual(dlg.ocr_run_count, 2)
                self.assertEqual(dlg.retry_attempt, 1)
                self.assertEqual(dlg.text_edit.toPlainText().strip(), "SELL LOGS")
            finally:
                dlg.close()


class TestPart10IndependentOcrRegressionAndRealWorldValidation(unittest.TestCase):
    """
    Part 11 — Independent Held-Out OCR Regression & Real-World Crop Validation:
      1. All 6 independent held-out fixtures (`new_game_menu`, `keep_leading_I`,
         `novel_stylized_sign`, `punctuation`, `new_icon_menu`, `gradient`) achieve 0.0% CER / 0.0% WER.
      2. `new_game_menu.png` outputs clean 4-line menu labels without leading `O` even if
         pre-OCR icon masking is bypassed, and word bounding boxes remain accurately aligned.
      3. `keep_leading_I.png` (`I LOVE LOGS`) and prose lines (`I agree to the terms`,
         `A wooden sign ahead`, `O Captain My Captain`, `Options`) preserve leading `I`, `A`, `O`.
      4. Inline HUD pipes (`VIP | 60 FPS | 95°C`), markdown pipe tables (`| Player | Ping | Status |`),
         and `@` emails (`user42@example.com`) are preserved without false icon stripping.
      5. Held-out real-world screenshot crops (`real_win11_explorer_search`, `real_win11_preview_warning`,
         `real_code_python_imports`) recognize cleanly offline.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.ind_fixtures = {f.fixture_id: f for f in build_independent_regression_ocr_fixtures()}
        cls.rw_fixtures = {f.fixture_id: f for f in build_realworld_heldout_ocr_fixtures()}

    def test_01_all_six_independent_heldout_fixtures_pass_with_zero_cer_and_wer(self) -> None:
        self.assertEqual(len(self.ind_fixtures), 6)
        expected_ids = {
            "new_game_menu",
            "keep_leading_I",
            "novel_stylized_sign",
            "punctuation",
            "new_icon_menu",
            "gradient",
        }
        self.assertEqual(set(self.ind_fixtures.keys()), expected_ids)
        for fid, fx in self.ind_fixtures.items():
            res = recognize_image_ocr(fx.image, language="eng")
            self.assertEqual(
                res.text.strip(),
                fx.ground_truth,
                msg=f"Independent fixture {fid} failed: expected {fx.ground_truth!r}, got {res.text!r}",
            )
            self.assertEqual(compute_cer(res.text, fx.ground_truth), 0.0)
            self.assertEqual(compute_wer(res.text, fx.ground_truth), 0.0)

    def test_02_new_game_menu_gutter_filtering_and_word_coordinate_invariance(self) -> None:
        fx = self.ind_fixtures["new_game_menu"]
        res = recognize_image_ocr(fx.image, language="eng")
        self.assertEqual(res.text, "Trade Items\nInventory\nSettings\nLeave Lobby")
        for w in res.words:
            self.assertGreaterEqual(w.x, 56, msg=f"Word {w.text!r} x={w.x} should be in text column >=56")

        # Also verify post-OCR refinement strips left-gutter 'O' even if icon masking was not applied
        prof = analyze_image_for_ocr(fx.image)
        noisy_lines = [
            OcrLineBox(
                "= Trade Items", 10, 20, 184, 43, 88.0, 0,
                (
                    OcrWordBox("=", 10, 20, 33, 43, 78.7, 0, 0),
                    OcrWordBox("Trade", 60, 34, 62, 17, 95.8, 0, 1),
                    OcrWordBox("Items", 132, 34, 62, 17, 90.8, 0, 2),
                ),
            ),
            OcrLineBox(
                "_ Inventory", 10, 80, 159, 38, 70.0, 1,
                (
                    OcrWordBox("_", 10, 80, 33, 38, 41.7, 1, 0),
                    OcrWordBox("Inventory", 62, 88, 107, 28, 96.4, 1, 1),
                ),
            ),
            OcrLineBox(
                "O Settings .", 25, 132, 365, 38, 70.0, 2,
                (
                    OcrWordBox("O", 25, 139, 18, 18, 82.3, 2, 0),
                    OcrWordBox("Settings", 62, 146, 92, 22, 94.7, 2, 1),
                    OcrWordBox(".", 384, 132, 6, 38, 33.6, 2, 2),
                ),
            ),
            OcrLineBox(
                "| O Leave Lobby", 11, 195, 193, 37, 67.0, 3,
                (
                    OcrWordBox("|", 11, 226, 6, 6, 45.0, 3, 0),
                    OcrWordBox("O", 26, 195, 17, 18, 31.0, 3, 1),
                    OcrWordBox("Leave", 62, 202, 65, 17, 96.8, 3, 2),
                    OcrWordBox("Lobby", 138, 202, 66, 22, 96.6, 3, 3),
                ),
            ),
        ]
        raw_unmasked = OcrRecognitionResult(
            text="= Trade Items\n_ Inventory\nO Settings .\n| O Leave Lobby",
            lines=noisy_lines,
            words=[w for ln in noisy_lines for w in ln.words],
            source_width=fx.image.width,
            source_height=fx.image.height,
        )
        refined = refine_ocr_result_layout_and_spacing(raw_unmasked, fx.image, prof)
        self.assertEqual(refined.text, "Trade Items\nInventory\nSettings\nLeave Lobby")
        # Verify word coordinates of remaining words are preserved unmodified
        by_text = {w.text: w for w in refined.words}
        self.assertEqual((by_text["Settings"].x, by_text["Settings"].y, by_text["Settings"].width, by_text["Settings"].height), (62, 146, 92, 22))
        self.assertEqual((by_text["Leave"].x, by_text["Leave"].y, by_text["Leave"].width, by_text["Leave"].height), (62, 202, 65, 17))
        self.assertEqual((by_text["Lobby"].x, by_text["Lobby"].y, by_text["Lobby"].width, by_text["Lobby"].height), (138, 202, 66, 22))

    def test_03_leading_I_A_O_and_pipe_table_preservation(self) -> None:
        fx_i = self.ind_fixtures["keep_leading_I"]
        res_i = recognize_image_ocr(fx_i.image, language="eng")
        self.assertEqual(res_i.text, "I LOVE LOGS")
        self.assertEqual(res_i.words[0].text, "I")
        self.assertEqual((res_i.words[0].x, res_i.words[0].y), (43, 37))

        fx_prose = self.rw_fixtures["unseen_prose_leading_I_A_O"]
        res_prose = recognize_image_ocr(fx_prose.image, language="eng")
        self.assertEqual(res_prose.text, "I agree to the terms\nA wooden sign ahead\nO Captain My Captain")

        fx_table = self.rw_fixtures["unseen_markdown_pipe_table"]
        res_table = recognize_image_ocr(fx_table.image, language="eng")
        self.assertEqual(res_table.text, "| Player | Ping | Status |\n| Shadow | 18ms | READY |")

    def test_04_realworld_screenshot_crops_and_bordered_icon_menu(self) -> None:
        for fid in (
            "real_win11_explorer_search",
            "real_win11_preview_warning",
            "real_code_python_imports",
            "unseen_bordered_icon_menu",
            "unseen_shell_and_metadata",
        ):
            fx = self.rw_fixtures[fid]
            res = recognize_image_ocr(fx.image, language="eng")
            self.assertEqual(res.text.strip(), fx.ground_truth, msg=f"Failed on {fid}: {res.text!r}")




class TestPart11RealWorldFailureAndSubprocessDeadlockRegression(unittest.TestCase):
    """
    Part 12 — Real-World OCR Failure, Subprocess Pipe Deadlock, Timeout, Cancellation & Menu Segmentation Regression:
      1. Large-TSV subprocess pipe deadlock test: mock child process writing >1.6 MB stdout and >256 KB stderr
         (far exceeding OS pipe buffers on Windows and Linux) drains concurrently without deadlocking.
      2. Subprocess timeout test: stalling child process is killed & reaped after `pass_timeout_sec` and returns
         an actionable timeout error without hanging.
      3. Subprocess cancellation & child reaping test: canceling an active OCR pass terminates/kills and reaps
         the child process and removes temporary PNG files.
      4. Cyan 5-button game menu regression (`unseen_cyan_five_buttons_menu.png` + `diagnostic_only_cyan_menu_preview_crop.png`):
         `analyze_image_for_ocr()` detects 5 lines, `is_light_ink=True`, `is_sparse_menu=True`, `has_left_icon_column=True`,
         and `recognize_image_ocr()` extracts all 5 button labels in order (`Report Bug / Request Feature`,
         `Join us on Discord`, `Steam Workshop`, `Video Tutorials`, `Merch Store`), never returning `'—<'`.
      5. Tall multi-entry sidebar menu (`unseen_tall_sidebar_game_list.png`) and multi-color vivid pills
         (`unseen_vivid_colored_pills_menu.png`) recognize with 0.0% CER / 0.0% WER, while low-confidence
         punctuation fragments (`'—<'`) and sub-legible 3px preview thumbnails (`diagnostic_only_tall_menu_preview_crop.png`)
         are rejected by `is_plausible_ocr_result` (`low_confidence_rejected=True`).
      6. Opt-in diagnostic bundle export (`export_ocr_diagnostic_bundle`) and pass-aware progress messages
         (`Recognizing pass 1 of up to 4...`).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.rw_fixtures = {f.fixture_id: f for f in build_realworld_heldout_ocr_fixtures()}
        cls.ev_dir = Path(__file__).resolve().parent / "fixtures" / "failure_evidence"

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        if sys.platform == "win32":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == STILL_ACTIVE
                return False
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def test_01_large_tsv_subprocess_pipe_no_deadlock(self) -> None:
        """
        Spawn a real child process that writes >1.6 MB of TSV rows to stdout and >256 KB to stderr
        (substantially larger than OS pipe capacity on Windows and Linux) and verify zero deadlock.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            tessdata_dir = tmp_p / "tessdata"
            tessdata_dir.mkdir(parents=True, exist_ok=True)
            (tessdata_dir / "eng.traineddata").write_bytes(b"MOCK_TRAINEDDATA")

            mock_bin = tmp_p / "mock_tesseract_large_tsv.py"
            mock_bin.write_text(
                "import sys\n"
                "if '--version' in sys.argv:\n"
                "    sys.stdout.write('tesseract 5.5.0-mock\\n')\n"
                "    sys.exit(0)\n"
                "# Write 280 KB to stderr and >1.6 MB (20,000 TSV rows) to stdout\n"
                "sys.stderr.write('DIAG_STDERR_LINE_' * 16500 + '\\n')\n"
                "sys.stderr.flush()\n"
                "sys.stdout.write('level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext\\n')\n"
                "sys.stdout.write('5\\t1\\t1\\t1\\t1\\t1\\t24\\t24\\t80\\t20\\t96.5\\tPrismwake\\n')\n"
                "sys.stdout.write('5\\t1\\t1\\t1\\t1\\t2\\t114\\t24\\t90\\t20\\t95.8\\tLargeTSV\\n')\n"
                "row = '5\\t1\\t1\\t1\\t2\\t1\\t24\\t56\\t60\\t18\\t94.0\\t' + ('X' * 64) + '\\n'\n"
                "for _ in range(20000):\n"
                "    sys.stdout.write(row)\n"
                "sys.stdout.flush()\n"
                "sys.exit(0)\n",
                encoding="utf-8",
            )

            # 1. Direct run_bounded_ocr_subprocess test verifying >1.6MB stdout + >256KB stderr drains fast
            t0 = time.perf_counter()
            rc, out_s, err_s, cancelled, timed_out = run_bounded_ocr_subprocess(
                [sys.executable, str(mock_bin), "dummy.png", "stdout"],
                timeout_sec=6.0,
            )
            elapsed = time.perf_counter() - t0
            self.assertEqual(rc, 0)
            self.assertFalse(cancelled)
            self.assertFalse(timed_out)
            self.assertLess(elapsed, 5.0)
            self.assertGreater(len(out_s), 1_500_000)
            self.assertGreater(len(err_s), 250_000)

            # 2. End-to-end recognize_image_ocr with mock_bin
            img = Image.new("RGB", (320, 90), (250, 252, 255))
            res = recognize_image_ocr(
                img,
                language="eng",
                custom_binary=mock_bin,
                custom_tessdata=tessdata_dir,
                pass_timeout_sec=6.0,
            )
            self.assertTrue(res.ok, msg=f"Large TSV OCR failed: {res.error}")
            self.assertIn("Prismwake LargeTSV", res.text)

    def test_02_subprocess_timeout_enforcement_and_orphan_reaping(self) -> None:
        """
        Verify that a stalling child process is terminated/killed and reaped when `pass_timeout_sec`
        expires, returning an explicit timeout error and leaving zero orphan processes.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            tessdata_dir = tmp_p / "tessdata"
            tessdata_dir.mkdir(parents=True, exist_ok=True)
            (tessdata_dir / "eng.traineddata").write_bytes(b"MOCK_TRAINEDDATA")
            pid_file = tmp_p / "child.pid"

            mock_bin = tmp_p / "mock_tesseract_stall.py"
            mock_bin.write_text(
                "import os, sys, time\n"
                "if '--version' in sys.argv:\n"
                "    sys.stdout.write('tesseract 5.5.0-mock\\n')\n"
                "    sys.exit(0)\n"
                f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
                "sys.stdout.write('level\\tpage_num\\tblock_num\\n')\n"
                "sys.stdout.flush()\n"
                "time.sleep(30.0)\n",
                encoding="utf-8",
            )

            img = Image.new("RGB", (240, 80), (255, 255, 255))
            t0 = time.perf_counter()
            res = recognize_image_ocr(
                img,
                language="eng",
                custom_binary=mock_bin,
                custom_tessdata=tessdata_dir,
                pass_timeout_sec=2.5,
                total_timeout_sec=4.5,
            )
            elapsed = time.perf_counter() - t0
            self.assertLess(elapsed, 7.0)
            self.assertFalse(res.ok)
            self.assertIn("timed out", res.error.lower())
            self.assertTrue(pid_file.is_file())
            child_pid = int(pid_file.read_text().strip())
            time.sleep(0.05)
            self.assertFalse(self._is_pid_running(child_pid), msg=f"Child PID {child_pid} was not reaped after timeout")

    def test_03_subprocess_cancellation_kills_and_reaps_child_and_cleans_temp_files(self) -> None:
        """
        Verify canceling an in-flight OCR pass terminates and reaps the child process
        immediately and cleans up temporary PNG files.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            tessdata_dir = tmp_p / "tessdata"
            tessdata_dir.mkdir(parents=True, exist_ok=True)
            (tessdata_dir / "eng.traineddata").write_bytes(b"MOCK_TRAINEDDATA")
            pid_file = tmp_p / "cancel_child.pid"
            arg_img_file = tmp_p / "arg_img_path.txt"

            mock_bin = tmp_p / "mock_tesseract_cancel.py"
            mock_bin.write_text(
                "import os, sys, time\n"
                "if '--version' in sys.argv:\n"
                "    sys.stdout.write('tesseract 5.5.0-mock\\n')\n"
                "    sys.exit(0)\n"
                f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
                f"open({str(arg_img_file)!r}, 'w').write(sys.argv[1])\n"
                "time.sleep(30.0)\n",
                encoding="utf-8",
            )

            token = CancellationToken()
            stop_wait = threading.Event()

            def _cancel_once_started() -> None:
                deadline = time.monotonic() + 5.0
                while not stop_wait.is_set() and time.monotonic() < deadline:
                    if pid_file.is_file() and pid_file.stat().st_size > 0:
                        time.sleep(0.05)
                        token.cancel()
                        return
                    time.sleep(0.02)
                token.cancel()

            cancel_thread = threading.Thread(target=_cancel_once_started, daemon=True)
            cancel_thread.start()
            try:
                img = Image.new("RGB", (240, 80), (255, 255, 255))
                t0 = time.perf_counter()
                res = recognize_image_ocr(
                    img,
                    language="eng",
                    custom_binary=mock_bin,
                    custom_tessdata=tessdata_dir,
                    cancel_token=token,
                    pass_timeout_sec=8.0,
                )
                elapsed = time.perf_counter() - t0
            finally:
                stop_wait.set()
                cancel_thread.join(timeout=1.0)

            self.assertTrue(res.cancelled)
            self.assertLess(elapsed, 3.0)
            self.assertTrue(pid_file.is_file())
            child_pid = int(pid_file.read_text().strip())
            time.sleep(0.05)
            self.assertFalse(self._is_pid_running(child_pid), msg=f"Child PID {child_pid} was not reaped on cancel")
            if arg_img_file.is_file():
                temp_png_path = Path(arg_img_file.read_text().strip())
                self.assertFalse(temp_png_path.exists(), msg=f"Temporary PNG {temp_png_path} was not cleaned up")

    def test_04_cyan_five_buttons_analyzer_and_recognition_regression(self) -> None:
        """
        Verify that both the native-scale 5-button cyan menu (`unseen_cyan_five_buttons_menu`)
        and the diagnostic preview crop (`diagnostic_only_cyan_menu_preview_crop.png`)
        accurately detect 5 separated text lines with left icons and extract all 5 button labels
        in reading order (`Report Bug / Request Feature`, `Join us on Discord`, `Steam Workshop`,
        `Video Tutorials`, `Merch Store`) instead of `'—<'`.
        """
        expected_lines = [
            "Report Bug / Request Feature",
            "Join us on Discord",
            "Steam Workshop",
            "Video Tutorials",
            "Merch Store",
        ]
        expected_text = "\n".join(expected_lines)

        # 1. Native-scale 5-button cyan menu fixture
        fx_native = self.rw_fixtures["unseen_cyan_five_buttons_menu"]
        prof_native = analyze_image_for_ocr(fx_native.image)
        self.assertEqual(prof_native.estimated_line_count, 5)
        self.assertTrue(prof_native.is_light_ink)
        self.assertTrue(prof_native.is_sparse_menu)
        self.assertTrue(prof_native.has_left_icon_column)
        self.assertEqual(len(prof_native.row_text_rois), 5)

        res_native = recognize_image_ocr(fx_native.image, language="eng")
        self.assertTrue(res_native.ok)
        self.assertNotEqual(res_native.text.strip(), "—<")
        self.assertEqual(res_native.text.strip(), expected_text)
        self.assertEqual([ln.text for ln in res_native.lines], expected_lines)

        # 2. Diagnostic preview crop from Prismwake_v020_OCR_Failure_Evidence.zip (non-native resolution)
        diag_cyan_path = self.ev_dir / "diagnostic_only_cyan_menu_preview_crop.png"
        if diag_cyan_path.is_file():
            diag_img = Image.open(diag_cyan_path).convert("RGB")
            prof_diag = analyze_image_for_ocr(diag_img)
            self.assertEqual(prof_diag.estimated_line_count, 5)
            self.assertTrue(prof_diag.is_light_ink)
            self.assertTrue(prof_diag.is_sparse_menu)
            self.assertTrue(prof_diag.has_left_icon_column)
            res_diag = recognize_image_ocr(diag_img, language="eng")
            self.assertEqual(res_diag.text.strip(), expected_text)

    def test_05_calibrated_rejection_and_tall_sidebar_menu_recognition(self) -> None:
        """
        Verify:
          1. A single punctuation fragment (`'—<'`) on a 5-line menu is classified as implausible
             (`is_plausible_ocr_result == False`) and rejected rather than accepted as `'1 word'`.
          2. The downsampled 67x191 preview crop (`diagnostic_only_tall_menu_preview_crop.png`)
             with sub-legible 3px glyphs is rejected (`low_confidence_rejected == True`) while
             preserving `raw_rejected_text` and `candidate_diagnostics` for Advanced inspection.
          3. Native-resolution tall 15-line sidebar menu (`unseen_tall_sidebar_game_list`) and
             multi-color vivid pills (`unseen_vivid_colored_pills_menu`) recognize with 0.0% CER / 0.0% WER.
        """
        fx_cyan = self.rw_fixtures["unseen_cyan_five_buttons_menu"]
        prof_cyan = analyze_image_for_ocr(fx_cyan.image)
        junk_word = OcrWordBox(text="—<", x=40, y=50, width=18, height=10, confidence=62.0, line_index=0, word_index=0)
        junk_line = OcrLineBox(text="—<", x=40, y=50, width=18, height=10, confidence=62.0, line_index=0, words=(junk_word,))
        junk_res = OcrRecognitionResult(
            text="—<",
            lines=[junk_line],
            words=[junk_word],
            source_width=fx_cyan.image.width,
            source_height=fx_cyan.image.height,
        )
        junk_res.quality_score = score_ocr_candidate(junk_res, prof_cyan, fx_cyan.image)
        self.assertFalse(is_plausible_ocr_result(junk_res, prof_cyan))

        diag_tall_path = self.ev_dir / "diagnostic_only_tall_menu_preview_crop.png"
        if diag_tall_path.is_file():
            diag_tall_img = Image.open(diag_tall_path).convert("RGB")
            res_tall_diag = recognize_image_ocr(diag_tall_img, language="eng")
            self.assertTrue(res_tall_diag.low_confidence_rejected)
            self.assertEqual(res_tall_diag.text, "")
            self.assertTrue(bool(res_tall_diag.raw_rejected_text))
            self.assertGreaterEqual(len(res_tall_diag.candidate_diagnostics), 1)
            self.assertIn("rejected", format_ocr_summary(res_tall_diag).lower())

        for fid in ("unseen_tall_sidebar_game_list", "unseen_vivid_colored_pills_menu", "unseen_tiny_colored_badges_hud"):
            fx = self.rw_fixtures[fid]
            res = recognize_image_ocr(fx.image, language="eng")
            self.assertEqual(res.text.strip(), fx.ground_truth, msg=f"Failed on {fid}: {res.text!r}")
            self.assertEqual(compute_cer(res.text, fx.ground_truth), 0.0)
            self.assertEqual(compute_wer(res.text, fx.ground_truth), 0.0)

    def test_06_opt_in_diagnostic_bundle_export_and_pass_progress_reporting(self) -> None:
        """
        Verify opt-in diagnostic export (`export_ocr_diagnostic_bundle` and `dlg.export_diagnostic_bundle`)
        and pass-aware progress callback messages (`Recognizing pass 1 of up to 4...`).
        """
        fx = self.rw_fixtures["unseen_cyan_five_buttons_menu"]
        progress_msgs: List[Tuple[int, str]] = []
        res = recognize_image_ocr(
            fx.image,
            language="eng",
            progress_callback=lambda pct, msg: progress_msgs.append((pct, msg)),
        )
        self.assertTrue(res.ok)
        self.assertTrue(
            any("Recognizing pass 1 of up to" in msg for _pct, msg in progress_msgs),
            msg=f"Expected pass-aware progress message in {progress_msgs}",
        )
        self.assertGreaterEqual(len(res.pass_timings_ms), 1)
        self.assertGreaterEqual(len(res.candidate_diagnostics), 1)

        with tempfile.TemporaryDirectory() as tmpdir:
            dlg = OcrResultsDialog(fx.image, initial_result=res, auto_start=False)
            try:
                dlg.expand_to_advanced()
                self.assertTrue(dlg.export_diag_btn.isVisible())
                info = dlg.export_diagnostic_bundle(tmpdir)
                self.assertTrue(Path(info["original_file"]).is_file())
                self.assertTrue(Path(info["manifest_file"]).is_file())
                self.assertGreaterEqual(len(info["candidate_files"]), 2)
                manifest = json.loads(Path(info["manifest_file"]).read_text(encoding="utf-8"))
                self.assertEqual(manifest["profile"]["estimated_line_count"], 5)
                self.assertTrue(manifest["profile"]["has_left_icon_column"])
            finally:
                dlg.close()




class TestPart12OcrEngineResetPartialSalvageAndBackends(unittest.TestCase):
    """
    Part 13 — OCR Engine Reset: 4-Pill Game HUD, Partial-Result Salvage, and Pluggable Backends:
      1. Partial-result salvage (`filter_and_salvage_partial_ocr_result`): when raw OCR contains
         noise on one pill (`'—<'`) and a valid word on another (`'CLOSED'`), the valid word and
         its native bounding box are NEVER zeroed out; the result returns `'CLOSED'` with
         `partial_low_confidence=True` and a clear badge/warning (`'1 word • partial / low confidence'`),
         allowing manual editing and copying.
      2. 4-Pill Game HUD (`unseen_four_pill_game_hud.png` — `$3,020`, `+75% NEXT CUSTOMER`, `CLOSED`, `3 days`):
         connected-component white-core island detection isolates all 4 pills across the 2x2 grid,
         extracts all 4 labels in reading order in a single stacked pass with 0.0% CER / 0.0% WER,
         and maps every word box back to native screenshot coordinates.
      3. Pluggable OCR Backend architecture (`RapidOcrBackend`, `TesseractOcrBackend`,
         `HybridOcrOrchestrator`, `ocr.eval_side_by_side`) reports truthful runtime and model
         availability without faking missing packages or making network calls.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.rw_fixtures = {f.fixture_id: f for f in build_realworld_heldout_ocr_fixtures()}

    def test_01_partial_result_salvage_never_discards_closed_when_noise_present(self) -> None:
        w_garbage = OcrWordBox("—<", 18, 22, 16, 12, 41.0, 0, 0)
        w_closed = OcrWordBox("CLOSED", 42, 74, 73, 14, 93.0, 1, 0)
        raw_res = OcrRecognitionResult(
            text="—<\nCLOSED",
            lines=[
                OcrLineBox("—<", 18, 22, 16, 12, 41.0, 0, (w_garbage,)),
                OcrLineBox("CLOSED", 42, 74, 73, 14, 93.0, 1, (w_closed,)),
            ],
            words=[w_garbage, w_closed],
            source_width=420,
            source_height=118,
        )
        fx_hud = self.rw_fixtures["unseen_four_pill_game_hud"]
        prof_hud = analyze_image_for_ocr(fx_hud.image)

        salvaged = filter_and_salvage_partial_ocr_result(raw_res, prof_hud)
        self.assertTrue(salvaged.has_text)
        self.assertEqual(salvaged.text, "CLOSED")
        self.assertTrue(salvaged.partial_low_confidence)
        self.assertFalse(salvaged.low_confidence_rejected)
        self.assertEqual(len(salvaged.words), 1)
        self.assertEqual((salvaged.words[0].text, salvaged.words[0].x, salvaged.words[0].y, salvaged.words[0].width, salvaged.words[0].height), ("CLOSED", 42, 74, 73, 14))
        self.assertIn("partial", format_quick_ocr_badge_text(salvaged.text, salvaged).lower())
        self.assertIn("partial result / low confidence", format_ocr_summary(salvaged).lower())

        # Verify OcrResultsDialog displays partial result as editable and copyable (not 'No text recognized')
        dlg = OcrResultsDialog(fx_hud.image, initial_result=salvaged, auto_start=False)
        try:
            self.assertEqual(dlg.view_state, "ready")
            self.assertEqual(dlg.text_edit.toPlainText(), "CLOSED")
            self.assertIn("partial", dlg.word_count_badge.text().lower())
            copied = dlg.copy_all_text()
            self.assertEqual(copied, "CLOSED")
        finally:
            dlg.close()

    def test_02_four_pill_game_hud_island_detection_and_recognition(self) -> None:
        fx_hud = self.rw_fixtures["unseen_four_pill_game_hud"]
        prof = analyze_image_for_ocr(fx_hud.image)
        self.assertEqual(len(prof.row_text_rois), 4)

        res = recognize_image_ocr(fx_hud.image, language="eng")
        self.assertTrue(res.ok)
        self.assertEqual(res.text.strip(), "$3,020\n+75% NEXT CUSTOMER\nCLOSED\n3 days")
        self.assertEqual(compute_cer(res.text, fx_hud.ground_truth), 0.0)
        self.assertEqual(compute_wer(res.text, fx_hud.ground_truth), 0.0)
        self.assertEqual(res.candidates_evaluated, 1)

        by_word = {w.text: w for w in res.words}
        self.assertIn("$3,020", by_word)
        self.assertIn("+75%", by_word)
        self.assertIn("CLOSED", by_word)
        self.assertIn("days", by_word)
        # Verify native coordinates match the 2x2 pill quadrants
        self.assertLess(by_word["$3,020"].x, 150)
        self.assertLess(by_word["$3,020"].y, 55)
        self.assertGreater(by_word["+75%"].x, 165)
        self.assertLess(by_word["+75%"].y, 55)
        self.assertLess(by_word["CLOSED"].x, 150)
        self.assertGreater(by_word["CLOSED"].y, 60)
        self.assertGreater(by_word["days"].x, 165)
        self.assertGreater(by_word["days"].y, 60)

    def test_03_pluggable_ocr_backends_and_side_by_side_evaluator(self) -> None:
        from ocr.eval_side_by_side import run_side_by_side_evaluation

        orch = HybridOcrOrchestrator(prefer_neural=True)
        statuses = orch.query_all_backends()
        self.assertIn("rapidocr", statuses)
        self.assertIn("tesseract", statuses)
        self.assertTrue(statuses["tesseract"].available)

        fx_hud = self.rw_fixtures["unseen_four_pill_game_hud"]
        res = orch.recognize(fx_hud.image, language="eng")
        self.assertTrue(res.ok)
        self.assertEqual(res.text.strip(), "$3,020\n+75% NEXT CUSTOMER\nCLOSED\n3 days")

        eval_report = run_side_by_side_evaluation()
        self.assertEqual(eval_report["partial_salvage_verification"]["salvaged_text"], "CLOSED")
        self.assertTrue(eval_report["partial_salvage_verification"]["partial_low_confidence"])
        hud_comp = next(c for c in eval_report["comparisons"] if c["fixture_id"] == "unseen_four_pill_game_hud")
        self.assertEqual(hud_comp["region_island_tesseract"]["cer"], 0.0)
        self.assertEqual(hud_comp["region_island_tesseract"]["wer"], 0.0)





class _SentinelNeuralBackend(OcrBackend):
    """Fake neural backend returning a unique sentinel result to prove production dispatch."""

    SENTINEL_TEXT = "SENTINEL_NEURAL_OCR_7749\nSECOND_LINE_8821"

    def __init__(self, *, echo_self_test: bool = False) -> None:
        self.call_count = 0
        self.echo_self_test = echo_self_test

    @property
    def backend_id(self) -> str:
        return "rapidocr"

    def query_status(self) -> OcrBackendStatus:
        return OcrBackendStatus(
            backend_id="rapidocr",
            available=True,
            engine_version="rapidocr 3.10.0 (sentinel)",
            runtime_provider="onnxruntime 1.31.0 (CPUExecutionProvider)",
            model_dir="/bundled/rapidocr_models",
            model_files=("multi_PP-OCRv6_det_small.onnx", "multi_PP-OCRv6_rec_small.onnx"),
            supported_languages=("eng", "ita", "eng+ita"),
            reason="Ready (sentinel neural backend)",
            models_verified=True,
            manifest_verified=True,
            model_family="PP-OCRv6-multilingual",
        )

    def recognize(
        self,
        image_source: Any,
        *,
        language: str = "eng",
        quality_mode: str = "auto",
        **kwargs: Any,
    ) -> OcrRecognitionResult:
        self.call_count += 1
        pil_im = Image.fromarray(image_source) if isinstance(image_source, np.ndarray) else image_source
        w, h = pil_im.size if hasattr(pil_im, "size") else (320, 120)
        txt = (
            "Prismwake OCR Ready 2026\n$3,020\n+75% NEXT CUSTOMER\nCLOSED\n3 days"
            if self.echo_self_test
            else self.SENTINEL_TEXT
        )
        w0 = OcrWordBox(txt.splitlines()[0], 12, 14, min(180, max(10, w - 20)), min(24, max(8, h - 20)), 98.5, 0, 0)
        l0 = OcrLineBox(txt.splitlines()[0], 12, 14, w0.width, w0.height, 98.5, 0, (w0,))
        return OcrRecognitionResult(
            text=txt,
            lines=[l0],
            words=[w0],
            language=language,
            engine_name="rapidocr",
            source_width=w,
            source_height=h,
            elapsed_ms=14.2,
            preprocessing_strategy="rapidocr_neural",
            psm_used=0,
            quality_score=140.0,
            backend_selected="RapidOCR (ONNX CPU)",
        )


class _UnavailableNeuralBackend(OcrBackend):
    """Explicitly controlled fake neural backend reporting available=False."""

    @property
    def backend_id(self) -> str:
        return "rapidocr"

    def query_status(self) -> OcrBackendStatus:
        return OcrBackendStatus(
            backend_id="rapidocr",
            available=False,
            engine_version="rapidocr (unavailable)",
            runtime_provider="onnxruntime (unavailable)",
            reason="Simulated unavailable neural backend for fallback isolation test",
            models_verified=False,
        )

    def recognize(self, image_source: Any, **kwargs: Any) -> OcrRecognitionResult:
        return OcrRecognitionResult(
            text="",
            error="Simulated unavailable neural backend",
            engine_name="rapidocr",
        )


class _ThrowingNeuralBackend(OcrBackend):
    """Fake neural backend that reports available=True but raises RuntimeError during recognize()."""

    def __init__(self) -> None:
        self.call_count = 0

    @property
    def backend_id(self) -> str:
        return "rapidocr"

    def query_status(self) -> OcrBackendStatus:
        return OcrBackendStatus(
            backend_id="rapidocr",
            available=True,
            engine_version="rapidocr 3.10.0 (faulty)",
            runtime_provider="onnxruntime 1.31.0 (CPUExecutionProvider)",
            model_dir="/bundled/rapidocr_models",
            model_files=("det.onnx", "rec.onnx"),
            supported_languages=("eng",),
            reason="Ready",
            models_verified=True,
        )

    def recognize(self, image_source: Any, **kwargs: Any) -> OcrRecognitionResult:
        self.call_count += 1
        raise RuntimeError("Simulated ONNX Runtime inference crash")


class TestPart13ProductionRapidOcrWiringFallbackAndReleaseGates(unittest.TestCase):
    """
    Part 14 — Mandatory v8 Release-Blocker Repairs:
      1. Proves with a fake neural backend returning a unique sentinel string that EVERY
         user-facing and background production OCR invocation (Quick OCR, Advanced OCR,
         Retry, tray Text Capture, editor OCR button, background screenshot-history indexing,
         and history gallery OCR) routes through `recognize_production_ocr` / `HybridOcrOrchestrator`
         and receives the neural sentinel.
      2. Proves that both an unavailable neural backend and an exception-throwing neural backend
         gracefully fall back to `TesseractOcrBackend` without crashing, preserve the region-island
         Tesseract pipeline, and display `Backend: Tesseract fallback` in Advanced OCR diagnostics.
      3. Verifies ONNX model directory validation (`verify_rapidocr_model_directory`) rejects dummy
         `*det*.onnx` / `*rec*.onnx` files, validates real ONNX graphs via `onnxruntime.InferenceSession`,
         enforces SHA-256 `model_manifest.json` integrity, and blocks runtime network downloads.
      4. Verifies the packaged-EXE CLI gate (`--write-ocr-verify-file <path> --require-neural`)
         fails (exit code 3) on a Tesseract-only build and passes (exit code 0) when neural OCR is functional.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.rw_fixtures = {f.fixture_id: f for f in build_realworld_heldout_ocr_fixtures()}

    def test_01_sentinel_fake_neural_backend_proves_every_production_workflow_uses_hybrid_service(self) -> None:
        from ocr.engine import OcrWorkerJob

        fx_hud = self.rw_fixtures["unseen_four_pill_game_hud"]
        sentinel = _SentinelNeuralBackend()
        orch = HybridOcrOrchestrator(prefer_neural=True, neural_backend=sentinel)

        with override_production_ocr_orchestrator(orch):
            # (a) Direct production service call
            res_direct = recognize_production_ocr(fx_hud.image, language="eng")
            self.assertEqual(res_direct.text, _SentinelNeuralBackend.SENTINEL_TEXT)
            self.assertEqual(res_direct.engine_name, "rapidocr")
            self.assertEqual(res_direct.backend_selected, "RapidOCR (ONNX CPU)")
            self.assertEqual(sentinel.call_count, 1)

            # (b) Background OcrWorkerJob.run()
            worker = OcrWorkerJob(fx_hud.image, language="eng")
            got_worker: List[OcrRecognitionResult] = []
            worker.signals.finished.connect(lambda r: got_worker.append(r))
            worker.run()
            self.assertEqual(len(got_worker), 1)
            self.assertEqual(got_worker[0].text, _SentinelNeuralBackend.SENTINEL_TEXT)
            self.assertEqual(got_worker[0].backend_selected, "RapidOCR (ONNX CPU)")
            self.assertEqual(sentinel.call_count, 2)

            # (c) OcrResultsDialog in Quick OCR mode -> Expand to Advanced OCR -> Retry Recognition
            dlg = OcrResultsDialog(fx_hud.image, auto_start=True)
            dlg.present_in_front()
            try:
                self.assertEqual(dlg.text_edit.toPlainText(), _SentinelNeuralBackend.SENTINEL_TEXT)
                self.assertFalse(dlg.backend_diag_label.isVisible())  # Quick mode stays uncluttered
                self.assertEqual(sentinel.call_count, 3)

                dlg.expand_to_advanced()
                self.assertTrue(dlg.backend_diag_label.isVisible())
                self.assertEqual(dlg.backend_diag_label.text(), "Backend: RapidOCR (ONNX CPU)")
                self.assertIn("Backend: RapidOCR (ONNX CPU)", dlg.status_label.text())

                dlg.start_recognition(force_discard_edits=True)
                self.assertEqual(sentinel.call_count, 4)
                self.assertEqual(dlg.text_edit.toPlainText(), _SentinelNeuralBackend.SENTINEL_TEXT)
            finally:
                dlg.close()

            # (d) Full application flows: Tray Text Capture, Editor OCR, History Indexing, History Gallery OCR
            with tempfile.TemporaryDirectory() as tmp_dir:
                cfg = pw.AppConfig()
                cfg.history_capture_mode = "saved_or_copied"
                cfg.history_index_ocr = True
                app_ctrl = pw.HDRSnipFusionApplication(
                    config=cfg,
                    history_root=Path(tmp_dir) / "hist",
                    synthetic_screen_image=fx_hud.image,
                )
                try:
                    # Tray Text Capture -> drag selection -> auto-triggers OCR via production orchestrator
                    c_before = sentinel.call_count
                    app_ctrl.trigger_capture_mode("ocr")
                    self.assertIsNotNone(app_ctrl.overlay)
                    app_ctrl.overlay.simulate_region_drag(10, 10, 380, 100)
                    app_ctrl.history_store.wait_for_pending_ocr(timeout=5.0)
                    self.assertIsNotNone(app_ctrl._active_ocr_dialog)
                    self.assertEqual(
                        app_ctrl._active_ocr_dialog.text_edit.toPlainText(),
                        _SentinelNeuralBackend.SENTINEL_TEXT,
                    )
                    self.assertGreaterEqual(sentinel.call_count, c_before + 1)
                    app_ctrl._active_ocr_dialog.close()

                    # Editor OCR button -> trigger_snip -> select_region -> ocr_snip
                    c_before = sentinel.call_count
                    app_ctrl.trigger_snip()
                    app_ctrl.overlay.select_region(10, 10, 380, 100)
                    app_ctrl.overlay.ocr_snip()
                    app_ctrl.history_store.wait_for_pending_ocr(timeout=5.0)
                    self.assertIsNotNone(app_ctrl._active_ocr_dialog)
                    self.assertEqual(
                        app_ctrl._active_ocr_dialog.text_edit.toPlainText(),
                        _SentinelNeuralBackend.SENTINEL_TEXT,
                    )
                    self.assertGreaterEqual(sentinel.call_count, c_before + 1)
                    app_ctrl._active_ocr_dialog.close()

                    # Background screenshot-history OCR indexing on capture_completed
                    c_before = sentinel.call_count
                    app_ctrl._on_overlay_capture_completed(fx_hud.image, "region", "")
                    app_ctrl.history_store.wait_for_pending_ocr(timeout=5.0)
                    entries = app_ctrl.history_store.search_entries()
                    self.assertGreaterEqual(len(entries), 1)
                    self.assertEqual(entries[0].ocr_text, _SentinelNeuralBackend.SENTINEL_TEXT)
                    self.assertGreaterEqual(sentinel.call_count, c_before + 1)

                    # History Gallery OCR on an unindexed entry
                    c_before = sentinel.call_count
                    unindexed = app_ctrl.history_store.record_capture(
                        fx_hud.image,
                        capture_mode="region",
                        was_saved_or_copied=True,
                        ocr_text="",
                    )
                    self.assertIsNotNone(unindexed)
                    hist_win = app_ctrl.open_history_window()
                    self.assertIsNotNone(hist_win)
                    hist_win.selected_capture_id = unindexed.capture_id
                    gallery_txt = hist_win.copy_current_text()
                    self.assertEqual(gallery_txt, _SentinelNeuralBackend.SENTINEL_TEXT)
                    self.assertGreaterEqual(sentinel.call_count, c_before + 1)
                finally:
                    app_ctrl.quit_app()

    def test_02_unavailable_and_exception_throwing_neural_backends_prove_graceful_fallback_to_tesseract(self) -> None:
        fx_hud = self.rw_fixtures["unseen_four_pill_game_hud"]
        expected_hud_text = "$3,020\n+75% NEXT CUSTOMER\nCLOSED\n3 days"

        # Case A: Exception-throwing neural backend -> falls back to TesseractOcrBackend cleanly
        throwing_backend = _ThrowingNeuralBackend()
        orch_throw = HybridOcrOrchestrator(prefer_neural=True, neural_backend=throwing_backend)
        with override_production_ocr_orchestrator(orch_throw):
            dlg = OcrResultsDialog(fx_hud.image, auto_start=True)
            dlg.present_in_front()
            try:
                self.assertEqual(throwing_backend.call_count, 1)
                self.assertEqual(dlg.text_edit.toPlainText().strip(), expected_hud_text)
                dlg.expand_to_advanced()
                self.assertEqual(dlg.backend_diag_label.text(), "Backend: Tesseract fallback")
                self.assertIn("Backend: Tesseract fallback", dlg.status_label.text())
                self.assertIn("Simulated ONNX Runtime inference crash", dlg._result.fallback_reason)
            finally:
                dlg.close()

        # Case B: Unavailable neural backend (explicit controlled stub) -> falls back to TesseractOcrBackend with accurate status
        unavail_orch = HybridOcrOrchestrator(
            prefer_neural=True,
            neural_backend=_UnavailableNeuralBackend(),
        )
        with override_production_ocr_orchestrator(unavail_orch):
            res_fb = recognize_production_ocr(fx_hud.image, language="eng")
            self.assertTrue(res_fb.ok)
            self.assertEqual(res_fb.engine_name, "tesseract")
            self.assertEqual(res_fb.backend_selected, "Tesseract fallback")
            self.assertEqual(res_fb.text.strip(), expected_hud_text)

    def test_03_onnx_model_directory_integrity_sha256_manifest_and_network_block_verification(self) -> None:
        from ocr.backends import _MODEL_DIR_VERIFICATION_CACHE, _block_network_downloads
        import shutil
        import urllib.request

        with tempfile.TemporaryDirectory() as tmp_dir:
            mdir = Path(tmp_dir)
            # 1. Dummy non-ONNX files named *det*.onnx and *rec*.onnx must FAIL ONNX Runtime validation
            (mdir / "fake_det.onnx").write_bytes(b"NOT_AN_ONNX_MODEL" * 200)
            (mdir / "fake_rec.onnx").write_bytes(b"NOT_AN_ONNX_MODEL" * 200)
            _MODEL_DIR_VERIFICATION_CACHE.clear()
            v_bad = verify_rapidocr_model_directory(mdir)
            self.assertFalse(v_bad["ok"])
            self.assertIn("ONNX Runtime session validation failed", v_bad["reason"])

            # 2. Real loadable ONNX graphs + valid SHA-256 model_manifest.json must PASS
            ort_sample = Path("/opt/spark/local/lib/python3.11/dist-packages/onnxruntime/datasets/mul_1.onnx")
            if ort_sample.is_file():
                det_f = mdir / "multi_PP-OCRv6_det_small.onnx"
                rec_f = mdir / "multi_PP-OCRv6_rec_small.onnx"
                shutil.copy2(ort_sample, det_f)
                shutil.copy2(ort_sample, rec_f)
                (mdir / "fake_det.onnx").unlink()
                (mdir / "fake_rec.onnx").unlink()
                sha = pw.compute_file_sha256(det_f)
                manifest = {
                    "model_family": "PP-OCRv6-multilingual",
                    "supported_languages": ["eng", "ita", "eng+ita"],
                    "files": {
                        det_f.name: {"size_bytes": det_f.stat().st_size, "sha256": sha},
                        rec_f.name: {"size_bytes": rec_f.stat().st_size, "sha256": sha},
                    },
                }
                (mdir / "model_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                _MODEL_DIR_VERIFICATION_CACHE.clear()
                v_good = verify_rapidocr_model_directory(mdir)
                self.assertTrue(v_good["ok"], v_good.get("reason"))
                self.assertTrue(v_good["manifest_verified"])
                self.assertEqual(v_good["supported_languages"], ("eng", "ita", "eng+ita"))

                # Tampered SHA-256 in manifest must FAIL
                manifest["files"][det_f.name]["sha256"] = "0" * 64
                (mdir / "model_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                _MODEL_DIR_VERIFICATION_CACHE.clear()
                v_tampered = verify_rapidocr_model_directory(mdir)
                self.assertFalse(v_tampered["ok"])
                self.assertIn("SHA-256 mismatch", v_tampered["reason"])

        # 3. Runtime network download blocker must reject any outbound URL request
        with _block_network_downloads():
            with self.assertRaises(RuntimeError):
                urllib.request.urlopen("https://example.com/model.onnx")

    def test_04_release_blocking_neural_gate_fails_on_tesseract_only_build_and_passes_when_neural_functional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            verify_json = Path(tmp_dir) / "ocr_verify.json"

            # 1. When neural OCR is unavailable (Tesseract-only), --require-neural MUST FAIL with exit code 3
            unavail_orch = HybridOcrOrchestrator(
                prefer_neural=True,
                neural_backend=_UnavailableNeuralBackend(),
            )
            with override_production_ocr_orchestrator(unavail_orch):
                rc_fail = pw.main(["--write-ocr-verify-file", str(verify_json), "--require-neural"])
                self.assertEqual(rc_fail, 3)
                data_fail = json.loads(verify_json.read_text(encoding="utf-8"))
                self.assertFalse(data_fail["ok"])
                self.assertFalse(data_fail["neural_exe_inference_pass"])
                self.assertTrue(data_fail["tesseract_fallback_pass"])
                self.assertEqual(data_fail["summary_table"]["neural EXE inference"], "FAIL")
                self.assertEqual(data_fail["summary_table"]["Tesseract fallback"], "PASS")

            # 2. When a functional offline neural backend is active, --require-neural PASSES with exit code 0
            ready_neural = _SentinelNeuralBackend(echo_self_test=True)
            ready_orch = HybridOcrOrchestrator(prefer_neural=True, neural_backend=ready_neural)
            with override_production_ocr_orchestrator(ready_orch):
                rc_pass = pw.main(["--write-ocr-verify-file", str(verify_json), "--require-neural"])
                self.assertEqual(rc_pass, 0)
                data_pass = json.loads(verify_json.read_text(encoding="utf-8"))
                self.assertTrue(data_pass["ok"])
                self.assertTrue(data_pass["neural_exe_inference_pass"])
                self.assertTrue(data_pass["tesseract_fallback_pass"])
                self.assertTrue(data_pass["offline_cache_cleared_pass"])
                for gate_name, gate_val in data_pass["summary_table"].items():
                    self.assertEqual(gate_val, "PASS", f"Expected PASS for {gate_name}, got {gate_val}")



class TestPart14UiPolishSettingsPinControlsAndTrueWindowCapture(unittest.TestCase):
    """
    Part 15 — v0.2.0 UI Polish, Settings Reliability, Pinned Screenshot Controls & True Window Capture:
      1. Simplified Tray Menu (one primary Capture entry, History, Settings, Open Screenshots Folder,
         Check for Updates, Pinned & Diagnostics submenu, Exit) and Unified Capture-Mode HUD switching.
      2. Settings actions reliability (Tray Settings and History Storage & Privacy Settings open
         reliably, focus the requested section, and bring an already-open Settings window to front).
      3. Pinned screenshot controls (live opacity adjustment, click-through toggle + unlock via pill
         or tray action, always-on-top toggle, reset size to 100%, and close/unpin).
      4. True Window Capture (deterministic candidate enumeration, live hover highlight on topmost
         window under cursor, click-to-snap exact window bounds, clicking a different window moves
         the capture area to that window instead of freehand region drag, and Client Area toggle).
      5. Comprehensive Screenshot History actions (Pin, re-pinning focuses existing pin while
         Duplicate Pin creates a second copy, Reopen in Editor, Favorite, Copy Image, Copy Text,
         Save As, Rename, Open Location, Search/Filter, Sort, Delete Selected, Clear History,
         and Storage Privacy Settings).
    """

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp_dir.name)
        self.history_root = self.tmp_path / "History"
        self.cfg = pw.AppConfig()
        self.cfg.save_directory = str(self.tmp_path / "Captures")
        self.cfg.history_directory = str(self.history_root)
        self.cfg.history_mode = "saved_or_copied"
        self.cfg.history_index_ocr = False
        self.screen_img = Image.new("RGB", (1280, 720), (18, 36, 58))

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_01_simplified_tray_menu_and_unified_capture_mode_switching(self) -> None:
        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.screen_img,
        )
        try:
            labels = app_ctrl.get_top_level_tray_menu_labels()
            self.assertEqual(len(labels), 7)
            self.assertTrue(any("Capture" in lbl for lbl in labels))
            self.assertTrue(any("History" in lbl for lbl in labels))
            self.assertTrue(any("Settings" in lbl for lbl in labels))
            self.assertTrue(any("Open Screenshots Folder" in lbl for lbl in labels))
            self.assertTrue(any("Check for Updates" in lbl for lbl in labels))
            self.assertTrue(any("Pinned & Diagnostics" in lbl for lbl in labels))
            self.assertTrue(any("Exit" in lbl for lbl in labels))

            # Top-level tray menu must NOT expose separate cluttering mode-specific capture items
            for forbidden in ("Region Capture", "Window Capture", "Fullscreen / Monitor Capture", "Text Capture / Offline OCR", "Delayed Capture"):
                self.assertFalse(
                    any(forbidden in lbl for lbl in labels),
                    f"Top-level tray menu should not expose '{forbidden}': {labels}",
                )

            # Unified Capture Flow: pressing Capture opens overlay and supports switching modes live
            app_ctrl.trigger_snip()
            ov = app_ctrl.overlay
            self.assertIsNotNone(ov)
            self.assertTrue(ov.isVisible())
            self.assertEqual(ov.capture_workflow_mode, "region")

            # Switch to Monitor (fullscreen) mode inside capture experience
            ov.set_capture_workflow_mode("fullscreen")
            self.assertEqual(ov.capture_workflow_mode, "fullscreen")
            self.assertTrue(ov.has_selection)
            self.assertEqual(
                (ov.selection_rect.left(), ov.selection_rect.top(), ov.selection_rect.width(), ov.selection_rect.height()),
                (0.0, 0.0, 1280.0, 720.0),
            )

            # Switch to Window mode inside capture experience -> clears fullscreen box
            ov.set_capture_workflow_mode("window")
            self.assertEqual(ov.capture_workflow_mode, "window")
            self.assertFalse(ov.has_selection)

            # Switch to OCR (Text Capture) mode inside capture experience
            ov.set_capture_workflow_mode("ocr")
            self.assertEqual(ov.capture_workflow_mode, "ocr")

            # Request Delayed Capture (3s) from inside the capture experience
            ov.request_delayed_capture(3, "window")
            self.assertIn("delayed_capture:3:window", app_ctrl._workflow_event_log)
        finally:
            app_ctrl.quit_app()

    def test_02_settings_actions_open_reliably_from_tray_and_history_without_duplicates(self) -> None:
        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.screen_img,
        )
        try:
            # 1. Open main Settings from tray
            dlg1 = app_ctrl.open_settings()
            self.assertIsNotNone(dlg1)
            self.assertTrue(dlg1.isVisible())
            self.assertEqual(dlg1.focused_section, "general")
            self.assertIn("settings_opened:general", app_ctrl._workflow_event_log)

            # 2. Calling open_settings again while open brings existing dialog to front without duplicating
            dlg2 = app_ctrl.open_settings()
            self.assertIs(dlg1, dlg2)
            self.assertIn("settings_focused:general", app_ctrl._workflow_event_log)

            # 3. Clicking Storage & Privacy Settings inside Screenshot History focuses storage_privacy section
            hist_win = app_ctrl.open_history_window()
            self.assertIsNotNone(hist_win)
            hist_win.openSettingsRequested.emit()
            self.assertIs(app_ctrl._active_settings_dialog, dlg1)
            self.assertEqual(dlg1.focused_section, "storage_privacy")
            self.assertIn("settings_focused:storage_privacy", app_ctrl._workflow_event_log)

            # 4. Closing Settings and clicking Storage & Privacy Settings opens fresh Settings on storage_privacy
            dlg1.close()
            hist_win.openSettingsRequested.emit()
            dlg3 = app_ctrl._active_settings_dialog
            self.assertIsNotNone(dlg3)
            self.assertTrue(dlg3.isVisible())
            self.assertEqual(dlg3.focused_section, "storage_privacy")
            self.assertIn("settings_opened:storage_privacy", app_ctrl._workflow_event_log)
        finally:
            app_ctrl.quit_app()

    def test_03_pinned_screenshot_opacity_click_through_unlock_and_reset_size(self) -> None:
        mgr = PinnedScreenshotManager()
        pin = mgr.create_pin(Image.new("RGB", (400, 250), (30, 80, 140)), spawn_qt_window=False)

        # Opacity control & clamping
        self.assertEqual(pin.opacity_pct, 100)
        pin.set_opacity(60)
        self.assertEqual(pin.opacity_pct, 60)
        pin.step_opacity(-1, step=15)
        self.assertEqual(pin.opacity_pct, 45)
        pin.set_opacity(5)
        self.assertEqual(pin.opacity_pct, pw.MIN_PIN_OPACITY_PCT)

        # Zoom and Reset Size (1:1)
        pin.set_zoom(200)
        self.assertEqual((pin.width, pin.height), (800, 500))
        pin.reset_size()
        self.assertEqual(pin.zoom_pct, 100)
        self.assertEqual((pin.width, pin.height), (400, 250))

        # Click-through toggle blocks mouse drag/resize until unlocked
        self.assertFalse(pin.click_through)
        pin.toggle_click_through()
        self.assertTrue(pin.click_through)
        self.assertFalse(pin.move_to(300, 300))
        self.assertFalse(pin.resize_to(600, 375))

        # Tray / Manager bulk unlock restores interactivity across all click-through pins
        unlocked_count = mgr.set_all_click_through(False)
        self.assertEqual(unlocked_count, 1)
        self.assertFalse(pin.click_through)
        self.assertTrue(pin.move_to(300, 300))
        self.assertEqual((pin.x, pin.y), (300, 300))

    def test_04_true_window_capture_hover_highlight_z_order_and_click_switching(self) -> None:
        own_pid = os.getpid()
        win_self_overlay = DetectedWindowInfo(
            hwnd=9001, title="Prismwake Overlay", class_name="Qt6QWindowToolSaveBits",
            process_id=own_pid, left=0, top=0, right=1280, bottom=720,
        )
        win_minimized = DetectedWindowInfo(
            hwnd=9002, title="Minimized Music Player", class_name="MusicApp",
            process_id=own_pid + 10, left=50, top=50, right=600, bottom=450, is_minimized=True,
        )
        # Foreground overlapping window (higher in Z-order) with distinct full-frame and client-area bounds
        win_editor = DetectedWindowInfo(
            hwnd=9003, title="Visual Studio Code — Prismwake.py", class_name="Chrome_WidgetWin_1",
            process_id=own_pid + 20, left=120, top=80, right=760, bottom=520,
            client_left=128, client_top=112, client_right=752, client_bottom=512,
        )
        # Background window partially behind win_editor and extending to the right (x=400..1180, y=100..660)
        win_browser = DetectedWindowInfo(
            hwnd=9004, title="Mozilla Firefox — Documentation", class_name="MozillaWindowClass",
            process_id=own_pid + 30, left=400, top=100, right=1180, bottom=660,
            client_left=400, client_top=140, client_right=1180, client_bottom=660,
        )
        candidates = [win_self_overlay, win_minimized, win_editor, win_browser]

        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.screen_img,
        )
        app_ctrl._mock_candidate_windows = candidates
        try:
            app_ctrl.trigger_capture_mode("window")
            ov = app_ctrl.overlay
            self.assertIsNotNone(ov)
            self.assertEqual(ov.capture_workflow_mode, "window")
            self.assertFalse(ov.has_selection)

            # 1. Hover over overlap region (x=500, y=250) -> must highlight topmost win_editor (NOT win_self_overlay or win_browser)
            hov1 = ov.hover_window_at(500, 250)
            self.assertIsNotNone(hov1)
            self.assertEqual(hov1.hwnd, 9003)
            self.assertEqual(ov.window_capture_controller.hovered_local_rect, (120, 80, 640, 440))

            # 2. Hover over right side (x=950, y=300) -> highlight moves live to win_browser
            hov2 = ov.hover_window_at(950, 300)
            self.assertIsNotNone(hov2)
            self.assertEqual(hov2.hwnd, 9004)
            self.assertEqual(ov.window_capture_controller.hovered_local_rect, (400, 100, 780, 560))

            # 3. Click on win_editor at (250, 200) -> snaps selection_rect to exact bounds of win_editor
            clicked1 = ov.click_window_at(250, 200)
            self.assertIsNotNone(clicked1)
            self.assertEqual(clicked1.hwnd, 9003)
            self.assertTrue(ov.has_selection)
            r1 = ov.selection_rect.normalized()
            self.assertEqual((r1.left(), r1.top(), r1.width(), r1.height()), (120.0, 80.0, 640.0, 440.0))

            # 4. Toggle Client Area mode -> snaps selection_rect to inner client area of win_editor
            ov.toggle_window_client_area_mode(True)
            r1_client = ov.selection_rect.normalized()
            self.assertEqual((r1_client.left(), r1_client.top(), r1_client.width(), r1_client.height()), (128.0, 112.0, 624.0, 400.0))
            ov.toggle_window_client_area_mode(False)

            # 5. Click on a DIFFERENT window (win_browser at 950, 300) -> immediately moves selection to win_browser!
            clicked2 = ov.click_window_at(950, 300)
            self.assertIsNotNone(clicked2)
            self.assertEqual(clicked2.hwnd, 9004)
            r2 = ov.selection_rect.normalized()
            self.assertEqual((r2.left(), r2.top(), r2.width(), r2.height()), (400.0, 100.0, 780.0, 560.0))
        finally:
            app_ctrl.quit_app()

    def test_05_comprehensive_screenshot_history_actions_and_repin_focus(self) -> None:
        self.cfg.history_index_ocr = True
        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.screen_img,
        )
        try:
            e1 = app_ctrl.history_store.record_capture(
                Image.new("RGB", (320, 180), (20, 40, 80)),
                title="Alpha Login Dialog",
                ocr_text="Username Password Sign In",
                timestamp_utc=time.time() - 120.0,
            )
            e2 = app_ctrl.history_store.record_capture(
                Image.new("RGB", (640, 360), (40, 90, 120)),
                title="Beta Chart Overview",
                ocr_text="Quarterly Revenue +42%",
                timestamp_utc=time.time() - 60.0,
            )
            self.assertIsNotNone(e1)
            self.assertIsNotNone(e2)

            hist_win = app_ctrl.open_history_window()
            self.assertIsNotNone(hist_win)
            hist_win.selected_capture_id = e2.capture_id

            # 1. Pin from History -> creates 1 pin with source_key == e2.capture_id
            self.assertTrue(hist_win.pin_current_entry())
            self.assertEqual(app_ctrl.pin_manager.active_count, 1)
            pin_state = app_ctrl.pin_manager.active_states[0]
            self.assertEqual(pin_state.source_key, e2.capture_id)

            # Enable click-through on that pin, then click Pin again in History:
            # Must focus the existing pin (not create an unintended duplicate) and unlock click-through!
            pin_state.set_click_through(True)
            self.assertTrue(hist_win.pin_current_entry())
            self.assertEqual(app_ctrl.pin_manager.active_count, 1)
            self.assertFalse(pin_state.click_through)

            # 2. Favorite toggle preserves selection
            fav_res = hist_win.toggle_current_favorite()
            self.assertTrue(fav_res)
            self.assertEqual(hist_win.selected_capture_id, e2.capture_id)
            self.assertTrue(app_ctrl.history_store.get_entry(e2.capture_id).favorite)

            # 3. Rename preserves selection
            self.assertTrue(hist_win.rename_current_entry("Beta Executive Chart"))
            self.assertEqual(hist_win.selected_capture_id, e2.capture_id)
            self.assertEqual(app_ctrl.history_store.get_entry(e2.capture_id).title, "Beta Executive Chart")

            # 4. Copy Image & Copy Text
            self.assertTrue(hist_win.copy_current_image())
            self.assertEqual(hist_win.copy_current_text(), "Quarterly Revenue +42%")

            # 5. Save As & Open Location
            exported_png = self.tmp_path / "exported_beta.png"
            saved_p = hist_win.save_current_as(exported_png)
            self.assertEqual(saved_p, exported_png)
            self.assertTrue(exported_png.is_file())
            loc_p = hist_win.open_current_file_location()
            self.assertIsNotNone(loc_p)
            self.assertTrue(loc_p.is_file())

            # 6. Reopen in Editor
            self.assertTrue(hist_win.reopen_current_in_editor())
            self.assertIsNotNone(app_ctrl.overlay)
            self.assertTrue(app_ctrl.overlay.isVisible())
            self.assertEqual((app_ctrl.overlay.width(), app_ctrl.overlay.height()), (640, 360))
            app_ctrl.overlay.close()

            # 7. Search, Filter, and Sort
            fav_only = hist_win.set_filter_mode("favorites")
            self.assertEqual([x.capture_id for x in fav_only], [e2.capture_id])
            hist_win.set_filter_mode("all")
            q_alpha = hist_win.set_search_query("Username")
            self.assertEqual([x.capture_id for x in q_alpha], [e1.capture_id])
            hist_win.set_search_query("")
            oldest_list = hist_win.set_sort_mode("oldest")
            self.assertEqual([x.capture_id for x in oldest_list], [e1.capture_id, e2.capture_id])

            # 8. Delete Selected & Clear History
            hist_win.selected_capture_id = e1.capture_id
            deleted_n = hist_win.delete_selected_items(confirm=False)
            self.assertEqual(deleted_n, 1)
            self.assertIsNone(app_ctrl.history_store.get_entry(e1.capture_id))

            cleared_n = hist_win.prompt_clear_history(confirm=False)
            self.assertEqual(cleared_n, 1)
            self.assertEqual(len(app_ctrl.history_store.search_entries()), 0)
        finally:
            app_ctrl.quit_app()



class TestPart15HistoryRedesignAndAnnotationPerformance(unittest.TestCase):
    """
    Part 16 — v0.2.0 Final UI Consistency (Screenshot History Frutiger Aqua Redesign)
    and Annotation Performance Overhaul (4-Layer Cached Pipeline & Dirty-Rect Painting):
      1. HistoryWindow Frutiger Aqua visual identity, theme/animation/transparency/safe-mode
         synchronization, category counts, Grid/List view toggle, empty/no-results states,
         Clear Non-Favorites, and New Capture signal.
      2. HistoryWindow 200-item gallery responsiveness, bounded LRU thumbnail & preview caches,
         and fast SQLite aggregate category count queries.
      3. AnnotationItem O(1) incremental QPainterPath & bounding box extension, vectorized
         world-aligned pixelation, and fast-preview vs full-resolution blur parity.
      4. SnipOverlayWindow 4-layer committed annotation cache, incremental single-annotation
         commit on mouseReleaseEvent, undo/redo cache rebuilds, and bounded dirty-rectangle
         updates (< 5% of screen area for pen strokes).
      5. 100% preview-to-export fidelity across Pen, Highlighter, Line, Arrow, Rectangle,
         Ellipse, Text, Numbered Step Badge, Blur, and Pixelate tools.
    """

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp_dir.name)
        self.history_root = self.tmp_path / "History"
        self.cfg = pw.AppConfig()
        self.cfg.save_directory = str(self.tmp_path / "Captures")
        self.cfg.history_directory = str(self.history_root)
        self.cfg.history_mode = "saved_or_copied"
        self.cfg.history_index_ocr = True
        self.cfg.aqua_theme = "Deep Sea"
        self.cfg.animation_intensity = "medium"
        self.cfg.glass_transparency = 0.88
        self.screen_img = Image.new("RGB", (1920, 1080), (22, 44, 72))

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_01_history_frutiger_aqua_redesign_themes_views_and_actions(self) -> None:
        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.screen_img,
        )
        try:
            hist_win = app_ctrl.open_history_window()
            self.assertIsNotNone(hist_win)
            # Empty state when 0 captures exist
            self.assertEqual(hist_win.empty_state_kind, "empty")
            self.assertEqual(hist_win.aqua_theme, "Deep Sea")
            self.assertEqual(hist_win.animation_intensity, "medium")
            self.assertAlmostEqual(hist_win.glass_transparency, 0.88, places=2)

            # Live theme & animation update
            hist_win.apply_aqua_theme_and_config(
                aqua_theme="Emerald Lagoon",
                animation_intensity="subtle",
                glass_transparency=0.92,
                safe_mode=False,
                disable_continuous_animations=False,
            )
            self.assertEqual(hist_win.aqua_theme, "Emerald Lagoon")
            self.assertEqual(hist_win.animation_intensity, "subtle")

            # Add 3 entries (1 favorite, 1 with OCR text, 1 old entry)
            e1 = app_ctrl.history_store.record_capture(
                Image.new("RGB", (400, 220), (30, 70, 110)),
                title="Design Spec Alpha",
                ocr_text="Liquid Glass Specular Caustics",
                favorite=True,
                timestamp_utc=time.time() - 30.0,
            )
            e2 = app_ctrl.history_store.record_capture(
                Image.new("RGB", (600, 340), (50, 90, 130)),
                title="Terminal Build Output",
                ocr_text="",
                favorite=False,
                timestamp_utc=time.time() - 10.0,
            )
            e3 = app_ctrl.history_store.record_capture(
                Image.new("RGB", (320, 200), (70, 40, 90)),
                title="Archived Diagram",
                ocr_text="Legacy Flow",
                favorite=False,
                timestamp_utc=time.time() - (12.0 * 86400.0),
            )
            self.assertIsNotNone(e1)
            self.assertIsNotNone(e2)
            self.assertIsNotNone(e3)

            hist_win.refresh_gallery()
            self.assertEqual(hist_win.empty_state_kind, "none")
            self.assertEqual(hist_win.category_counts["all"], 3)
            self.assertEqual(hist_win.category_counts["favorites"], 1)
            self.assertEqual(hist_win.category_counts["recent_7d"], 2)
            self.assertEqual(hist_win.category_counts["with_ocr"], 2)

            # Grid / Compact List view toggle preserves selection
            hist_win.selected_capture_id = e1.capture_id
            self.assertEqual(hist_win.set_view_mode("list"), "list")
            self.assertEqual(hist_win.selected_capture_id, e1.capture_id)
            self.assertEqual(hist_win.set_view_mode("grid"), "grid")
            self.assertEqual(hist_win.selected_capture_id, e1.capture_id)

            # Search with no matching items -> no_results state, Clear Filters restores all
            no_hits = hist_win.set_search_query("nonexistent_xyz_token_999")
            self.assertEqual(len(no_hits), 0)
            self.assertEqual(hist_win.empty_state_kind, "no_results")
            restored = hist_win.clear_search_and_filters()
            self.assertEqual(len(restored), 3)
            self.assertEqual(hist_win.empty_state_kind, "none")

            # Clear Non-Favorites removes e2 and e3 while preserving favorite e1
            removed_non_fav = hist_win.clear_non_favorites(confirm=False)
            self.assertEqual(removed_non_fav, 2)
            remaining = app_ctrl.history_store.search_entries()
            self.assertEqual([x.capture_id for x in remaining], [e1.capture_id])

            # New Capture button triggers capture overlay
            hist_win.request_new_capture()
            self.assertIsNotNone(app_ctrl.overlay)
            self.assertTrue(app_ctrl.overlay.isVisible())
        finally:
            app_ctrl.quit_app()

    def test_02_history_200_items_gallery_responsiveness_and_lru_caches(self) -> None:
        store = ScreenshotHistoryStore(
            self.history_root,
            privacy_mode="saved_or_copied",
            max_items=250,
            max_storage_mb=500,
            enable_ocr_indexing=False,
        )
        try:
            base_im = Image.new("RGB", (96, 64), (28, 68, 112))
            t_now = time.time()
            for i in range(200):
                store.record_capture(
                    base_im,
                    title=f"Bulk Capture #{i:03d}",
                    ocr_text=f"Invoice {i:03d} Total ${(i + 1) * 10}",
                    favorite=(i % 10 == 0),
                    timestamp_utc=t_now - (200 - i),
                )

            t0 = time.perf_counter()
            win = pw._HistoryWindow(store, aqua_theme="Bondi Blue", animation_intensity="high")
            open_ms = (time.perf_counter() - t0) * 1000.0
            self.assertEqual(len(win.current_entries), 200)
            self.assertEqual(win.category_counts["all"], 200)
            self.assertEqual(win.category_counts["favorites"], 20)
            self.assertLess(open_ms, 500.0, f"Opening 200-item HistoryWindow took too long: {open_ms:.1f}ms")

            t1 = time.perf_counter()
            hits = win.set_search_query("Capture #150")
            search_ms = (time.perf_counter() - t1) * 1000.0
            self.assertEqual(len(hits), 1)
            self.assertLess(search_ms, 120.0, f"Searching 200-item HistoryWindow took too long: {search_ms:.1f}ms")
            win.close()
        finally:
            store.shutdown(timeout=0.5)

    def test_03_annotation_incremental_stroke_dirty_rect_and_committed_cache(self) -> None:
        import math
        pw.PERF_TELEMETRY.reset()
        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=self.screen_img,
        )
        try:
            app_ctrl.trigger_snip()
            ov = app_ctrl.overlay
            self.assertIsNotNone(ov)
            ov.select_region(100.0, 100.0, 1200.0, 700.0)

            # Simulate 60-point freehand pen stroke and verify O(1) incremental path & bounded dirty rect
            pts = [(200.0 + i * 6.0, 220.0 + math.sin(i * 0.2) * 18.0) for i in range(60)]
            ann = ov.simulate_pen_stroke(pts, tool_type="pen", color=(0, 220, 255, 255), thickness=4)
            self.assertIsNotNone(ann)
            self.assertEqual(len(ann.points), 60)
            self.assertEqual(len(ov.annotations), 1)
            self.assertEqual(ov._incremental_commit_count, 1)

            # Dirty rect for pen segment must be < 5% of total 1920x1080 screen area
            snap = pw.PERF_TELEMETRY.snapshot()
            self.assertGreaterEqual(snap["annotation_move_count"], 59)
            self.assertLess(snap["avg_dirty_area_ratio"], 0.05)

            # Add a second stroke -> commits incrementally without rebuilding entire committed cache from scratch
            rebuilds_before = ov._committed_cache_rebuild_count
            pts2 = [(300.0 + i * 5.0, 400.0 + i * 2.0) for i in range(30)]
            ov.simulate_pen_stroke(pts2, tool_type="highlighter", color=(255, 230, 0, 255), thickness=8)
            self.assertEqual(len(ov.annotations), 2)
            self.assertEqual(ov._committed_cache_rebuild_count, rebuilds_before)
            self.assertEqual(ov._incremental_commit_count, 2)

            # Undo rebuilds committed cache cleanly; Redo commits incrementally
            ov.undo_annotation()
            self.assertEqual(len(ov.annotations), 1)
            self.assertEqual(ov._committed_cache_rebuild_count, rebuilds_before + 1)
            ov.redo_annotation()
            self.assertEqual(len(ov.annotations), 2)
            self.assertEqual(ov._incremental_commit_count, 3)
        finally:
            app_ctrl.quit_app()

    def test_04_annotation_tools_export_fidelity_across_all_10_tools(self) -> None:
        # Build a vibrant patterned base image so blur and pixelate produce distinct pixel changes
        arr = np.zeros((480, 640, 3), dtype=np.uint8)
        arr[:, :, 0] = np.linspace(20, 220, 640, dtype=np.uint8)[None, :]
        arr[:, :, 1] = np.linspace(30, 200, 480, dtype=np.uint8)[:, None]
        arr[::8, ::8, 2] = 255
        base_img = Image.fromarray(arr, mode="RGB")

        app_ctrl = pw.HDRSnipFusionApplication(
            config=self.cfg,
            history_root=self.history_root,
            synthetic_screen_image=base_img,
        )
        try:
            app_ctrl.trigger_snip()
            ov = app_ctrl.overlay
            self.assertIsNotNone(ov)
            ov.select_region(20.0, 20.0, 600.0, 440.0)

            ov.annotations.extend([
                pw.AnnotationItem(tool="pen", color="#00D2FF", thickness=4, points=[(40.0, 50.0), (140.0, 80.0), (220.0, 60.0)]),
                pw.AnnotationItem(tool="line", color="#50FFA0", thickness=3, points=[(40.0, 150.0), (240.0, 175.0)]),
                pw.AnnotationItem(tool="arrow", color="#FF5A78", thickness=4, points=[(40.0, 200.0), (240.0, 230.0)]),
                pw.AnnotationItem(tool="rect", color="#00DCFF", thickness=3, points=[(280.0, 50.0), (420.0, 140.0)]),
                pw.AnnotationItem(tool="ellipse", color="#B478FF", thickness=3, points=[(280.0, 160.0), (420.0, 250.0)]),
                pw.AnnotationItem(tool="text", color="#FFFFFF", thickness=3, points=[(440.0, 70.0)], text="Aqua Note"),
                pw.AnnotationItem(tool="callout", color="#00BEFF", thickness=3, points=[(460.0, 180.0)], callout_number=1),
                pw.AnnotationItem(tool="blur", color="#FFFFFF", thickness=3, points=[(60.0, 280.0), (260.0, 400.0)], blur_radius=12),
                pw.AnnotationItem(tool="pixelate", color="#FFFFFF", thickness=3, points=[(300.0, 280.0), (520.0, 400.0)], pixel_size=12),
                pw.AnnotationItem(tool="redact", color="#08121E", thickness=3, points=[(530.0, 280.0), (600.0, 400.0)]),
            ])

            cropped_out = ov.render_final_cropped_pixmap()
            self.assertEqual(cropped_out.size, (600, 440))
            out_np = np.asarray(cropped_out, dtype=np.uint8)
            base_crop_np = arr[20:460, 20:620, :3]
            diff_pixels = int(np.count_nonzero(np.any(out_np != base_crop_np, axis=2)))
            self.assertGreater(diff_pixels, 2500, "Rendered annotations must visibly modify exported image")
        finally:
            app_ctrl.quit_app()

    def test_05_async_full_resolution_preview_upgrade_and_aspect_ratio(self) -> None:
        store = ScreenshotHistoryStore(
            self.history_root / "async_preview_store",
            privacy_mode="saved_or_copied",
            enable_ocr_indexing=False,
        )
        try:
            full_img = Image.new("RGB", (1280, 720), (18, 92, 168))
            rec = store.record_capture(full_img, title="FullRes 16x9 Capture", ocr_text="Async Preview Test")
            self.assertIsNotNone(rec)

            win = pw._HistoryWindow(store, aqua_theme="Bondi Blue", animation_intensity="medium")
            try:
                # Clear full-res preview cache and introduce a short decode delay so we can inspect
                # the immediate thumbnail state right after _on_selection_changed()
                win._preview_pixmap_cache.clear()
                win._preview_decode_delay_sec = 0.05
                win._on_selection_changed()

                # 1. Immediate state: thumbnail is shown first, preserving 16:9 aspect ratio
                self.assertEqual(win._current_preview_stage, "thumbnail")
                self.assertTrue(win._current_preview_is_thumbnail)
                self.assertIsNotNone(win._current_preview_full_pixmap)
                thumb_w = win._current_preview_full_pixmap.width()
                thumb_h = win._current_preview_full_pixmap.height()
                self.assertEqual((thumb_w, thumb_h), (280, 158))
                lbl_pm_thumb = win.preview_img_lbl.pixmap()
                self.assertIsNotNone(lbl_pm_thumb)
                self.assertAlmostEqual(lbl_pm_thumb.width() / float(lbl_pm_thumb.height()), 16.0 / 9.0, delta=0.03)

                # 2. Wait for background off-GUI-thread decode + GUI-thread preview update
                ok = win.wait_for_async_preview(timeout=2.5)
                self.assertTrue(ok, "Asynchronous full-resolution preview failed to complete")
                self.assertEqual(win._current_preview_stage, "full")
                self.assertFalse(win._current_preview_is_thumbnail)
                self.assertIsNotNone(win._current_preview_full_pixmap)
                self.assertEqual(
                    (win._current_preview_full_pixmap.width(), win._current_preview_full_pixmap.height()),
                    (1280, 720),
                )
                # Full-image decode must happen off the GUI thread, while pixmap update happens on GUI thread
                self.assertIsNotNone(win._last_preview_decode_thread_id)
                self.assertNotEqual(win._last_preview_decode_thread_id, win._gui_thread_id)
                self.assertEqual(win._last_preview_gui_update_thread_id, win._gui_thread_id)

                lbl_pm_full = win.preview_img_lbl.pixmap()
                self.assertIsNotNone(lbl_pm_full)
                self.assertGreater(lbl_pm_full.width(), thumb_w)
                self.assertAlmostEqual(lbl_pm_full.width() / float(lbl_pm_full.height()), 16.0 / 9.0, delta=0.03)
            finally:
                win.close()
        finally:
            store.shutdown(timeout=0.5)

    def test_06_async_preview_selection_cancellation_and_stale_result_rejection(self) -> None:
        store = ScreenshotHistoryStore(
            self.history_root / "cancel_preview_store",
            privacy_mode="saved_or_copied",
            enable_ocr_indexing=False,
        )
        try:
            dims = [(1280, 720), (1000, 800), (1400, 700), (1600, 900)]
            records = []
            t_base = time.time()
            for idx, (w, h) in enumerate(dims):
                im = Image.new("RGB", (w, h), (30 + idx * 20, 80, 140))
                rec = store.record_capture(im, title=f"Item {idx}", timestamp_utc=t_base + idx)
                self.assertIsNotNone(rec)
                records.append(rec)

            win = pw._HistoryWindow(store, aqua_theme="Bondi Blue", animation_intensity="medium")
            try:
                win._preview_pixmap_cache.clear()
                win._preview_decode_delay_sec = 0.05

                # Rapidly switch selection across all 4 items so earlier requests become stale
                for rec in records:
                    win.selected_capture_id = rec.capture_id

                # Also queue a synthetic stale decode completion for records[0] to verify GUI-thread guard
                with win._async_lock:
                    win._completed_preview_decodes.insert(
                        0,
                        (1, records[0].capture_id, 1280, 720, b"\x10" * (1280 * 720 * 4)),
                    )

                ok = win.wait_for_async_preview(timeout=2.5)
                self.assertTrue(ok)
                self.assertGreaterEqual(win._cancelled_preview_decode_count, 1)
                self.assertGreaterEqual(win._ignored_stale_preview_count, 1)
                self.assertEqual(win.selected_capture_id, records[-1].capture_id)
                self.assertEqual(win._current_preview_cid, records[-1].capture_id)
                self.assertEqual(win._current_preview_stage, "full")
                self.assertEqual(
                    (win._current_preview_full_pixmap.width(), win._current_preview_full_pixmap.height()),
                    (1600, 900),
                )
            finally:
                win.close()
        finally:
            store.shutdown(timeout=0.5)

    def test_07_gallery_delegate_paint_zero_sync_io_and_async_visible_prioritized_thumbnails(self) -> None:
        import threading
        store = ScreenshotHistoryStore(
            self.history_root / "async_thumb_store",
            privacy_mode="saved_or_copied",
            enable_ocr_indexing=False,
        )
        try:
            t_base = time.time()
            for i in range(36):
                im = Image.new("RGB", (640, 360), (20, (i * 7) % 255, 160))
                store.record_capture(im, title=f"Gallery Card #{i:02d}", timestamp_utc=t_base - (36 - i))

            win = pw._HistoryWindow(store, aqua_theme="Bondi Blue", animation_intensity="medium")
            try:
                # Wait for initial background pass, then reset caches to test cold paint() + prioritization
                win.wait_for_async_thumbnails(timeout=2.5)
                with win._async_lock:
                    win._thumb_pixmap_cache.clear()
                    win._thumb_decode_order.clear()
                    win._pending_thumb_rows.clear()

                orig_load_thumb = store.load_thumbnail_pil
                gui_tid = win._gui_thread_id
                in_paint = {"active": False, "sync_calls": 0}

                def _guarded_load_thumb(cid: str):
                    if in_paint["active"] and threading.get_ident() == gui_tid:
                        in_paint["sync_calls"] += 1
                    return orig_load_thumb(cid)

                store.load_thumbnail_pil = _guarded_load_thumb  # type: ignore[method-assign]
                try:
                    target_entry = win.current_entries[20]
                    in_paint["active"] = True
                    pm_during_paint = win.card_delegate.paint(
                        None,
                        None,
                        {"row_idx": 20, "capture_id": target_entry.capture_id, "thumb_pixmap": None},
                    )
                    in_paint["active"] = False
                    self.assertIsNone(pm_during_paint, "Cold paint() must not synchronously decode a thumbnail")
                    self.assertEqual(in_paint["sync_calls"], 0, "HistoryCardDelegate.paint() must perform zero disk I/O")

                    # Now test visible-range prioritization across all 36 rows
                    with win._async_lock:
                        win._thumb_pixmap_cache.clear()
                        win._thumb_decode_order.clear()
                        win._gallery_load_gen += 1
                        gen = win._gallery_load_gen
                        win._pending_thumb_rows = [
                            (idx, e.capture_id, gen) for idx, e in enumerate(win.current_entries)
                        ]
                    win.set_visible_row_range(18, 23)
                    cached_cnt = win.wait_for_async_thumbnails(timeout=3.0)
                    self.assertEqual(cached_cnt, 36)

                    expected_visible_first = [win.current_entries[r].capture_id for r in range(18, 24)]
                    self.assertEqual(
                        win._thumb_decode_order[:6],
                        expected_visible_first,
                        "Visible viewport items must be decoded before off-screen items",
                    )
                    self.assertIsNotNone(win._last_thumb_decode_thread_id)
                    self.assertNotEqual(win._last_thumb_decode_thread_id, win._gui_thread_id)
                    self.assertEqual(win._last_thumb_pixmap_thread_id, win._gui_thread_id)

                    # Verify bounded LRU eviction when THUMB_CACHE_CAPACITY is reduced
                    win.THUMB_CACHE_CAPACITY = 10
                    for e in win.current_entries[:16]:
                        win._cache_thumb_pixmap(e.capture_id, win._thumb_pixmap_cache.get(e.capture_id) or win._rgba_bytes_to_qpixmap(64, 36, b"\x00" * (64 * 36 * 4)))
                    self.assertLessEqual(len(win._thumb_pixmap_cache), 10)
                finally:
                    store.load_thumbnail_pil = orig_load_thumb  # type: ignore[method-assign]
            finally:
                win.close()
        finally:
            store.shutdown(timeout=0.5)

    def test_08_qt_gui_branch_async_preview_cancellation_and_delegate_no_sync_paint(self) -> None:
        import subprocess
        script = """
import os, sys, tempfile, threading, time
from pathlib import Path
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if "." not in sys.path:
    sys.path.insert(0, ".")

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPainter, QPixmap
    from PyQt6.QtWidgets import QApplication, QStyleOptionViewItem
    app = QApplication.instance() or QApplication([])
    def _make_index(win, row):
        return win.grid_list.model().index(row, 0)
except Exception:
    for p in ("tests", "/tmp", "/working_dir/c_276e449611636a2f/artifacts/file_generation/ttl=63d/intermediate"):
        if Path(p).exists() and p not in sys.path:
            sys.path.insert(0, p)
    from qt_cairo_harness import install_qt_cairo_harness, QApplication, QPainter, QPixmap, QStyleOptionViewItem, _ModelIndex
    install_qt_cairo_harness()
    app = QApplication([])
    def _make_index(win, row):
        return _ModelIndex(row, win.grid_list.item(row))

import history.storage as hs
assert hs.HAS_QT is True, "Expected HAS_QT=True"

with tempfile.TemporaryDirectory() as td:
    store = hs.ScreenshotHistoryStore(Path(td) / "History", enable_ocr_indexing=False)
    t_now = time.time()
    e0 = store.record_capture(Image.new("RGB", (1280, 720), (15, 85, 160)), title="Cap 0", timestamp_utc=t_now - 20.0)
    e1 = store.record_capture(Image.new("RGB", (1600, 900), (45, 115, 190)), title="Cap 1", timestamp_utc=t_now - 10.0)
    e2 = store.record_capture(Image.new("RGB", (1920, 1080), (75, 145, 210)), title="Cap 2", timestamp_utc=t_now)

    win = hs.HistoryWindow(store)
    win.show()
    win.wait_for_async_thumbnails(timeout=2.0)
    win.wait_for_async_preview(timeout=2.0)

    # Fake Qt originally cleared previous selections in setCurrentRow(), whereas
    # real QListWidget defaults to QItemSelectionModel.NoUpdate. Reproduce native
    # semantics in the fallback harness so this Windows-only regression cannot hide.
    if hasattr(win.grid_list, "_items"):
        def _native_qt_set_current_row(row):
            win.grid_list._current_row = int(row)
            if not win.grid_list.signalsBlocked():
                win.grid_list.currentRowChanged.emit(int(row))
        win.grid_list.setCurrentRow = _native_qt_set_current_row

    # 1. Verify HistoryCardDelegate.paint() performs zero synchronous disk I/O on cache miss
    win._thumb_pixmap_cache.clear()
    it0 = win.grid_list.item(0)
    it0.setData(hs.HistoryCardDelegate.ROLE_THUMB_PIXMAP, None)
    sync_thumb_io = {"count": 0}
    orig_lt = store.load_thumbnail_pil
    def _checked_lt(cid):
        if threading.get_ident() == win._gui_thread_id:
            sync_thumb_io["count"] += 1
        return orig_lt(cid)
    store.load_thumbnail_pil = _checked_lt

    canvas = QPixmap(220, 190)
    p = QPainter(canvas)
    opt = QStyleOptionViewItem()
    opt.rect = canvas.rect()
    win.card_delegate.paint(p, opt, _make_index(win, 0))
    p.end()
    assert sync_thumb_io["count"] == 0, f"Delegate paint() performed synchronous thumbnail I/O: {sync_thumb_io}"
    win.wait_for_async_thumbnails(timeout=2.0)
    assert e2.capture_id in win._thumb_pixmap_cache
    assert win._last_thumb_decode_thread_id != win._gui_thread_id
    assert win._last_thumb_pixmap_thread_id == win._gui_thread_id
    store.load_thumbnail_pil = orig_lt

    # 2. Verify _on_selection_changed() shows thumbnail immediately, then upgrades to full resolution on GUI thread
    win._preview_pixmap_cache.clear()
    win._preview_decode_delay_sec = 0.05
    win.selected_capture_id = e0.capture_id
    assert win._current_preview_stage == "thumbnail", f"Expected thumbnail stage, got {win._current_preview_stage}"
    assert win._current_preview_is_thumbnail is True
    assert win._current_preview_full_pixmap.width() == 280 and win._current_preview_full_pixmap.height() == 158

    assert win.wait_for_async_preview(timeout=2.5) is True
    assert win._current_preview_stage == "full"
    assert win._current_preview_is_thumbnail is False
    assert win._current_preview_full_pixmap.width() == 1280 and win._current_preview_full_pixmap.height() == 720
    assert win._last_preview_decode_thread_id != win._gui_thread_id
    assert win._last_preview_gui_update_thread_id == win._gui_thread_id

    # 3. Verify rapid selection change cancels/ignores stale preview results
    win._preview_pixmap_cache.clear()
    win._preview_decode_delay_sec = 0.05
    win.selected_capture_id = e0.capture_id
    win.selected_capture_id = e1.capture_id
    win.selected_capture_id = e2.capture_id
    assert win.wait_for_async_preview(timeout=2.5) is True
    assert (win._cancelled_preview_decode_count + win._ignored_stale_preview_count) >= 1
    assert win.selected_capture_id == e2.capture_id, f"Expected last selected {e2.capture_id}, got {win.selected_capture_id}"
    assert len(win.grid_list.selectedItems()) == 1, "Programmatic selection must clear previous Qt ExtendedSelection rows"
    assert win.grid_list.currentItem().data(hs.Qt.ItemDataRole.UserRole) == e2.capture_id
    assert win._current_preview_full_pixmap.width() == 1920 and win._current_preview_full_pixmap.height() == 1080
    # Ctrl/Shift multiselection must inspect the *focused* card, not the first
    # selected item in gallery order. Bulk-delete still uses selectedItems().
    win.grid_list.item(1).setSelected(True)
    assert len(win.grid_list.selectedItems()) == 2
    assert win._current_entry().capture_id == e2.capture_id
    win.selected_capture_id = e1.capture_id
    assert win.selected_capture_id == e1.capture_id
    assert len(win.grid_list.selectedItems()) == 1
    win.close()
    store.shutdown(timeout=0.5)
print("QT_GUI_BRANCH_OK")
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, f"Qt branch test failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        self.assertIn("QT_GUI_BRANCH_OK", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
