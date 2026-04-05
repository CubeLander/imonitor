from __future__ import annotations

from dataclasses import dataclass

from imonitor.core.types import MonitorContext
from imonitor.signals.schema import Signal


@dataclass(slots=True)
class MetricStat:
    unit: str
    count: int = 0
    total: float = 0.0
    min_value: float = float("inf")
    max_value: float = float("-inf")
    last_value: float = 0.0

    def update(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.last_value = value
        if value < self.min_value:
            self.min_value = value
        if value > self.max_value:
            self.max_value = value

    @property
    def avg(self) -> float:
        return self.total / self.count if self.count else 0.0


class Aggregator:
    def __init__(self) -> None:
        self._stats: dict[tuple[str, str, int | None], MetricStat] = {}
        self._first_seen: dict[int, int] = {}
        self._last_seen: dict[int, int] = {}
        self._comm_by_pid: dict[int, str] = {}

        self._cpu_current: dict[int, float] = {}
        self._rss_current: dict[int, float] = {}
        self.peak_total_cpu_pct: float = 0.0
        self.peak_total_rss_bytes: float = 0.0

    def ingest(self, signal: Signal) -> None:
        key = (signal.sensor, signal.metric, signal.pid)
        stat = self._stats.get(key)
        if stat is None:
            stat = MetricStat(unit=signal.unit)
            self._stats[key] = stat
        stat.update(signal.value)

        pid = signal.pid
        if pid is not None:
            self._first_seen[pid] = min(self._first_seen.get(pid, signal.ts_ns), signal.ts_ns)
            self._last_seen[pid] = max(self._last_seen.get(pid, signal.ts_ns), signal.ts_ns)
            comm = signal.tags.get("comm")
            if comm:
                self._comm_by_pid[pid] = comm

        if signal.metric == "cpu.util_pct" and pid is not None:
            self._cpu_current[pid] = signal.value
            total_cpu = sum(self._cpu_current.values())
            if total_cpu > self.peak_total_cpu_pct:
                self.peak_total_cpu_pct = total_cpu

        if signal.metric == "mem.rss_bytes" and pid is not None:
            self._rss_current[pid] = signal.value
            total_rss = sum(self._rss_current.values())
            if total_rss > self.peak_total_rss_bytes:
                self.peak_total_rss_bytes = total_rss

    def build_run_row(
        self,
        ctx: MonitorContext,
        end_ns: int,
        exit_code: int,
        sample_count: int,
    ) -> dict[str, object]:
        duration_sec = max(0.0, (end_ns - ctx.start_ns) / 1e9)
        return {
            "run_id": ctx.run_id,
            "command": " ".join(ctx.command),
            "start_ns": ctx.start_ns,
            "end_ns": end_ns,
            "duration_sec": duration_sec,
            "exit_code": exit_code,
            "interval_sec": ctx.interval_sec,
            "sample_count": sample_count,
            "peak_total_cpu_pct": self.peak_total_cpu_pct,
            "peak_total_rss_bytes": self.peak_total_rss_bytes,
        }

    def build_process_rows(self, run_id: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for pid in sorted(self._first_seen):
            rows.append(
                {
                    "run_id": run_id,
                    "pid": pid,
                    "comm": self._comm_by_pid.get(pid, ""),
                    "first_seen_ns": self._first_seen[pid],
                    "last_seen_ns": self._last_seen.get(pid, self._first_seen[pid]),
                }
            )
        return rows

    def build_metric_rows(self, run_id: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for (sensor, metric, pid), stat in sorted(
            self._stats.items(), key=lambda x: (x[0][0], x[0][1], -1 if x[0][2] is None else x[0][2])
        ):
            rows.append(
                {
                    "run_id": run_id,
                    "sensor": sensor,
                    "metric": metric,
                    "pid": pid,
                    "unit": stat.unit,
                    "sample_count": stat.count,
                    "min": stat.min_value,
                    "max": stat.max_value,
                    "avg": stat.avg,
                    "last": stat.last_value,
                }
            )
        return rows
