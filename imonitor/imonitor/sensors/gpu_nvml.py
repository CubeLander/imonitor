from __future__ import annotations

from imonitor.core.types import MonitorContext
from imonitor.sensors.base import Sensor
from imonitor.signals.schema import Signal


class GPUNvmlSensor(Sensor):
    name = "gpu_nvml"

    def __init__(self, nvml_module) -> None:
        self._nvml = nvml_module
        self._device_count = self._nvml.nvmlDeviceGetCount()

    @classmethod
    def create(cls) -> "GPUNvmlSensor | None":
        try:
            import pynvml

            pynvml.nvmlInit()
            return cls(pynvml)
        except Exception:
            return None

    def sample(self, ctx: MonitorContext, ts_ns: int) -> list[Signal]:
        out: list[Signal] = []
        active = ctx.active_pids
        alias_map = ctx.metadata.get("pid_alias_to_local", {}) if isinstance(ctx.metadata, dict) else {}

        for idx in range(self._device_count):
            h = self._nvml.nvmlDeviceGetHandleByIndex(idx)
            tags = {"gpu_index": str(idx)}

            try:
                util = self._nvml.nvmlDeviceGetUtilizationRates(h)
                mem = self._nvml.nvmlDeviceGetMemoryInfo(h)
            except Exception:
                continue

            out.append(
                Signal(ts_ns, ctx.run_id, self.name, "gpu.device.util_pct", float(util.gpu), "pct", None, tags)
            )
            out.append(
                Signal(ts_ns, ctx.run_id, self.name, "gpu.device.mem_used_bytes", float(mem.used), "bytes", None, tags)
            )

            pcie_rx_bps = self._read_pcie_bytes_per_sec(h, "rx")
            pcie_tx_bps = self._read_pcie_bytes_per_sec(h, "tx")
            if pcie_rx_bps is not None:
                out.append(
                    Signal(
                        ts_ns,
                        ctx.run_id,
                        self.name,
                        "pcie.device.rx_bytes_s",
                        pcie_rx_bps,
                        "bytes/s",
                        None,
                        tags,
                    )
                )
            if pcie_tx_bps is not None:
                out.append(
                    Signal(
                        ts_ns,
                        ctx.run_id,
                        self.name,
                        "pcie.device.tx_bytes_s",
                        pcie_tx_bps,
                        "bytes/s",
                        None,
                        tags,
                    )
                )

            pcie_gen_cur = self._read_int_metric(h, ("nvmlDeviceGetCurrPcieLinkGeneration",))
            pcie_gen_max = self._read_int_metric(h, ("nvmlDeviceGetMaxPcieLinkGeneration",))
            pcie_w_cur = self._read_int_metric(h, ("nvmlDeviceGetCurrPcieLinkWidth",))
            pcie_w_max = self._read_int_metric(h, ("nvmlDeviceGetMaxPcieLinkWidth",))
            if pcie_gen_cur is not None:
                out.append(Signal(ts_ns, ctx.run_id, self.name, "pcie.link.gen.current", pcie_gen_cur, "count", None, tags))
            if pcie_gen_max is not None:
                out.append(Signal(ts_ns, ctx.run_id, self.name, "pcie.link.gen.max", pcie_gen_max, "count", None, tags))
            if pcie_w_cur is not None:
                out.append(Signal(ts_ns, ctx.run_id, self.name, "pcie.link.width.current", pcie_w_cur, "count", None, tags))
            if pcie_w_max is not None:
                out.append(Signal(ts_ns, ctx.run_id, self.name, "pcie.link.width.max", pcie_w_max, "count", None, tags))

            # Placeholder for future multi-GPU/NVLink expansion.
            nvlink_links = self._count_active_nvlink_links(h)
            if nvlink_links is not None:
                out.append(Signal(ts_ns, ctx.run_id, self.name, "nvlink.device.link_count", float(nvlink_links), "count", None, tags))

            proc_lists: list[object] = []
            for fn_name in (
                "nvmlDeviceGetComputeRunningProcesses_v3",
                "nvmlDeviceGetComputeRunningProcesses_v2",
                "nvmlDeviceGetComputeRunningProcesses",
                "nvmlDeviceGetGraphicsRunningProcesses_v3",
                "nvmlDeviceGetGraphicsRunningProcesses_v2",
                "nvmlDeviceGetGraphicsRunningProcesses",
            ):
                fn = getattr(self._nvml, fn_name, None)
                if fn is None:
                    continue
                try:
                    current = fn(h)
                except Exception:
                    continue
                if current:
                    proc_lists.extend(current)

            # De-duplicate by pid within a GPU and keep max observed memory usage.
            per_pid_used: dict[int, float] = {}
            for proc in proc_lists:
                pid = int(getattr(proc, "pid", -1))
                if pid < 0:
                    continue
                raw_used = getattr(proc, "usedGpuMemory", 0)
                try:
                    used = float(raw_used)
                except Exception:
                    continue
                # NVML can expose "not available" as very large uint64 sentinel.
                if used < 0 or used > 9.0e18:
                    used = 0.0
                prev = per_pid_used.get(pid)
                if prev is None or used > prev:
                    per_pid_used[pid] = used

            for pid, used in per_pid_used.items():
                local_pid = int(alias_map.get(pid, pid))
                if active and local_pid not in active:
                    continue
                out.append(
                    Signal(
                        ts_ns,
                        ctx.run_id,
                        self.name,
                        "gpu.proc.mem_used_bytes",
                        used,
                        "bytes",
                        local_pid,
                        {**tags, "nvml_pid": str(pid)},
                    )
                )

        return out

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

    def close(self) -> None:
        try:
            self._nvml.nvmlShutdown()
        except Exception:
            pass
