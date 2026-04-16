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

When you run `imonitor` in local wrapper mode, it stays interactive with the
target program while `imonitord` serves queryable tables and web dashboards.
`imonitor` now lazily starts daemon service by default.

## Quick Start

```bash
cd /home/flecther/workspace/myprofile/imonitor
python -m imonitor -- python -c "import time; [time.sleep(0.2) for _ in range(10)]"
```

## Related Docs

- Ascend vLLM startup guide: [ASCEND_VLLM_STARTUP.md](./ASCEND_VLLM_STARTUP.md)
- CANN 8.5 docs crawl guide: [develop/CANN850_DOC_CRAWL.md](./develop/CANN850_DOC_CRAWL.md)

## Unified Daemon Mode

`imonitord` is the single server process:
- receives push streams from `imonitor`
- serves query APIs
- serves web dashboard at `/`

You usually do not need to start it manually. `imonitor` will lazy-start daemon automatically.

Run a workload locally (interactive) and push live metrics/logs:

```bash
imonitor run -- python -c "import time; print('hello'); time.sleep(2); print('bye')"
```

`imonitor run` is transparent to the target process I/O. It prints only one line
to `stderr` at startup: the `job_id` (`run_id`).

`run` now keeps CLI minimal. Runtime knobs are configured via optional config file:

```bash
imonitor run --config ./imonitor.run.toml -- python your_program.py
```

Inspect one job in real time and export report files:

```bash
imonitor inspect <job_id>
```

After that, open dashboard:

```text
http://127.0.0.1:18180
```

Query recent runs:

```bash
imonitor recent --limit 10
```

Inspect the latest tables for one run:

```bash
imonitor tables latest --run-id <run_id> --limit 20
```

View logs:

```bash
imonitor logs --run-id <run_id> --limit 200
```

## Install Optional Dependencies

```bash
pip install -e .[parquet,gpu]
```

If you use YAML config files:

```bash
pip install -e .[yaml]
```

For web UI:

```bash
pip install -e .[web]
```

If you want to run daemon manually:

```bash
python -m imonitor.daemon_cli --db ./runs/imonitord.sqlite --host 127.0.0.1 --port 18180
```

## Notes

- Linux only (procfs-based sensors).
- GPU metrics are optional and require NVML (`nvidia-ml-py`) and compatible drivers.
- PCIe throughput metrics are sampled from NVML device counters (`pcie.device.rx_bytes_s` / `pcie.device.tx_bytes_s`).
- NVLink currently exposes a lightweight placeholder metric (`nvlink.device.link_count`) for capability probing.
- Network stats in v1 are sampled from `/proc/<pid>/net/dev` using the root process namespace.

## Web UI

After daemon starts (manual or lazy), open `http://127.0.0.1:18180`.

The default dashboard is now Task-Manager style:
- `Performance` tab: real-time CPU / Memory / Disk IO / GPU charts
- `Processes` tab: full-system live process table (`top`-style), with `imonitor`-launched processes tagged as `monitored`
- `SQL` tab: run read-only SQL against daemon SQLite for custom table extraction
- Frontend is now modularized under `imonitor/webui/` (`index.html` + `assets/*.css/js`), no longer embedded in Python source.

`imonitor-web` is now just an alias entrypoint to the same unified server app
for convenience.

## Lazy Service

By default `imonitor` commands auto-resolve daemon URL and try to start daemon lazily:
1. ping `/healthz`
2. try `systemctl --user start imonitord.service`
3. fallback spawn local background daemon process

So you no longer need to pass host/port each time.

You can override with env vars:
- `IMONITOR_DAEMON_URL`
- `IMONITOR_DAEMON_HOST`
- `IMONITOR_DAEMON_PORT`
- `IMONITOR_DAEMON_DB`

`run` defaults to daemon mode. If you want local-only outputs, use `daemon_enabled=false`
inside the config file and enable local sinks there.

## Query APIs

The daemon exposes agent-friendly read endpoints:

- `/api/agent/runs/recent`
- `/api/agent/run/{run_id}/tables/latest`
- `/api/agent/run/{run_id}/logs`
- `/api/taskmanager/runs`
- `/api/taskmanager/run/{run_id}/snapshot`
- `/api/taskmanager/run/{run_id}/performance?seconds=120`
- `/api/taskmanager/processes?limit=500`
- `POST /api/sql/query`

These are what `imonitor recent`, `imonitor tables latest`, and `imonitor logs`
use under the hood.

Example SQL query payload:

```json
{
  "sql": "SELECT ts_ns, pid, sensor, metric, value, unit FROM metrics_raw WHERE run_id = ? AND ts_ns BETWEEN ? AND ? ORDER BY ts_ns, pid LIMIT 500",
  "params": ["20260405-xxxx", 1712290000000000000, 1712290030000000000],
  "limit": 500
}
```

SQL endpoint is intentionally read-only (`SELECT`/`WITH`/`PRAGMA` only).

## System Sampling Policy

- Daemon system sampler writes only host-level aggregate metrics (no unrelated process rows).
- Per-process rows are written only for processes launched by `imonitor run` (its process tree).
- Daemon process sampler keeps a live in-memory full-system process snapshot for UI (`top`-style); non-monitored process rows are not written to DB.
- Default host sampling interval is low-frequency: `5s`.

Optional envs:
- `IMONITOR_SYSTEM_SAMPLER_ENABLED` (`1` by default)
- `IMONITOR_SYSTEM_INTERVAL_SEC` (`5.0` by default)
- `IMONITOR_SYSTEM_GPU_ENABLED` (`1` by default)
- `IMONITOR_PROCESS_SAMPLER_ENABLED` (`1` by default)
- `IMONITOR_PROCESS_INTERVAL_SEC` (`1.0` by default)
- `IMONITOR_PROCESS_MAX` (`300` by default)
- `IMONITOR_PROCESS_GPU_ENABLED` (`0` by default)

System endpoints:
- `/api/system/latest`
- `/api/system/performance?seconds=600`

GPU/PCIe related system metrics include:
- `system.gpu.util_pct`
- `system.gpu.mem_used_bytes`
- `system.pcie.rx_bytes_s`
- `system.pcie.tx_bytes_s`

## Run Config (Optional)

`--config` supports TOML and YAML.

Example `imonitor.run.toml`:

```toml
interval_sec = 0.5
daemon_enabled = true
enable_gpu = true
enable_net = true

[sink]
sqlite = false
csv = false
parquet = false
live = false
```

Local output mode example (`imonitor.run.yaml`):

```yaml
daemon_enabled: false
out_dir: ./runs/local
write_local_report: true
sink:
  sqlite: true
  csv: true
  parquet: false
```
