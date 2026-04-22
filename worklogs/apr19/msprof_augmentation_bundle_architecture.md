# msprof 增强包目标与源码架构设计（apr19）

## 1. 项目目标（重新对齐）

本项目的 v1 目标定义为：

1. 面向 **单次 run** 做深度数据挖掘（多 `PROF` 聚合、stream 依赖、wait/comm/exec/idle、micro-loop）。
2. 输出一个“增强版 profiling 包”（augmentation bundle），在同一目录中同时包含：
   - 原始 msprof 产物（保持原样）
   - 我们的结构化聚合结果
   - 可离线打开的网页报告
3. 所有聚合指标都能追溯到原始数据来源（诚实呈现，不隐藏不确定性）。

非目标（v1）：

- 跨 run 的自动对比与回归判定。
- 重写 msprof 采集链路本身。

### 1.1 工程硬约束（必须满足）

以下约束是项目的硬门槛，不作为可选优化项：

1. 运行时最小依赖：核心链路只依赖 `Python 标准库 + sqlite3`。
2. 零 Docker 依赖：分析与报告生成默认不依赖容器。
3. 零复杂包前置：不要求用户预装大型三方包才能完成核心分析。
4. conda 兼容优先：在多种常见 conda 环境中保持高可用和一致输出。
5. 功能分层降级：可选能力缺失时自动降级，不影响主流程成功率。
6. 口径稳定可追溯：schema 版本化，指标来源与公式可追溯。
7. 默认离线可运行：不依赖远程服务即可产出完整 bundle。

### 1.2 约束验收口径（Definition of Done）

每次版本发布至少满足：

1. 在“干净 conda 环境”中，无额外 pip 安装也可跑通核心命令并生成 `derived/unified_profile.json`。
2. 缺失可选依赖时，工具给出明确提示并继续产出核心结果（不崩溃）。
3. 同一输入 run 在不同环境输出的关键指标一致（允许浮点微差）。
4. `lineage.json` 覆盖所有核心指标（wait/comm/exec/idle、causality、loop）。

---

## 2. 交付物规范（augmentation bundle）

建议固定输出目录结构：

```text
bundle/<run_id>/
  raw/
    ... 原始 run 目录镜像（PROF_*, msprof.log, run_meta.env, ...）
  derived/
    unified_profile.json
    lineage.json
    quality_report.json
  web/
    index.html
    assets/*
  manifest.json
```

说明：

- `raw/`：原始数据只读语义，不做内容改写。
- `derived/unified_profile.json`：统一数据模型，供网页与 AI 报告共同消费。
- `derived/lineage.json`：指标口径、来源表、过滤条件、公式、覆盖率。
- `derived/quality_report.json`：缺失数据、时间对齐、匹配率、异常告警。
- `manifest.json`：bundle 版本、文件清单、hash、生成时间、工具版本。

---

## 3. 网页信息架构（v1）

建议网页按“原始事实 -> 聚合洞察 -> 方法透明”组织为 9 页：

1. 总览：run 元信息、全局 wait/comm/exec/idle、热点 stream。
2. 原始数据地图：`PROF`/进程/设备/文件/表的覆盖关系。
3. 原始时间线：按 device/stream 浏览事件。
4. Stream 画像：每 stream 的 task 占比、idle 气泡、阶段分布。
5. Wait 拆解：`comm_wait/sync_wait/unknown_wait` 与规则说明。
6. 通信与链路：通信算子、连接、主要 producer/consumer 对。
7. 流间因果：`EVENT_WAIT -> EVENT_RECORD` 边与置信度。
8. Micro-loop：热点 loop 结构、步级耗时、步间 gap。
9. 数据质量与口径：覆盖率、缺失项、误差、已知限制。

每页都要有“数据来源/公式”入口，直接链接到 `lineage.json` 对应条目。

---

## 4. unified_profile.json（建议字段骨架）

```json
{
  "schema_version": "v0.1",
  "run": {},
  "sources": {},
  "quality": {},
  "timeline": {},
  "streams": {},
  "phases": {},
  "causality": {},
  "micro_loops": {},
  "rules": {}
}
```

字段约定：

- `run`：run_id、时间范围、tp/pp、设备映射、进程映射。
- `sources`：DB 列表、每个源的覆盖范围与计数。
- `quality`：time alignment、missing data、异常告警。
- `timeline`：标准化事件（必要时支持抽样/分页存储）。
- `streams`：每 stream 的占比、idle、top kernels、阶段统计。
- `phases`：phase 定义与 phase 内聚合。
- `causality`：边列表、匹配参数、覆盖率。
- `micro_loops`：候选 loop 与 best loop 细节。
- `rules`：分类规则、版本、参数（与 `classification_rules.md` 对齐）。

---

## 5. 现有源码复用评估

