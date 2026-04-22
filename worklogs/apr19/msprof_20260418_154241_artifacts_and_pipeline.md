# msprof 产物解读与分析链路固化（run: 20260418_154241）

## 1. 目标与范围

本文只回答两件事：

1. 单次 `msprof` 执行（`/home/user8/workspace/imonitor/msprof-docs-processed/ascend/out/msprof_smoke/20260418_154241`）到底产生了哪些原始文件、它们分别表示什么。
2. 现有分析器 `analyzer/msprof_stage_analyzer.py` 如何消费这些原始产物并输出结构化结论。

---

## 2. 这次 run 的基本事实

- run 路径：`/home/user8/workspace/imonitor/msprof-docs-processed/ascend/out/msprof_smoke/20260418_154241`
- workload：Qwen3-8B，`tp=2`，`pp=2`，`visible_devices=4,5,6,7`
- 采集开关（`run_meta.env`）：`ascendcl=on`、`runtime_api=on`、`task_time=l1`、`hccl=on`，其余重项（`ai_core/aicpu/l2/task_memory/...`）为 `off`
- 退出码：`exit_code.txt = 0`
- 任务结果：`workload_result.json.status = ok`

顶层控制文件（run 根目录）含义：

- `run_meta.env`：本次采集参数快照。
- `workload_result.json`：业务 workload 执行结果与耗时。
- `msprof.log`：采集脚本与被采集程序的标准输出（stdout）归档，包含采集、导出、解析全过程日志（排障首要入口）。
- `prof_dirs.txt`：原始 `PROF_*` 目录列表。
- `key_files.txt`：导出的高价值文件清单（摘要 csv/json）。
- `exit_code.txt`：整体脚本退出码。

---

## 3. 目录结构（单次 run）

本次 run 下有 4 个 `PROF_*` 目录：

- `PROF_...PJPD...`
- `PROF_...GMKA...`
- `PROF_...IQQM...`
- `PROF_...GADB...`

每个 `PROF_*` 结构基本一致：

1. `msprof_*.db`
2. `mindstudio_profiler_output/*`
3. `host/*`
4. `device_*/ *`
5. `mindstudio_profiler_log/*`

其中真正被 analyzer 消费的主输入是 `msprof_*.db`（每个 PROF 1 个）。

### 3.1 这 4 个 `PROF_*` 是怎么形成的

先给结论：

- 从官方文档口径看：`PROF_*` 的个数主要对应“采集进程数”，不是强约束“每张卡一个 PROF”。
- 在本次 run 中，4 个 `PROF_*` 与 4 个 vLLM worker 进程一一对应，并且每个 `msprof_*.db` 的 `TASK` 基本只覆盖 1 张主卡（4/5/6/7）。

证据（本次实测）：

- `msprof_20260418074418.db`：`globalPid=38049`、`deviceId=4`
- `msprof_20260418074524.db`：`globalPid=38052`、`deviceId=5`
- `msprof_20260418074448.db`：`globalPid=38057`、`deviceId=6`
- `msprof_20260418074556.db`：`globalPid=38062`、`deviceId=7`
- 上述 PID 与 `msprof.log` 中的 `Worker_PP*_TP* pid=...` 对应。

官方说明（`atlasprofiling_16_0021`）也明确：

- “单采集进程”通常生成一个 `PROF_XXX`；
- “多采集进程”会生成多个 `PROF_XXX`；
- 每个 `PROF` 下出现多少 `device_*` 目录与实际操作有关，不影响分析。

因此更准确说法是：本次是“多进程采集导致多 `PROF`”，而不是“msprof 固定按卡切分”。

### 3.2 “每进程一个 PROF”之间的时间参考系是否对齐

结论（基于本次 run 实测）：**对齐**，可以直接做跨 `PROF` 时间线聚合。

证据 1：`TASK.startNs/endNs` 是同一量纲的绝对时间（纳秒级时间戳），4 个 DB 的时间窗高度重叠：

- 设备4（pid 38049）：`[1776498181167610281, 1776498234862693729]`
- 设备6（pid 38057）：`[1776498182432936410, 1776498234952371770]`
- 设备5（pid 38052）：`[1776498182456088236, 1776498234979687358]`
- 设备7（pid 38062）：`[1776498182472441030, 1776498234847413430]`

