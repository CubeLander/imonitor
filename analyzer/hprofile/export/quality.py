from __future__ import annotations

from pathlib import Path
from typing import Dict, Sequence

from ..model.schema import QUALITY_SCHEMA_VERSION


def _detect_metadata_only_devices(run_dir: Path) -> list[dict]:
    issues: list[dict] = []
    for prof in sorted(run_dir.glob("PROF_*")):
        if not prof.is_dir():
            continue
        for dev in sorted(prof.glob("device_*")):
            if not dev.is_dir():
                continue
            data_dir = dev / "data"
            sqlite_dir = dev / "sqlite"
            has_data = data_dir.exists() and any(data_dir.rglob("*"))
            has_sqlite = sqlite_dir.exists() and any(sqlite_dir.rglob("*.db"))
            if not has_data and not has_sqlite:
                issues.append(
                    {
                        "prof_dir": prof.name,
                        "device_dir": dev.name,
                        "reason": "metadata_only",
                    }
                )
    return issues


def build_quality_report(
    run_dir: Path,
    alignment: Dict[str, object],
    causality_meta: Dict[str, object],
    notes: Sequence[str] | None = None,
) -> Dict[str, object]:
    warnings: list[str] = []

    pair_overlap_ratio_min = float(alignment.get("pair_overlap_ratio_min", 0.0) or 0.0)
    if pair_overlap_ratio_min < 0.95:
        warnings.append(
            f"pair_overlap_ratio_min below 0.95 ({pair_overlap_ratio_min:.4f}); cross-PROF alignment may be weak"
        )

    matched_ratio = float(causality_meta.get("matched_ratio", 0.0) or 0.0)
    if matched_ratio < 0.90:
        warnings.append(
            f"EVENT_WAIT matching ratio below 0.90 ({matched_ratio:.4f}); causality confidence is reduced"
        )

    metadata_only = _detect_metadata_only_devices(run_dir)
    if metadata_only:
        warnings.append(f"metadata-only device dirs detected: {len(metadata_only)}")

    report = {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "run_dir": str(run_dir.resolve()),
        "alignment": alignment,
        "causality_match": {
            "event_wait_total": int(causality_meta.get("event_wait_total", 0) or 0),
            "matched_wait_count": int(causality_meta.get("matched_wait_count", 0) or 0),
            "matched_ratio": matched_ratio,
            "cross_stream_matched_wait_count": int(
                causality_meta.get("cross_stream_matched_wait_count", 0) or 0
            ),
            "cross_stream_ratio_in_matched": float(
                causality_meta.get("cross_stream_ratio_in_matched", 0.0) or 0.0
            ),
            "match_pre_us": float(causality_meta.get("match_pre_us", 0.0) or 0.0),
            "match_post_us": float(causality_meta.get("match_post_us", 0.0) or 0.0),
            "blocking_wait_us_threshold": float(
                causality_meta.get("blocking_wait_us_threshold", 0.0) or 0.0
            ),
        },
        "metadata_only_devices": metadata_only,
        "warnings": warnings,
        "notes": list(notes or []),
    }
    return report
