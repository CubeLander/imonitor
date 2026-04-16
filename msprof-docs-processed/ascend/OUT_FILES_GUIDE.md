# Ascend `out/` 产物说明书

这份说明针对目录：

- `/home/user8/workspace/imonitor/msprof-docs-processed/ascend/out`

## 1. 顶层目录含义

`out/` 下有两类结果：

- `vllm_smoke/`: 只跑 vLLM workload（不包 msprof）的结果。
- `msprof_smoke/`: `msprof` 包裹 vLLM workload 的结果。

每次执行都会生成一个 `run_id` 子目录，例如 `20260414_163910`。

## 2. `vllm_smoke/<run_id>/` 文件说明

常见文件：

- `exit_code.txt`: 脚本退出码，`0` 表示 smoke 成功。
- `run_meta.env`: 本次运行参数（模型、tp/pp、可见卡号等）。
- `workload.log`: 运行日志，包含模型加载、图编译、生成过程。
- `workload_result.json`: 结构化结果（耗时、输出文本、错误信息）。

用途：

- 证明“模型能跑起来并产出文本”。
- 作为 msprof 前置可用性检查。

## 3. `msprof_smoke/<run_id>/` 文件说明

### 3.1 run 级文件（最先看）

- `exit_code.txt`: `msprof` 命令退出码。
- `msprof.log`: `msprof` 主日志（含导出、query、finished 关键字）。
- `run_meta.env`: 采集参数快照。
- `workload_result.json`: 被包裹 workload 的结果。
- `prof_dirs.txt`: 本次生成的 `PROF_*` 目录清单。
- `key_files.txt`: 关键导出文件清单（聚焦 `mindstudio_profiler_output`）。

### 3.2 `PROF_*` 目录（一次采集会有 1~N 个）

每个 `PROF_*` 里通常包含：

- `mindstudio_profiler_output/`: 人可读导出结果（重点目录）。
- `mindstudio_profiler_log/`: 解析/导出阶段日志。
- `host/`: Host 侧原始采集数据与 sqlite。
- `device_*`: Device 侧原始采集数据与 sqlite。
- `msprof_*.db`: 汇总数据库（可供后续离线分析）。

## 4. `mindstudio_profiler_output/` 关键文件怎么读

高价值文件（优先级从上到下）：

- `op_statistic_*.csv`
  - 看“按 OP Type 聚合”的总耗时分布。
  - 用它快速定位最耗时算子类型（如 `MatMulV2`）。
- `op_summary_*.csv`
  - 看单算子明细（Op 名、形状、时长、上下文）。
  - 用于从“算子类型”下钻到“具体算子实例”。
- `api_statistic_*.csv`
  - 看 ACL/Runtime/API 层开销。
  - 识别是否被 `DeviceSynchronize`、内存拷贝等主导。
- `communication_statistic_*.csv`
  - 看通信算子（`hcom_*`）开销占比。
  - 多卡性能分析时非常关键。
- `task_time_*.csv`
  - 最细粒度 task 时间线（任务级）。
  - 用于细查长尾任务。
- `ai_core_utilization_*.csv`, `ai_vector_core_utilization_*.csv`
  - 看 AI Core 利用率相关指标均值/分布。
- `l2_cache_*.csv`
  - 看 L2 命中与访存行为。
- `npu_mem_*.csv`, `npu_module_mem_*.csv`, `hbm_*.csv`, `llc_read_write_*.csv`
  - 看内存与带宽维度瓶颈。
- `msprof_*.json`
  - 可视化工具常用元数据。
- `README.txt`
  - 导出目录字段说明。

## 5. `host/` 与 `device_*` 为什么文件这么多

这些目录是原始/中间采集数据，不是给人直接读的报表，常见类型：

- `data/*.slice_*`: 切片原始数据。
- `*.done` / `*.complete`: 采集/解析阶段标志位。
- `sqlite/*.db`: 原始数据数据库。
- `info.json`, `start_info`, `incompatible_features.json`: 采集元信息。

结论：

- 日常分析优先看 `mindstudio_profiler_output`。
- 只有做深度追溯时再进 `host/device/sqlite`。

