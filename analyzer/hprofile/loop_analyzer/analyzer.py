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


@dataclass(frozen=True)
class SeqToken:
    name: str
    start_ns: int
    end_ns: int


@dataclass
class MacroDef:
    name: str
    level: str
    tokens: List[str]
    definition_len: int
    replace_count: int
    gain: int
    first_pos: int
    windows: List[Tuple[int, int]]
    defs_covered: int


@dataclass
class TokAtom:
    name: str
    key: Tuple[str, str]


@dataclass
class TokRepeat:
    count: int
    body: List["TokNode"]
    key: Tuple[str, int, Tuple[Tuple, ...]]


TokNode = Union[TokAtom, TokRepeat]


def _normalize_task_type(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).upper().replace("_", " ")


def _normalize_task_key(name: str) -> str:
    s = (name or "").strip().upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _canonical_label(label: str, *, category: str) -> str:
    s = (label or "").strip()
    if not s:
        return "UNKNOWN"
    # Keep operator variants like MatMulV2/MatMulV3 distinguishable for exec.
    # For non-exec control/comm labels, normalize numbers more aggressively.
    if category == "exec":
        s = re.sub(r"\b\d{6,}\b", "#", s)
    else:
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


def _find_non_overlap_starts(seq: Sequence[str], pattern: Sequence[str]) -> List[int]:
    if not pattern or len(pattern) > len(seq):
        return []
    starts: List[int] = []
    i = 0
    n = len(seq)
    m = len(pattern)
    while i <= n - m:
        if tuple(seq[i : i + m]) == tuple(pattern):
            starts.append(i)
            i += m
        else:
            i += 1
    return starts


def _tok_key(node: TokNode) -> Tuple:
    if isinstance(node, TokAtom):
        return node.key
    return node.key


def _compress_token_nodes(
    nodes: List[TokNode],
    *,
    max_period: int,
    min_repeat_count: int,
) -> List[TokNode]:
    current = nodes
    while True:
        key_to_id: Dict[Tuple, int] = {}
        ids: List[int] = []
        for node in current:
            k = _tok_key(node)
            if k not in key_to_id:
                key_to_id[k] = len(key_to_id) + 1
            ids.append(key_to_id[k])

        best = _find_best_repeat(ids, max_period=max_period, min_repeat_count=min_repeat_count)
        if best is None:
            break
        i, period, count = best
        groups = [current[i + r * period : i + (r + 1) * period] for r in range(count)]
        body = groups[0]
        key = ("repeat", count, tuple(_tok_key(x) for x in body))
        rep = TokRepeat(count=count, body=body, key=key)
        current = current[:i] + [rep] + current[i + count * period :]
    return current


def _compress_token_sequence(
    tokens: Sequence[str],
    *,
    max_period: int = 12,
    min_repeat_count: int = 2,
) -> List[TokNode]:
    nodes: List[TokNode] = [TokAtom(name=t, key=("atom", t)) for t in tokens]
    return _compress_token_nodes(nodes, max_period=max_period, min_repeat_count=min_repeat_count)


def _select_best_candidate(
    seq: Sequence[str],
    *,
    min_len: int,
    max_len: int,
    min_count: int,
) -> Tuple[Tuple[str, ...], List[int], int] | None:
    n = len(seq)
    if n < min_len:
        return None
    counts: Dict[Tuple[str, ...], int] = {}
    first_pos: Dict[Tuple[str, ...], int] = {}
    upper = min(max_len, n)
    for l in range(min_len, upper + 1):
        for i in range(0, n - l + 1):
            pat = tuple(seq[i : i + l])
            counts[pat] = counts.get(pat, 0) + 1
            if pat not in first_pos:
                first_pos[pat] = i

    best: Tuple[Tuple[str, ...], List[int], int] | None = None
    best_key: Tuple[int, int, int, int] | None = None
    for pat, c in counts.items():
        if c < min_count:
            continue
        if len(set(pat)) < 2:
            continue

        starts = _find_non_overlap_starts(seq, pat)
        k = len(starts)
        if k < min_count:
            continue
        gain = k * (len(pat) - 1) - (len(pat) + 1)
        if gain <= 0:
            continue

        key = (len(pat), gain, k, -first_pos.get(pat, 0))
        if best_key is None or key > best_key:
            best_key = key
            best = (pat, starts, gain)
    return best


