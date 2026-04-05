from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="imonitor web", version="0.1.0")


def _db_path() -> Path:
    return Path(os.getenv("IMONITOR_DB", "./runs/integrated_demo/metrics.sqlite")).expanduser().resolve()


def _connect_db() -> sqlite3.Connection:
    db_path = _db_path()
    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>imonitor web</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 16px; color: #111; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; align-items: center; }
    .card { border: 1px solid #ddd; border-radius: 10px; padding: 10px; margin-bottom: 10px; }
    label { font-size: 13px; color: #444; }
    select, input, button { font-size: 13px; padding: 4px 6px; }
    #chart { height: 440px; width: 100%; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #ddd; padding: 4px 6px; font-size: 12px; }
    th { background: #f7f7f7; text-align: left; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  </style>
</head>
<body>
  <h2>imonitor Web</h2>
  <div class="card">
    <div class="row">
      <label>Run:
        <select id="runSelect"></select>
      </label>
      <label>Metric:
        <select id="metricSelect"></select>
      </label>
      <label>Sensor:
        <select id="sensorSelect"><option value="">(all)</option></select>
      </label>
      <label>PID:
        <select id="pidSelect"><option value="">(all)</option></select>
      </label>
      <label>Mode:
        <select id="modeSelect">
          <option value="rollup">rollup</option>
          <option value="raw">raw</option>
        </select>
      </label>
      <label>Bucket(s):
        <input id="bucketSec" type="number" value="1" min="1" step="1" style="width:70px;" />
      </label>
      <label>Raw limit:
        <input id="rawLimit" type="number" value="8000" min="100" step="100" style="width:90px;" />
      </label>
      <button id="refreshBtn">Refresh</button>
    </div>
    <div class="mono" id="metaLine"></div>
  </div>

  <div class="card"><div id="chart"></div></div>
  <div class="card">
    <h4>Series Preview</h4>
    <table id="previewTable">
      <thead><tr><th>ts_ns</th><th>sensor</th><th>metric</th><th>pid</th><th>value</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <script>
    const chart = echarts.init(document.getElementById("chart"));
    const runSelect = document.getElementById("runSelect");
    const metricSelect = document.getElementById("metricSelect");
    const sensorSelect = document.getElementById("sensorSelect");
    const pidSelect = document.getElementById("pidSelect");
    const modeSelect = document.getElementById("modeSelect");
    const bucketSec = document.getElementById("bucketSec");
    const rawLimit = document.getElementById("rawLimit");
    const metaLine = document.getElementById("metaLine");

    async function jget(url) {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
      return r.json();
    }

    function setOptions(selectEl, items, selectedValue = "") {
      const current = selectedValue || selectEl.value;
      selectEl.innerHTML = "";
      for (const it of items) {
        const opt = document.createElement("option");
        opt.value = it.value;
        opt.textContent = it.label;
        selectEl.appendChild(opt);
      }
      if (current) selectEl.value = current;
    }

    async function loadRuns() {
      const data = await jget("/api/runs?limit=50");
      const opts = data.runs.map(r => ({ value: r.run_id, label: `${r.run_id} | ${r.duration_sec.toFixed(2)}s | rc=${r.exit_code}` }));
      setOptions(runSelect, opts);
    }

    async function loadRunMeta() {
      const runId = runSelect.value;
      if (!runId) return;

      const metricData = await jget(`/api/run/${runId}/metrics`);
      const metricOpts = metricData.metrics.map(m => ({ value: m.metric, label: `${m.metric} (${m.sensor})` }));
      setOptions(metricSelect, metricOpts, "cpu.util_pct");

      const sensorOpts = [{ value: "", label: "(all)" }].concat(metricData.sensors.map(s => ({ value: s, label: s })));
      setOptions(sensorSelect, sensorOpts);

      const pidData = await jget(`/api/run/${runId}/pids`);
      const pidOpts = [{ value: "", label: "(all)" }].concat(
        pidData.pids.map(p => ({ value: String(p.pid), label: `${p.pid} (${p.comm || "-"})` }))
      );
      setOptions(pidSelect, pidOpts);
    }

    function groupRows(rows) {
      const grouped = new Map();
      for (const r of rows) {
        const key = r.pid !== null ? `pid:${r.pid}` : `${r.sensor}`;
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push([Math.floor(r.ts_ns / 1_000_000), r.value]);
      }
      return grouped;
    }

    function renderPreview(rows) {
      const body = document.querySelector("#previewTable tbody");
      body.innerHTML = "";
      for (const r of rows.slice(0, 40)) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${r.ts_ns}</td><td>${r.sensor}</td><td>${r.metric}</td><td>${r.pid ?? ""}</td><td>${Number(r.value).toFixed(4)}</td>`;
        body.appendChild(tr);
      }
    }

    async function refreshSeries() {
      const runId = runSelect.value;
      if (!runId) return;
      const metric = metricSelect.value;
      const sensor = sensorSelect.value;
      const pid = pidSelect.value;
      const useRollup = modeSelect.value === "rollup";
      const bsec = parseInt(bucketSec.value || "1", 10);
      const limit = parseInt(rawLimit.value || "8000", 10);
      const qs = new URLSearchParams();
      qs.set("metric", metric);
      qs.set("rollup", useRollup ? "true" : "false");
      qs.set("bucket_ns", String(Math.max(1, bsec) * 1000000000));
      qs.set("limit", String(Math.max(100, limit)));
      if (sensor) qs.set("sensor", sensor);
      if (pid) qs.set("pid", pid);

      const data = await jget(`/api/run/${runId}/series?${qs.toString()}`);
      const rows = data.rows || [];
      renderPreview(rows);
      metaLine.textContent = `db=${data.db_path} | run=${runId} | mode=${data.mode} | rows=${rows.length}`;

      const grouped = groupRows(rows);
      const series = [];
      for (const [name, points] of grouped.entries()) {
        series.push({
          name,
          type: "line",
          showSymbol: false,
          sampling: "lttb",
          data: points
        });
      }

      chart.setOption({
        title: { text: `${metric} (${data.mode})` },
        tooltip: { trigger: "axis" },
        legend: { type: "scroll" },
        xAxis: { type: "time" },
        yAxis: { type: "value", scale: true },
        grid: { left: 40, right: 20, top: 40, bottom: 30 },
        series
      });
    }

    document.getElementById("refreshBtn").addEventListener("click", refreshSeries);
    runSelect.addEventListener("change", async () => { await loadRunMeta(); await refreshSeries(); });
    metricSelect.addEventListener("change", refreshSeries);
    sensorSelect.addEventListener("change", refreshSeries);
    pidSelect.addEventListener("change", refreshSeries);
    modeSelect.addEventListener("change", refreshSeries);

    (async () => {
      try {
        await loadRuns();
        await loadRunMeta();
        await refreshSeries();
      } catch (e) {
        metaLine.textContent = `Error: ${e.message}`;
      }
    })();
  </script>
</body>
</html>
"""


@app.get("/api/runs")
def api_runs(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    with _connect_db() as conn:
        rows = conn.execute(
            """
            SELECT run_id, command, start_ns, end_ns, duration_sec, exit_code, sample_count
            FROM runs
            ORDER BY start_ns DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"db_path": str(_db_path()), "runs": [dict(r) for r in rows]}


@app.get("/api/run/{run_id}/metrics")
def api_run_metrics(run_id: str) -> dict[str, Any]:
    with _connect_db() as conn:
        rows = conn.execute(
            """
            SELECT sensor, metric, unit
            FROM metrics_agg
            WHERE run_id = ?
            ORDER BY sensor, metric
            """,
            (run_id,),
        ).fetchall()
    metrics = [dict(r) for r in rows]
    sensors = sorted({m["sensor"] for m in metrics})
    return {"run_id": run_id, "metrics": metrics, "sensors": sensors}


@app.get("/api/run/{run_id}/pids")
def api_run_pids(run_id: str) -> dict[str, Any]:
    with _connect_db() as conn:
        rows = conn.execute(
            """
            SELECT pid, comm, first_seen_ns, last_seen_ns
            FROM processes
            WHERE run_id = ?
            ORDER BY pid
            """,
            (run_id,),
        ).fetchall()
    return {"run_id": run_id, "pids": [dict(r) for r in rows]}


@app.get("/api/run/{run_id}/series")
def api_run_series(
    run_id: str,
    metric: str = Query(...),
    sensor: str | None = Query(default=None),
    pid: int | None = Query(default=None),
    rollup: bool = Query(default=True),
    bucket_ns: int = Query(default=1_000_000_000, ge=1_000_000),
    limit: int = Query(default=8000, ge=100, le=200000),
) -> dict[str, Any]:
    with _connect_db() as conn:
        if rollup:
            rows = conn.execute(
                """
                SELECT
                    bucket_start_ns AS ts_ns,
                    sensor, metric, pid, unit,
                    avg AS value,
                    min, max, p95, sample_count
                FROM metrics_rollup
                WHERE run_id = ?
                  AND metric = ?
                  AND bucket_ns = ?
                  AND (? IS NULL OR sensor = ?)
                  AND (? IS NULL OR pid = ?)
                ORDER BY ts_ns
                """,
                (run_id, metric, bucket_ns, sensor, sensor, pid, pid),
            ).fetchall()
            mode = "rollup"
        else:
            rows = conn.execute(
                """
                SELECT ts_ns, sensor, metric, pid, unit, value
                FROM metrics_raw
                WHERE run_id = ?
                  AND metric = ?
                  AND (? IS NULL OR sensor = ?)
                  AND (? IS NULL OR pid = ?)
                ORDER BY ts_ns
                LIMIT ?
                """,
                (run_id, metric, sensor, sensor, pid, pid, limit),
            ).fetchall()
            mode = "raw"

    return {"db_path": str(_db_path()), "run_id": run_id, "mode": mode, "rows": [dict(r) for r in rows]}

