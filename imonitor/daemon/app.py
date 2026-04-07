from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from imonitor.core.launcher import Procfs
from imonitor.daemon.models import (
    LogBatch,
    SQLQueryRequest,
    SignalBatch,
    RunFinishRequest,
    RunStartRequest,
)
from imonitor.daemon.process_sampler import SystemProcessSampler
from imonitor.daemon.store import DaemonStore
from imonitor.daemon.system_sampler import SystemHostSampler
from imonitor.web.app import dashboard_html, mount_webui_assets


def _default_db_path() -> Path:
    raw = os.getenv("IMONITOR_DAEMON_DB") or os.getenv("IMONITOR_DB") or "./runs/imonitord.sqlite"
    return Path(raw)


def _create_app(db_path: Path | None = None) -> FastAPI:
    resolved_db = (db_path or _default_db_path()).expanduser().resolve()
    store = DaemonStore(resolved_db)
    system_sampler = SystemHostSampler.from_env(store)
    process_sampler = SystemProcessSampler.from_env()
    app = FastAPI(title="imonitord", version="0.1.0")
    mount_webui_assets(app)
    app.state.store = store
    app.state.system_sampler = system_sampler
    app.state.process_sampler = process_sampler

    @app.on_event("startup")
    def _on_startup() -> None:
        system_sampler.start()
        process_sampler.start()

    @app.on_event("shutdown")
    def _on_shutdown() -> None:
        system_sampler.stop()
        process_sampler.stop()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return dashboard_html()

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True, "db_path": str(store.db_path)}

    @app.get("/api/runs")
    def api_runs(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
        return {"db_path": str(store.db_path), "runs": store.recent_runs(limit)}

    @app.get("/api/run/{run_id}/metrics")
    def api_run_metrics(run_id: str) -> dict[str, Any]:
        return store.run_metrics(run_id)

    @app.get("/api/run/{run_id}/pids")
    def api_run_pids(run_id: str) -> dict[str, Any]:
        return store.run_pids(run_id)

    @app.get("/api/run/{run_id}/series")
    def api_run_series(
        run_id: str,
        metric: str = Query(...),
        sensor: str | None = Query(default=None),
        pid: int | None = Query(default=None),
        rollup: bool = Query(default=True),
        bucket_ns: int = Query(default=1_000_000_000, ge=1_000_000),
        limit: int = Query(default=8000, ge=100, le=200000),
    ) -> dict[str, Any]:
        payload = store.run_series(
            run_id=run_id,
            metric=metric,
            sensor=sensor,
            pid=pid,
            rollup=rollup,
            bucket_ns=bucket_ns,
            limit=limit,
        )
        payload["db_path"] = str(store.db_path)
        return payload

    @app.get("/api/run/{run_id}/logs")
    def api_run_logs(run_id: str, limit: int = Query(default=200, ge=1, le=5000)) -> dict[str, Any]:
        return {"db_path": str(store.db_path), "run_id": run_id, "rows": store.recent_logs(run_id, limit)}

    @app.get("/api/run/{run_id}/tables/latest")
    def api_run_tables_latest(run_id: str, limit: int = Query(default=20, ge=1, le=5000)) -> dict[str, Any]:
        return {
            "db_path": str(store.db_path),
            "run_id": run_id,
            "limit": limit,
            "tables": store.latest_tables(run_id, limit),
        }

    @app.get("/api/taskmanager/runs")
    def api_taskmanager_runs(limit: int = Query(default=30, ge=1, le=300)) -> dict[str, Any]:
        return {"db_path": str(store.db_path), "runs": store.taskmanager_runs(limit)}

    @app.get("/api/taskmanager/run/{run_id}/snapshot")
    def api_taskmanager_snapshot(run_id: str) -> dict[str, Any]:
        payload = store.taskmanager_snapshot(run_id)
        payload["db_path"] = str(store.db_path)
        return payload

    @app.get("/api/taskmanager/run/{run_id}/performance")
    def api_taskmanager_performance(run_id: str, seconds: int = Query(default=120, ge=5, le=3600)) -> dict[str, Any]:
        payload = store.taskmanager_performance(run_id, seconds)
        payload["db_path"] = str(store.db_path)
        return payload

    @app.get("/api/taskmanager/processes")
    def api_taskmanager_processes(limit: int = Query(default=300, ge=1, le=2000)) -> dict[str, Any]:
        snapshot = process_sampler.latest_snapshot(limit=limit)
        rows = [dict(row) for row in snapshot.get("rows", [])]
        running_runs = store.taskmanager_running_runs(limit=100)

        monitored_pid_to_runs: dict[int, set[str]] = defaultdict(set)
        live_running_runs: list[dict[str, object]] = []
        for run in running_runs:
            run_id = str(run.get("run_id", ""))
            root_pid = int(run.get("root_pid") or 0)
            if not run_id or root_pid <= 0:
                continue
            if not Procfs.pid_exists(root_pid):
                continue

            descendants = Procfs.list_descendants(root_pid)
            if not descendants:
                continue
            live_running_runs.append(run)
            for pid in descendants:
                monitored_pid_to_runs[pid].add(run_id)

        monitored_pids = sorted(monitored_pid_to_runs.keys())
        metric_rows = store.latest_run_pid_metrics(
            run_ids=[str(r["run_id"]) for r in live_running_runs],
            pids=monitored_pids,
            metric_prefixes=["gpu.", "pcie.", "nvlink."],
        )

        extras_by_pid: dict[int, dict[str, dict[str, object]]] = {}
        snapshot_caps = dict(snapshot.get("capabilities", {}) or {})
        has_gpu_proc_mem = bool(snapshot_caps.get("gpu_proc_mem"))
        has_gpu_proc_util = bool(snapshot_caps.get("gpu_proc_util"))
        gpu_channels = [str(x) for x in (snapshot_caps.get("gpu_channels") or []) if str(x)]
        for item in metric_rows:
            pid = int(item["pid"])
            metric = str(item["metric"])
            per_pid = extras_by_pid.setdefault(pid, {})
            if metric in per_pid:
                continue
            per_pid[metric] = {
                "value": float(item["value"]),
                "unit": str(item["unit"]),
                "ts_ns": int(item["ts_ns"]),
                "run_id": str(item["run_id"]),
            }
            if metric == "gpu.proc.mem_used_bytes":
                has_gpu_proc_mem = True

        monitored_count = 0
        for row in rows:
            pid = int(row.get("pid") or 0)
            run_ids = sorted(monitored_pid_to_runs.get(pid, set()))
            is_monitored = bool(run_ids)
            if is_monitored:
                monitored_count += 1

            extras = extras_by_pid.get(pid, {})
            row["monitored"] = is_monitored
            row["run_ids"] = run_ids
            row["source"] = "monitored" if is_monitored else "system"
            row["extra_metrics"] = extras

            if (not bool(row.get("gpu_mem_known"))) and "gpu.proc.mem_used_bytes" in extras:
                row["gpu_mem_known"] = True
                row["gpu_mem_used_bytes"] = float(extras["gpu.proc.mem_used_bytes"]["value"])

        return {
            "db_path": str(store.db_path),
            "latest_ts_ns": snapshot.get("latest_ts_ns"),
            "rows": rows,
            "counts": {
                "total": len(rows),
                "monitored": monitored_count,
                "system": max(0, len(rows) - monitored_count),
            },
            "running_runs": live_running_runs,
            "capabilities": {
                "gpu_proc_mem": has_gpu_proc_mem,
                "gpu_proc_util": has_gpu_proc_util,
                "gpu_channels": gpu_channels,
            },
            "sampler_enabled": process_sampler.enabled,
            "sampling_interval_sec": process_sampler.interval_sec,
        }

    @app.post("/api/sql/query")
    def api_sql_query(payload: SQLQueryRequest) -> dict[str, Any]:
        try:
            data = store.query_sql(payload.sql, payload.params, payload.limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        data["db_path"] = str(store.db_path)
        return data

    @app.get("/api/system/latest")
    def api_system_latest() -> dict[str, Any]:
        payload = store.system_host_latest()
        payload["db_path"] = str(store.db_path)
        payload["sampler_enabled"] = system_sampler.enabled
        payload["sampling_interval_sec"] = system_sampler.interval_sec
        gpu_channels = system_sampler.gpu_channels()
        payload["gpu_channels"] = gpu_channels

        static_profiles = system_sampler.gpu_static_profiles()
        summary = dict(payload.get("summary", {}) or {})
        latest_ts_ns = int(payload.get("latest_ts_ns") or 0)
        dynamic_profiles: dict[str, dict[str, Any]] = {}
        for channel in gpu_channels:
            rx = float(summary.get(f"system.pcie.{channel}.rx_bytes_s", 0.0) or 0.0)
            tx = float(summary.get(f"system.pcie.{channel}.tx_bytes_s", 0.0) or 0.0)
            throughput = float(
                summary.get(
                    f"system.pcie.{channel}.throughput_bytes_s",
                    rx + tx,
                )
                or 0.0
            )
            dynamic_profiles[channel] = {
                "util_pct": float(summary.get(f"system.gpu.{channel}.util_pct", 0.0) or 0.0),
                "mem_used_bytes": float(summary.get(f"system.gpu.{channel}.mem_used_bytes", 0.0) or 0.0),
                "power_w": float(summary.get(f"system.gpu.{channel}.power_w", 0.0) or 0.0),
                "pcie_rx_bytes_s": rx,
                "pcie_tx_bytes_s": tx,
                "pcie_throughput_bytes_s": throughput,
                "pcie_gen_current": float(summary.get(f"system.pcie.{channel}.link.gen.current", 0.0) or 0.0),
                "pcie_width_current": float(summary.get(f"system.pcie.{channel}.link.width.current", 0.0) or 0.0),
                "sample_ts_ns": latest_ts_ns,
            }
        payload["gpu_static_profiles"] = static_profiles
        payload["gpu_dynamic_profiles"] = dynamic_profiles
        return payload

    @app.get("/api/system/performance")
    def api_system_performance(seconds: int = Query(default=600, ge=10, le=86_400)) -> dict[str, Any]:
        payload = store.system_host_performance(seconds=seconds)
        payload["db_path"] = str(store.db_path)
        payload["sampler_enabled"] = system_sampler.enabled
        payload["sampling_interval_sec"] = system_sampler.interval_sec
        payload["gpu_channels"] = system_sampler.gpu_channels()
        return payload

    @app.post("/api/agent/run/start")
    def agent_run_start(payload: RunStartRequest) -> dict[str, Any]:
        row = store.start_run(payload.model_dump() if hasattr(payload, "model_dump") else payload.dict())
        return {"ok": True, "run": row, "db_path": str(store.db_path)}

    @app.post("/api/agent/run/{run_id}/signals")
    def agent_run_signals(run_id: str, payload: SignalBatch) -> dict[str, Any]:
        rows_in = payload.rows
        rows = []
        for item in rows_in:
            row = item.model_dump() if hasattr(item, "model_dump") else item.dict()
            if row["run_id"] != run_id:
                raise HTTPException(status_code=400, detail="row run_id mismatch")
            rows.append(row)
        inserted = store.append_signals(rows)
        return {"ok": True, "inserted": inserted}

    @app.post("/api/agent/run/{run_id}/logs")
    def agent_run_logs(run_id: str, payload: LogBatch) -> dict[str, Any]:
        chunks_in = payload.chunks
        chunks = []
        for item in chunks_in:
            chunk = item.model_dump() if hasattr(item, "model_dump") else item.dict()
            chunks.append(chunk)
        inserted = store.append_logs(run_id, chunks)
        return {"ok": True, "inserted": inserted}

    @app.post("/api/agent/run/{run_id}/finish")
    def agent_run_finish(run_id: str, payload: RunFinishRequest) -> dict[str, Any]:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        if data["run_row"]["run_id"] != run_id:
            raise HTTPException(status_code=400, detail="run_id mismatch")
        result = store.finish_run(data)
        return {"ok": True, "counts": result}

    @app.get("/api/agent/runs/recent")
    def agent_runs_recent(limit: int = Query(default=20, ge=1, le=500)) -> dict[str, Any]:
        return {"db_path": str(store.db_path), "runs": store.recent_runs(limit)}

    @app.get("/api/agent/run/{run_id}/tables/latest")
    def agent_run_tables_latest(
        run_id: str,
        limit: int = Query(default=200, ge=1, le=5000),
    ) -> dict[str, Any]:
        return {
            "db_path": str(store.db_path),
            "run_id": run_id,
            "limit": limit,
            "tables": store.latest_tables(run_id, limit),
        }

    @app.get("/api/agent/run/{run_id}/logs")
    def agent_run_logs_query(
        run_id: str,
        limit: int = Query(default=200, ge=1, le=5000),
    ) -> dict[str, Any]:
        return {"db_path": str(store.db_path), "run_id": run_id, "rows": store.recent_logs(run_id, limit)}

    return app


app = _create_app()
