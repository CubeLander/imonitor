from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18180
DEFAULT_SERVICE_NAME = "imonitord.service"


def default_daemon_url() -> str:
    explicit = os.getenv("IMONITOR_DAEMON_URL")
    if explicit:
        return explicit.rstrip("/")
    host = os.getenv("IMONITOR_DAEMON_HOST", DEFAULT_HOST)
    port = int(os.getenv("IMONITOR_DAEMON_PORT", str(DEFAULT_PORT)))
    return f"http://{host}:{port}"


def default_daemon_db_path() -> Path:
    raw = os.getenv("IMONITOR_DAEMON_DB")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".local" / "state" / "imonitor" / "imonitord.sqlite").resolve()


def ensure_daemon_running(base_url: str | None = None, timeout_sec: float = 8.0) -> str:
    url = (base_url or default_daemon_url()).rstrip("/")
    if _is_healthy(url):
        return url

    started_by_systemd = _try_start_systemd_service(DEFAULT_SERVICE_NAME)
    if not started_by_systemd:
        _spawn_local_daemon(url, default_daemon_db_path())

    if _wait_healthy(url, timeout_sec=timeout_sec):
        return url
    raise RuntimeError(f"imonitord did not become ready at {url}")


def _is_healthy(base_url: str, timeout_sec: float = 0.5) -> bool:
    req = Request(f"{base_url.rstrip('/')}/healthz", headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError):
        return False

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return bool(payload.get("ok"))


def _wait_healthy(base_url: str, timeout_sec: float) -> bool:
    deadline = time.monotonic() + max(0.2, timeout_sec)
    while time.monotonic() < deadline:
        if _is_healthy(base_url):
            return True
        time.sleep(0.2)
    return _is_healthy(base_url, timeout_sec=1.0)


def _try_start_systemd_service(service_name: str) -> bool:
    if shutil.which("systemctl") is None:
        return False
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "start", service_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.0,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0


def _spawn_local_daemon(base_url: str, db_path: Path) -> None:
    parsed = urlparse(base_url)
    host = parsed.hostname or DEFAULT_HOST
    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    else:
        port = DEFAULT_PORT

    cmd = [
        sys.executable,
        "-m",
        "imonitor.daemon_cli",
        "--db",
        str(db_path),
        "--host",
        host,
        "--port",
        str(port),
    ]
    env = os.environ.copy()
    env["IMONITOR_DAEMON_DB"] = str(db_path)
    env["IMONITOR_DB"] = str(db_path)
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        env=env,
    )
