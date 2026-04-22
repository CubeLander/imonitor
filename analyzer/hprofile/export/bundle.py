from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Iterable, List

from ..model.schema import MANIFEST_SCHEMA_VERSION


def ensure_bundle_layout(bundle_dir: Path) -> Dict[str, Path]:
    raw_dir = bundle_dir / "raw"
    derived_dir = bundle_dir / "derived"
    web_dir = bundle_dir / "web"
    assets_dir = web_dir / "assets"

    for p in (bundle_dir, raw_dir, derived_dir, web_dir, assets_dir):
        p.mkdir(parents=True, exist_ok=True)

    return {
        "bundle_dir": bundle_dir,
        "raw_dir": raw_dir,
        "derived_dir": derived_dir,
        "web_dir": web_dir,
        "assets_dir": assets_dir,
    }


def materialize_raw(run_dir: Path, raw_dir: Path, mode: str) -> Dict[str, object]:
    run_dir = run_dir.resolve()
    target = raw_dir / "run"

    if target.exists() or target.is_symlink():
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()

    if mode == "none":
        return {
            "mode": "none",
            "source_run_dir": str(run_dir),
            "target": None,
        }

    if mode == "copy":
        shutil.copytree(run_dir, target)
        return {
            "mode": "copy",
            "source_run_dir": str(run_dir),
            "target": str(target),
        }

    target.symlink_to(run_dir, target_is_directory=True)
    return {
        "mode": "symlink",
        "source_run_dir": str(run_dir),
        "target": str(target),
    }


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_manifest_files(bundle_dir: Path) -> Iterable[Path]:
    for p in sorted(bundle_dir.rglob("*")):
        if p.is_dir() or p.name == "manifest.json":
            continue
        if p.is_symlink():
            continue
        yield p


def build_manifest(
    *,
    bundle_dir: Path,
    run_id: str,
    generated_at: str,
    tool_version: str,
    raw: Dict[str, object],
) -> Dict[str, object]:
    files: List[Dict[str, object]] = []
    for p in _iter_manifest_files(bundle_dir):
        rel = p.relative_to(bundle_dir).as_posix()
        files.append(
            {
                "path": rel,
                "size": p.stat().st_size,
                "sha256": _sha256(p),
            }
        )

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "tool": {
            "name": "hprofile",
            "version": tool_version,
        },
        "raw": raw,
        "files": files,
    }
