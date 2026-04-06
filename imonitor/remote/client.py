from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from imonitor.console import emit_log_line


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _post_json(url: str, payload: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read()
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


async def start_run(base_url: str, payload: dict[str, Any], timeout_sec: float = 5.0) -> dict[str, Any]:
    return await asyncio.to_thread(_post_json, f"{_normalize_base_url(base_url)}/api/agent/run/start", payload, timeout_sec)


async def send_signals(
    base_url: str,
    run_id: str,
    batch: list[dict[str, Any]],
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    payload = {"rows": batch}
    return await asyncio.to_thread(
        _post_json,
        f"{_normalize_base_url(base_url)}/api/agent/run/{run_id}/signals",
        payload,
        timeout_sec,
    )


async def send_logs(
    base_url: str,
    run_id: str,
    batch: list[dict[str, Any]],
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    payload = {"chunks": batch}
    return await asyncio.to_thread(
        _post_json,
        f"{_normalize_base_url(base_url)}/api/agent/run/{run_id}/logs",
        payload,
        timeout_sec,
    )


async def finish_run(base_url: str, run_id: str, payload: dict[str, Any], timeout_sec: float = 10.0) -> dict[str, Any]:
    return await asyncio.to_thread(
        _post_json,
        f"{_normalize_base_url(base_url)}/api/agent/run/{run_id}/finish",
        payload,
        timeout_sec,
    )


@dataclass(slots=True)
class RemoteDaemonClient:
    base_url: str
    timeout_sec: float = 5.0
    warn_on_error: bool = False
    _signal_buffer: list[dict[str, Any]] = field(default_factory=list)
    _log_buffer: list[dict[str, Any]] = field(default_factory=list)
    _run_id: str | None = None
    _last_warn_ns: int = 0

    def __post_init__(self) -> None:
        self.base_url = _normalize_base_url(self.base_url)

    def bind_run(self, run_id: str) -> None:
        self._run_id = run_id

    def record_signal(self, row: dict[str, Any]) -> None:
        self._signal_buffer.append(row)

    def record_log(self, text: str, stream: str = "stdout", ts_ns: int | None = None) -> None:
        self._log_buffer.append(
            {
                "ts_ns": ts_ns if ts_ns is not None else time.time_ns(),
                "stream": stream,
                "text": text,
            }
        )

    async def start_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await start_run(self.base_url, payload, timeout_sec=self.timeout_sec)

    async def send_signals(self, batch: list[dict[str, Any]]) -> dict[str, Any]:
        if self._run_id is None:
            raise RuntimeError("remote client is not bound to a run")
        return await send_signals(self.base_url, self._run_id, batch, timeout_sec=self.timeout_sec)

    async def send_logs(self, batch: list[dict[str, Any]]) -> dict[str, Any]:
        if self._run_id is None:
            raise RuntimeError("remote client is not bound to a run")
        return await send_logs(self.base_url, self._run_id, batch, timeout_sec=self.timeout_sec)

    async def finish_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._run_id is None:
            raise RuntimeError("remote client is not bound to a run")
        return await finish_run(self.base_url, self._run_id, payload, timeout_sec=max(self.timeout_sec, 10.0))

    def drain_buffers(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        signal_batch = self._signal_buffer
        log_batch = self._log_buffer
        self._signal_buffer = []
        self._log_buffer = []
        return signal_batch, log_batch

    def requeue_buffers(
        self,
        signal_batch: list[dict[str, Any]],
        log_batch: list[dict[str, Any]],
    ) -> None:
        if signal_batch:
            self._signal_buffer[:0] = signal_batch
        if log_batch:
            self._log_buffer[:0] = log_batch

    async def flush(self) -> None:
        if self._run_id is None:
            return

        signal_batch, log_batch = self.drain_buffers()
        if not signal_batch and not log_batch:
            return

        try:
            if signal_batch:
                await self.send_signals(signal_batch)
            if log_batch:
                await self.send_logs(log_batch)
        except (HTTPError, URLError, OSError, RuntimeError) as exc:
            self.requeue_buffers(signal_batch, log_batch)
            if self.warn_on_error:
                now = time.time_ns()
                if now - self._last_warn_ns > 10_000_000_000:
                    self._last_warn_ns = now
                    emit_log_line(f"[imonitor] remote push failed: {exc}")
