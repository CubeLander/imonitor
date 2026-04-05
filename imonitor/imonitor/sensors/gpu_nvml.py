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

        for idx in range(self._device_count):
            h = self._nvml.nvmlDeviceGetHandleByIndex(idx)
            tags = {"gpu_index": str(idx)}

            util = self._nvml.nvmlDeviceGetUtilizationRates(h)
            mem = self._nvml.nvmlDeviceGetMemoryInfo(h)

            out.append(
                Signal(ts_ns, ctx.run_id, self.name, "gpu.device.util_pct", float(util.gpu), "pct", None, tags)
            )
            out.append(
                Signal(ts_ns, ctx.run_id, self.name, "gpu.device.mem_used_bytes", float(mem.used), "bytes", None, tags)
            )

            proc_lists = []
            for fn_name in (
                "nvmlDeviceGetComputeRunningProcesses_v3",
                "nvmlDeviceGetComputeRunningProcesses_v2",
                "nvmlDeviceGetComputeRunningProcesses",
            ):
                fn = getattr(self._nvml, fn_name, None)
                if fn is None:
                    continue
                try:
                    proc_lists = fn(h)
                    break
                except Exception:
                    continue

            for proc in proc_lists:
                pid = int(getattr(proc, "pid", -1))
                if pid < 0:
                    continue
                if active and pid not in active:
                    continue
                used = float(getattr(proc, "usedGpuMemory", 0))
                out.append(
                    Signal(
                        ts_ns,
                        ctx.run_id,
                        self.name,
                        "gpu.proc.mem_used_bytes",
                        used,
                        "bytes",
                        pid,
                        tags,
                    )
                )

        return out

    def close(self) -> None:
        try:
            self._nvml.nvmlShutdown()
        except Exception:
            pass
