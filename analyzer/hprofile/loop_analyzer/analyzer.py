from __future__ import annotations

import csv
import json
import re
import sqlite3
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple, Union

from ..io.discover import discover_msprof_dbs


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


@dataclass(frozen=True)
class LoopAnalyzerConfig:
    top_streams_per_db: int = 3
    max_events_per_stream: int = 20000
    max_period: int = 12
    min_repeat_count: int = 2


@dataclass(frozen=True)
class StreamEvent:
    start_ns: int
    end_ns: int
    device_id: int
    stream_id: int
    task_id: int
    global_task_id: int
    connection_id: int
    task_type: str
    label: str
    category: str

    @property
    def dur_ns(self) -> int:
        return max(self.end_ns - self.start_ns, 0)


@dataclass
class AtomNode:
    symbol: str
    label: str
    category: str
    task_type: str
    anchor_start_ns: int
    anchor_end_ns: int
    windows: List[Tuple[int, int]]
    global_task_ids: List[int]
    connection_ids: List[int]
    key: Tuple[str, str]


@dataclass
class RepeatNode:
    count: int
    body: List["Node"]
    anchor_start_ns: int
    anchor_end_ns: int
    span_windows: List[Tuple[int, int]]
    index_windows: List[List[Tuple[int, int]]]
    key: Tuple[str, int, Tuple[Tuple, ...]]


Node = Union[AtomNode, RepeatNode]


def _normalize_task_type(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).upper().replace("_", " ")


def _normalize_task_key(name: str) -> str:
    s = (name or "").strip().upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _canonical_label(label: str) -> str:
    s = (label or "").strip()
    if not s:
        return "UNKNOWN"
    s = re.sub(r"\d+", "#", s)
    s = re.sub(r"\s+", " ", s)
    if len(s) > 96:
        s = s[:93] + "..."
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


def _symbol_name(idx: int) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    base = len(alphabet)
    out = ""
    x = idx
    while True:
        out = alphabet[x % base] + out
        x = x // base - 1
        if x < 0:
            break
    return out


def _segments_equal(ids: Sequence[int], a: int, b: int, length: int) -> bool:
    for i in range(length):
        if ids[a + i] != ids[b + i]:
            return False
    return True


