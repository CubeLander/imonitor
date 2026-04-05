from __future__ import annotations

import argparse
import asyncio
import json
import platform
import time
import uuid
from pathlib import Path

from imonitor.config import MonitorConfig, SinkConfig
from imonitor.core.hub import Hub
from imonitor.core.launcher import ProcessLauncher
from imonitor.core.registry import build_sensors
from imonitor.core.scheduler import SensorScheduler
from imonitor.core.types import MonitorContext
from imonitor.pipelines.summarizer import build_summary
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
    parser.add_argument("--interval", type=float, default=0.5, help="sampling interval in seconds")
    parser.add_argument("--out-dir", type=Path, default=Path("./imonitor-output"), help="output directory")
    parser.add_argument("--no-gpu", action="store_true", help="disable NVML gpu sensor")
    parser.add_argument("--no-net", action="store_true", help="disable procfs net sensor")

    parser.add_argument("--no-live", action="store_true", help="disable live console prints")
    parser.add_argument("--no-sqlite", action="store_true", help="disable sqlite output")
    parser.add_argument("--no-parquet", action="store_true", help="disable parquet output")
    parser.add_argument("--no-csv", action="store_true", help="disable csv output")

    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="target command, usually after '--'",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> MonitorConfig:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command
    if command and command[0] == "--":
        command = command[1:]

    sink = SinkConfig(
        sqlite=not args.no_sqlite,
        parquet=not args.no_parquet,
        csv=not args.no_csv,
        live=not args.no_live,
    )

    cfg = MonitorConfig(
        command=command,
        out_dir=args.out_dir,
        interval_sec=args.interval,
        enable_gpu=not args.no_gpu,
        enable_net=not args.no_net,
        sink=sink,
    )
    cfg.validate()
    return cfg


async def run_monitor(cfg: MonitorConfig) -> int:
    if platform.system() != "Linux":
        raise RuntimeError("imonitor v1 only supports Linux")

    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    launcher = ProcessLauncher()
    process = launcher.start(cfg.command)
    start_ns = time.time_ns()
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{process.pid}-{uuid.uuid4().hex[:8]}"

    ctx = MonitorContext(
        run_id=run_id,
        command=cfg.command,
        root_pid=process.pid,
        start_ns=start_ns,
        interval_sec=cfg.interval_sec,
    )

    sinks = []
    if cfg.sink.sqlite:
        sinks.append(SQLiteSink(cfg.out_dir / "metrics.sqlite"))
    if cfg.sink.csv:
        sinks.append(CSVSink(cfg.out_dir / "csv"))
    if cfg.sink.parquet:
        if ParquetSink.is_available():
            sinks.append(ParquetSink(cfg.out_dir / "parquet"))
        else:
            print("[imonitor] parquet sink requested but pyarrow is not installed; skipping parquet output")

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
    hub = Hub(sinks=sinks, live_sink=live_sink)

    scheduler_task = asyncio.create_task(scheduler.run(), name="imonitor-scheduler")
    hub_task = asyncio.create_task(hub.run(bus), name="imonitor-hub")

    print(f"[imonitor] started run_id={run_id} pid={process.pid} cmd={' '.join(cfg.command)}")

    exit_code = await asyncio.to_thread(process.wait)
    stop_event.set()

    await scheduler_task
    scheduler.close()

    await bus.close()
    await hub_task

    end_ns = time.time_ns()
    run_row, process_rows, agg_rows, frame_rows, rollup_rows = hub.persist(
        ctx=ctx, end_ns=end_ns, exit_code=exit_code
    )

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

    print(f"[imonitor] finished exit_code={exit_code} duration_sec={run_row['duration_sec']:.3f}")
    print(f"[imonitor] outputs: {cfg.out_dir}")
    print(
        "[imonitor] "
        f"processes={len(process_rows)} "
        f"raw_points={len(hub.raw_rows)} "
        f"frames={len(frame_rows)} "
        f"agg_rows={len(agg_rows)} "
        f"rollup_rows={len(rollup_rows)}"
    )
    return int(exit_code)


def main(argv: list[str] | None = None) -> int:
    cfg = parse_args(argv)
    return asyncio.run(run_monitor(cfg))


if __name__ == "__main__":
    raise SystemExit(main())
