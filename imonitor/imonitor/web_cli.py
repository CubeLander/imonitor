from __future__ import annotations

import argparse
import os
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="imonitor-web", description="Launch imonitor web UI.")
    parser.add_argument("--db", type=Path, default=Path("./runs/integrated_demo/metrics.sqlite"), help="path to sqlite database")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--reload", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ["IMONITOR_DB"] = str(args.db.expanduser().resolve())

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("uvicorn is required. Install with: pip install -e .[web]") from exc

    uvicorn.run("imonitor.web.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