def _find_best_repeat(
    ids: Sequence[int], *, max_period: int, min_repeat_count: int
) -> Tuple[int, int, int] | None:
    n = len(ids)
    if n < 2:
        return None

    best: Tuple[int, int, int] | None = None
    best_score: Tuple[int, int, int, int, int] | None = None

    upper_period = min(max_period, n // 2)
    for period in range(1, upper_period + 1):
        i = 0
        while i + 2 * period <= n:
            if not _segments_equal(ids, i, i + period, period):
                i += 1
                continue

            count = 2
            while i + (count + 1) * period <= n and _segments_equal(
                ids, i, i + count * period, period
            ):
                count += 1

            if count >= min_repeat_count:
                span = count * period
                savings = span - 1
                score = (savings, span, count, -period, -i)
                if best_score is None or score > best_score:
                    best_score = score
                    best = (i, period, count)
            i += 1
    return best


def _node_key(node: Node) -> Tuple:
    if isinstance(node, AtomNode):
        return node.key
    return node.key


def _node_anchor_start(node: Node) -> int:
    if isinstance(node, AtomNode):
        return node.anchor_start_ns
    return node.anchor_start_ns


def _node_anchor_end(node: Node) -> int:
    if isinstance(node, AtomNode):
        return node.anchor_end_ns
    return node.anchor_end_ns


def _merge_nodes(dst: Node, src: Node) -> None:
    if _node_key(dst) != _node_key(src):
        raise ValueError("attempt to merge non-equivalent nodes")

    if isinstance(dst, AtomNode) and isinstance(src, AtomNode):
        dst.windows.extend(src.windows)
        dst.global_task_ids.extend(src.global_task_ids)
        dst.connection_ids.extend(src.connection_ids)
        return

    if isinstance(dst, RepeatNode) and isinstance(src, RepeatNode):
        dst.span_windows.extend(src.span_windows)
        for i in range(dst.count):
            dst.index_windows[i].extend(src.index_windows[i])
        for d_child, s_child in zip(dst.body, src.body):
            _merge_nodes(d_child, s_child)
        return

    raise ValueError("node type mismatch in merge")


def _build_repeat_node(groups: List[List[Node]]) -> RepeatNode:
    count = len(groups)
    period = len(groups[0])
    body = groups[0]

    idx_windows: List[List[Tuple[int, int]]] = []
    for g in groups:
        idx_windows.append([(_node_anchor_start(g[0]), _node_anchor_end(g[-1]))])

    for g in groups[1:]:
        for i in range(period):
            _merge_nodes(body[i], g[i])

    anchor_start = _node_anchor_start(groups[0][0])
    anchor_end = _node_anchor_end(groups[-1][-1])
    span_windows = [(anchor_start, anchor_end)]
    key = ("repeat", count, tuple(_node_key(x) for x in body))
    return RepeatNode(
        count=count,
        body=body,
        anchor_start_ns=anchor_start,
        anchor_end_ns=anchor_end,
        span_windows=span_windows,
        index_windows=idx_windows,
        key=key,
    )


def _compress_nodes(
    nodes: List[Node], *, max_period: int, min_repeat_count: int
) -> Tuple[List[Node], int]:
    passes = 0
    current = nodes
    while True:
        key_to_id: Dict[Tuple, int] = {}
        ids: List[int] = []
        for node in current:
            k = _node_key(node)
            if k not in key_to_id:
                key_to_id[k] = len(key_to_id) + 1
            ids.append(key_to_id[k])

        best = _find_best_repeat(ids, max_period=max_period, min_repeat_count=min_repeat_count)
        if best is None:
            break

        i, period, count = best
        groups = [
            current[i + r * period : i + (r + 1) * period]
            for r in range(count)
        ]
        rep = _build_repeat_node(groups)
        current = current[:i] + [rep] + current[i + count * period :]
        passes += 1
    return current, passes


def _render_node(node: Node) -> str:
    if isinstance(node, AtomNode):
        return node.symbol
    body = " ".join(_render_node(x) for x in node.body)
    return f"({body}){node.count}"


def _render_expression(nodes: Sequence[Node]) -> str:
    return " ".join(_render_node(n) for n in nodes)


def _rle_tokens(tokens: Sequence[str]) -> List[str]:
    if not tokens:
        return []
    out: List[str] = []
    cur = tokens[0]
    cnt = 1
    for t in tokens[1:]:
        if t == cur:
            cnt += 1
            continue
        out.append(f"{cur}^{cnt}" if cnt > 1 else cur)
        cur = t
        cnt = 1
    out.append(f"{cur}^{cnt}" if cnt > 1 else cur)
    return out


def _render_nodes_pretty(nodes: Sequence[Node]) -> str:
    parts: List[str] = []
    i = 0
    n = len(nodes)
    while i < n:
        cur = nodes[i]
        if isinstance(cur, AtomNode):
            j = i + 1
            while j < n and isinstance(nodes[j], AtomNode) and nodes[j].symbol == cur.symbol:
                j += 1
            cnt = j - i
            parts.append(f"{cur.symbol}^{cnt}" if cnt > 1 else cur.symbol)
            i = j
            continue

        body = _render_nodes_pretty(cur.body)
        parts.append(f"({body})^{cur.count}")
        i += 1
    return " ".join(parts)


def _wrap_expression(expr: str, width: int = 120) -> str:
    return textwrap.fill(
        expr.strip(),
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _is_subseq(needle: Tuple[str, ...], hay: Tuple[str, ...]) -> bool:
    if len(needle) > len(hay):
        return False
    for i in range(0, len(hay) - len(needle) + 1):
        if hay[i : i + len(needle)] == needle:
            return True
    return False


def _mine_meta_patterns(
    symbol_seq: Sequence[str],
    *,
    min_len: int = 3,
    max_len: int = 8,
    min_count: int = 3,
    topn: int = 20,
) -> List[Dict[str, object]]:
    n = len(symbol_seq)
    if n < min_len:
        return []
    counts: Dict[Tuple[str, ...], int] = {}
    first_pos: Dict[Tuple[str, ...], int] = {}
    upper = min(max_len, n)
    for l in range(min_len, upper + 1):
        for i in range(0, n - l + 1):
            pat = tuple(symbol_seq[i : i + l])
            counts[pat] = counts.get(pat, 0) + 1
            if pat not in first_pos:
                first_pos[pat] = i

    rows: List[Dict[str, object]] = []
    for pat, c in counts.items():
        if c < min_count:
            continue
        score = c * (len(pat) - 1)
        if score <= 0:
            continue
        rows.append(
            {
                "pattern_tokens": pat,
                "pattern_len": len(pat),
                "count": c,
                "score": score,
                "first_pos": first_pos.get(pat, -1),
            }
        )
    rows.sort(
        key=lambda r: (
            int(r["score"]),
            int(r["pattern_len"]),
            int(r["count"]),
            -int(r["first_pos"]),
        ),
        reverse=True,
    )

    selected: List[Dict[str, object]] = []
    for r in rows:
        pat = r["pattern_tokens"]  # type: ignore[assignment]
        conflict = False
        for s in selected:
            sp = s["pattern_tokens"]  # type: ignore[assignment]
            if _is_subseq(pat, sp) or _is_subseq(sp, pat):
                conflict = True
                break
        if conflict:
            continue
        selected.append(r)
        if len(selected) >= topn:
            break

    out: List[Dict[str, object]] = []
    for i, r in enumerate(selected, start=1):
        pat = list(r["pattern_tokens"])  # type: ignore[arg-type]
        out.append(
            {
                "rank": i,
                "pattern": " ".join(_rle_tokens(pat)),
                "pattern_len": int(r["pattern_len"]),
                "count": int(r["count"]),
                "score": int(r["score"]),
                "first_pos": int(r["first_pos"]),
            }
        )
    return out


def _build_readable_markdown(
    *,
    db_path: Path,
    device_id: int,
    stream_id: int,
    original_events: int,
    used_events: int,
    truncated: bool,
    compressed_nodes: int,
    compression_ratio_used: float,
    compression_ratio_original: float,
    expression_pretty: str,
    symbol_rows: Sequence[Dict[str, object]],
    meta_rows: Sequence[Dict[str, object]],
) -> str:
    lines: List[str] = []
    lines.append("# Loop Analyzer Readable Report")
    lines.append("")
    lines.append(f"- db: `{db_path}`")
    lines.append(f"- device_id: `{device_id}`")
    lines.append(f"- stream_id: `{stream_id}`")
    lines.append(f"- original_events: `{original_events}`")
    lines.append(f"- used_events: `{used_events}`")
    lines.append(f"- truncated: `{int(truncated)}`")
    lines.append(f"- compressed_nodes: `{compressed_nodes}`")
    lines.append(f"- compression_ratio_used: `{compression_ratio_used:.6f}`")
    lines.append(f"- compression_ratio_original: `{compression_ratio_original:.6f}`")
    lines.append("")
    lines.append("## Expression")
    lines.append("")
    lines.append("```")
    lines.append(expression_pretty)
    lines.append("```")
    lines.append("")
    lines.append("## Symbols")
    lines.append("")
    lines.append("| symbol | category | window_count | label |")
    lines.append("| --- | --- | ---: | --- |")
    for r in sorted(symbol_rows, key=lambda x: int(x.get("window_count", 0)), reverse=True):
        lines.append(
            f"| {r.get('symbol','')} | {r.get('category','')} | {int(r.get('window_count',0))} | {r.get('label','')} |"
        )
    lines.append("")
    lines.append("## Meta Patterns")
    lines.append("")
    if meta_rows:
        lines.append("| rank | pattern | len | count | score |")
        lines.append("| ---: | --- | ---: | ---: | ---: |")
        for r in meta_rows:
            lines.append(
                f"| {int(r.get('rank',0))} | {r.get('pattern','')} | {int(r.get('pattern_len',0))} | {int(r.get('count',0))} | {int(r.get('score',0))} |"
            )
    else:
        lines.append("No frequent meta pattern found with current threshold.")
    lines.append("")
    return "\n".join(lines)


def _node_to_dict(node: Node) -> Dict[str, object]:
    if isinstance(node, AtomNode):
        return {
            "type": "atom",
            "symbol": node.symbol,
            "label": node.label,
            "category": node.category,
            "task_type": node.task_type,
            "anchor_window": [node.anchor_start_ns, node.anchor_end_ns],
            "window_count": len(node.windows),
            "windows": [[s, e] for s, e in node.windows],
            "global_task_ids": node.global_task_ids,
            "connection_ids": node.connection_ids,
        }

    return {
        "type": "repeat",
        "count": node.count,
        "anchor_window": [node.anchor_start_ns, node.anchor_end_ns],
        "repeat_window_count": len(node.span_windows),
        "repeat_windows": [[s, e] for s, e in node.span_windows],
        "index_windows": {
            str(i + 1): [[s, e] for s, e in ws] for i, ws in enumerate(node.index_windows)
        },
        "body": [_node_to_dict(x) for x in node.body],
    }


def _collect_atom_stats(nodes: Sequence[Node]) -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}

    def visit(n: Node) -> None:
        if isinstance(n, AtomNode):
            row = out.get(n.symbol)
            if row is None:
                out[n.symbol] = {
                    "symbol": n.symbol,
                    "label": n.label,
                    "category": n.category,
                    "task_type": n.task_type,
                    "window_count": len(n.windows),
                }
            else:
                row["window_count"] = int(row["window_count"]) + len(n.windows)
            return
        for c in n.body:
            visit(c)

    for n in nodes:
        visit(n)
    return out


def _load_string_ids(conn: sqlite3.Connection) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for sid, value in conn.execute("SELECT id, value FROM STRING_IDS"):
        if sid is None:
            continue
        out[int(sid)] = str(value or "")
    return out


def _load_global_task_names(conn: sqlite3.Connection) -> Tuple[Dict[int, str], Dict[int, str]]:
    compute: Dict[int, str] = {}
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='COMPUTE_TASK_INFO'"
    ).fetchone():
        for gid, name_id in conn.execute("SELECT globalTaskId, name FROM COMPUTE_TASK_INFO"):
            if gid is None or name_id is None:
                continue
            compute[int(gid)] = str(name_id)

    comm: Dict[int, str] = {}
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='COMMUNICATION_TASK_INFO'"
    ).fetchone():
        for gid, name_id in conn.execute(
            "SELECT globalTaskId, MIN(name) FROM COMMUNICATION_TASK_INFO GROUP BY globalTaskId"
        ):
            if gid is None or name_id is None:
                continue
            comm[int(gid)] = str(name_id)
    return compute, comm


