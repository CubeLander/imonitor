from __future__ import annotations

import subprocess
from collections import defaultdict, deque
from pathlib import Path


_PROC = Path("/proc")


class ProcessLauncher:
    def start(self, command: list[str]) -> subprocess.Popen[bytes]:
        return subprocess.Popen(command, start_new_session=True)


class Procfs:
    @staticmethod
    def pid_exists(pid: int) -> bool:
        return (_PROC / str(pid)).exists()

    @staticmethod
    def read_comm(pid: int) -> str:
        path = _PROC / str(pid) / "comm"
        try:
            return path.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, PermissionError, OSError):
            return ""

    @staticmethod
    def list_descendants(root_pid: int) -> set[int]:
        # Build PPID adjacency table once per sampling tick.
        children: dict[int, list[int]] = defaultdict(list)
        for entry in _PROC.iterdir():
            name = entry.name
            if not name.isdigit():
                continue
            pid = int(name)
            stat_path = entry / "stat"
            try:
                raw = stat_path.read_text(encoding="utf-8")
            except (FileNotFoundError, PermissionError, OSError):
                continue
            ppid = Procfs._parse_ppid_from_stat(raw)
            if ppid is None:
                continue
            children[ppid].append(pid)

        result: set[int] = set()
        q: deque[int] = deque([root_pid])
        while q:
            cur = q.popleft()
            if cur in result:
                continue
            if not Procfs.pid_exists(cur):
                continue
            result.add(cur)
            q.extend(children.get(cur, []))
        return result

    @staticmethod
    def _parse_ppid_from_stat(raw: str) -> int | None:
        # /proc/<pid>/stat format: pid (comm) state ppid ...
        rparen = raw.rfind(")")
        if rparen < 0 or rparen + 2 >= len(raw):
            return None
        remainder = raw[rparen + 2 :].split()
        if len(remainder) < 2:
            return None
        try:
            return int(remainder[1])
        except ValueError:
            return None