def _replace_pattern_tokens(
    seq_tokens: Sequence[SeqToken],
    pattern: Sequence[str],
    starts: Sequence[int],
    macro_name: str,
) -> Tuple[List[SeqToken], List[Tuple[int, int]]]:
    m = len(pattern)
    start_set = set(starts)
    out: List[SeqToken] = []
    windows: List[Tuple[int, int]] = []
    i = 0
    n = len(seq_tokens)
    while i < n:
        if i in start_set and i + m <= n:
            seg = seq_tokens[i : i + m]
            s = seg[0].start_ns
            e = seg[-1].end_ns
            out.append(SeqToken(name=macro_name, start_ns=s, end_ns=e))
            windows.append((s, e))
            i += m
            continue
        out.append(seq_tokens[i])
        i += 1
    return out, windows


def _build_macros(
    symbol_seq: Sequence[str],
    atom_windows: Sequence[Tuple[int, int]],
) -> Tuple[List[str], List[MacroDef], List[MacroDef]]:
    seq_tokens = [
        SeqToken(name=s, start_ns=atom_windows[i][0], end_ns=atom_windows[i][1])
        for i, s in enumerate(symbol_seq)
    ]

    l1_defs: List[MacroDef] = []
    macro_id = 1
    while True:
        names = [t.name for t in seq_tokens]
        cand = _select_best_candidate(
            names,
            min_len=4,
            max_len=12,
            min_count=3,
        )
        if cand is None:
            break
        pat, starts, gain = cand
        macro_name = f"M{macro_id}"
        seq_tokens, windows = _replace_pattern_tokens(seq_tokens, pat, starts, macro_name)
        l1_defs.append(
            MacroDef(
                name=macro_name,
                level="L1",
                tokens=list(pat),
                definition_len=len(pat),
                replace_count=len(starts),
                gain=gain,
                first_pos=starts[0] if starts else -1,
                windows=windows,
                defs_covered=0,
            )
        )
        macro_id += 1

    def_map: Dict[str, List[str]] = {d.name: list(d.tokens) for d in l1_defs}
    l2_defs: List[MacroDef] = []
    while True:
        all_names = list(def_map.keys())
        if not all_names:
            break

        seq_by_name = {k: list(v) for k, v in def_map.items()}
        counts: Dict[Tuple[str, ...], int] = {}
        first_pos: Dict[Tuple[str, ...], int] = {}
        defs_occ: Dict[Tuple[str, ...], int] = {}
        occ_by_def: Dict[Tuple[str, ...], Dict[str, List[int]]] = {}

        for dname, toks in seq_by_name.items():
            n = len(toks)
            if n < 4:
                continue
            for l in range(4, min(10, n) + 1):
                for i in range(0, n - l + 1):
                    pat = tuple(toks[i : i + l])
                    counts[pat] = counts.get(pat, 0) + 1
                    if pat not in first_pos:
                        first_pos[pat] = i

            for l in range(4, min(10, n) + 1):
                seen_pat: set[Tuple[str, ...]] = set()
                for i in range(0, n - l + 1):
                    pat = tuple(toks[i : i + l])
                    if pat in seen_pat:
                        continue
                    starts = _find_non_overlap_starts(toks, pat)
                    if starts:
                        occ_by_def.setdefault(pat, {})[dname] = starts
                        seen_pat.add(pat)

        for pat, dmap in occ_by_def.items():
            defs_occ[pat] = len(dmap)

        best_pat: Tuple[str, ...] | None = None
        best_gain = 0
        best_starts_by_def: Dict[str, List[int]] = {}
        best_key: Tuple[int, int, int, int] | None = None
        for pat, c in counts.items():
            if c < 3:
                continue
            if len(set(pat)) < 2:
                continue
            cover = defs_occ.get(pat, 0)
            if cover < 2:
                continue
            starts_by_def = occ_by_def.get(pat, {})
            total_occ = sum(len(v) for v in starts_by_def.values())
            if total_occ < 3:
                continue
            gain = total_occ * (len(pat) - 1) - (len(pat) + 1)
            if gain <= 0:
                continue
            key = (len(pat), gain, total_occ, -first_pos.get(pat, 0))
            if best_key is None or key > best_key:
                best_key = key
                best_gain = gain
                best_pat = pat
                best_starts_by_def = starts_by_def

        if best_pat is None:
            break

        macro_name = f"M{macro_id}"
        for dname in all_names:
            toks = def_map[dname]
            starts = best_starts_by_def.get(dname, [])
            if not starts:
                continue
            new_toks: List[str] = []
            i = 0
            m = len(best_pat)
            start_set = set(starts)
            while i < len(toks):
                if i in start_set and i + m <= len(toks) and tuple(toks[i : i + m]) == best_pat:
                    new_toks.append(macro_name)
                    i += m
                    continue
                new_toks.append(toks[i])
                i += 1
            def_map[dname] = new_toks

        l2_defs.append(
            MacroDef(
                name=macro_name,
                level="L2",
                tokens=list(best_pat),
                definition_len=len(best_pat),
                replace_count=sum(len(v) for v in best_starts_by_def.values()),
                gain=best_gain,
                first_pos=min((v[0] for v in best_starts_by_def.values() if v), default=-1),
                windows=[],
                defs_covered=len(best_starts_by_def),
            )
        )
        macro_id += 1

    # apply L2 substitutions onto L1 definitions for final rendering
    for d in l1_defs:
        if d.name in def_map:
            d.tokens = list(def_map[d.name])
    all_defs = l1_defs + l2_defs

    # remove alias macros like Mx -> My to keep dictionary readable.
    alias: Dict[str, str] = {}
    for d in all_defs:
        if len(d.tokens) == 1 and d.tokens[0].startswith("M") and d.tokens[0] != d.name:
            alias[d.name] = d.tokens[0]

    def _resolve_alias(name: str) -> str:
        seen: set[str] = set()
        cur = name
        while cur in alias and cur not in seen:
            seen.add(cur)
            cur = alias[cur]
        return cur

    final_expr_tokens = [_resolve_alias(t.name) for t in seq_tokens]
    kept: List[MacroDef] = []
    for d in all_defs:
        if d.name in alias:
            continue
        d.tokens = [_resolve_alias(t) for t in d.tokens]
        d.definition_len = len(d.tokens)
        kept.append(d)

    kept.sort(key=lambda x: int(x.name[1:]) if x.name[1:].isdigit() else 10**9)
    l1_kept = [d for d in kept if d.level == "L1"]
    l2_kept = [d for d in kept if d.level == "L2"]
    return final_expr_tokens, l1_kept, l2_kept


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
    macro_expression: str,
    macro_defs: Sequence[Dict[str, object]],
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
    lines.append("## Macro Expression")
    lines.append("")
    lines.append("```")
    lines.append(macro_expression)
    lines.append("```")
    lines.append("")
    lines.append("## Macros")
    lines.append("")
    if macro_defs:
        lines.append("| name | level | definition | len | replace_count | gain | defs_covered |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: |")
        for r in macro_defs:
            lines.append(
                f"| {r.get('name','')} | {r.get('level','')} | {r.get('definition','')} | {int(r.get('definition_len',0))} | {int(r.get('replace_count',0))} | {int(r.get('gain',0))} | {int(r.get('defs_covered',0))} |"
            )
    else:
        lines.append("No macro selected (all candidates have non-positive net gain).")
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