## 6. 你可以用的“5 分钟排查流程”

1. 看 `exit_code.txt` 和 `msprof.log` 是否成功结束。
2. 看 `mindstudio_profiler_output/` 是否含 `op_statistic`, `api_statistic`, `communication_statistic`。
3. 先看 `op_statistic` 的 Top 耗时。
4. 再看 `api_statistic` 判断是否 API 同步/拷贝开销过高。
5. 多卡场景看 `communication_statistic` 是否占比过高。
6. 若算力利用低，再看 `ai_core_utilization` 与 `l2_cache`。
7. 若怀疑内存瓶颈，再看 `npu_module_mem` / `hbm` / `llc_read_write`。

## 7. 现有自动化脚本对应关系

- 总览报告：
  - `generate_smoke_report.py` -> `out/report.md`
- 单 run 深度摘要：
  - `analyze_msprof_output.py` -> `<run_dir>/analysis.md`

你可以把这两个脚本视为“把海量原始文件压缩成可读摘要”的第一层工具。

## 8. CSV逐表释义（字段含义 + 数据来源 + 物理信号）

以下内容对应你当前目录：

- `/home/user8/workspace/imonitor/msprof-docs-processed/ascend/out/msprof_smoke/20260414_163910/PROF_000001_20260414083930904_NRFNGCKOBLFGJDAC/mindstudio_profiler_output`

### 8.1 `task_time_*.csv`（任务级时间线）

- 行粒度：1行 = 1个Task（调度单元）。
- 数据来源：Runtime/任务调度器时间戳（CANN任务下发与完成事件）。
- 物理信号：
  - `task_start/task_stop`: NPU任务开始/结束时刻（主机时钟域映射）。
  - `task_time`: 从调度到执行结束的总时长，含调度等待与执行响应。
- 字段阅读：
  - `kernel_type`: 在哪类执行单元运行（如 `KERNEL_AICORE` / `KERNEL_AICPU`）。
  - `stream_id/task_id`: 与 `op_summary` 关联定位具体算子实例。

### 8.2 `op_summary_*.csv`（算子实例明细）

- 行粒度：1行 = 1个算子实例（通常对应1个Task，通信类可能聚合显示）。
- 数据来源：GE/Runtime算子下发记录 + task-time采集 + 可选PMU指标。
- 物理信号：
  - `Task Start/Duration/Wait`: 调度器时间线信号。
  - `Block Dim/Mix Block Dim`: 并行块数量，反映并行占用核数。
  - `Task Type`: 实际硬件执行类型（`AI_CORE`/`AI_VECTOR_CORE`/`AI_CPU`/`COMMUNICATION`）。
  - 形状/数据类型字段：来自图执行时的算子元信息，不是硬件计数器。

### 8.3 `op_statistic_*.csv`（按算子类型聚合）

- 行粒度：1行 = 同一 `OP Type + Core Type (+Device)` 的聚合统计。
- 数据来源：`op_summary` 聚合。
- 物理信号：间接来自任务时间线，不是直接PMU采样。
- 字段阅读：
  - `Total/Avg/Min/Max Time(us)`: 同类型算子的时间分布。
  - `Ratio(%)`: 该类型在全部算子总耗时中的占比。

### 8.4 `api_statistic_*.csv`（API层聚合）

- 行粒度：1行 = 同一API名在本次运行中的聚合统计。
- 数据来源：AscendCL/Runtime/Node/Model/Communication API调用埋点。
- 物理信号：主机侧API调用开始/结束时间戳（软件层信号）。
- 字段阅读：
  - `Level`: API所属层（如 `acl`/`runtime`/`node`）。
  - `Variance`: 调用稳定性指标，越小通常越稳定。

### 8.5 `communication_statistic_*.csv`（集合通信聚合）

- 行粒度：1行 = 一类集合通信算子（如 `hcom_allReduce_`）的聚合。
- 数据来源：HCCL通信任务统计。
- 物理信号：通信任务执行时长（链路+同步等待的综合效果）。
- 字段阅读：
  - `Ratio(%)`: 该通信算子类型在“全部通信时间”中的占比，不是全程序占比。

