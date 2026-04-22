# MSPROF Raw Artifacts 说明书

## 1. 目的与范围

本文档定义 `msprof` 原始产物（raw layer）的标准解释口径，面向以下场景：

1. 识别单次采集 run 的目录结构与关键文件职责。
2. 明确 `msprof_*.db`、`mindstudio_profiler_output`、`host/device_n` 三层数据关系。
3. 说明 `analyzer/msprof_stage_analyzer.py` 的输入发现、聚合与消费链路。

本文档不定义业务级结论（例如某次 workload 的性能优劣），仅定义可复用的数据结构与解析规范。

## 2. 单次 Run 目录规范

单次 run 目录（示例：`msprof-docs-processed/.../<run_id>/`）通常包含：

- `run_meta.env`：采集开关与环境快照。
- `workload_result.json`：workload 执行状态、耗时与摘要信息。
- `msprof.log`：采集、解析、导出过程日志（排障主入口）。
- `prof_dirs.txt`：本次 run 的 `PROF_*` 子目录列表。
- `key_files.txt`：导出关键文件索引。
- `exit_code.txt`：采集脚本退出码。
- `PROF_*/`：按采集进程归档的 profiler 产物目录。

## 3. `PROF_*` 分层结构

每个 `PROF_*` 目录一般包含：

1. `msprof_*.db`
2. `mindstudio_profiler_output/*`
3. `host/*`
4. `device_n/*`（`n` 为设备号）
5. `mindstudio_profiler_log/*`

### 3.1 形成原则

- `PROF_*` 的数量主要与采集进程数相关。
- 多设备场景下，常见“多采集进程 -> 多 `PROF_*`”。
- 不应假设“固定每卡一个 `PROF_*`”；应以 run 实际产物为准。

### 3.2 时间参考系

跨 `PROF_*` 时间聚合以 DB 时间字段为准：

- `TASK.startNs/endNs`
- `SESSION_TIME_INFO.startTimeNs/endTimeNs`

工程上可在同一 run 内直接进行跨 `PROF_*` 时间线拼接；跨 run 对比时建议统一时间零点（例如减去各自最小 `startNs`）。

## 4. `msprof_*.db`（Raw 主输入）

`msprof_*.db` 是 analyzer 的主输入层。核心表关系如下：

- `TASK`：时序事实（任务起止、设备、stream、connection 等）。
- `STRING_IDS`：字符串字典（task/op 名称反解）。
- `COMPUTE_TASK_INFO`：计算任务语义（op name/op type）。
- `COMMUNICATION_TASK_INFO`：通信任务语义（src/dst、link、size、bandwidth 等）。
- `COMMUNICATION_OP`：通信算子级语义（connectionId、algType、opType）。
- `ENUM_HCCL_*`：通信相关枚举映射。

说明：

- 同一 run 的不同 DB 可能存在 `stream_id` 重号，聚合时必须使用 `(device_id, stream_id)` 复合键。
- 对时序分析、wait/comm/exec 分类、跨流因果恢复等任务，`msprof_*.db` 通常可作为一手数据源。

## 5. `mindstudio_profiler_output`（导出可读层）

`mindstudio_profiler_output` 是基于 DB 导出的可读视图，常见文件包括：

- `msprof_*.json`（timeline 事件流，常用于 tracing 视图）
- `api_statistic_*.csv`
- `communication_statistic_*.csv`
- `op_statistic_*.csv`
- `op_summary_*.csv`
- `task_time_*.csv`
- `README.txt`

定位：

- 该层用于快速浏览与 sanity check。
- 细粒度时序与因果分析应以 `msprof_*.db` 为准，并用 CSV/JSON 做互证。

## 6. `host` 与 `device_n`（原始切片与中间库）

### 6.1 `host` 目录（主机侧）

建议按三层理解：

