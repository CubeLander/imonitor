#!/usr/bin/env python3
"""First-version msprof analyzer.

Goals:
1. Normalize TASK timeline from msprof SQLite DB.
2. Report wait/comm/exec/other ratios by stream.
3. Provide optional coarse model-exec phase breakdown.
4. Mine repeated micro-loop candidates from hot streams.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


# Task types that are treated as communication-side execution primitives.
# These are normalized with `_normalize_task_key`.
COMM_TASK_TYPES = {
    "SDMA",
    "RDMA",
    "LOCAL",
    "MEMCPY_ASYNC",
    "MEMCPY",
    "WRITE_VALUE",
    "MEM_WRITE_VALUE",
    "EVENT_RECORD",
    "NOTIFY_RECORD",
    "CAPTURE_RECORD",
}

# Task type substrings that indicate compute-side execution.
# Note: these are overridden by communication-connection reclassification
# in `_load_tasks` when `connection_id in COMMUNICATION_OP`.
EXEC_HINTS = (
    "AI_CORE",
    "AI_VECTOR_CORE",
    "AIVEC",
    "AICORE",
    "KERNEL",
    "MODEL_EXECUTE",
    "MODEL_MAINTAINCE",
    "MODEL_MAINTENANCE",
    "MIX_AIV",
    "MIX_AIC",
)


@dataclass
class TaskEvent:
    start_ns: int
    end_ns: int
    dur_ns: int
    device_id: int
    stream_id: int
    task_id: int
    connection_id: int
    global_task_id: int
    global_pid: int
    task_type: str
    label: str
    category: str
    wait_kind: str = ""
    phase_id: str = "global"
    canon_label: str = ""

    @property
    def dur_us(self) -> float:
        return self.dur_ns / 1000.0


def _task_identity_key(t: TaskEvent) -> Tuple[int, int, int, int, int, int, int, int, str]:
    return (
        t.device_id,
        t.stream_id,
        t.task_id,
        t.start_ns,
        t.end_ns,
        t.connection_id,
        t.global_task_id,
        t.global_pid,
        t.task_type,
    )


def _dedup_tasks(tasks: Sequence[TaskEvent]) -> List[TaskEvent]:
    out: List[TaskEvent] = []
    seen: set[Tuple[int, int, int, int, int, int, int, int, str]] = set()
    for t in tasks:
        key = _task_identity_key(t)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _q(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    idx = int((len(values) - 1) * p)
    return float(sorted(values)[idx])


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _query_one(conn: sqlite3.Connection, sql: str) -> Optional[Tuple]:
    cur = conn.execute(sql)
    return cur.fetchone()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = _query_one(
        conn,
        f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{name}' LIMIT 1",
    )
    return row is not None


def _resolve_default_run_dir(repo_root: Path) -> Optional[Path]:
    latest = (
        repo_root
        / "msprof-docs-processed"
        / "ascend"
        / "out"
        / "msprof_smoke"
        / "latest"
    )
    if latest.exists():
        return latest.resolve()
    return None


def _find_msprof_dbs_with_task(run_dir: Path) -> List[Path]:
    candidates = sorted(run_dir.glob("PROF_*/msprof_*.db"))
    if not candidates:
        raise FileNotFoundError(f"no msprof_*.db under run_dir={run_dir}")

    out: List[Path] = []
    for db in candidates:
        with sqlite3.connect(str(db)) as conn:
            if _table_exists(conn, "TASK"):
                out.append(db.resolve())
    if out:
        return out
    raise RuntimeError(
        f"no database with TASK table under run_dir={run_dir}; checked {len(candidates)} db(s)"
    )


def _normalize_task_type(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).upper().replace("_", " ")


def _normalize_task_key(name: str) -> str:
    s = (name or "").strip().upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _canonical_label(label: str) -> str:
    s = (label or "").strip()
    s = re.sub(r"\d+", "#", s)
    if len(s) > 80:
        s = s[:77] + "..."
    return s


def _classify_task(task_type: str) -> str:
    k = _normalize_task_key(task_type)
    if "WAIT" in k:
        return "wait"
    if k in COMM_TASK_TYPES:
        return "comm"
    if "NOTIFY" in k and "WAIT" not in k:
        return "comm"
    if any(h in k for h in EXEC_HINTS):
        return "exec"
    return "other"


def _load_comm_connection_ids(conn: sqlite3.Connection) -> set[int]:
    if not _table_exists(conn, "COMMUNICATION_OP"):
        return set()
    out: set[int] = set()
    for (cid,) in conn.execute("SELECT DISTINCT connectionId FROM COMMUNICATION_OP"):
        if cid is None:
            continue
        out.add(int(cid))
    return out


def _infer_wait_kind(task: TaskEvent, comm_connection_ids: set[int]) -> str:
    if task.category != "wait":
        return ""
    key = _normalize_task_key(task.task_type)
    if key == "NOTIFY_WAIT":
        return "comm_wait"
    if task.connection_id in comm_connection_ids:
        return "comm_wait"
    if key == "EVENT_WAIT":
        return "sync_wait"
    return "unknown_wait"


def _classification_rules_markdown() -> str:
    return "\n".join(
        [
            "# Event Classification Rules",
            "",
            "This file explains how analyzer maps msprof TASK events into output buckets.",
            "",
            "## Base Category (`category`)",
            "",
            "1. `wait`: normalized `task_type` contains `WAIT`.",
            "2. `comm`: normalized `task_type` in `COMM_TASK_TYPES` (`SDMA`, `RDMA`, `WRITE_VALUE`, ...).",
            "3. `comm`: normalized `task_type` contains `NOTIFY` and not `WAIT`.",
            "4. `exec`: normalized `task_type` contains one of `EXEC_HINTS` (`AI_CORE`, `KERNEL`, ...).",
            "5. `other`: fallback.",
            "",
            "## Wait Subtype (`wait_kind`)",
            "",
            "Applied only when `category == wait`:",
            "",
            "1. `comm_wait`: `task_type == NOTIFY_WAIT`.",
            "2. `comm_wait`: `connection_id` exists in `COMMUNICATION_OP.connectionId`.",
            "3. `sync_wait`: `task_type == EVENT_WAIT` (and not matched as communication).",
            "4. `unknown_wait`: fallback.",
            "",
            "## Communication Connection Override",
            "",
            "If an event is initially classified as `exec`, but its `connection_id`",
            "belongs to `COMMUNICATION_OP`, it is reclassified to `comm`.",
            "",
            "This avoids counting communication-side AI_CORE tasks as compute execution.",
            "",
            "## Idle Gap",
            "",
            "For each bucket (for example per stream):",
            "",
            "- `span_us = max(end_ns) - min(start_ns)`.",
            "- `covered_us` = union length of task intervals (overlap merged).",
            "- `idle_gap_us = span_us - covered_us`.",
            "",
            "`idle_gap_us` is the explicit timeline bubble for this bucket.",
            "",
            "## Cross-Stream Causality (`EVENT_WAIT` -> `EVENT_RECORD`)",
            "",
            "A matched edge means: consumer stream in `EVENT_WAIT` was likely unblocked",
            "by producer stream `EVENT_RECORD`.",
            "",
            "Matching heuristic:",
            "",
            "1. Wait event type is exactly `EVENT_WAIT`.",
            "2. Record event type is `EVENT_RECORD` or `CAPTURE_RECORD`.",
            "3. Candidate record end time is within:",
            "   `[wait.start - pre_window, wait.end + post_window]`.",
            "4. Pick the candidate with minimal `abs(record.end - wait.end)`.",
            "",
            "This is a timeline-based inference, not explicit runtime dependency metadata.",
            "",
        ]
    ) + "\n"


def _task_type_rollup_rows(tasks: Sequence[TaskEvent]) -> List[Dict[str, object]]:
    acc: Dict[Tuple[str, str, str], Dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "total_us": 0.0}
    )
    for t in tasks:
        wait_kind = t.wait_kind if t.category == "wait" else ""
        key = (t.task_type, t.category, wait_kind)
        acc[key]["count"] += 1.0
        acc[key]["total_us"] += t.dur_us

    rows: List[Dict[str, object]] = []
    for (task_type, category, wait_kind), v in acc.items():
        cnt = int(v["count"])
        total_us = float(v["total_us"])
        rows.append(
            {
                "task_type": task_type,
                "category": category,
                "wait_kind": wait_kind,
                "count": cnt,
                "total_us": total_us,
                "avg_us": (total_us / cnt) if cnt else 0.0,
            }
        )
    rows.sort(key=lambda r: float(r["total_us"]), reverse=True)
    return rows


def _load_compute_labels(conn: sqlite3.Connection) -> Dict[int, str]:
    if not _table_exists(conn, "COMPUTE_TASK_INFO"):
        return {}
    sql = """
    SELECT c.globalTaskId,
           COALESCE(sn.value, so.value, '') AS label
      FROM COMPUTE_TASK_INFO c
 LEFT JOIN STRING_IDS sn ON c.name = sn.id
 LEFT JOIN STRING_IDS so ON c.opType = so.id
    """
    out: Dict[int, str] = {}
    for gid, label in conn.execute(sql):
        if gid is None:
            continue
        txt = (label or "").strip()
        if txt:
            out[int(gid)] = txt
    return out


def _load_comm_labels(conn: sqlite3.Connection) -> Dict[int, str]:
    if not _table_exists(conn, "COMMUNICATION_TASK_INFO"):
        return {}
    sql = """
    SELECT c.globalTaskId,
           COALESCE(sn.value, st.value, '') AS label
      FROM COMMUNICATION_TASK_INFO c
 LEFT JOIN STRING_IDS sn ON c.name = sn.id
 LEFT JOIN STRING_IDS st ON c.taskType = st.id
    """
    out: Dict[int, str] = {}
    for gid, label in conn.execute(sql):
        if gid is None:
            continue
        txt = (label or "").strip()
        if txt:
            out[int(gid)] = txt
    return out


def _load_tasks(conn: sqlite3.Connection, comm_connection_ids: set[int]) -> List[TaskEvent]:
    compute_labels = _load_compute_labels(conn)
    comm_labels = _load_comm_labels(conn)
    sql = """
    SELECT t.startNs,
           t.endNs,
           t.endNs - t.startNs AS durNs,
           t.deviceId,
           t.streamId,
           t.taskId,
           t.connectionId,
           t.globalTaskId,
           t.globalPid,
           COALESCE(s.value, 'UNKNOWN') AS taskType
      FROM TASK t
      JOIN STRING_IDS s ON t.taskType = s.id
     WHERE t.endNs > t.startNs
     ORDER BY t.startNs
    """
    rows: List[TaskEvent] = []
    for (
        start_ns,
        end_ns,
        dur_ns,
        device_id,
        stream_id,
        task_id,
        connection_id,
        global_task_id,
        global_pid,
        task_type,
    ) in conn.execute(sql):
        gid = int(global_task_id or -1)
        label = (
            compute_labels.get(gid)
            or comm_labels.get(gid)
            or (task_type or "UNKNOWN").strip()
        )
        cat = _classify_task(task_type or "")
        event = TaskEvent(
            start_ns=int(start_ns),
            end_ns=int(end_ns),
            dur_ns=int(dur_ns),
            device_id=int(device_id),
            stream_id=int(stream_id),
            task_id=int(task_id),
            connection_id=int(connection_id),
            global_task_id=gid,
            global_pid=int(global_pid or -1),
            task_type=(task_type or "UNKNOWN").strip(),
            label=label,
            category=cat,
            canon_label=_canonical_label(label),
        )
        # If an "exec-like" task is attached to a communication connection,
        # treat it as communication-side execution to avoid inflating compute ratio.
        if event.category == "exec" and event.connection_id in comm_connection_ids:
            event.category = "comm"
        event.wait_kind = _infer_wait_kind(event, comm_connection_ids)
        rows.append(event)
    return rows


def _build_model_exec_phases(tasks: Sequence[TaskEvent], merge_gap_us: float) -> List[Tuple[str, int, int]]:
    model_exec = [t for t in tasks if _normalize_task_key(t.task_type) == "MODEL_EXECUTE"]
    if not model_exec:
        return []
    model_exec.sort(key=lambda t: t.start_ns)
    phases: List[Tuple[int, int]] = []
    cur_start = model_exec[0].start_ns
    cur_end = model_exec[0].end_ns
    max_gap_ns = int(merge_gap_us * 1000.0)
    for t in model_exec[1:]:
        if t.start_ns - cur_end <= max_gap_ns:
            if t.end_ns > cur_end:
                cur_end = t.end_ns
            continue
        phases.append((cur_start, cur_end))
        cur_start, cur_end = t.start_ns, t.end_ns
    phases.append((cur_start, cur_end))
    out: List[Tuple[str, int, int]] = []
    for i, (s, e) in enumerate(phases, start=1):
        out.append((f"model_exec_{i:04d}", s, e))
    return out


def _assign_phases(
    tasks: Sequence[TaskEvent],
    model_phases: Sequence[Tuple[str, int, int]],
) -> None:
    if not model_phases:
        for t in tasks:
            t.phase_id = "global"
        return

    starts = [s for _, s, _ in model_phases]
    ids = [pid for pid, _, _ in model_phases]
    ends = [e for _, _, e in model_phases]
    for t in tasks:
        mid = t.start_ns + (t.end_ns - t.start_ns) // 2
        idx = bisect_right(starts, mid) - 1
        if idx >= 0 and mid <= ends[idx]:
            t.phase_id = ids[idx]
        else:
            t.phase_id = "outside_model_exec"


def _merge_intervals_covered_and_span_ns(intervals: Sequence[Tuple[int, int]]) -> Tuple[int, int]:
    if not intervals:
        return 0, 0
    seq = sorted((int(s), int(e)) for s, e in intervals if e > s)
    if not seq:
        return 0, 0
    span_ns = int(seq[-1][1] - seq[0][0])
    covered_ns = 0
    cur_s, cur_e = seq[0]
    for s, e in seq[1:]:
        if s <= cur_e:
            if e > cur_e:
                cur_e = e
            continue
        covered_ns += cur_e - cur_s
        cur_s, cur_e = s, e
    covered_ns += cur_e - cur_s
    return max(0, covered_ns), max(0, span_ns)


def _new_bucket() -> Dict[str, object]:
    return {
        "total_task_us": 0.0,
        "wait_us": 0.0,
        "comm_wait_us": 0.0,
        "sync_wait_us": 0.0,
        "unknown_wait_us": 0.0,
        "comm_us": 0.0,
        "exec_us": 0.0,
        "other_us": 0.0,
        "intervals": [],
    }


def _acc_v2_rows(tasks: Sequence[TaskEvent], key_fields: Iterable[str]) -> List[Dict[str, object]]:
    buckets: Dict[Tuple, Dict[str, object]] = defaultdict(_new_bucket)
    key_fields = list(key_fields)
    for t in tasks:
        key = tuple(getattr(t, f) for f in key_fields)
        b = buckets[key]
        u = t.dur_us
        b["total_task_us"] = float(b["total_task_us"]) + u
        b[f"{t.category}_us"] = float(b[f"{t.category}_us"]) + u
        if t.category == "wait":
            wk = t.wait_kind or "unknown_wait"
            b[f"{wk}_us"] = float(b.get(f"{wk}_us", 0.0)) + u
        intervals: List[Tuple[int, int]] = b["intervals"]  # type: ignore[assignment]
        intervals.append((t.start_ns, t.end_ns))

    rows: List[Dict[str, object]] = []
    for key, agg in buckets.items():
        total_task_us = float(agg["total_task_us"])
        wait_us = float(agg["wait_us"])
        comm_wait_us = float(agg["comm_wait_us"])
        sync_wait_us = float(agg["sync_wait_us"])
        unknown_wait_us = float(agg["unknown_wait_us"])
        comm_us = float(agg["comm_us"])
        exec_us = float(agg["exec_us"])
        other_us = float(agg["other_us"])

        intervals: List[Tuple[int, int]] = agg["intervals"]  # type: ignore[assignment]
        covered_ns, span_ns = _merge_intervals_covered_and_span_ns(intervals)
        covered_us = covered_ns / 1000.0
        span_us = span_ns / 1000.0
        idle_gap_us = max(0.0, span_us - covered_us)

        task_denom = total_task_us if total_task_us > 0 else 1.0
        span_denom = span_us if span_us > 0 else 1.0

        row: Dict[str, object] = {k: v for k, v in zip(key_fields, key)}
        row.update(
            {
                "total_task_us": total_task_us,
                "total_us": total_task_us,  # backward-compat alias
                "span_us": span_us,
                "covered_us": covered_us,
                "idle_gap_us": idle_gap_us,
                "wait_us": wait_us,
                "comm_wait_us": comm_wait_us,
                "sync_wait_us": sync_wait_us,
                "unknown_wait_us": unknown_wait_us,
                "comm_us": comm_us,
                "exec_us": exec_us,
                "other_us": other_us,
                "wait_ratio_task": wait_us / task_denom,
                "comm_ratio_task": comm_us / task_denom,
                "exec_ratio_task": exec_us / task_denom,
                "other_ratio_task": other_us / task_denom,
                "comm_wait_ratio_task": comm_wait_us / task_denom,
                "sync_wait_ratio_task": sync_wait_us / task_denom,
                "unknown_wait_ratio_task": unknown_wait_us / task_denom,
                "wait_ratio_span": wait_us / span_denom,
                "comm_ratio_span": comm_us / span_denom,
                "exec_ratio_span": exec_us / span_denom,
                "other_ratio_span": other_us / span_denom,
                "idle_ratio_span": idle_gap_us / span_denom,
                "comm_wait_ratio_span": comm_wait_us / span_denom,
                "sync_wait_ratio_span": sync_wait_us / span_denom,
                "unknown_wait_ratio_span": unknown_wait_us / span_denom,
                # backward-compat aliases
                "wait_ratio": wait_us / task_denom,
                "comm_ratio": comm_us / task_denom,
                "exec_ratio": exec_us / task_denom,
                "other_ratio": other_us / task_denom,
            }
        )
        rows.append(row)
    rows.sort(key=lambda x: float(x["total_task_us"]), reverse=True)
    return rows


def _top_kernels(tasks: Sequence[TaskEvent], topn: int) -> List[Dict[str, object]]:
    acc: Dict[str, Dict[str, float]] = defaultdict(lambda: {"total_us": 0.0, "count": 0.0})
    for t in tasks:
        if t.category != "exec":
            continue
        key = t.label
        acc[key]["total_us"] += t.dur_us
        acc[key]["count"] += 1.0
    out: List[Dict[str, object]] = []
    for k, v in acc.items():
        cnt = int(v["count"])
        total = float(v["total_us"])
        out.append(
            {
                "label": k,
                "count": cnt,
                "total_us": total,
                "avg_us": (total / cnt) if cnt else 0.0,
            }
        )
    out.sort(key=lambda r: float(r["total_us"]), reverse=True)
    return out[:topn]


def _mine_loops_for_stream(
    stream_events: Sequence[TaskEvent],
    min_len: int,
    max_len: int,
    min_count: int,
    max_occ_per_motif: int,
) -> List[Dict[str, object]]:
    seq = [
        e
        for e in stream_events
        if e.category in {"wait", "comm", "exec"}
        and _normalize_task_key(e.task_type) != "CAPTURE_WAIT"
    ]
    if len(seq) < min_len:
        return []

    motifs: Dict[Tuple[str, ...], Dict[str, object]] = {}
    for n in range(min_len, max_len + 1):
        for i in range(0, len(seq) - n + 1):
            w = seq[i : i + n]
            cats = {x.category for x in w}
            if "exec" not in cats:
                continue
            signature = tuple(x.canon_label for x in w)
            entry = motifs.get(signature)
            if entry is None:
                entry = {
                    "len": n,
                    "count": 0,
                    "sum_cycle_us": 0.0,
                    "occ_idx": [],
                }
                motifs[signature] = entry
            entry["count"] = int(entry["count"]) + 1
            cycle_us = (w[-1].end_ns - w[0].start_ns) / 1000.0
            entry["sum_cycle_us"] = float(entry["sum_cycle_us"]) + cycle_us
            occ_idx: List[int] = entry["occ_idx"]  # type: ignore[assignment]
            if len(occ_idx) < max_occ_per_motif:
                occ_idx.append(i)

    out: List[Dict[str, object]] = []
    for sig, m in motifs.items():
        cnt = int(m["count"])
        if cnt < min_count:
            continue
        avg_cycle = float(m["sum_cycle_us"]) / float(cnt)
        out.append(
            {
                "motif": list(sig),
                "motif_len": int(m["len"]),
                "count": cnt,
                "avg_cycle_us": avg_cycle,
                "coverage_us": avg_cycle * float(cnt),
                "occ_idx": list(m["occ_idx"]),  # type: ignore[arg-type]
            }
        )
    out.sort(key=lambda x: float(x["coverage_us"]), reverse=True)
    return out


def _build_best_loop_detail(
    device_id: int,
    stream_id: int,
    stream_events: Sequence[TaskEvent],
    loop: Dict[str, object],
) -> Dict[str, object]:
    seq = [
        e
        for e in stream_events
        if e.category in {"wait", "comm", "exec"}
        and _normalize_task_key(e.task_type) != "CAPTURE_WAIT"
    ]
    n = int(loop["motif_len"])
    occ_idx = [int(x) for x in loop.get("occ_idx", [])]
    step_durs: List[List[float]] = [[] for _ in range(n)]
    gap_durs: List[List[float]] = [[] for _ in range(max(0, n - 1))]
    step_cat_counter: List[Counter] = [Counter() for _ in range(n)]
    step_wait_kind_counter: List[Counter] = [Counter() for _ in range(n)]
    for i in occ_idx:
        if i < 0 or i + n > len(seq):
            continue
        w = seq[i : i + n]
        for j, ev in enumerate(w):
            step_durs[j].append(ev.dur_us)
            step_cat_counter[j][ev.category] += 1
            if ev.wait_kind:
                step_wait_kind_counter[j][ev.wait_kind] += 1
        for j in range(0, n - 1):
            gap = max(0.0, (w[j + 1].start_ns - w[j].end_ns) / 1000.0)
            gap_durs[j].append(gap)

    steps = []
    for j in range(n):
        vals = step_durs[j]
        dominant_cat = (
            step_cat_counter[j].most_common(1)[0][0]
            if step_cat_counter[j]
            else ""
        )
        dominant_wait_kind = (
            step_wait_kind_counter[j].most_common(1)[0][0]
            if step_wait_kind_counter[j]
            else ""
        )
        steps.append(
            {
                "step": j + 1,
                "label": loop["motif"][j],  # type: ignore[index]
                "category": dominant_cat,
                "wait_kind": dominant_wait_kind,
                "avg_us": (sum(vals) / len(vals)) if vals else 0.0,
                "p50_us": _q(vals, 0.50),
                "p95_us": _q(vals, 0.95),
                "samples": len(vals),
            }
        )
    gaps = []
    for j in range(0, n - 1):
        vals = gap_durs[j]
        gaps.append(
            {
                "from_step": j + 1,
                "to_step": j + 2,
                "avg_us": (sum(vals) / len(vals)) if vals else 0.0,
                "p50_us": _q(vals, 0.50),
                "p95_us": _q(vals, 0.95),
                "samples": len(vals),
            }
        )
    return {
        "device_id": device_id,
        "stream_id": stream_id,
        "motif": loop["motif"],
        "motif_len": n,
        "count": loop["count"],
        "avg_cycle_us": loop["avg_cycle_us"],
        "coverage_us": loop["coverage_us"],
        "steps": steps,
        "gaps": gaps,
    }


def _write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_summary_md(
    out_path: Path,
    db_paths: Sequence[Path],
    tasks: Sequence[TaskEvent],
    global_rows: Sequence[Dict[str, object]],
    stream_rows: Sequence[Dict[str, object]],
    phase_rows: Sequence[Dict[str, object]],
    stream_causality_rows: Sequence[Dict[str, object]],
    stream_causality_meta: Dict[str, object],
    task_type_rows: Sequence[Dict[str, object]],
    kernels: Sequence[Dict[str, object]],
    loops: Sequence[Dict[str, object]],
) -> None:
    total_us = sum(t.dur_us for t in tasks)
    lines: List[str] = []
    lines.append("# msprof Stage Analyzer Summary")
    lines.append("")
    if len(db_paths) == 1:
        lines.append(f"- db: `{db_paths[0]}`")
    else:
        lines.append(f"- db_count: `{len(db_paths)}`")
        for i, p in enumerate(db_paths, start=1):
            lines.append(f"- db[{i}]: `{p}`")
    lines.append(f"- task_count: `{len(tasks)}`")
    lines.append(f"- total_task_time_us: `{total_us:.3f}`")
    lines.append("")

    lines.append("## Global Ratio")
    lines.append("")
    if global_rows:
        g = global_rows[0]
        lines.append(
            f"- wait/comm/exec/other (task ratio): `{g['wait_ratio_task']:.3%}` / `{g['comm_ratio_task']:.3%}` / `{g['exec_ratio_task']:.3%}` / `{g['other_ratio_task']:.3%}`"
        )
        lines.append(
            f"- wait_us/comm_us/exec_us/other_us: `{g['wait_us']:.3f}` / `{g['comm_us']:.3f}` / `{g['exec_us']:.3f}` / `{g['other_us']:.3f}`"
        )
        lines.append(
            f"- wait split (comm_wait/sync_wait/unknown_wait): `{g['comm_wait_us']:.3f}` / `{g['sync_wait_us']:.3f}` / `{g['unknown_wait_us']:.3f}`"
        )
        lines.append(
            f"- wait split ratio (task): `{g['comm_wait_ratio_task']:.3%}` / `{g['sync_wait_ratio_task']:.3%}` / `{g['unknown_wait_ratio_task']:.3%}`"
        )
    lines.append("")

    lines.append("## Classification")
    lines.append("")
    lines.append("- Rules file: `classification_rules.md`")
    lines.append("")
    lines.append("| task_type | category | wait_kind | total_us | count |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in list(task_type_rows)[:20]:
        wk = str(r["wait_kind"]) if r["wait_kind"] else "-"
        lines.append(
            f"| {r['task_type']} | {r['category']} | {wk} | {float(r['total_us']):.3f} | {int(r['count'])} |"
        )
    lines.append("")

    lines.append("## Top Streams")
    lines.append("")
    lines.append(
        "| device_id | stream_id | total_task_us | span_us | idle_ratio(span) | comm_wait_ratio(span) | sync_wait_ratio(span) | comm_ratio(task) | exec_ratio(task) |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in list(stream_rows)[:20]:
        lines.append(
            f"| {r['device_id']} | {r['stream_id']} | {float(r['total_task_us']):.3f} | {float(r['span_us']):.3f} | {float(r['idle_ratio_span']):.2%} | {float(r['comm_wait_ratio_span']):.2%} | {float(r['sync_wait_ratio_span']):.2%} | {float(r['comm_ratio_task']):.2%} | {float(r['exec_ratio_task']):.2%} |"
        )
    lines.append("")

    lines.append("## Stream Causality")
    lines.append("")
    total_wait = int(stream_causality_meta.get("event_wait_total", 0))
    matched_wait = int(stream_causality_meta.get("matched_wait_count", 0))
    cross_wait = int(stream_causality_meta.get("cross_stream_matched_wait_count", 0))
    match_ratio = (matched_wait / total_wait) if total_wait else 0.0
    cross_ratio_total = (cross_wait / total_wait) if total_wait else 0.0
    cross_ratio_matched = (cross_wait / matched_wait) if matched_wait else 0.0
    lines.append(
        f"- EVENT_WAIT matched by EVENT_RECORD: `{matched_wait}/{total_wait}` (`{match_ratio:.2%}`)"
    )
    lines.append(
        f"- cross-stream matches: `{cross_wait}` (`{cross_ratio_total:.2%}` of total, `{cross_ratio_matched:.2%}` of matched)"
    )
    lines.append("- file: `stream_causality_edges.csv`")
    lines.append("")
    if stream_causality_rows:
        lines.append(
            "| producer_device | producer_stream | consumer_device | consumer_stream | wait_count | total_wait_us | consumer_wait_share_us | p95_wait_us | p95_unblock_gap_us |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in list(stream_causality_rows)[:20]:
            lines.append(
                f"| {r['producer_device_id']} | {r['producer_stream_id']} | {r['consumer_device_id']} | {r['consumer_stream_id']} | {int(r['wait_count'])} | {float(r['total_wait_us']):.3f} | {float(r['consumer_wait_share_us']):.2%} | {float(r['p95_wait_us']):.3f} | {float(r['p95_unblock_gap_us']):.3f} |"
            )
    else:
        lines.append("No causality edge inferred from EVENT_WAIT/EVENT_RECORD.")
    lines.append("")

    lines.append("## Top Kernels (Exec)")
    lines.append("")
    lines.append("| label | total_us | count | avg_us |")
    lines.append("| --- | --- | --- | --- |")
    for r in list(kernels)[:20]:
        lines.append(
            f"| {r['label']} | {float(r['total_us']):.3f} | {int(r['count'])} | {float(r['avg_us']):.3f} |"
        )
    lines.append("")

    lines.append("## Loop Candidates")
    lines.append("")
    if loops:
        lines.append("| device_id | stream_id | motif_len | count | avg_cycle_us | coverage_us | motif |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for r in list(loops)[:15]:
            motif = " -> ".join(list(r["motif"])[:6])
            lines.append(
                f"| {r.get('device_id', -1)} | {r['stream_id']} | {r['motif_len']} | {r['count']} | {float(r['avg_cycle_us']):.3f} | {float(r['coverage_us']):.3f} | {motif} |"
            )
    else:
        lines.append("No loop candidate meeting threshold.")
    lines.append("")

    if phase_rows:
        lines.append("## Phase Rows")
        lines.append("")
        lines.append(f"- phase_stream_rows: `{len(phase_rows)}`")
        lines.append("- file: `phase_stream_breakdown.csv`")
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _global_ratio_row(tasks: Sequence[TaskEvent]) -> Dict[str, object]:
    agg = {
        "wait_us": 0.0,
        "comm_wait_us": 0.0,
        "sync_wait_us": 0.0,
        "unknown_wait_us": 0.0,
        "comm_us": 0.0,
        "exec_us": 0.0,
        "other_us": 0.0,
    }
    total = 0.0
    for t in tasks:
        u = t.dur_us
        total += u
        agg[f"{t.category}_us"] += u
        if t.category == "wait":
            wk = t.wait_kind or "unknown_wait"
            agg[f"{wk}_us"] += u
    denom = total or 1.0
    return {
        "phase_id": "global",
        "total_task_us": total,
        "total_us": total,
        "wait_us": agg["wait_us"],
        "comm_wait_us": agg["comm_wait_us"],
        "sync_wait_us": agg["sync_wait_us"],
        "unknown_wait_us": agg["unknown_wait_us"],
        "comm_us": agg["comm_us"],
        "exec_us": agg["exec_us"],
        "other_us": agg["other_us"],
        "comm_wait_ratio_task": agg["comm_wait_us"] / denom,
        "sync_wait_ratio_task": agg["sync_wait_us"] / denom,
        "unknown_wait_ratio_task": agg["unknown_wait_us"] / denom,
        "wait_ratio": agg["wait_us"] / denom,
        "comm_ratio": agg["comm_us"] / denom,
        "exec_ratio": agg["exec_us"] / denom,
        "other_ratio": agg["other_us"] / denom,
        "wait_ratio_task": agg["wait_us"] / denom,
        "comm_ratio_task": agg["comm_us"] / denom,
        "exec_ratio_task": agg["exec_us"] / denom,
        "other_ratio_task": agg["other_us"] / denom,
    }


def _event_stream_causality_rows(
    tasks: Sequence[TaskEvent],
    match_pre_us: float,
    match_post_us: float,
    blocking_wait_us: float,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    event_waits = [
        t for t in tasks if _normalize_task_key(t.task_type) == "EVENT_WAIT"
    ]
    event_records = [
        t
        for t in tasks
        if _normalize_task_key(t.task_type) in {"EVENT_RECORD", "CAPTURE_RECORD"}
    ]
    meta: Dict[str, object] = {
        "event_wait_total": len(event_waits),
        "event_record_total": len(event_records),
        "matched_wait_count": 0,
        "unmatched_wait_count": 0,
        "cross_stream_matched_wait_count": 0,
        "match_pre_us": match_pre_us,
        "match_post_us": match_post_us,
        "blocking_wait_us_threshold": blocking_wait_us,
    }
    if not event_waits or not event_records:
        meta["unmatched_wait_count"] = len(event_waits)
        return [], meta

    records_by_device: Dict[int, List[TaskEvent]] = defaultdict(list)
    for r in event_records:
        records_by_device[r.device_id].append(r)
    for dev in list(records_by_device.keys()):
        records_by_device[dev].sort(key=lambda x: x.end_ns)
    rec_end_ns_by_device: Dict[int, List[int]] = {
        dev: [x.end_ns for x in recs] for dev, recs in records_by_device.items()
    }
    pre_ns = int(match_pre_us * 1000.0)
    post_ns = int(match_post_us * 1000.0)

    edge_wait_vals: Dict[Tuple[int, int, int, int], List[float]] = defaultdict(list)
    edge_unblock_gap_vals: Dict[Tuple[int, int, int, int], List[float]] = defaultdict(list)
    consumer_wait_count: Dict[Tuple[int, int], int] = defaultdict(int)
    consumer_wait_us: Dict[Tuple[int, int], float] = defaultdict(float)

    matched_wait_count = 0
    cross_stream_matched_wait_count = 0
    unmatched_wait_count = 0

    for w in event_waits:
        ckey = (w.device_id, w.stream_id)
        consumer_wait_count[ckey] += 1
        consumer_wait_us[ckey] += w.dur_us

        records = records_by_device.get(w.device_id, [])
        rec_end_ns = rec_end_ns_by_device.get(w.device_id, [])
        left = bisect_left(rec_end_ns, w.start_ns - pre_ns)
        right = bisect_right(rec_end_ns, w.end_ns + post_ns)
        if left >= right:
            unmatched_wait_count += 1
            continue

        # Nearest record end to wait end is the best unblock candidate.
        cand = min(
            records[left:right],
            key=lambda r: (abs(r.end_ns - w.end_ns), abs(r.start_ns - w.start_ns)),
        )
        key = (cand.device_id, cand.stream_id, w.device_id, w.stream_id)  # producer -> consumer
        edge_wait_vals[key].append(w.dur_us)
        edge_unblock_gap_vals[key].append((w.end_ns - cand.end_ns) / 1000.0)
        matched_wait_count += 1
        if cand.device_id != w.device_id or cand.stream_id != w.stream_id:
            cross_stream_matched_wait_count += 1

    rows: List[Dict[str, object]] = []
    for (
        producer_device_id,
        producer_sid,
        consumer_device_id,
        consumer_sid,
    ), waits in edge_wait_vals.items():
        waits_sorted = sorted(waits)
        gaps = sorted(
            edge_unblock_gap_vals[
                (producer_device_id, producer_sid, consumer_device_id, consumer_sid)
            ]
        )
        total_wait_us = float(sum(waits_sorted))
        cnt = len(waits_sorted)
        blocking_vals = [x for x in waits_sorted if x >= blocking_wait_us]
        ckey = (consumer_device_id, consumer_sid)
        rows.append(
            {
                "producer_device_id": producer_device_id,
                "producer_stream_id": producer_sid,
                "consumer_device_id": consumer_device_id,
                "consumer_stream_id": consumer_sid,
                "is_cross_stream": (
                    producer_device_id != consumer_device_id
                    or producer_sid != consumer_sid
                ),
                "wait_count": cnt,
                "total_wait_us": total_wait_us,
                "avg_wait_us": (total_wait_us / cnt) if cnt else 0.0,
                "p50_wait_us": _q(waits_sorted, 0.50),
                "p95_wait_us": _q(waits_sorted, 0.95),
                "blocking_wait_count": len(blocking_vals),
                "blocking_wait_us": float(sum(blocking_vals)),
                "avg_unblock_gap_us": (sum(gaps) / len(gaps)) if gaps else 0.0,
                "p95_unblock_gap_us": _q(gaps, 0.95),
                "consumer_event_wait_count": consumer_wait_count[ckey],
                "consumer_event_wait_us": consumer_wait_us[ckey],
                "consumer_wait_share_count": (
                    cnt / float(consumer_wait_count[ckey])
                    if consumer_wait_count[ckey]
                    else 0.0
                ),
                "consumer_wait_share_us": (
                    total_wait_us / float(consumer_wait_us[ckey])
                    if consumer_wait_us[ckey] > 0
                    else 0.0
                ),
            }
        )
    rows.sort(key=lambda x: float(x["total_wait_us"]), reverse=True)

    meta["matched_wait_count"] = matched_wait_count
    meta["unmatched_wait_count"] = unmatched_wait_count
    meta["cross_stream_matched_wait_count"] = cross_stream_matched_wait_count
    meta["matched_ratio"] = (matched_wait_count / len(event_waits)) if event_waits else 0.0
    meta["cross_stream_ratio_in_matched"] = (
        cross_stream_matched_wait_count / matched_wait_count
        if matched_wait_count
        else 0.0
    )
    return rows, meta


def run(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    run_dir: Optional[Path] = Path(args.run_dir).resolve() if args.run_dir else None
    db_paths: List[Path] = [Path(args.db).resolve()] if args.db else []
    if not db_paths:
        if run_dir is None:
            run_dir = _resolve_default_run_dir(repo_root)
        if run_dir is None:
            raise SystemExit(
                "cannot resolve run_dir automatically; pass --run-dir or --db explicitly"
            )
        db_paths = _find_msprof_dbs_with_task(run_dir)

    tasks: List[TaskEvent] = []
    comm_connection_ids_all: set[int] = set()
    for db_path in db_paths:
        with sqlite3.connect(str(db_path)) as conn:
            comm_connection_ids = _load_comm_connection_ids(conn)
            comm_connection_ids_all |= comm_connection_ids
            tasks.extend(_load_tasks(conn, comm_connection_ids=comm_connection_ids))

    if not args.disable_task_dedup:
        tasks = _dedup_tasks(tasks)

    if not tasks:
        raise SystemExit(f"no valid TASK rows found in db_paths={db_paths}")

    model_phases = _build_model_exec_phases(tasks, merge_gap_us=args.model_exec_merge_gap_us)
    _assign_phases(tasks, model_phases)

    out_dir = Path(args.out_dir).resolve()
    _ensure_dir(out_dir)

    global_only = [_global_ratio_row(tasks)]

    stream_rows = _acc_v2_rows(tasks, ["device_id", "stream_id"])
    phase_stream_rows = _acc_v2_rows(tasks, ["phase_id", "device_id", "stream_id"])
    stream_causality_rows, stream_causality_meta = _event_stream_causality_rows(
        tasks,
        match_pre_us=args.causal_match_pre_us,
        match_post_us=args.causal_match_post_us,
        blocking_wait_us=args.causal_blocking_wait_us,
    )
    task_type_rows = _task_type_rollup_rows(tasks)

    kernels = _top_kernels(tasks, topn=args.top_kernels)

    by_stream: Dict[Tuple[int, int], List[TaskEvent]] = defaultdict(list)
    for t in tasks:
        by_stream[(t.device_id, t.stream_id)].append(t)
    hot_streams = [
        (int(r["device_id"]), int(r["stream_id"]))
        for r in stream_rows[: args.loop_top_streams]
    ]

    loop_rows: List[Dict[str, object]] = []
    best_loop_detail: Optional[Dict[str, object]] = None
    for dev_sid in hot_streams:
        stream_events = by_stream.get(dev_sid, [])
        loops = _mine_loops_for_stream(
            stream_events=stream_events,
            min_len=args.loop_min_len,
            max_len=args.loop_max_len,
            min_count=args.loop_min_count,
            max_occ_per_motif=args.loop_max_occurrences,
        )
        for row in loops[: args.loop_top_per_stream]:
            out = dict(row)
            out["device_id"] = dev_sid[0]
            out["stream_id"] = dev_sid[1]
            loop_rows.append(out)

    loop_rows.sort(key=lambda x: float(x["coverage_us"]), reverse=True)
    if loop_rows:
        best = loop_rows[0]
        best_dev_sid = (int(best["device_id"]), int(best["stream_id"]))
        best_loop_detail = _build_best_loop_detail(
            best_dev_sid[0],
            best_dev_sid[1],
            by_stream[best_dev_sid],
            best,
        )

    # Persist outputs.
    _write_csv(out_dir / "global_breakdown.csv", global_only)
    _write_csv(out_dir / "stream_breakdown.csv", stream_rows)
    _write_csv(out_dir / "phase_stream_breakdown.csv", phase_stream_rows)
    _write_csv(out_dir / "stream_causality_edges.csv", stream_causality_rows)
    _write_csv(out_dir / "task_type_breakdown.csv", task_type_rows)
    _write_csv(out_dir / "top_kernels.csv", kernels)
    _write_csv(out_dir / "loop_candidates.csv", loop_rows)
    (out_dir / "classification_rules.md").write_text(
        _classification_rules_markdown(),
        encoding="utf-8",
    )

    if best_loop_detail is not None:
        (out_dir / "loop_best.json").write_text(
            json.dumps(best_loop_detail, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        (out_dir / "loop_best.json").write_text("{}\n", encoding="utf-8")

    meta = {
        "db_count": len(db_paths),
        "dbs": [str(p) for p in db_paths],
        "task_count": len(tasks),
        "stream_count": len(stream_rows),
        "model_exec_phase_count": len(model_phases),
        "comm_connection_id_count": len(comm_connection_ids_all),
        "task_dedup_enabled": (not args.disable_task_dedup),
        "hot_streams": hot_streams,
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "stream_causality_meta.json").write_text(
        json.dumps(stream_causality_meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    _write_summary_md(
        out_path=out_dir / "summary.md",
        db_paths=db_paths,
        tasks=tasks,
        global_rows=global_only,
        stream_rows=stream_rows,
        phase_rows=phase_stream_rows,
        stream_causality_rows=stream_causality_rows,
        stream_causality_meta=stream_causality_meta,
        task_type_rows=task_type_rows,
        kernels=kernels,
        loops=loop_rows,
    )

    if len(db_paths) == 1:
        print(f"[analyzer] db={db_paths[0]}")
    else:
        print(f"[analyzer] db_count={len(db_paths)}")
        for i, p in enumerate(db_paths, start=1):
            print(f"[analyzer] db[{i}]={p}")
    print(f"[analyzer] out_dir={out_dir}")
    print(f"[analyzer] task_count={len(tasks)} stream_count={len(stream_rows)}")
    if model_phases:
        print(f"[analyzer] model_exec_phase_count={len(model_phases)}")
    if loop_rows:
        best = loop_rows[0]
        print(
            "[analyzer] best_loop "
            f"device={best.get('device_id', -1)} stream={best['stream_id']} len={best['motif_len']} "
            f"count={best['count']} coverage_us={float(best['coverage_us']):.3f}"
        )
    else:
        print("[analyzer] no loop candidate meeting threshold")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze msprof TASK timeline for wait/comm/exec ratios and micro-loop candidates"
    )
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--db", default="")
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parent / "out" / "latest"))
    parser.add_argument("--top-kernels", type=int, default=30)
    parser.add_argument("--model-exec-merge-gap-us", type=float, default=2000.0)
    parser.add_argument("--loop-top-streams", type=int, default=3)
    parser.add_argument("--loop-top-per-stream", type=int, default=10)
    parser.add_argument("--loop-min-len", type=int, default=3)
    parser.add_argument("--loop-max-len", type=int, default=6)
    parser.add_argument("--loop-min-count", type=int, default=6)
    parser.add_argument("--loop-max-occurrences", type=int, default=128)
    parser.add_argument("--causal-match-pre-us", type=float, default=50.0)
    parser.add_argument("--causal-match-post-us", type=float, default=2.0)
    parser.add_argument("--causal-blocking-wait-us", type=float, default=10.0)
    parser.add_argument("--disable-task-dedup", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
