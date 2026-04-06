from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .client import RemoteDaemonClient, finish_run, send_logs, send_signals, start_run
from .transcript import TranscriptTailer


class RemoteError(RuntimeError):
    pass


@dataclass(slots=True)
class RemoteClient:
    base_url: str
    timeout_sec: float = 10.0

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self._build_url(path, params)
        req = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RemoteError(f"{exc.code} {exc.reason}: {detail}") from exc
        except URLError as exc:
            raise RemoteError(str(exc.reason)) from exc
        return json.loads(raw)

    def _build_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        base = self.base_url.rstrip("/") + "/"
        url = urljoin(base, path.lstrip("/"))
        if params:
            query = urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
            if query:
                url = f"{url}?{query}"
        return url


def format_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]], max_rows: int | None = None) -> str:
    visible = rows if max_rows is None else rows[:max_rows]
    widths = [len(header) for _, header in columns]
    rendered_rows: list[list[str]] = []
    for row in visible:
        rendered = []
        for idx, (key, _) in enumerate(columns):
            value = row.get(key, "")
            text = _stringify(value)
            rendered.append(text)
            widths[idx] = max(widths[idx], len(text))
        rendered_rows.append(rendered)

    lines = []
    header = "  ".join(header.ljust(widths[idx]) for idx, (_, header) in enumerate(columns))
    lines.append(header)
    lines.append("  ".join("-" * widths[idx] for idx, _ in enumerate(columns)))
    for rendered in rendered_rows:
        lines.append("  ".join(rendered[idx].ljust(widths[idx]) for idx in range(len(columns))))
    return "\n".join(lines)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    text = str(value)
    return text.replace("\r", "\\r").replace("\n", "\\n")


__all__ = [
    "RemoteClient",
    "RemoteDaemonClient",
    "RemoteError",
    "TranscriptTailer",
    "finish_run",
    "format_table",
    "send_logs",
    "send_signals",
    "start_run",
]
