from __future__ import annotations

from typing import Dict

from ..model.schema import LINEAGE_SCHEMA_VERSION


def build_lineage(run_id: str) -> Dict[str, object]:
    return {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "run_id": run_id,
        "metrics": [
            {
                "id": "global.wait_comm_exec_idle",
                "name": "Global wait/comm/exec/other ratios",
                "source": [
                    "derived/legacy_stage/global_breakdown.csv",
                    "derived/legacy_stage/classification_rules.md",
                ],
                "formula": "ratio = bucket_us / total_task_us",
                "notes": "bucket definitions follow classification_rules.md",
            },
            {
                "id": "stream.breakdown",
                "name": "Per-stream wait/comm/exec/idle",
                "source": ["derived/legacy_stage/stream_breakdown.csv"],
                "formula": "aggregated by (device_id, stream_id)",
                "notes": "idle_gap_us = span_us - covered_us",
            },
            {
                "id": "causality.event_wait_event_record",
                "name": "EVENT_WAIT -> EVENT_RECORD inferred edges",
                "source": [
                    "derived/legacy_stage/stream_causality_edges.csv",
                    "derived/legacy_stage/stream_causality_meta.json",
                ],
                "formula": "timeline matching with pre/post windows",
                "notes": "heuristic inference, not explicit runtime dependency metadata",
            },
            {
                "id": "micro_loop.hot_stream_motif",
                "name": "Hot stream repeated motif candidates",
                "source": [
                    "derived/legacy_stage/loop_candidates.csv",
                    "derived/legacy_stage/loop_best.json",
                ],
                "formula": "motif mining on hot streams",
                "notes": "coverage_us ranks candidate importance",
            },
            {
                "id": "compressed_loop.stream_queue_trace",
                "name": "Greedy compressed stream trace with exact windows",
                "source": [
                    "derived/loop_analyzer/summary.csv",
                    "derived/loop_analyzer/db*_rank*_dev*_stream*.tree.json",
                    "derived/loop_analyzer/db*_rank*_dev*_stream*.expr.txt",
                ],
                "formula": "greedy tandem-repeat compression over key TASK events by stream",
                "notes": "v0-exact keeps full time windows for every repeat index and nested child node",
            },
            {
                "id": "quality.alignment",
                "name": "Cross-DB time alignment",
                "source": ["msprof_*.db/TASK(startNs,endNs)", "derived/quality_report.json"],
                "formula": "pair_overlap_ratio = overlap / min(span_i, span_j)",
                "notes": "computed directly from TASK windows",
            },
        ],
    }
