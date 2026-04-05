from __future__ import annotations

from abc import ABC, abstractmethod

from imonitor.core.types import MonitorContext
from imonitor.signals.schema import Signal


class Sensor(ABC):
    name: str

    @abstractmethod
    def sample(self, ctx: MonitorContext, ts_ns: int) -> list[Signal]:
        raise NotImplementedError

    def close(self) -> None:
        return
