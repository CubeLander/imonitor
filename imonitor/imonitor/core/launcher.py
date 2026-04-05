from __future__ import annotations

import shlex
import shutil
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path


_PROC = Path("/proc")


@dataclass(slots=True)
class LaunchResult:
    process: subprocess.Popen[bytes]
    transcript_path: Path | None = None
    wrapper: str = "direct"


class ProcessLauncher:
    def start(
        self,
        command: list[str],
        transcript_path: Path | None = None,
        use_script: bool = False,
    ) -> LaunchResult:
        if use_script and transcript_path is not None and shutil.which("script") is not None:
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            transcript_path.touch(exist_ok=True)
            shell_cmd = "exec " + shlex.join(command)
            process = subprocess.Popen(
                ["script", "-qefc", shell_cmd, str(transcript_path)],
                start_new_session=True,
            )
            return LaunchResult(process=process, transcript_path=transcript_path, wrapper="script")

        process = subprocess.Popen(command, start_new_session=True)
        return LaunchResult(process=process)


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
    def read_nspid_chain(pid: int) -> list[int]:
        path = _PROC / str(pid) / "status"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, PermissionError, OSError):
            return []

        for line in lines:
            if not line.startswith("NSpid:"):
                continue
            parts = line.split(":", 1)[1].strip().split()
            out: list[int] = []
            for part in parts:
                try:
                    out.append(int(part))
                except ValueError:
                    continue
            return out
        return []

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
