from __future__ import annotations

import ast
import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List

from ..model.schema import SCHEMA_VERSION


def _to_scalar(value: str):
    if value is None:
        return ""
    v = value.strip()
    if v == "":
        return ""
    if v.lower() in {"true", "false"}:
        return v.lower() == "true"
    try:
        if any(c in v for c in (".", "e", "E")):
            return float(v)
        return int(v)
    except ValueError:
        return v


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path, limit: int | None = None) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    out: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            item = {k: _to_scalar(v or "") for k, v in row.items()}
            out.append(item)
            if limit is not None and i + 1 >= limit:
                break
    return out


def _safe_literal_list(value: object) -> list:
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text.startswith("["):
        return []
    try:
        obj = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return []
    return obj if isinstance(obj, list) else []


def _load_loop_candidates(path: Path, limit: int) -> List[Dict[str, object]]:
    rows = _read_csv(path, limit=limit)
    for r in rows:
        r["motif"] = _safe_literal_list(r.get("motif"))
        r["occ_idx"] = _safe_literal_list(r.get("occ_idx"))
    return rows


def build_unified_profile(
    *,
    run_id: str,
    run_dir: Path,
    generated_at: str,
    legacy_out_dir: Path,
    loop_analyzer_meta: Dict[str, object],
    quality_report: Dict[str, object],
    topn_streams: int,
    topn_edges: int,
    topn_loops: int,
    topn_kernels: int,
) -> Dict[str, object]:
    meta = _read_json(legacy_out_dir / "meta.json", {})
    causality_meta = _read_json(legacy_out_dir / "stream_causality_meta.json", {})
    loop_best = _read_json(legacy_out_dir / "loop_best.json", {})

    global_rows = _read_csv(legacy_out_dir / "global_breakdown.csv", limit=1)
    stream_rows = _read_csv(legacy_out_dir / "stream_breakdown.csv", limit=topn_streams)
    phase_rows = _read_csv(legacy_out_dir / "phase_stream_breakdown.csv", limit=topn_streams)
    edge_rows = _read_csv(legacy_out_dir / "stream_causality_edges.csv", limit=topn_edges)
    task_type_rows = _read_csv(legacy_out_dir / "task_type_breakdown.csv", limit=topn_streams)
    kernel_rows = _read_csv(legacy_out_dir / "top_kernels.csv", limit=topn_kernels)
    loop_rows = _load_loop_candidates(legacy_out_dir / "loop_candidates.csv", limit=topn_loops)
    loop_analyzer_dir = legacy_out_dir.parent / "loop_analyzer"
    compressed_loop_summary = _read_csv(loop_analyzer_dir / "summary.csv", limit=topn_streams)
    compressed_loop_meta = _read_json(loop_analyzer_dir / "meta.json", {})
    if loop_analyzer_meta:
        compressed_loop_meta.update(loop_analyzer_meta)

    rules_text = ""
    rules_path = legacy_out_dir / "classification_rules.md"
    if rules_path.exists():
        rules_text = rules_path.read_text(encoding="utf-8")

    alignment = quality_report.get("alignment", {})
    db_windows = alignment.get("db_windows", []) if isinstance(alignment, dict) else []

    profile = {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "run_dir": str(run_dir.resolve()),
            "generated_at": generated_at,
            "task_count": int(meta.get("task_count", 0) or 0),
            "stream_count": int(meta.get("stream_count", 0) or 0),
            "model_exec_phase_count": int(meta.get("model_exec_phase_count", 0) or 0),
        },
        "sources": {
            "db_count": int(meta.get("db_count", 0) or 0),
            "dbs": meta.get("dbs", []),
            "db_windows": db_windows,
            "legacy_output_dir": str(legacy_out_dir.resolve()),
        },
        "quality": quality_report,
        "timeline": {
            "included": False,
            "mode": "aggregate_only_v0",
            "notes": "timeline event pagination/sampling is not implemented in this bootstrap",
        },
        "streams": {
            "top_streams": stream_rows,
            "task_type_breakdown": task_type_rows,
            "top_kernels": kernel_rows,
        },
        "phases": {
            "phase_stream_rows": phase_rows,
        },
        "causality": {
            "meta": causality_meta,
            "edges": edge_rows,
        },
        "micro_loops": {
            "best": loop_best,
            "candidates": loop_rows,
        },
        "compressed_loops": {
            "meta": compressed_loop_meta,
            "top_streams": compressed_loop_summary,
        },
        "rules": {
            "classification_rules_md": rules_text,
        },
        "summary": {
            "global": global_rows[0] if global_rows else {},
        },
    }
    return profile
