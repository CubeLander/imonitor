from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List, Sequence


def _query_one(conn: sqlite3.Connection, sql: str):
    return conn.execute(sql).fetchone()


def _query_values(conn: sqlite3.Connection, sql: str) -> List[int]:
    out: List[int] = []
    for (v,) in conn.execute(sql):
        if v is None:
            continue
        out.append(int(v))
    return sorted(set(out))


def summarize_db_windows(db_paths: Sequence[Path]) -> List[Dict[str, object]]:
    windows: List[Dict[str, object]] = []
    for db in db_paths:
        with sqlite3.connect(str(db)) as conn:
            row = _query_one(conn, "SELECT MIN(startNs), MAX(endNs), COUNT(*) FROM TASK")
            if not row:
                continue
            start_ns = int(row[0] or 0)
            end_ns = int(row[1] or 0)
            task_rows = int(row[2] or 0)
            device_ids = _query_values(conn, "SELECT DISTINCT deviceId FROM TASK")
            global_pids = _query_values(conn, "SELECT DISTINCT globalPid FROM TASK")
        span_ns = max(end_ns - start_ns, 0)
        windows.append(
            {
                "db": str(db),
                "start_ns": start_ns,
                "end_ns": end_ns,
                "span_ns": span_ns,
                "task_rows": task_rows,
                "device_ids": device_ids,
                "global_pids": global_pids,
            }
        )
    return windows


def _overlap_ns(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def build_alignment_summary(windows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    if not windows:
        return {
            "db_count": 0,
            "global_start_ns": 0,
            "global_end_ns": 0,
            "global_span_ns": 0,
            "max_start_delta_ms": 0.0,
            "pair_overlap_ratio_min": 0.0,
            "pair_non_overlap_max_ms": 0.0,
            "db_windows": [],
        }

    starts = [int(w["start_ns"]) for w in windows]
    ends = [int(w["end_ns"]) for w in windows]
    global_start = min(starts)
    global_end = max(ends)
    global_span = max(global_end - global_start, 0)

    pair_overlap_ratio_min = 1.0
    pair_non_overlap_max_ns = 0
    n = len(windows)
    if n == 1:
        pair_overlap_ratio_min = 1.0
        pair_non_overlap_max_ns = 0
    else:
        for i in range(n):
            for j in range(i + 1, n):
                wi = windows[i]
                wj = windows[j]
                si, ei = int(wi["start_ns"]), int(wi["end_ns"])
                sj, ej = int(wj["start_ns"]), int(wj["end_ns"])
                span_i = max(ei - si, 0)
                span_j = max(ej - sj, 0)
                min_span = max(min(span_i, span_j), 1)
                ov = _overlap_ns(si, ei, sj, ej)
                ratio = ov / float(min_span)
                pair_overlap_ratio_min = min(pair_overlap_ratio_min, ratio)
                non_overlap = max(min_span - ov, 0)
                pair_non_overlap_max_ns = max(pair_non_overlap_max_ns, non_overlap)

    db_windows = []
    for w in windows:
        start_ns = int(w["start_ns"])
        span_ns = int(w["span_ns"])
        db_windows.append(
            {
                **w,
                "start_delta_ms": round((start_ns - global_start) / 1e6, 3),
                "span_ms": round(span_ns / 1e6, 3),
            }
        )

    return {
        "db_count": len(windows),
        "global_start_ns": global_start,
        "global_end_ns": global_end,
        "global_span_ns": global_span,
        "global_span_ms": round(global_span / 1e6, 3),
        "max_start_delta_ms": round(max((s - global_start) / 1e6 for s in starts), 3),
        "pair_overlap_ratio_min": pair_overlap_ratio_min,
        "pair_non_overlap_max_ms": round(pair_non_overlap_max_ns / 1e6, 3),
        "db_windows": db_windows,
    }
