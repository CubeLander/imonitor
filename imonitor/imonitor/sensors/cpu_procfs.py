from __future__ import annotations

import os
from pathlib import Path

from imonitor.core.launcher import Procfs
from imonitor.core.types import MonitorContext
from imonitor.sensors.base import Sensor
from imonitor.signals.schema import Signal


class CPUProcfsSensor(Sensor):
    name = "cpu_procfs"

    def __init__(self) -> None:
        self._hz = float(os.sysconf("SC_CLK_TCK"))
        self._last_total_ticks: dict[int, int] = {}
        self._last_ts_ns: int | None = None

    def sample(self, ctx: MonitorContext, ts_ns: int) -> list[Signal]:
        pids = ctx.active_pids or ({ctx.root_pid} if Procfs.pid_exists(ctx.root_pid) else set())
        dt_sec = None
        if self._last_ts_ns is not None:
            dt_sec = max(1e-9, (ts_ns - self._last_ts_ns) / 1e9)

        signals: list[Signal] = []
        seen: set[int] = set()
        for pid in pids:
            total_ticks = self._read_total_ticks(pid)
            if total_ticks is None:
                continue
            seen.add(pid)
            total_cpu_sec = total_ticks / self._hz
            comm = Procfs.read_comm(pid)
            signals.append(
                Signal(
                    ts_ns=ts_ns,
                    run_id=ctx.run_id,
                    sensor=self.name,
                    metric="cpu.time_sec_total",
                    value=total_cpu_sec,
                    unit="s",
                    pid=pid,
                    tags={"comm": comm},
                )
            )

            prev = self._last_total_ticks.get(pid)
            if prev is not None and dt_sec is not None:
                delta_ticks = max(0, total_ticks - prev)
                util_pct = (delta_ticks / self._hz) / dt_sec * 100.0
                signals.append(
                    Signal(
                        ts_ns=ts_ns,
                        run_id=ctx.run_id,
                        sensor=self.name,
                        metric="cpu.util_pct",
                        value=util_pct,
                        unit="pct",
                        pid=pid,
                        tags={"comm": comm},
                    )
                )

            self._last_total_ticks[pid] = total_ticks

        # Drop stale pids to keep state bounded.
        stale = set(self._last_total_ticks) - seen
        for pid in stale:
            self._last_total_ticks.pop(pid, None)

        self._last_ts_ns = ts_ns
        return signals

    @staticmethod
    def _read_total_ticks(pid: int) -> int | None:
        path = Path(f"/proc/{pid}/stat")
        try:
            raw = path.read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError, OSError):
            return None

        rparen = raw.rfind(")")
        if rparen < 0:
            return None
        fields = raw[rparen + 2 :].split()
        # fields start from stat field #3 (state)
        # utime=#14 => index 11, stime=#15 => index 12
        if len(fields) <= 12:
            return None
        try:
            utime = int(fields[11])
            stime = int(fields[12])
        except ValueError:
            return None
        return utime + stime