两两窗口交叠比例（交集 / 较短窗口）在本次都接近 `1.0`（约 `0.998`~`1.000`）。

证据 2：`SESSION_TIME_INFO.startTimeNs` 也落在同一时间基准，4 个 `PROF` 仅相差亚秒级启动抖动。

误差口径（本报告约定）：

- 启动偏移：`Δstart_i = min(TASK.startNs_i) - min_all(TASK.startNs)`。
- 会话偏移：`Δsession_i = SESSION_TIME_INFO.startTimeNs_i - min_all(SESSION_TIME_INFO.startTimeNs)`。
- 两两非重叠误差：`ε(i,j) = min(span_i, span_j) - overlap(i,j)`，其中 `span = max(endNs)-min(startNs)`。

本次实测结果：

| device | pid | Δstart(ms) | Δsession(ms) | span(ms) |
| --- | ---: | ---: | ---: | ---: |
| 4 | 38049 | 0.000 | 0.000 | 53695.083 |
| 5 | 38052 | 1288.478 | 262.378 | 52523.599 |
| 6 | 38057 | 1265.326 | 236.199 | 52519.435 |
| 7 | 38062 | 1304.831 | 369.107 | 52374.972 |

两两 `overlap_ratio = overlap / min(span_i, span_j)` 为 `0.997773 ~ 1.000000`；最大非重叠误差 `ε_max = 116.994 ms`（device4 vs device5）。

解读：

- 进程启动不是同一时刻（有秒级以内偏移），但采样窗口足够长（~52s），主区间几乎完全重叠。
- 对“按时间窗聚合比例/因果边”这类统计影响很小，足够支持本次跨 `PROF` 合并分析。

工程建议：

- 同一次采集（同一 run-dir）可按 `startNs/endNs` 直接拼接跨进程时间线。
- 跨不同 run 对比时，仍建议先做时间零点归一化（例如减去各自最小 `startNs`）以规避启动偏移。

### 3.3 Ascend 官方口径（对应本结论）

官方文档来源：

- `atlasprofiling_16_1144`（msprof db 说明）：<https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_1144.html>
- `atlasprofiling_16_0021`（解析导出与目录结构）：<https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0021.html>

关键口径（已在本地文档镜像核对）：

1. 时间字段口径：时间统一为纳秒（ns），且为本地 Unix 时间。  
2. `TASK` 表字段：`startNs/endNs/deviceId/globalPid` 明确给出。  
3. `SESSION_TIME_INFO` 表字段：`startTimeNs/endTimeNs`（会话开始结束时间）。  
4. 目录结构口径：多 Device 场景下，单采集进程可 1 个 `PROF`，多采集进程会有多个 `PROF`；`device_*` 目录数量与实际操作有关。  

因此“本次 4 个 `PROF` 来自 4 个采集进程（并与 4 个 worker 对应）”与官方口径一致；“跨 `PROF` 时间可对齐”也与其时间字段定义相容。

---

## 4. `msprof_*.db` 是什么

### 4.1 本次 run 中的 4 个主 DB

- `...PJPD.../msprof_20260418074418.db`（TASK 主设备=4，`362,328` 行）
- `...GMKA.../msprof_20260418074448.db`（主设备=6，`407,203` 行）
- `...IQQM.../msprof_20260418074524.db`（主设备=5，`551,022` 行）
- `...GADB.../msprof_20260418074556.db`（主设备=7，`443,550` 行）

总 TASK 行数（聚合后）= `1,754,398`。

### 4.2 DB 里的关键表（分析主干）

- `TASK`：时间线最底层任务事件（start/end/stream/taskType/deviceId/connectionId）。
- `STRING_IDS`：字符串字典（taskType、op 名称等都要通过它还原）。
- `COMPUTE_TASK_INFO`：计算任务标签（op name/op type）。
- `COMMUNICATION_TASK_INFO`：通信任务标签及 src/dst rank、transport/link、size、bandwidth。
- `COMMUNICATION_OP`：通信大算子级信息（connectionId、algType、opType）。
- 枚举表：`ENUM_HCCL_*`（link/transport/data type 等编码映射）。

