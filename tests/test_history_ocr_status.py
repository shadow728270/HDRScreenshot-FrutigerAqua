"""Fast regression tests for Prismwake's History OCR job status tracking."""
from __future__ import annotations

import threading
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from history.storage import ScreenshotHistoryStore


class HistoryOcrJobStatusTests(unittest.TestCase):
    def _check(self, result_text: str, expected_state: str) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = ScreenshotHistoryStore(root_dir=Path(root))
            image = Image.new("RGB", (80, 60), "white")
            entry = store.record_capture(image, was_saved_or_copied=True)
            self.assertIsNotNone(entry)
            assert entry is not None
            started = threading.Event()
            release = threading.Event()

            def recognize(_img: Image.Image) -> str:
                started.set()
                release.wait(3)
                return result_text

            t = store.enqueue_async_ocr_indexing(entry.capture_id, image, recognize)
            self.assertIsNotNone(t)
            self.assertTrue(started.wait(3))
            self.assertEqual(store.get_ocr_job_state(entry.capture_id), "pending")
            self.assertTrue(store.has_pending_ocr_jobs())
            self.assertIs(
                store.enqueue_async_ocr_indexing(entry.capture_id, image, recognize), t,
                "Repeated requests must not duplicate an active OCR worker",
            )
            release.set()
            self.assertTrue(store.wait_for_pending_ocr(timeout=5))
            self.assertEqual(store.get_ocr_job_state(entry.capture_id), expected_state)
            self.assertFalse(store.has_pending_ocr_jobs())
            self.assertEqual(store.get_entry(entry.capture_id).ocr_text, result_text)
            store.shutdown()

    def test_async_ocr_indexed_and_duplicate_request(self):
        self._check("Found words", "indexed")

    def test_async_ocr_completed_without_readable_text(self):
        self._check("", "empty")


if __name__ == "__main__":
    unittest.main()
