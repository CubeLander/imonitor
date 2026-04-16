#!/usr/bin/env python3
import argparse
import datetime as dt
import json
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _read_int(path: Path):
    try:
        return int(_read_text(path))
    except Exception:
        return None


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _collect_runs(base: Path):
    if not base.exists():
        return []
    runs = [p for p in base.iterdir() if p.is_dir() and p.name != "latest"]
    return sorted(runs, key=lambda p: p.name, reverse=True)


def _vllm_row(run_dir: Path):
    rc = _read_int(run_dir / "exit_code.txt")
    js = _load_json(run_dir / "workload_result.json") or {}
    status = "PASS" if rc == 0 and js.get("status") == "ok" else "FAIL"
    return {
        "run_id": run_dir.name,
        "status": status,
        "rc": rc,
        "model": js.get("model", ""),
        "tp": js.get("tp", ""),
        "pp": js.get("pp", ""),
        "total_seconds": js.get("total_seconds", ""),
        "output_preview": (js.get("output_text") or "")[:80],
        "error_preview": (js.get("error") or "")[:120],
        "path": run_dir,
    }


def _msprof_row(run_dir: Path):
    rc = _read_int(run_dir / "exit_code.txt")
    prof_dirs = _count_lines(run_dir / "prof_dirs.txt")
    key_files = _count_lines(run_dir / "key_files.txt")
    log_text = _read_text(run_dir / "msprof.log")
    profiling_finished = "Profiling finished" in log_text
    status = "PASS" if rc == 0 and prof_dirs > 0 and profiling_finished else "FAIL"
    return {
        "run_id": run_dir.name,
        "status": status,
        "rc": rc,
        "prof_dirs": prof_dirs,
        "key_files": key_files,
        "profiling_finished": profiling_finished,
        "path": run_dir,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate markdown report from ascend smoke outputs")
    parser.add_argument("--ascend-dir", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--report", default="")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    ascend_dir = Path(args.ascend_dir).resolve()
    out_dir = ascend_dir / "out"
    report_path = Path(args.report).resolve() if args.report else out_dir / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    vllm_runs = _collect_runs(out_dir / "vllm_smoke")[: args.limit]
    msprof_runs = _collect_runs(out_dir / "msprof_smoke")[: args.limit]

    vllm_rows = [_vllm_row(p) for p in vllm_runs]
    msprof_rows = [_msprof_row(p) for p in msprof_runs]

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append("# Ascend Smoke Report")
    lines.append("")
    lines.append(f"- Generated at: {now}")
    lines.append(f"- Ascend dir: `{ascend_dir}`")
    lines.append("")

    lines.append("## vLLM 8-NPU Smoke")
    lines.append("")
    if vllm_rows:
        lines.append("| run_id | status | rc | tp | pp | total_seconds | output_preview | error_preview |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in vllm_rows:
            lines.append(
                f"| {r['run_id']} | {r['status']} | {r['rc']} | {r['tp']} | {r['pp']} | {r['total_seconds']} | {r['output_preview'].replace('|', ' ')} | {r['error_preview'].replace('|', ' ')} |"
            )
    else:
        lines.append("No vLLM smoke runs found.")
    lines.append("")

    lines.append("## msprof + vLLM 8-NPU Smoke")
    lines.append("")
    if msprof_rows:
        lines.append("| run_id | status | rc | prof_dirs | key_files | profiling_finished |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in msprof_rows:
            lines.append(
                f"| {r['run_id']} | {r['status']} | {r['rc']} | {r['prof_dirs']} | {r['key_files']} | {r['profiling_finished']} |"
            )
    else:
        lines.append("No msprof smoke runs found.")
    lines.append("")

    lines.append("## Paths")
    lines.append("")
    lines.append(f"- vLLM outputs: `{out_dir / 'vllm_smoke'}`")
    lines.append(f"- msprof outputs: `{out_dir / 'msprof_smoke'}`")
    lines.append("")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
