from __future__ import annotations

import sys
from typing import TextIO


def emit_log_line(text: str, stream: TextIO | None = None) -> None:
    out = stream or sys.stderr
    if hasattr(out, "isatty") and out.isatty():
        # Reset to line start and clear the line to avoid cursor pollution
        # from interactive child-process output.
        out.write("\r\x1b[K")
    out.write(f"{text}\n")
    out.flush()
