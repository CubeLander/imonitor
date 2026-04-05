from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(slots=True)
class Signal:
    ts_ns: int
    run_id: str
    sensor: str
    metric: str
    value: float
    unit: str
    pid: int | None = None
    tags: dict[str, str] = field(default_factory=dict)

    def to_row(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "ts_ns": self.ts_ns,
            "sensor": self.sensor,
            "metric": self.metric,
            "value": float(self.value),
            "unit": self.unit,
            "pid": self.pid,
            "tags_json": json.dumps(self.tags, sort_keys=True),
        }
