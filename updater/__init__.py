"""
Prismwake v0.2.0 — Modern Single-EXE Automatic Updater (`updater`)
==================================================================
In Prismwake v0.2.0, the legacy dual-executable compatibility layer is retired.
Only `Prismwake.exe` and `Prismwake.exe.sha256` are built, published, and accepted
by the modern updater.
"""

from .single_exe import (
    CANONICAL_EXECUTABLE_NAME,
    CANONICAL_CHECKSUM_NAME,
    SUPPORTED_SINGLE_EXE_ASSETS,
    resolve_v020_release_asset_names,
    verify_single_exe_release_assets,
)

__all__ = [
    "CANONICAL_EXECUTABLE_NAME",
    "CANONICAL_CHECKSUM_NAME",
    "SUPPORTED_SINGLE_EXE_ASSETS",
    "resolve_v020_release_asset_names",
    "verify_single_exe_release_assets",
]
