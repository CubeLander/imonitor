from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from imonitor.console import emit_log_line
from imonitor.config import MonitorConfig, SinkConfig
from imonitor.daemon.service import default_daemon_url, ensure_daemon_running
from imonitor.core.hub import Hub
from imonitor.core.launcher import ProcessLauncher
from imonitor.core.registry import build_sensors
from imonitor.core.scheduler import SensorScheduler
from imonitor.core.types import MonitorContext
from imonitor.pipelines.summarizer import build_summary
from imonitor.remote import (
    RemoteClient,
    RemoteDaemonClient,
    RemoteError,
    format_table,
)
from imonitor.reports.html_report import write_html_report
from imonitor.sinks.csv_sink import CSVSink
from imonitor.sinks.live_sink import LiveSink
from imonitor.sinks.parquet_sink import ParquetSink
from imonitor.sinks.sqlite_sink import SQLiteSink
from imonitor.signals.bus import SignalBus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imonitor",
        description="Wrap and monitor a Linux command with process-level sensors.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="optional run config file (.toml or .yaml/.yml)",
    )

    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="target command, usually after '--'",
    )
    return parser


def build_recent_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="imonitor recent", description="Show recent runs from imonitord.")
    parser.add_argument("--daemon-url", default=None, help="imonitord base URL (optional)")
    parser.add_argument("--limit", type=int, default=20, help="number of recent runs to show")
    return parser


def build_tables_latest_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="imonitor tables latest", description="Show latest rows for a run.")
    parser.add_argument("--daemon-url", default=None, help="imonitord base URL (optional)")
    parser.add_argument("--run-id", required=True, help="run identifier")
    parser.add_argument("--limit", type=int, default=20, help="rows per table")
    return parser


def build_logs_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="imonitor logs", description="Show logs from imonitord.")
    parser.add_argument("--daemon-url", default=None, help="imonitord base URL (optional)")
    parser.add_argument("--run-id", required=True, help="run identifier")
    parser.add_argument("--limit", type=int, default=200, help="number of log lines to show")
    return parser


def build_inspect_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imonitor inspect",
        description="Inspect one monitored job in real time and export report files.",
    )
    parser.add_argument("job_id", help="job id (run_id)")
    parser.add_argument("--daemon-url", default=None, help="imonitord base URL (optional)")
    parser.add_argument("--interval", type=float, default=1.0, help="refresh interval in seconds")
    parser.add_argument("--top", type=int, default=8, help="number of top processes to print")
    parser.add_argument("--once", action="store_true", help="fetch one snapshot and exit")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("./runs/inspect_reports"),
        help="directory where summary.json/report.html will be written",
    )
    parser.add_argument("--no-report", action="store_true", help="skip report export")
    return parser


