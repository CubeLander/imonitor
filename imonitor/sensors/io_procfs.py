from __future__ import annotations

from pathlib import Path

from imonitor.core.launcher import Procfs
from imonitor.core.types import MonitorContext
from imonitor.sensors.base import Sensor
from imonitor.signals.schema import Signal


class IOProcfsSensor(Sensor):
    name = "io_procfs"

    def __init__(self) -> None:
        self._last_ts_ns: int | None = None
        self._last_read: dict[int, int] = {}
        self._last_write: dict[int, int] = {}

    def sample(self, ctx: MonitorContext, ts_ns: int) -> list[Signal]:
        pids = ctx.active_pids or ({ctx.root_pid} if Procfs.pid_exists(ctx.root_pid) else set())
        dt_sec = None
        if self._last_ts_ns is not None:
            dt_sec = max(1e-9, (ts_ns - self._last_ts_ns) / 1e9)

        signals: list[Signal] = []
        seen: set[int] = set()
        for pid in pids:
            io = self._read_io(pid)
            if io is None:
                continue
            seen.add(pid)
            comm = Procfs.read_comm(pid)

            read_bytes = io.get("read_bytes", 0)
            write_bytes = io.get("write_bytes", 0)
            cancelled = io.get("cancelled_write_bytes", 0)

            signals.extend(
                [
                    Signal(ts_ns, ctx.run_id, self.name, "io.read_bytes", float(read_bytes), "bytes", pid, {"comm": comm}),
                    Signal(ts_ns, ctx.run_id, self.name, "io.write_bytes", float(write_bytes), "bytes", pid, {"comm": comm}),
                    Signal(ts_ns, ctx.run_id, self.name, "io.cancelled_write_bytes", float(cancelled), "bytes", pid, {"comm": comm}),
                ]
            )

            prev_r = self._last_read.get(pid)
            prev_w = self._last_write.get(pid)
            if dt_sec is not None and prev_r is not None:
                signals.append(
                    Signal(ts_ns, ctx.run_id, self.name, "io.read_bps", max(0.0, (read_bytes - prev_r) / dt_sec), "bytes/s", pid, {"comm": comm})
                )
            if dt_sec is not None and prev_w is not None:
                signals.append(
                    Signal(ts_ns, ctx.run_id, self.name, "io.write_bps", max(0.0, (write_bytes - prev_w) / dt_sec), "bytes/s", pid, {"comm": comm})
                )

            self._last_read[pid] = read_bytes
            self._last_write[pid] = write_bytes

        stale = set(self._last_read) - seen
        for pid in stale:
            self._last_read.pop(pid, None)
            self._last_write.pop(pid, None)

        self._last_ts_ns = ts_ns
        return signals

    @staticmethod
    def _read_io(pid: int) -> dict[str, int] | None:
        path = Path(f"/proc/{pid}/io")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, PermissionError, OSError):
            return None

        out: dict[str, int] = {}
        for line in lines:
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            key = key.strip()
            if key not in {"read_bytes", "write_bytes", "cancelled_write_bytes"}:
                continue
            try:
                out[key] = int(raw.strip())
            except ValueError:
                continue
        return out
