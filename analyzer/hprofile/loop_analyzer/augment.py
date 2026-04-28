from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from .analyzer import StreamEvent, _events_to_nodes, _load_stream_events


@dataclass(frozen=True)
class LoopTreeAugmentConfig:
    top_other_streams: int = 3
    top_streams_by_total_dur: int = 0
    source_notes_path: str | None = None


@dataclass
class _TemplateAgg:
    template_id: str
    node_type: str
    label: str
    category: str
    repeat_count: int
    order_idx: int
    occ_count: int = 0
    total_dur_ns: int = 0
    exec_ns: int = 0
    comm_ns: int = 0
    wait_ns: int = 0
    idle_ns: int = 0
    npu_exec_overlap_ns: int = 0
    dur_samples_ns: List[int] = field(default_factory=list)
    other_stream_counter: Counter[str] = field(default_factory=Counter)
    source_counter: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class _IntervalIndex:
    starts: List[int]
    ends: List[int]

    @staticmethod
    def from_intervals(intervals: Sequence[Tuple[int, int]]) -> "_IntervalIndex":
        merged = _merge_intervals(intervals)
        starts = [s for s, _ in merged]
        ends = [e for _, e in merged]
        return _IntervalIndex(starts=starts, ends=ends)

    def overlap_ns(self, start_ns: int, end_ns: int) -> int:
        if end_ns <= start_ns or not self.starts:
            return 0
        i = bisect_right(self.ends, start_ns)
        total = 0
        n = len(self.starts)
        while i < n and self.starts[i] < end_ns:
            s = self.starts[i]
            e = self.ends[i]
            if e > start_ns:
                total += max(0, min(end_ns, e) - max(start_ns, s))
            i += 1
        return total


@dataclass
class _WalkState:
    atom_events: List[StreamEvent]
    atom_symbols: List[str]
    atom_categories: List[str]
    symbol_to_category: Dict[str, str]
    root: Dict[str, Any]
    macros: Dict[str, Dict[str, Any]]
    cursor: int = 0
    order_counter: int = 0
    template_rows: Dict[str, _TemplateAgg] = field(default_factory=dict)
    instance_rows: List[Dict[str, object]] = field(default_factory=list)
    device_exec_index: _IntervalIndex | None = None
    other_stream_busy: Dict[int, _IntervalIndex] = field(default_factory=dict)
    task_source_notes: Dict[str, str] = field(default_factory=dict)
    node_source_notes: Dict[str, str] = field(default_factory=dict)
    cfg: LoopTreeAugmentConfig = field(default_factory=LoopTreeAugmentConfig)


