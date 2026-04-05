from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DaemonStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript(
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
                    peak_total_rss_bytes REAL NOT NULL,
                    root_pid INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'running',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
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

                CREATE TABLE IF NOT EXISTS run_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    ts_ns INTEGER NOT NULL,
                    stream TEXT NOT NULL,
                    text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_pid_live (
                    run_id TEXT NOT NULL,
                    pid INTEGER NOT NULL,
                    last_seen_ns INTEGER NOT NULL,
                    PRIMARY KEY (run_id, pid)
                );

                CREATE TABLE IF NOT EXISTS system_host_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_ns INTEGER NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_metrics_raw_run_ts ON metrics_raw(run_id, ts_ns);
                CREATE INDEX IF NOT EXISTS idx_metrics_raw_metric ON metrics_raw(run_id, metric);
                CREATE INDEX IF NOT EXISTS idx_metrics_agg_run_metric ON metrics_agg(run_id, metric);
                CREATE INDEX IF NOT EXISTS idx_frames_run_ts ON frames(run_id, ts_ns);
                CREATE INDEX IF NOT EXISTS idx_metrics_rollup_run_metric_bucket ON metrics_rollup(run_id, metric, bucket_start_ns);
                CREATE INDEX IF NOT EXISTS idx_run_logs_run_ts ON run_logs(run_id, ts_ns);
                CREATE INDEX IF NOT EXISTS idx_system_host_samples_metric_ts ON system_host_samples(metric, ts_ns);
                """
            )
            self._ensure_column(conn, "runs", "root_pid", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "runs", "status", "TEXT NOT NULL DEFAULT 'running'")
            self._ensure_column(conn, "runs", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if any(str(row["name"]) == column for row in rows):
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def start_run(self, payload: dict[str, object]) -> dict[str, object]:
        command_obj = payload.get("command", [])
        if isinstance(command_obj, list):
            command_text = " ".join(str(item) for item in command_obj)
        else:
            command_text = str(command_obj)

        metadata_json = json.dumps(payload.get("metadata") or {}, ensure_ascii=False, sort_keys=True)
        row = {
            "run_id": payload["run_id"],
            "command": command_text,
            "start_ns": payload["start_ns"],
            "end_ns": payload["start_ns"],
            "duration_sec": 0.0,
            "exit_code": -1,
            "interval_sec": payload["interval_sec"],
            "sample_count": 0,
            "peak_total_cpu_pct": 0.0,
            "peak_total_rss_bytes": 0.0,
            "root_pid": payload["root_pid"],
            "status": "running",
            "metadata_json": metadata_json,
        }

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(
                    run_id, command, start_ns, end_ns, duration_sec, exit_code,
                    interval_sec, sample_count, peak_total_cpu_pct, peak_total_rss_bytes,
                    root_pid, status, metadata_json
                ) VALUES (
                    :run_id, :command, :start_ns, :end_ns, :duration_sec, :exit_code,
                    :interval_sec, :sample_count, :peak_total_cpu_pct, :peak_total_rss_bytes,
                    :root_pid, :status, :metadata_json
                )
                ON CONFLICT(run_id) DO UPDATE SET
                    command = excluded.command,
                    start_ns = excluded.start_ns,
                    end_ns = excluded.end_ns,
                    duration_sec = excluded.duration_sec,
                    exit_code = excluded.exit_code,
                    interval_sec = excluded.interval_sec,
                    sample_count = excluded.sample_count,
                    peak_total_cpu_pct = excluded.peak_total_cpu_pct,
                    peak_total_rss_bytes = excluded.peak_total_rss_bytes,
                    root_pid = excluded.root_pid,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json
                """,
                row,
            )
            if int(row["root_pid"]) > 0:
                conn.execute(
                    """
                    INSERT INTO run_pid_live(run_id, pid, last_seen_ns)
                    VALUES (?, ?, ?)
                    ON CONFLICT(run_id, pid) DO UPDATE SET
                        last_seen_ns = excluded.last_seen_ns
                    """,
                    (str(row["run_id"]), int(row["root_pid"]), int(row["start_ns"])),
                )
        return row

    def append_signals(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        run_id = str(rows[0]["run_id"])
        latest_ts_ns = max(int(row["ts_ns"]) for row in rows)
        with self.connect() as conn:
            root_row = conn.execute("SELECT root_pid FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            known_pids = {
                int(r["pid"])
                for r in conn.execute("SELECT pid FROM run_pid_live WHERE run_id = ?", (run_id,)).fetchall()
            }
            if root_row is not None:
                root_pid = int(root_row["root_pid"])
                if root_pid > 0:
                    known_pids.add(root_pid)

            alive_updates: dict[int, int] = {}
            for row in rows:
                pid_obj = row.get("pid")
                if pid_obj is None:
                    continue
                try:
                    pid = int(pid_obj)
                except (TypeError, ValueError):
                    continue
                if str(row.get("metric")) != "proc.alive":
                    continue
                ts_ns = int(row["ts_ns"])
                prev = alive_updates.get(pid)
                if prev is None or ts_ns > prev:
                    alive_updates[pid] = ts_ns

            if alive_updates:
                conn.executemany(
                    """
                    INSERT INTO run_pid_live(run_id, pid, last_seen_ns)
                    VALUES (?, ?, ?)
                    ON CONFLICT(run_id, pid) DO UPDATE SET
                        last_seen_ns = CASE
                            WHEN run_pid_live.last_seen_ns < excluded.last_seen_ns THEN excluded.last_seen_ns
                            ELSE run_pid_live.last_seen_ns
                        END
                    """,
                    [(run_id, pid, ts_ns) for pid, ts_ns in alive_updates.items()],
                )
                known_pids.update(alive_updates.keys())

            filtered_rows: list[dict[str, object]] = []
            for row in rows:
                pid_obj = row.get("pid")
                if pid_obj is None:
                    filtered_rows.append(row)
                    continue
                try:
                    pid = int(pid_obj)
                except (TypeError, ValueError):
                    continue
                metric = str(row.get("metric"))
                if metric in {"proc.alive", "proc.count"}:
                    filtered_rows.append(row)
                    continue
                if pid in known_pids:
                    filtered_rows.append(row)

            if filtered_rows:
                conn.executemany(
                    """
                    INSERT INTO metrics_raw(run_id, ts_ns, sensor, metric, value, unit, pid, tags_json)
                    VALUES (:run_id, :ts_ns, :sensor, :metric, :value, :unit, :pid, :tags_json)
                    """,
                    filtered_rows,
                )
            conn.execute(
                """
                UPDATE runs
                SET sample_count = sample_count + ?,
                    end_ns = CASE WHEN end_ns < ? THEN ? ELSE end_ns END
                WHERE run_id = ?
                """,
                (len(filtered_rows), latest_ts_ns, latest_ts_ns, run_id),
            )
        return len(filtered_rows)

    def append_logs(self, run_id: str, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        payload = []
        for row in rows:
            payload.append(
                {
                    "run_id": run_id,
                    "ts_ns": row["ts_ns"],
                    "stream": row.get("stream", "combined"),
                    "text": row["text"],
                }
            )
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO run_logs(run_id, ts_ns, stream, text)
                VALUES (:run_id, :ts_ns, :stream, :text)
                """,
                payload,
            )
        return len(payload)

    def finish_run(self, payload: dict[str, object]) -> dict[str, int]:
        run_row = dict(payload["run_row"])
        run_id = str(run_row["run_id"])

        with self.connect() as conn:
            existing = conn.execute(
                "SELECT root_pid, metadata_json FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            root_pid = run_row.get("root_pid")
            if root_pid is None and existing is not None:
                root_pid = existing["root_pid"]
            if root_pid is None:
                root_pid = 0

            metadata_json = run_row.get("metadata_json")
            if metadata_json is None and existing is not None:
                metadata_json = existing["metadata_json"]
            if metadata_json is None:
                metadata_json = "{}"

            conn.execute(
                """
                INSERT INTO runs(
                    run_id, command, start_ns, end_ns, duration_sec, exit_code,
                    interval_sec, sample_count, peak_total_cpu_pct, peak_total_rss_bytes,
                    root_pid, status, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    command = excluded.command,
                    start_ns = excluded.start_ns,
                    end_ns = excluded.end_ns,
                    duration_sec = excluded.duration_sec,
                    exit_code = excluded.exit_code,
                    interval_sec = excluded.interval_sec,
                    sample_count = excluded.sample_count,
                    peak_total_cpu_pct = excluded.peak_total_cpu_pct,
                    peak_total_rss_bytes = excluded.peak_total_rss_bytes,
                    root_pid = excluded.root_pid,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json
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
                    root_pid,
                    "completed",
                    metadata_json if isinstance(metadata_json, str) else json.dumps(metadata_json, ensure_ascii=False, sort_keys=True),
                ),
            )

            conn.execute("DELETE FROM processes WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM metrics_agg WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM frames WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM metrics_rollup WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM run_pid_live WHERE run_id = ?", (run_id,))

            process_rows = payload.get("process_rows", [])
            if process_rows:
                conn.executemany(
                    """
                    INSERT INTO processes(run_id, pid, comm, first_seen_ns, last_seen_ns)
                    VALUES (:run_id, :pid, :comm, :first_seen_ns, :last_seen_ns)
                    """,
                    process_rows,
                )

            agg_rows = payload.get("agg_rows", [])
            if agg_rows:
                conn.executemany(
                    """
                    INSERT INTO metrics_agg(run_id, sensor, metric, pid, unit, sample_count, min, max, avg, last)
                    VALUES (:run_id, :sensor, :metric, :pid, :unit, :sample_count, :min, :max, :avg, :last)
                    """,
                    agg_rows,
                )

            frame_rows = payload.get("frame_rows", [])
            if frame_rows:
                conn.executemany(
                    """
                    INSERT INTO frames(run_id, frame_id, ts_ns, signal_count, active_pids)
                    VALUES (:run_id, :frame_id, :ts_ns, :signal_count, :active_pids)
                    ON CONFLICT(run_id, frame_id) DO UPDATE SET
                        ts_ns = excluded.ts_ns,
                        signal_count = excluded.signal_count,
                        active_pids = excluded.active_pids
                    """,
                    frame_rows,
                )

            rollup_rows = payload.get("rollup_rows", [])
            if rollup_rows:
                conn.executemany(
                    """
                    INSERT INTO metrics_rollup(
                        run_id, sensor, metric, pid, unit, bucket_ns, bucket_start_ns,
                        sample_count, min, max, avg, p95, last
                    ) VALUES (:run_id, :sensor, :metric, :pid, :unit, :bucket_ns, :bucket_start_ns,
                              :sample_count, :min, :max, :avg, :p95, :last)
                    """,
                    rollup_rows,
                )

        return {
            "run_row": 1,
            "process_rows": len(payload.get("process_rows", [])),
            "agg_rows": len(payload.get("agg_rows", [])),
            "frame_rows": len(payload.get("frame_rows", [])),
            "rollup_rows": len(payload.get("rollup_rows", [])),
        }

    def recent_runs(self, limit: int) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    run_id, command, start_ns, end_ns, duration_sec, exit_code,
                    interval_sec, sample_count, peak_total_cpu_pct, peak_total_rss_bytes,
                    root_pid, status, metadata_json
                FROM runs
                ORDER BY start_ns DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def run_metrics(self, run_id: str) -> dict[str, object]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT sensor, metric, unit
                FROM metrics_agg
                WHERE run_id = ?
                ORDER BY sensor, metric
                """,
                (run_id,),
            ).fetchall()
            if not rows:
                # During in-progress runs, metrics_agg may be empty; fallback to raw stream schema.
                rows = conn.execute(
                    """
                    SELECT sensor, metric, unit
                    FROM metrics_raw
                    WHERE run_id = ?
                    GROUP BY sensor, metric, unit
                    ORDER BY sensor, metric
                    """,
                    (run_id,),
                ).fetchall()
        metrics = [dict(row) for row in rows]
        sensors = sorted({str(m["sensor"]) for m in metrics})
        return {"run_id": run_id, "metrics": metrics, "sensors": sensors}

    def run_pids(self, run_id: str) -> dict[str, object]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT pid, comm, first_seen_ns, last_seen_ns
                FROM processes
                WHERE run_id = ?
                ORDER BY pid
                """,
                (run_id,),
            ).fetchall()
        return {"run_id": run_id, "pids": [dict(row) for row in rows]}

    def run_series(
        self,
        run_id: str,
        metric: str,
        sensor: str | None,
        pid: int | None,
        rollup: bool,
        bucket_ns: int,
        limit: int,
    ) -> dict[str, object]:
        with self.connect() as conn:
            if rollup:
                rows = conn.execute(
                    """
                    SELECT
                        bucket_start_ns AS ts_ns,
                        sensor, metric, pid, unit,
                        avg AS value,
                        min, max, p95, sample_count
                    FROM metrics_rollup
                    WHERE run_id = ?
                      AND metric = ?
                      AND bucket_ns = ?
                      AND (? IS NULL OR sensor = ?)
                      AND (? IS NULL OR pid = ?)
                    ORDER BY ts_ns
                    """,
                    (run_id, metric, bucket_ns, sensor, sensor, pid, pid),
                ).fetchall()
                mode = "rollup"
            else:
                rows = conn.execute(
                    """
                    SELECT ts_ns, sensor, metric, pid, unit, value
                    FROM metrics_raw
                    WHERE run_id = ?
                      AND metric = ?
                      AND (? IS NULL OR sensor = ?)
                      AND (? IS NULL OR pid = ?)
                    ORDER BY ts_ns
                    LIMIT ?
                    """,
                    (run_id, metric, sensor, sensor, pid, pid, limit),
                ).fetchall()
                mode = "raw"

        return {"run_id": run_id, "mode": mode, "rows": [dict(row) for row in rows]}

    def latest_tables(self, run_id: str, limit: int) -> dict[str, list[dict[str, object]]]:
        with self.connect() as conn:
            run = conn.execute(
                """
                SELECT
                    run_id, command, start_ns, end_ns, duration_sec, exit_code,
                    interval_sec, sample_count, peak_total_cpu_pct, peak_total_rss_bytes,
                    root_pid, status, metadata_json
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

            processes = conn.execute(
                """
                SELECT run_id, pid, comm, first_seen_ns, last_seen_ns
                FROM processes
                WHERE run_id = ?
                ORDER BY pid
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
            raw_rows = conn.execute(
                """
                SELECT run_id, ts_ns, sensor, metric, value, unit, pid, tags_json
                FROM metrics_raw
                WHERE run_id = ?
                ORDER BY ts_ns DESC, id DESC
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
            agg_rows = conn.execute(
                """
                SELECT run_id, sensor, metric, pid, unit, sample_count, min, max, avg, last
                FROM metrics_agg
                WHERE run_id = ?
                ORDER BY sensor, metric, pid
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
            frame_rows = conn.execute(
                """
                SELECT run_id, frame_id, ts_ns, signal_count, active_pids
                FROM frames
                WHERE run_id = ?
                ORDER BY frame_id DESC
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
            rollup_rows = conn.execute(
                """
                SELECT
                    run_id, sensor, metric, pid, unit, bucket_ns, bucket_start_ns,
                    sample_count, min, max, avg, p95, last
                FROM metrics_rollup
                WHERE run_id = ?
                ORDER BY bucket_start_ns DESC, sensor, metric
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
            log_rows = conn.execute(
                """
                SELECT run_id, ts_ns, stream, text
                FROM run_logs
                WHERE run_id = ?
                ORDER BY ts_ns DESC, id DESC
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()

        return {
            "runs": [dict(run)] if run is not None else [],
            "processes": [dict(row) for row in processes],
            "metrics_raw": [dict(row) for row in reversed(raw_rows)],
            "frames": [dict(row) for row in reversed(frame_rows)],
            "metrics_agg": [dict(row) for row in agg_rows],
            "metrics_rollup": [dict(row) for row in reversed(rollup_rows)],
            "run_logs": [dict(row) for row in reversed(log_rows)],
        }

    def recent_logs(self, run_id: str, limit: int) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, ts_ns, stream, text
                FROM run_logs
                WHERE run_id = ?
                ORDER BY ts_ns DESC, id DESC
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def append_system_host_samples(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO system_host_samples(ts_ns, metric, value, unit)
                VALUES (:ts_ns, :metric, :value, :unit)
                """,
                rows,
            )
        return len(rows)

    def system_host_latest(self) -> dict[str, object]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.metric, s.value, s.unit, s.ts_ns
                FROM system_host_samples AS s
                JOIN (
                    SELECT metric, MAX(ts_ns) AS max_ts
                    FROM system_host_samples
                    GROUP BY metric
                ) AS latest
                  ON latest.metric = s.metric
                 AND latest.max_ts = s.ts_ns
                ORDER BY s.metric
                """
            ).fetchall()
        summary = {str(row["metric"]): float(row["value"]) for row in rows}
        latest_ts_ns = max((int(row["ts_ns"]) for row in rows), default=None)
        return {"latest_ts_ns": latest_ts_ns, "rows": [dict(row) for row in rows], "summary": summary}

    def system_host_performance(self, seconds: int) -> dict[str, object]:
        seconds = max(10, min(86_400, int(seconds)))
        with self.connect() as conn:
            latest_ts_row = conn.execute("SELECT MAX(ts_ns) AS latest_ts_ns FROM system_host_samples").fetchone()
            latest_ts_ns = int(latest_ts_row["latest_ts_ns"]) if latest_ts_row and latest_ts_row["latest_ts_ns"] is not None else int(time.time_ns())
            start_ts_ns = latest_ts_ns - seconds * 1_000_000_000

            rows = conn.execute(
                """
                SELECT ts_ns, metric, value
                FROM system_host_samples
                WHERE ts_ns >= ?
                ORDER BY ts_ns, metric
                """,
                (start_ts_ns,),
            ).fetchall()

        series: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            metric = str(row["metric"])
            series.setdefault(metric, []).append({"ts_ns": int(row["ts_ns"]), "value": float(row["value"])})
        return {"seconds": seconds, "latest_ts_ns": latest_ts_ns, "series": series}

    def taskmanager_runs(self, limit: int) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    run_id, command, start_ns, end_ns, duration_sec, exit_code,
                    interval_sec, sample_count, root_pid, status
                FROM runs
                ORDER BY start_ns DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def taskmanager_running_runs(self, limit: int = 100) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    run_id, command, start_ns, end_ns, duration_sec, exit_code,
                    interval_sec, sample_count, root_pid, status
                FROM runs
                WHERE status = 'running'
                ORDER BY start_ns DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_run_pid_metrics(
        self,
        run_ids: list[str],
        pids: list[int],
        metric_prefixes: list[str],
    ) -> list[dict[str, object]]:
        run_ids_clean = [str(x) for x in run_ids if str(x)]
        pids_clean = []
        for pid in pids:
            try:
                p = int(pid)
            except (TypeError, ValueError):
                continue
            if p > 0:
                pids_clean.append(p)
        prefixes = [str(x) for x in metric_prefixes if str(x)]
        if not run_ids_clean or not pids_clean or not prefixes:
            return []

        metric_clause = " OR ".join("metric LIKE ?" for _ in prefixes)
        # Keep sqlite bind parameter count under the common 999 default.
        max_bind = 900
        base_bind = len(run_ids_clean) + len(prefixes)
        chunk_size = max(1, min(500, max_bind - base_bind))

        rows = []
        run_placeholders = ",".join("?" for _ in run_ids_clean)
        with self.connect() as conn:
            for i in range(0, len(pids_clean), chunk_size):
                pid_chunk = pids_clean[i : i + chunk_size]
                pid_placeholders = ",".join("?" for _ in pid_chunk)
                params: list[object] = [*run_ids_clean, *pid_chunk, *[f"{prefix}%" for prefix in prefixes]]
                rows.extend(
                    conn.execute(
                        f"""
                        SELECT run_id, pid, metric, value, unit, ts_ns
                        FROM metrics_raw
                        WHERE run_id IN ({run_placeholders})
                          AND pid IN ({pid_placeholders})
                          AND ({metric_clause})
                        ORDER BY ts_ns DESC, id DESC
                        """,
                        params,
                    ).fetchall()
                )

        latest: dict[tuple[str, int, str], dict[str, object]] = {}
        for row in rows:
            run_id = str(row["run_id"])
            pid = int(row["pid"])
            metric = str(row["metric"])
            key = (run_id, pid, metric)
            if key in latest:
                continue
            latest[key] = {
                "run_id": run_id,
                "pid": pid,
                "metric": metric,
                "value": float(row["value"]),
                "unit": str(row["unit"]),
                "ts_ns": int(row["ts_ns"]),
            }
        return list(latest.values())

    @staticmethod
    def _decode_tags_json(raw: object) -> dict[str, str]:
        if raw is None:
            return {}
        data: object = raw
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return {}
            try:
                data = json.loads(text)
            except Exception:
                return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in data.items():
            out[str(k)] = str(v)
        return out

    @classmethod
    def _pcie_channel_from_tags(cls, raw_tags: object) -> str | None:
        tags = cls._decode_tags_json(raw_tags)
        gpu_index = str(tags.get("gpu_index", "")).strip()
        if not gpu_index:
            return None
        if gpu_index.startswith("gpu"):
            return gpu_index
        if gpu_index.isdigit():
            return f"gpu{gpu_index}"
        return re.sub(r"[^a-zA-Z0-9_-]+", "_", gpu_index)

    @staticmethod
    def _channel_sort_key(name: str) -> tuple[int, int, str]:
        m = re.fullmatch(r"gpu(\d+)", str(name))
        if m:
            return (0, int(m.group(1)), str(name))
        return (1, 0, str(name))

    @staticmethod
    def _latest_scalar_metric(conn: sqlite3.Connection, run_id: str, metric: str) -> tuple[float, int] | None:
        row = conn.execute(
            """
            SELECT value, ts_ns
            FROM metrics_raw
            WHERE run_id = ? AND metric = ?
            ORDER BY ts_ns DESC, id DESC
            LIMIT 1
            """,
            (run_id, metric),
        ).fetchone()
        if row is None:
            return None
        return float(row["value"]), int(row["ts_ns"])

    @staticmethod
    def _latest_scalar_metric_agg(
        conn: sqlite3.Connection,
        run_id: str,
        metric: str,
        agg: str,
        pid_clause: str = "pid IS NULL",
    ) -> tuple[float, int] | None:
        agg_upper = agg.strip().upper()
        if agg_upper not in {"SUM", "AVG", "MAX", "MIN"}:
            raise ValueError(f"unsupported agg: {agg}")
        latest_row = conn.execute(
            f"""
            SELECT {agg_upper}(value) AS value, ts_ns
            FROM metrics_raw
            WHERE run_id = ?
              AND metric = ?
              AND {pid_clause}
              AND ts_ns = (
                SELECT MAX(ts_ns)
                FROM metrics_raw
                WHERE run_id = ?
                  AND metric = ?
                  AND {pid_clause}
              )
            GROUP BY ts_ns
            LIMIT 1
            """,
            (run_id, metric, run_id, metric),
        ).fetchone()
        if latest_row is None:
            return None
        return float(latest_row["value"]), int(latest_row["ts_ns"])

    def taskmanager_snapshot(self, run_id: str) -> dict[str, object]:
        with self.connect() as conn:
            run = conn.execute(
                """
                SELECT
                    run_id, command, start_ns, end_ns, duration_sec, exit_code,
                    interval_sec, sample_count, root_pid, status
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                return {"run_id": run_id, "run": None, "summary": {}, "processes": [], "latest_ts_ns": None, "pcie_channels": {}}

            latest_ts_row = conn.execute(
                "SELECT MAX(ts_ns) AS latest_ts_ns FROM metrics_raw WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            latest_ts_ns = int(latest_ts_row["latest_ts_ns"]) if latest_ts_row and latest_ts_row["latest_ts_ns"] is not None else None

            process_rows = conn.execute(
                """
                SELECT pid, comm, first_seen_ns, last_seen_ns
                FROM processes
                WHERE run_id = ?
                ORDER BY pid
                """,
                (run_id,),
            ).fetchall()
            pid_meta = {int(r["pid"]): dict(r) for r in process_rows}

            tracked_metrics = (
                "cpu.util_pct",
                "mem.rss_bytes",
                "io.read_bps",
                "io.write_bps",
                "net.rx_bps",
                "net.tx_bps",
                "gpu.proc.mem_used_bytes",
            )
            placeholders = ",".join("?" for _ in tracked_metrics)
            raw_rows = conn.execute(
                f"""
                SELECT pid, metric, value, ts_ns
                FROM metrics_raw
                WHERE run_id = ?
                  AND pid IS NOT NULL
                  AND metric IN ({placeholders})
                ORDER BY ts_ns DESC, id DESC
                """,
                (run_id, *tracked_metrics),
            ).fetchall()

        latest_by_pid_metric: dict[tuple[int, str], tuple[float, int]] = {}
        for row in raw_rows:
            pid = int(row["pid"])
            metric = str(row["metric"])
            key = (pid, metric)
            if key in latest_by_pid_metric:
                continue
            latest_by_pid_metric[key] = (float(row["value"]), int(row["ts_ns"]))
        has_gpu_proc_metric = any(metric == "gpu.proc.mem_used_bytes" for _, metric in latest_by_pid_metric)

        processes: list[dict[str, object]] = []
        all_pids = sorted(set(pid_meta) | {pid for pid, _ in latest_by_pid_metric})
        for pid in all_pids:
            meta = pid_meta.get(pid, {})

            def mv(metric: str) -> tuple[float, int | None]:
                tup = latest_by_pid_metric.get((pid, metric))
                if tup is None:
                    return 0.0, None
                return tup[0], tup[1]

            cpu_pct, ts_cpu = mv("cpu.util_pct")
            mem_rss, ts_mem = mv("mem.rss_bytes")
            io_r, ts_io_r = mv("io.read_bps")
            io_w, ts_io_w = mv("io.write_bps")
            net_r, ts_net_r = mv("net.rx_bps")
            net_w, ts_net_w = mv("net.tx_bps")
            gpu_mem, ts_gpu_mem = mv("gpu.proc.mem_used_bytes")
            ts_candidates = [t for t in [ts_cpu, ts_mem, ts_io_r, ts_io_w, ts_net_r, ts_net_w, ts_gpu_mem] if t is not None]

            processes.append(
                {
                    "pid": pid,
                    "comm": meta.get("comm", ""),
                    "cpu_pct": cpu_pct,
                    "mem_rss_bytes": mem_rss,
                    "io_read_bps": io_r,
                    "io_write_bps": io_w,
                    "net_rx_bps": net_r,
                    "net_tx_bps": net_w,
                    "gpu_mem_used_bytes": gpu_mem,
                    "gpu_mem_known": ts_gpu_mem is not None,
                    "last_seen_ns": max(ts_candidates) if ts_candidates else int(meta.get("last_seen_ns", 0)),
                }
            )
        processes.sort(key=lambda x: (float(x["cpu_pct"]), float(x["mem_rss_bytes"])), reverse=True)

        cpu_total = sum(float(p["cpu_pct"]) for p in processes)
        mem_total = sum(float(p["mem_rss_bytes"]) for p in processes)
        io_read_total = sum(float(p["io_read_bps"]) for p in processes)
        io_write_total = sum(float(p["io_write_bps"]) for p in processes)
        net_rx_total = sum(float(p["net_rx_bps"]) for p in processes)
        net_tx_total = sum(float(p["net_tx_bps"]) for p in processes)
        proc_count_value = 0.0

        # Re-open once for scalar metrics to keep logic simple and explicit.
        pcie_channels_latest: dict[str, dict[str, float]] = {}
        with self.connect() as conn2:
            proc_count_t = self._latest_scalar_metric(conn2, run_id, "proc.count")
            gpu_util_t = self._latest_scalar_metric_agg(conn2, run_id, "gpu.device.util_pct", agg="AVG")
            gpu_mem_t = self._latest_scalar_metric_agg(conn2, run_id, "gpu.device.mem_used_bytes", agg="SUM")
            pcie_rx_t = self._latest_scalar_metric_agg(conn2, run_id, "pcie.device.rx_bytes_s", agg="SUM")
            pcie_tx_t = self._latest_scalar_metric_agg(conn2, run_id, "pcie.device.tx_bytes_s", agg="SUM")
            pcie_raw_rows = conn2.execute(
                """
                SELECT ts_ns, metric, value, tags_json
                FROM metrics_raw
                WHERE run_id = ?
                  AND pid IS NULL
                  AND metric IN (
                    'pcie.device.rx_bytes_s',
                    'pcie.device.tx_bytes_s',
                    'pcie.link.gen.current',
                    'pcie.link.gen.max',
                    'pcie.link.width.current',
                    'pcie.link.width.max'
                  )
                ORDER BY ts_ns DESC, id DESC
                """,
                (run_id,),
            ).fetchall()

        metric_map = {
            "pcie.device.rx_bytes_s": "rx_bytes_s",
            "pcie.device.tx_bytes_s": "tx_bytes_s",
            "pcie.link.gen.current": "link_gen_current",
            "pcie.link.gen.max": "link_gen_max",
            "pcie.link.width.current": "link_width_current",
            "pcie.link.width.max": "link_width_max",
        }
        for row in pcie_raw_rows:
            field = metric_map.get(str(row["metric"]))
            if field is None:
                continue
            channel = self._pcie_channel_from_tags(row["tags_json"])
            if channel is None:
                continue
            channel_row = pcie_channels_latest.setdefault(channel, {})
            if field in channel_row:
                continue
            channel_row[field] = float(row["value"])
            channel_row[f"{field}_ts_ns"] = int(row["ts_ns"])

        pcie_channels_latest = {
            channel: pcie_channels_latest[channel]
            for channel in sorted(pcie_channels_latest.keys(), key=self._channel_sort_key)
        }
        if proc_count_t is not None:
            proc_count_value = float(proc_count_t[0])
        gpu_util = float(gpu_util_t[0]) if gpu_util_t is not None else 0.0
        gpu_mem_total = float(gpu_mem_t[0]) if gpu_mem_t is not None else 0.0
        pcie_rx_total = float(pcie_rx_t[0]) if pcie_rx_t is not None else 0.0
        pcie_tx_total = float(pcie_tx_t[0]) if pcie_tx_t is not None else 0.0

        return {
            "run_id": run_id,
            "run": dict(run),
            "latest_ts_ns": latest_ts_ns,
            "summary": {
                "proc_count": proc_count_value,
                "cpu_total_pct": cpu_total,
                "mem_total_bytes": mem_total,
                "io_read_bps": io_read_total,
                "io_write_bps": io_write_total,
                "net_rx_bps": net_rx_total,
                "net_tx_bps": net_tx_total,
                "gpu_util_pct": gpu_util,
                "gpu_mem_used_bytes": gpu_mem_total,
                "pcie_rx_bytes_s": pcie_rx_total,
                "pcie_tx_bytes_s": pcie_tx_total,
                "pcie_channel_count": len(pcie_channels_latest),
            },
            "capabilities": {"gpu_proc_mem": has_gpu_proc_metric},
            "processes": processes,
            "pcie_channels": pcie_channels_latest,
        }

    def taskmanager_performance(self, run_id: str, seconds: int) -> dict[str, object]:
        seconds = max(5, min(3600, int(seconds)))
        with self.connect() as conn:
            latest_ts_row = conn.execute(
                "SELECT MAX(ts_ns) AS latest_ts_ns FROM metrics_raw WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            latest_ts_ns = int(latest_ts_row["latest_ts_ns"]) if latest_ts_row and latest_ts_row["latest_ts_ns"] is not None else int(time.time_ns())
            start_ts_ns = latest_ts_ns - seconds * 1_000_000_000

            def series_sum(metric: str, pid_clause: str = "pid IS NOT NULL") -> list[dict[str, object]]:
                rows = conn.execute(
                    f"""
                    SELECT ts_ns, SUM(value) AS value
                    FROM metrics_raw
                    WHERE run_id = ?
                      AND metric = ?
                      AND ts_ns >= ?
                      AND {pid_clause}
                    GROUP BY ts_ns
                    ORDER BY ts_ns
                    """,
                    (run_id, metric, start_ts_ns),
                ).fetchall()
                return [{"ts_ns": int(r["ts_ns"]), "value": float(r["value"])} for r in rows]

            def series_avg(metric: str, pid_clause: str = "pid IS NULL") -> list[dict[str, object]]:
                rows = conn.execute(
                    f"""
                    SELECT ts_ns, AVG(value) AS value
                    FROM metrics_raw
                    WHERE run_id = ?
                      AND metric = ?
                      AND ts_ns >= ?
                      AND {pid_clause}
                    GROUP BY ts_ns
                    ORDER BY ts_ns
                    """,
                    (run_id, metric, start_ts_ns),
                ).fetchall()
                return [{"ts_ns": int(r["ts_ns"]), "value": float(r["value"])} for r in rows]

            def series_max(metric: str, pid_clause: str = "1=1") -> list[dict[str, object]]:
                rows = conn.execute(
                    f"""
                    SELECT ts_ns, MAX(value) AS value
                    FROM metrics_raw
                    WHERE run_id = ?
                      AND metric = ?
                      AND ts_ns >= ?
                      AND {pid_clause}
                    GROUP BY ts_ns
                    ORDER BY ts_ns
                    """,
                    (run_id, metric, start_ts_ns),
                ).fetchall()
                return [{"ts_ns": int(r["ts_ns"]), "value": float(r["value"])} for r in rows]

            series = {
                "cpu_total_pct": series_sum("cpu.util_pct"),
                "mem_total_bytes": series_sum("mem.rss_bytes"),
                "io_read_bps": series_sum("io.read_bps"),
                "io_write_bps": series_sum("io.write_bps"),
                "net_rx_bps": series_sum("net.rx_bps"),
                "net_tx_bps": series_sum("net.tx_bps"),
                "gpu_util_pct": series_avg("gpu.device.util_pct"),
                "gpu_mem_used_bytes": series_sum("gpu.device.mem_used_bytes", pid_clause="pid IS NULL"),
                "pcie_rx_bytes_s": series_sum("pcie.device.rx_bytes_s", pid_clause="pid IS NULL"),
                "pcie_tx_bytes_s": series_sum("pcie.device.tx_bytes_s", pid_clause="pid IS NULL"),
                "proc_count": series_max("proc.count"),
            }

            pcie_rows = conn.execute(
                """
                SELECT ts_ns, metric, value, tags_json
                FROM metrics_raw
                WHERE run_id = ?
                  AND pid IS NULL
                  AND ts_ns >= ?
                  AND metric IN ('pcie.device.rx_bytes_s', 'pcie.device.tx_bytes_s')
                ORDER BY ts_ns
                """,
                (run_id, start_ts_ns),
            ).fetchall()

            pcie_channels: dict[str, dict[str, list[dict[str, object]]]] = {}
            for row in pcie_rows:
                metric_name = str(row["metric"])
                channel_metric = "rx_bytes_s" if metric_name == "pcie.device.rx_bytes_s" else "tx_bytes_s"
                channel = self._pcie_channel_from_tags(row["tags_json"])
                if channel is None:
                    continue
                channel_rows = pcie_channels.setdefault(channel, {"rx_bytes_s": [], "tx_bytes_s": []})
                channel_rows[channel_metric].append({"ts_ns": int(row["ts_ns"]), "value": float(row["value"])})

            pcie_channels = {
                channel: pcie_channels[channel]
                for channel in sorted(pcie_channels.keys(), key=self._channel_sort_key)
            }

        return {
            "run_id": run_id,
            "seconds": seconds,
            "latest_ts_ns": latest_ts_ns,
            "series": series,
            "pcie_channels": pcie_channels,
        }

    def query_sql(self, sql: str, params: list[object], limit: int) -> dict[str, object]:
        query = sql.strip()
        if not query:
            raise ValueError("sql cannot be empty")

        lowered = query.lower().lstrip()
        if not (lowered.startswith("select") or lowered.startswith("with") or lowered.startswith("pragma")):
            raise ValueError("only SELECT/WITH/PRAGMA queries are allowed")
        if ";" in query.strip().strip(";"):
            raise ValueError("multiple statements are not allowed")

        with self.connect() as conn:
            cur = conn.execute(query, tuple(params))
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(int(limit))

        encoded_rows = [[row[col] for col in columns] for row in rows]
        return {"columns": columns, "rows": encoded_rows, "row_count": len(encoded_rows)}
