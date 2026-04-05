from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SinkConfig:
    sqlite: bool = True
    parquet: bool = True
    csv: bool = True
    live: bool = True


@dataclass(slots=True)
class MonitorConfig:
    command: list[str]
    out_dir: Path
    interval_sec: float = 0.5
    enable_gpu: bool = True
    enable_net: bool = True
    sink: SinkConfig = field(default_factory=SinkConfig)

    def validate(self) -> None:
        if not self.command:
            raise ValueError("command cannot be empty")
        if self.interval_sec <= 0:
            raise ValueError("interval_sec must be > 0")
