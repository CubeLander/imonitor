from __future__ import annotations

import time

from imonitor.pipelines.aggregator import Aggregator
from imonitor.signals.schema import Signal


class LiveSink:
    def __init__(self, refresh_sec: float = 1.0) -> None:
        self.refresh_sec = refresh_sec
        self._last_print_by_metric: dict[str, float] = {}

    def ingest(self, signal: Signal, aggregator: Aggregator) -> None:
        now = time.monotonic()
        if signal.metric not in {
            "proc.count",
            "cpu.util_pct",
            "mem.rss_bytes",
            "io.read_bps",
            "io.write_bps",
            "gpu.device.util_pct",
            "gpu.proc.mem_used_bytes",
        }:
            return

        last = self._last_print_by_metric.get(signal.metric, 0.0)
        if now - last < self.refresh_sec:
            return
        self._last_print_by_metric[signal.metric] = now

        print(
            "[live] "
            f"metric={signal.metric} "
            f"value={signal.value:.3f} "
            f"pid={signal.pid} "
            f"peak_cpu_pct={aggregator.peak_total_cpu_pct:.2f} "
            f"peak_rss_mb={aggregator.peak_total_rss_bytes / (1024 * 1024):.2f}"
        )
