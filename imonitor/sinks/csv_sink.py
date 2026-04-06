from __future__ import annotations

import csv
from pathlib import Path


class CSVSink:
    name = "csv"

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def persist(
        self,
        run_row: dict[str, object],
        process_rows: list[dict[str, object]],
        raw_rows: list[dict[str, object]],
        agg_rows: list[dict[str, object]],
        frame_rows: list[dict[str, object]],
        rollup_rows: list[dict[str, object]],
    ) -> None:
        run_id = str(run_row["run_id"])
        self._write_rows(
            self.out_dir / f"{run_id}_run.csv",
            [run_row],
            [
                "run_id",
                "command",
                "start_ns",
                "end_ns",
                "duration_sec",
                "exit_code",
                "interval_sec",
                "sample_count",
                "peak_total_cpu_pct",
                "peak_total_rss_bytes",
            ],
        )
        self._write_rows(
            self.out_dir / f"{run_id}_processes.csv",
            process_rows,
            ["run_id", "pid", "comm", "first_seen_ns", "last_seen_ns"],
        )
        self._write_rows(
            self.out_dir / f"{run_id}_metrics_raw.csv",
            raw_rows,
            ["run_id", "ts_ns", "sensor", "metric", "value", "unit", "pid", "tags_json"],
        )
        self._write_rows(
            self.out_dir / f"{run_id}_metrics_agg.csv",
            agg_rows,
            ["run_id", "sensor", "metric", "pid", "unit", "sample_count", "min", "max", "avg", "last"],
        )
        self._write_rows(
            self.out_dir / f"{run_id}_frames.csv",
            frame_rows,
            ["run_id", "frame_id", "ts_ns", "signal_count", "active_pids"],
        )
        self._write_rows(
            self.out_dir / f"{run_id}_metrics_rollup.csv",
            rollup_rows,
            [
                "run_id",
                "sensor",
                "metric",
                "pid",
                "unit",
                "bucket_ns",
                "bucket_start_ns",
                "sample_count",
                "min",
                "max",
                "avg",
                "p95",
                "last",
            ],
        )

    @staticmethod
    def _write_rows(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
