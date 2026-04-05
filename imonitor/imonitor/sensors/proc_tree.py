from __future__ import annotations

from imonitor.core.launcher import Procfs
from imonitor.core.types import MonitorContext
from imonitor.sensors.base import Sensor
from imonitor.signals.schema import Signal


class ProcTreeSensor(Sensor):
    name = "proc_tree"

    def sample(self, ctx: MonitorContext, ts_ns: int) -> list[Signal]:
        pids = Procfs.list_descendants(ctx.root_pid)
        ctx.active_pids = pids

        signals: list[Signal] = [
            Signal(
                ts_ns=ts_ns,
                run_id=ctx.run_id,
                sensor=self.name,
                metric="proc.count",
                value=float(len(pids)),
                unit="count",
                pid=ctx.root_pid,
            )
        ]

        for pid in pids:
            comm = Procfs.read_comm(pid)
            signals.append(
                Signal(
                    ts_ns=ts_ns,
                    run_id=ctx.run_id,
                    sensor=self.name,
                    metric="proc.alive",
                    value=1.0,
                    unit="bool",
                    pid=pid,
                    tags={"comm": comm},
                )
            )

        return signals