def _load_stream_events(db_path: Path) -> Dict[Tuple[int, int], List[StreamEvent]]:
    out: Dict[Tuple[int, int], List[StreamEvent]] = {}
    with sqlite3.connect(str(db_path)) as conn:
        sid_to_value = _load_string_ids(conn)
        compute_name_ids, comm_name_ids = _load_global_task_names(conn)

        query = (
            "SELECT startNs, endNs, deviceId, streamId, taskId, globalTaskId, connectionId, taskType "
            "FROM TASK ORDER BY deviceId, streamId, startNs, endNs, globalTaskId"
        )
        for row in conn.execute(query):
            start_ns = int(row[0] if row[0] is not None else 0)
            end_ns = int(row[1] if row[1] is not None else 0)
            device_id = int(row[2] if row[2] is not None else -1)
            stream_id = int(row[3] if row[3] is not None else -1)
            task_id = int(row[4] if row[4] is not None else -1)
            global_task_id = int(row[5] if row[5] is not None else -1)
            connection_id = int(row[6] if row[6] is not None else -1)
            task_type_id = int(row[7] if row[7] is not None else -1)

            task_type = sid_to_value.get(task_type_id, str(task_type_id))
            task_type_norm = _normalize_task_type(task_type)
            task_key = _normalize_task_key(task_type_norm)
            if task_key == "CAPTURE_WAIT":
                continue

            category = _classify_task(task_type_norm)
            if category not in {"wait", "comm", "exec"}:
                continue

            label_raw = ""
            compute_name_id = compute_name_ids.get(global_task_id)
            if compute_name_id is not None:
                try:
                    label_raw = sid_to_value.get(int(compute_name_id), "")
                except ValueError:
                    label_raw = ""
            if not label_raw:
                comm_name_id = comm_name_ids.get(global_task_id)
                if comm_name_id is not None:
                    try:
                        label_raw = sid_to_value.get(int(comm_name_id), "")
                    except ValueError:
                        label_raw = ""
            if not label_raw:
                label_raw = task_type_norm
            label = _canonical_label(label_raw)

            key = (device_id, stream_id)
            out.setdefault(key, []).append(
                StreamEvent(
                    start_ns=start_ns,
                    end_ns=end_ns,
                    device_id=device_id,
                    stream_id=stream_id,
                    task_id=task_id,
                    global_task_id=global_task_id,
                    connection_id=connection_id,
                    task_type=task_type_norm,
                    label=label,
                    category=category,
                )
            )
    return out


