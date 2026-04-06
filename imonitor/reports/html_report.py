from __future__ import annotations

from pathlib import Path


def _render_rows(rows: list[dict[str, object]], columns: list[str]) -> str:
    if not rows:
        return "<p>(empty)</p>"
    head = "".join(f"<th>{c}</th>" for c in columns)
    body_parts = []
    for row in rows:
        cells = "".join(f"<td>{row.get(c, '')}</td>" for c in columns)
        body_parts.append(f"<tr>{cells}</tr>")
    body = "".join(body_parts)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def write_html_report(path: Path, summary: dict[str, object]) -> None:
    run = summary["run"]
    top_cpu = summary.get("top_cpu", [])
    top_mem = summary.get("top_mem", [])

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>imonitor report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 24px; color: #111; }}
    h1, h2 {{ margin: 0.4em 0; }}
    .card {{ padding: 12px 14px; border: 1px solid #ddd; border-radius: 10px; margin: 10px 0; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 8px; font-size: 13px; }}
    th {{ background: #f6f6f6; text-align: left; }}
    code {{ background: #f5f5f5; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>imonitor report</h1>
  <div class=\"card\">
    <p><b>run_id:</b> {run['run_id']}</p>
    <p><b>command:</b> <code>{run['command']}</code></p>
    <p><b>duration_sec:</b> {run['duration_sec']}</p>
    <p><b>exit_code:</b> {run['exit_code']}</p>
    <p><b>sample_count:</b> {run['sample_count']}</p>
    <p><b>peak_total_cpu_pct:</b> {run['peak_total_cpu_pct']}</p>
    <p><b>peak_total_rss_bytes:</b> {run['peak_total_rss_bytes']}</p>
  </div>

  <h2>Top CPU</h2>
  {_render_rows(top_cpu, ['pid', 'max', 'avg', 'sample_count', 'sensor'])}

  <h2>Top Memory</h2>
  {_render_rows(top_mem, ['pid', 'max', 'avg', 'sample_count', 'sensor'])}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
