from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, TextIO


@dataclass(frozen=True)
class TimelineSource:
    source_idx: int
    process_key: str
    prof_dir: Path
    json_path: Path
    db_path: Path | None


def discover_timeline_sources(run_dir: Path) -> List[TimelineSource]:
    run_dir = run_dir.resolve()
    sources: List[TimelineSource] = []
    for idx, json_path in enumerate(
        sorted(run_dir.glob("PROF_*/mindstudio_profiler_output/msprof_*.json")),
        start=1,
    ):
        prof_dir = json_path.parents[1]
        dbs = sorted(prof_dir.glob("msprof_*.db"))
        sources.append(
            TimelineSource(
                source_idx=idx,
                process_key=f"proc{idx:02d}",
                prof_dir=prof_dir.resolve(),
                json_path=json_path.resolve(),
                db_path=dbs[0].resolve() if dbs else None,
            )
        )
    return sources


def _iter_json_array(path: Path) -> Iterator[Dict[str, Any]]:
    decoder = json.JSONDecoder()
    chunk_size = 1024 * 1024

    with path.open("r", encoding="utf-8") as f:
        buf = ""
        pos = 0
        eof = False

        def fill() -> bool:
            nonlocal buf, eof
            chunk = f.read(chunk_size)
            if chunk == "":
                eof = True
                return False
            buf += chunk
            return True

        def compact() -> None:
            nonlocal buf, pos
            if pos > chunk_size:
                buf = buf[pos:]
                pos = 0

        while True:
            if pos >= len(buf) and not fill():
                raise ValueError(f"empty JSON trace file: {path}")
            while pos < len(buf) and buf[pos].isspace():
                pos += 1
            if pos < len(buf):
                break

        if buf[pos] != "[":
            # Rare wrapper form; keep the simple path for small/non-MindStudio traces.
            payload = json.loads(buf[pos:] + f.read())
            events = payload.get("traceEvents", []) if isinstance(payload, dict) else payload
            if not isinstance(events, list):
                raise ValueError(f"unsupported trace event JSON format: {path}")
            for ev in events:
                if isinstance(ev, dict):
                    yield ev
            return

        pos += 1
        while True:
            while True:
                if pos >= len(buf):
                    if not fill():
                        raise ValueError(f"unterminated JSON array: {path}")
                    continue
                while pos < len(buf) and (buf[pos].isspace() or buf[pos] == ","):
                    pos += 1
                if pos >= len(buf):
                    continue
                if buf[pos] == "]":
                    return
                break

            while True:
                try:
                    obj, end = decoder.raw_decode(buf, pos)
                    pos = end
                    compact()
                    if isinstance(obj, dict):
                        yield obj
                    break
                except json.JSONDecodeError:
                    if eof:
                        raise
                    fill()


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _scan_trace_source(path: Path) -> Dict[str, Any]:
    event_count = 0
    original_pids: set[int] = set()
    tids_by_pid: Dict[int, set[int]] = {}

    for ev in _iter_json_array(path):
        event_count += 1
        pid = _coerce_int(ev.get("pid"))
        if pid is None:
            continue
        original_pids.add(pid)
        tid = _coerce_int(ev.get("tid"))
        if tid is not None:
            tids_by_pid.setdefault(pid, set()).add(tid)

    return {
        "event_count": event_count,
        "original_pids": sorted(original_pids),
        "tids_by_pid": tids_by_pid,
    }


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _write_trace_event(f: TextIO, ev: Dict[str, Any], *, first: bool) -> bool:
    if not first:
        f.write(",")
    f.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")))
    return False


