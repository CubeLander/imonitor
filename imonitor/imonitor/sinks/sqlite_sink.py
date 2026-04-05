from __future__ import annotations

import sqlite3
from pathlib import Path


class SQLiteSink:
    name = "sqlite"

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                start_ns INTEGER NOT NULL,
                end_ns INTEGER NOT NULL,
                duration_sec REAL NOT NULL,
                exit_code INTEGER NOT NULL,
                interval_sec REAL NOT NULL,
                sample_count INTEGER NOT NULL,
                peak_total_cpu_pct REAL NOT NULL,
                peak_total_rss_bytes REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS processes (
                run_id TEXT NOT NULL,
                pid INTEGER NOT NULL,
                comm TEXT,
                first_seen_ns INTEGER NOT NULL,
                last_seen_ns INTEGER NOT NULL,
                PRIMARY KEY (run_id, pid)
            );

            CREATE TABLE IF NOT EXISTS metrics_raw (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ts_ns INTEGER NOT NULL,
                sensor TEXT NOT NULL,
                metric TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT NOT NULL,
                pid INTEGER,
                tags_json TEXT
            );

            CREATE TABLE IF NOT EXISTS metrics_agg (
                run_id TEXT NOT NULL,
                sensor TEXT NOT NULL,
                metric TEXT NOT NULL,
                pid INTEGER,
                unit TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                min REAL NOT NULL,
                max REAL NOT NULL,
                avg REAL NOT NULL,
                last REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS frames (
                run_id TEXT NOT NULL,
                frame_id INTEGER NOT NULL,
                ts_ns INTEGER NOT NULL,
                signal_count INTEGER NOT NULL,
                active_pids INTEGER NOT NULL,
                PRIMARY KEY (run_id, frame_id)
            );

            CREATE TABLE IF NOT EXISTS metrics_rollup (
                run_id TEXT NOT NULL,
                sensor TEXT NOT NULL,
                metric TEXT NOT NULL,
                pid INTEGER,
                unit TEXT NOT NULL,
                bucket_ns INTEGER NOT NULL,
                bucket_start_ns INTEGER NOT NULL,
                sample_count INTEGER NOT NULL,
                min REAL NOT NULL,
                max REAL NOT NULL,
                avg REAL NOT NULL,
                p95 REAL NOT NULL,
                last REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_metrics_raw_run_ts ON metrics_raw(run_id, ts_ns);
            CREATE INDEX IF NOT EXISTS idx_metrics_raw_metric ON metrics_raw(run_id, metric);
            CREATE INDEX IF NOT EXISTS idx_metrics_agg_run_metric ON metrics_agg(run_id, metric);
            CREATE INDEX IF NOT EXISTS idx_frames_run_ts ON frames(run_id, ts_ns);
            CREATE INDEX IF NOT EXISTS idx_metrics_rollup_run_metric_bucket ON metrics_rollup(run_id, metric, bucket_start_ns);
            """
        )
        self._conn.commit()

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
        cur = self._conn.cursor()

        cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        cur.execute("DELETE FROM processes WHERE run_id = ?", (run_id,))
        cur.execute("DELETE FROM metrics_raw WHERE run_id = ?", (run_id,))
        cur.execute("DELETE FROM metrics_agg WHERE run_id = ?", (run_id,))
        cur.execute("DELETE FROM frames WHERE run_id = ?", (run_id,))
        cur.execute("DELETE FROM metrics_rollup WHERE run_id = ?", (run_id,))

        cur.execute(
            """
            INSERT INTO runs(
                run_id, command, start_ns, end_ns, duration_sec, exit_code,
                interval_sec, sample_count, peak_total_cpu_pct, peak_total_rss_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_row["run_id"],
                run_row["command"],
                run_row["start_ns"],
                run_row["end_ns"],
                run_row["duration_sec"],
                run_row["exit_code"],
                run_row["interval_sec"],
                run_row["sample_count"],
                run_row["peak_total_cpu_pct"],
                run_row["peak_total_rss_bytes"],
            ),
        )

        if process_rows:
            cur.executemany(
                """
                INSERT INTO processes(run_id, pid, comm, first_seen_ns, last_seen_ns)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["run_id"],
                        row["pid"],
                        row["comm"],
                        row["first_seen_ns"],
                        row["last_seen_ns"],
                    )
                    for row in process_rows
                ],
            )

        if raw_rows:
            cur.executemany(
                """
                INSERT INTO metrics_raw(run_id, ts_ns, sensor, metric, value, unit, pid, tags_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["run_id"],
                        row["ts_ns"],
                        row["sensor"],
                        row["metric"],
                        row["value"],
                        row["unit"],
                        row["pid"],
                        row["tags_json"],
                    )
                    for row in raw_rows
                ],
            )

        if agg_rows:
            cur.executemany(
                """
                INSERT INTO metrics_agg(run_id, sensor, metric, pid, unit, sample_count, min, max, avg, last)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["run_id"],
                        row["sensor"],
                        row["metric"],
                        row["pid"],
                        row["unit"],
                        row["sample_count"],
                        row["min"],
                        row["max"],
                        row["avg"],
                        row["last"],
                    )
                    for row in agg_rows
                ],
            )

        if frame_rows:
            cur.executemany(
                """
                INSERT INTO frames(run_id, frame_id, ts_ns, signal_count, active_pids)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["run_id"],
                        row["frame_id"],
                        row["ts_ns"],
                        row["signal_count"],
                        row["active_pids"],
                    )
                    for row in frame_rows
                ],
            )

        if rollup_rows:
            cur.executemany(
                """
                INSERT INTO metrics_rollup(
                    run_id, sensor, metric, pid, unit, bucket_ns, bucket_start_ns,
                    sample_count, min, max, avg, p95, last
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["run_id"],
                        row["sensor"],
                        row["metric"],
                        row["pid"],
                        row["unit"],
                        row["bucket_ns"],
                        row["bucket_start_ns"],
                        row["sample_count"],
                        row["min"],
                        row["max"],
                        row["avg"],
                        row["p95"],
                        row["last"],
                    )
                    for row in rollup_rows
                ],
            )

        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
