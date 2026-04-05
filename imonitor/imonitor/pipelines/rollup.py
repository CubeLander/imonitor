from __future__ import annotations

import math
from dataclasses import dataclass, field


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
    return ordered[idx]


@dataclass(slots=True)
class BucketStat:
    values: list[float] = field(default_factory=list)
    last: float = 0.0

    def add(self, value: float) -> None:
        self.values.append(value)
        self.last = value


def build_rollup_rows(
    raw_rows: list[dict[str, object]],
    bucket_ns: int = 1_000_000_000,
) -> list[dict[str, object]]:
    if bucket_ns <= 0:
        raise ValueError("bucket_ns must be > 0")

    grouped: dict[
        tuple[str, str, str, int | None, str, int, int],
        BucketStat,
    ] = {}

    for row in raw_rows:
        run_id = str(row["run_id"])
        ts_ns = int(row["ts_ns"])
        sensor = str(row["sensor"])
        metric = str(row["metric"])
        unit = str(row["unit"])
        pid = row.get("pid")
        pid_norm: int | None = int(pid) if pid is not None else None
        value = float(row["value"])

        start_ns = (ts_ns // bucket_ns) * bucket_ns
        key = (run_id, sensor, metric, pid_norm, unit, bucket_ns, start_ns)
        stat = grouped.get(key)
        if stat is None:
            stat = BucketStat()
            grouped[key] = stat
        stat.add(value)

    out: list[dict[str, object]] = []
    for (run_id, sensor, metric, pid, unit, width_ns, start_ns), stat in sorted(
        grouped.items(),
        key=lambda x: (x[0][0], x[0][6], x[0][1], x[0][2], -1 if x[0][3] is None else x[0][3]),
    ):
        values = stat.values
        out.append(
            {
                "run_id": run_id,
                "sensor": sensor,
                "metric": metric,
                "pid": pid,
                "unit": unit,
                "bucket_ns": width_ns,
                "bucket_start_ns": start_ns,
                "sample_count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "p95": _p95(values),
                "last": stat.last,
            }
        )
    return out
