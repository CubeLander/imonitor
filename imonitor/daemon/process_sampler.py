from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from imonitor.console import emit_log_line


_PROC = Path("/proc")


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


class SystemProcessSampler:
    def __init__(
        self,
        interval_sec: float = 1.0,
        enabled: bool = True,
        gpu_enabled: bool = True,
        max_processes: int = 300,
    ) -> None:
        self._interval_sec = max(0.2, float(interval_sec))
        self._enabled = bool(enabled)
        self._gpu_enabled = bool(gpu_enabled)
        self._max_processes = max(50, int(max_processes))

        self._hz = float(os.sysconf("SC_CLK_TCK"))
        self._page_size = int(os.sysconf("SC_PAGE_SIZE"))

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        self._last_ts_ns: int | None = None
        self._last_cpu_ticks: dict[int, int] = {}
        self._last_io_bytes: dict[int, tuple[int, int]] = {}

        self._latest_ts_ns: int | None = None
        self._snapshot_rows: list[dict[str, object]] = []
        self._capabilities: dict[str, object] = {
            "gpu_proc_mem": False,
            "gpu_proc_util": False,
            "gpu_channels": [],
        }

        self._nvml = None
        self._nvml_handles = []
        self._last_gpu_util_ts_us: dict[int, int] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def interval_sec(self) -> float:
        return self._interval_sec

    @classmethod
    def from_env(cls) -> "SystemProcessSampler":
        enabled = _parse_bool_env("IMONITOR_PROCESS_SAMPLER_ENABLED", True)
        gpu_enabled = _parse_bool_env("IMONITOR_PROCESS_GPU_ENABLED", True)
        try:
            interval = float(os.getenv("IMONITOR_PROCESS_INTERVAL_SEC", "1.0"))
        except ValueError:
            interval = 1.0
        try:
            max_processes = int(os.getenv("IMONITOR_PROCESS_MAX", "300"))
        except ValueError:
            max_processes = 300
        return cls(
            interval_sec=interval,
            enabled=enabled,
            gpu_enabled=gpu_enabled,
            max_processes=max_processes,
        )

    def start(self) -> None:
        if not self._enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="imonitord-process-sampler", daemon=True)
        self._thread.start()
        emit_log_line(
            f"[imonitord] process sampler started interval={self._interval_sec:.2f}s max={self._max_processes}"
        )

    def stop(self, timeout_sec: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.1, timeout_sec))
        self._shutdown_nvml()

    def latest_snapshot(self, limit: int) -> dict[str, object]:
        with self._lock:
            rows = list(self._snapshot_rows)
            latest_ts_ns = self._latest_ts_ns
            capabilities = dict(self._capabilities)
        lim = max(1, int(limit))
        if len(rows) > lim:
            rows = rows[:lim]
        return {
            "latest_ts_ns": latest_ts_ns,
            "rows": rows,
            "capabilities": capabilities,
            "sampling_interval_sec": self._interval_sec,
            "sampler_enabled": self._enabled,
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            ts_ns = time.time_ns()
            try:
                rows, capabilities = self._collect(ts_ns)
                with self._lock:
                    self._latest_ts_ns = ts_ns
                    self._snapshot_rows = rows
                    self._capabilities = capabilities
            except Exception as exc:
                emit_log_line(f"[imonitord] process sampler error: {exc}")
            self._stop.wait(self._interval_sec)

    def _collect(self, ts_ns: int) -> tuple[list[dict[str, object]], dict[str, object]]:
        dt_sec = None
        if self._last_ts_ns is not None:
            dt_sec = max(1e-9, (ts_ns - self._last_ts_ns) / 1e9)

        gpu_by_pid: dict[int, dict[str, dict[str, object]]] = {}
        gpu_channels: list[str] = []
        capabilities = {
            "gpu_proc_mem": False,
            "gpu_proc_util": False,
            "gpu_channels": [],
        }
        if self._gpu_enabled:
            gpu_by_pid, gpu_channels, has_gpu_mem, has_gpu_util = self._collect_gpu_proc_metrics_by_pid()
            capabilities = {
                "gpu_proc_mem": bool(has_gpu_mem),
                "gpu_proc_util": bool(has_gpu_util),
                "gpu_channels": list(gpu_channels),
            }

        rows: list[dict[str, object]] = []
        next_cpu_ticks: dict[int, int] = {}
        next_io_bytes: dict[int, tuple[int, int]] = {}

        for entry in _PROC.iterdir():
            name = entry.name
            if not name.isdigit():
                continue
            pid = int(name)
            stat = self._read_stat(pid)
            if stat is None:
                continue

            comm, total_ticks = stat
            rss_bytes = self._read_rss_bytes(pid)
            io_read_bytes, io_write_bytes = self._read_io_bytes(pid)

            cpu_pct = 0.0
            prev_ticks = self._last_cpu_ticks.get(pid)
            if prev_ticks is not None and dt_sec is not None:
                cpu_pct = max(0.0, ((total_ticks - prev_ticks) / self._hz) / dt_sec * 100.0)

            io_read_bps = 0.0
            io_write_bps = 0.0
            prev_io = self._last_io_bytes.get(pid)
            if prev_io is not None and dt_sec is not None:
                io_read_bps = max(0.0, float(io_read_bytes - prev_io[0]) / dt_sec)
                io_write_bps = max(0.0, float(io_write_bytes - prev_io[1]) / dt_sec)

            per_gpu = gpu_by_pid.get(pid, {})
            gpu_mem = 0.0
            gpu_known = False
            for channel in gpu_channels:
                cell = per_gpu.get(channel, {})
                if bool(cell.get("mem_known")):
                    gpu_known = True
                    gpu_mem += float(cell.get("mem_used_bytes", 0.0) or 0.0)

            rows.append(
                {
                    "pid": pid,
                    "comm": comm,
                    "cpu_pct": cpu_pct,
                    "mem_rss_bytes": float(rss_bytes),
                    "io_read_bps": io_read_bps,
                    "io_write_bps": io_write_bps,
                    "net_rx_bps": 0.0,
                    "net_tx_bps": 0.0,
                    "gpu_mem_used_bytes": gpu_mem,
                    "gpu_mem_known": gpu_known,
                    "gpu_per_device": per_gpu,
                    "source": "system",
                    "last_seen_ns": ts_ns,
                }
            )

            next_cpu_ticks[pid] = total_ticks
            next_io_bytes[pid] = (io_read_bytes, io_write_bytes)

        rows.sort(key=lambda x: (float(x["cpu_pct"]), float(x["mem_rss_bytes"]), -int(x["pid"])), reverse=True)
        if len(rows) > self._max_processes:
            rows = rows[: self._max_processes]

        self._last_ts_ns = ts_ns
        self._last_cpu_ticks = next_cpu_ticks
        self._last_io_bytes = next_io_bytes
        return rows, capabilities

    @staticmethod
    def _read_stat(pid: int) -> tuple[str, int] | None:
        path = _PROC / str(pid) / "stat"
        try:
            raw = path.read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError, OSError):
            return None

        lparen = raw.find("(")
        rparen = raw.rfind(")")
        if lparen < 0 or rparen <= lparen:
            return None
        comm = raw[lparen + 1 : rparen]
        fields = raw[rparen + 2 :].split()
        if len(fields) <= 12:
            return None
        try:
            utime = int(fields[11])
            stime = int(fields[12])
        except ValueError:
            return None
        return comm, (utime + stime)

    def _read_rss_bytes(self, pid: int) -> int:
        path = _PROC / str(pid) / "statm"
        try:
            fields = path.read_text(encoding="utf-8").split()
        except (FileNotFoundError, PermissionError, OSError):
            return 0
        if len(fields) < 2:
            return 0
        try:
            rss_pages = int(fields[1])
        except ValueError:
            return 0
        return max(0, rss_pages * self._page_size)

    @staticmethod
    def _read_io_bytes(pid: int) -> tuple[int, int]:
        path = _PROC / str(pid) / "io"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, PermissionError, OSError):
            return 0, 0

        read_bytes = 0
        write_bytes = 0
        for line in lines:
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            key = key.strip()
            if key not in {"read_bytes", "write_bytes"}:
                continue
            try:
                val = int(raw.strip())
            except ValueError:
                continue
            if key == "read_bytes":
                read_bytes = val
            elif key == "write_bytes":
                write_bytes = val
        return read_bytes, write_bytes

    def _collect_gpu_proc_mem_by_pid(self) -> dict[int, int]:
        if not self._ensure_nvml():
            return {}

        out: dict[int, int] = {}
        for handle in self._nvml_handles:
            procs = self._nvml_processes(handle)
            for proc in procs:
                try:
                    pid = int(getattr(proc, "pid"))
                except Exception:
                    continue
                used = int(getattr(proc, "usedGpuMemory", 0))
                if used < 0 or used > 9_000_000_000_000_000_000:
                    used = 0
                prev = out.get(pid)
                if prev is None or used > prev:
                    out[pid] = used
        return out

    def _collect_gpu_proc_metrics_by_pid(
        self,
    ) -> tuple[dict[int, dict[str, dict[str, object]]], list[str], bool, bool]:
        if not self._ensure_nvml():
            return {}, [], False, False

        out: dict[int, dict[str, dict[str, object]]] = {}
        channels: list[str] = []
        has_mem = False
        has_util = False

        for idx, handle in enumerate(self._nvml_handles):
            channel = f"gpu{idx}"
            channels.append(channel)

            mem_by_pid: dict[int, int] = {}
            for proc in self._nvml_processes(handle):
                try:
                    pid = int(getattr(proc, "pid"))
                except Exception:
                    continue
                used = int(getattr(proc, "usedGpuMemory", 0))
                if used < 0 or used > 9_000_000_000_000_000_000:
                    used = 0
                prev = mem_by_pid.get(pid)
                if prev is None or used > prev:
                    mem_by_pid[pid] = used
            if mem_by_pid:
                has_mem = True

            for pid, used in mem_by_pid.items():
                row = out.setdefault(pid, {})
                cell = row.setdefault(channel, {})
                cell["mem_used_bytes"] = float(used)
                cell["mem_known"] = True

            util_by_pid = self._nvml_process_util_by_pid(handle, idx)
            if util_by_pid:
                has_util = True

            for pid, util_row in util_by_pid.items():
                row = out.setdefault(pid, {})
                cell = row.setdefault(channel, {})
                cell["util_pct"] = float(util_row.get("sm_util", 0.0))
                cell["mem_util_pct"] = float(util_row.get("mem_util", 0.0))
                cell["enc_util_pct"] = float(util_row.get("enc_util", 0.0))
                cell["dec_util_pct"] = float(util_row.get("dec_util", 0.0))
                cell["util_known"] = True
                cell["util_ts_us"] = int(util_row.get("ts_us", 0))

        channels.sort(key=lambda x: int(x[3:]) if x.startswith("gpu") and x[3:].isdigit() else 9999)
        return out, channels, has_mem, has_util

    def _nvml_process_util_by_pid(self, handle, gpu_idx: int) -> dict[int, dict[str, object]]:
        if self._nvml is None:
            return {}

        fn = getattr(self._nvml, "nvmlDeviceGetProcessUtilization", None)
        if fn is None:
            return {}

        last_ts = int(self._last_gpu_util_ts_us.get(gpu_idx, 0))
        try:
            rows = fn(handle, last_ts)
        except Exception:
            return {}

        latest_by_pid: dict[int, dict[str, object]] = {}
        max_seen_ts = last_ts
        for item in rows or []:
            try:
                pid = int(getattr(item, "pid"))
                ts_us = int(getattr(item, "timeStamp", 0))
            except Exception:
                continue
            if ts_us > max_seen_ts:
                max_seen_ts = ts_us
            prev = latest_by_pid.get(pid)
            if prev is not None and int(prev.get("ts_us", 0)) >= ts_us:
                continue
            latest_by_pid[pid] = {
                "ts_us": ts_us,
                "sm_util": float(getattr(item, "smUtil", 0.0)),
                "mem_util": float(getattr(item, "memUtil", 0.0)),
                "enc_util": float(getattr(item, "encUtil", 0.0)),
                "dec_util": float(getattr(item, "decUtil", 0.0)),
            }

        if max_seen_ts > last_ts:
            self._last_gpu_util_ts_us[gpu_idx] = max_seen_ts
        return latest_by_pid

    def _nvml_processes(self, handle) -> list[object]:
        if self._nvml is None:
            return []
        out: list[object] = []
        fn_names = [
            "nvmlDeviceGetComputeRunningProcesses_v3",
            "nvmlDeviceGetComputeRunningProcesses_v2",
            "nvmlDeviceGetComputeRunningProcesses",
            "nvmlDeviceGetGraphicsRunningProcesses_v3",
            "nvmlDeviceGetGraphicsRunningProcesses_v2",
            "nvmlDeviceGetGraphicsRunningProcesses",
            "nvmlDeviceGetMPSComputeRunningProcesses_v3",
            "nvmlDeviceGetMPSComputeRunningProcesses_v2",
            "nvmlDeviceGetMPSComputeRunningProcesses",
        ]
        for name in fn_names:
            fn = getattr(self._nvml, name, None)
            if fn is None:
                continue
            try:
                rows = fn(handle)
            except Exception:
                continue
            if rows:
                out.extend(rows)
        return out

    def _ensure_nvml(self) -> bool:
        if self._nvml is not None:
            return True
        try:
            import pynvml

            pynvml.nvmlInit()
            count = int(pynvml.nvmlDeviceGetCount())
            self._nvml = pynvml
            self._nvml_handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
            return True
        except Exception:
            self._nvml = None
            self._nvml_handles = []
            return False

    def _shutdown_nvml(self) -> None:
        if self._nvml is None:
            return
        try:
            self._nvml.nvmlShutdown()
        except Exception:
            pass
        self._nvml = None
        self._nvml_handles = []