def build_machine_timeline(
    *,
    run_dir: Path,
    out_dir: Path,
    run_id: str,
) -> Dict[str, Any]:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = discover_timeline_sources(run_dir)
    source_rows: List[Dict[str, Any]] = []
    pid_rows: List[Dict[str, Any]] = []
    trace_path = out_dir / "machine_timeline.perfetto.json"
    meta_path = out_dir / "machine_timeline.meta.json"
    sources_path = out_dir / "timeline_sources.csv"
    pid_map_path = out_dir / "pid_map.csv"
    output_event_count = 0

    first_event = True
    with trace_path.open("w", encoding="utf-8") as trace_f:
        trace_f.write('{"traceEvents":[')

        for source in sources:
            scan = _scan_trace_source(source.json_path)
            original_pids = scan["original_pids"]
            tids_by_pid = scan["tids_by_pid"]
            pid_map = {
                original_pid: source.source_idx * 1_000_000 + local_idx
                for local_idx, original_pid in enumerate(original_pids, start=1)
            }

            source_rows.append(
                {
                    "process_key": source.process_key,
                    "source_idx": source.source_idx,
                    "prof_dir": str(source.prof_dir),
                    "json_path": str(source.json_path),
                    "db_path": str(source.db_path) if source.db_path else "",
                    "event_count": scan["event_count"],
                    "pid_count": len(original_pids),
                }
            )
            for original_pid, new_pid in pid_map.items():
                pid_rows.append(
                    {
                        "process_key": source.process_key,
                        "source_idx": source.source_idx,
                        "original_pid": original_pid,
                        "machine_pid": new_pid,
                    }
                )

            for ev in _iter_json_array(source.json_path):
                out = dict(ev)
                original_pid = out.get("pid")
                original_tid = out.get("tid")
                original_pid_int = _coerce_int(original_pid)
                if original_pid_int is not None:
                    out["pid"] = pid_map.get(original_pid_int, original_pid_int)

                # Flow ids are local to one exported timeline; prefix them before merging.
                if "id" in out:
                    out["id"] = f"{source.process_key}:{out['id']}"

                args = out.get("args")
                if isinstance(args, dict):
                    args = dict(args)
                else:
                    args = {}
                if out.get("ph") == "M" and out.get("name") == "process_name":
                    raw_name = str(args.get("name", "")).strip()
                    args["name"] = (
                        f"{source.process_key} | {raw_name}" if raw_name else source.process_key
                    )
                elif out.get("ph") == "M" and out.get("name") == "process_labels":
                    raw_labels = str(args.get("labels", "")).strip()
                    extra = f"source={source.prof_dir.name}"
                    args["labels"] = f"{raw_labels}; {extra}" if raw_labels else extra
                args["hprofile.process_key"] = source.process_key
                args["hprofile.prof_dir"] = source.prof_dir.name
                if original_pid is not None:
                    args["hprofile.original_pid"] = original_pid
                if original_tid is not None:
                    args["hprofile.original_tid"] = original_tid
                out["args"] = args
                first_event = _write_trace_event(trace_f, out, first=first_event)
                output_event_count += 1

            # Add explicit stream labels. Existing MindStudio output often names processes
            # but leaves stream lanes as numeric tids only.
            for original_pid, tids in sorted(tids_by_pid.items()):
                machine_pid = pid_map.get(original_pid, original_pid)
                for tid in sorted(tids):
                    first_event = _write_trace_event(
                        trace_f,
                        {
                            "name": "thread_name",
                            "ph": "M",
                            "pid": machine_pid,
                            "tid": tid,
                            "args": {
                                "name": f"{source.process_key}/stream{tid}",
                                "hprofile.process_key": source.process_key,
                                "hprofile.prof_dir": source.prof_dir.name,
                                "hprofile.original_tid": tid,
                            },
                        },
                        first=first_event,
                    )
                    output_event_count += 1

        metadata = {
            "tool": "hprofile",
            "kind": "machine-level runtime timeline",
            "run_id": run_id,
            "source_count": len(sources),
            "streaming_merge": True,
        }
        trace_f.write(
            '],"metadata":'
            + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
            + "}\n"
        )

    _write_csv(sources_path, source_rows)
    _write_csv(pid_map_path, pid_rows)

    meta = {
        "run_id": run_id,
        "source_count": len(sources),
        "event_count": output_event_count,
        "trace_file": str(trace_path),
        "sources_file": str(sources_path),
        "pid_map_file": str(pid_map_path),
        "sources": source_rows,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta
