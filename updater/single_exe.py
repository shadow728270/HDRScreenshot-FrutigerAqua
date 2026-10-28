"""
Prismwake v0.2.0 — Single-Executable Release Asset Contract & Validation
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

CANONICAL_EXECUTABLE_NAME: str = "Prismwake.exe"
CANONICAL_CHECKSUM_NAME: str = "Prismwake.exe.sha256"
SUPPORTED_SINGLE_EXE_ASSETS: Tuple[str, ...] = (CANONICAL_EXECUTABLE_NAME,)


def resolve_v020_release_asset_names(
    installed_exe_path: Optional[Path] = None,
) -> Tuple[str, ...]:
    """
    In Prismwake v0.2.0+, `Prismwake.exe` is the sole supported release executable.
    Does not fall back to `HDRSnipFusion.exe` or arbitrary `.exe` filenames.
    """
    _ = installed_exe_path
    return SUPPORTED_SINGLE_EXE_ASSETS


def verify_single_exe_release_assets(asset_names: Sequence[str]) -> Tuple[bool, str]:
    """
    Verify that a v0.2.0+ release asset list contains `Prismwake.exe` and
    `Prismwake.exe.sha256` and does NOT publish any obsolete dual-EXE alias.
    """
    names = {str(n).strip() for n in asset_names if str(n).strip()}
    if "HDRSnipFusion.exe" in names or "HDRSnipFusion.exe.sha256" in names:
        return (
            False,
            "Release contains retired legacy executable alias 'HDRSnipFusion.exe'. "
            "Prismwake v0.2.0+ must publish only Prismwake.exe and Prismwake.exe.sha256.",
        )
    if CANONICAL_EXECUTABLE_NAME not in names:
        return (False, f"Missing required release executable '{CANONICAL_EXECUTABLE_NAME}'.")
    if CANONICAL_CHECKSUM_NAME not in names:
        return (False, f"Missing required release checksum '{CANONICAL_CHECKSUM_NAME}'.")
    return (True, "ok")