def _merge_intervals(intervals: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    cleaned = sorted((int(s), int(e)) for s, e in intervals if int(e) > int(s))
    if not cleaned:
        return []
    out: List[Tuple[int, int]] = []
    cur_s, cur_e = cleaned[0]
    for s, e in cleaned[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
            continue
        out.append((cur_s, cur_e))
        cur_s, cur_e = s, e
    out.append((cur_s, cur_e))
    return out


def _node_children(node: Dict[str, Any]) -> List[Tuple[int, Dict[str, Any]]]:
    if str(node.get("type", "")) != "Seq":
        return []
    out: List[Tuple[int, Dict[str, Any]]] = []
    items = node.get("items", [])
    if not isinstance(items, list):
        return out
    for idx, it in enumerate(items, start=1):
        if not isinstance(it, dict):
            continue
        ord_idx = int(it.get("ord", idx))
        child = it.get("node", {})
        if isinstance(child, dict):
            out.append((ord_idx, child))
    return out


def _macro_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    table = payload.get("macro_table")
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(table, dict):
        for name, row in table.items():
            if isinstance(name, str) and isinstance(row, dict):
                tree = row.get("tree")
                if isinstance(tree, dict):
                    out[name] = tree
    if out:
        return out
    defs = payload.get("macro_defs", [])
    if not isinstance(defs, list):
        return out
    for row in defs:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        tree = row.get("tree")
        if isinstance(name, str) and isinstance(tree, dict):
            out[name] = tree
    return out


def _stem_from_tree_v2_path(tree_v2_path: Path) -> str:
    stem = tree_v2_path.name
    if stem.endswith(".tree.v2.json"):
        return stem[: -len(".tree.v2.json")]
    return tree_v2_path.stem


def _normalize_source_text(v: str) -> str:
    s = (v or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _load_source_notes(path: Path | None) -> Tuple[Dict[str, str], Dict[str, str]]:
    if path is None or not path.exists():
        return {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    if not isinstance(payload, dict):
        return {}, {}

    out_task: Dict[str, str] = {}
    out_node: Dict[str, str] = {}
    task_map = payload.get("task_label")
    if isinstance(task_map, dict):
        for k, v in task_map.items():
            if isinstance(k, str) and isinstance(v, str):
                txt = _normalize_source_text(v)
                if txt:
                    out_task[k] = txt
    node_map = payload.get("node")
    if isinstance(node_map, dict):
        for k, v in node_map.items():
            if isinstance(k, str) and isinstance(v, str):
                txt = _normalize_source_text(v)
                if txt:
                    out_node[k] = txt
    return out_task, out_node


def _camel_to_snake(s: str) -> str:
    t = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    t = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", t)
    return t.lower()


def _anchor_to_segments(anchor: str) -> List[str]:
    a = _normalize_source_text(anchor)
    if not a:
        return []
    if not a.startswith("python::"):
        return ["python", a]
    body = a[len("python::") :]
    body = body.replace("::", ".").replace("/", ".")
    segs = [x for x in re.split(r"[.]+", body) if x]
    return ["python"] + segs


def _segments_to_anchor(segments: Sequence[str]) -> str:
    if not segments:
        return "python::unresolved"
    if segments[0] != "python":
        return "python::" + ".".join(str(x) for x in segments)
    if len(segments) == 1:
        return "python::unresolved"
    return "python::" + ".".join(str(x) for x in segments[1:])


def _lcp_segments(paths: Sequence[Sequence[str]]) -> List[str]:
    if not paths:
        return []
    cur = list(paths[0])
    for p in paths[1:]:
        n = min(len(cur), len(p))
        i = 0
        while i < n and cur[i] == p[i]:
            i += 1
        cur = cur[:i]
        if not cur:
            break
    return cur


def _infer_block_source_lca(window_events: Sequence[StreamEvent]) -> str:
    weight_by_anchor: Counter[str] = Counter()
    for ev in window_events:
        anchor = _infer_python_anchor_from_label(
            node_type="Atom",
            category=str(ev.category),
            label=str(ev.label),
        )
        if anchor:
            weight_by_anchor[anchor] += max(1, int(ev.dur_ns))
    if not weight_by_anchor:
        return "python::unresolved"

    seg_paths = [_anchor_to_segments(a) for a in weight_by_anchor.keys()]
    seg_paths = [p for p in seg_paths if p]
    if not seg_paths:
        return "python::unresolved"

    lca = _lcp_segments(seg_paths)
    # Keep block anchor informative; a too-shallow prefix like just `python`
    # is not helpful for source backtracking.
    if len(lca) >= 3:
        return _segments_to_anchor(lca)
    if len(lca) == 2 and lca[1] in {"torch", "vllm", "transformers", "tensor"}:
        return _segments_to_anchor(lca)

    branch_weight: Counter[str] = Counter()
    total = sum(weight_by_anchor.values())
    for anchor, w in weight_by_anchor.items():
        seg = _anchor_to_segments(anchor)
        if len(seg) >= 3:
            branch = ".".join(seg[1:3])
        elif len(seg) >= 2:
            branch = seg[1]
        else:
            branch = "unknown"
        branch_weight[branch] += w
    tops = branch_weight.most_common(2)
    parts = [
        f"{name}:{(100.0 * float(w) / float(total)):.0f}%"
        for name, w in tops
        if total > 0
    ]
    if not parts:
        return "python::mixed"
    return "python::mixed[" + ",".join(parts) + "]"


def _infer_python_anchor_from_label(*, node_type: str, category: str, label: str) -> str:
    lab = (label or "").strip()
    up = lab.upper()
    low = lab.lower()

    if node_type == "MacroRef":
        name = lab[len("MacroRef ") :].strip() if lab.startswith("MacroRef ") else lab
        return f"python::macro::{name}" if name else "python::macro"

    if category == "wait":
        return "python::torch.distributed/stream_wait_or_work_wait"

    if category == "comm":
        if "ALLREDUCE" in up:
            return "python::torch.distributed.all_reduce"
        if "ALLGATHER" in up:
            return "python::torch.distributed.all_gather"
        if "MEMCPY" in up:
            return "python::tensor.copy_or_to_async"
        if "EVENT" in up or "NOTIFY" in up:
            return "python::stream_or_event_sync"
        return "python::torch.distributed.communication"

    if category != "exec":
        return ""

    if "split_qkv_rmsnorm_rope_kernel" in low:
        return "python::vllm.layers.attention.qkv_rope_path"
    if "applyrotaryposemb" in low:
        return "python::vllm.layers.rotary_embedding.forward"
    if "addrmsnormbias" in low or low == "rmsnorm":
        return "python::vllm.layers.layernorm.rmsnorm_path"
    if low == "swiglu":
        return "python::vllm.layers.activation.swiglu"

    m = re.match(r"^(aclnn[A-Za-z0-9]+)", lab)
    if m:
        acl = m.group(1)
        op = acl[len("aclnn") :] if acl.startswith("aclnn") else acl
        if op.startswith(("Mm", "MatMul", "BatchMatMul")):
            return "python::torch.nn.functional.linear_or_torch.matmul"
        if op.startswith("Embedding"):
            return "python::torch.nn.functional.embedding"
        if op.startswith(("ReduceSum", "Sum")):
            return "python::torch.sum"
        if op.startswith(("Amax", "Max")):
            return "python::torch.amax"
        if op.startswith(("Div", "RealDiv")):
            return "python::torch.div"
        if op.startswith(("Mul", "Muls")):
            return "python::torch.mul"
        if op.startswith("Sub"):
            return "python::torch.sub"
        if op.startswith("Exp"):
            return "python::torch.exp"
        if op.startswith("Sin"):
            return "python::torch.sin"
        if op.startswith("Cos"):
            return "python::torch.cos"
        if op.startswith("Cat"):
            return "python::torch.cat"
        if op.startswith("Repeat"):
            return "python::torch.repeat_or_tile"
        if op.startswith(("InplaceCopy", "Contiguous", "InplaceFill", "InplaceZero", "InplaceOne")):
            return "python::tensor.copy_fill_contiguous_path"
        if op.startswith("Dropout"):
            return "python::torch.nn.functional.dropout"
        if op:
            return f"python::torch.ops.aten.{_camel_to_snake(op)}"
        return "python::torch.ops.aten"

    if lab and lab not in {"Seq", "Repeat"}:
        return f"python::custom_kernel::{lab}"
    return ""


def _infer_source_deepest(
    *,
    state: _WalkState,
    template_id: str,
    node_type: str,
    category: str,
    label: str,
    window_events: Sequence[StreamEvent],
) -> str:
    manual_node = _normalize_source_text(state.node_source_notes.get(template_id, ""))
    if manual_node:
        return manual_node
    manual_task = _normalize_source_text(state.task_source_notes.get(label, ""))
    if manual_task:
        return manual_task

    if node_type in {"Seq", "Repeat"}:
        return _infer_block_source_lca(window_events)

    direct = _infer_python_anchor_from_label(node_type=node_type, category=category, label=label)
    if direct:
        return direct

    # Fallback for unknown node types.
    cnt: Counter[str] = Counter()
    for ev in window_events:
        x = _infer_python_anchor_from_label(
            node_type="Atom",
            category=str(ev.category),
            label=str(ev.label),
        )
        if x:
            cnt[x] += max(1, int(ev.dur_ns))
    if cnt:
        return cnt.most_common(1)[0][0]
    return "python::unresolved"


def _count_atoms(
    node: Dict[str, Any],
    macros: Dict[str, Dict[str, Any]],
    memo: Dict[str, int],
    stack: set[str],
) -> int:
    t = str(node.get("type", ""))
    if t == "Atom":
        return 1
    if t == "Seq":
        return sum(_count_atoms(ch, macros, memo, stack) for _, ch in _node_children(node))
    if t == "Repeat":
        cnt = int(node.get("count", 1))
        body = node.get("body", {})
        if not isinstance(body, dict):
            return 0
        return cnt * _count_atoms(body, macros, memo, stack)
    if t == "MacroRef":
        name = str(node.get("name", ""))
        if not name or name not in macros:
            return 0
        if name in stack:
            raise ValueError(f"recursive macro detected: {name}")
        if name in memo:
            return memo[name]
        stack.add(name)
        n = _count_atoms(macros[name], macros, memo, stack)
        stack.remove(name)
        memo[name] = n
        return n
    return 0


def _to_ms(ns: int) -> float:
    return round(ns / 1_000_000.0, 6)


def _p90(values: Sequence[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.9)))
    return int(ordered[idx])


def _p50(values: Sequence[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.5)))
    return int(ordered[idx])


def _cv(values: Sequence[int]) -> float:
    if not values:
        return 0.0
    mean = sum(float(v) for v in values) / float(len(values))
    if mean == 0.0:
        return 0.0
    var = sum((float(v) - mean) ** 2 for v in values) / float(len(values))
    return round(math.sqrt(var) / mean, 6)


def _ratio(n: int, d: int) -> float:
    if d <= 0:
        return 0.0
    return round(float(n) / float(d), 6)


def _window_stats(state: _WalkState, start_idx: int, end_idx: int) -> Dict[str, object]:
    if end_idx <= start_idx or start_idx < 0 or end_idx > len(state.atom_events):
        return {
            "start_ns": 0,
            "end_ns": 0,
            "dur_ns": 0,
            "exec_ns": 0,
            "comm_ns": 0,
            "wait_ns": 0,
            "idle_ns": 0,
            "npu_exec_overlap_ns": 0,
            "npu_util_avg": 0.0,
            "active_other_streams": "",
        }

    events = state.atom_events[start_idx:end_idx]
    start_ns = min(e.start_ns for e in events)
    end_ns = max(e.end_ns for e in events)
    dur_ns = max(0, end_ns - start_ns)
    exec_ns = sum(e.dur_ns for e in events if e.category == "exec")
    comm_ns = sum(e.dur_ns for e in events if e.category == "comm")
    wait_ns = sum(e.dur_ns for e in events if e.category == "wait")
    known_ns = exec_ns + comm_ns + wait_ns
    idle_ns = max(0, dur_ns - known_ns)

    npu_exec_overlap_ns = (
        state.device_exec_index.overlap_ns(start_ns, end_ns) if state.device_exec_index else 0
    )
    npu_util_avg = _ratio(npu_exec_overlap_ns, dur_ns)

    stream_overlap: List[Tuple[int, int]] = []
    for sid, idx in state.other_stream_busy.items():
        ov = idx.overlap_ns(start_ns, end_ns)
        if ov > 0:
            stream_overlap.append((sid, ov))
    stream_overlap.sort(key=lambda x: x[1], reverse=True)
    topk = stream_overlap[: max(1, state.cfg.top_other_streams)]
    active_other_streams = ";".join(f"{sid}:{_ratio(ov, dur_ns)}" for sid, ov in topk) if topk else ""

    return {
        "start_ns": start_ns,
        "end_ns": end_ns,
        "dur_ns": dur_ns,
        "exec_ns": exec_ns,
        "comm_ns": comm_ns,
        "wait_ns": wait_ns,
        "idle_ns": idle_ns,
        "npu_exec_overlap_ns": npu_exec_overlap_ns,
        "npu_util_avg": npu_util_avg,
        "active_other_streams": active_other_streams,
    }


def _bottleneck_tag(exec_ns: int, comm_ns: int, wait_ns: int, idle_ns: int, dur_ns: int) -> str:
    wait_ratio = _ratio(wait_ns, dur_ns)
    comm_ratio = _ratio(comm_ns, dur_ns)
    exec_ratio = _ratio(exec_ns, dur_ns)
    idle_ratio = _ratio(idle_ns, dur_ns)
    if wait_ratio >= 0.35:
        return "WAIT_BOUND"
    if comm_ratio >= 0.4 and exec_ratio < 0.4:
        return "COMM_HEAVY"
    if idle_ratio >= 0.3:
        return "SPARSE_SUBMIT"
    if exec_ratio >= 0.6:
        return "COMPUTE_HEAVY"
    return "MIXED"


def _ensure_template(
    state: _WalkState,
    *,
    template_id: str,
    node_type: str,
    label: str,
    category: str,
    repeat_count: int,
) -> _TemplateAgg:
    row = state.template_rows.get(template_id)
    if row is not None:
        return row
    state.order_counter += 1
    row = _TemplateAgg(
        template_id=template_id,
        node_type=node_type,
        label=label,
        category=category,
        repeat_count=repeat_count,
        order_idx=state.order_counter,
    )
    state.template_rows[template_id] = row
    return row


def _record_instance(
    state: _WalkState,
    *,
    template_id: str,
    node_type: str,
    label: str,
    category: str,
    repeat_count: int,
    start_idx: int,
    end_idx: int,
) -> None:
    stats = _window_stats(state, start_idx, end_idx)
    window_events = state.atom_events[start_idx:end_idx] if end_idx > start_idx else []
    source_deepest = _infer_source_deepest(
        state=state,
        template_id=template_id,
        node_type=node_type,
        category=category,
        label=label,
        window_events=window_events,
    )
    agg = _ensure_template(
        state,
        template_id=template_id,
        node_type=node_type,
        label=label,
        category=category,
        repeat_count=repeat_count,
    )
    agg.occ_count += 1
    agg.total_dur_ns += int(stats["dur_ns"])
    agg.exec_ns += int(stats["exec_ns"])
    agg.comm_ns += int(stats["comm_ns"])
    agg.wait_ns += int(stats["wait_ns"])
    agg.idle_ns += int(stats["idle_ns"])
    agg.npu_exec_overlap_ns += int(stats["npu_exec_overlap_ns"])
    agg.dur_samples_ns.append(int(stats["dur_ns"]))

    aos = str(stats["active_other_streams"])
    if aos:
        for part in aos.split(";"):
            sid = part.split(":")[0].strip()
            if sid:
                agg.other_stream_counter[sid] += 1
    if source_deepest:
        agg.source_counter[source_deepest] += 1

    state.instance_rows.append(
        {
            "template_id": template_id,
            "node_type": node_type,
            "category": category,
            "label": label,
            "occ_idx": agg.occ_count,
            "start_ns": int(stats["start_ns"]),
            "end_ns": int(stats["end_ns"]),
            "dur_ns": int(stats["dur_ns"]),
            "exec_ns": int(stats["exec_ns"]),
            "comm_ns": int(stats["comm_ns"]),
            "wait_ns": int(stats["wait_ns"]),
            "idle_ns": int(stats["idle_ns"]),
            "wait_ratio": _ratio(int(stats["wait_ns"]), int(stats["dur_ns"])),
            "npu_util_avg": float(stats["npu_util_avg"]),
            "active_other_streams": str(stats["active_other_streams"]),
            "start_atom_idx": start_idx,
            "end_atom_idx": end_idx,
            "source_deepest": source_deepest,
        }
    )


def _walk_node(
    node: Dict[str, Any],
    *,
    state: _WalkState,
    template_id: str,
    macro_stack: set[str],
) -> Tuple[int, int]:
    t = str(node.get("type", ""))
    start_idx = state.cursor

    if t == "Atom":
        symbol = str(node.get("symbol", ""))
        if state.cursor >= len(state.atom_events):
            raise ValueError(f"atom cursor out of range at {template_id}")
        expected = symbol
        actual = state.atom_symbols[state.cursor]
        if expected and actual and expected != actual:
            # Keep analysis resilient to small mismatches; consume in-order event.
            pass
        category = str(node.get("category") or state.symbol_to_category.get(actual, "other"))
        label = str(node.get("op_label", actual))
        state.cursor += 1
        _record_instance(
            state,
            template_id=template_id,
            node_type="Atom",
            label=label,
            category=category,
            repeat_count=1,
            start_idx=start_idx,
            end_idx=state.cursor,
        )
        return start_idx, state.cursor

    if t == "Seq":
        for ord_idx, ch in _node_children(node):
            child_id = f"{template_id}[{ord_idx}]"
            _walk_node(ch, state=state, template_id=child_id, macro_stack=macro_stack)
        _record_instance(
            state,
            template_id=template_id,
            node_type="Seq",
            label="Seq",
            category="container",
            repeat_count=1,
            start_idx=start_idx,
            end_idx=state.cursor,
        )
        return start_idx, state.cursor

    if t == "Repeat":
        count = int(node.get("count", 1))
        body = node.get("body", {})
        if isinstance(body, dict):
            for _ in range(count):
                _walk_node(
                    body,
                    state=state,
                    template_id=f"{template_id}.body",
                    macro_stack=macro_stack,
                )
        _record_instance(
            state,
            template_id=template_id,
            node_type="Repeat",
            label=f"Repeat x{count}",
            category="container",
            repeat_count=count,
            start_idx=start_idx,
            end_idx=state.cursor,
        )
        return start_idx, state.cursor

    if t == "MacroRef":
        name = str(node.get("name", ""))
        if name and name in macro_stack:
            raise ValueError(f"recursive macro detected while walking: {name}")
        macro_tree = state.macros.get(name)
        if isinstance(macro_tree, dict):
            macro_stack.add(name)
            _walk_node(
                macro_tree,
                state=state,
                template_id=f"Macro:{name}",
                macro_stack=macro_stack,
            )
            macro_stack.remove(name)
        _record_instance(
            state,
            template_id=template_id,
            node_type="MacroRef",
            label=f"MacroRef {name}",
            category="macro",
            repeat_count=1,
            start_idx=start_idx,
            end_idx=state.cursor,
        )
        return start_idx, state.cursor

    # Unknown node: consume nothing but keep a row for visibility.
    _record_instance(
        state,
        template_id=template_id,
        node_type=t or "Unknown",
        label=t or "Unknown",
        category="other",
        repeat_count=1,
        start_idx=start_idx,
        end_idx=state.cursor,
    )
    return start_idx, state.cursor


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


def _type_detail(row: Dict[str, object]) -> Dict[str, object]:
    node_type = str(row.get("node_type", ""))
    category = str(row.get("category", ""))
    total_dur = int(row.get("total_dur_ns", 0))
    exec_ns = int(row.get("exec_ns", 0))
    comm_ns = int(row.get("comm_ns", 0))
    wait_ns = int(row.get("wait_ns", 0))
    idle_ns = int(row.get("idle_ns", 0))
    overlap_exec = int(row.get("npu_exec_overlap_ns", 0))
    repeat_count = int(row.get("repeat_count", 1))

    if node_type == "Atom" and category == "exec":
        return {
            "kernel_active_ratio": _ratio(exec_ns, total_dur),
            "avg_launch_gap_ns": int(round(idle_ns / max(1, int(row.get("occ_count", 1))))),
        }
    if node_type == "Atom" and category == "comm":
        return {
            "comm_ratio": _ratio(comm_ns, total_dur),
            "overlap_loss_ratio": round(1.0 - _ratio(overlap_exec, total_dur), 6),
        }
    if node_type == "Atom" and category == "wait":
        return {
            "blocked_ns": wait_ns,
            "blocked_ratio": _ratio(wait_ns, total_dur),
            "blocked_by_stream_topk": row.get("top_other_streams", ""),
        }
    if node_type == "Repeat":
        return {
            "amplification_factor": repeat_count,
            "child_time_ns": exec_ns + comm_ns + wait_ns,
            "self_time_ns": idle_ns,
        }
    if node_type in {"Seq", "MacroRef"} or str(category) == "macro":
        return {
            "child_time_ns": exec_ns + comm_ns + wait_ns,
            "self_time_ns": idle_ns,
        }
    return {}


def _core_rows(template_rows: Dict[str, _TemplateAgg]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    ordered = sorted(template_rows.values(), key=lambda r: r.order_idx)
    for r in ordered:
        avg_dur = int(round(r.total_dur_ns / max(1, r.occ_count)))
        p50_dur = _p50(r.dur_samples_ns)
        p90_dur = _p90(r.dur_samples_ns)
        p90_over_p50 = round(float(p90_dur) / float(p50_dur), 6) if p50_dur > 0 else 0.0
        top_other = ",".join(k for k, _ in r.other_stream_counter.most_common(3))
        source_deepest = r.source_counter.most_common(1)[0][0] if r.source_counter else ""
        tag = _bottleneck_tag(r.exec_ns, r.comm_ns, r.wait_ns, r.idle_ns, r.total_dur_ns)
        rows.append(
            {
                "template_id": r.template_id,
                "node_type": r.node_type,
                "category": r.category,
                "label": r.label,
                "repeat_count": r.repeat_count,
                "occ_count": r.occ_count,
                "total_dur_ns": r.total_dur_ns,
                "avg_dur_ns": avg_dur,
                "p50_dur_ns": p50_dur,
                "p90_dur_ns": p90_dur,
                "p90_over_p50": p90_over_p50,
                "dur_cv": _cv(r.dur_samples_ns),
                "exec_ns": r.exec_ns,
                "comm_ns": r.comm_ns,
                "wait_ns": r.wait_ns,
                "idle_ns": r.idle_ns,
                "wait_ratio": _ratio(r.wait_ns, r.total_dur_ns),
                "npu_util_avg": _ratio(r.npu_exec_overlap_ns, r.total_dur_ns),
                "top_other_streams": top_other,
                "bottleneck_tag": tag,
                "npu_exec_overlap_ns": r.npu_exec_overlap_ns,
                "source_deepest": source_deepest,
            }
        )
    return rows


def _key_detail_for_row(row: Dict[str, object]) -> str:
    detail = _type_detail(row)
    node_type = str(row.get("node_type", ""))
    category = str(row.get("category", ""))
    if node_type == "Atom" and category == "exec":
        filtered: Dict[str, object] = {}
        launch_gap = int(detail.get("avg_launch_gap_ns", 0))
        if launch_gap > 0:
            filtered["avg_launch_gap_ns"] = launch_gap
        kernel_active_ratio = float(detail.get("kernel_active_ratio", 1.0))
        if abs(kernel_active_ratio - 1.0) > 1e-9:
            filtered["kernel_active_ratio"] = kernel_active_ratio
        detail = filtered
    if not detail:
        return ""
    parts = []
    for k, v in detail.items():
        parts.append(f"{k}={v}")
    return "; ".join(parts)


def _display_npu_util_pct(row: Dict[str, object]) -> str:
    if str(row.get("node_type", "")) == "Atom" and str(row.get("category", "")) == "exec":
        return "-"
    return f"{100.0 * float(row.get('npu_util_avg', 0.0)):.2f}"


def _display_bottleneck_tag(row: Dict[str, object]) -> str:
    if str(row.get("node_type", "")) == "Atom" and str(row.get("category", "")) == "exec":
        return "-"
    return str(row.get("bottleneck_tag", ""))


def _display_node_type(row: Dict[str, object]) -> str:
    nt = str(row.get("node_type", ""))
    if nt in {"Seq", "Repeat"}:
        return "Block"
    return nt


def _md_cell(v: object) -> str:
    return str(v).replace("|", "\\|")


_TEMPLATE_SEG_RE = re.compile(r"([A-Za-z:]+)|\[(\d+)\]")


def _template_depth(template_id: str) -> int:
    return template_id.count("[") + template_id.count(".body")


def _template_sort_key(template_id: str) -> Tuple:
    key: List[Tuple[int, object]] = []
    for seg in str(template_id).split("."):
        for m in _TEMPLATE_SEG_RE.finditer(seg):
            name = m.group(1)
            if name is not None:
                rank = 3
                if name == "Root":
                    rank = 0
                elif name.startswith("Macro:"):
                    rank = 1
                elif name == "body":
                    rank = 2
                key.append((0, rank, name))
                continue
            idx = m.group(2)
            if idx is not None:
                key.append((1, int(idx)))
    return tuple(key)


def _macro_name_from_label(label: str) -> str:
    if not label.startswith("MacroRef "):
        return ""
    return label[len("MacroRef ") :].strip()


def _macro_sort_key(name: str) -> Tuple[int, str]:
    if name.startswith("M") and name[1:].isdigit():
        return (int(name[1:]), name)
    return (10**9, name)


def _display_common_cells(row: Dict[str, object]) -> Dict[str, object]:
    return {
        "occ": int(row.get("occ_count", 0)),
        "avg": _to_ms(int(row.get("avg_dur_ns", 0))),
        "p50": _to_ms(int(row.get("p50_dur_ns", 0))),
        "p90": _to_ms(int(row.get("p90_dur_ns", 0))),
        "p90p50": float(row.get("p90_over_p50", 0.0)),
        "cv": float(row.get("dur_cv", 0.0)),
        "wait": 100.0 * float(row.get("wait_ratio", 0.0)),
        "util": _display_npu_util_pct(row),
        "tag": _display_bottleneck_tag(row),
        "detail": _key_detail_for_row(row),
        "source": str(row.get("source_deepest", "")),
    }


def _build_macro_views(
    *,
    ordered_rows: Sequence[Dict[str, object]],
    macro_rows: Sequence[Dict[str, object]],
) -> Tuple[List[Dict[str, object]], Dict[str, List[Dict[str, object]]]]:
    macro_ref_callsites: Dict[str, set[str]] = {}
    macro_ref_call_count: Dict[str, int] = {}
    for r in ordered_rows:
        if str(r.get("node_type", "")) != "MacroRef":
            continue
        name = _macro_name_from_label(str(r.get("label", "")))
        if not name:
            continue
        macro_ref_callsites.setdefault(name, set()).add(str(r.get("template_id", "")))
        macro_ref_call_count[name] = macro_ref_call_count.get(name, 0) + int(r.get("occ_count", 0))

    macro_roots: Dict[str, Dict[str, object]] = {}
    for r in macro_rows:
        tid = str(r.get("template_id", ""))
        if not tid.startswith("Macro:"):
            continue
        name = tid[len("Macro:") :]
        if "[" in name or "." in name:
            continue
        macro_roots[name] = r

    summary_rows: List[Dict[str, object]] = []
    step_rows_by_macro: Dict[str, List[Dict[str, object]]] = {}
    for name in sorted(macro_roots.keys(), key=_macro_sort_key):
        root_row = macro_roots[name]
        root_cells = _display_common_cells(root_row)
        callsites = len(macro_ref_callsites.get(name, set()))
        call_count = int(root_row.get("occ_count", 0))
        if call_count <= 0:
            call_count = int(macro_ref_call_count.get(name, 0))
        summary_rows.append(
            {
                "macro": name,
                "call_count": call_count,
                "callsites": callsites,
                "avg_ms": float(root_cells["avg"]),
                "p50_ms": float(root_cells["p50"]),
                "p90_ms": float(root_cells["p90"]),
                "p90_over_p50": float(root_cells["p90p50"]),
                "cv": float(root_cells["cv"]),
                "wait_pct": float(root_cells["wait"]),
                "npu_util_pct": str(root_cells["util"]),
                "tag": str(root_cells["tag"]),
                "source_deepest": str(root_cells["source"]),
                "template_id": str(root_row.get("template_id", "")),
            }
        )

        root_tid = f"Macro:{name}"
        block_rows = [
            r
            for r in macro_rows
            if str(r.get("template_id", "")) == root_tid
            or str(r.get("template_id", "")).startswith(root_tid + "[")
            or str(r.get("template_id", "")).startswith(root_tid + ".")
        ]
        block_rows = sorted(block_rows, key=lambda r: _template_sort_key(str(r.get("template_id", ""))))

        base_depth = _template_depth(root_tid)
        step_rows: List[Dict[str, object]] = []
        for r in block_rows:
            tid = str(r.get("template_id", ""))
            local_depth = max(0, _template_depth(tid) - base_depth)
            step = "<macro>" if tid == root_tid else tid[len(root_tid) :].lstrip(".")
            c = _display_common_cells(r)
            step_rows.append(
                {
                    "macro": name,
                    "indent": local_depth,
                    "step": step,
                    "template_id": tid,
                    "task_label": str(r.get("label", "")),
                    "node_type": str(r.get("node_type", "")),
                    "category": str(r.get("category", "")),
                    "occ": int(c["occ"]),
                    "avg_ms": float(c["avg"]),
                    "p50_ms": float(c["p50"]),
                    "p90_ms": float(c["p90"]),
                    "p90_over_p50": float(c["p90p50"]),
                    "cv": float(c["cv"]),
                    "wait_pct": float(c["wait"]),
                    "npu_util_pct": str(c["util"]),
                    "tag": str(c["tag"]),
                    "key_detail": str(c["detail"]),
                    "source_deepest": str(c["source"]),
                }
            )
        step_rows_by_macro[name] = step_rows

    return summary_rows, step_rows_by_macro


def _build_augmented_md(
    *,
    db_path: Path,
    device_id: int,
    stream_id: int,
    atom_count: int,
    core_rows: Sequence[Dict[str, object]],
) -> str:
    ordered_rows = sorted(core_rows, key=lambda r: _template_sort_key(str(r.get("template_id", ""))))
    root_rows = [r for r in ordered_rows if str(r.get("template_id", "")).startswith("Root")]
    macro_rows = [r for r in ordered_rows if str(r.get("template_id", "")).startswith("Macro:")]
    macro_summary_rows, step_rows_by_macro = _build_macro_views(
        ordered_rows=ordered_rows,
        macro_rows=macro_rows,
    )

    lines: List[str] = []
    lines.append("# Loop Tree Augmented Report")
    lines.append("")
    lines.append(f"- db: `{db_path}`")
    lines.append(f"- device_id: `{device_id}`")
    lines.append(f"- stream_id: `{stream_id}`")
    lines.append(f"- atoms_used: `{atom_count}`")
    lines.append("")
    lines.append("## Root Flow Metrics")
    lines.append("")
    lines.append(f"- rows_shown: `{len(root_rows)}` (full root rows)")
    lines.append("- full_root_and_macro_rows: `*.node_perf_core.csv`")
    lines.append("")
    lines.append("| indent | node | task_label | type | category | occ | avg_ms | p50_ms | p90_ms | p90/p50 | cv | wait% | npu_util% | tag | key_detail | source_deepest |")
    lines.append("| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |")
    for r in root_rows:
        template_id = str(r.get("template_id", ""))
        depth = _template_depth(template_id)
        c = _display_common_cells(r)
        lines.append(
            "| {indent} | {node} | {label} | {typ} | {cat} | {occ} | {avg:.3f} | {p50:.3f} | {p90:.3f} | {p90p50:.3f} | {cv:.3f} | {wait:.2f} | {util} | {tag} | {detail} | {source} |".format(
                indent=depth,
                node=_md_cell(template_id),
                label=_md_cell(str(r.get("label", ""))),
                typ=_md_cell(_display_node_type(r)),
                cat=_md_cell(str(r.get("category", ""))),
                occ=c["occ"],
                avg=c["avg"],
                p50=c["p50"],
                p90=c["p90"],
                p90p50=c["p90p50"],
                cv=c["cv"],
                wait=c["wait"],
                util=_md_cell(c["util"]),
                tag=_md_cell(c["tag"]),
                detail=_md_cell(c["detail"]),
                source=_md_cell(c["source"]),
            )
        )
    lines.append("")

    lines.append("## Macro Summary (Averaged Across Calls)")
    lines.append("")
    lines.append("| macro | call_count | callsites | avg_ms | p50_ms | p90_ms | p90/p50 | cv | wait% | npu_util% | tag | source_deepest |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |")
    for row in macro_summary_rows:
        lines.append(
            "| {name} | {call_count} | {callsites} | {avg:.3f} | {p50:.3f} | {p90:.3f} | {p90p50:.3f} | {cv:.3f} | {wait:.2f} | {util} | {tag} | {source} |".format(
                name=_md_cell(str(row.get("macro", ""))),
                call_count=int(row.get("call_count", 0)),
                callsites=int(row.get("callsites", 0)),
                avg=float(row.get("avg_ms", 0.0)),
                p50=float(row.get("p50_ms", 0.0)),
                p90=float(row.get("p90_ms", 0.0)),
                p90p50=float(row.get("p90_over_p50", 0.0)),
                cv=float(row.get("cv", 0.0)),
                wait=float(row.get("wait_pct", 0.0)),
                util=_md_cell(str(row.get("npu_util_pct", "0.00"))),
                tag=_md_cell(str(row.get("tag", ""))),
                source=_md_cell(str(row.get("source_deepest", ""))),
            )
        )
    if not macro_summary_rows:
        lines.append("| - | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.00 | 0.00 | - | - |")
    lines.append("")

    lines.append("## Macro Blocks (Vertical Step Aggregation)")
    lines.append("")
    summary_by_macro = {str(r.get("macro", "")): r for r in macro_summary_rows}
    for name in sorted(step_rows_by_macro.keys(), key=_macro_sort_key):
        s = summary_by_macro.get(name, {})
        call_count = int(s.get("call_count", 0))
        callsites = int(s.get("callsites", 0))
        lines.append(f"### Macro {name} (call_count={call_count}, callsites={callsites})")
        lines.append("")
        lines.append("| indent | step | task_label | type | category | occ | avg_ms | p50_ms | p90_ms | p90/p50 | cv | wait% | npu_util% | tag | key_detail | source_deepest |")
        lines.append("| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |")
        for r in step_rows_by_macro[name]:
            lines.append(
                "| {indent} | {step} | {label} | {typ} | {cat} | {occ} | {avg:.3f} | {p50:.3f} | {p90:.3f} | {p90p50:.3f} | {cv:.3f} | {wait:.2f} | {util} | {tag} | {detail} | {source} |".format(
                    indent=int(r.get("indent", 0)),
                    step=_md_cell(str(r.get("step", ""))),
                    label=_md_cell(str(r.get("task_label", ""))),
                    typ=_md_cell(_display_node_type(r)),
                    cat=_md_cell(str(r.get("category", ""))),
                    occ=int(r.get("occ", 0)),
                    avg=float(r.get("avg_ms", 0.0)),
                    p50=float(r.get("p50_ms", 0.0)),
                    p90=float(r.get("p90_ms", 0.0)),
                    p90p50=float(r.get("p90_over_p50", 0.0)),
                    cv=float(r.get("cv", 0.0)),
                    wait=float(r.get("wait_pct", 0.0)),
                    util=_md_cell(str(r.get("npu_util_pct", "0.00"))),
                    tag=_md_cell(str(r.get("tag", ""))),
                    detail=_md_cell(str(r.get("key_detail", ""))),
                    source=_md_cell(str(r.get("source_deepest", ""))),
                )
            )
        lines.append("")

    return "\n".join(lines)


def _build_interval_indices(
    *,
    events_by_stream: Dict[Tuple[int, int], List[StreamEvent]],
    device_id: int,
    stream_id: int,
) -> Tuple[_IntervalIndex, Dict[int, _IntervalIndex]]:
    exec_intervals: List[Tuple[int, int]] = []
    other_stream_busy: Dict[int, List[Tuple[int, int]]] = {}

    for (dev, sid), events in events_by_stream.items():
        if dev != device_id:
            continue
        busy = [(e.start_ns, e.end_ns) for e in events if e.end_ns > e.start_ns]
        if sid != stream_id and busy:
            other_stream_busy[sid] = busy
        exec_intervals.extend((e.start_ns, e.end_ns) for e in events if e.category == "exec" and e.end_ns > e.start_ns)

    exec_index = _IntervalIndex.from_intervals(exec_intervals)
    other_busy_index = {sid: _IntervalIndex.from_intervals(iv) for sid, iv in other_stream_busy.items()}
    return exec_index, other_busy_index


def augment_one_tree(
    *,
    tree_v2_path: Path,
    out_dir: Path | None = None,
    config: LoopTreeAugmentConfig | None = None,
) -> Dict[str, object]:
    cfg = config or LoopTreeAugmentConfig()
    tree_v2_path = tree_v2_path.resolve()
    stem = _stem_from_tree_v2_path(tree_v2_path)
    payload = json.loads(tree_v2_path.read_text(encoding="utf-8"))
    root = payload.get("root", {})
    if not isinstance(root, dict):
        raise ValueError(f"invalid root in {tree_v2_path}")

    db_path = Path(str(payload.get("db", ""))).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"db not found: {db_path}")
    device_id = int(payload.get("device_id", -1))
    stream_id = int(payload.get("stream_id", -1))
    if device_id < 0 or stream_id < 0:
        raise ValueError(f"invalid device/stream in {tree_v2_path}")

    source_notes_path: Path | None = None
    if cfg.source_notes_path:
        source_notes_path = Path(cfg.source_notes_path).expanduser().resolve()
    else:
        default_notes_path = tree_v2_path.parent / f"{stem}.source_notes.json"
        if default_notes_path.exists():
            source_notes_path = default_notes_path
    task_source_notes, node_source_notes = _load_source_notes(source_notes_path)

    macros = _macro_map(payload)
    atom_count = _count_atoms(root, macros, memo={}, stack=set())

    events_by_stream = _load_stream_events(db_path)
    stream_events = list(events_by_stream.get((device_id, stream_id), []))
    if not stream_events:
        raise ValueError(f"target stream not found in db: dev={device_id}, stream={stream_id}")
    used_events = list(stream_events[:atom_count])

    nodes, _ = _events_to_nodes(used_events)
    atom_symbols = [n.symbol for n in nodes]
    if len(atom_symbols) != atom_count:
        raise ValueError(
            f"atom count mismatch in {tree_v2_path}: tree={atom_count}, stream={len(atom_symbols)}"
        )

    symbol_to_category: Dict[str, str] = {}
    for r in payload.get("symbol_table", []):
        if not isinstance(r, dict):
            continue
        s = str(r.get("symbol", ""))
        if not s:
            continue
        symbol_to_category[s] = str(r.get("category", "other"))

    exec_idx, other_busy_idx = _build_interval_indices(
        events_by_stream=events_by_stream,
        device_id=device_id,
        stream_id=stream_id,
    )

    state = _WalkState(
        atom_events=used_events,
        atom_symbols=atom_symbols,
        atom_categories=[e.category for e in used_events],
        symbol_to_category=symbol_to_category,
        root=root,
        macros=macros,
        device_exec_index=exec_idx,
        other_stream_busy=other_busy_idx,
        task_source_notes=task_source_notes,
        node_source_notes=node_source_notes,
        cfg=cfg,
    )
    _walk_node(root, state=state, template_id="Root", macro_stack=set())
    if state.cursor != atom_count:
        raise ValueError(
            f"tree walk not fully consumed: consumed={state.cursor}, expected={atom_count}, file={tree_v2_path}"
        )

    core_rows = _core_rows(state.template_rows)
    detail_rows = [{"template_id": r["template_id"], "detail": _type_detail(r)} for r in core_rows]
    ordered_rows = sorted(core_rows, key=lambda r: _template_sort_key(str(r.get("template_id", ""))))
    macro_rows = [r for r in ordered_rows if str(r.get("template_id", "")).startswith("Macro:")]
    macro_summary_rows, step_rows_by_macro = _build_macro_views(
        ordered_rows=ordered_rows,
        macro_rows=macro_rows,
    )
    macro_step_rows: List[Dict[str, object]] = []
    for name in sorted(step_rows_by_macro.keys(), key=_macro_sort_key):
        macro_step_rows.extend(step_rows_by_macro[name])
    augmented_md = _build_augmented_md(
        db_path=db_path,
        device_id=device_id,
        stream_id=stream_id,
        atom_count=atom_count,
        core_rows=core_rows,
    )

    output_dir = out_dir.resolve() if out_dir else tree_v2_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    core_csv_path = output_dir / f"{stem}.node_perf_core.csv"
    detail_jsonl_path = output_dir / f"{stem}.node_perf_detail.jsonl"
    instances_csv_path = output_dir / f"{stem}.node_instances.csv"
    macro_summary_csv_path = output_dir / f"{stem}.macro_summary.csv"
    macro_steps_csv_path = output_dir / f"{stem}.macro_steps.csv"
    augmented_md_path = output_dir / f"{stem}.tree.readable.augmented.md"

    _write_csv(instances_csv_path, state.instance_rows)
    _write_csv(core_csv_path, core_rows)
    _write_csv(macro_summary_csv_path, macro_summary_rows)
    _write_csv(macro_steps_csv_path, macro_step_rows)
    with detail_jsonl_path.open("w", encoding="utf-8") as f:
        for row in detail_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    augmented_md_path.write_text(augmented_md + "\n", encoding="utf-8")

    return {
        "tree_v2_file": str(tree_v2_path),
        "db": str(db_path),
        "device_id": device_id,
        "stream_id": stream_id,
        "atom_count": atom_count,
        "source_notes_file": str(source_notes_path) if source_notes_path else "",
        "core_csv": str(core_csv_path),
        "detail_jsonl": str(detail_jsonl_path),
        "instances_csv": str(instances_csv_path),
        "macro_summary_csv": str(macro_summary_csv_path),
        "macro_steps_csv": str(macro_steps_csv_path),
        "augmented_md": str(augmented_md_path),
    }


def _select_tree_v2_files(loop_dir: Path, *, top_streams_by_total_dur: int) -> List[Path]:
    files = sorted(loop_dir.glob("*.tree.v2.json"))
    topk = max(0, int(top_streams_by_total_dur))
    if topk <= 0:
        return files

    summary_path = loop_dir / "summary.csv"
    if not summary_path.exists():
        return files[:topk]

    by_name: Dict[str, Path] = {p.name: p for p in files}
    ranked: List[Tuple[float, Path]] = []
    with summary_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rel = str(row.get("tree_v2_file", "")).strip()
            if not rel:
                continue
            p = Path(rel)
            cand = by_name.get(p.name)
            if cand is None:
                cand = (loop_dir / rel).resolve()
                if not cand.exists():
                    continue
            try:
                total_dur_us = float(row.get("total_dur_us", 0.0))
            except Exception:
                total_dur_us = 0.0
            ranked.append((total_dur_us, cand))

    if not ranked:
        return files[:topk]

    ranked.sort(key=lambda x: x[0], reverse=True)
    out: List[Path] = []
    seen: set[Path] = set()
    for _, p in ranked:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= topk:
            break
    return out


def augment_loop_tree_dir(
    *,
    loop_dir: Path,
    out_dir: Path | None = None,
    config: LoopTreeAugmentConfig | None = None,
) -> Dict[str, object]:
    cfg = config or LoopTreeAugmentConfig()
    loop_dir = loop_dir.resolve()
    files = _select_tree_v2_files(
        loop_dir,
        top_streams_by_total_dur=cfg.top_streams_by_total_dur,
    )
    rows: List[Dict[str, object]] = []
    for p in files:
        rows.append(augment_one_tree(tree_v2_path=p, out_dir=out_dir, config=cfg))
    return {
        "loop_dir": str(loop_dir),
        "file_count": len(rows),
        "top_streams_by_total_dur": int(cfg.top_streams_by_total_dur),
        "outputs": rows,
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Augment existing loop tree outputs without re-running workload."
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to one *.tree.v2.json or a directory containing them.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Optional output directory (default: same directory as input file(s)).",
    )
    parser.add_argument(
        "--top-other-streams",
        type=int,
        default=3,
        help="Top-k active other streams stored in instance rows.",
    )
    parser.add_argument(
        "--top-streams-by-total-dur",
        type=int,
        default=0,
        help="When path is a directory, only augment top-k streams by summary.csv total_dur_us (0 means all).",
    )
    parser.add_argument(
        "--source-notes",
        type=Path,
        default=None,
        help=(
            "Optional JSON annotations for source mapping. "
            "If omitted, tries sibling <stem>.source_notes.json when augmenting a single tree."
        ),
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    cfg = LoopTreeAugmentConfig(
        top_other_streams=max(1, int(args.top_other_streams)),
        top_streams_by_total_dur=max(0, int(args.top_streams_by_total_dur)),
        source_notes_path=str(args.source_notes.resolve()) if args.source_notes else None,
    )
    p = args.path.resolve()
    if p.is_dir():
        meta = augment_loop_tree_dir(loop_dir=p, out_dir=args.out_dir, config=cfg)
    else:
        meta = augment_one_tree(tree_v2_path=p, out_dir=args.out_dir, config=cfg)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
