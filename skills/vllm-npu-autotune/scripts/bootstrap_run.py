#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import shutil
from pathlib import Path


TEMPLATES = (
    "run_spec.yaml",
    "state.json",
    "trials.csv",
    "accepted_patches.csv",
    "metrics.sample.json",
)


def _default_run_id() -> str:
    return dt.datetime.now().strftime("run_%Y%m%d_%H%M%S")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize a reproducible autotune run workspace.")
    p.add_argument("--workspace", type=Path, required=True, help="Root folder for autotune runs.")
    p.add_argument("--run-id", type=str, default="", help="Optional explicit run id.")
    p.add_argument(
        "--force",
        action="store_true",
        help="Allow reusing an existing run directory.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    run_id = args.run_id.strip() or _default_run_id()
    root = args.workspace.expanduser().resolve()
    run_dir = root / run_id

    if run_dir.exists() and not args.force:
        raise SystemExit(f"run directory already exists: {run_dir} (use --force to reuse)")

    run_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("patches", "reports", "profiles", "logs", "artifacts"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)

    templates_dir = Path(__file__).resolve().parents[1] / "assets" / "templates"
    for name in TEMPLATES:
        src = templates_dir / name
        dst = run_dir / name
        if dst.exists() and args.force:
            continue
        shutil.copy2(src, dst)

    print(f"run_id={run_id}")
    print(f"run_dir={run_dir}")
    print(f"state_file={run_dir / 'state.json'}")
    print(f"run_spec_file={run_dir / 'run_spec.yaml'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