def _stream_total_dur(events: Sequence[StreamEvent]) -> int:
    return sum(e.dur_ns for e in events)


def _events_to_nodes(events: Sequence[StreamEvent]) -> Tuple[List[Node], Dict[str, Dict[str, str]]]:
    symbol_by_key: Dict[Tuple[str, str, str], str] = {}
    symbol_meta: Dict[str, Dict[str, str]] = {}
    nodes: List[Node] = []

    for ev in events:
        key = (ev.label, ev.category, ev.task_type)
        symbol = symbol_by_key.get(key)
        if symbol is None:
            symbol = _symbol_name(len(symbol_by_key))
            symbol_by_key[key] = symbol
            symbol_meta[symbol] = {
                "symbol": symbol,
                "label": ev.label,
                "category": ev.category,
                "task_type": ev.task_type,
            }

        nodes.append(
            AtomNode(
                symbol=symbol,
                label=ev.label,
                category=ev.category,
                task_type=ev.task_type,
                anchor_start_ns=ev.start_ns,
                anchor_end_ns=ev.end_ns,
                windows=[(ev.start_ns, ev.end_ns)],
                global_task_ids=[ev.global_task_id],
                connection_ids=[ev.connection_id],
                key=("atom", symbol),
            )
        )
    return nodes, symbol_meta


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


