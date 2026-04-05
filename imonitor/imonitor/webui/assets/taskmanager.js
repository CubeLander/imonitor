(() => {
  const PAGE_COPY = {
    performance: {
      title: "Performance",
      subtitle: "CPU, memory, disk, ethernet, GPU, and PCIe at a glance.",
    },
    processes: {
      title: "Processes",
      subtitle: "Real-time system process table with monitored rows tagged.",
    },
    sql: {
      title: "SQL",
      subtitle: "Read-only SQL against the daemon SQLite store.",
    },
  };

  const RESOURCE_LABELS = {
    cpu: "CPU",
    memory: "Memory",
    disk: "Disk",
    ethernet: "Ethernet",
    gpu: "GPU",
    pcie: "PCIe",
  };

  const state = {
    activeTab: "performance",
    perfResource: "cpu",
    runId: null,
    runs: [],
    latestRunTsNs: null,
    latestSystemTsNs: null,
    latestProcessTsNs: null,
    inFlight: false,
    timer: null,
    systemLatest: null,
    systemPerf: null,
    runSnapshot: null,
    runPerf: null,
    runProcesses: [],
    runCapabilities: {},
    processRows: [],
    processCapabilities: {},
    processCounts: { total: 0, monitored: 0, system: 0 },
    procSort: { key: "cpu_pct", dir: "desc" },
    followRunning: true,
  };

  const charts = {
    perfPrimary: echarts.init(document.getElementById("perfChartPrimary")),
    perfSecondary: echarts.init(document.getElementById("perfChartSecondary")),
  };

  function escHtml(v) {
    return String(v ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function fmtBytes(n) {
    const x = Number(n || 0);
    if (x < 1024) return `${x.toFixed(0)} B`;
    if (x < 1024 ** 2) return `${(x / 1024).toFixed(1)} KB`;
    if (x < 1024 ** 3) return `${(x / 1024 ** 2).toFixed(1)} MB`;
    return `${(x / 1024 ** 3).toFixed(2)} GB`;
  }

  function fmtBps(n) {
    return `${fmtBytes(n)}/s`;
  }

  function fmtPct(n) {
    return `${Number(n || 0).toFixed(1)}%`;
  }

  function toMs(tsNs) {
    return Math.floor(Number(tsNs || 0) / 1e6);
  }

  function fmtTime(tsNs) {
    if (!tsNs) return "-";
    return new Date(toMs(tsNs)).toLocaleTimeString();
  }

  function fmtValueOrDash(v) {
    return v === null || v === undefined || v === "" ? "-" : String(v);
  }

  function fmtBytesPair(current, total) {
    const cur = fmtBytes(current);
    if (Number(total || 0) > 0) {
      return `${cur} / ${fmtBytes(total)}`;
    }
    return cur;
  }

  function fmtRatePair(a, b) {
    return `${fmtBps(a)} / ${fmtBps(b)}`;
  }

  function clamp01(v) {
    return Math.max(0, Math.min(1, Number(v || 0)));
  }

  function meterHtml(label, ratio) {
    const pct = clamp01(ratio) * 100;
    return `
      <div class="meter">
        <div class="meter-fill" style="width:${pct.toFixed(1)}%;"></div>
        <span class="meter-label">${escHtml(label)}</span>
      </div>
    `;
  }

  function lineData(rows) {
    return (rows || []).map((r) => [toMs(r.ts_ns), Number(r.value || 0)]);
  }

  function sortedChannelKeys(obj) {
    return Object.keys(obj || {}).sort((a, b) => {
      const ma = /^gpu(\d+)$/.exec(String(a));
      const mb = /^gpu(\d+)$/.exec(String(b));
      if (ma && mb) return Number(ma[1]) - Number(mb[1]);
      if (ma) return -1;
      if (mb) return 1;
      return String(a).localeCompare(String(b));
    });
  }

  function collectHostPcieChannelsFromSummary(summary) {
    const out = {};
    for (const [metric, value] of Object.entries(summary || {})) {
      const m = /^system\.pcie\.(gpu[^.]+)\.(rx_bytes_s|tx_bytes_s|link\.gen\.current|link\.gen\.max|link\.width\.current|link\.width\.max)$/.exec(String(metric));
      if (!m) continue;
      const channel = m[1];
      const field = m[2].replaceAll(".", "_");
      const row = out[channel] || {};
      row[field] = Number(value || 0);
      out[channel] = row;
    }
    return out;
  }

  function collectHostPcieChannelSeries(series) {
    const out = {};
    for (const [metric, rows] of Object.entries(series || {})) {
      const m = /^system\.pcie\.(gpu[^.]+)\.(rx_bytes_s|tx_bytes_s)$/.exec(String(metric));
      if (!m) continue;
      const channel = m[1];
      const field = m[2];
      const row = out[channel] || { rx_bytes_s: [], tx_bytes_s: [] };
      row[field] = rows || [];
      out[channel] = row;
    }
    return out;
  }

  function cardHtml(label, value, hint = "") {
    return `
      <div class="metric-card">
        <div class="k">${escHtml(label)}</div>
        <div class="v">${escHtml(value)}</div>
        ${hint ? `<div class="h">${escHtml(hint)}</div>` : ""}
      </div>
    `;
  }

  async function jget(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(await r.text());
    return await r.json();
  }

  async function jpost(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    return await r.json();
  }

  function updateTopNav() {
    document.querySelectorAll(".nav-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === state.activeTab);
    });

    const page = PAGE_COPY[state.activeTab] || PAGE_COPY.performance;
    document.getElementById("pageTitle").textContent = page.title;
    document.getElementById("pageSubtitle").textContent = page.subtitle;
  }

  function setTab(name) {
    state.activeTab = name;
    document.getElementById("tab-performance").classList.toggle("hidden", name !== "performance");
    document.getElementById("tab-processes").classList.toggle("hidden", name !== "processes");
    document.getElementById("tab-sql").classList.toggle("hidden", name !== "sql");
    updateTopNav();
    renderDashboard();
    if (name === "performance") {
      scheduleChartResize();
    }
  }

  function renderRuns() {
    const root = document.getElementById("runList");
    if (!root) return;
    root.innerHTML = "";
    if (!state.runs.length) {
      root.innerHTML = '<div class="muted" style="padding:10px;">No runs</div>';
      return;
    }

    for (const run of state.runs) {
      const btn = document.createElement("button");
      btn.className = "run-item" + (run.run_id === state.runId ? " active" : "");
      const status = run.status || "completed";
      const dur = Number(run.duration_sec || 0).toFixed(2);
      btn.innerHTML = `
        <div class="run-id">${escHtml(run.run_id)}</div>
        <div class="muted" style="margin-top:4px;">${escHtml(run.command || "")}</div>
        <div class="muted" style="margin-top:4px;">${dur}s | samples=${run.sample_count ?? 0}</div>
        <span class="status ${escHtml(status)}">${escHtml(status)}</span>
      `;
      btn.addEventListener("click", async () => {
        state.runId = run.run_id;
        document.getElementById("runPill").textContent = `run=${state.runId}`;
        if (state.followRunning && run.status !== "running") {
          state.followRunning = false;
          document.getElementById("followRunning").checked = false;
        }
        renderRuns();
        await refreshRunOnly();
        renderDashboard();
      });
      root.appendChild(btn);
    }
  }

  async function loadRuns() {
    const payload = await jget("/api/taskmanager/runs?limit=80");
    state.runs = payload.runs || [];
    if (!state.runs.length) {
      state.runId = null;
      document.getElementById("runPill").textContent = "run=none";
    } else {
      const running = state.runs.find((r) => r.status === "running");
      if (state.followRunning && running) {
        state.runId = running.run_id;
      } else if (state.followRunning && !running) {
        state.runId = null;
      } else if (!state.runId || !state.runs.some((r) => r.run_id === state.runId)) {
        state.runId = state.runs[0].run_id;
      }
      document.getElementById("runPill").textContent = state.runId ? `run=${state.runId}` : "run=none";
    }
    renderRuns();
  }

  function renderPerformanceNav() {
    const summary = state.systemLatest?.summary || {};

    const cpu = fmtPct(summary["system.cpu.util_pct"]);
    const memUsed = summary["system.mem.used_bytes"];
    const memTotal = summary["system.mem.total_bytes"];
    const disk = fmtRatePair(summary["system.disk.read_bps"], summary["system.disk.write_bps"]);
    const net = fmtRatePair(summary["system.net.rx_bps"], summary["system.net.tx_bps"]);
    const gpu = `${fmtPct(summary["system.gpu.util_pct"])} | ${fmtBytes(summary["system.gpu.mem_used_bytes"])}`;
    const pcie = fmtRatePair(summary["system.pcie.rx_bytes_s"], summary["system.pcie.tx_bytes_s"]);
    const memoryText = fmtBytesPair(memUsed, memTotal);

    const values = {
      cpu,
      memory: memoryText,
      disk,
      ethernet: net,
      gpu,
      pcie,
    };

    document.querySelectorAll(".perf-nav-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.resource === state.perfResource);
      const key = btn.dataset.resource;
      const meta = btn.querySelector(".perf-nav-meta");
      if (meta) {
        meta.textContent = values[key] || "--";
      }
    });
  }

  function renderPerformanceCards(cards) {
    document.getElementById("perfSummaryCards").innerHTML = cards.join("");
  }

  function renderPerformanceView() {
    renderPerformanceNav();

    const systemSummary = state.systemLatest?.summary || {};
    const systemSeries = state.systemPerf?.series || {};
    const runSummary = state.runSnapshot?.summary || {};
    const runSeries = state.runPerf?.series || {};
    const latestStamp = state.latestRunTsNs || state.latestSystemTsNs || state.latestProcessTsNs;
    const selectedRun = state.runSnapshot?.run || null;
    const hasRun = Boolean(state.runId && selectedRun);
    const resource = state.perfResource;
    const resourceLabel = RESOURCE_LABELS[resource] || "CPU";

    document.getElementById("perfResourceTitle").textContent = resourceLabel;
    document.getElementById("perfResourcePill").textContent = `resource=${resource}`;
    document.getElementById("perfResourceStamp").textContent = `updated=${fmtTime(latestStamp)}`;

    const perfSecondaryBox = document.getElementById("perfSecondaryBox");
    perfSecondaryBox.classList.add("hidden");
    charts.perfSecondary.clear();

    let subtitle = "";
    let notes = "";
    let cards = [];
    let chartTitle = "";
    let yAxis = [{ type: "value", min: 0 }];
    let legend = [];
    let series = [];

    switch (resource) {
      case "memory":
        subtitle = hasRun
          ? `Host memory vs monitored run ${state.runId}.`
          : "Host memory with no monitored run selected.";
        cards = [
          cardHtml("Host Used", fmtBytes(systemSummary["system.mem.used_bytes"]), fmtBytesPair(systemSummary["system.mem.used_bytes"], systemSummary["system.mem.total_bytes"])),
          cardHtml("Host Total", fmtBytes(systemSummary["system.mem.total_bytes"]), "Physical memory"),
          cardHtml("Run RSS", hasRun ? fmtBytes(runSummary.mem_total_bytes) : "No run", hasRun ? `Processes: ${state.processCounts.monitored}` : "Select a run"),
          cardHtml("Run Window", hasRun ? `${state.runSnapshot?.run?.sample_count ?? 0} samples` : "No run", hasRun ? `Last sample ${fmtTime(state.latestRunTsNs)}` : `Last system sample ${fmtTime(state.latestSystemTsNs)}`),
        ];
        chartTitle = "Memory usage";
        legend = ["host used", "host available", "run rss"];
        series = [
          { name: "host used", type: "line", showSymbol: false, data: lineData(systemSeries["system.mem.used_bytes"]) },
          { name: "host available", type: "line", showSymbol: false, data: lineData(systemSeries["system.mem.available_bytes"]) },
          { name: "run rss", type: "line", showSymbol: false, data: lineData(runSeries.mem_total_bytes) },
        ];
        notes = hasRun
          ? "Run RSS is aggregated from monitored process-tree samples; host data is host aggregate memory usage."
          : "Select a run to overlay monitored-process memory.";
        break;
      case "disk":
        subtitle = hasRun
          ? `Host disk IO and monitored run ${state.runId}.`
          : "Host disk IO with no monitored run selected.";
        cards = [
          cardHtml("Host Read", fmtBps(systemSummary["system.disk.read_bps"]), "Current throughput"),
          cardHtml("Host Write", fmtBps(systemSummary["system.disk.write_bps"]), "Current throughput"),
          cardHtml("Run Read", hasRun ? fmtBps(runSummary.io_read_bps) : "No run", hasRun ? "Monitored process IO" : "Select a run"),
          cardHtml("Run Write", hasRun ? fmtBps(runSummary.io_write_bps) : "No run", hasRun ? "Monitored process IO" : "Select a run"),
        ];
        chartTitle = "Disk throughput";
        legend = ["host read", "host write", "run read", "run write"];
        series = [
          { name: "host read", type: "line", showSymbol: false, data: lineData(systemSeries["system.disk.read_bps"]) },
          { name: "host write", type: "line", showSymbol: false, data: lineData(systemSeries["system.disk.write_bps"]) },
          { name: "run read", type: "line", showSymbol: false, data: lineData(runSeries.io_read_bps) },
          { name: "run write", type: "line", showSymbol: false, data: lineData(runSeries.io_write_bps) },
        ];
        notes = hasRun
          ? "Disk IO is plotted from host aggregate counters and monitored run process-tree IO samples."
          : "Select a run to overlay monitored-process disk IO.";
        break;
      case "ethernet":
        subtitle = hasRun
          ? `Host ethernet traffic and monitored run ${state.runId}.`
          : "Host ethernet traffic with no monitored run selected.";
        cards = [
          cardHtml("Host Rx", fmtBps(systemSummary["system.net.rx_bps"]), "Incoming bytes per second"),
          cardHtml("Host Tx", fmtBps(systemSummary["system.net.tx_bps"]), "Outgoing bytes per second"),
          cardHtml("Run Rx", hasRun ? fmtBps(runSummary.net_rx_bps) : "No run", hasRun ? "Monitored process network IO" : "Select a run"),
          cardHtml("Run Tx", hasRun ? fmtBps(runSummary.net_tx_bps) : "No run", hasRun ? "Monitored process network IO" : "Select a run"),
        ];
        chartTitle = "Network throughput";
        legend = ["host rx", "host tx", "run rx", "run tx"];
        series = [
          { name: "host rx", type: "line", showSymbol: false, data: lineData(systemSeries["system.net.rx_bps"]) },
          { name: "host tx", type: "line", showSymbol: false, data: lineData(systemSeries["system.net.tx_bps"]) },
          { name: "run rx", type: "line", showSymbol: false, data: lineData(runSeries.net_rx_bps) },
          { name: "run tx", type: "line", showSymbol: false, data: lineData(runSeries.net_tx_bps) },
        ];
        notes = hasRun
          ? "Network IO is plotted from host aggregate counters and monitored run process-tree samples."
          : "Select a run to overlay monitored-process ethernet traffic.";
        break;
      case "gpu":
        subtitle = hasRun
          ? `Host GPU usage and monitored run ${state.runId}.`
          : "Host GPU usage with no monitored run selected.";
        cards = [
          cardHtml("Host Util", fmtPct(systemSummary["system.gpu.util_pct"]), "GPU utilization"),
          cardHtml("Host Mem", fmtBytes(systemSummary["system.gpu.mem_used_bytes"]), "GPU memory used"),
          cardHtml("Run Util", hasRun ? fmtPct(runSummary.gpu_util_pct) : "No run", hasRun ? "Run aggregate GPU utilization" : "Select a run"),
          cardHtml("Run Mem", hasRun ? fmtBytes(runSummary.gpu_mem_used_bytes) : "No run", hasRun ? "Run aggregate GPU memory" : "Select a run"),
          cardHtml("Run Window", hasRun ? `${state.runSnapshot?.run?.sample_count ?? 0} samples` : "No run", hasRun ? `Last sample ${fmtTime(state.latestRunTsNs)}` : `Last system sample ${fmtTime(state.latestSystemTsNs)}`),
        ];
        chartTitle = "GPU utilization and memory";
        legend = ["host util", "run util", "host mem", "run mem"];
        yAxis = [
          { type: "value", min: 0, max: 100, axisLabel: { formatter: "{value}%" } },
          { type: "value", min: 0, axisLabel: { formatter: (value) => fmtBytes(value) } },
        ];
        series = [
          { name: "host util", type: "line", showSymbol: false, data: lineData(systemSeries["system.gpu.util_pct"]), yAxisIndex: 0 },
          { name: "run util", type: "line", showSymbol: false, data: lineData(runSeries.gpu_util_pct), yAxisIndex: 0 },
          { name: "host mem", type: "line", showSymbol: false, data: lineData(systemSeries["system.gpu.mem_used_bytes"]), yAxisIndex: 1 },
          { name: "run mem", type: "line", showSymbol: false, data: lineData(runSeries.gpu_mem_used_bytes), yAxisIndex: 1 },
        ];
        notes = hasRun
          ? "GPU is shown independently from PCIe. Open the PCIe view for bus throughput and per-channel curves."
          : "Select a run to overlay monitored-run GPU metrics.";
        break;
      case "pcie": {
        const hostChannelsSummary = collectHostPcieChannelsFromSummary(systemSummary);
        const hostChannelSeries = collectHostPcieChannelSeries(systemSeries);
        const runChannelsSummary = state.runSnapshot?.pcie_channels || {};
        const runChannelSeries = state.runPerf?.pcie_channels || {};
        const hostChannels = sortedChannelKeys(hostChannelsSummary);
        const runChannels = sortedChannelKeys(runChannelsSummary);

        subtitle = hasRun
          ? `Host PCIe throughput and monitored run ${state.runId}.`
          : "Host PCIe throughput with no monitored run selected.";
        cards = [
          cardHtml("Host Rx", fmtBps(systemSummary["system.pcie.rx_bytes_s"]), "Host aggregate receive"),
          cardHtml("Host Tx", fmtBps(systemSummary["system.pcie.tx_bytes_s"]), "Host aggregate transmit"),
          cardHtml("Run Rx", hasRun ? fmtBps(runSummary.pcie_rx_bytes_s) : "No run", hasRun ? "Run aggregate receive" : "Select a run"),
          cardHtml("Run Tx", hasRun ? fmtBps(runSummary.pcie_tx_bytes_s) : "No run", hasRun ? "Run aggregate transmit" : "Select a run"),
          cardHtml("Host Channels", String(hostChannels.length), hostChannels.length ? hostChannels.join(", ") : "No per-channel data"),
          cardHtml("Run Channels", hasRun ? String(runChannels.length) : "No run", hasRun ? (runChannels.length ? runChannels.join(", ") : "No per-channel data") : "Select a run"),
        ];
        chartTitle = "PCIe throughput (aggregate)";
        legend = ["host rx", "host tx", "run rx", "run tx"];
        series = [
          { name: "host rx", type: "line", showSymbol: false, data: lineData(systemSeries["system.pcie.rx_bytes_s"]) },
          { name: "host tx", type: "line", showSymbol: false, data: lineData(systemSeries["system.pcie.tx_bytes_s"]) },
          { name: "run rx", type: "line", showSymbol: false, data: lineData(runSeries.pcie_rx_bytes_s) },
          { name: "run tx", type: "line", showSymbol: false, data: lineData(runSeries.pcie_tx_bytes_s) },
        ];

        const secondarySeries = [];
        const secondaryLegend = [];
        for (const channel of sortedChannelKeys(hostChannelSeries)) {
          const row = hostChannelSeries[channel] || {};
          const rx = row.rx_bytes_s || [];
          const tx = row.tx_bytes_s || [];
          if (rx.length) {
            secondaryLegend.push(`host ${channel} rx`);
            secondarySeries.push({ name: `host ${channel} rx`, type: "line", showSymbol: false, data: lineData(rx) });
          }
          if (tx.length) {
            secondaryLegend.push(`host ${channel} tx`);
            secondarySeries.push({ name: `host ${channel} tx`, type: "line", showSymbol: false, data: lineData(tx) });
          }
        }
        if (hasRun) {
          for (const channel of sortedChannelKeys(runChannelSeries)) {
            const row = runChannelSeries[channel] || {};
            const rx = row.rx_bytes_s || [];
            const tx = row.tx_bytes_s || [];
            if (rx.length) {
              secondaryLegend.push(`run ${channel} rx`);
              secondarySeries.push({ name: `run ${channel} rx`, type: "line", showSymbol: false, data: lineData(rx) });
            }
            if (tx.length) {
              secondaryLegend.push(`run ${channel} tx`);
              secondarySeries.push({ name: `run ${channel} tx`, type: "line", showSymbol: false, data: lineData(tx) });
            }
          }
        }

        if (secondarySeries.length) {
          perfSecondaryBox.classList.remove("hidden");
          renderChart(charts.perfSecondary, "PCIe throughput (per channel)", secondarySeries, [{ type: "value", min: 0 }], secondaryLegend);
        }

        notes = hasRun
          ? "Per-channel PCIe uses NVML GPU-index channels (gpu0/gpu1/...), not physical per-lane counters."
          : "Select a run to overlay monitored-run PCIe. Channel = GPU endpoint channel via NVML.";
        break;
      }
      case "cpu":
      default:
        subtitle = hasRun
          ? `Host CPU vs monitored run ${state.runId}.`
          : "Host CPU with no monitored run selected.";
        cards = [
          cardHtml("Host CPU", fmtPct(systemSummary["system.cpu.util_pct"]), "Current host aggregate"),
          cardHtml("Run CPU", hasRun ? fmtPct(runSummary.cpu_total_pct) : "No run", hasRun ? `Run ${state.runId}` : "Select a run"),
          cardHtml("Processes", String(state.processCounts.total || 0), `Monitored: ${state.processCounts.monitored || 0}`),
          cardHtml("Sample Time", fmtTime(latestStamp), hasRun ? `Run samples ${state.runSnapshot?.run?.sample_count ?? 0}` : "Host sample only"),
        ];
        chartTitle = "CPU utilization";
        legend = ["host cpu", "run cpu"];
        yAxis = [{ type: "value", min: 0, max: 100, axisLabel: { formatter: "{value}%" } }];
        series = [
          { name: "host cpu", type: "line", showSymbol: false, areaStyle: { opacity: 0.12 }, data: lineData(systemSeries["system.cpu.util_pct"]) },
          { name: "run cpu", type: "line", showSymbol: false, areaStyle: { opacity: 0.08 }, data: lineData(runSeries.cpu_total_pct) },
        ];
        notes = hasRun
          ? "CPU usage is plotted from host aggregate data and the monitored run process-tree CPU samples."
          : "Select a run to overlay monitored-process CPU usage.";
        break;
    }

    document.getElementById("perfResourceSubtitle").textContent = subtitle;
    renderPerformanceCards(cards);

    renderChart(charts.perfPrimary, chartTitle, series, yAxis, legend);

    document.getElementById("perfNotes").textContent = notes;
    scheduleChartResize();
  }

  function renderChart(chart, title, series, yAxis, legend) {
    chart.setOption(
      {
        animation: false,
        color: ["#0b6bd3", "#14a37f", "#8b5cf6", "#ef8f1d"],
        title: {
          text: title,
          left: 8,
          top: 6,
          textStyle: {
            fontSize: 12,
            fontWeight: 600,
            color: "#21324c",
          },
        },
        tooltip: { trigger: "axis" },
        legend: legend.length
          ? {
              right: 8,
              top: 4,
              data: legend,
              itemWidth: 10,
              itemHeight: 8,
              textStyle: { fontSize: 11, color: "#5d6b7d" },
            }
          : undefined,
        grid: { left: 52, right: 18, top: 36, bottom: 28 },
        xAxis: {
          type: "time",
          axisLabel: { color: "#6c7a8b" },
          axisLine: { lineStyle: { color: "#d7e0ea" } },
          axisTick: { show: false },
        },
        yAxis,
        series,
      },
      true
    );
  }

  function sortProcesses(rows) {
    const out = [...rows];
    const key = state.procSort.key;
    const dir = state.procSort.dir === "asc" ? 1 : -1;

    out.sort((a, b) => {
      if (key === "source") {
        const av = String(a.source || "").toLowerCase();
        const bv = String(b.source || "").toLowerCase();
        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;
        return 0;
      }
      if (key === "run_label") {
        const av = String(a.run_label || "").toLowerCase();
        const bv = String(b.run_label || "").toLowerCase();
        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;
        return 0;
      }
      if (key === "comm") {
        const av = String(a.comm || "").toLowerCase();
        const bv = String(b.comm || "").toLowerCase();
        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;
        return 0;
      }
      const av = Number(a[key] || 0);
      const bv = Number(b[key] || 0);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });

    return out;
  }

  function updateSortHeaders() {
    document.querySelectorAll("#tab-processes th[data-sort]").forEach((th) => {
      const key = th.dataset.sort;
      th.classList.remove("sort-asc", "sort-desc");
      if (state.procSort.key === key) {
        th.classList.add(state.procSort.dir === "asc" ? "sort-asc" : "sort-desc");
      }
      th.textContent = th.dataset.title || key;
    });
  }

  function renderProcesses(rowsIn) {
    const rows = sortProcesses(rowsIn || []);
    const tbody = document.getElementById("procTbody");
    tbody.innerHTML = "";
    const counts = state.processCounts || { total: rows.length, monitored: 0, system: rows.length };
    document.getElementById("procCountPill").textContent = `total=${counts.total} monitored=${counts.monitored} system=${counts.system}`;
    const gpuCap = Boolean(state.processCapabilities?.gpu_proc_mem);
    document.getElementById("procGpuHint").textContent = gpuCap
      ? ""
      : "GPU process memory is not exposed by current driver/runtime; shown as N/A.";

    const maxCpu = Math.max(100, ...rows.map((p) => Number(p.cpu_pct || 0)));
    const maxMem = Math.max(1, ...rows.map((p) => Number(p.mem_rss_bytes || 0)));
    const knownGpuVals = rows
      .filter((p) => Boolean(p.gpu_mem_known))
      .map((p) => Number(p.gpu_mem_used_bytes || 0));
    const maxGpu = knownGpuVals.length ? Math.max(1, ...knownGpuVals) : 1;

    for (const p of rows) {
      const tr = document.createElement("tr");
      const gpuVal = Number(p.gpu_mem_used_bytes || 0);
      const gpuCell = p.gpu_mem_known
        ? meterHtml(fmtBytes(gpuVal), gpuVal / maxGpu)
        : '<span class="muted">N/A</span>';
      const runLabel = (p.run_ids || []).join(", ");
      const extraNames = Object.keys(p.extra_metrics || {});
      const extraLabel = extraNames.length ? extraNames.join(" | ") : "-";
      const sourceTag = p.monitored
        ? '<span class="source-tag monitored">monitored</span>'
        : '<span class="source-tag system">system</span>';
      tr.innerHTML = `
        <td>${sourceTag}</td>
        <td class="mono">${escHtml(runLabel || "-")}</td>
        <td class="mono extra-cell">${escHtml(extraLabel)}</td>
        <td>${escHtml(p.comm || "")}</td>
        <td class="mono">${escHtml(p.pid)}</td>
        <td>${meterHtml(fmtPct(p.cpu_pct), Number(p.cpu_pct || 0) / maxCpu)}</td>
        <td>${gpuCell}</td>
        <td>${meterHtml(fmtBytes(p.mem_rss_bytes), Number(p.mem_rss_bytes || 0) / maxMem)}</td>
        <td>${escHtml(fmtBps(p.io_read_bps))}</td>
        <td>${escHtml(fmtBps(p.io_write_bps))}</td>
        <td>${escHtml(fmtBps(p.net_rx_bps))}</td>
        <td>${escHtml(fmtBps(p.net_tx_bps))}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  function clearRunPanels() {
    state.runSnapshot = null;
    state.runPerf = null;
    state.latestRunTsNs = null;
  }

  function clearProcessPanels() {
    state.processRows = [];
    state.processCounts = { total: 0, monitored: 0, system: 0 };
    renderProcesses([]);
  }

  async function refreshSystemOnly() {
    const winSec = Math.max(10, Number(document.getElementById("windowSec").value || 120));
    const [latest, perf] = await Promise.all([
      jget("/api/system/latest"),
      jget(`/api/system/performance?seconds=${winSec}`),
    ]);
    state.systemLatest = latest;
    state.systemPerf = perf;
    state.latestSystemTsNs = latest.latest_ts_ns || perf.latest_ts_ns || null;
  }

  async function refreshRunOnly() {
    if (!state.runId) {
      clearRunPanels();
      return;
    }

    const winSec = Math.max(10, Number(document.getElementById("windowSec").value || 120));
    const [snap, perf] = await Promise.all([
      jget(`/api/taskmanager/run/${state.runId}/snapshot`),
      jget(`/api/taskmanager/run/${state.runId}/performance?seconds=${winSec}`),
    ]);
    state.runSnapshot = snap;
    state.runPerf = perf;
    state.latestRunTsNs = snap.latest_ts_ns || perf.latest_ts_ns || null;
    state.runProcesses = snap.processes || [];
    state.runCapabilities = snap.capabilities || {};
  }

  async function refreshProcessesOnly() {
    const payload = await jget("/api/taskmanager/processes?limit=500");
    state.latestProcessTsNs = payload.latest_ts_ns || null;
    state.processRows = (payload.rows || []).map((row) => {
      const runIds = row.run_ids || [];
      const extraMetrics = row.extra_metrics || {};
      return {
        ...row,
        run_ids: runIds,
        run_label: runIds.length ? runIds.join(", ") : "",
        extra_metrics: extraMetrics,
        extra_count: Object.keys(extraMetrics).length,
      };
    });
    state.processCapabilities = payload.capabilities || {};
    state.processCounts = payload.counts || {
      total: state.processRows.length,
      monitored: state.processRows.filter((r) => r.monitored).length,
      system: state.processRows.filter((r) => !r.monitored).length,
    };
  }

  function renderDashboard() {
    updateTopNav();
    renderPerformanceNav();
    renderRuns();

    if (state.activeTab === "performance") {
      renderPerformanceView();
    } else if (state.activeTab === "processes") {
      renderProcesses(state.processRows);
      updateSortHeaders();
    }
  }

  async function refreshAll() {
    if (state.inFlight) return;
    state.inFlight = true;
    try {
      await loadRuns();
      await Promise.all([refreshSystemOnly(), refreshRunOnly(), refreshProcessesOnly()]);
      renderDashboard();
      document.getElementById("refreshAtPill").textContent = `updated=${new Date().toLocaleTimeString()}`;
    } catch (e) {
      document.getElementById("refreshAtPill").textContent = `error=${String(e).slice(0, 48)}`;
      console.error(e);
    } finally {
      state.inFlight = false;
    }
  }

  function renderSqlResult(payload) {
    const columns = payload.columns || [];
    const rows = payload.rows || [];

    document.getElementById("sqlMeta").textContent = `rows=${rows.length}`;

    const head = document.getElementById("sqlHead");
    const body = document.getElementById("sqlBody");
    head.innerHTML = `<tr>${columns.map((c) => `<th>${escHtml(c)}</th>`).join("")}</tr>`;
    body.innerHTML = "";

    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = row.map((v) => `<td>${escHtml(v === null ? "" : String(v))}</td>`).join("");
      body.appendChild(tr);
    }
  }

  function buildSqlTemplate() {
    const ts = state.latestRunTsNs || state.latestSystemTsNs;
    if (!ts) return;
    const sec = Math.max(1, Number(document.getElementById("sqlIntervalSec").value || 30));
    const end = Number(ts);
    const start = end - sec * 1_000_000_000;

    if (state.runId) {
      const safeRunId = String(state.runId).replaceAll("'", "''");
      document.getElementById("sqlText").value = [
        "SELECT ts_ns, pid, sensor, metric, value, unit",
        "FROM metrics_raw",
        `WHERE run_id = '${safeRunId}'`,
        `  AND ts_ns BETWEEN ${start} AND ${end}`,
        "ORDER BY ts_ns, pid",
        "LIMIT 200",
      ].join("\n");
      return;
    }

    document.getElementById("sqlText").value = [
      "SELECT ts_ns, metric, value, unit",
      "FROM system_host_samples",
      `WHERE ts_ns BETWEEN ${start} AND ${end}`,
      "ORDER BY ts_ns, metric",
      "LIMIT 200",
    ].join("\n");
  }

  async function runSql() {
    try {
      const limit = Math.max(1, Number(document.getElementById("sqlLimit").value || 500));
      const sql = document.getElementById("sqlText").value;
      const payload = await jpost("/api/sql/query", { sql, params: [], limit });
      renderSqlResult(payload);
    } catch (e) {
      document.getElementById("sqlMeta").textContent = `SQL Error: ${e.message || e}`;
    }
  }

  function setupSortHeaders() {
    document.querySelectorAll("#tab-processes th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (!key) return;
        if (state.procSort.key === key) {
          state.procSort.dir = state.procSort.dir === "asc" ? "desc" : "asc";
        } else {
          state.procSort.key = key;
          state.procSort.dir = key === "comm" || key === "pid" || key === "source" || key === "run_label" ? "asc" : "desc";
        }
        updateSortHeaders();
        renderProcesses(state.processRows);
      });
    });
    updateSortHeaders();
  }

  function scheduleChartResize() {
    window.requestAnimationFrame(() => {
      Object.values(charts).forEach((chart) => chart.resize());
    });
  }

  function setupAutoRefresh() {
    if (state.timer) clearInterval(state.timer);
    state.timer = setInterval(async () => {
      if (!document.getElementById("autoRefresh").checked) return;
      await refreshAll();
    }, 1000);
  }

  function bindEvents() {
    document.querySelectorAll(".nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => setTab(btn.dataset.tab));
    });

    document.querySelectorAll(".perf-nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const resource = btn.dataset.resource;
        if (!resource) return;
        state.perfResource = resource;
        renderDashboard();
      });
    });

    document.getElementById("refreshNowBtn").addEventListener("click", refreshAll);
    document.getElementById("followRunning").addEventListener("change", async (e) => {
      state.followRunning = Boolean(e.target.checked);
      if (state.followRunning) {
        await refreshAll();
      }
    });
    document.getElementById("sqlTemplateBtn").addEventListener("click", buildSqlTemplate);
    document.getElementById("sqlRunBtn").addEventListener("click", runSql);

    window.addEventListener("resize", scheduleChartResize);
  }

  (async () => {
    bindEvents();
    setupSortHeaders();
    updateTopNav();
    await refreshAll();
    setupAutoRefresh();
  })();
})();
