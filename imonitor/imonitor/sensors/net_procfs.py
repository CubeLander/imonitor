from __future__ import annotations

from pathlib import Path

from imonitor.core.launcher import Procfs
from imonitor.core.types import MonitorContext
from imonitor.sensors.base import Sensor
from imonitor.signals.schema import Signal


class NetProcfsSensor(Sensor):
    name = "net_procfs"

    def __init__(self) -> None:
        self._last_ts_ns: int | None = None
        self._last_rx_bytes: int | None = None
        self._last_tx_bytes: int | None = None

    def sample(self, ctx: MonitorContext, ts_ns: int) -> list[Signal]:
        pid = ctx.root_pid
        if not Procfs.pid_exists(pid) and ctx.active_pids:
            pid = min(ctx.active_pids)

        totals = self._read_net_dev(pid)
        if totals is None:
            return []

        rx_bytes, tx_bytes = totals
        comm = Procfs.read_comm(pid)
        signals = [
            Signal(ts_ns, ctx.run_id, self.name, "net.rx_bytes", float(rx_bytes), "bytes", pid, {"comm": comm, "scope": "namespace"}),
            Signal(ts_ns, ctx.run_id, self.name, "net.tx_bytes", float(tx_bytes), "bytes", pid, {"comm": comm, "scope": "namespace"}),
        ]

        if self._last_ts_ns is not None:
            dt_sec = max(1e-9, (ts_ns - self._last_ts_ns) / 1e9)
            if self._last_rx_bytes is not None:
                signals.append(
                    Signal(ts_ns, ctx.run_id, self.name, "net.rx_bps", max(0.0, (rx_bytes - self._last_rx_bytes) / dt_sec), "bytes/s", pid, {"comm": comm, "scope": "namespace"})
                )
            if self._last_tx_bytes is not None:
                signals.append(
                    Signal(ts_ns, ctx.run_id, self.name, "net.tx_bps", max(0.0, (tx_bytes - self._last_tx_bytes) / dt_sec), "bytes/s", pid, {"comm": comm, "scope": "namespace"})
                )

        self._last_ts_ns = ts_ns
        self._last_rx_bytes = rx_bytes
        self._last_tx_bytes = tx_bytes
        return signals

    @staticmethod
    def _read_net_dev(pid: int) -> tuple[int, int] | None:
        path = Path(f"/proc/{pid}/net/dev")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, PermissionError, OSError):
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