def run_loop_analyzer(
    *,
    run_dir: Path,
    out_dir: Path,
    config: LoopAnalyzerConfig | None = None,
) -> Dict[str, object]:
    cfg = config or LoopAnalyzerConfig()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    db_paths = discover_msprof_dbs(run_dir)

    summary_rows: List[Dict[str, object]] = []
    stream_file_count = 0

    for db_idx, db_path in enumerate(db_paths, start=1):
        events_by_stream = _load_stream_events(db_path)
        ranked = sorted(
            events_by_stream.items(),
            key=lambda kv: _stream_total_dur(kv[1]),
            reverse=True,
        )

        for stream_rank, ((device_id, stream_id), events) in enumerate(
            ranked[: cfg.top_streams_per_db],
            start=1,
        ):
            original_events = len(events)
            used_events = min(original_events, cfg.max_events_per_stream)
            trimmed = list(events[:used_events])
            truncated = used_events < original_events

            nodes, symbol_meta = _events_to_nodes(trimmed)
            symbol_seq = [n.symbol for n in nodes if isinstance(n, AtomNode)]
            compressed_nodes, passes = _compress_nodes(
                nodes,
                max_period=cfg.max_period,
                min_repeat_count=cfg.min_repeat_count,
            )

            expression = _render_expression(compressed_nodes)
            expression_pretty = _render_nodes_pretty(compressed_nodes)
            expression_pretty_wrapped = _wrap_expression(expression_pretty)
            atom_stats = _collect_atom_stats(compressed_nodes)
            meta_rows = _mine_meta_patterns(
                symbol_seq,
                min_len=3,
                max_len=8,
                min_count=3,
                topn=20,
            )
            symbol_rows = []
            for symbol in sorted(symbol_meta):
                row = dict(symbol_meta[symbol])
                row["window_count"] = int(atom_stats.get(symbol, {}).get("window_count", 0))
                symbol_rows.append(row)

            file_stem = f"db{db_idx:02d}_rank{stream_rank:02d}_dev{device_id}_stream{stream_id}"
            expr_path = out_dir / f"{file_stem}.expr.txt"
            expr_pretty_path = out_dir / f"{file_stem}.expr.pretty.txt"
            json_path = out_dir / f"{file_stem}.tree.json"
            symbol_path = out_dir / f"{file_stem}.symbols.csv"
            meta_pattern_path = out_dir / f"{file_stem}.meta_patterns.csv"
            readable_path = out_dir / f"{file_stem}.readable.md"

            expr_path.write_text(expression + "\n", encoding="utf-8")
            expr_pretty_path.write_text(expression_pretty_wrapped + "\n", encoding="utf-8")
            payload = {
                "db": str(db_path),
                "device_id": device_id,
                "stream_id": stream_id,
                "stream_rank_in_db": stream_rank,
                "original_events": original_events,
                "used_events": used_events,
                "truncated": truncated,
                "compression_passes": passes,
                "compressed_nodes": len(compressed_nodes),
                "compression_ratio_used": round(used_events / max(len(compressed_nodes), 1), 6),
                "compression_ratio_original": round(original_events / max(len(compressed_nodes), 1), 6),
                "expression": expression,
                "expression_pretty": expression_pretty,
                "root": [_node_to_dict(n) for n in compressed_nodes],
                "symbol_legend": symbol_rows,
                "meta_patterns": meta_rows,
            }
            json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _write_csv(symbol_path, symbol_rows)
            _write_csv(meta_pattern_path, meta_rows)
            readable = _build_readable_markdown(
                db_path=db_path,
                device_id=device_id,
                stream_id=stream_id,
                original_events=original_events,
                used_events=used_events,
                truncated=truncated,
                compressed_nodes=len(compressed_nodes),
                compression_ratio_used=round(used_events / max(len(compressed_nodes), 1), 6),
                compression_ratio_original=round(original_events / max(len(compressed_nodes), 1), 6),
                expression_pretty=expression_pretty_wrapped,
                symbol_rows=symbol_rows,
                meta_rows=meta_rows,
            )
            readable_path.write_text(readable + "\n", encoding="utf-8")

            total_dur_us = round(sum(e.dur_ns for e in trimmed) / 1000.0, 3)
            summary_rows.append(
                {
                    "db": str(db_path),
                    "device_id": device_id,
                    "stream_id": stream_id,
                    "stream_rank_in_db": stream_rank,
                    "original_events": original_events,
                    "used_events": used_events,
                    "truncated": int(truncated),
                    "total_dur_us": total_dur_us,
                    "compressed_nodes": len(compressed_nodes),
                    "compression_ratio_used": round(used_events / max(len(compressed_nodes), 1), 6),
                    "compression_ratio_original": round(original_events / max(len(compressed_nodes), 1), 6),
                    "compression_passes": passes,
                    "expression_preview": expression_pretty_wrapped[:240],
                    "expr_file": str(expr_path.relative_to(out_dir)),
                    "expr_pretty_file": str(expr_pretty_path.relative_to(out_dir)),
                    "tree_file": str(json_path.relative_to(out_dir)),
                    "symbols_file": str(symbol_path.relative_to(out_dir)),
                    "meta_patterns_file": str(meta_pattern_path.relative_to(out_dir)),
                    "readable_file": str(readable_path.relative_to(out_dir)),
                }
            )
            stream_file_count += 1

    summary_path = out_dir / "summary.csv"
    _write_csv(summary_path, summary_rows)

    meta = {
        "version": "v0-exact",
        "run_dir": str(run_dir.resolve()),
        "db_count": len(db_paths),
        "dbs": [str(p) for p in db_paths],
        "top_streams_per_db": cfg.top_streams_per_db,
        "max_events_per_stream": cfg.max_events_per_stream,
        "max_period": cfg.max_period,
        "min_repeat_count": cfg.min_repeat_count,
        "stream_output_count": stream_file_count,
        "summary_file": str(summary_path),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta
