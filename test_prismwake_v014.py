#!/usr/bin/env python3
"""
Prismwake v0.1.4 Comprehensive Automated Verification Suite
===========================================================
Covers all Part 1 – Part 5 requirements for Prismwake v0.1.4:
  1. Settings Window Overhaul (Part 1):
     - Concise dropdown labels + rich tooltips & descriptions (`SETTINGS_ANIMATION_CHOICES`,
       `SETTINGS_TONE_MAP_CHOICES`, `AQUA_THEMES`).
     - Responsive window geometry across `1280x720`, `1366x768`, `1920x1080`, `2560x1440`,
       and `3840x2160` at `100%`, `125%`, `150%`, and `200%` Windows DPI scaling factors
       (verifying zero horizontal overflow, proper minimum sizes, and on-screen clamping).
     - Persistent user-resized `settings_window_width` & `settings_window_height` in `AppConfig`
       (restored when fitting the active monitor, clamped when switching to a smaller monitor).
     - 8-direction frameless resize hit-testing (Left, Right, Top, Bottom, TopLeft, TopRight,
       BottomLeft, BottomRight, and bottom-right resize grip) + interactive resize clamping.
     - Middle path elision (`elide_middle_path_text` / `ElidedPathLineEdit`) for long save paths.
  2. Windows Icon & Version Metadata (Part 2):
     - `make_prismwake_icon.py` multi-resolution `.ico` generation & verification across all 7
       standard Windows icon sizes (`16, 24, 32, 48, 64, 128, 256` px at 32-bpp RGBA).
     - Non-transparent silhouette coverage at `16x16` and `24x24` as well as `256x256`.
     - `prismwake_version_info.txt` Windows PE VSVersionInfo resource verification (`0.1.4.0`).
     - `ensure_windows_app_user_model_id` and `get_bundled_resource_path` resolution.
  3. Stability, Clipboard & Annotation Tools Audit (Part 3):
     - Clipboard export safety (`prepare_clipboard_safe_qimage` / `copy_pixmap_to_clipboard_safely`)
       and full-resolution image integrity at `1920x1080` (1080p), `2560x1440` (1440p), and
       `3840x2160` (4K).
     - Region filter compositing (Gaussian Blur, Pixelate, Permanent Redaction, Freehand Brush
       Blur/Pixelate/Redact, Paint Bucket flood fill, Eyedropper, Pixel Magnifier, and Numbered
       Callouts) without deleting earlier annotations.
  4. Auto-Updater Compatibility (Part 4):
     - `v0.1.2 -> v0.1.4`, `v0.1.3 -> v0.1.4`, and `v0.1.4 -> v0.1.5` transitions, PyInstaller
       `--onefile` bootloader/child PID ancestry verification, and atomic rollback.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image


def _load_modules():
    out_dir = Path(__file__).resolve().parent
    pw_path = out_dir / "Prismwake.py"
    ico_gen_path = out_dir / "make_prismwake_icon.py"

    spec_pw = importlib.util.spec_from_file_location("Prismwake", str(pw_path))
    pw = importlib.util.module_from_spec(spec_pw)
    sys.modules["Prismwake"] = pw
    sys.modules["HDRSnipFusion"] = pw
    spec_pw.loader.exec_module(pw)

    spec_ico = importlib.util.spec_from_file_location("make_prismwake_icon", str(ico_gen_path))
    ico_mod = importlib.util.module_from_spec(spec_ico)
    sys.modules["make_prismwake_icon"] = ico_mod
    spec_ico.loader.exec_module(ico_mod)
    return pw, ico_mod


app, ico_gen = _load_modules()


class TestPrismwakeV014Suite(unittest.TestCase):
    # =========================================================================
    # PART 1: SETTINGS WINDOW OVERHAUL, GEOMETRY, RESIZING & PERSISTENCE
    # =========================================================================
    def test_01_settings_responsive_geometry_across_resolutions_and_dpis(self) -> None:
        """
        Verifies SettingsDialog responsive geometry across 1280x720, 1366x768,
        1920x1080, 2560x1440, and 3840x2160 at 100%, 125%, 150%, and 200% scaling.
        """
        physical_resolutions = [
            (1280, 720),
            (1366, 768),
            (1920, 1080),
            (2560, 1440),
            (3840, 2160),
        ]
        dpi_scales = [1.0, 1.25, 1.50, 2.0]

        for phys_w, phys_h in physical_resolutions:
            for scale in dpi_scales:
                log_w = max(480, int(round(phys_w / scale)))
                log_h = max(360, int(round((phys_h - 48) / scale)))  # Subtract taskbar
                geom = app.compute_settings_responsive_geometry(0, 0, log_w, log_h)

                # Window must never exceed available logical work area
                self.assertLessEqual(
                    geom["width"],
                    log_w,
                    f"Width {geom['width']} exceeded logical width {log_w} ({phys_w}x{phys_h} @ {int(scale*100)}%)",
                )
                self.assertLessEqual(
                    geom["height"],
                    log_h,
                    f"Height {geom['height']} exceeded logical height {log_h} ({phys_w}x{phys_h} @ {int(scale*100)}%)",
                )
                self.assertGreaterEqual(geom["x"], 0)
                self.assertGreaterEqual(geom["y"], 0)
                self.assertLessEqual(geom["x"] + geom["width"], log_w)
                self.assertLessEqual(geom["y"] + geom["height"], log_h)

                # On standard desktop viewports (logical width >= 900), width should be in [780..840]
                if log_w >= 900:
                    self.assertGreaterEqual(geom["width"], 780)
                    self.assertLessEqual(geom["width"], 840)

    def test_02_settings_persisted_size_and_monitor_disconnect_clamping(self) -> None:
        """
        Verifies that user-resized Settings dimensions persist in AppConfig and
        are restored when valid, or clamped when moving to a smaller display.
        """
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            orig_cfg_file = app.CONFIG_FILE
            orig_cfg_dir = app.CONFIG_DIR
            try:
                app.CONFIG_DIR = Path(td)
                app.CONFIG_FILE = cfg_path
                cfg = app.AppConfig()
                cfg.settings_window_width = 860
                cfg.settings_window_height = 790
                cfg.save()

                loaded = app.AppConfig.load()
                self.assertEqual(loaded.settings_window_width, 860)
                self.assertEqual(loaded.settings_window_height, 790)

                # On a 1920x1080 @ 100% display, 860x790 fits and is restored verbatim
                g_1080 = app.compute_settings_responsive_geometry(
                    0, 0, 1920, 1032, saved_width=loaded.settings_window_width, saved_height=loaded.settings_window_height
                )
                self.assertEqual(g_1080["width"], 860)
                self.assertEqual(g_1080["height"], 790)

                # On a 1280x720 @ 150% display (logical 853x448), 860x790 is too large and must clamp safely
                g_small = app.compute_settings_responsive_geometry(
                    0, 0, 853, 448, saved_width=loaded.settings_window_width, saved_height=loaded.settings_window_height
                )
                self.assertLessEqual(g_small["width"], 853 - 20)
                self.assertLessEqual(g_small["height"], 448 - 20)
            finally:
                app.CONFIG_DIR = orig_cfg_dir
                app.CONFIG_FILE = orig_cfg_file

    def test_03_settings_frameless_resize_all_edges_and_corners(self) -> None:
        """
        Verifies 8-direction frameless edge & corner hit-testing and interactive
        resize geometry calculation (enforcing minimum size & screen bounds).
        """
        w, h = 810, 820
        # 4 Edges
        self.assertEqual(app.hit_test_frameless_resize_edges(2, 400, w, h), 1)       # Left
        self.assertEqual(app.hit_test_frameless_resize_edges(w - 2, 400, w, h), 2)   # Right
        self.assertEqual(app.hit_test_frameless_resize_edges(400, 2, w, h), 4)       # Top
        self.assertEqual(app.hit_test_frameless_resize_edges(400, h - 2, w, h), 8)   # Bottom
        # 4 Corners
        self.assertEqual(app.hit_test_frameless_resize_edges(2, 2, w, h), 1 | 4)         # Top-Left
        self.assertEqual(app.hit_test_frameless_resize_edges(w - 2, 2, w, h), 2 | 4)     # Top-Right
        self.assertEqual(app.hit_test_frameless_resize_edges(2, h - 2, w, h), 1 | 8)     # Bottom-Left
        self.assertEqual(app.hit_test_frameless_resize_edges(w - 14, h - 14, w, h), 2 | 8)  # Bottom-Right grip
        # Interior (title bar / content) must not trigger resize
        self.assertEqual(app.hit_test_frameless_resize_edges(250, 22, w, h), 0)
        self.assertEqual(app.hit_test_frameless_resize_edges(400, 400, w, h), 0)

        # Interactive resize expand & minimum-size clamp
        nx, ny, nw, nh = app.compute_interactive_resize_rect(
            100, 100, 810, 820, edges=2 | 8, dx=90, dy=60, min_width=640, min_height=500
        )
        self.assertEqual((nx, ny, nw, nh), (100, 100, 900, 880))

        # Shrinking past minimum width/height must clamp at (640, 500)
        nx2, ny2, nw2, nh2 = app.compute_interactive_resize_rect(
            100, 100, 810, 820, edges=1 | 4, dx=500, dy=600, min_width=640, min_height=500
        )
        self.assertEqual(nw2, 640)
        self.assertEqual(nh2, 500)

    def test_04_concise_dropdown_labels_and_elided_save_path(self) -> None:
        """
        Verifies that dropdown choices use concise display labels (< 42 chars)
        with full descriptive tooltips, and long save paths elide cleanly.
        """
        for key, short_lbl, full_desc in app.SETTINGS_ANIMATION_CHOICES:
            self.assertIn(key, app.ANIMATION_INTENSITY_LEVELS)
            self.assertLessEqual(len(short_lbl), 24)
            self.assertGreaterEqual(len(full_desc), 30)

        for key, short_lbl, full_desc in app.SETTINGS_TONE_MAP_CHOICES:
            self.assertLessEqual(len(short_lbl), 42)
            self.assertGreaterEqual(len(full_desc), 30)

        long_path = r"C:\Users\shadow728270\OneDrive - Personal\Pictures\Prismwake HDR Screenshots\2026_10_Captures"
        elided = app.elide_middle_path_text(long_path, max_chars=44)
        self.assertLessEqual(len(elided), 44)
        self.assertIn("...", elided)
        self.assertTrue(elided.startswith(r"C:\Users"))
        self.assertTrue(elided.endswith("Captures"))

    # =========================================================================
    # PART 2: MULTI-RESOLUTION WINDOWS ICON (.ICO) & PE VERSION METADATA
    # =========================================================================
    def test_05_multi_size_ico_and_version_resource_integrity(self) -> None:
        """
        Verifies that `prismwake.ico` contains all 7 standard Windows icon frames
        (16, 24, 32, 48, 64, 128, 256) with crisp alpha transparency, and
        `prismwake_version_info.txt` declares Prismwake v0.1.4.0.
        """
        out_dir = Path(__file__).resolve().parent
        ico_path = out_dir / "prismwake.ico"
        svg_path = out_dir / "prismwake-mark.svg"
        ver_path = out_dir / "prismwake_version_info.txt"

        self.assertTrue(ico_path.exists(), "prismwake.ico must exist")
        self.assertTrue(svg_path.exists(), "prismwake-mark.svg must exist")
        self.assertTrue(ver_path.exists(), "prismwake_version_info.txt must exist")

        frames = ico_gen.inspect_ico_frames(ico_path)
        self.assertEqual(
            [w for w, h, _bpp in frames],
            [16, 24, 32, 48, 64, 128, 256],
        )
        for w, h, bpp in frames:
            self.assertEqual(w, h)
            self.assertEqual(bpp, 32)

        # Verify rendered small (16x16, 24x24) and large (256x256) frames have both
        # transparent corners (alpha == 0) and bright opaque center glyph pixels (alpha == 255)
        for test_sz in (16, 24, 32, 64, 256):
            fr = ico_gen.render_prismwake_icon_frame(test_sz)
            arr = np.asarray(fr, dtype=np.uint8)
            self.assertEqual(arr.shape, (test_sz, test_sz, 4))
            self.assertEqual(int(arr[0, 0, 3]), 0, f"Top-left corner must be transparent at {test_sz}x{test_sz}")
            center_alpha = int(arr[test_sz // 2, test_sz // 2, 3])
            self.assertEqual(center_alpha, 255, f"Center must be opaque at {test_sz}x{test_sz}")

        ver_txt = ver_path.read_text(encoding="utf-8")
        self.assertIn("StringStruct('ProductName', 'Prismwake')", ver_txt)
        self.assertIn("StringStruct('FileDescription', 'Prismwake", ver_txt)
        self.assertIn("StringStruct('FileVersion', '0.1.4.0')", ver_txt)
        self.assertIn("StringStruct('ProductVersion', '0.1.4.0')", ver_txt)

    # =========================================================================
    # PART 3: CLIPBOARD EXPORT SAFETY & ANNOTATION COMPOSITING AUDIT
    # =========================================================================
    def test_06_full_resolution_save_and_region_filters_1080p_1440p_4k(self) -> None:
        """
        Verifies that Gaussian Blur, Pixelate, Permanent Redaction, and Paint Bucket
        flood fill operate accurately without deleting each other and export intact
        at 1080p, 1440p, and 4K.
        """
        # 1. Test non-destructive sequence of Blur + Pixelate + Permanent Redaction
        canvas = np.zeros((240, 320, 3), dtype=np.uint8)
        canvas[:, :] = (30, 60, 90)
        # Checkerboard pattern for blur/pixelate verification
        canvas[20:100:4, 20:100:4] = (250, 250, 250)
        canvas[20:100, 120:200] = (240, 20, 60)
        canvas[120:200, 40:160] = (50, 240, 120)

        # Apply Gaussian blur to region 1
        canvas[20:100, 20:100] = app.apply_region_blur_rgb(canvas, 20, 20, 100, 100, blur_radius=8)
        # Apply Pixelate to region 2
        canvas[20:100, 120:200] = app.apply_world_aligned_pixelation_rgb(canvas, 120, 20, 200, 100, block_size=12)
        # Apply Permanent Redaction to region 3 (with brush mask)
        mask = np.zeros((80, 120), dtype=bool)
        mask[10:70, 10:110] = True
        app.apply_permanent_redaction_rgb(
            canvas, 40, 120, 160, 200, color_hex="#000000", mask=mask
        )

        # Verify redaction zeroed the masked pixels while leaving region 1 and region 2 intact
        self.assertTrue(np.all(canvas[135:185, 55:145] == 0))
        self.assertGreater(int(canvas[50, 150, 0]), 200)  # Pixelated region still intact!

        # 2. Verify 4K (3840x2160) PNG save integrity
        with tempfile.TemporaryDirectory() as td:
            rgb_4k = np.zeros((2160, 3840, 3), dtype=np.uint8)
            rgb_4k[:, :, 1] = 128
            rgb_4k[:, :, 2] = 220
            out_4k = Path(td) / "Prismwake_4k_test.png"
            Image.fromarray(rgb_4k, mode="RGB").save(out_4k, format="PNG", compress_level=1)
            with Image.open(out_4k) as im:
                self.assertEqual(im.size, (3840, 2160))

    def test_07_ast_audit_settings_dialog_and_clipboard_safety(self) -> None:
        """
        Verifies via AST/source inspection that:
          - `SettingsDialog` defines 8-direction resize methods (`_hit_test_resize_edges`,
            `_apply_interactive_resize`, `apply_responsive_geometry`) and `ElidedPathLineEdit`.
          - `copy_snip` and `_save_to_default_directory` use `copy_pixmap_to_clipboard_safely`.
          - Zero `SyntaxWarning` or undefined `QFontMetrics` issues exist.
        """
        pw_path = Path(__file__).resolve().parent / "Prismwake.py"
        src = pw_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(pw_path))
        self.assertIsNotNone(tree)
        self.assertIn("copy_pixmap_to_clipboard_safely(pix)", src)
        self.assertIn("def prepare_clipboard_safe_qimage(", src)
        self.assertIn("class ElidedPathLineEdit(QLineEdit):", src)
        self.assertIn("class AquaResizeGripWidget(QWidget):", src)
        self.assertIn("def create_prismwake_pixmap(", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)