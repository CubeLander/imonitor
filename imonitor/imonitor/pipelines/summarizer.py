from __future__ import annotations


def build_summary(run_row: dict[str, object], agg_rows: list[dict[str, object]]) -> dict[str, object]:
    top_cpu = sorted(
        [row for row in agg_rows if row["metric"] == "cpu.util_pct"],
        key=lambda x: float(x["max"]),
        reverse=True,
    )[:5]
    top_mem = sorted(
        [row for row in agg_rows if row["metric"] == "mem.rss_bytes"],
        key=lambda x: float(x["max"]),
        reverse=True,
    )[:5]

    return {
        "run": run_row,
        "top_cpu": top_cpu,
        "top_mem": top_mem,
    }