### 8.6 `ai_core_utilization_*.csv`（AI Core管线占用）

- 行粒度：1行 = 1个AI Core核的统计结果。
- 数据来源：AI Core PMU计数器（task-based采集后汇总）。
- 物理信号（均为cycle占比或事件比率）：
  - `mac_ratio`: Cube/MAC矩阵计算相关cycle占比。
  - `scalar_ratio`: 标量指令cycle占比。
  - `mte1_ratio`: L1->L0A/L0B搬运相关cycle占比。
  - `mte2_ratio`: 主存(DDR/HBM)->AI Core搬运相关cycle占比。
  - `fixpipe_ratio`: L0C->OUT/L1搬运相关cycle占比。
  - `icache_miss_rate`: 指令Cache未命中率。

### 8.7 `ai_vector_core_utilization_*.csv`（AI Vector Core管线占用）

- 行粒度：1行 = 1个Vector Core核的统计结果。
- 数据来源：Vector Core PMU计数器。
- 物理信号：
  - `vec_ratio/mac_ratio/scalar_ratio/mte1/mte2/mte3`: 各类指令或搬运阶段cycle占比。
  - `mte3_ratio`: AI Core->主存回写相关cycle占比。
  - `memory_bound`: `mte2_ratio / max(mac_ratio, vec_ratio)`，大于1通常表示访存受限更明显。
  - `icache_miss_rate`: 指令cache miss率。

### 8.8 `l2_cache_*.csv`（L2命中与替换）

- 行粒度：1行 = 某个Task/Stream下某算子的L2统计。
- 数据来源：L2相关硬件计数器（DHA路径统计）。
- 物理信号：
  - `Hit Rate`: 请求命中L2的比率。
  - `Victim Rate`: 未命中并触发替换的比率。
- 说明：首个算子有时不具参考性，建议看整体分布与热点算子。

### 8.9 `llc_read_write_*.csv`（LLC/L3带宽）

- 行粒度：常见是 `Mode(read/write) + Task(如Average)` 的统计行。
- 数据来源：LLC硬件带宽计数器（`--sys-hardware-mem`路径）。
- 物理信号：
  - `Hit Rate(%)`: LLC命中率。
  - `Throughput(MB/s)`: LLC吞吐，来自单位时间字节计数。

### 8.10 `hbm_*.csv`（HBM带宽）

- 行粒度：常见是设备级统计（如 `Metric=Average`）。
- 数据来源：HBM控制器带宽计数器。
- 物理信号：
  - `Read/Write(MB/s)`: HBM读写带宽平均值或窗口统计值。

### 8.11 `npu_mem_*.csv`（NPU内存占用时间序列）

- 行粒度：1行 = 某时刻一次采样。
- 数据来源：驱动内存占用采样（由 `--sys-hardware-mem` + 采样频率开关控制）。
- 物理信号：
  - `event`: `app` 或 `device` 视角。
  - `ddr/hbm/memory`: 对应时刻内存占用（KB），`memory` 为总和。
  - `timestamp(us)`: 采样时间戳。

### 8.12 `npu_module_mem_*.csv`（组件内存占用时间序列）

- 行粒度：1行 = 某组件在某时刻的保留内存值。
- 数据来源：CANN组件内存管理统计。
- 物理信号：
  - `Component`: 如 `APP/HCCL/RUNTIME/SLOG` 等组件。
  - `Total Reserved(KB)`: 组件维度保留内存。
  - `Timestamp(us)`: 采样时刻。

## 9. 这些数据“怎么来的”的最短链路

1. 运行 `msprof ... <你的vllm workload>` 时，msprof通过Runtime/ACL/HCCL埋点记录软件层时间线。  
2. 同时按开关采集硬件计数器（PMU、L2/LLC/HBM、内存占用采样）。  
3. 采集完成后，解析器把原始slice/db聚合为 `mindstudio_profiler_output/*.csv`。  
4. 因此：
   - `api/op/task/communication` 更偏“软件执行路径时间统计”；
   - `ai_core/vector/l2/llc/hbm` 更偏“硬件计数器与带宽信号”；
   - `npu_mem/npu_module_mem` 更偏“内存容量占用时间序列”。
