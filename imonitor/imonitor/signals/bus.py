from __future__ import annotations

import asyncio

from imonitor.signals.schema import Signal


class SignalBus:
    def __init__(self, maxsize: int = 100_000) -> None:
        self._queue: asyncio.Queue[Signal | None] = asyncio.Queue(maxsize=maxsize)

    async def publish(self, signal: Signal) -> None:
        await self._queue.put(signal)

    async def publish_many(self, signals: list[Signal]) -> None:
        for sig in signals:
            await self._queue.put(sig)

    async def get(self) -> Signal | None:
        return await self._queue.get()

    async def close(self) -> None:
        await self._queue.put(None)