### 4.3 为什么是“每进程/每卡拆分 DB”

这次 2x2 结果不是一个总 DB，而是多个 `PROF/msprof_*.db` 分散记录。并且不同 DB 内 `stream_id` 会重号，必须带上 `device_id` 聚合，否则会把不同卡的 stream 混成一个。

---

## 5. `mindstudio_profiler_output` 是什么

建议固定口径（与你刚才提议一致）：

- `mindstudio_profiler_output` = 从该 `PROF` 的解析后 DB 数据导出的**人类可读视图**（timeline json + summary csv）。
- 这次 run 的 `msprof.log` 也能看到对应流程：`All data will be exported from db in sqlite`，随后 `End exporting summary output_file ... mindstudio_profiler_output path`。

每个 `PROF` 都导出以下摘要文件：

- `msprof_*.json`
- `api_statistic_*.csv`
- `communication_statistic_*.csv`
- `op_statistic_*.csv`
- `op_summary_*.csv`
- `task_time_*.csv`
- `README.txt`

这些文件偏“人读总结”，适合快速看热点；而 analyzer 主要使用 DB 还原更细粒度时序关系。

### 5.1 典型 CSV 字段（本次实测表头）

- `api_statistic`: `Device_id, Level, API Name, Time(us), Count, Avg(us), ...`
- `communication_statistic`: `Device_id, OP Type, Count, Total Time(us), ...`
- `op_statistic`: `Device_id, OP Type, Core Type, Count, Total Time(us), ...`
- `op_summary`: 包含 `Task ID / Stream ID / Op Name / Task Type / Task Duration / Task Wait Time ...`
- `task_time`: `kernel_name, kernel_type, stream_id, task_id, task_time(us), task_start, task_stop`

### 5.2 `msprof_*.json` 形态

本次文件是 **事件数组**（顶层 `list`，约几十万到百万事件），每个事件常见字段：

- `name, pid, tid, ts, ph, args`

可直接用于 `chrome://tracing` 风格时间线视图。

---

## 6. `host` 与 `device_*` 子目录是什么

建议把 `device_*` 统一记为 `device_n`（`n` 为设备号），这样口径更清晰。

### 6.1 `mindstudio_profiler_log`（日志层）

建议固定口径（与你刚才提议一致）：

- `mindstudio_profiler_log` = attach 到该 `PROF` 对应采集进程上下文后的 profiler 日志输出（采集/解析/导出阶段日志）。

本次每个 `PROF` 下常见文件：

- `collection_host.log`
- `collection_device_<n>.log`
- `msprof_analysis_<pid>.log`

这些日志里能直接看到：

- 解析器与导出器执行阶段（例如 `Data will be parsed/export by msprof_analysis.so`）
- 从 `host/sqlite`、`device_n/sqlite` 导出 summary/timeline 的路径与告警
- 哪些 `device_n` 目录只有元数据、哪些有完整数据

### 6.2 `host` 原始数据（主机侧）

`host` 目录可分三层：

1. 元信息层：`sample.json`, `info.json`, `start_info`, `host_start.log`, `incompatible_features.json`
2. 原始切片层：`host/data/*`
3. 中间库层：`host/sqlite/*.db`

本次 `host/data` 观测到的原始类型（按前缀归并）：

- `aging.api_event.data`
- `aging.additional.tensor_info`
- `aging.additional.context_id_info`
- `aging.compact.task_track`
- `aging.compact.node_basic_info`
- `aging.compact.hccl_op_info`
- `aging.compact.memcpy_info`
- `unaging.api_event.data`
- `unaging.additional.hccl_info`
- `unaging.additional.type_info_dic`
- `unaging.additional.hash_dic`
- `unaging.additional.tensor_info`
- `unaging.additional.context_id_info`
- `unaging.compact.capture_stream_info`
- `unaging.compact.hccl_op_info`
- `unaging.compact.node_basic_info`
- `unaging.compact.task_track`

本次 `host/sqlite` 主要 DB 及表：

