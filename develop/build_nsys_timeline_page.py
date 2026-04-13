#!/usr/bin/env python3
import argparse
from collections import Counter
import json
import subprocess
from pathlib import Path

API_KEEP_PREFIX = (
    "cudaLaunchKernel",
    "cuLaunchKernel",
    "cudaGraphLaunch",
    "cudaMemcpyAsync",
    "cudaDeviceSynchronize",
    "cudaStreamSynchronize",
    "cudaMemGetInfo",
)


REQ_KIND_MAP = {
    "request_in": "req_in",
    "prefill_start": "req_prefill",
    "prefill_done": "req_prefill_done",
    "decode_start": "req_decode",
    "token_out": "req_token",
    "request_done": "req_done",
    "request_error": "req_error",
}


def load_report_json(rep_path: str, report_name: str):
    try:
        out = subprocess.check_output(
            ["nsys", "stats", "-q", "-f", "json", "--report", report_name, rep_path],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as e:
        out = e.output or ""
    txt = str(out or "").strip()
    if not txt:
        return []

    b = txt.find("[")
    e = txt.rfind("]")
    if b != -1 and e != -1 and e >= b:
        payload = txt[b : e + 1]
    else:
        b = txt.find("{")
        e = txt.rfind("}")
        payload = txt[b : e + 1] if (b != -1 and e != -1 and e >= b) else ""
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except Exception:
        return []
    if isinstance(data, list):
        return data
    return [data]


def shorten(name: str, n: int = 92) -> str:
    if len(name) <= n:
        return name
    return name[: n - 3] + "..."


def detect_profile_window(rep_path: str):
    try:
        rows = load_report_json(rep_path, "nvtx_pushpop_trace")
    except Exception:
        return None

    def _is_profile_name(raw: str) -> bool:
        n = str(raw or "").strip()
        if not n:
            return False
        n = n.lstrip(":")
        return n == "IMONITOR_PROFILE_PHASE" or n.endswith("/IMONITOR_PROFILE_PHASE")

    cands = []
    for r in rows:
        name = r.get("Name", "") or r.get("NameTree", "") or r.get("Range", "")
        if not _is_profile_name(name):
            continue
        s = int(r.get("Start (ns)", 0) or 0)
        e = int(r.get("End (ns)", 0) or 0)
        if e > s:
            cands.append((s, e))
    if not cands:
        return None
    cands.sort(key=lambda x: x[1] - x[0], reverse=True)
    return cands[0]


def detect_profiler_api_window(api_rows):
    start_names = {"cuProfilerStart", "cudaProfilerStart"}
    stop_names = {"cuProfilerStop", "cudaProfilerStop"}

    starts = []
    stops = []
    for r in api_rows:
        name = str(r.get("Name", "") or "")
        s = int(r.get("Start (ns)", 0) or 0)
        d = max(0, int(r.get("Duration (ns)", 0) or 0))
        e = s + d
        if name in start_names:
            starts.append((s, e))
        elif name in stop_names:
            stops.append((s, e))

    if not starts:
        return None
    starts.sort(key=lambda x: x[0])
    stops.sort(key=lambda x: x[0])

    for s0, s1 in starts:
        for t0, _t1 in stops:
            if t0 >= s0:
                if t0 > s0:
                    return (s0, t0)
                break
        if s1 > s0:
            return (s0, s1)
    return None


def in_window(start_ns: int, dur_ns: int, window):
    if window is None:
        return True
    ws, we = window
    end_ns = start_ns + max(0, dur_ns)
    return not (end_ns < ws or start_ns > we)


def build_gpu_events(api_rows, gpu_rows, max_api=3500, max_kern=3500, window=None):
    api_corr_start = {}
    api_candidates = []
    for r in api_rows:
        name = str(r.get("Name", ""))
        start = int(r.get("Start (ns)", 0) or 0)
        corr = r.get("CorrID")
        if corr is None:
            corr = r.get("CorrId")
        try:
            if corr is not None:
                ci = int(corr)
                if ci not in api_corr_start or start < api_corr_start[ci]:
                    api_corr_start[ci] = start
        except Exception:
            pass

        if not name.startswith(API_KEEP_PREFIX):
            continue
        dur = int(r.get("Duration (ns)", 0) or 0)
        if dur <= 0:
            continue
        if not in_window(start, dur, window):
            continue
        api_candidates.append(
            {
                "lane": "CPU CUDA API",
                "start": start,
                "dur": dur,
                "label": name,
                "kind": "api",
            }
        )

    if len(api_candidates) <= max_api:
        api_events = sorted(api_candidates, key=lambda x: x["start"])
    else:
        important_n = max(1, max_api // 3)
        important = sorted(api_candidates, key=lambda x: x["dur"], reverse=True)[
            :important_n
        ]
        important_keys = {(e["start"], e["dur"], e["label"]) for e in important}
        timeline = [
            e
            for e in sorted(api_candidates, key=lambda x: x["start"])
            if (e["start"], e["dur"], e["label"]) not in important_keys
        ]
        need = max_api - len(important)
        if need <= 0 or not timeline:
            sampled = []
        elif len(timeline) <= need:
            sampled = timeline
        else:
            step = len(timeline) / float(need)
            sampled = [timeline[int(i * step)] for i in range(need)]
        api_events = sorted(important + sampled, key=lambda x: x["start"])

    memcpys = []
    kernels = []
    for r in gpu_rows:
        name = str(r.get("Name", ""))
        dur = int(r.get("Duration (ns)", 0) or 0)
        start = int(r.get("Start (ns)", 0) or 0)
        corr = r.get("CorrId")
        if corr is None:
            corr = r.get("CorrID")
        try:
            if corr is not None:
                start = int(api_corr_start.get(int(corr), start))
        except Exception:
            pass
        if dur <= 0:
            continue
        if not in_window(start, dur, window):
            continue
        stream = str(r.get("Strm", ""))
        lane = f"GPU Stream {stream}" if stream else "GPU Stream ?"
        ev = {
            "lane": lane,
            "start": start,
            "dur": dur,
            "label": name,
            "kind": "memcpy" if name.startswith("[CUDA memcpy") else "kernel",
        }
        if ev["kind"] == "memcpy":
            memcpys.append(ev)
        else:
            kernels.append(ev)

    kernels.sort(key=lambda x: x["dur"], reverse=True)
    kernel_events = kernels[:max_kern]

    events = api_events + memcpys + kernel_events

    lanes = ["CPU CUDA API"]
    gpu_lanes = sorted(
        {e["lane"] for e in events if e["lane"].startswith("GPU Stream")},
        key=lambda s: int(s.split()[-1]) if s.split()[-1].isdigit() else 10**9,
    )
    lanes.extend(gpu_lanes)

    return events, lanes


def load_request_events(path: str):
    rows = []
    session_meta = {}
    p = Path(path)
    if not p.exists():
        return rows, session_meta
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("event_type") == "session_meta" and not session_meta:
                session_meta = obj
                continue
            rows.append(obj)
    return rows, session_meta


def infer_profile_duration_ns(req_rows):
    best_rel = None
    best_sec = None
    for r in req_rows:
        if str(r.get("event_type", "")) != "profile_phase_done":
            continue
        rel = r.get("rel_ns")
        try:
            if rel is not None:
                rel_i = int(rel)
                if rel_i > 0 and (best_rel is None or rel_i > best_rel):
                    best_rel = rel_i
        except Exception:
            pass
        sec = r.get("profile_sec")
        try:
            if sec is not None:
                sec_f = float(sec)
                if sec_f > 0 and (best_sec is None or sec_f > best_sec):
                    best_sec = sec_f
        except Exception:
            pass
    if best_rel is not None:
        return int(best_rel)
    if best_sec is not None:
        return int(best_sec * 1e9)
    return None


def infer_request_anchor_ns(req_rows, gpu_events, bin_ns=50_000_000):
    req_token_rel = []
    for r in req_rows:
        if str(r.get("event_type", "")) != "token_out":
            continue
        rel = r.get("rel_ns")
        if rel is None:
            continue
        try:
            req_token_rel.append(int(rel))
        except Exception:
            continue

    gpu_kernel_starts = [
        int(e.get("start", 0))
        for e in gpu_events
        if str(e.get("kind", "")) == "kernel"
    ]

    if not req_token_rel or not gpu_kernel_starts:
        return None

    rb = Counter(int(t // bin_ns) for t in req_token_rel)
    gb = Counter(int(s // bin_ns) for s in gpu_kernel_starts)
    if not rb or not gb:
        return None

    min_shift = min(gb.keys()) - max(rb.keys())
    max_shift = max(gb.keys()) - min(rb.keys())
    if max_shift < min_shift:
        return None
    if (max_shift - min_shift) > 12000:
        return None

    best_shift = None
    best_score = -1
    for sh in range(min_shift, max_shift + 1):
        sc = 0
        for k, v in rb.items():
            sc += v * gb.get(k + sh, 0)
        if sc > best_score:
            best_score = sc
            best_shift = sh
    if best_shift is None:
        return None
    return int(best_shift * bin_ns)


def build_request_events(req_rows, profile_start_ns, req_group_size=100):
    if not req_rows:
        return [], [], {}, {"request_rows": 0, "request_events": 0, "request_ids": 0}

    req_events = []
    per_req = {}
    req_ids = set()

    for r in req_rows:
        et = str(r.get("event_type", ""))
        if et in ("profile_phase_start", "profile_phase_done", "session_meta"):
            continue

        rid = r.get("req_id")
        if rid is None:
            continue
        rid = int(rid)
        req_ids.add(rid)

        if r.get("rel_ns") is not None and profile_start_ns is not None:
            start_ns = int(profile_start_ns + int(r.get("rel_ns", 0)))
        elif r.get("ts_ns") is not None:
            start_ns = int(r.get("ts_ns", 0))
        else:
            continue

        label = et
        if et == "token_out" and r.get("token_idx") is not None:
            label = f"token_out #{int(r['token_idx'])}"

        ev = {
            "lane": f"REQ {rid}",
            "start": start_ns,
            "dur": 50_000,
            "label": label,
            "kind": REQ_KIND_MAP.get(et, "req_other"),
            "req_id": rid,
        }
        req_events.append(ev)
        per_req.setdefault(rid, []).append(ev)

    sorted_ids = sorted(req_ids)
    req_lanes = [f"REQ {rid}" for rid in sorted_ids]

    group_map = {}
    group_lanes = []
    grouped_events = []
    if req_group_size <= 0:
        req_group_size = 100

    for i in range(0, len(sorted_ids), req_group_size):
        chunk = sorted_ids[i : i + req_group_size]
        if not chunk:
            continue
        gname = f"REQ {chunk[0]}-{chunk[-1]}"
        members = [f"REQ {rid}" for rid in chunk]
        group_map[gname] = members
        group_lanes.append(gname)
        for rid in chunk:
            for e in per_req.get(rid, []):
                ge = dict(e)
                ge["lane"] = gname
                grouped_events.append(ge)

    all_req_events = grouped_events + req_events
    all_req_lanes = group_lanes + req_lanes

    return all_req_events, all_req_lanes, group_map, {
        "request_rows": len(req_rows),
        "request_events": len(req_events),
        "request_ids": len(sorted_ids),
        "request_group_size": req_group_size,
        "request_group_count": len(group_map),
    }


def normalize_events(events, t0):
    norm = []
    for e in events:
        norm.append(
            {
                "lane": e["lane"],
                "start_us": (int(e["start"]) - t0) / 1_000.0,
                "dur_us": max(1.0, int(e["dur"]) / 1_000.0),
                "label": shorten(str(e.get("label", ""))),
                "kind": str(e.get("kind", "other")),
                "req_id": e.get("req_id"),
            }
        )
    return norm


def build_html(data_obj):
    data_json = json.dumps(data_obj, ensure_ascii=False)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
<title>Nsight Timeline + Requests (Full Events)</title>
<style>
  :root {{
    --bg: #0b1220;
    --panel: #111a2a;
    --line: #26344f;
    --text: #dbe7ff;
    --muted: #9fb0d1;
    --api: #f59e0b;
    --kernel: #60a5fa;
    --memcpy: #34d399;
    --req_in: #a78bfa;
    --req_prefill: #f97316;
    --req_decode: #22c55e;
    --req_token: #38bdf8;
    --req_done: #eab308;
    --req_error: #ef4444;
    --req_other: #94a3b8;
  }}
  body {{ margin:0; font-family: ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto; background:var(--bg); color:var(--text); }}
  .wrap {{ max-width: 1600px; margin: 16px auto; padding: 0 16px; }}
  .card {{ background: var(--panel); border:1px solid var(--line); border-radius:12px; padding:12px; }}
  .row {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:10px; }}
  .row-tight {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }}
  input {{ background:#0d1524; color:var(--text); border:1px solid var(--line); border-radius:8px; padding:6px 8px; width:120px; }}
  button {{ background:#1c2a45; color:var(--text); border:1px solid #324769; border-radius:8px; padding:6px 10px; cursor:pointer; }}
  .meta {{ color: var(--muted); font-size: 13px; }}
  .legend {{ display:flex; gap:12px; font-size:12px; color:var(--muted); flex-wrap:wrap; }}
  .dot {{ width:10px; height:10px; display:inline-block; border-radius:999px; margin-right:6px; }}
  #canvasWrap {{ border:1px solid var(--line); border-radius:10px; background:#0a1120; overflow:auto; max-height:78vh; }}
  canvas {{ width:100%; display:block; background:#0a1120; }}
  #tip {{ position:fixed; pointer-events:none; background:#0e1728; border:1px solid #34496d; color:#e6f0ff; padding:6px 8px; font-size:12px; border-radius:8px; display:none; max-width:700px; z-index:1000; }}
  #groupControls {{ display:flex; gap:6px; flex-wrap:wrap; }}
</style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"card\">
      <div class=\"row\">
        <strong>Nsight Timeline + Request Timeline (Full Events)</strong>
        <span class=\"meta\" id=\"summary\"></span>
      </div>
      <div class=\"row meta\" id=\"profileMeta\"></div>
      <div class=\"row\">
        <label>Start ms <input id=\"startMs\" type=\"number\" step=\"0.1\" value=\"0\"></label>
        <label>Window ms <input id=\"windowMs\" type=\"number\" step=\"0.1\" value=\"0\"></label>
        <button id=\"apply\">Apply</button>
        <button id=\"reset\">Reset</button>
        <button id=\"prevPage\">Prev 1/2 Page</button>
        <button id=\"nextPage\">Next 1/2 Page</button>
        <button id=\"zoomIn\">Zoom In 2x</button>
        <button id=\"zoomOut\">Zoom Out 2x</button>
      </div>
      <div class=\"row-tight\">
        <span class=\"meta\">Request groups:</span>
        <div id=\"groupControls\"></div>
      </div>
      <div class=\"legend\">
        <span><i class=\"dot\" style=\"background:var(--api)\"></i>CUDA API</span>
        <span><i class=\"dot\" style=\"background:var(--kernel)\"></i>Kernel</span>
        <span><i class=\"dot\" style=\"background:var(--memcpy)\"></i>Memcpy</span>
        <span><i class=\"dot\" style=\"background:var(--req_in)\"></i>Req In</span>
        <span><i class=\"dot\" style=\"background:var(--req_prefill)\"></i>Prefill</span>
        <span><i class=\"dot\" style=\"background:var(--req_decode)\"></i>Decode</span>
        <span><i class=\"dot\" style=\"background:var(--req_token)\"></i>Token Out</span>
        <span><i class=\"dot\" style=\"background:var(--req_done)\"></i>Req Done</span>
        <span><i class=\"dot\" style=\"background:var(--req_error)\"></i>Req Error</span>
      </div>
      <div id=\"canvasWrap\"><canvas id=\"cv\" width=\"1560\" height=\"800\"></canvas></div>
      <div class=\"meta\" style=\"margin-top:8px\">Hover to inspect event. Paging: buttons or Left/Right key (half-window step).</div>
    </div>
  </div>
  <div id=\"tip\"></div>
<script>
const DATA = {data_json};
const cv = document.getElementById('cv');
const ctx = cv.getContext('2d');
const tip = document.getElementById('tip');
const allLanes = DATA.lanes;
const groupMap = DATA.group_map || {{}};
const groupState = {{}};
for (const g of Object.keys(groupMap)) groupState[g] = false;

const laneH = 24;
const topPad = 28;
const leftPad = 190;
const rightPad = 20;
const bottomPad = 24;
const axisW = cv.width - leftPad - rightPad;
const totalUs = DATA.total_us;
let viewStartUs = 0;
let viewWinUs = totalUs;

let visibleLanes = [];
let laneIndex = new Map();

const colors = {{
  api:'#f59e0b', kernel:'#60a5fa', memcpy:'#34d399',
  req_in:'#a78bfa', req_prefill:'#f97316', req_decode:'#22c55e', req_token:'#38bdf8',
  req_done:'#eab308', req_error:'#ef4444', req_other:'#94a3b8'
}};

const eventsByLane = new Map(allLanes.map(l=>[l,[]]));
for (const e of DATA.events) {{
  if (!eventsByLane.has(e.lane)) eventsByLane.set(e.lane, []);
  eventsByLane.get(e.lane).push(e);
}}
for (const [k,arr] of eventsByLane.entries()) arr.sort((a,b)=>a.start_us-b.start_us);

function computeVisibleLanes() {{
  const hidden = new Set();
  for (const [g,members] of Object.entries(groupMap)) {{
    if (groupState[g]) {{
      hidden.add(g);
    }} else {{
      for (const m of members) hidden.add(m);
    }}
  }}
  visibleLanes = allLanes.filter(l => !hidden.has(l));
  laneIndex = new Map(visibleLanes.map((l,i)=>[l,i]));
}}

function resizeCanvas() {{
  const needed = Math.max(800, topPad + bottomPad + visibleLanes.length * laneH + 12);
  cv.height = needed;
}}

function xOf(us) {{ return leftPad + ((us - viewStartUs) / viewWinUs) * axisW; }}
function yOf(lane) {{ return topPad + laneIndex.get(lane) * laneH; }}

function drawAxis() {{
  ctx.strokeStyle = '#314160';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(leftPad, topPad - 10);
  ctx.lineTo(leftPad, cv.height - bottomPad);
  ctx.lineTo(cv.width - rightPad, cv.height - bottomPad);
  ctx.stroke();

  const tickN = 8;
  ctx.fillStyle = '#9fb0d1';
  ctx.font = '12px ui-sans-serif';
  for (let i=0;i<=tickN;i++) {{
    const t = viewStartUs + (viewWinUs * i / tickN);
    const x = xOf(t);
    ctx.beginPath(); ctx.moveTo(x, cv.height-bottomPad); ctx.lineTo(x, cv.height-bottomPad+4); ctx.stroke();
    const ms = (t/1000).toFixed(2);
    ctx.fillText(ms + ' ms', x-20, cv.height-6);
  }}
}}

function draw() {{
  computeVisibleLanes();
  resizeCanvas();

  ctx.clearRect(0,0,cv.width,cv.height);
  drawAxis();

  ctx.font = '12px ui-sans-serif';
  for (const lane of visibleLanes) {{
    const y = yOf(lane);
    ctx.fillStyle = '#9fb0d1';
    ctx.fillText(lane, 8, y + 14);

    ctx.strokeStyle = '#1e2b44';
    ctx.beginPath();
    ctx.moveTo(leftPad, y + laneH - 3);
    ctx.lineTo(cv.width-rightPad, y + laneH - 3);
    ctx.stroke();

    const arr = eventsByLane.get(lane) || [];
    for (const e of arr) {{
      const s = e.start_us;
      const en = s + e.dur_us;
      if (en < viewStartUs || s > viewStartUs + viewWinUs) continue;
      const x = xOf(Math.max(s, viewStartUs));
      const x2 = xOf(Math.min(en, viewStartUs + viewWinUs));
      const w = Math.max(1, x2 - x);
      ctx.fillStyle = colors[e.kind] || '#9ca3af';
      ctx.fillRect(x, y + 3, w, laneH - 8);
    }}
  }}

  document.getElementById('summary').textContent =
    `Events: ${{DATA.events.length}} | Visible lanes: ${{visibleLanes.length}}/${{allLanes.length}} | Total: ${{(totalUs/1000).toFixed(2)}} ms`;
  document.getElementById('startMs').value = (viewStartUs/1000).toFixed(3);
  document.getElementById('windowMs').value = (viewWinUs/1000).toFixed(3);

  const p = DATA.session_meta || {{}};
  const pieces = [];
  if (p.model) pieces.push(`model=${{p.model}}`);
  if (p.gpu_name) pieces.push(`gpu=${{p.gpu_name}}`);
  if (p.requests_per_iter != null) pieces.push(`rpi=${{p.requests_per_iter}}`);
  if (p.max_tokens != null) pieces.push(`max_tokens=${{p.max_tokens}}`);
  if (p.profile_iters != null) pieces.push(`profile_iters=${{p.profile_iters}}`);
  pieces.push(`profile_window=${{DATA.meta.profile_window_found ? 'yes' : 'no'}}`);
  document.getElementById('profileMeta').textContent = pieces.join(' | ');

  renderGroupButtons();
}}

function renderGroupButtons() {{
  const box = document.getElementById('groupControls');
  if (!box.dataset.init) {{
    box.dataset.init = '1';
    for (const g of Object.keys(groupMap)) {{
      const b = document.createElement('button');
      b.id = `gbtn_${{g}}`;
      b.onclick = () => {{ groupState[g] = !groupState[g]; draw(); }};
      box.appendChild(b);
    }}
  }}
  for (const g of Object.keys(groupMap)) {{
    const b = document.getElementById(`gbtn_${{g}}`);
    if (!b) continue;
    b.textContent = `${{groupState[g] ? '[-]' : '[+]'}} ${{g}}`;
  }}
}}

function eventAt(mx,my) {{
  if (mx < leftPad || mx > cv.width-rightPad || my < topPad-2 || my > cv.height-bottomPad) return null;
  const li = Math.floor((my - topPad)/laneH);
  if (li < 0 || li >= visibleLanes.length) return null;
  const lane = visibleLanes[li];
  const t = viewStartUs + ((mx-leftPad)/axisW)*viewWinUs;
  const arr = eventsByLane.get(lane) || [];
  for (let i=arr.length-1;i>=0;i--) {{
    const e = arr[i];
    if (e.start_us <= t && t <= e.start_us + e.dur_us) return e;
    if (e.start_us < t - 100000) break;
  }}
  return null;
}}

cv.addEventListener('mousemove', (ev) => {{
  const r = cv.getBoundingClientRect();
  const mx = (ev.clientX-r.left) * (cv.width / r.width);
  const my = (ev.clientY-r.top) * (cv.height / r.height);
  const e = eventAt(mx,my);
  if (!e) {{ tip.style.display='none'; return; }}
  tip.style.display='block';
  tip.style.left = (ev.clientX + 12) + 'px';
  tip.style.top = (ev.clientY + 12) + 'px';
  const req = (e.req_id != null) ? ` | req=${{e.req_id}}` : '';
  tip.textContent = `${{e.kind}} | ${{e.lane}}${{req}} | start=${{(e.start_us/1000).toFixed(3)}}ms dur=${{(e.dur_us/1000).toFixed(6)}}ms | ${{e.label}}`;
}});

cv.addEventListener('mouseleave', () => tip.style.display='none');

document.getElementById('apply').onclick = () => {{
  const s = parseFloat(document.getElementById('startMs').value || '0') * 1000;
  const w = parseFloat(document.getElementById('windowMs').value || '0') * 1000;
  if (w > 0.001) {{
    viewStartUs = Math.max(0, Math.min(totalUs-1, s));
    viewWinUs = Math.max(1, Math.min(totalUs - viewStartUs, w));
    draw();
  }}
}};

document.getElementById('reset').onclick = () => {{
  viewStartUs = 0; viewWinUs = totalUs; draw();
}};

document.getElementById('zoomIn').onclick = () => {{
  const c = viewStartUs + viewWinUs/2;
  viewWinUs = Math.max(50, viewWinUs/2);
  viewStartUs = Math.max(0, Math.min(totalUs-viewWinUs, c-viewWinUs/2));
  draw();
}};

document.getElementById('zoomOut').onclick = () => {{
  const c = viewStartUs + viewWinUs/2;
  viewWinUs = Math.min(totalUs, viewWinUs*2);
  viewStartUs = Math.max(0, Math.min(totalUs-viewWinUs, c-viewWinUs/2));
  draw();
}};

function panHalf(dir) {{
  const step = viewWinUs / 2;
  viewStartUs = Math.max(0, Math.min(totalUs - viewWinUs, viewStartUs + dir * step));
  draw();
}}

document.getElementById('prevPage').onclick = () => panHalf(-1);
document.getElementById('nextPage').onclick = () => panHalf(1);

window.addEventListener('keydown', (ev) => {{
  if (ev.key === 'ArrowLeft') {{ ev.preventDefault(); panHalf(-1); }}
  else if (ev.key === 'ArrowRight') {{ ev.preventDefault(); panHalf(1); }}
}});

draw();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rep", required=True, help="Path to .nsys-rep")
    ap.add_argument("--out", required=True, help="Output .html")
    ap.add_argument("--max-api", type=int, default=3500)
    ap.add_argument("--max-kern", type=int, default=3500)
    ap.add_argument("--req-events", type=str, default="", help="Optional request event JSONL")
    ap.add_argument("--req-group-size", type=int, default=100, help="Request lanes per collapsible group")
    args = ap.parse_args()

    rep = str(Path(args.rep).resolve())
    out = Path(args.out).resolve()

    api_rows = load_report_json(rep, "cuda_api_trace")
    gpu_rows = load_report_json(rep, "cuda_gpu_trace")

    req_rows = []
    session_meta = {}
    req_profile_duration_ns = None
    if args.req_events:
        req_rows, session_meta = load_request_events(args.req_events)
        req_profile_duration_ns = infer_profile_duration_ns(req_rows)

    profile_window = detect_profile_window(rep)
    profiler_api_window = detect_profiler_api_window(api_rows)
    profiler_api_anchor_ns = (
        int(profiler_api_window[0]) if profiler_api_window is not None else None
    )
    selected_window = profile_window
    duration_backfill = False
    gpu_events, gpu_lanes = build_gpu_events(
        api_rows,
        gpu_rows,
        max_api=args.max_api,
        max_kern=args.max_kern,
        window=selected_window,
    )
    if (
        selected_window is None
        and profiler_api_anchor_ns is None
        and req_profile_duration_ns is not None
        and len(gpu_rows) > 0
    ):
        try:
            gpu_end_ns = max(
                int(r.get("Start (ns)", 0) or 0)
                + max(0, int(r.get("Duration (ns)", 0) or 0))
                for r in gpu_rows
            )
            gpu_start_ns = max(0, int(gpu_end_ns - int(req_profile_duration_ns)))
            if gpu_end_ns > gpu_start_ns:
                selected_window = (gpu_start_ns, gpu_end_ns)
                duration_backfill = True
                gpu_events, gpu_lanes = build_gpu_events(
                    api_rows,
                    gpu_rows,
                    max_api=args.max_api,
                    max_kern=args.max_kern,
                    window=selected_window,
                )
        except Exception:
            pass

    mixed_clock_fallback = False
    if (
        selected_window is not None
        and req_profile_duration_ns is not None
        and len(gpu_rows) > 0
        and len(gpu_events) <= 1
    ):
        try:
            gpu_end_ns = max(
                int(r.get("Start (ns)", 0) or 0)
                + max(0, int(r.get("Duration (ns)", 0) or 0))
                for r in gpu_rows
            )
            gpu_start_ns = max(0, int(gpu_end_ns - int(req_profile_duration_ns)))
            if gpu_end_ns > gpu_start_ns:
                selected_window = (gpu_start_ns, gpu_end_ns)
                gpu_events, gpu_lanes = build_gpu_events(
                    api_rows,
                    gpu_rows,
                    max_api=args.max_api,
                    max_kern=args.max_kern,
                    window=selected_window,
                )
                mixed_clock_fallback = True
        except Exception:
            pass

    req_events = []
    req_lanes = []
    group_map = {}
    req_meta = {"request_rows": 0, "request_events": 0, "request_ids": 0}
    if selected_window is not None:
        req_profile_start_ns = int(selected_window[0])
        req_alignment_anchor_ns = int(selected_window[0])
    elif profiler_api_anchor_ns is not None:
        req_profile_start_ns = int(profiler_api_anchor_ns)
        req_alignment_anchor_ns = int(profiler_api_anchor_ns)
    else:
        req_profile_start_ns = None
        req_alignment_anchor_ns = None

    if profile_window is None and profiler_api_anchor_ns is None and selected_window is None:
        req_alignment_method = "window_start"
    elif profile_window is not None:
        req_alignment_method = "nvtx_window_start"
    elif profiler_api_anchor_ns is not None:
        req_alignment_method = "cuda_profiler_api_start"
    elif duration_backfill:
        req_alignment_method = "profile_duration_backfill_start"
    else:
        req_alignment_method = "window_start"
    if req_rows and gpu_events and req_profile_start_ns is None:
        inferred_anchor = infer_request_anchor_ns(req_rows, gpu_events)
        if inferred_anchor is not None:
            req_profile_start_ns = int(inferred_anchor)
            req_alignment_anchor_ns = int(inferred_anchor)
            req_alignment_method = "token_kernel_xcorr"

    if req_rows:
        req_events, req_lanes, group_map, req_meta = build_request_events(
            req_rows,
            profile_start_ns=req_profile_start_ns,
            req_group_size=int(args.req_group_size),
        )

    all_events = gpu_events + req_events
    if all_events:
        t0 = min(int(e["start"]) for e in all_events)
        t1 = max(int(e["start"]) + int(e["dur"]) for e in all_events)
    else:
        t0 = 0
        t1 = 0
    total_us = (t1 - t0) / 1_000.0 if t1 > t0 else 0.0

    all_lanes = gpu_lanes + req_lanes
    norm = normalize_events(all_events, t0)

    data_obj = {
        "rep": rep,
        "events": norm,
        "lanes": all_lanes,
        "group_map": group_map,
        "session_meta": session_meta,
        "total_us": total_us,
        "meta": {
            "api_rows": len(api_rows),
            "gpu_rows": len(gpu_rows),
            "gpu_events": len(gpu_events),
            "request_events": req_meta.get("request_events", 0),
            "request_ids": req_meta.get("request_ids", 0),
            "kept_events": len(norm),
            "max_api": args.max_api,
            "max_kern": args.max_kern,
            "profile_window_found": bool(profile_window),
            "profile_window_start_ns": int(profile_window[0]) if profile_window else None,
            "profile_window_end_ns": int(profile_window[1]) if profile_window else None,
            "profiler_api_window_found": bool(profiler_api_window),
            "profiler_api_window_start_ns": int(profiler_api_window[0]) if profiler_api_window else None,
            "profiler_api_window_end_ns": int(profiler_api_window[1]) if profiler_api_window else None,
            "selected_window_start_ns": int(selected_window[0]) if selected_window else None,
            "selected_window_end_ns": int(selected_window[1]) if selected_window else None,
            "mixed_clock_fallback": bool(mixed_clock_fallback),
            "duration_backfill": bool(duration_backfill),
            "req_alignment_method": req_alignment_method,
            "req_alignment_anchor_ns": req_alignment_anchor_ns,
        },
    }

    out.write_text(build_html(data_obj), encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps(data_obj["meta"], ensure_ascii=False))


if __name__ == "__main__":
    main()
