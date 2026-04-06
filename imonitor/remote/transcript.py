from __future__ import annotations

import asyncio
from pathlib import Path

from imonitor.remote.client import RemoteDaemonClient


class TranscriptTailer:
    def __init__(
        self,
        transcript_path: Path,
        client: RemoteDaemonClient,
        stream: str = "stdout",
        poll_interval_sec: float = 0.25,
    ) -> None:
        self.transcript_path = transcript_path
        self.client = client
        self.stream = stream
        self.poll_interval_sec = poll_interval_sec

    async def run(self, stop_event: asyncio.Event) -> None:
        offset = 0
        while True:
            if self.transcript_path.exists():
                try:
                    size = self.transcript_path.stat().st_size
                except OSError:
                    size = offset
                if size > offset:
                    chunk = await asyncio.to_thread(self._read_chunk, offset, size)
                    offset = size
                    if chunk:
                        for line in chunk.splitlines():
                            clean = line.rstrip("\r\n")
                            if clean:
                                self.client.record_log(clean, stream=self.stream)
            if stop_event.is_set():
                if not self.transcript_path.exists():
                    break
                try:
                    size = self.transcript_path.stat().st_size
                except OSError:
                    size = offset
                if size <= offset:
                    break
            await asyncio.sleep(self.poll_interval_sec)

    def _read_chunk(self, start: int, end: int) -> str:
        with self.transcript_path.open("rb") as f:
            f.seek(start)
            data = f.read(max(0, end - start))
        return data.decode("utf-8", errors="replace")