def _tok_nodes_to_ast_seq(
    nodes: Sequence[TokNode],
    *,
    symbol_meta_map: Dict[str, Dict[str, object]],
    macro_names: set[str],
) -> Dict[str, object]:
    items: List[Dict[str, object]] = []
    for i, n in enumerate(nodes, start=1):
        if isinstance(n, TokRepeat):
            items.append(
                {
                    "ord": i,
                    "node": {
                        "type": "Repeat",
                        "count": n.count,
                        "body": _tok_nodes_to_ast_seq(
                            n.body,
                            symbol_meta_map=symbol_meta_map,
                            macro_names=macro_names,
                        ),
                    },
                }
            )
            continue

        if n.name in macro_names:
            items.append(
                {
                    "ord": i,
                    "node": {"type": "MacroRef", "name": n.name},
                }
            )
            continue

        meta = symbol_meta_map.get(n.name, {})
        items.append(
            {
                "ord": i,
                "node": {
                    "type": "Atom",
                    "symbol": n.name,
                    "op_label": meta.get("label", n.name),
                    "category": meta.get("category", ""),
                    "task_type": meta.get("task_type", ""),
                    "window_count": int(meta.get("window_count", 0)),
                },
            }
        )
    return {"type": "Seq", "items": items}


def _render_ast_lines(
    node: Dict[str, object],
    *,
    out: List[str],
    indent: str = "",
    prefix: str = "",
) -> None:
    t = str(node.get("type", ""))
    if t == "Seq":
        out.append(f"{indent}{prefix}Seq")
        items = node.get("items", [])
        if isinstance(items, list):
            for idx, it in enumerate(items, start=1):
                if not isinstance(it, dict):
                    continue
                child = it.get("node", {})
                if not isinstance(child, dict):
                    continue
                _render_ast_lines(
                    child,
                    out=out,
                    indent=indent + "  ",
                    prefix=f"[{idx}] ",
                )
        return

    if t == "Repeat":
        out.append(f"{indent}{prefix}Repeat x{int(node.get('count', 1))}")
        body = node.get("body", {})
        if isinstance(body, dict):
            _render_ast_lines(body, out=out, indent=indent + "  ", prefix="body: ")
        return

    if t == "MacroRef":
        out.append(f"{indent}{prefix}MacroRef {node.get('name', '')}")
        return

    if t == "Atom":
        out.append(
            f"{indent}{prefix}Atom {node.get('symbol','')} | {node.get('op_label','')} | {node.get('category','')}"
        )
        return

    out.append(f"{indent}{prefix}{t}")


