#!/usr/bin/env python3
"""Run deterministic, non-GUI application and OCR integration tests.

The project ships alternate headless controllers for synthetic capture tests.
If the real PyQt6 package is importable, accidentally selecting QWidget-based
controllers without a QApplication can trigger a native Qt fail-fast rather
than a Python exception (Windows 0xC0000409). These tests MUST select the
headless controllers. Actual Qt window construction is smoke-tested separately.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# This process tests the documented pure Python/headless code paths. Do not
# change or remove the actual app's production imports or its GUI behavior.
if any(key == 'PyQt6' or key.startswith('PyQt6.') for key in sys.modules):
    raise RuntimeError('PyQt6 was loaded before headless test initialization')
sys.modules['PyQt6'] = None

if __name__ == '__main__':
    print('Testing headless controllers (GUI integration is tested in a separate process)', flush=True)
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(ROOT / 'tests'), pattern='test_prismwake_v020.py'
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