def _read_run_config(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read config file: {resolved}") from exc

    def _load_toml(text: str) -> dict[str, Any]:
        try:
            import tomllib  # py311+

            obj = tomllib.loads(text)
        except ModuleNotFoundError:
            try:
                import tomli  # py310 fallback

                obj = tomli.loads(text)
            except ModuleNotFoundError as exc:
                raise ValueError("toml config requires 'tomli' (Python 3.10) or Python 3.11+") from exc
        if not isinstance(obj, dict):
            raise ValueError("config root must be an object")
        return obj

    def _load_yaml(text: str) -> dict[str, Any]:
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise ValueError("yaml config requires 'PyYAML'") from exc
        obj = yaml.safe_load(text)
        if obj is None:
            return {}
        if not isinstance(obj, dict):
            raise ValueError("config root must be an object")
        return obj

    suffix = resolved.suffix.lower()
    if suffix == ".json":
        payload = json.loads(raw)
    elif suffix == ".toml":
        payload = _load_toml(raw)
    elif suffix in {".yaml", ".yml"}:
        payload = _load_yaml(raw)
    else:
        # Try TOML/YAML/JSON by order.
        errors: list[str] = []
        try:
            payload = _load_toml(raw)
        except Exception as exc:
            errors.append(str(exc))
            try:
                payload = _load_yaml(raw)
            except Exception as exc2:
                errors.append(str(exc2))
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc3:
                    errors.append(str(exc3))
                    raise ValueError(
                        f"config parse failed for {resolved}; expected TOML/YAML/JSON"
                    ) from exc3

    if not isinstance(payload, dict):
        raise ValueError("config root must be an object")
    return payload


def _cfg_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def parse_args(argv: list[str] | None = None) -> MonitorConfig:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command
    if command and command[0] == "--":
        command = command[1:]

    overrides: dict[str, Any] = {}
    if args.config is not None:
        overrides = _read_run_config(args.config)

    interval_sec = float(overrides.get("interval_sec", overrides.get("interval", 0.5)))
    daemon_url_obj = overrides.get("daemon_url")
    daemon_url = str(daemon_url_obj).strip() if daemon_url_obj not in {None, ""} else None

    daemon_enabled = _cfg_bool(overrides, "daemon_enabled", True)
    if "no_daemon" in overrides:
        daemon_enabled = not _cfg_bool(overrides, "no_daemon", False)

    enable_gpu = _cfg_bool(overrides, "enable_gpu", True)
    if "no_gpu" in overrides:
        enable_gpu = not _cfg_bool(overrides, "no_gpu", False)

    enable_net = _cfg_bool(overrides, "enable_net", True)
    if "no_net" in overrides:
        enable_net = not _cfg_bool(overrides, "no_net", False)

    sink_obj = overrides.get("sink", {})
    if sink_obj is None:
        sink_obj = {}
    if not isinstance(sink_obj, dict):
        raise ValueError("config key 'sink' must be an object")

    sink = SinkConfig(
        sqlite=_cfg_bool(sink_obj, "sqlite", False),
        parquet=_cfg_bool(sink_obj, "parquet", False),
        csv=_cfg_bool(sink_obj, "csv", False),
        live=_cfg_bool(sink_obj, "live", False),
    )
    # Backward-compatible top-level sink keys.
    if "sqlite" in overrides:
        sink.sqlite = _cfg_bool(overrides, "sqlite", sink.sqlite)
    if "parquet" in overrides:
        sink.parquet = _cfg_bool(overrides, "parquet", sink.parquet)
    if "csv" in overrides:
        sink.csv = _cfg_bool(overrides, "csv", sink.csv)
    if "live" in overrides:
        sink.live = _cfg_bool(overrides, "live", sink.live)
    if "no_sqlite" in overrides:
        sink.sqlite = not _cfg_bool(overrides, "no_sqlite", False)
    if "no_parquet" in overrides:
        sink.parquet = not _cfg_bool(overrides, "no_parquet", False)
    if "no_csv" in overrides:
        sink.csv = not _cfg_bool(overrides, "no_csv", False)
    if "no_live" in overrides:
        sink.live = not _cfg_bool(overrides, "no_live", False)

    out_dir: Path | None = None
    out_dir_obj = overrides.get("out_dir", overrides.get("local_out_dir"))
    if out_dir_obj not in {None, ""}:
        out_dir = Path(str(out_dir_obj)).expanduser()

    write_local_report = _cfg_bool(overrides, "write_local_report", False)
    wants_local_output = sink.sqlite or sink.parquet or sink.csv or write_local_report
    if wants_local_output and out_dir is None:
        out_dir = Path("./imonitor-output")
    if (not daemon_enabled) and (not wants_local_output):
        raise ValueError(
            "daemon_enabled=false requires local output; set sink sqlite/csv/parquet "
            "or write_local_report in --config"
        )

    cfg = MonitorConfig(
        command=command,
        out_dir=out_dir,
        write_local_report=write_local_report,
        interval_sec=interval_sec,
        daemon_url=daemon_url,
        daemon_enabled=daemon_enabled,
        enable_gpu=enable_gpu,
        enable_net=enable_net,
        sink=sink,
    )
    cfg.validate()
    return cfg


def _ns_to_iso(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _resolve_daemon_url(explicit_url: str | None) -> str:
    target_url = (explicit_url or default_daemon_url()).rstrip("/")
    try:
        return ensure_daemon_running(target_url)
    except Exception as exc:
        raise RemoteError(f"daemon unavailable at {target_url}: {exc}") from exc


def _run_recent(argv: list[str]) -> int:
    args = build_recent_parser().parse_args(argv)
    daemon_url = _resolve_daemon_url(args.daemon_url)
    client = RemoteClient(daemon_url)
    payload = client.get_json("/api/agent/runs/recent", {"limit": args.limit})
    runs = payload.get("runs", [])
    print(f"daemon={payload.get('db_path', daemon_url)} limit={args.limit} runs={len(runs)}")
    if not runs:
        return 0

    rows: list[dict[str, Any]] = []
    for run in runs:
        rows.append(
            {
                "run_id": run.get("run_id", ""),
                "start_time": _ns_to_iso(int(run.get("start_ns", 0))),
                "duration_sec": float(run.get("duration_sec", 0.0)),
                "exit_code": run.get("exit_code", ""),
                "sample_count": run.get("sample_count", ""),
                "command": run.get("command", ""),
            }
        )
    print(
        format_table(
            rows,
            [
                ("run_id", "run_id"),
                ("start_time", "start_time"),
                ("duration_sec", "duration_sec"),
                ("exit_code", "rc"),
                ("sample_count", "samples"),
                ("command", "command"),
            ],
        )
    )
    return 0


def _run_tables_latest(argv: list[str]) -> int:
    args = build_tables_latest_parser().parse_args(argv)
    daemon_url = _resolve_daemon_url(args.daemon_url)
    client = RemoteClient(daemon_url)
    payload = client.get_json(
        f"/api/agent/run/{args.run_id}/tables/latest",
        {"limit": args.limit},
    )
    tables = payload.get("tables", {})
    print(f"daemon={payload.get('db_path', daemon_url)} run_id={args.run_id} limit={args.limit}")

    column_map: dict[str, list[tuple[str, str]]] = {
        "runs": [
            ("run_id", "run_id"),
            ("start_ns", "start_ns"),
            ("end_ns", "end_ns"),
            ("duration_sec", "duration_sec"),
            ("exit_code", "rc"),
            ("sample_count", "samples"),
            ("command", "command"),
        ],
        "processes": [
            ("pid", "pid"),
            ("comm", "comm"),
            ("first_seen_ns", "first_seen_ns"),
            ("last_seen_ns", "last_seen_ns"),
        ],
        "metrics_raw": [
            ("ts_ns", "ts_ns"),
            ("sensor", "sensor"),
            ("metric", "metric"),
            ("pid", "pid"),
            ("value", "value"),
            ("unit", "unit"),
        ],
        "frames": [
            ("frame_id", "frame_id"),
            ("ts_ns", "ts_ns"),
            ("signal_count", "signals"),
            ("active_pids", "active_pids"),
        ],
        "metrics_agg": [
            ("sensor", "sensor"),
            ("metric", "metric"),
            ("pid", "pid"),
            ("sample_count", "samples"),
            ("min", "min"),
            ("max", "max"),
            ("avg", "avg"),
            ("last", "last"),
            ("unit", "unit"),
        ],
        "metrics_rollup": [
            ("bucket_start_ns", "bucket_start_ns"),
            ("sensor", "sensor"),
            ("metric", "metric"),
            ("pid", "pid"),
            ("sample_count", "samples"),
            ("min", "min"),
            ("max", "max"),
            ("avg", "avg"),
            ("p95", "p95"),
            ("last", "last"),
            ("unit", "unit"),
        ],
        "run_logs": [
            ("ts_ns", "ts_ns"),
            ("stream", "stream"),
            ("text", "text"),
        ],
    }

    for table_name in ["runs", "processes", "metrics_raw", "frames", "metrics_agg", "metrics_rollup", "run_logs"]:
        rows = tables.get(table_name, [])
        print()
        print(f"[{table_name}] rows={len(rows)}")
        if rows:
            print(format_table(rows, column_map[table_name], max_rows=args.limit))
        else:
            print("(empty)")
    return 0


def _run_logs(argv: list[str]) -> int:
    args = build_logs_parser().parse_args(argv)
    daemon_url = _resolve_daemon_url(args.daemon_url)
    client = RemoteClient(daemon_url)
    payload = client.get_json(f"/api/agent/run/{args.run_id}/logs", {"limit": args.limit})
    rows = payload.get("rows", payload.get("logs", []))
    print(f"daemon={payload.get('db_path', daemon_url)} run_id={args.run_id} logs={len(rows)}")
    if not rows:
        return 0
    print(format_table(rows, [("ts_ns", "ts_ns"), ("stream", "stream"), ("text", "text")], max_rows=args.limit))
    return 0


def _fmt_bytes(value: float) -> str:
    x = float(value)
    if x < 1024:
        return f"{x:.0f} B"
    if x < 1024**2:
        return f"{x / 1024:.1f} KB"
    if x < 1024**3:
        return f"{x / 1024**2:.1f} MB"
    return f"{x / 1024**3:.2f} GB"


def _fmt_bps(value: float) -> str:
    return f"{_fmt_bytes(value)}/s"


def _fmt_pct(value: float) -> str:
    return f"{float(value):.1f}%"


def _normalize_run_row(run_id: str, run_row: dict[str, object] | None) -> dict[str, object]:
    row = dict(run_row or {})
    row.setdefault("run_id", run_id)
    row.setdefault("command", "")
    row.setdefault("duration_sec", 0.0)
    row.setdefault("exit_code", -1)
    row.setdefault("sample_count", 0)
    row.setdefault("peak_total_cpu_pct", 0.0)
    row.setdefault("peak_total_rss_bytes", 0.0)
    return row


def _render_inspect_panel(run_id: str, snapshot: dict[str, Any], top_n: int) -> str:
    run = dict(snapshot.get("run") or {})
    summary = dict(snapshot.get("summary") or {})
    status = run.get("status", "unknown")
    exit_code = run.get("exit_code", "-")
    sample_count = run.get("sample_count", 0)
    latest_ts_ns = snapshot.get("latest_ts_ns")

    lines = [
        f"job_id={run_id}",
        f"status={status} exit_code={exit_code} samples={sample_count} updated={_ns_to_iso(int(latest_ts_ns or time.time_ns()))}",
        (
            f"cpu={_fmt_pct(float(summary.get('cpu_total_pct', 0.0)))} "
            f"mem={_fmt_bytes(float(summary.get('mem_total_bytes', 0.0)))} "
            f"io={_fmt_bps(float(summary.get('io_read_bps', 0.0)))}/{_fmt_bps(float(summary.get('io_write_bps', 0.0)))} "
            f"net={_fmt_bps(float(summary.get('net_rx_bps', 0.0)))}/{_fmt_bps(float(summary.get('net_tx_bps', 0.0)))} "
            f"gpu={_fmt_pct(float(summary.get('gpu_util_pct', 0.0)))}/{_fmt_bytes(float(summary.get('gpu_mem_used_bytes', 0.0)))} "
            f"pcie={_fmt_bps(float(summary.get('pcie_rx_bytes_s', 0.0)))}/{_fmt_bps(float(summary.get('pcie_tx_bytes_s', 0.0)))}"
        ),
    ]

    processes = list(snapshot.get("processes") or [])
    if processes:
        lines.append("")
        lines.append(
            format_table(
                processes,
                [
                    ("pid", "pid"),
                    ("comm", "name"),
                    ("cpu_pct", "cpu_pct"),
                    ("mem_rss_bytes", "mem_rss"),
                    ("gpu_mem_used_bytes", "gpu_mem"),
                    ("io_read_bps", "io_read_bps"),
                    ("io_write_bps", "io_write_bps"),
                ],
                max_rows=max(1, int(top_n)),
            )
        )
    return "\n".join(lines)


def _write_inspect_report(
    client: RemoteClient,
    run_id: str,
    report_root: Path,
    fallback_run_row: dict[str, object] | None = None,
) -> Path:
    payload = client.get_json(f"/api/agent/run/{run_id}/tables/latest", {"limit": 5000})
    tables = payload.get("tables", {})
    run_rows = tables.get("runs", [])
    agg_rows = tables.get("metrics_agg", [])
    run_row = _normalize_run_row(run_id, run_rows[0] if run_rows else fallback_run_row)
    summary = build_summary(run_row, agg_rows)

    out_dir = report_root.expanduser().resolve() / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html_report(out_dir / "report.html", summary)
    return out_dir


def _run_inspect(argv: list[str]) -> int:
    args = build_inspect_parser().parse_args(argv)
    daemon_url = _resolve_daemon_url(args.daemon_url)
    client = RemoteClient(daemon_url)
    job_id = args.job_id

    interval_sec = max(0.2, float(args.interval))
    top_n = max(1, int(args.top))
    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    latest_snapshot: dict[str, Any] | None = None
    try:
        while True:
            snapshot = client.get_json(f"/api/taskmanager/run/{job_id}/snapshot")
            latest_snapshot = snapshot
            if snapshot.get("run") is None:
                raise RemoteError(f"job_id not found: {job_id}")
            panel = _render_inspect_panel(job_id, snapshot, top_n=top_n)
            if is_tty:
                sys.stdout.write("\x1b[2J\x1b[H")
            print(panel, flush=True)

            run = snapshot.get("run") or {}
            status = str(run.get("status", "unknown"))
            if args.once or status != "running":
                break
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n[imonitor] inspect interrupted by user", file=sys.stderr)

    if not args.no_report:
        fallback_run_row = dict((latest_snapshot or {}).get("run") or {})
        out_dir = _write_inspect_report(
            client=client,
            run_id=job_id,
            report_root=args.report_dir,
            fallback_run_row=fallback_run_row,
        )
        print(f"report_dir={out_dir}")
        print(f"summary_json={out_dir / 'summary.json'}")
        print(f"report_html={out_dir / 'report.html'}")

    return 0


def _dispatch_query(argv: list[str]) -> int:
    if not argv:
        raise SystemExit("usage: imonitor <recent|tables latest|logs|inspect> ...")
    cmd = argv[0]
    if cmd == "recent":
        return _run_recent(argv[1:])
    if cmd == "tables" and len(argv) > 1 and argv[1] == "latest":
        return _run_tables_latest(argv[2:])
    if cmd == "logs":
        return _run_logs(argv[1:])
    if cmd == "inspect":
        return _run_inspect(argv[1:])
    raise SystemExit("usage: imonitor <recent|tables latest|logs|inspect> ...")


async def _remote_flush_loop(client: RemoteDaemonClient, stop_event: asyncio.Event, interval_sec: float) -> None:
    while True:
        await client.flush()
        if stop_event.is_set():
            break
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    await client.flush()


async def run_monitor(cfg: MonitorConfig) -> int:
    if platform.system() != "Linux":
        raise RuntimeError("imonitor v1 only supports Linux")

    if cfg.out_dir is not None:
        cfg.out_dir.mkdir(parents=True, exist_ok=True)

    daemon_url: str | None = None
    if cfg.daemon_enabled:
        target_url = (cfg.daemon_url or default_daemon_url()).rstrip("/")
        try:
            daemon_url = ensure_daemon_running(target_url)
        except Exception as exc:
            raise RuntimeError(
                f"daemon startup failed at {target_url}: {exc}. "
                "Use --no-daemon to run local-only."
            ) from exc

    launcher = ProcessLauncher()
    start_ns = time.time_ns()
    launch_result = launcher.start(
        cfg.command,
        transcript_path=None,
        use_script=False,
    )
    process = launch_result.process
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{process.pid}-{uuid.uuid4().hex[:8]}"
    sys.stderr.write(f"{run_id}\n")
    sys.stderr.flush()

    ctx = MonitorContext(
        run_id=run_id,
        command=cfg.command,
        root_pid=process.pid,
        start_ns=start_ns,
        interval_sec=cfg.interval_sec,
    )

    remote_client: RemoteDaemonClient | None = None
    if daemon_url is not None:
        candidate = RemoteDaemonClient(daemon_url)
        candidate.bind_run(run_id)
        try:
            await candidate.start_run(
                {
                    "run_id": run_id,
                    "command": cfg.command,
                    "start_ns": start_ns,
                    "interval_sec": cfg.interval_sec,
                    "root_pid": process.pid,
                    "metadata": {
                        "launcher": launch_result.wrapper,
                        "transcript_path": str(launch_result.transcript_path) if launch_result.transcript_path else None,
                    },
                }
            )
        except Exception as exc:
            try:
                process.terminate()
            except Exception:
                pass
            raise RuntimeError(f"failed to register run_id={run_id} in daemon: {exc}") from exc
        remote_client = candidate

    sinks = []
    if cfg.out_dir is not None:
        if cfg.sink.sqlite:
            sinks.append(SQLiteSink(cfg.out_dir / "metrics.sqlite"))
        if cfg.sink.csv:
            sinks.append(CSVSink(cfg.out_dir / "csv"))
        if cfg.sink.parquet:
            if ParquetSink.is_available():
                sinks.append(ParquetSink(cfg.out_dir / "parquet"))

    live_sink = LiveSink() if cfg.sink.live else None

    bus = SignalBus()
    sensors = build_sensors(cfg)
    stop_event = asyncio.Event()

    scheduler = SensorScheduler(
        sensors=sensors,
        bus=bus,
        ctx=ctx,
        interval_sec=cfg.interval_sec,
        stop_event=stop_event,
    )
    hub = Hub(sinks=sinks, live_sink=live_sink, remote_client=remote_client)

    scheduler_task = asyncio.create_task(scheduler.run(), name="imonitor-scheduler")
    hub_task = asyncio.create_task(hub.run(bus), name="imonitor-hub")
    remote_flush_task = None
    if remote_client is not None:
        remote_flush_task = asyncio.create_task(
            _remote_flush_loop(remote_client, stop_event, interval_sec=max(0.1, cfg.interval_sec)),
            name="imonitor-remote-flush",
        )

    exit_code = await asyncio.to_thread(process.wait)
    stop_event.set()

    await scheduler_task
    scheduler.close()

    await bus.close()
    await hub_task
    if remote_flush_task is not None:
        await remote_flush_task

    end_ns = time.time_ns()
    run_row, process_rows, agg_rows, frame_rows, rollup_rows = hub.persist(
        ctx=ctx, end_ns=end_ns, exit_code=exit_code
    )
    if remote_client is not None:
        try:
            await remote_client.flush()
            await remote_client.finish_run(
                {
                    "run_row": run_row,
                    "process_rows": process_rows,
                    "agg_rows": agg_rows,
                    "frame_rows": frame_rows,
                    "rollup_rows": rollup_rows,
                }
            )
        except Exception:
            pass

    if cfg.out_dir is not None and cfg.write_local_report:
        summary = build_summary(run_row, agg_rows)
        (cfg.out_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_html_report(cfg.out_dir / "report.html", summary)

    for sink in sinks:
        close_fn = getattr(sink, "close", None)
        if callable(close_fn):
            close_fn()

    return int(exit_code)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "run":
        args = args[1:]
    if args and args[0] in {"recent", "tables", "logs", "inspect"}:
        try:
            return _dispatch_query(args)
        except RemoteError as exc:
            emit_log_line(f"[imonitor] remote error: {exc}", stream=sys.stderr)
            return 1

    try:
        cfg = parse_args(args)
    except ValueError as exc:
        emit_log_line(f"[imonitor] error: {exc}", stream=sys.stderr)
        return 2
    try:
        return asyncio.run(run_monitor(cfg))
    except RuntimeError as exc:
        emit_log_line(f"[imonitor] error: {exc}", stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
