from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


_HTML = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>hprofile Report</title>
  <link rel=\"stylesheet\" href=\"assets/style.css\" />
</head>
<body>
  <header class=\"hero\">
    <h1>hprofile Augmentation Report</h1>
    <p id=\"run-meta\">Loading...</p>
  </header>

  <main class=\"layout\">
    <section class=\"card\">
      <h2>Global Ratio</h2>
      <pre id=\"global-ratio\"></pre>
    </section>

    <section class=\"card\">
      <h2>Top Streams</h2>
      <div id=\"top-streams\"></div>
    </section>

    <section class=\"card\">
      <h2>Causality Summary</h2>
      <pre id=\"causality-meta\"></pre>
    </section>

    <section class=\"card\">
      <h2>Best Micro-Loop</h2>
      <pre id=\"loop-best\"></pre>
    </section>

    <section class=\"card\">
      <h2>Data Quality</h2>
      <pre id=\"quality\"></pre>
    </section>

    <section class=\"card\">
      <h2>Lineage</h2>
      <div id=\"lineage-list\"></div>
    </section>
  </main>

  <script src=\"assets/data.js\"></script>
  <script src=\"assets/app.js\"></script>
</body>
</html>
"""


_STYLE = """:root {
  --bg: #f6f8fb;
  --card: #ffffff;
  --text: #1d2733;
  --muted: #5c6875;
  --accent: #0057b8;
  --line: #d9e1ec;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "IBM Plex Sans", "Noto Sans", sans-serif;
  color: var(--text);
  background: radial-gradient(circle at top right, #e7f0ff, var(--bg) 35%);
}
.hero {
  padding: 24px 20px 10px;
  border-bottom: 1px solid var(--line);
}
.hero h1 { margin: 0 0 6px; font-size: 26px; }
.hero p { margin: 0; color: var(--muted); }
.layout {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  padding: 16px 20px 24px;
}
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px;
  box-shadow: 0 2px 10px rgba(23, 39, 68, 0.04);
}
.card h2 {
  margin: 0 0 10px;
  font-size: 16px;
  color: var(--accent);
}
pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.4;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
th, td {
  border-bottom: 1px solid var(--line);
  padding: 6px 4px;
  text-align: left;
}
"""


_APP_JS = """(function () {
  const unified = window.HPROFILE_UNIFIED || {};
  const lineage = window.HPROFILE_LINEAGE || {};

  const run = unified.run || {};
  const summary = unified.summary || {};
  const streams = (unified.streams && unified.streams.top_streams) || [];
  const causality = (unified.causality && unified.causality.meta) || {};
  const loopBest = (unified.micro_loops && unified.micro_loops.best) || {};
  const quality = unified.quality || {};

  const runMeta = document.getElementById('run-meta');
  runMeta.textContent = `run_id=${run.run_id || '-'} | tasks=${run.task_count || 0} | streams=${run.stream_count || 0}`;

  document.getElementById('global-ratio').textContent = JSON.stringify(summary.global || {}, null, 2);
  document.getElementById('causality-meta').textContent = JSON.stringify(causality, null, 2);
  document.getElementById('loop-best').textContent = JSON.stringify(loopBest, null, 2);
  document.getElementById('quality').textContent = JSON.stringify(quality, null, 2);

  renderTopStreams(streams.slice(0, 12));
  renderLineage((lineage.metrics || []).slice(0, 20));

  function renderTopStreams(rows) {
    const root = document.getElementById('top-streams');
    if (!rows.length) {
      root.textContent = 'No stream rows.';
      return;
    }
    const cols = ['device_id', 'stream_id', 'total_task_us', 'wait_ratio_task', 'comm_ratio_task', 'exec_ratio_task', 'idle_ratio_span'];
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const trh = document.createElement('tr');
    cols.forEach((c) => {
      const th = document.createElement('th');
      th.textContent = c;
      trh.appendChild(th);
    });
    thead.appendChild(trh);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    rows.forEach((r) => {
      const tr = document.createElement('tr');
      cols.forEach((c) => {
        const td = document.createElement('td');
        td.textContent = r[c] === undefined ? '' : String(r[c]);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    root.appendChild(table);
  }

  function renderLineage(metrics) {
    const root = document.getElementById('lineage-list');
    if (!metrics.length) {
      root.textContent = 'No lineage metrics.';
      return;
    }
    const ul = document.createElement('ul');
    metrics.forEach((m) => {
      const li = document.createElement('li');
      li.textContent = `${m.id}: ${m.name}`;
      ul.appendChild(li);
    });
    root.appendChild(ul);
  }
})();
"""


def render_web(web_dir: Path, unified_profile: Dict[str, object], lineage: Dict[str, object]) -> None:
    assets_dir = web_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    (web_dir / "index.html").write_text(_HTML, encoding="utf-8")
    (assets_dir / "style.css").write_text(_STYLE, encoding="utf-8")
    (assets_dir / "app.js").write_text(_APP_JS, encoding="utf-8")

    data_js = (
        "window.HPROFILE_UNIFIED = "
        + json.dumps(unified_profile, ensure_ascii=False)
        + ";\nwindow.HPROFILE_LINEAGE = "
        + json.dumps(lineage, ensure_ascii=False)
        + ";\n"
    )
    (assets_dir / "data.js").write_text(data_js, encoding="utf-8")
