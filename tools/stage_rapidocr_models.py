#!/usr/bin/env python3
"""
Prismwake v0.2.0 — Deterministic RapidOCR ONNX Model Stager & Integrity Verifier
================================================================================
Stages and cryptographically/structurally validates the offline RapidOCR detector,
recognizer, and classifier `.onnx` weights plus configuration and dictionary files
into `rapidocr_models/` before PyInstaller packaging.

Usage:
    python tools/stage_rapidocr_models.py --output-dir rapidocr_models --strict
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List, Optional, Set

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont
from ocr.backends import (
    ITALIAN_DIACRITIC_PROBES,
    RapidOcrBackend,
    _block_network_downloads,
    verify_rapidocr_model_directory,
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_paths_from_object(obj: Any, visited: Optional[Set[int]] = None, depth: int = 0) -> List[Path]:
    if visited is None:
        visited = set()
    if obj is None or depth > 5 or id(obj) in visited:
        return []
    visited.add(id(obj))
    found: List[Path] = []
    if isinstance(obj, (str, Path)):
        s = str(obj)
        if s.lower().endswith((".onnx", ".txt", ".yaml", ".yml")):
            p = Path(s)
            if p.is_file():
                found.append(p.resolve())
        return found
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.extend(_collect_paths_from_object(k, visited, depth + 1))
            found.extend(_collect_paths_from_object(v, visited, depth + 1))
        return found
    if isinstance(obj, (list, tuple, set)):
        for it in obj:
            found.extend(_collect_paths_from_object(it, visited, depth + 1))
        return found
    if hasattr(obj, "__dict__"):
        for v in vars(obj).values():
            found.extend(_collect_paths_from_object(v, visited, depth + 1))
    return found


def stage_and_verify_rapidocr_models(output_dir: Path, *, strict: bool = True) -> Dict[str, Any]:
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        import onnxruntime as ort  # type: ignore
        ort_version = getattr(ort, "__version__", "installed")
    except Exception as exc:
        msg = f"CRITICAL: onnxruntime is not installed in {sys.executable} ({exc}). Cannot build offline neural OCR."
        if strict:
            raise RuntimeError(msg) from exc
        return {"ok": False, "error": msg}

    pkg_name = ""
    pkg_version = ""
    pkg_root: Optional[Path] = None
    for cand_mod in ("rapidocr", "rapidocr_onnxruntime"):
        try:
            mod = __import__(cand_mod)
            pkg_name = cand_mod
            pkg_version = getattr(mod, "__version__", "installed")
            pkg_root = Path(mod.__file__).resolve().parent
            break
        except Exception:
            continue

    if not pkg_name or pkg_root is None:
        msg = (
            f"CRITICAL: 'rapidocr' is not installed in {sys.executable}. "
            "Run 'pip install -r requirements.txt' in a supported Python 3.11-3.13 environment."
        )
        if strict:
            raise RuntimeError(msg)
        return {"ok": False, "error": msg}

    # 1. Initialize RapidOCR explicitly requesting ONNXRUNTIME + PP-OCRv6 small (multilingual EN+IT)
    #    with fallback to default bundled ONNX models if PP-OCRv6 enum is not present in older rapidocr.
    engine: Any = None
    selected_family = "PP-OCRv6-small-multilingual"
    try:
        from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR  # type: ignore

        try:
            engine = RapidOCR(
                params={
                    "Det.engine_type": EngineType.ONNXRUNTIME,
                    "Det.ocr_version": OCRVersion.PPOCRV6,
                    "Det.model_type": ModelType.SMALL,
                    "Rec.engine_type": EngineType.ONNXRUNTIME,
                    "Rec.ocr_version": OCRVersion.PPOCRV6,
                    "Rec.model_type": ModelType.SMALL,
                    "Cls.engine_type": EngineType.ONNXRUNTIME,
                }
            )
        except Exception:
            selected_family = "PP-OCR-default-bundled"
            engine = RapidOCR()
    except Exception:
        try:
            from rapidocr import RapidOCR  # type: ignore
            selected_family = "PP-OCR-default-bundled"
            engine = RapidOCR()
        except Exception:
            from rapidocr_onnxruntime import RapidOCR as RapidOCROrt  # type: ignore
            selected_family = "PP-OCRv4-onnxruntime"
            engine = RapidOCROrt()

    # Run a warmup pass during build staging so any lazy-loaded model paths are resolved
    probe_img = Image.new("RGB", (520, 100), (255, 255, 255))
    drw = ImageDraw.Draw(probe_img)
    drw.text((20, 32), "Prismwake OCR Ready 2026", fill=(10, 18, 28), font=ImageFont.load_default())
    _ = engine(probe_img)

    # 2. Gather all .onnx, .yaml, and dictionary .txt files from the initialized engine and package dir
    discovered_files: List[Path] = _collect_paths_from_object(engine)
    for sub in ("models", "default_models", ""):
        cand_d = pkg_root / sub if sub else pkg_root
        if cand_d.is_dir():
            for ext in ("*.onnx", "*.yaml", "*.yml", "*keys*.txt", "*dict*.txt"):
                for p in cand_d.glob(ext):
                    if p.is_file():
                        discovered_files.append(p.resolve())

    copied_files: Dict[str, Dict[str, Any]] = {}
    seen_src: Set[str] = set()
    for src_p in discovered_files:
        if str(src_p) in seen_src or not src_p.is_file():
            continue
        seen_src.add(str(src_p))
        dst_p = out_dir / src_p.name
        if src_p.resolve() != dst_p.resolve():
            shutil.copy2(src_p, dst_p)
        if dst_p.suffix.lower() in (".onnx", ".txt", ".yaml", ".yml"):
            copied_files[dst_p.name] = {
                "size_bytes": dst_p.stat().st_size,
                "sha256": _sha256_file(dst_p),
            }

    # 3. Validate the staged directory with ONNX Runtime InferenceSession
    v_meta = verify_rapidocr_model_directory(out_dir)
    if not v_meta.get("ok"):
        msg = f"CRITICAL: Staged RapidOCR model verification failed in {out_dir}: {v_meta.get('reason')}"
        if strict:
            raise RuntimeError(msg)
        return {"ok": False, "error": msg}

    # 4. Write model_manifest.json with SHA-256 digests and verified metadata
    manifest = {
        "rapidocr_package": pkg_name,
        "rapidocr_version": pkg_version,
        "onnxruntime_version": ort_version,
        "model_family": v_meta.get("model_family") or selected_family,
        "supported_languages": list(v_meta.get("supported_languages") or ["eng"]),
        "det_model": Path(v_meta["det_path"]).name if v_meta.get("det_path") else "",
        "rec_model": Path(v_meta["rec_path"]).name if v_meta.get("rec_path") else "",
        "cls_model": Path(v_meta["cls_path"]).name if v_meta.get("cls_path") else "",
        "files": copied_files,
    }
    manifest_path = out_dir / "model_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # 5. Re-verify with manifest present and run strict offline inference test (network blocked)
    from ocr.backends import _MODEL_DIR_VERIFICATION_CACHE
    _MODEL_DIR_VERIFICATION_CACHE.clear()
    v_meta_final = verify_rapidocr_model_directory(out_dir)
    if not v_meta_final.get("ok") or not v_meta_final.get("manifest_verified"):
        msg = f"CRITICAL: Post-manifest verification failed for {out_dir}: {v_meta_final.get('reason')}"
        if strict:
            raise RuntimeError(msg)
        return {"ok": False, "error": msg}

    with _block_network_downloads():
        backend = RapidOcrBackend(custom_model_dir=out_dir)
        stat = backend.query_status()
        if not stat.available:
            msg = f"CRITICAL: RapidOcrBackend reported unavailable on staged models: {stat.reason}"
            if strict:
                raise RuntimeError(msg)
            return {"ok": False, "error": msg}
        res = backend.recognize(probe_img, language="eng")
        if not res.ok or "prismwake" not in res.text.lower():
            msg = f"CRITICAL: Offline RapidOcrBackend dry-run failed on staged models: error={res.error!r}, text={res.text!r}"
            if strict:
                raise RuntimeError(msg)
            return {"ok": False, "error": msg}

    print(
        f"[RapidOCR Model Stager] Successfully staged & verified {len(v_meta_final['onnx_files'])} ONNX models "
        f"({manifest['model_family']}) in {out_dir} — recognized {res.text.strip()!r} completely offline."
    )
    return {
        "ok": True,
        "output_dir": str(out_dir),
        "manifest": manifest,
        "recognized_probe": res.text.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage and verify offline RapidOCR ONNX models for Prismwake.")
    parser.add_argument("--output-dir", default="rapidocr_models", help="Target directory for staged ONNX models.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if staging or verification fails.")
    args = parser.parse_args()
    try:
        res = stage_and_verify_rapidocr_models(Path(args.output_dir), strict=args.strict)
        return 0 if res.get("ok") else 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
