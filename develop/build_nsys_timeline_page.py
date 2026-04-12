#!/usr/bin/env python3
import argparse
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


def load_report_json(rep_path: str, report_name: str):
    out = subprocess.check_output(
        ["nsys", "stats", "-q", "-f", "json", "--report", report_name, rep_path],
        text=True,
    )
    return json.loads(out)


def shorten(name: str, n: int = 92) -> str:
    if len(name) <= n:
        return name
    return name[: n - 3] + "..."


def build_events(api_rows, gpu_rows, max_api=3500, max_kern=3500):
    api_candidates = []
    for r in api_rows:
        name = str(r.get("Name", ""))
        if not name.startswith(API_KEEP_PREFIX):
            continue
        dur = int(r.get("Duration (ns)", 0) or 0)
        if dur <= 0:
            continue
        api_candidates.append(
            {
                "lane": "CPU CUDA API",
                "start": int(r.get("Start (ns)", 0) or 0),
                "dur": dur,
                "label": name,
                "kind": "api",
            }
        )

    if len(api_candidates) <= max_api:
        api_events = sorted(api_candidates, key=lambda x: x["start"])
    else:
        # Mixed sampling for API lane:
        # 1) keep a slice of longest calls for "important stalls"
        # 2) add timeline-uniform samples to preserve temporal/context diversity
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
        if dur <= 0:
            continue
        stream = str(r.get("Strm", ""))
        lane = f"GPU Stream {stream}" if stream else "GPU Stream ?"
        ev = {
            "lane": lane,
            "start": int(r.get("Start (ns)", 0) or 0),
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
    if not events:
        return [], [], 0, 0

    t0 = min(e["start"] for e in events)
    t1 = max(e["start"] + e["dur"] for e in events)

    lanes = ["CPU CUDA API"]
    gpu_lanes = sorted(
        {e["lane"] for e in events if e["lane"].startswith("GPU Stream")},
        key=lambda s: int(s.split()[-1]) if s.split()[-1].isdigit() else 10**9,
    )
    lanes.extend(gpu_lanes)

    norm = []
    for e in events:
        norm.append(
            {
                "lane": e["lane"],
                "start_us": (e["start"] - t0) / 1_000.0,
                "dur_us": e["dur"] / 1_000.0,
                "label": shorten(e["label"]),
                "kind": e["kind"],
            }
        )

    return norm, lanes, t0, t1


def build_html(data_obj):
    data_json = json.dumps(data_obj, ensure_ascii=False)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
<title>Nsight Timeline (Simplified)</title>
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
  }}
  body {{ margin:0; font-family: ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto; background:var(--bg); color:var(--text); }}
  .wrap {{ max-width: 1500px; margin: 20px auto; padding: 0 16px; }}
  .card {{ background: var(--panel); border:1px solid var(--line); border-radius:12px; padding:12px; }}
  .row {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:10px; }}
  input {{ background:#0d1524; color:var(--text); border:1px solid var(--line); border-radius:8px; padding:6px 8px; width:120px; }}
  button {{ background:#1c2a45; color:var(--text); border:1px solid #324769; border-radius:8px; padding:6px 10px; cursor:pointer; }}
  .meta {{ color: var(--muted); font-size: 13px; }}
  .legend {{ display:flex; gap:14px; font-size:13px; color:var(--muted); }}
  .dot {{ width:10px; height:10px; display:inline-block; border-radius:999px; margin-right:6px; }}
  canvas {{ width:100%; border:1px solid var(--line); border-radius:10px; background:#0a1120; }}
  #tip {{ position:fixed; pointer-events:none; background:#0e1728; border:1px solid #34496d; color:#e6f0ff; padding:6px 8px; font-size:12px; border-radius:8px; display:none; max-width:560px; z-index:1000; }}
</style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"card\">
      <div class=\"row\">
        <strong>Nsight Timeline (Simplified)</strong>
        <span class=\"meta\" id=\"summary\"></span>
      </div>
      <div class=\"row\">
        <label>Start ms <input id=\"startMs\" type=\"number\" step=\"0.1\" value=\"0\"></label>
        <label>Window ms <input id=\"windowMs\" type=\"number\" step=\"0.1\" value=\"0\"></label>
        <button id=\"apply\">Apply</button>
        <button id=\"reset\">Reset</button>
        <button id=\"prevPage\">Prev 1/2 Page</button>
        <button id=\"nextPage\">Next 1/2 Page</button>
        <button id=\"zoomIn\">Zoom In 2x</button>
        <button id=\"zoomOut\">Zoom Out 2x</button>
        <div class=\"legend\">
          <span><i class=\"dot\" style=\"background:var(--api)\"></i>CUDA API</span>
          <span><i class=\"dot\" style=\"background:var(--kernel)\"></i>Kernel</span>
          <span><i class=\"dot\" style=\"background:var(--memcpy)\"></i>Memcpy</span>
        </div>
      </div>
      <canvas id=\"cv\" width=\"1460\" height=\"800\"></canvas>
      <div class=\"meta\" style=\"margin-top:8px\">Hover to inspect event. Paging: buttons or Left/Right key (half-window step). This view is sampled (long/important events prioritized) for browser performance.</div>
    </div>
  </div>
  <div id=\"tip\"></div>
<script>
const DATA = {data_json};
const cv = document.getElementById('cv');
const ctx = cv.getContext('2d');
const tip = document.getElementById('tip');
const lanes = DATA.lanes;
const laneH = 26;
const topPad = 28;
const leftPad = 160;
const rightPad = 20;
const bottomPad = 24;
const axisW = cv.width - leftPad - rightPad;
const totalUs = DATA.total_us;
let viewStartUs = 0;
let viewWinUs = totalUs;
const colors = {{ api:'#f59e0b', kernel:'#60a5fa', memcpy:'#34d399' }};

const laneIndex = new Map(lanes.map((l,i)=>[l,i]));
const eventsByLane = new Map(lanes.map(l=>[l,[]]));
for (const e of DATA.events) eventsByLane.get(e.lane).push(e);

for (const l of lanes) eventsByLane.get(l).sort((a,b)=>a.start_us-b.start_us);

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
    ctx.fillText(ms + ' ms', x-18, cv.height-6);
  }}
}}

function draw() {{
  ctx.clearRect(0,0,cv.width,cv.height);
  drawAxis();

  ctx.font = '12px ui-sans-serif';
  for (const lane of lanes) {{
    const y = yOf(lane);
    ctx.fillStyle = '#9fb0d1';
    ctx.fillText(lane, 8, y + 14);
    ctx.strokeStyle = '#1e2b44';
    ctx.beginPath();
    ctx.moveTo(leftPad, y + laneH - 3);
    ctx.lineTo(cv.width-rightPad, y + laneH - 3);
    ctx.stroke();

    for (const e of eventsByLane.get(lane)) {{
      const s = e.start_us;
      const en = s + e.dur_us;
      if (en < viewStartUs || s > viewStartUs + viewWinUs) continue;
      const x = xOf(Math.max(s, viewStartUs));
      const x2 = xOf(Math.min(en, viewStartUs + viewWinUs));
      const w = Math.max(1, x2 - x);
      ctx.fillStyle = colors[e.kind] || '#aaa';
      ctx.fillRect(x, y + 3, w, laneH - 8);
    }}
  }}

  document.getElementById('summary').textContent =
    `Events: ${{DATA.events.length}} | Lanes: ${{lanes.length}} | Total window: ${{(totalUs/1000).toFixed(2)}} ms`;
  document.getElementById('startMs').value = (viewStartUs/1000).toFixed(3);
  document.getElementById('windowMs').value = (viewWinUs/1000).toFixed(3);
}}

function eventAt(mx,my) {{
  if (mx < leftPad || mx > cv.width-rightPad || my < topPad-2 || my > cv.height-bottomPad) return null;
  const li = Math.floor((my - topPad)/laneH);
  if (li < 0 || li >= lanes.length) return null;
  const lane = lanes[li];
  const t = viewStartUs + ((mx-leftPad)/axisW)*viewWinUs;
  const arr = eventsByLane.get(lane);
  for (let i=arr.length-1;i>=0;i--) {{
    const e = arr[i];
    if (e.start_us <= t && t <= e.start_us + e.dur_us) return e;
    if (e.start_us < t - 80000) break;
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
  tip.textContent = `${{e.kind}} | ${{e.lane}} | start=${{(e.start_us/1000).toFixed(3)}}ms dur=${{(e.dur_us/1000).toFixed(6)}}ms | ${{e.label}}`;
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
  if (ev.key === 'ArrowLeft') {{
    ev.preventDefault();
    panHalf(-1);
  }} else if (ev.key === 'ArrowRight') {{
    ev.preventDefault();
    panHalf(1);
  }}
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
    args = ap.parse_args()

    rep = str(Path(args.rep).resolve())
    out = Path(args.out).resolve()

    api_rows = load_report_json(rep, "cuda_api_trace")
    gpu_rows = load_report_json(rep, "cuda_gpu_trace")

    events, lanes, t0, t1 = build_events(api_rows, gpu_rows, max_api=args.max_api, max_kern=args.max_kern)
    total_us = (t1 - t0) / 1_000.0 if t1 > t0 else 0.0

    data_obj = {
        "rep": rep,
        "events": events,
        "lanes": lanes,
        "total_us": total_us,
        "meta": {
            "api_rows": len(api_rows),
            "gpu_rows": len(gpu_rows),
            "kept_events": len(events),
            "max_api": args.max_api,
            "max_kern": args.max_kern,
        },
    }

    out.write_text(build_html(data_obj), encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps(data_obj["meta"], ensure_ascii=False))


if __name__ == "__main__":
    main()
