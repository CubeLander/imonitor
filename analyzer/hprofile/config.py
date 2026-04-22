from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HProfileConfig:
    run_dir: Path
    bundle_dir: Path
    legacy_out_dir: Path
    raw_mode: str = "symlink"
    topn_streams: int = 30
    topn_edges: int = 50
    topn_loops: int = 50
    topn_kernels: int = 30
