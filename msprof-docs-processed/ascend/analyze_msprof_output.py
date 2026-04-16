#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


def _to_float(v: str) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace(',', '')
    if not s or s.upper() == 'N/A':
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    try:
        with path.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({(k or '').strip(): (v or '').strip() for k, v in row.items()})
    except Exception:
        return []
    return rows


def _find_latest_run(base: Path) -> Optional[Path]:
    latest = base / 'latest'
    if latest.exists() and latest.is_symlink():
        target = latest.resolve()
        if target.exists() and target.is_dir():
            return target
    candidates = sorted([p for p in base.iterdir() if p.is_dir() and p.name != 'latest'], reverse=True)
    return candidates[0] if candidates else None


def _parse_env(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip()] = v.strip()
    return out


def _top_items(counter: Dict[str, float], top_n: int = 10) -> List[Tuple[str, float]]:
    return sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:top_n]


def _summarize_op_stat(files: Iterable[Path]) -> Tuple[List[Tuple[str, float]], float]:
    totals: Dict[str, float] = defaultdict(float)
    total_time = 0.0
    for f in files:
        for r in _read_csv_rows(f):
            op_type = r.get('OP Type', 'UNKNOWN') or 'UNKNOWN'
            t = _to_float(r.get('Total Time(us)', ''))
            if t is None:
                continue
            totals[op_type] += t
            total_time += t
    return _top_items(totals, 10), total_time


def _summarize_api(files: Iterable[Path]) -> Tuple[List[Tuple[str, float]], float]:
    totals: Dict[str, float] = defaultdict(float)
    total_time = 0.0
    for f in files:
        for r in _read_csv_rows(f):
            level = r.get('Level', '')
            name = r.get('API Name', 'UNKNOWN') or 'UNKNOWN'
            key = f"{level}:{name}" if level else name
            t = _to_float(r.get('Time(us)', ''))
            if t is None:
                continue
            totals[key] += t
            total_time += t
    return _top_items(totals, 10), total_time


def _summarize_comm(files: Iterable[Path]) -> Tuple[List[Tuple[str, float]], float]:
    totals: Dict[str, float] = defaultdict(float)
    total_time = 0.0
    for f in files:
        for r in _read_csv_rows(f):
            op = r.get('OP Type', 'UNKNOWN') or 'UNKNOWN'
            t = _to_float(r.get('Total Time(us)', ''))
            if t is None:
                continue
            totals[op] += t
            total_time += t
    return _top_items(totals, 10), total_time


def _summarize_task_time(files: Iterable[Path]) -> Tuple[int, float]:
    count = 0
    total_us = 0.0
    for f in files:
        for r in _read_csv_rows(f):
            t = _to_float(r.get('task_time(us)', ''))
            if t is None:
                continue
            count += 1
            total_us += t
    return count, total_us


def _avg_ratio(files: Iterable[Path], cols: List[str]) -> Dict[str, float]:
    sums = {c: 0.0 for c in cols}
    counts = {c: 0 for c in cols}
    for f in files:
        for r in _read_csv_rows(f):
            for c in cols:
                v = _to_float(r.get(c, ''))
                if v is None:
                    continue
                sums[c] += v
                counts[c] += 1
    out: Dict[str, float] = {}
    for c in cols:
        if counts[c] > 0:
            out[c] = sums[c] / counts[c]
    return out


def _avg_l2_hit_rate(files: Iterable[Path]) -> Optional[float]:
    s = 0.0
    c = 0
    for f in files:
        for r in _read_csv_rows(f):
            v = _to_float(r.get('Hit Rate', ''))
            if v is None:
                continue
            s += v
            c += 1
    if c == 0:
        return None
    return s / c


def _max_npu_module_mem(files: Iterable[Path]) -> Dict[str, float]:
    max_by_component: Dict[str, float] = {}
    for f in files:
        for r in _read_csv_rows(f):
            comp = r.get('Component', 'UNKNOWN') or 'UNKNOWN'
            v = _to_float(r.get('Total Reserved(KB)', ''))
            if v is None:
                continue
            if comp not in max_by_component or v > max_by_component[comp]:
                max_by_component[comp] = v
    return dict(sorted(max_by_component.items(), key=lambda kv: kv[1], reverse=True))


def _collect_output_files(run_dir: Path) -> List[Path]:
    return sorted(run_dir.glob('PROF_*/mindstudio_profiler_output/*'))


def _group_by_prefix(files: Iterable[Path]) -> Counter:
    counter = Counter()
    for f in files:
        if f.suffix.lower() not in {'.csv', '.json', '.txt'}:
            continue
        stem = f.stem
        prefix = stem.split('_20')[0] if '_20' in stem else stem
        counter[prefix] += 1
    return counter


