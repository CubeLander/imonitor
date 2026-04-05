from __future__ import annotations

from collections import defaultdict

from imonitor.core.types import MonitorContext
from imonitor.remote.client import RemoteDaemonClient
from imonitor.pipelines.aggregator import Aggregator
from imonitor.pipelines.rollup import build_rollup_rows
from imonitor.sinks.base import Sink
from imonitor.sinks.live_sink import LiveSink
from imonitor.signals.bus import SignalBus
from imonitor.signals.normalize import normalize_signal


class Hub:
    def __init__(
        self,
        sinks: list[Sink],
        live_sink: LiveSink | None = None,
        remote_client: RemoteDaemonClient | None = None,
    ) -> None:
        self.sinks = sinks
        self.live_sink = live_sink
        self.remote_client = remote_client
        self.aggregator = Aggregator()
        self.raw_rows: list[dict[str, object]] = []

    async def run(self, bus: SignalBus) -> None:
        while True:
            sig = await bus.get()
            if sig is None:
                break
            normalized = normalize_signal(sig)
            if normalized is None:
                continue
            self.aggregator.ingest(normalized)
            row = normalized.to_row()
            self.raw_rows.append(row)
            if self.remote_client is not None:
                self.remote_client.record_signal(row)
            if self.live_sink is not None:
                self.live_sink.ingest(normalized, self.aggregator)

    @staticmethod
    def _build_frame_rows(run_id: str, raw_rows: list[dict[str, object]]) -> list[dict[str, object]]:
        signal_count_by_ts: dict[int, int] = defaultdict(int)
        pid_set_by_ts: dict[int, set[int]] = defaultdict(set)

        for row in raw_rows:
            ts_ns = int(row["ts_ns"])
            signal_count_by_ts[ts_ns] += 1
            pid = row.get("pid")
            if pid is not None:
                pid_set_by_ts[ts_ns].add(int(pid))

        frame_rows: list[dict[str, object]] = []
        for i, ts_ns in enumerate(sorted(signal_count_by_ts), start=1):
            frame_rows.append(
                {
                    "run_id": run_id,
                    "frame_id": i,
                    "ts_ns": ts_ns,
                    "signal_count": signal_count_by_ts[ts_ns],
                    "active_pids": len(pid_set_by_ts.get(ts_ns, set())),
                }
            )
        return frame_rows

    def persist(
        self,
        ctx: MonitorContext,
        end_ns: int,
        exit_code: int,
    ) -> tuple[
        dict[str, object],
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, object]],
    ]:
        run_row = self.aggregator.build_run_row(
            ctx=ctx,
            end_ns=end_ns,
            exit_code=exit_code,
            sample_count=len(self.raw_rows),
        )
        process_rows = self.aggregator.build_process_rows(ctx.run_id)
        agg_rows = self.aggregator.build_metric_rows(ctx.run_id)
        frame_rows = self._build_frame_rows(ctx.run_id, self.raw_rows)
        rollup_rows = build_rollup_rows(self.raw_rows, bucket_ns=1_000_000_000)

        for sink in self.sinks:
            sink.persist(
                run_row=run_row,
                process_rows=process_rows,
                raw_rows=self.raw_rows,
                agg_rows=agg_rows,
                frame_rows=frame_rows,
                rollup_rows=rollup_rows,
            )

        return run_row, process_rows, agg_rows, frame_rows, rollup_rows
