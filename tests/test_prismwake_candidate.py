"""Headless Prismwake v0.1.3 candidate checks for release packaging."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import HDRSnipFusion as app

REPO = "shadow728270/HDRScreenshot-FrutigerAqua"
SHA = "a3" * 32

def payload():
    return {
        "tag_name": "v0.1.4",
        "name": "Prismwake v0.1.4",
        "draft": False,
        "prerelease": False,
        "html_url": f"https://github.com/{REPO}/releases/tag/v0.1.4",
        "assets": [
            {"name": name, "state": "uploaded", "size": 105000000,
             "digest": "sha256:" + SHA,
             "browser_download_url": f"https://github.com/{REPO}/releases/download/v0.1.4/{name}"}
            for name in ("Prismwake.exe", "HDRSnipFusion.exe")
        ],
    }

class CandidateContractTests(unittest.TestCase):
    def test_version_and_legacy_repo(self):
        self.assertEqual(app.APP_VERSION, "0.1.3")
        self.assertEqual(app.APP_NAME, "Prismwake")
        self.assertEqual(app.GITHUB_REPO_NAME, "HDRScreenshot-FrutigerAqua")
        self.assertEqual(app.LEGACY_RELEASE_ASSET_NAME, "HDRSnipFusion.exe")

    def test_dual_asset_preference(self):
        for filename, preferred in [("Prismwake.exe", "Prismwake.exe"), ("HDRSnipFusion.exe", "HDRSnipFusion.exe")]:
            names = app.resolve_preferred_release_asset_names(Path("C:/Users/Test/Downloads") / filename)
            self.assertEqual(names[0], preferred)
            r = app.parse_github_release_payload(payload(), current_version="0.1.3", preferred_asset_names=names)
            self.assertEqual(r.status, "update_available", r.message)
            self.assertEqual(r.asset_name, preferred)
            self.assertEqual(r.expected_sha256, SHA)
        self.assertEqual(app.parse_github_release_payload(payload(), current_version="0.1.4").status, "up_to_date")

    def test_bogus_repo_digest_and_no_assets_rejected(self):
        wrong = payload()
        wrong["assets"][0]["browser_download_url"] = "https://evil.example/Prismwake.exe"
        result = app.parse_github_release_payload(wrong, current_version="0.1.3",
                                                  preferred_asset_names=("Prismwake.exe",))
        self.assertEqual(result.status, "error")
        wrong = payload()
        wrong["assets"][0]["digest"] = "sha256:" + ("n" * 64)
        self.assertEqual(app.parse_github_release_payload(
            wrong, current_version="0.1.3", preferred_asset_names=("Prismwake.exe",)
        ).status, "error")
        wrong = payload()
        wrong["assets"] = []
        self.assertEqual(app.parse_github_release_payload(wrong, current_version="0.1.3").status, "asset_pending")

    def test_themes_and_bounds(self):
        self.assertEqual(len(app.AQUA_THEMES), 4)
        self.assertEqual(app.normalize_aqua_theme("Emerald Glass"), "emerald_glass")
        self.assertEqual(app.clamp_blur_radius(900), 40)
        self.assertEqual(app.clamp_pixelate_size(-10), 2)
        self.assertEqual(app.clamp_callout_radius(900), 36)
        self.assertEqual(app.get_next_callout_number([]), 1)
        self.assertEqual(app.get_next_callout_number([app.AnnotationItem(tool="callout",callout_number=8,points=[(3,4)])]), 9)

    def test_redact_zeroes_target_pixels(self):
        rgb = np.arange(24*18*3,dtype=np.uint8).reshape((18,24,3))
        old = rgb.copy()
        app.apply_permanent_redaction_rgb(rgb, 5,4,14,11, "#000000")
        self.assertTrue(np.all(rgb[4:11,5:14]==0))
        self.assertTrue(np.array_equal(rgb[0:4],old[0:4]))
        self.assertTrue(np.array_equal(rgb[11:],old[11:]))

    def test_redaction_mask_is_opaque(self):
        rgb = np.full((6,6,3),[100,120,140],dtype=np.uint8)
        mask = np.zeros((4,4),dtype=np.uint8)
        mask[1:3,1:3] = 255
        app.apply_permanent_redaction_rgb(rgb,1,1,5,5,"#ff0000",mask=mask)
        self.assertTrue(np.all(rgb[2:4,2:4]==np.array([255,0,0],dtype=np.uint8)))
        self.assertEqual(tuple(rgb[1,1]),(100,120,140))

    def test_annotation_fill_ignores_background_photo(self):
        annotation=[app.AnnotationItem(tool="rect",thickness=5,points=[(10,10),(52,52)])]
        a=np.zeros((64,64,3),dtype=np.uint8)
        b=np.full((64,64,3),[110,211,19],dtype=np.uint8)
        first,alpha=app.render_annotations_for_fill_pil(a,annotation)
        second,alpha2=app.render_annotations_for_fill_pil(b,annotation)
        self.assertTrue(np.array_equal(first,second))
        self.assertTrue(np.array_equal(alpha,alpha2))
        self.assertGreater(int(np.max(alpha)),0)

    def test_atomic_non_destructive_profile_copy(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"old"/"config.json"
            b=Path(d)/"prismwake"/"config.json"
            a.parent.mkdir(parents=True)
            a.write_text('{"hotkey_str":"Ctrl+Alt+S"}',encoding="utf-8")
            app.AppConfig.sync_profiles_non_destructive(a,b)
            self.assertTrue(b.is_file())
            self.assertEqual(a.read_bytes(),b.read_bytes())
            a.write_text('{"hotkey_str":"Ctrl+Alt+R"}',encoding="utf-8")
            app.AppConfig.sync_profiles_non_destructive(a,b)
            self.assertIn("Ctrl+Alt+S",b.read_text())
            self.assertIn("Ctrl+Alt+R",a.read_text())

if __name__ == "__main__":
    unittest.main()
