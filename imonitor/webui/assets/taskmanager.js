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
    perfTertiary: echarts.init(document.getElementById("perfChartTertiary")),
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

  function fmtWatts(n) {
    return `${Number(n || 0).toFixed(1)} W`;
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

  function gpuChannelLabel(channel) {
    const m = /^gpu(\d+)$/.exec(String(channel));
    if (m) return `GPU ${m[1]}`;
    return `GPU ${String(channel)}`;
  }

  function parseGpuResource(resource) {
    const m = /^gpu:(.+)$/.exec(String(resource || ""));
    if (!m) return null;
    return { channel: m[1] };
  }

  function collectHostGpuChannelsFromSummary(summary) {
    const out = {};
    for (const [metric, value] of Object.entries(summary || {})) {
      const m = /^system\.gpu\.(gpu[^.]+)\.(util_pct|mem_used_bytes|power_w)$/.exec(String(metric));
      if (!m) continue;
      const channel = m[1];
      const field = m[2];
      const row = out[channel] || {};
      row[field] = Number(value || 0);
      out[channel] = row;
    }
    return out;
  }

  function collectHostGpuChannelSeries(series) {
    const out = {};
    for (const [metric, rows] of Object.entries(series || {})) {
      const m = /^system\.gpu\.(gpu[^.]+)\.(util_pct|mem_used_bytes|power_w)$/.exec(String(metric));
      if (!m) continue;
      const channel = m[1];
      const field = m[2];
      const row = out[channel] || { util_pct: [], mem_used_bytes: [], power_w: [] };
      row[field] = rows || [];
      out[channel] = row;
    }
    return out;
  }

  function collectHostPcieChannelsFromSummary(summary) {
    const out = {};
    for (const [metric, value] of Object.entries(summary || {})) {
      const m = /^system\.pcie\.(gpu[^.]+)\.(rx_bytes_s|tx_bytes_s|throughput_bytes_s|link\.gen|link\.gen\.current|link\.gen\.max|link\.width|link\.width\.current|link\.width\.max)$/.exec(String(metric));
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
      const m = /^system\.pcie\.(gpu[^.]+)\.(rx_bytes_s|tx_bytes_s|throughput_bytes_s)$/.exec(String(metric));
      if (!m) continue;
      const channel = m[1];
      const field = m[2];
      const row = out[channel] || { rx_bytes_s: [], tx_bytes_s: [], throughput_bytes_s: [] };
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
    const systemSeries = state.systemPerf?.series || {};

    const cpu = fmtPct(summary["system.cpu.util_pct"]);
    const memUsed = summary["system.mem.used_bytes"];
    const memTotal = summary["system.mem.total_bytes"];
    const disk = fmtRatePair(summary["system.disk.read_bps"], summary["system.disk.write_bps"]);
    const net = fmtRatePair(summary["system.net.rx_bps"], summary["system.net.tx_bps"]);
    const pcie = fmtRatePair(summary["system.pcie.rx_bytes_s"], summary["system.pcie.tx_bytes_s"]);
    const memoryText = fmtBytesPair(memUsed, memTotal);

    const hostGpuSummary = collectHostGpuChannelsFromSummary(summary);
    const hostGpuSeries = collectHostGpuChannelSeries(systemSeries);
    const samplerGpuChannels = Array.isArray(state.systemLatest?.gpu_channels)
      ? state.systemLatest.gpu_channels.map((x) => String(x))
      : [];
    const hostGpuChannelMap = { ...hostGpuSummary, ...hostGpuSeries };
    for (const channel of samplerGpuChannels) {
      if (!hostGpuChannelMap[channel]) hostGpuChannelMap[channel] = {};
    }
    const hostGpuChannels = sortedChannelKeys(hostGpuChannelMap);

    const gpuItems = hostGpuChannels.length
      ? hostGpuChannels.map((channel) => {
          const row = hostGpuSummary[channel] || {};
          return {
            key: `gpu:${channel}`,
            label: gpuChannelLabel(channel),
            meta: `${fmtPct(row.util_pct)} | ${fmtBytes(row.mem_used_bytes)} | ${fmtWatts(row.power_w)}`,
          };
        })
      : [
          {
            key: "gpu",
            label: "GPU",
            meta: `${fmtPct(summary["system.gpu.util_pct"])} | ${fmtBytes(summary["system.gpu.mem_used_bytes"])} | ${fmtWatts(summary["system.gpu.power_w"])}`,
          },
        ];

    const navItems = [
      { key: "cpu", label: "CPU", meta: cpu },
      { key: "memory", label: "Memory", meta: memoryText },
      { key: "disk", label: "Disk", meta: disk },
      { key: "ethernet", label: "Ethernet", meta: net },
      ...gpuItems,
      { key: "pcie", label: "PCIe", meta: pcie },
    ];

    const validResources = new Set(navItems.map((item) => item.key));
    if (!validResources.has(state.perfResource)) {
      state.perfResource = validResources.has("cpu") ? "cpu" : navItems[0]?.key || "cpu";
    }

    const navRoot = document.querySelector(".perf-nav-list");
    if (!navRoot) return;
    navRoot.innerHTML = navItems
      .map(
        (item) => `
          <button class="perf-nav-btn${item.key === state.perfResource ? " active" : ""}" data-resource="${escHtml(item.key)}">
            <span class="perf-nav-label">${escHtml(item.label)}</span>
            <span class="perf-nav-meta">${escHtml(item.meta || "--")}</span>
          </button>
        `
      )
      .join("");
  }

  function renderPerformanceCards(cards) {
    document.getElementById("perfSummaryCards").innerHTML = cards.join("");
  }

  function pcieLaneBytesPerSec(gen) {
    const g = Number(gen || 0);
    if (g <= 1) return 250_000_000;
    if (g === 2) return 500_000_000;
    if (g === 3) return 984_615_385;
    if (g === 4) return 1_969_230_769;
    if (g === 5) return 3_938_461_538;
    if (g === 6) return 7_876_923_076;
    const extra = Math.max(0, g - 6);
    return 7_876_923_076 * (2 ** extra);
  }

  function pcieMaxBytesByGenWidth(gen, width) {
    const lanes = Math.max(1, Number(width || 1));
    return pcieLaneBytesPerSec(gen) * lanes;
  }

  function renderSparkChart(chart, title, data, yMax, unitKind) {
    chart.setOption(
      {
        animation: false,
        color: ["#0b6bd3"],
        title: {
          text: title,
          left: 6,
          top: 2,
          textStyle: {
            fontSize: 11,
            fontWeight: 600,
            color: "#21324c",
          },
        },
        tooltip: {
          trigger: "axis",
          formatter: (params) => {
            const p = Array.isArray(params) ? params[0] : params;
            if (!p || !Array.isArray(p.value)) return "";
            const ts = Number(p.value[0] || 0);
            const raw = Number(p.value[1] || 0);
            let val = "";
            if (unitKind === "util") {
              val = `${raw.toFixed(1)}%`;
            } else if (unitKind === "mem_gb") {
              val = `${(raw / (1024 ** 3)).toFixed(2)} GB`;
            } else if (unitKind === "pcie_mbps") {
              val = `${(raw / 1_000_000).toFixed(2)} Mb/s`;
            } else {
              val = String(raw);
            }
            return `${new Date(ts).toLocaleTimeString()}<br/>${title}: ${val}`;
          },
        },
        grid: { left: 4, right: 4, top: 22, bottom: 6, containLabel: false },
        xAxis: { type: "time", show: false },
        yAxis: { type: "value", min: 0, max: yMax > 0 ? yMax : null, show: false },
        series: [
          {
            name: title,
            type: "line",
            showSymbol: false,
            lineStyle: { width: 1.6 },
            areaStyle: { opacity: 0.08 },
            data,
          },
        ],
      },
      true
    );
  }

  function renderGpuProfiles(channel) {
    const root = document.getElementById("gpuProfiles");
    if (!root) return;
    const statics = state.systemLatest?.gpu_static_profiles || {};
    const dynamics = state.systemLatest?.gpu_dynamic_profiles || {};
    const s = statics[channel] || {};
    const d = dynamics[channel] || {};
    if (!channel || (!Object.keys(s).length && !Object.keys(d).length)) {
      root.classList.add("hidden");
      root.innerHTML = "";
      return;
    }

    const staticRows = [
      ["Name", fmtValueOrDash(s.name)],
      ["UUID", fmtValueOrDash(s.uuid)],
      ["PCI Bus", fmtValueOrDash(s.pci_bus_id)],
      ["VRAM Total", fmtBytes(Number(s.mem_total_bytes || 0))],
      ["Power Limit", s.power_limit_w === null || s.power_limit_w === undefined ? "-" : fmtWatts(s.power_limit_w)],
      ["PCIe Gen Max", `Gen${Number(s.pcie_gen_max || 0).toFixed(0)}`],
      ["PCIe Width Max", `x${Number(s.pcie_width_max || 0).toFixed(0)}`],
      ["NUMA", s.numa_node === null || s.numa_node === undefined ? "-" : String(s.numa_node)],
    ];

    const dynamicRows = [
      ["Util", fmtPct(d.util_pct)],
      ["Memory Used", fmtBytes(d.mem_used_bytes)],
      ["Power", fmtWatts(d.power_w)],
      ["PCIe Rx", fmtBps(d.pcie_rx_bytes_s)],
      ["PCIe Tx", fmtBps(d.pcie_tx_bytes_s)],
      ["PCIe Rate", fmtBps(d.pcie_throughput_bytes_s)],
      ["PCIe Gen Cur", `Gen${Number(d.pcie_gen_current || 0).toFixed(0)}`],
      ["PCIe Width Cur", `x${Number(d.pcie_width_current || 0).toFixed(0)}`],
      ["Sample Time", fmtTime(d.sample_ts_ns)],
    ];

    const staticHtml = staticRows
      .map(([k, v]) => `<div class="gpu-prof-row"><span class="k">${escHtml(k)}</span><span class="v mono">${escHtml(v)}</span></div>`)
      .join("");
    const dynamicHtml = dynamicRows
      .map(([k, v]) => `<div class="gpu-prof-row"><span class="k">${escHtml(k)}</span><span class="v mono">${escHtml(v)}</span></div>`)
      .join("");

    root.classList.remove("hidden");
    root.innerHTML = `
      <section class="gpu-prof-box">
        <div class="gpu-prof-title">Static Profile</div>
        ${staticHtml}
      </section>
      <section class="gpu-prof-box">
        <div class="gpu-prof-title">Dynamic Profile</div>
        ${dynamicHtml}
      </section>
    `;
  }

  function applyGpuMiniLayout(enabled) {
    const stack = document.querySelector(".perf-chart-stack");
    const boxes = [
      document.querySelector("#perfChartPrimary")?.parentElement,
      document.getElementById("perfSecondaryBox"),
      document.getElementById("perfTertiaryBox"),
    ].filter(Boolean);
    const chartsEls = [
      document.getElementById("perfChartPrimary"),
      document.getElementById("perfChartSecondary"),
      document.getElementById("perfChartTertiary"),
    ].filter(Boolean);

    if (!stack) return;
    if (enabled) {
      stack.classList.add("gpu-mini-charts");
      stack.style.display = "grid";
      stack.style.gridTemplateColumns = "repeat(3,minmax(0,1fr))";
      stack.style.gap = "8px";
      for (const box of boxes) {
        box.style.minHeight = "140px";
        box.style.height = "140px";
      }
      for (const el of chartsEls) {
        el.style.minHeight = "140px";
        el.style.height = "140px";
      }
      return;
    }

    stack.classList.remove("gpu-mini-charts");
    stack.style.display = "";
    stack.style.gridTemplateColumns = "";
    stack.style.gap = "";
    for (const box of boxes) {
      box.style.minHeight = "";
      box.style.height = "";
    }
    for (const el of chartsEls) {
      el.style.minHeight = "";
      el.style.height = "";
    }
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
    const gpuResource = parseGpuResource(resource);
    const resourceLabel = gpuResource ? gpuChannelLabel(gpuResource.channel) : RESOURCE_LABELS[resource] || "CPU";

    document.getElementById("perfResourceTitle").textContent = resourceLabel;
    document.getElementById("perfResourcePill").textContent = `resource=${resource}`;
    document.getElementById("perfResourceStamp").textContent = `updated=${fmtTime(latestStamp)}`;

    const perfSecondaryBox = document.getElementById("perfSecondaryBox");
    const perfTertiaryBox = document.getElementById("perfTertiaryBox");
    const gpuProfiles = document.getElementById("gpuProfiles");
    applyGpuMiniLayout(false);
    perfSecondaryBox.classList.add("hidden");
    perfTertiaryBox.classList.add("hidden");
    if (gpuProfiles) {
      gpuProfiles.classList.add("hidden");
      gpuProfiles.innerHTML = "";
    }
    charts.perfSecondary.clear();
    charts.perfTertiary.clear();

    let subtitle = "";
    let notes = "";
    let cards = [];
    let chartTitle = "";
    let yAxis = [{ type: "value", min: 0 }];
    let legend = [];
    let series = [];
    let chartHandled = false;

    switch (gpuResource ? "gpu_channel" : resource) {
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
      case "gpu_channel": {
        const channel = gpuResource.channel;
        const hostUtilMetric = `system.gpu.${channel}.util_pct`;
        const hostMemMetric = `system.gpu.${channel}.mem_used_bytes`;
        const hostPowerMetric = `system.gpu.${channel}.power_w`;
        const pcieThroughputMetric = `system.pcie.${channel}.throughput_bytes_s`;
        const st = (state.systemLatest?.gpu_static_profiles || {})[channel] || {};
        const powerNow = Number(systemSummary[hostPowerMetric] || 0);
        const memMax = Number(st.mem_total_bytes || 0);
        const pcieMax = pcieMaxBytesByGenWidth(st.pcie_gen_max, st.pcie_width_max);
        subtitle = hasRun
          ? `Host ${resourceLabel} usage and monitored run ${state.runId}.`
          : `Host ${resourceLabel} usage with no monitored run selected.`;
        cards = [];
        perfSecondaryBox.classList.remove("hidden");
        perfTertiaryBox.classList.remove("hidden");
        applyGpuMiniLayout(true);
        renderSparkChart(charts.perfPrimary, `${resourceLabel} Util (${fmtWatts(powerNow)})`, lineData(systemSeries[hostUtilMetric]), 100, "util");
        renderSparkChart(charts.perfSecondary, `${resourceLabel} Memory`, lineData(systemSeries[hostMemMetric]), memMax, "mem_gb");
        renderSparkChart(charts.perfTertiary, `${resourceLabel} PCIe`, lineData(systemSeries[pcieThroughputMetric]), pcieMax, "pcie_mbps");
        renderGpuProfiles(channel);
        chartHandled = true;
        notes = `${resourceLabel} trend charts use fixed static ranges (util=100, memory=VRAM max, PCIe=GenMax×WidthMax).`;
        break;
      }
      case "gpu":
        subtitle = hasRun
          ? `Host GPU usage and monitored run ${state.runId}.`
          : "Host GPU usage with no monitored run selected.";
        cards = [];
        perfSecondaryBox.classList.remove("hidden");
        perfTertiaryBox.classList.remove("hidden");
        applyGpuMiniLayout(true);
        const statics = state.systemLatest?.gpu_static_profiles || {};
        const channels = sortedChannelKeys(statics);
        const totalMemMax = channels.reduce((acc, ch) => acc + Number(statics[ch]?.mem_total_bytes || 0), 0);
        const totalPcieMax = channels.reduce((acc, ch) => {
          const s = statics[ch] || {};
          return acc + pcieMaxBytesByGenWidth(s.pcie_gen_max, s.pcie_width_max);
        }, 0);
        renderSparkChart(charts.perfPrimary, `GPU Util (${fmtWatts(systemSummary["system.gpu.power_w"])})`, lineData(systemSeries["system.gpu.util_pct"]), 100, "util");
        renderSparkChart(charts.perfSecondary, "GPU Memory", lineData(systemSeries["system.gpu.mem_used_bytes"]), totalMemMax, "mem_gb");
        renderSparkChart(charts.perfTertiary, "GPU PCIe", lineData(systemSeries["system.pcie.throughput_bytes_s"]), totalPcieMax, "pcie_mbps");
        chartHandled = true;
        notes = "Aggregate GPU trend charts use static ranges derived from summed hardware maxima.";
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
          const tp = row.throughput_bytes_s || [];
          if (rx.length) {
            secondaryLegend.push(`host ${channel} rx`);
            secondarySeries.push({ name: `host ${channel} rx`, type: "line", showSymbol: false, data: lineData(rx) });
          }
          if (tx.length) {
            secondaryLegend.push(`host ${channel} tx`);
            secondarySeries.push({ name: `host ${channel} tx`, type: "line", showSymbol: false, data: lineData(tx) });
          }
          if (tp.length) {
            secondaryLegend.push(`host ${channel} throughput`);
            secondarySeries.push({ name: `host ${channel} throughput`, type: "line", showSymbol: false, data: lineData(tp) });
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
          ? "Per GPU PCIe now includes static generation plus real-time width and throughput."
          : "Per GPU PCIe now includes static generation plus real-time width and throughput.";
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

    if (!chartHandled) {
      renderChart(charts.perfPrimary, chartTitle, series, yAxis, legend);
    }

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

  function processGpuChannels() {
    const raw = state.processCapabilities?.gpu_channels;
    if (!Array.isArray(raw)) return [];
    const seen = {};
    for (const item of raw) {
      const key = String(item || "").trim();
      if (!key) continue;
      seen[key] = 1;
    }
    return sortedChannelKeys(seen);
  }

  function renderProcessGpuHeaders(gpuChannels) {
    const row = document.querySelector("#tab-processes thead tr");
    const anchor = document.getElementById("procGpuAnchor");
    if (!row || !anchor) return;

    row.querySelectorAll("th.proc-gpu-dyn").forEach((th) => th.remove());

    if (!gpuChannels.length) {
      anchor.classList.remove("hidden");
      anchor.textContent = anchor.dataset.title || "GPU";
      return;
    }

    anchor.classList.add("hidden");
    const insertBeforeNode = row.querySelector('th[data-sort="mem_rss_bytes"]');
    for (const channel of gpuChannels) {
      const utilTh = document.createElement("th");
      utilTh.className = "proc-gpu-dyn";
      utilTh.textContent = `${gpuChannelLabel(channel)} Util`;
      if (insertBeforeNode) row.insertBefore(utilTh, insertBeforeNode);
      else row.appendChild(utilTh);

      const memTh = document.createElement("th");
      memTh.className = "proc-gpu-dyn";
      memTh.textContent = `${gpuChannelLabel(channel)} Mem`;
      if (insertBeforeNode) row.insertBefore(memTh, insertBeforeNode);
      else row.appendChild(memTh);
    }
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
    const gpuChannels = processGpuChannels();
    renderProcessGpuHeaders(gpuChannels);
    const counts = state.processCounts || { total: rows.length, monitored: 0, system: rows.length };
    document.getElementById("procCountPill").textContent = `total=${counts.total} monitored=${counts.monitored} system=${counts.system}`;
    const gpuMemCap = Boolean(state.processCapabilities?.gpu_proc_mem);
    const gpuUtilCap = Boolean(state.processCapabilities?.gpu_proc_util);
    document.getElementById("procGpuHint").textContent = gpuMemCap || gpuUtilCap
      ? ""
      : "No active GPU process sample right now; values shown as 0.";

    const maxCpu = Math.max(100, ...rows.map((p) => Number(p.cpu_pct || 0)));
    const maxMem = Math.max(1, ...rows.map((p) => Number(p.mem_rss_bytes || 0)));
    const perGpuMaxMem = {};
    for (const channel of gpuChannels) {
      const vals = rows
        .map((p) => p.gpu_per_device?.[channel])
        .filter((x) => Boolean(x?.mem_known))
        .map((x) => Number(x.mem_used_bytes || 0));
      perGpuMaxMem[channel] = vals.length ? Math.max(1, ...vals) : 1;
    }

    const knownGpuVals = rows.filter((p) => Boolean(p.gpu_mem_known)).map((p) => Number(p.gpu_mem_used_bytes || 0));
    const maxGpu = knownGpuVals.length ? Math.max(1, ...knownGpuVals) : 1;

    for (const p of rows) {
      const tr = document.createElement("tr");
      const gpuVal = Number(p.gpu_mem_used_bytes || 0);
      const gpuCellLegacy = p.gpu_mem_known
        ? meterHtml(fmtBytes(gpuVal), gpuVal / maxGpu)
        : meterHtml(fmtBytes(0), 0);
      let gpuCellsHtml = "";
      if (gpuChannels.length) {
        for (const channel of gpuChannels) {
          const cell = p.gpu_per_device?.[channel] || {};
          const utilKnown = Boolean(cell.util_known);
          const memKnown = Boolean(cell.mem_known);
          const utilPct = Number(cell.util_pct || 0);
          const memBytes = Number(cell.mem_used_bytes || 0);
          const utilCell = utilKnown
            ? meterHtml(fmtPct(utilPct), utilPct / 100.0)
            : meterHtml(fmtPct(0), 0);
          const memCell = memKnown
            ? meterHtml(fmtBytes(memBytes), memBytes / Number(perGpuMaxMem[channel] || 1))
            : meterHtml(fmtBytes(0), 0);
          gpuCellsHtml += `<td>${utilCell}</td><td>${memCell}</td>`;
        }
      } else {
        gpuCellsHtml = `<td>${gpuCellLegacy}</td>`;
      }
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
        ${gpuCellsHtml}
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

    const perfNavList = document.querySelector(".perf-nav-list");
    if (perfNavList) {
      perfNavList.addEventListener("click", (event) => {
        const btn = event.target.closest(".perf-nav-btn");
        if (!btn) return;
        const resource = btn.dataset.resource;
        if (!resource) return;
        state.perfResource = resource;
        renderDashboard();
      });
    }

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
