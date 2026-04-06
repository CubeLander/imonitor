from __future__ import annotations

import asyncio
import time

from imonitor.core.types import MonitorContext
from imonitor.sensors.base import Sensor
from imonitor.signals.bus import SignalBus


class SensorScheduler:
    def __init__(
        self,
        sensors: list[Sensor],
        bus: SignalBus,
        ctx: MonitorContext,
        interval_sec: float,
        stop_event: asyncio.Event,
    ) -> None:
        self.sensors = sensors
        self.bus = bus
        self.ctx = ctx
        self.interval_sec = interval_sec
        self.stop_event = stop_event

    async def run(self) -> None:
        next_tick = time.monotonic()
        while not self.stop_event.is_set():
            ts_ns = time.time_ns()
            for sensor in self.sensors:
                try:
                    signals = sensor.sample(self.ctx, ts_ns)
                except Exception as exc:  # pragma: no cover - best effort collection
                    self.ctx.metadata.setdefault("sensor_errors", []).append(
                        f"{sensor.name}: {exc}"
                    )
                    continue
                if signals:
                    await self.bus.publish_many(signals)

            next_tick += self.interval_sec
            sleep_sec = max(0.0, next_tick - time.monotonic())
            await asyncio.sleep(sleep_sec)

    def close(self) -> None:
        for sensor in self.sensors:
            try:
                sensor.close()
            except Exception:
                pass