| 路径 | 当前作用 | 复用级别 | 处理建议 |
| --- | --- | --- | --- |
| `analyzer/msprof_stage_analyzer.py` | 读取 `TASK`、事件分类、stream 统计、因果边、loop 挖掘 | 高 | 拆分为可复用库模块，CLI 保留为 thin wrapper |
| `msprof-docs-processed/ascend/run_msprof_vllm_smoke.sh` | 采集执行主入口 | 高 | 保留；后续在 bundle 中记录采集参数与版本 |
| `msprof-docs-processed/ascend/run_msprof_vllm_2x2_stable.sh` | 稳定预设 | 高 | 保留；作为标准 workload preset |
| `msprof-docs-processed/ascend/analyze_msprof_output.py` | 基于导出 CSV 的摘要 | 中 | 作为 sanity-check 辅助，不作为主分析链路 |
| `msprof-docs-processed/ascend/generate_smoke_report.py` | 多 run 冒烟汇总 | 中 | 保留用于运营看板，不进入单 run 深挖核心 |
| `imonitor/reports/html_report.py` | 简单 HTML 表格报告 | 低 | 仅复用“静态文件写出”模式，页面重写 |
| `imonitor/sinks/csv_sink.py` | 结构化表输出 | 中 | 可复用通用 writer 思路，抽为 `exporters/tabular.py` |
| `imonitor/sinks/sqlite_sink.py` | 关系化持久层模式 | 低-中 | 如需 query 缓存可借鉴 schema 管理方式 |
| `imonitor/web/app.py` | FastAPI 静态挂载 | 中 | 可做可选本地服务预览；离线包不依赖服务 |
| `imonitor/webui/assets/taskmanager.js` | 实时系统监控前端 | 低 | 不直接复用业务逻辑，仅可借鉴图表组织方式 |

结论：

- 算法核心可复用（主要在 `analyzer/msprof_stage_analyzer.py`）。
- 表达层（网页）需要重新设计。
- 采集层脚本保持稳定，不在 v1 做破坏性改动。

---

## 6. 统一源码架构（建议）

建议新增模块树（保留 `analyzer/msprof_stage_analyzer.py` 作为兼容入口）：

```text
analyzer/
  msprof_augment/
    __init__.py
    cli.py
    config.py
    io/
      discover.py          # run/PROF/db 发现与校验
      sqlite_reader.py     # TASK + 辅助表读取
      raw_inventory.py     # host/device/raw 清点
    model/
      events.py            # TaskEvent / StreamStat / CausalityEdge dataclass
      schema.py            # unified_profile schema helpers
    normalize/
      classify.py          # wait/comm/exec/other + wait_kind
      phase.py             # MODEL_EXECUTE 或业务 phase 赋值
      align.py             # 多 DB 时间对齐与误差估计
    analytics/
      breakdown.py         # global/stream/phase 统计
      causality.py         # EVENT_WAIT -> EVENT_RECORD
      loops.py             # micro-loop 挖掘
      topology.py          # 预留：通信拓扑与链路质量
    export/
      unified_json.py
      lineage.py
      quality.py
      bundle.py            # 产物打包、manifest、raw 映射
    web/
      renderer.py          # 生成 web/ 静态站点
      templates/
      assets/
    doctor/
      env_check.py         # 环境自检与降级提示
```

设计原则：

1. **单向数据流**：`io -> normalize -> analytics -> export -> web`。
2. **指标与展示解耦**：网页只读 `unified_profile.json` 与 `lineage.json`。
3. **严格口径版本化**：分类规则、参数、schema 必须带版本。
4. **可测试**：每个 analytics 模块可用小样本 DB 单测。
5. **核心零三方依赖**：`msprof_augment core` 不引入重量级依赖。
6. **可选能力插件化**：可视化增强组件按需启用，不阻塞主链路。

---

## 7. 迁移路线（建议 4 步）

### Step 1：抽核（先保证功能不变）

- 将 `msprof_stage_analyzer.py` 的核心函数拆到 `msprof_augment/analytics/*`。
- 保持当前 CSV/MD 输出不变，做回归对齐。

验收：`analyzer/out/*` 关键指标与当前脚本一致（允许浮点微差）。

### Step 2：统一模型

- 定义 `unified_profile.json v0.1`。
- 增加 `quality_report.json` 与 `lineage.json`。

验收：单次 run 可生成 `derived/` 三个核心 JSON，字段稳定。

### Step 3：网页生成

- 基于 `unified_profile.json` 生成 `web/index.html + assets`。
- 支持离线打开，不依赖后端服务。

验收：9 页可浏览，关键图表可下钻到来源说明。

### Step 4：bundle 打包

- 实现 `bundle/<run_id>/raw|derived|web|manifest`。
- 记录原始文件映射与 hash。

验收：用户拿到一个目录即可同时查看“原始事实 + 集成分析”。

---

## 8. 风险与约束

1. `timeline` 事件量很大，`unified_profile.json` 可能过大。
   - 方案：时间线按窗口分片或采样；聚合结果保持全量。
2. `EVENT_WAIT -> EVENT_RECORD` 因果是启发式，不是显式依赖。
   - 方案：输出匹配率、窗口参数、置信度，禁止过度结论。
3. 部分 `device_n` 可能 metadata-only。
   - 方案：在 `quality_report` 中显式标注，不做静默补全。
4. stream 内并发会影响直觉观察。
   - 方案：区分 `task_ratio` 与 `span_ratio`，并保留 `idle_gap`。

---

## 9. 立即执行建议（本周）

1. 先完成 `unified_profile.json v0.1` schema 定稿。
2. 将现有 analyzer 输出映射到 schema（不改算法）。
3. 先做“总览 + 数据质量 + stream 画像”三页网页 MVP。
4. 在同一 run 上做一次端到端 bundle 产出验证。

## 10. 依赖策略（落地约定）

### 10.1 Core（必须）

- Python 标准库：`argparse/csv/json/pathlib/sqlite3/dataclasses` 等
- 输入依赖：本地 msprof 产物目录（`PROF_*`, `msprof_*.db`）

### 10.2 Optional（可选）

- 本地服务预览（例如 FastAPI）仅用于开发体验，不作为交付必要条件。
- 高级前端构建链路如需引入，必须提供“纯静态降级版本”。

### 10.3 禁止项（v1）

- 将 Docker 作为分析器默认依赖。
- 将大型第三方包作为核心路径硬依赖。
- 将在线服务作为唯一渲染路径（必须支持离线打开）。
