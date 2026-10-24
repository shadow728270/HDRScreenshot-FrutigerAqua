"""Frozen v0.1.2 updater compatibility contract for the Prismwake rename.

Loads the actual shipped source at Git tag v0.1.2, never the potentially
modified v0.1.3 source, and validates realistic v0.1.3 metadata.
Run: python -m unittest discover -s tests -p test_legacy_updater_contract.py -v
"""
from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = "shadow728270/HDRScreenshot-FrutigerAqua"
RELEASE_URL = f"https://github.com/{REPO}/releases/tag/v0.1.3"
LEGACY_ASSET = "HDRSnipFusion.exe"
NEW_ASSET = "Prismwake.exe"
SAMPLE_SHA = "c3" * 32
SAMPLE_SIZE = 104_200_000


def load_frozen_v012():
    """Import bytes pinned to the existing Git tag so future changes cannot fake legacy compatibility."""
    root = Path(__file__).resolve().parents[1]
    raw = subprocess.check_output(
        ["git", "show", "v0.1.2:HDRSnipFusion.py"],
        cwd=root,
        stderr=subprocess.PIPE,
    )
    with tempfile.TemporaryDirectory(prefix="prismwake_legacy_v012_") as temp:
        path = Path(temp) / "frozen_v012.py"
        path.write_bytes(raw)
        module_name = "prismwake_frozen_v012"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not import the frozen v0.1.2 updater")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module


def release_payload():
    return {
        "tag_name": "v0.1.3",
        "draft": False,
        "prerelease": False,
        "name": "Prismwake v0.1.3",
        "html_url": RELEASE_URL,
        "body": "Rebranded editor release with a legacy-compatible download asset.",
        "published_at": "2026-11-01T00:00:00Z",
        "assets": [
            {
                "name": NEW_ASSET,
                "state": "uploaded",
                "size": SAMPLE_SIZE,
                "digest": "sha256:" + SAMPLE_SHA,
                "browser_download_url": f"{RELEASE_URL.replace('/tag/v0.1.3', '')}/download/v0.1.3/{NEW_ASSET}",
            },
            {
                "name": LEGACY_ASSET,
                "state": "uploaded",
                "size": SAMPLE_SIZE,
                "digest": "sha256:" + SAMPLE_SHA,
                "browser_download_url": f"https://github.com/{REPO}/releases/download/v0.1.3/{LEGACY_ASSET}",
            },
        ],
    }


class LegacyUpdaterContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v012 = load_frozen_v012()

    def test_expected_v012_contract_is_frozen(self):
        self.assertEqual(self.v012.APP_VERSION, "0.1.2")
        self.assertEqual(self.v012.GITHUB_REPO_NAME, "HDRScreenshot-FrutigerAqua")
        self.assertEqual(self.v012.EXPECTED_RELEASE_ASSET_NAME, LEGACY_ASSET)

    def test_legacy_accepts_dual_alias_prismwake_release(self):
        result = self.v012.parse_github_release_payload(release_payload(), current_version="0.1.2")
        self.assertEqual(result.status, "update_available", result.message)
        self.assertEqual(result.latest_version, "0.1.3")
        self.assertEqual(result.asset_name, LEGACY_ASSET)
        self.assertEqual(result.expected_sha256, SAMPLE_SHA)
        self.assertTrue(result.is_update_ready)

    def test_legacy_must_not_accept_only_new_name(self):
        payload = release_payload()
        payload["assets"] = payload["assets"][:1]
        result = self.v012.parse_github_release_payload(payload, current_version="0.1.2")
        self.assertEqual(result.status, "asset_pending")

    def test_legacy_rejects_renamed_repo_release_url(self):
        payload = release_payload()
        payload["html_url"] = "https://github.com/shadow728270/Prismwake/releases/tag/v0.1.3"
        result = self.v012.parse_github_release_payload(payload, current_version="0.1.2")
        self.assertEqual(result.status, "error")

    def test_legacy_rejects_wrong_checksum(self):
        payload = release_payload()
        payload["assets"][1]["digest"] = "sha256:" + ("0" * 64)
        payload["body"] = SAMPLE_SHA + "  HDRSnipFusion.exe"
        result = self.v012.parse_github_release_payload(payload, current_version="0.1.2")
        self.assertEqual(result.status, "error")
        self.assertIn("mismatch", result.message.lower())

    def test_legacy_rejects_bad_asset_url(self):
        payload = release_payload()
        payload["assets"][1]["browser_download_url"] = "https://example.com/v0.1.3/HDRSnipFusion.exe"
        result = self.v012.parse_github_release_payload(payload, current_version="0.1.2")
        self.assertEqual(result.status, "error")

    def test_legacy_rejects_missing_digest(self):
        payload = release_payload()
        payload["assets"][1].pop("digest")
        result = self.v012.parse_github_release_payload(payload, current_version="0.1.2")
        self.assertEqual(result.status, "error")

    def test_legacy_rejects_unfinished_legacy_asset(self):
        payload = release_payload()
        payload["assets"][1]["state"] = "uploading"
        result = self.v012.parse_github_release_payload(payload, current_version="0.1.2")
        self.assertEqual(result.status, "asset_pending")

    def test_legacy_rejects_too_small_executable(self):
        payload = release_payload()
        payload["assets"][1]["size"] = 100
        result = self.v012.parse_github_release_payload(payload, current_version="0.1.2")
        self.assertEqual(result.status, "error")

    def test_legacy_ignores_prerelease(self):
        payload = release_payload()
        payload["prerelease"] = True
        result = self.v012.parse_github_release_payload(payload, current_version="0.1.2")
        self.assertEqual(result.status, "up_to_date")


if __name__ == "__main__":
    unittest.main()