- `api_event.db`（`ApiData`）
- `runtime.db`（`HostTask`, `MemcpyInfo`）
- `hccl.db`（`HCCLOP`, `HCCLTask`）
- `stream_info.db`（`CaptureStreamInfo`）
- `ge_info.db`（`TaskInfo`）
- `ge_hash.db`（`GeHashInfo`, `TypeHashInfo`）
- `time.db`（`Time`）

### 6.3 `device_n` 原始数据（设备侧）

`device_n` 目录同样是三层：

1. 元信息层：`sample.json`, `info.json.<n>`, `start_info.<n>`, `dev_start.log.<n>`, `host_start.log.<n>`, `incompatible_features.json`
2. 原始切片层：`device_n/data/*`
3. 中间库层：`device_n/sqlite/*.db`

本次 `device_n/data` 观测到的主类型：

- `stars_soc.data.<n>.slice_*`（本次 n=4/5/6/7，主设备切片最完整）

本次 `device_n/sqlite` 主要 DB 及表：

- `ascend_task.db`（`AscendTask`）
- `ai_core_op_summary.db`（`ge_summary`, `task_time`）
- `hccl_single_device.db`（`HCCLOpSingleDevice`, `HCCLTaskSingleDevice`, `HcclOpReport`）
- `op_counter.db`（`ge_task_merge`, `op_report`, `rts_task`）
- `time.db`（`Time`）
- `step_trace.db`（本次多数为空表/无关键数据）
- `biu_perf.db`（本次基本为空，用于更底层总线性能场景）

### 6.4 原始数据到最终输出的关系

可按下面理解：

1. `host/data` 与 `device_n/data`：最原始切片（分片文件）。
2. `host/sqlite` 与 `device_n/sqlite`：解析后的中间数据库。
3. `msprof_*.db`：该 `PROF` 级别的汇总数据库（analyzer 主输入）。
4. `mindstudio_profiler_output/*`：在 DB 基础上导出的可读报告（csv/json）。

因此，“DB 是否包含主要分析信息”可以分两层回答：

- 对我们当前 analyzer 的目标（task 时序、wait/comm/exec、stream 因果、micro-loop）：`msprof_*.db` 已足够作为主数据源。
- 对更底层排障（采集缺失、导出失败、某些扩展指标为空）：仍需回看 `mindstudio_profiler_log` + `host/device_n` 原始层。

### 6.5 本次 run 的一个现象（metadata-only device）

本次 4 个 `PROF` 中，3 个 `PROF` 的 `device_4` 只有元信息文件，无 `data/sqlite` 实体数据。对应日志有明确告警：

- `There is no file in .../device_4/data. Collect data failed.`

这解释了“为什么每个 `PROF` 下会看到多个 `device_n` 目录，但并非每个都有可分析原始数据”。

### 6.6 每张卡是怎么被 profile 到的（机制层）

基于这次日志与产物，可以确定的事实是：

1. `msprof` 作为外层采集器启动业务程序（本次是 vLLM workload）。
2. 业务程序再拉起多个 worker 子进程（本次 4 个 worker，对应 TP/PP 组合）。
3. 每个 worker 在其绑定 NPU 上产生采集数据，最终导出为对应 `PROF_*/msprof_*.db` 与 `mindstudio_profiler_output`。

关于“是否是 hook fork”：

- 从当前可见日志和导出物无法直接证明底层实现细节（例如是否通过 fork hook 注入）。
- 但行为上可确认：`msprof` 会按进程维度归档并导出，不需要手动逐卡启动 4 次独立采集。

---

## 7. analyzer 如何处理原始产物（代码级流程）

目标脚本：`/home/user8/workspace/imonitor/analyzer/msprof_stage_analyzer.py`

### 7.1 输入发现与聚合

1. 在 run-dir 下找所有 `PROF_*/msprof_*.db`。
2. 仅保留包含 `TASK` 表的 DB。
3. 逐库读取后拼接为一份任务集合。
4. 默认做 task 去重（可 `--disable-task-dedup` 关闭）。

### 7.2 事件标准化

每条 `TASK` 被还原成 `TaskEvent`（含 `device_id + stream_id + task_type + label + connection_id`）。