def _build_tree_v2(
    *,
    db_path: Path,
    device_id: int,
    stream_id: int,
    final_expr_tokens: Sequence[str],
    macro_rows: Sequence[Dict[str, object]],
    macro_def_tokens: Dict[str, List[str]],
    symbol_rows: Sequence[Dict[str, object]],
) -> Tuple[Dict[str, object], str]:
    symbol_meta_map = {str(r.get("symbol", "")): dict(r) for r in symbol_rows}
    macro_names = set(macro_def_tokens.keys())

    root_nodes = _compress_token_sequence(final_expr_tokens, max_period=12, min_repeat_count=2)
    root_ast = _tok_nodes_to_ast_seq(
        root_nodes,
        symbol_meta_map=symbol_meta_map,
        macro_names=macro_names,
    )

    macro_defs_ast: List[Dict[str, object]] = []
    for row in macro_rows:
        name = str(row.get("name", ""))
        toks = list(macro_def_tokens.get(name, []))
        def_nodes = _compress_token_sequence(toks, max_period=12, min_repeat_count=2)
        def_ast = _tok_nodes_to_ast_seq(
            def_nodes,
            symbol_meta_map=symbol_meta_map,
            macro_names=macro_names,
        )
        macro_defs_ast.append(
            {
                "name": name,
                "level": row.get("level", ""),
                "gain": int(row.get("gain", 0)),
                "replace_count": int(row.get("replace_count", 0)),
                "definition": row.get("definition", ""),
                "tree": def_ast,
            }
        )

    def _collect_macro_refs(ast_node: Dict[str, object], out: Dict[str, int]) -> None:
        t = str(ast_node.get("type", ""))
        if t == "MacroRef":
            name = str(ast_node.get("name", ""))
            if name:
                out[name] = out.get(name, 0) + 1
            return
        if t == "Seq":
            items = ast_node.get("items", [])
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        child = it.get("node", {})
                        if isinstance(child, dict):
                            _collect_macro_refs(child, out)
            return
        if t == "Repeat":
            body = ast_node.get("body", {})
            if isinstance(body, dict):
                _collect_macro_refs(body, out)

    root_macro_ref_counts: Dict[str, int] = {}
    _collect_macro_refs(root_ast, root_macro_ref_counts)
    macro_table = {str(m.get("name", "")): m for m in macro_defs_ast if m.get("name")}

    payload = {
        "schema_version": "loop_tree_v2",
        "db": str(db_path),
        "device_id": device_id,
        "stream_id": stream_id,
        "root": root_ast,
        "macro_defs": macro_defs_ast,
        "macro_table": macro_table,
        "root_macro_ref_counts": root_macro_ref_counts,
        "symbol_table": list(symbol_rows),
    }

    lines: List[str] = []
    lines.append("# Loop Tree (v2)")
    lines.append("")
    lines.append(f"- db: `{db_path}`")
    lines.append(f"- device_id: `{device_id}`")
    lines.append(f"- stream_id: `{stream_id}`")
    lines.append("")
    lines.append("## Root")
    lines.append("")
    lines.append("```")
    _render_ast_lines(root_ast, out=lines)
    lines.append("```")
    lines.append("")
    lines.append("## Macro Subtrees")
    lines.append("")
    if macro_defs_ast:
        for m in macro_defs_ast:
            lines.append(
                f"### {m['name']} ({m['level']}, gain={m['gain']}, replace_count={m['replace_count']})"
            )
            lines.append("")
            lines.append("```")
            _render_ast_lines(m["tree"], out=lines)
            lines.append("```")
            lines.append("")
    else:
        lines.append("No macro definitions.")
        lines.append("")
    return payload, "\n".join(lines)


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