1. 元信息层：`sample.json`、`info.json`、`start_info`、日志等。
2. 原始切片层：`host/data/*`。
3. 中间库层：`host/sqlite/*.db`（如 `api_event.db`、`runtime.db`、`hccl.db`、`time.db` 等）。

### 6.2 `device_n` 目录（设备侧）

同样按三层理解：

1. 元信息层：`sample.json`、`info.json.<n>`、`start_info.<n>`、日志等。
2. 原始切片层：`device_n/data/*`（如 `stars_soc.data.<n>.slice_*`）。
3. 中间库层：`device_n/sqlite/*.db`（如 `ascend_task.db`、`ai_core_op_summary.db`、`hccl_single_device.db`、`time.db` 等）。

### 6.3 元数据目录与空数据目录

run 内可能出现“目录存在但仅元数据、无有效 `data/sqlite`”的 `device_n`。该现象属于采集结果的一种合法形态，应通过：

- `mindstudio_profiler_log/*`
- `msprof.log`

联合判定是否为采集缺失或导出失败。

## 7. Raw 到 Analyzer 的消费链路

目标脚本：`analyzer/msprof_stage_analyzer.py`

标准流程：

1. 扫描 run 目录下全部 `PROF_*/msprof_*.db`。
2. 过滤无 `TASK` 表的 DB。
3. 跨 DB 聚合任务事件（默认去重，可通过参数关闭）。
4. 基于 `TASK + STRING_IDS + *_TASK_INFO` 构建标准化任务语义。
5. 输出 wait/comm/exec 统计、stream 统计、phase 统计、因果边、loop 候选等结果。

常见输出目录（示例：`analyzer/out/<job_name>/`）：

- `summary.md`
- `meta.json`
- `global_breakdown.csv`
- `stream_breakdown.csv`
- `phase_stream_breakdown.csv`
- `task_type_breakdown.csv`
- `stream_causality_edges.csv`
- `stream_causality_meta.json`
- `top_kernels.csv`
- `loop_candidates.csv`
- `loop_best.json`
- `classification_rules.md`

## 8. 与 hprofile 的关系

本说明书覆盖的是 **raw 层**（`msprof` 原始采集与解析产物语义）。

`analyzer/hprofile` 位于 raw 之上，负责派生产物与交付层组织，典型包括：

- derived 数据（聚合与增强结果）
- web 展示物（可视化/浏览端消费）
- bundle 打包物（分发与归档）

边界约定：

- raw 层保持“事实记录与稳定字段语义”。
- hprofile 层保持“派生逻辑、展示模型、打包协议”。
- 两层之间通过 analyzer 输出的结构化结果对接，不回写 raw 原始事实。

## 9. 运行与定位（仓库内路径）

### 9.1 查找 run 下 DB

```bash
find msprof-docs-processed -type f -path '*/PROF_*/msprof_*.db'
```

### 9.2 运行 analyzer

```bash
python3 analyzer/msprof_stage_analyzer.py --help
```

```bash
python3 analyzer/msprof_stage_analyzer.py \
  --run-dir msprof-docs-processed/ascend/out/msprof_smoke/<run_id> \
  --out-dir analyzer/out/<job_name>
```

### 9.3 关键排障入口

- run 级：`<run_dir>/msprof.log`
- PROF 级：`<run_dir>/PROF_*/mindstudio_profiler_log/*`
- 结果级：`analyzer/out/<job_name>/meta.json`

## 附录 A：示例 Run（20260418_154241）

以下仅作为结构示例，不作为通用性能结论：

- run 路径：`msprof-docs-processed/ascend/out/msprof_smoke/20260418_154241`
- 该 run 包含 4 个 `PROF_*`，每个 `PROF_*` 含 1 个 `msprof_*.db`。
- 该 run 中观察到“部分 `PROF_*` 的某些 `device_n` 为 metadata-only”现象，并可在日志中定位。
- analyzer 在该 run 上执行时会聚合 4 个 DB 并输出统一结果目录（位于 `analyzer/out/...`）。