- label 来源：`COMPUTE_TASK_INFO` / `COMMUNICATION_TASK_INFO` + `STRING_IDS`
- 分类：`wait / comm / exec / other`
- wait 再拆：`comm_wait / sync_wait / unknown_wait`

### 7.3 核心统计口径

1. 全局比例：wait/comm/exec/other。
2. stream 维度：按 `(device_id, stream_id)` 聚合。
3. phase 维度：由 `MODEL_EXECUTE` 自动并窗生成粗 phase。
4. idle 气泡：`span_us - covered_us`（区间并集覆盖后计算）。
5. 因果边：`EVENT_WAIT -> EVENT_RECORD` 时间邻近匹配，得到 producer/consumer stream 边。
6. micro-loop：在热点 stream 上挖重复 motif，输出步级耗时与步间 gap。

### 7.4 输出物

输出目录包含：

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

---

## 8. 这次 run 的 analyzer 汇总（已聚合 4 个 DB）

使用目录：`analyzer/out/2x2_20260418_154241_agg_v2check`

- `db_count=4`
- `task_count=1,754,398`
- 全局 task 占比：
  - `wait=63.298%`
  - `comm=24.711%`
  - `exec=11.984%`
- wait 拆分：
  - `comm_wait=31.903%`
  - `sync_wait=24.410%`
  - `unknown_wait=6.985%`
- `EVENT_WAIT` 匹配 `EVENT_RECORD` 覆盖率：`94.70%`

这说明当前 workload 明显是 wait 主导（低负载/同步等待占比高），并且 stream 间依赖关系可被较高覆盖率地恢复。

---

## 9. 原始产物 -> 分析结果的映射（可固化为标准口径）

- `msprof_*.db/TASK` -> 时间线主事实（时序与耗时）
- `STRING_IDS + *_TASK_INFO` -> task 命名与语义标签
- `COMMUNICATION_OP/COMMUNICATION_TASK_INFO` -> 通信归因、wait 拆分、链路语义
- `mindstudio_profiler_output/*.csv` -> 快速 sanity check（与 analyzer 结果互证）
- `msprof.log` -> 导出异常解释（缺失 device data、导出重复等）

建议后续固定“先 DB 后 CSV、先 device+stream 再跨流因果”的解析顺序。

---

## 10. 下一步建议（面向你当前目标）

1. 先把“高价值 stream 过滤”规则接入 analyzer 主流程（例如 cumulative top 90% + 小流剔除阈值）。
2. 在 `meta.json` 增加 `db -> main_device/globalPid` 映射，方便你把 timeline 观察结果与 analyzer 行号快速对齐。
3. 再引入 vLLM 内部显式阶段标记（prefill/decode step id），把当前粗 phase 升级成业务 phase。

## 11. 目标与架构设计文档

本次 run 的产物解读之外，项目级目标（augmentation bundle）与统一源码架构设计已单独整理在：

- `/home/user8/workspace/imonitor/worklogs/apr19/msprof_augmentation_bundle_architecture.md`
  - 其中第 `1.1/1.2/10` 节是“工程硬约束 + 验收口径 + 依赖策略”。


## 附录A：4个 PROF 的逐项对照

| PROF | msprof_db | TASK主设备 | TASK行数 | span_ms | 有效device目录 | 备注 |
| --- | --- | --- | ---: | ---: | --- | --- |
| PROF_000001_20260418074300279_PJPDAGBKBLQMHQEA | msprof_20260418074418.db | 4 | 362328 | 53695.083 | device_4 | - |
| PROF_000001_20260418074300516_GMKALRMKQFIKHKAC | msprof_20260418074448.db | 6 | 407203 | 52519.435 | device_6 | device_4:meta-only |
| PROF_000001_20260418074300543_IQQMBLQCBJOJNILB | msprof_20260418074524.db | 5 | 551022 | 52523.599 | device_5 | device_4:meta-only |
| PROF_000001_20260418074300649_GADBRFKGQNMCOQBC | msprof_20260418074556.db | 7 | 443550 | 52374.972 | device_7 | device_4:meta-only |
