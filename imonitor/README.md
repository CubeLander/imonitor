# imonitor

`imonitor` is a Linux-first program wrapper monitor.

It launches a target command, samples process/resource usage in near real time,
and writes outputs to:

- SQLite (`metrics.sqlite`)
- Parquet (`parquet/*.parquet`) if `pyarrow` is installed
- CSV (`csv/*.csv`)
- HTML summary report (`report.html`)

Core tables (SQLite):

- `runs`: one row per wrapped execution
- `processes`: discovered PID lifecycle within a run
- `metrics_raw`: per-sensor per-frame raw points (time axis)
- `frames`: frame index by timestamp (`ts_ns`)
- `metrics_agg`: full-run aggregate stats
- `metrics_rollup`: time-bucket rollups (default 1s buckets)

## Quick Start

```bash
cd /home/flecther/workspace/myprofile/imonitor
python -m imonitor --interval 0.5 --out-dir ./runs/demo -- python -c "import time; [time.sleep(0.2) for _ in range(10)]"
```

## Install Optional Dependencies

```bash
pip install -e .[parquet,gpu]
```

For web UI:

```bash
pip install -e .[web]
```

## Notes

- Linux only (procfs-based sensors).
- GPU metrics are optional and require NVML (`nvidia-ml-py`) and compatible drivers.
- Network stats in v1 are sampled from `/proc/<pid>/net/dev` using the root process namespace.

## Web UI

Launch web viewer from project root:

```bash
cd /home/flecther/workspace/myprofile/imonitor
imonitor-web --db ./runs/integrated_demo/metrics.sqlite --host 127.0.0.1 --port 18080
```

Then open `http://127.0.0.1:18080`.
