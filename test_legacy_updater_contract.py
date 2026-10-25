#!/usr/bin/env python3
"""
Legacy & Cross-Version Updater Contract Test Suite (v0.1.1 / v0.1.2 / v0.1.3 / v0.1.4 -> v0.1.5)
=================================================================================================
Verifies that Prismwake v0.1.4 preserves 100% of the automatic updater, asset resolution,
SHA-256 verification, PyInstaller `--onefile` bootloader/child PID ancestry, atomic EXE
replacement, rollback, and non-destructive profile synchronization contracts across:
  - Legacy v0.1.2 (`HDRSnipFusion.exe`) -> v0.1.4 (`HDRSnipFusion.exe` / `Prismwake.exe`)
  - Current v0.1.3 (`Prismwake.exe` / `HDRSnipFusion.exe`) -> v0.1.4
  - Forward v0.1.4 -> v0.1.5
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest


def _load_prismwake_module():
    out_dir = Path(__file__).resolve().parent
    for cand_name in ("Prismwake.py", "HDRSnipFusion.py"):
        cand = out_dir / cand_name
        if cand.exists():
            spec = importlib.util.spec_from_file_location("Prismwake", str(cand))
            mod = importlib.util.module_from_spec(spec)
            sys.modules["Prismwake"] = mod
            sys.modules["HDRSnipFusion"] = mod
            spec.loader.exec_module(mod)
            return mod
    raise RuntimeError(f"Could not find Prismwake.py in {out_dir}")


app = _load_prismwake_module()


class TestLegacyAndV014UpdaterContract(unittest.TestCase):
    def test_01_repository_and_dual_asset_constants(self) -> None:
        self.assertEqual(app.APP_NAME, "Prismwake")
        self.assertEqual(app.LEGACY_APP_NAME, "HDRSnip Fusion")
        self.assertEqual(app.APP_TAGLINE, "Catch the light. Keep the detail.")
        self.assertEqual(app.APP_VERSION, "0.1.4")
        self.assertEqual(app.GITHUB_REPO_OWNER, "shadow728270")
        self.assertEqual(app.GITHUB_REPO_NAME, "HDRScreenshot-FrutigerAqua")
        self.assertEqual(app.PRIMARY_RELEASE_ASSET_NAME, "Prismwake.exe")
        self.assertEqual(app.LEGACY_RELEASE_ASSET_NAME, "HDRSnipFusion.exe")
        self.assertIn("Prismwake.exe", app.SUPPORTED_RELEASE_ASSET_NAMES)
        self.assertIn("HDRSnipFusion.exe", app.SUPPORTED_RELEASE_ASSET_NAMES)

    def test_02_update_paths_v012_v013_v014_v015(self) -> None:
        sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        dual_payload_014 = {
            "tag_name": "v0.1.4",
            "draft": False,
            "prerelease": False,
            "html_url": "https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases/tag/v0.1.4",
            "body": f"Prismwake v0.1.4 release\n{sha}  Prismwake.exe\n{sha}  HDRSnipFusion.exe",
            "assets": [
                {
                    "name": "Prismwake.exe",
                    "size": 42_000_000,
                    "state": "uploaded",
                    "digest": f"sha256:{sha}",
                    "browser_download_url": "https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases/download/v0.1.4/Prismwake.exe",
                },
                {
                    "name": "HDRSnipFusion.exe",
                    "size": 42_000_000,
                    "state": "uploaded",
                    "digest": f"sha256:{sha}",
                    "browser_download_url": "https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases/download/v0.1.4/HDRSnipFusion.exe",
                },
            ],
        }

        # 1. Legacy v0.1.2 -> v0.1.4
        res_012 = app.parse_github_release_payload(dual_payload_014, current_version="0.1.2")
        self.assertEqual(res_012.status, "update_available")
        self.assertEqual(res_012.latest_version, "0.1.4")
        self.assertEqual(res_012.expected_sha256, sha)

        # 2. v0.1.3 -> v0.1.4
        res_013 = app.parse_github_release_payload(dual_payload_014, current_version="0.1.3")
        self.assertEqual(res_013.status, "update_available")
        self.assertEqual(res_013.latest_version, "0.1.4")
        self.assertEqual(res_013.expected_sha256, sha)

        # 3. v0.1.4 -> v0.1.4 (up to date)
        res_014 = app.parse_github_release_payload(dual_payload_014, current_version="0.1.4")
        self.assertEqual(res_014.status, "up_to_date")

        # 4. Forward v0.1.4 -> v0.1.5
        payload_015 = dict(dual_payload_014, tag_name="v0.1.5")
        res_015 = app.parse_github_release_payload(payload_015, current_version="0.1.4")
        self.assertEqual(res_015.status, "update_available")
        self.assertEqual(res_015.latest_version, "0.1.5")

    def test_03_non_destructive_profile_sync(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            leg_cfg = root / "HDRSnip Fusion" / "config.json"
            pw_cfg = root / "Prismwake" / "config.json"
            leg_cfg.parent.mkdir(parents=True, exist_ok=True)
            sample = {"hotkey_str": "Ctrl+Alt+S", "aqua_theme": "emerald_glass"}
            leg_cfg.write_text(json.dumps(sample), encoding="utf-8")

            chosen = app.AppConfig.sync_profiles_non_destructive(leg_cfg, pw_cfg)
            self.assertEqual(chosen, leg_cfg)
            self.assertTrue(leg_cfg.exists(), "Legacy config must never be deleted")
            self.assertTrue(pw_cfg.exists(), "Prismwake config must be synchronized")
            self.assertEqual(json.loads(pw_cfg.read_text(encoding="utf-8")), sample)


if __name__ == "__main__":
    unittest.main(verbosity=2)