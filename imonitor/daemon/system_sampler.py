from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from imonitor.console import emit_log_line
from imonitor.daemon.store import DaemonStore


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


class SystemHostSampler:
    def __init__(
        self,
        store: DaemonStore,
        interval_sec: float = 5.0,
        enabled: bool = True,
        gpu_enabled: bool = True,
    ) -> None:
        self._store = store
        self._interval_sec = max(1.0, float(interval_sec))
        self._enabled = bool(enabled)
        self._gpu_enabled = bool(gpu_enabled)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._last_ts_ns: int | None = None
        self._last_cpu: tuple[int, int] | None = None
        self._last_disk: tuple[int, int] | None = None
        self._last_net: tuple[int, int] | None = None

        self._nvml = None
        self._nvml_handles = []
        self._gpu_static_cache: dict[str, dict[str, Any]] | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def interval_sec(self) -> float:
        return self._interval_sec

    @classmethod
    def from_env(cls, store: DaemonStore) -> "SystemHostSampler":
        enabled = _parse_bool_env("IMONITOR_SYSTEM_SAMPLER_ENABLED", True)
        gpu_enabled = _parse_bool_env("IMONITOR_SYSTEM_GPU_ENABLED", True)
        try:
            interval = float(os.getenv("IMONITOR_SYSTEM_INTERVAL_SEC", "5.0"))
        except ValueError:
            interval = 5.0
        return cls(store=store, interval_sec=interval, enabled=enabled, gpu_enabled=gpu_enabled)

    def start(self) -> None:
        if not self._enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="imonitord-system-sampler", daemon=True)
        self._thread.start()
        emit_log_line(f"[imonitord] system sampler started interval={self._interval_sec:.2f}s")

    def stop(self, timeout_sec: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.1, timeout_sec))
        self._shutdown_nvml()

    def _run(self) -> None:
        while not self._stop.is_set():
            ts_ns = time.time_ns()
            try:
                rows = self._collect(ts_ns)
                if rows:
                    self._store.append_system_host_samples(rows)
            except Exception as exc:
                emit_log_line(f"[imonitord] system sampler error: {exc}")
            self._stop.wait(self._interval_sec)

    def _collect(self, ts_ns: int) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        dt_sec = None
        if self._last_ts_ns is not None:
            dt_sec = max(1e-9, (ts_ns - self._last_ts_ns) / 1e9)

        cpu_now = self._read_cpu_totals()
        if cpu_now is not None and self._last_cpu is not None:
            total_delta = cpu_now[0] - self._last_cpu[0]
            busy_delta = cpu_now[1] - self._last_cpu[1]
            if total_delta > 0:
                rows.append(self._row(ts_ns, "system.cpu.util_pct", busy_delta / total_delta * 100.0, "pct"))
        self._last_cpu = cpu_now

        mem = self._read_meminfo_bytes()
        total = mem.get("MemTotal")
        available = mem.get("MemAvailable")
        if total is not None:
            rows.append(self._row(ts_ns, "system.mem.total_bytes", float(total), "bytes"))
        if available is not None:
            rows.append(self._row(ts_ns, "system.mem.available_bytes", float(available), "bytes"))
        if total is not None and available is not None:
            used = max(0.0, float(total) - float(available))
            rows.append(self._row(ts_ns, "system.mem.used_bytes", used, "bytes"))

        disk_now = self._read_disk_bytes_totals()
        if disk_now is not None and self._last_disk is not None and dt_sec is not None:
            rows.append(
                self._row(
                    ts_ns,
                    "system.disk.read_bps",
                    max(0.0, float(disk_now[0] - self._last_disk[0]) / dt_sec),
                    "bytes/s",
                )
            )
            rows.append(
                self._row(
                    ts_ns,
                    "system.disk.write_bps",
                    max(0.0, float(disk_now[1] - self._last_disk[1]) / dt_sec),
                    "bytes/s",
                )
            )
        self._last_disk = disk_now

        net_now = self._read_net_bytes_totals()
        if net_now is not None and self._last_net is not None and dt_sec is not None:
            rows.append(
                self._row(
                    ts_ns,
                    "system.net.rx_bps",
                    max(0.0, float(net_now[0] - self._last_net[0]) / dt_sec),
                    "bytes/s",
                )
            )
            rows.append(
                self._row(
                    ts_ns,
                    "system.net.tx_bps",
                    max(0.0, float(net_now[1] - self._last_net[1]) / dt_sec),
                    "bytes/s",
                )
            )
        self._last_net = net_now

        rows.extend(self._collect_gpu(ts_ns))
        self._last_ts_ns = ts_ns
        return rows

    def gpu_channels(self) -> list[str]:
        if not self._gpu_enabled:
            return []
        if not self._ensure_nvml():
            return []
        return [f"gpu{i}" for i, _ in enumerate(self._nvml_handles)]

    def gpu_static_profiles(self) -> dict[str, dict[str, Any]]:
        if not self._gpu_enabled:
            return {}
        if not self._ensure_nvml():
            return {}
        if self._gpu_static_cache is not None:
            return dict(self._gpu_static_cache)

        out: dict[str, dict[str, Any]] = {}
        for idx, handle in enumerate(self._nvml_handles):
            channel = f"gpu{idx}"
            name = self._read_nvml_str(handle, ("nvmlDeviceGetName",))
            uuid = self._read_nvml_str(handle, ("nvmlDeviceGetUUID",))
            pci_bus_id = self._read_pci_bus_id(handle)
            mem_total = self._read_mem_total(handle)
            gen_max = self._read_int_metric(handle, ("nvmlDeviceGetMaxPcieLinkGeneration",))
            width_max = self._read_int_metric(handle, ("nvmlDeviceGetMaxPcieLinkWidth",))
            power_limit_w = self._read_power_limit_watts(handle)
            out[channel] = {
                "channel": channel,
                "name": name,
                "uuid": uuid,
                "pci_bus_id": pci_bus_id,
                "mem_total_bytes": mem_total,
                "pcie_gen_max": gen_max,
                "pcie_width_max": width_max,
                "power_limit_w": power_limit_w,
                "numa_node": self._read_numa_node(pci_bus_id),
            }
        self._gpu_static_cache = out
        return dict(out)

    def _collect_gpu(self, ts_ns: int) -> list[dict[str, object]]:
        if not self._gpu_enabled:
            return []
        if not self._ensure_nvml():
            return []

        rows: list[dict[str, object]] = []
        util_values: list[float] = []
        mem_used_total = 0.0
        power_total_w = 0.0
        pcie_rx_total = 0.0
        pcie_tx_total = 0.0
        link_count_total = 0.0
        channel_count = 0
        for idx, handle in enumerate(self._nvml_handles):
            try:
                util = self._nvml.nvmlDeviceGetUtilizationRates(handle)
                mem = self._nvml.nvmlDeviceGetMemoryInfo(handle)
            except Exception:
                continue
            channel = f"gpu{idx}"
            channel_count += 1
            util_values.append(float(util.gpu))
            mem_used_total += float(mem.used)
            rows.append(self._row(ts_ns, f"system.gpu.{channel}.util_pct", float(util.gpu), "pct"))
            rows.append(self._row(ts_ns, f"system.gpu.{channel}.mem_used_bytes", float(mem.used), "bytes"))
            power_w = self._read_power_watts(handle)
            if power_w is not None:
                power_total_w += power_w
                rows.append(self._row(ts_ns, f"system.gpu.{channel}.power_w", power_w, "W"))

            pcie_rx = self._read_pcie_bytes_per_sec(handle, "rx")
            pcie_tx = self._read_pcie_bytes_per_sec(handle, "tx")
            if pcie_rx is not None:
                pcie_rx_total += pcie_rx
                rows.append(self._row(ts_ns, f"system.pcie.{channel}.rx_bytes_s", pcie_rx, "bytes/s"))
            if pcie_tx is not None:
                pcie_tx_total += pcie_tx
                rows.append(self._row(ts_ns, f"system.pcie.{channel}.tx_bytes_s", pcie_tx, "bytes/s"))
            pcie_tp = float(pcie_rx or 0.0) + float(pcie_tx or 0.0)
            rows.append(self._row(ts_ns, f"system.pcie.{channel}.throughput_bytes_s", pcie_tp, "bytes/s"))

            pcie_gen_cur = self._read_int_metric(handle, ("nvmlDeviceGetCurrPcieLinkGeneration",))
            pcie_gen_max = self._read_int_metric(handle, ("nvmlDeviceGetMaxPcieLinkGeneration",))
            pcie_w_cur = self._read_int_metric(handle, ("nvmlDeviceGetCurrPcieLinkWidth",))
            pcie_w_max = self._read_int_metric(handle, ("nvmlDeviceGetMaxPcieLinkWidth",))
            pcie_gen_static = pcie_gen_max if pcie_gen_max is not None else pcie_gen_cur
            if pcie_gen_static is not None:
                rows.append(self._row(ts_ns, f"system.pcie.{channel}.link.gen", pcie_gen_static, "count"))
            if pcie_w_cur is not None:
                rows.append(self._row(ts_ns, f"system.pcie.{channel}.link.width", pcie_w_cur, "count"))
            if pcie_gen_cur is not None:
                rows.append(self._row(ts_ns, f"system.pcie.{channel}.link.gen.current", pcie_gen_cur, "count"))
            if pcie_gen_max is not None:
                rows.append(self._row(ts_ns, f"system.pcie.{channel}.link.gen.max", pcie_gen_max, "count"))
            if pcie_w_cur is not None:
                rows.append(self._row(ts_ns, f"system.pcie.{channel}.link.width.current", pcie_w_cur, "count"))
            if pcie_w_max is not None:
                rows.append(self._row(ts_ns, f"system.pcie.{channel}.link.width.max", pcie_w_max, "count"))

            nvlink_links = self._count_active_nvlink_links(handle)
            if nvlink_links is not None:
                link_count_total += float(nvlink_links)

        if util_values:
            rows.append(self._row(ts_ns, "system.gpu.util_pct", sum(util_values) / len(util_values), "pct"))
        rows.append(self._row(ts_ns, "system.gpu.mem_used_bytes", mem_used_total, "bytes"))
        rows.append(self._row(ts_ns, "system.gpu.power_w", power_total_w, "W"))
        rows.append(self._row(ts_ns, "system.pcie.rx_bytes_s", pcie_rx_total, "bytes/s"))
        rows.append(self._row(ts_ns, "system.pcie.tx_bytes_s", pcie_tx_total, "bytes/s"))
        rows.append(self._row(ts_ns, "system.pcie.throughput_bytes_s", pcie_rx_total + pcie_tx_total, "bytes/s"))
        rows.append(self._row(ts_ns, "system.pcie.channel_count", float(channel_count), "count"))
        rows.append(self._row(ts_ns, "system.nvlink.link_count", link_count_total, "count"))
        return rows

    def _read_power_watts(self, handle) -> float | None:
        fn = getattr(self._nvml, "nvmlDeviceGetPowerUsage", None)
        if fn is None:
            return None
        try:
            mw = float(fn(handle))
        except Exception:
            return None
        if mw < 0:
            return 0.0
        return mw / 1000.0

    def _read_power_limit_watts(self, handle) -> float | None:
        for name in ("nvmlDeviceGetEnforcedPowerLimit", "nvmlDeviceGetPowerManagementLimit"):
            fn = getattr(self._nvml, name, None)
            if fn is None:
                continue
            try:
                mw = float(fn(handle))
            except Exception:
                continue
            if mw < 0:
                return 0.0
            return mw / 1000.0
        return None

    def _read_pcie_bytes_per_sec(self, handle, direction: str) -> float | None:
        fn = getattr(self._nvml, "nvmlDeviceGetPcieThroughput", None)
        if fn is None:
            return None
        const_name = "NVML_PCIE_UTIL_RX_BYTES" if direction == "rx" else "NVML_PCIE_UTIL_TX_BYTES"
        counter = getattr(self._nvml, const_name, None)
        if counter is None:
            return None
        try:
            value_kb_s = float(fn(handle, counter))
        except Exception:
            return None
        if value_kb_s < 0:
            return 0.0
        return value_kb_s * 1024.0

    def _count_active_nvlink_links(self, handle) -> int | None:
        fn_state = getattr(self._nvml, "nvmlDeviceGetNvLinkState", None)
        if fn_state is None:
            return None
        max_links = int(getattr(self._nvml, "NVML_NVLINK_MAX_LINKS", 18))
        active = 0
        for link in range(max_links):
            try:
                state = fn_state(handle, link)
            except Exception:
                continue
            if int(state) == 1:
                active += 1
        return active

    def _read_int_metric(self, handle, fn_names: tuple[str, ...]) -> float | None:
        for name in fn_names:
            fn = getattr(self._nvml, name, None)
            if fn is None:
                continue
            try:
                return float(fn(handle))
            except Exception:
                continue
        return None

    def _read_nvml_str(self, handle, fn_names: tuple[str, ...]) -> str:
        for name in fn_names:
            fn = getattr(self._nvml, name, None)
            if fn is None:
                continue
            try:
                raw = fn(handle)
            except Exception:
                continue
            if isinstance(raw, (bytes, bytearray)):
                try:
                    return raw.decode("utf-8", errors="ignore")
                except Exception:
                    return str(raw)
            return str(raw)
        return ""

    def _read_mem_total(self, handle) -> float:
        fn = getattr(self._nvml, "nvmlDeviceGetMemoryInfo", None)
        if fn is None:
            return 0.0
        try:
            mem = fn(handle)
            return float(getattr(mem, "total", 0.0) or 0.0)
        except Exception:
            return 0.0

    def _read_pci_bus_id(self, handle) -> str:
        fn = getattr(self._nvml, "nvmlDeviceGetPciInfo", None)
        if fn is None:
            return ""
        try:
            info = fn(handle)
        except Exception:
            return ""
        bus_id = getattr(info, "busId", "")
        if isinstance(bus_id, (bytes, bytearray)):
            bus_id = bus_id.decode("utf-8", errors="ignore")
        s = str(bus_id).strip()
        if not s:
            return ""
        # NVML may return 00000000:31:00.0; sysfs uses 0000:31:00.0
        parts = s.split(":")
        if len(parts) == 3 and len(parts[0]) > 4:
            parts[0] = parts[0][-4:]
            return ":".join(parts)
        return s

    @staticmethod
    def _read_numa_node(pci_bus_id: str) -> int | None:
        if not pci_bus_id:
            return None
        path = Path("/sys/bus/pci/devices") / pci_bus_id / "numa_node"
        try:
            raw = path.read_text(encoding="utf-8").strip()
            val = int(raw)
        except Exception:
            return None
        return val if val >= 0 else None

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

    @staticmethod
    def _row(ts_ns: int, metric: str, value: float, unit: str) -> dict[str, object]:
        return {"ts_ns": ts_ns, "metric": metric, "value": float(value), "unit": unit}

    @staticmethod
    def _read_cpu_totals() -> tuple[int, int] | None:
        path = Path("/proc/stat")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in lines:
            if not line.startswith("cpu "):
                continue
            parts = line.split()
            if len(parts) < 5:
                return None
            try:
                nums = [int(x) for x in parts[1:]]
            except ValueError:
                return None
            total = sum(nums)
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            busy = max(0, total - idle)
            return total, busy
        return None

    @staticmethod
    def _read_meminfo_bytes() -> dict[str, int]:
        path = Path("/proc/meminfo")
        out: dict[str, int] = {}
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return out
        wanted = {"MemTotal", "MemAvailable"}
        for line in lines:
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            key = key.strip()
            if key not in wanted:
                continue
            parts = raw.strip().split()
            if not parts:
                continue
            try:
                out[key] = int(parts[0]) * 1024
            except ValueError:
                continue
        return out

    @staticmethod
    def _read_disk_bytes_totals() -> tuple[int, int] | None:
        path = Path("/proc/diskstats")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None

        read_sectors_total = 0
        write_sectors_total = 0
        for line in lines:
            parts = line.split()
            if len(parts) < 14:
                continue
            name = parts[2]
            if name.startswith(("loop", "ram", "fd", "sr")):
                continue
            try:
                read_sectors_total += int(parts[5])
                write_sectors_total += int(parts[9])
            except ValueError:
                continue

        return read_sectors_total * 512, write_sectors_total * 512

    @staticmethod
    def _read_net_bytes_totals() -> tuple[int, int] | None:
        path = Path("/proc/net/dev")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None

        rx_total = 0
        tx_total = 0
        for line in lines[2:]:
            if ":" not in line:
                continue
            iface, raw = line.split(":", 1)
            iface = iface.strip()
            if iface == "lo":
                continue
            cols = raw.split()
            if len(cols) < 16:
                continue
            try:
                rx_total += int(cols[0])
                tx_total += int(cols[8])
            except ValueError:
                continue
        return rx_total, tx_total
