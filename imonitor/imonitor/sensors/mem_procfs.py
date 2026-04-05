from __future__ import annotations

from pathlib import Path

from imonitor.core.launcher import Procfs
from imonitor.core.types import MonitorContext
from imonitor.sensors.base import Sensor
from imonitor.signals.schema import Signal


class MemoryProcfsSensor(Sensor):
    name = "mem_procfs"

    def sample(self, ctx: MonitorContext, ts_ns: int) -> list[Signal]:
        pids = ctx.active_pids or ({ctx.root_pid} if Procfs.pid_exists(ctx.root_pid) else set())
        signals: list[Signal] = []
        for pid in pids:
            status = self._read_status(pid)
            if status is None:
                continue
            comm = Procfs.read_comm(pid)
            rss_kb = status.get("VmRSS")
            if rss_kb is not None:
                signals.append(
                    Signal(
                        ts_ns=ts_ns,
                        run_id=ctx.run_id,
                        sensor=self.name,
                        metric="mem.rss_bytes",
                        value=float(rss_kb * 1024),
                        unit="bytes",
                        pid=pid,
                        tags={"comm": comm},
                    )
                )
            vms_kb = status.get("VmSize")
            if vms_kb is not None:
                signals.append(
                    Signal(
                        ts_ns=ts_ns,
                        run_id=ctx.run_id,
                        sensor=self.name,
                        metric="mem.vms_bytes",
                        value=float(vms_kb * 1024),
                        unit="bytes",
                        pid=pid,
                        tags={"comm": comm},
                    )
                )
        return signals

    @staticmethod
    def _read_status(pid: int) -> dict[str, int] | None:
        path = Path(f"/proc/{pid}/status")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, PermissionError, OSError):
            return None

        out: dict[str, int] = {}
        for line in lines:
            if not line.startswith(("VmRSS:", "VmSize:")):
                continue
            key, raw_value = line.split(":", 1)
            parts = raw_value.strip().split()
            if not parts:
                continue
            try:
                out[key] = int(parts[0])
            except ValueError:
                continue
        return out