def main() -> int:
    parser = argparse.ArgumentParser(description='Analyze msprof output directory and generate markdown summary')
    parser.add_argument('--ascend-dir', default=str(Path(__file__).resolve().parent))
    parser.add_argument('--run-dir', default='')
    parser.add_argument('--out', default='')
    args = parser.parse_args()

    ascend_dir = Path(args.ascend_dir).resolve()
    base = ascend_dir / 'out' / 'msprof_smoke'
    run_dir = Path(args.run_dir).resolve() if args.run_dir else _find_latest_run(base)
    if run_dir is None or not run_dir.exists():
        raise SystemExit('no msprof run dir found')

    output_files = _collect_output_files(run_dir)
    csv_files = [p for p in output_files if p.suffix.lower() == '.csv']

    op_stat_files = [p for p in csv_files if p.name.startswith('op_statistic_')]
    api_files = [p for p in csv_files if p.name.startswith('api_statistic_')]
    comm_files = [p for p in csv_files if p.name.startswith('communication_statistic_')]
    task_files = [p for p in csv_files if p.name.startswith('task_time_')]
    aic_files = [p for p in csv_files if p.name.startswith('ai_core_utilization_')]
    l2_files = [p for p in csv_files if p.name.startswith('l2_cache_')]
    module_mem_files = [p for p in csv_files if p.name.startswith('npu_module_mem_')]

    op_top, op_total = _summarize_op_stat(op_stat_files)
    api_top, api_total = _summarize_api(api_files)
    comm_top, comm_total = _summarize_comm(comm_files)
    task_count, task_total_us = _summarize_task_time(task_files)
    ai_core_avg = _avg_ratio(aic_files, ['mac_ratio', 'scalar_ratio', 'mte1_ratio', 'mte2_ratio', 'fixpipe_ratio'])
    l2_avg = _avg_l2_hit_rate(l2_files)
    max_mem = _max_npu_module_mem(module_mem_files)

    file_counter = _group_by_prefix(output_files)
    meta = _parse_env(run_dir / 'run_meta.env')
    workload_json = {}
    try:
        workload_json = json.loads((run_dir / 'workload_result.json').read_text(encoding='utf-8'))
    except Exception:
        workload_json = {}

    out_path = Path(args.out).resolve() if args.out else (run_dir / 'analysis.md')
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    lines.append('# msprof 结果解析报告')
    lines.append('')
    lines.append(f'- run_dir: `{run_dir}`')
    lines.append(f'- exit_code: `{(run_dir / "exit_code.txt").read_text(encoding="utf-8").strip() if (run_dir / "exit_code.txt").exists() else "N/A"}`')
    if meta:
        lines.append(f"- visible_devices: `{meta.get('visible_devices', 'N/A')}`")
        lines.append(f"- tp/pp: `{meta.get('tp', 'N/A')}/{meta.get('pp', 'N/A')}`")
        lines.append(f"- model: `{meta.get('model', 'N/A')}`")
    if workload_json:
        lines.append(f"- workload_total_seconds: `{workload_json.get('total_seconds', 'N/A')}`")
    lines.append('')

    lines.append('## 产物概览')
    lines.append('')
    lines.append(f'- PROF 目录数: `{len(list(run_dir.glob("PROF_*")))}`')
    lines.append(f'- mindstudio 输出文件数: `{len(output_files)}`')
    lines.append('')
    lines.append('| 文件前缀 | 数量 |')
    lines.append('| --- | --- |')
    for k, v in file_counter.most_common(20):
        lines.append(f'| {k} | {v} |')
    lines.append('')

    lines.append('## Top 算子耗时（op_statistic）')
    lines.append('')
    lines.append(f'- 汇总耗时(us): `{op_total:.3f}`')
    lines.append('')
    lines.append('| OP Type | Total Time(us) | Ratio(%) |')
    lines.append('| --- | --- | --- |')
    for name, t in op_top:
        ratio = (t / op_total * 100.0) if op_total > 0 else 0.0
        lines.append(f'| {name} | {t:.3f} | {ratio:.2f} |')
    lines.append('')

    lines.append('## Top API 耗时（api_statistic）')
    lines.append('')
    lines.append(f'- 汇总耗时(us): `{api_total:.3f}`')
    lines.append('')
    lines.append('| API | Time(us) | Ratio(%) |')
    lines.append('| --- | --- | --- |')
    for name, t in api_top:
        ratio = (t / api_total * 100.0) if api_total > 0 else 0.0
        lines.append(f'| {name} | {t:.3f} | {ratio:.2f} |')
    lines.append('')

    lines.append('## 通信开销（communication_statistic）')
    lines.append('')
    lines.append(f'- 汇总耗时(us): `{comm_total:.3f}`')
    lines.append('')
    lines.append('| Comm OP | Time(us) | Ratio(%) |')
    lines.append('| --- | --- | --- |')
    for name, t in comm_top:
        ratio = (t / comm_total * 100.0) if comm_total > 0 else 0.0
        lines.append(f'| {name} | {t:.3f} | {ratio:.2f} |')
    lines.append('')

    lines.append('## 任务时长概览（task_time）')
    lines.append('')
    lines.append(f'- task 数量: `{task_count}`')
    lines.append(f'- task 总耗时(us): `{task_total_us:.3f}`')
    lines.append('')

    lines.append('## AI Core 利用率均值（ai_core_utilization）')
    lines.append('')
    if ai_core_avg:
        lines.append('| 指标 | 平均值 |')
        lines.append('| --- | --- |')
        for k, v in ai_core_avg.items():
            lines.append(f'| {k} | {v:.4f} |')
    else:
        lines.append('无 AI Core 利用率数据。')
    lines.append('')

    lines.append('## L2 与内存')
    lines.append('')
    lines.append(f"- L2 命中率均值: `{f'{l2_avg:.4f}' if l2_avg is not None else 'N/A'}`")
    lines.append('')
    if max_mem:
        lines.append('| Component | Max Reserved(KB) |')
        lines.append('| --- | --- |')
        for comp, v in list(max_mem.items())[:10]:
            lines.append(f'| {comp} | {v:.3f} |')
    else:
        lines.append('无 npu_module_mem 数据。')
    lines.append('')

    out_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'[analysis] wrote {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
