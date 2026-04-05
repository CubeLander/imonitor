from __future__ import annotations

import argparse
import os
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="imonitord", description="Launch the imonitor daemon/API server.")
    parser.add_argument("--db", type=Path, default=Path("./runs/imonitord.sqlite"), help="path to sqlite database")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18180)
    parser.add_argument("--reload", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = str(args.db.expanduser().resolve())
    os.environ["IMONITOR_DAEMON_DB"] = db
    # Web app reads IMONITOR_DB; point both to the same backing store.
    os.environ["IMONITOR_DB"] = db

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("uvicorn is required. Install with: pip install -e .[web]") from exc

    uvicorn.run("imonitor.daemon.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