def _load_global_task_names(
    conn: sqlite3.Connection,
) -> Tuple[Dict[int, str], Dict[int, str], Dict[int, str]]:
    compute: Dict[int, str] = {}
    compute_optype: Dict[int, str] = {}
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='COMPUTE_TASK_INFO'"
    ).fetchone():
        for gid, name_id, op_type_id in conn.execute(
            "SELECT globalTaskId, name, opType FROM COMPUTE_TASK_INFO"
        ):
            if gid is None or name_id is None:
                pass
            else:
                compute[int(gid)] = str(name_id)
            if gid is not None and op_type_id is not None:
                compute_optype[int(gid)] = str(op_type_id)

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
    return compute, compute_optype, comm


def _load_comm_connection_ids(conn: sqlite3.Connection) -> set[int]:
    out: set[int] = set()
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='COMMUNICATION_OP'"
    ).fetchone():
        return out
    for (cid,) in conn.execute("SELECT DISTINCT connectionId FROM COMMUNICATION_OP"):
        if cid is None:
            continue
        out.add(int(cid))
    return out


def _load_stream_events(db_path: Path) -> Dict[Tuple[int, int], List[StreamEvent]]:
    out: Dict[Tuple[int, int], List[StreamEvent]] = {}
    with sqlite3.connect(str(db_path)) as conn:
        sid_to_value = _load_string_ids(conn)
        compute_name_ids, compute_optype_ids, comm_name_ids = _load_global_task_names(conn)
        comm_connection_ids = _load_comm_connection_ids(conn)

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
            if category == "exec" and connection_id in comm_connection_ids:
                category = "comm"
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
                compute_op_type_id = compute_optype_ids.get(global_task_id)
                if compute_op_type_id is not None:
                    try:
                        label_raw = sid_to_value.get(int(compute_op_type_id), "")
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
            label = _canonical_label(label_raw, category=category)

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
            atom_windows = [(n.anchor_start_ns, n.anchor_end_ns) for n in nodes if isinstance(n, AtomNode)]
            compressed_nodes, passes = _compress_nodes(
                nodes,
                max_period=cfg.max_period,
                min_repeat_count=cfg.min_repeat_count,
            )

            expression = _render_expression(compressed_nodes)
            expression_pretty = _render_nodes_pretty(compressed_nodes)
            expression_pretty_wrapped = _wrap_expression(expression_pretty)
            macro_expr_tokens, l1_macro_defs, l2_macro_defs = _build_macros(symbol_seq, atom_windows)
            macro_expression = _wrap_expression(" ".join(_rle_tokens(macro_expr_tokens)))
            macro_defs = l1_macro_defs + l2_macro_defs
            macro_rows: List[Dict[str, object]] = []
            macro_json_rows: List[Dict[str, object]] = []
            macro_def_tokens: Dict[str, List[str]] = {}
            for d in macro_defs:
                defn = " ".join(_rle_tokens(d.tokens))
                row = {
                    "name": d.name,
                    "level": d.level,
                    "definition": defn,
                    "definition_len": d.definition_len,
                    "replace_count": d.replace_count,
                    "gain": d.gain,
                    "defs_covered": d.defs_covered,
                    "first_pos": d.first_pos,
                    "window_count": len(d.windows),
                }
                macro_rows.append(row)
                jr = dict(row)
                jr["tokens"] = list(d.tokens)
                jr["windows"] = [[s, e] for s, e in d.windows]
                macro_json_rows.append(jr)
                macro_def_tokens[d.name] = list(d.tokens)
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
            expr_macro_path = out_dir / f"{file_stem}.expr.macro.txt"
            json_path = out_dir / f"{file_stem}.tree.json"
            symbol_path = out_dir / f"{file_stem}.symbols.csv"
            meta_pattern_path = out_dir / f"{file_stem}.meta_patterns.csv"
            macro_path = out_dir / f"{file_stem}.macros.csv"
            macro_json_path = out_dir / f"{file_stem}.macros.json"
            readable_path = out_dir / f"{file_stem}.readable.md"
            tree_v2_path = out_dir / f"{file_stem}.tree.v2.json"
            tree_readable_path = out_dir / f"{file_stem}.tree.readable.md"

            expr_path.write_text(expression + "\n", encoding="utf-8")
            expr_pretty_path.write_text(expression_pretty_wrapped + "\n", encoding="utf-8")
            expr_macro_path.write_text(macro_expression + "\n", encoding="utf-8")
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
                "macro_expression": " ".join(_rle_tokens(macro_expr_tokens)),
                "root": [_node_to_dict(n) for n in compressed_nodes],
                "symbol_legend": symbol_rows,
                "meta_patterns": meta_rows,
                "macro_defs": macro_json_rows,
            }
            json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _write_csv(symbol_path, symbol_rows)
            _write_csv(meta_pattern_path, meta_rows)
            _write_csv(macro_path, macro_rows)
            macro_json_path.write_text(json.dumps({"macros": macro_json_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tree_v2, tree_readable = _build_tree_v2(
                db_path=db_path,
                device_id=device_id,
                stream_id=stream_id,
                final_expr_tokens=macro_expr_tokens,
                macro_rows=macro_rows,
                macro_def_tokens=macro_def_tokens,
                symbol_rows=symbol_rows,
            )
            tree_v2_path.write_text(json.dumps(tree_v2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tree_readable_path.write_text(tree_readable + "\n", encoding="utf-8")
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
                macro_expression=macro_expression,
                macro_defs=macro_rows,
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
                    "expr_macro_file": str(expr_macro_path.relative_to(out_dir)),
                    "tree_file": str(json_path.relative_to(out_dir)),
                    "tree_v2_file": str(tree_v2_path.relative_to(out_dir)),
                    "symbols_file": str(symbol_path.relative_to(out_dir)),
                    "meta_patterns_file": str(meta_pattern_path.relative_to(out_dir)),
                    "macros_file": str(macro_path.relative_to(out_dir)),
                    "macros_json_file": str(macro_json_path.relative_to(out_dir)),
                    "macro_count": len(macro_rows),
                    "macro_expression_tokens": len(macro_expr_tokens),
                    "macro_compression_ratio_used": round(used_events / max(len(macro_expr_tokens), 1), 6),
                    "readable_file": str(readable_path.relative_to(out_dir)),
                    "tree_readable_file": str(tree_readable_path.relative_to(out_dir)),
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
