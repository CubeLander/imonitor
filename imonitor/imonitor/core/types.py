from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MonitorContext:
    run_id: str
    command: list[str]
    root_pid: int
    start_ns: int
    interval_sec: float
    active_pids: set[int] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
