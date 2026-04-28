# 本科毕业设计论文统一初稿

题目建议：**面向 Ascend NPU 分布式推理的 Profiling 信号聚合分析与优化验证方法设计**

作者：田景远

说明：本文档用于合并文献综述与论文正文。当前版本先固定论文主线、章节结构、已有材料与待补内容，后续再迁移到学校 LaTeX 模板。

## 摘要

随着大模型推理服务从单机离线运行走向分布式在线部署，推理系统的性能瓶颈不再局限于单个算子，而是同时受到请求调度、KV cache 管理、通信同步、异构运行时和源码实现细节的影响。以 Ascend NPU 与 vLLM 分布式推理为例，开发者通常需要同时查看 `msprof` 时间线、stream 任务、通信事件、同步等待和框架源码。原始 profiling 信号中包含大量细粒度事件与噪声，人工定位成本高，且难以形成可复现的优化证据链。

本文设计并实现了一套面向 Ascend NPU 分布式推理的离线 profiling 信号分析方法与工具链 `hprofile`。该方法以 Ascend `msprof` 原始产物为输入，围绕“从噪声中聚合有效性能信号”的目标，完成统一事件建模、等待/通信/执行分类、跨 stream 因果边推断、Loop Tree 重复模式压缩、节点级性能统计、源码锚点记录与离线报告生成。本文重点不在于展示原始曲线，而在于把细粒度 trace 数据聚合为可解释的瓶颈证据，并通过 benchmark gate 验证优化 patch 的收益。

在 vLLM-Ascend 分布式推理实验中，本文系统发现关键 stream 存在 wait-bound 与 communication-bound 行为，并进一步定位到 OProj all-to-all 通信路径中每轮执行前重复申请接收缓冲区的问题。基于该证据链实现 recv buffer 复用后，固定 workload 下吞吐从 `10.9523 rps` 提升到 `11.3512 rps`，提升 `3.6422%`，p95 proxy 从 `730.8 ms` 降至 `705.2 ms`，错误率保持为 `0.0`。实验表明，本文系统能够将异构 trace 分析、源码定位和性能优化验证打通，为大模型推理场景下的可追溯性能调优提供了一条实用路径。

关键词：Ascend NPU；vLLM；性能分析；Tracing；源码归因；大模型推理

## 第 1 章 绪论

### 1.1 研究背景

大模型推理服务正在从离线批处理任务转向在线、低时延、高并发的生产系统。与传统深度学习推理相比，大语言模型推理由 prefill 与 decode 多阶段组成，且每个请求会在多轮 token 生成中反复参与调度。服务系统不仅需要提升吞吐，还要控制首 token 时延、token 间时延、尾延迟与 SLO 达标率。

在硬件平台方面，GPU/NPU 异构加速器成为大模型推理的主要承载平台。Ascend NPU 通过 CANN、HCCL、`msprof` 等工具链提供了完整的算子执行与通信 profiling 能力；vLLM 则通过 PagedAttention、continuous batching 和分布式并行机制提升推理效率。然而，在真实工程中，profiling 结果体量大、字段分散、语义层级复杂。原始时间线中既包含有价值的同步、通信和执行信号，也包含大量重复事件、短任务和局部噪声。开发者不仅需要知道“哪里耗时”，还需要回答“哪些信号真正构成瓶颈”“为什么等待”“哪个 stream 触发等待”“对应到哪段框架源码”“修改后是否真的有效”。

因此，本文关注的问题不是单次 benchmark 成绩，而是如何构建一套从 tracing 数据到性能归因，再到优化验证的系统化路径。

### 1.2 研究问题

本文将研究问题归纳为以下四点：

1. 如何从 Ascend `msprof` 原始产物中抽取统一、可复用的 profiling 事件模型；
2. 如何在细粒度 task timeline 中区分执行、通信、同步等待和空转行为，并降低局部噪声对判断的影响；
3. 如何把大规模 stream trace 聚合压缩成可读、可统计、可回溯的结构化表示；
4. 如何将聚合后的性能信号连接到源码优化，并通过固定协议验证优化收益。

### 1.3 本文工作

本文完成的主要工作包括：

1. 设计并实现 `analyzer/hprofile` 离线分析模块，支持 Ascend `msprof` 目录发现、`TASK` 表聚合、统一 profile 导出、lineage 与 quality report 生成。
2. 设计 profiling 信号聚合流程，将原始 task timeline 中的细粒度事件归并为 wait、comm、exec、idle 等可解释指标，降低单个事件噪声对分析结论的影响。
3. 实现跨 stream causality 推断，输出 global breakdown、stream breakdown、phase breakdown 和 producer/consumer 等待边。
4. 实现 Loop Tree 分析，将重复 stream 事件序列压缩为 macro/tree，并进一步生成节点级性能统计与源码锚点字段。
5. 构建一套 patch benchmark gate，在固定 workload 下比较 baseline 与 trial，依据吞吐、噪声、p95 和错误率决定 patch 是否接受。
6. 在 vLLM-Ascend OProj all-to-all 通信路径上完成真实优化案例，形成从 trace 证据到 PR 的闭环。

## 第 2 章 相关工作

本章合并现有文献综述内容，并围绕本文系统设计需要组织，而不是单纯罗列工具。

### 2.1 GPU/NPU Profiling 方法

Roofline 模型通过算力上界和带宽上界帮助判断程序瓶颈属于计算受限还是访存受限，是加速器性能分析的经典方法。后续分层 Roofline 与 time-based Roofline 将内存层级、运行时间和深度学习 workload 特征纳入分析，使其更适合解释真实推理流水线。

面向 NPU 的性能分析还需要关注片上存储、通信链路、同步事件和运行时调度。TPU 数据中心性能分析工作表明，硬件峰值能力并不能直接决定服务质量，关键在于 workload 形态与硬件执行路径是否匹配。对应到 Ascend 平台，不能只看总利用率，还要分解 stream、task、通信与等待行为。

HPCToolkit 等工作进一步说明，异构程序分析需要将主机侧调度、设备侧执行和源码上下文放在统一视角中。本文借鉴其上下文归因思想，但实现对象聚焦于 Ascend/vLLM 推理 trace。

### 2.2 LLM Serving 与 vLLM 性能问题

vLLM 的 PagedAttention 将 KV cache 管理显式化，通过分页式块管理降低显存碎片与过度预留，是大模型推理系统的重要基础。Orca 提出 iteration-level scheduling，说明生成式模型不适合只按请求粒度调度。Sarathi-Serve 与 DistServe 进一步强调 prefill/decode 阶段差异、吞吐与时延折中、goodput 与 SLO 约束。

这些研究共同说明，LLM serving profiling 不能只统计 kernel 时间，而必须同时记录阶段、调度、通信、内存和请求行为。本文系统在实现上先以 Ascend `msprof` 与 vLLM 分布式 smoke workload 为主要对象，并为后续 prefill/decode 显式阶段标记预留接口。

### 2.3 Trace 压缩与模式挖掘

大规模并行系统的 trace 数据随并发度、设备数和采样粒度快速增长。ScalaTrace 等通信 trace 压缩工作证明，可以通过结构化压缩保留通信模式，同时降低存储和分析成本。Xu 等人在 MASCOTS 2010 提出的 execution trace loop nest discovery 方法进一步指出，trace 压缩不应只追求字符串变短，还应显式发现循环嵌套结构，使代表性片段更容易被识别。该思想对大模型推理同样重要：stream 上的重复 kernel、通信、等待序列往往体现了模型层或推理迭代的结构。

本文中的 Loop Tree 正是沿着这一方向设计：先把 stream task 序列转化为符号序列，再挖掘重复 macro，最终形成树状结构。与原工作主要面向 CPU/MPI execution trace 不同，本文将重复结构发现思想迁移到 Ascend NPU stream profiling trace，并结合 wait/comm/exec 语义分类、时间窗统计和源码锚点，使压缩后的结构能够继续服务于性能归因。

### 2.4 源码归因与可解释优化

仅有时间线无法回答“应该改哪段代码”。HPCToolkit 通过调用上下文树将采样开销映射到函数、循环和源码行，为并行程序优化提供了可解释路径。异构 GPU 扩展则进一步处理 CPU/GPU 事件的统一归因问题。

本文在工程上采用证据驱动的源码锚点策略：通过算子名、任务名、通信类型、source notes 和人工复核字段，将 Loop Tree 节点与 vLLM/vLLM-Ascend 源码位置建立候选联系。本文不声称完全自动精准定位源码，而是强调每个结论都带有证据和置信边界。

### 2.5 现有工作的不足

综合已有工作，本文认为仍存在三类不足：

1. profiling 工具输出强，但跨层语义弱，难以直接形成优化动作；
2. LLM serving 研究强调调度与系统优化，但具体 trace 到源码的工程闭环较少；
3. trace 压缩和源码归因常被分开讨论，缺少“压缩后仍可解释”的统一路径。

本文系统的切入点是：以 Ascend/vLLM 为主要平台，构建 tracing 到 source attribution，再到 benchmark gate 的实用闭环。

## 第 3 章 需求分析与总体设计

### 3.1 需求分析

系统需要满足以下需求：

1. **离线解析**：支持处理已有 Ascend `msprof` 原始产物，自动发现多 `PROF_*` 目录和多个 `msprof_*.db`。
2. **统一建模**：将 run、device、stream、task、phase、edge、source anchor 等对象组织成稳定 schema。
3. **信号聚合**：从原始时间线中识别 wait/comm/exec、空转、跨 stream 等待边和重复 loop，将分散事件聚合成可解释瓶颈信号。
4. **可追溯报告**：每个分析结论应能回到原始文件、表、字段和处理规则。
5. **优化验证**：分析结果应能进入 patch 试验流程，通过固定 benchmark gate 判断是否有效。

### 3.2 总体架构

`hprofile` 采用四层架构：

1. **输入适配层**：发现并读取 Ascend `msprof` 原始目录、`msprof_*.db`、导出 CSV 和 run manifest。
2. **统一建模层**：统一表示 device、stream、task、phase、edge、lineage 和 quality 信息。
3. **信号分析层**：执行分类、聚合降噪、causality 推断、Loop Tree 压缩、节点级统计与源码锚点生成。
4. **报告与验证层**：生成离线 web bundle、可读报告和 patch benchmark 记录。

可在正式论文中绘制图 3-1：系统总体架构图。

### 3.3 关键产物

`hprofile_processed` 目录下的核心产物包括：

1. `derived/unified_profile.json`：统一 profile 数据；
2. `derived/lineage.json`：指标来源与处理路径；
3. `derived/quality_report.json`：数据覆盖率和质量信息；
4. `derived/legacy_stage/*`：全局 breakdown、stream breakdown、causality edge 等；
5. `derived/loop_analyzer/*`：Loop Tree、macro、symbols、可读报告；
6. `web/index.html`：离线可视化报告。

## 第 4 章 关键方法设计

### 4.1 原始 Profiling 信号模型

本文的分析对象是 Ascend `msprof` 采集生成的原始 profiling 产物。一次 workload profiling 对应一个 run 目录，该目录通常包含环境快照、workload 执行结果、采集日志、`PROF_*` 子目录列表以及若干 `PROF_*` profiler 产物目录。本文将这些文件视为 raw layer，即只记录事实，不直接给出性能结论。

单次 run 的典型目录结构包括：

| 产物 | 含义 |
| --- | --- |
| `run_meta.env` | 采集开关与环境快照 |
| `workload_result.json` | workload 执行状态、耗时与摘要信息 |
| `msprof.log` | 采集、解析、导出过程日志 |
| `prof_dirs.txt` | 本次 run 的 `PROF_*` 子目录列表 |
| `key_files.txt` | 导出关键文件索引 |
| `exit_code.txt` | 采集脚本退出码 |
| `PROF_*/` | 按采集进程归档的 profiler 产物目录 |

每个 `PROF_*` 目录内部通常包含四类数据：

1. `msprof_*.db`：时序分析的主输入；
2. `mindstudio_profiler_output/*`：由数据库导出的 JSON/CSV 可读视图；
3. `host/*`：主机侧元信息、原始切片和中间库；
4. `device_n/*`：设备侧元信息、原始切片和中间库。

其中，`msprof_*.db` 是本文信号聚合分析的核心输入。其主要表包括：

| 表 | 作用 |
| --- | --- |
| `TASK` | 时序事实表，记录任务起止时间、设备、stream、connection 等信息 |
| `STRING_IDS` | 字符串字典，用于反解 task/op 名称 |
| `COMPUTE_TASK_INFO` | 计算任务语义，如 op name、op type |
| `COMMUNICATION_TASK_INFO` | 通信任务语义，如 src/dst、link、size、bandwidth |
| `COMMUNICATION_OP` | 通信算子级语义，如 connectionId、algType、opType |
| `ENUM_HCCL_*` | HCCL 通信相关枚举映射 |

从这些原始表中可以抽取出本文使用的基本信号对象：

1. **Run**：一次 workload profiling 执行；
2. **Process / PROF**：一次采集进程对应的 profiler 产物集合；
3. **Device**：NPU 设备编号；
4. **Stream**：设备上的执行流；
5. **Task / Event**：stream 上的细粒度执行、通信、等待或同步任务；
6. **Timestamp / Duration**：任务开始时间、结束时间与持续时间；
7. **Task type / Name**：用于判断事件语义的原始类型与名称；
8. **Communication metadata**：通信大小、链路、算法类型等补充信息。

需要注意的是，同一 run 的不同 `msprof_*.db` 之间可能存在 `stream_id` 重号，因此跨数据库聚合时不能只使用 `stream_id`，而应至少使用 `(db_id, device_id, stream_id)` 或 `(process/rank, device_id, stream_id)` 作为复合键。跨 `PROF_*` 时间线拼接时，本文以数据库中的 `TASK.startNs/endNs` 和 `SESSION_TIME_INFO.startTimeNs/endTimeNs` 作为时间参考。

### 4.2 原始信号的噪声与语义缺口

原始 profiling 数据并不等同于性能结论。`msprof` raw layer 记录的是大量细粒度事实事件，而优化者真正需要的是能指导源码或配置改动的瓶颈证据。二者之间存在明显语义缺口。

第一，原始 task 数量大且重复度高。一个分布式推理 run 中，计算 kernel、通信任务、event wait、event record 和运行时同步事件会在多个 stream 上反复出现。单独观察某个 task 的耗时，容易受到短任务噪声、调度抖动和局部偶然性的影响。

第二，性能语义分散在多张表和多个目录中。`TASK` 表提供时间线事实，`STRING_IDS` 提供名称反解，`COMPUTE_TASK_INFO` 和 `COMMUNICATION_TASK_INFO` 提供计算与通信语义，导出 CSV/JSON 又提供另一套可读视图。如果不进行统一建模，同一个瓶颈可能被拆散在多个文件中。

第三，部分重要信号不是显式事件。例如 stream 空转不是一个独立 task，而需要根据相邻任务时间窗之间的 gap 推导；跨 stream 等待关系也不是直接给出的依赖图，而需要基于 `EVENT_WAIT` 与 `EVENT_RECORD` 的时间配对推断。

第四，原始事件粒度与优化动作粒度不匹配。raw layer 的基本单位是 task，但优化动作通常发生在模型阶段、通信路径、框架函数、源码行或环境配置上。因此，本文需要将 task-level raw signal 聚合为 optimization-level evidence。

基于上述问题，本文采用“先统一、再分类、再聚合、再解释”的方法，将原始 profiling 信号转化为面向优化决策的多层证据。

### 4.3 Machine-level Runtime Profile 中间表示层

原始 `msprof` 数据通常以 process 为单位生成数据库。对于一个分布式推理 workload，一次 profiling run 可能包含多个 process、多个 device 以及每个 process-device 组合下的多个 stream。如果分析模块直接分别读取每个 db，就容易产生局部视角偏差：某个 db 内部最显著的 stream 未必是整机 workload 中最重要的 stream。因此，本文在 raw layer 与具体分析算法之间引入 machine-level runtime profile 中间表示层，先将同一次 run 中所有 process 的 profiling 结果集成为统一的运行级数据模型，再在该模型上进行 stream 选择、信号聚合、因果分析和 Loop Tree 压缩。

该中间层的核心原则是任务无关。它不依赖具体模型并行策略，也不要求 profiling 框架理解 rank id、tensor parallel id 或 pipeline parallel id 等上层训练/推理语义。rank 信息可以作为可选 metadata 保存，但不应成为事件模型的主键。相反，底层运行时分析更关心 process、device 和 stream 之间的关系：一个 process 可能访问多个 device，一个 device 也可能被多个 process 访问，而 stream id 通常只在特定 process-device 上具有局部意义。因此，本文采用如下全局键：

```text
process_key       = source_db_id
process_device    = (process_key, device_id)
global_stream_key = (process_key, device_id, stream_id)
event_key         = (process_key, device_id, stream_id, task_id/global_task_id, start_ns, end_ns)
```

其中 `source_db_id` 对应原始 `msprof` 数据库，也可进一步与 PROF 目录、pid 或启动命令 metadata 关联。`device_id` 必须进入 stream 键，因为同一进程可能同时访问多个设备；`stream_id` 不能单独作为全局唯一标识，因为不同 process 或不同 device 上可能存在相同数值的 stream id。

基于该键空间，中间层至少生成以下聚合对象：

| 对象 | 作用 |
| --- | --- |
| process summary | 描述每个 process 的总任务时间、事件数量和访问 device 集合，用于区分主负载进程与辅助进程 |
| device summary | 描述每个 device 上来自不同 process 的任务分布，用于观察设备间负载与跨进程访问关系 |
| stream summary | 以 `global_stream_key` 为单位统计 busy time、事件数、exec/comm/wait 占比和事件密度 |
| event table | 保存规范化后的 task 事件，作为 causality、Loop Analyzer 和源码归因的共同输入 |
| candidate streams | 根据全局资源占用、事件密度和后续压缩收益筛选值得深入分析的 stream |
| machine timeline | 将各 process 导出的 trace event timeline 合并为整机级 Perfetto trace，便于人工观察跨进程、跨设备和跨 stream 的时序关系 |

这样，后续分析不再从“每个 db 各选若干 top stream”开始，而是先在整机视角下找出真正占用资源最多、事件最密集、最可能包含关键重复结构的 stream。该设计也为后续扩展到跨 process、跨 device、跨 stream 的全局 pattern 聚合奠定基础。

除结构化表格外，中间层还保留一份面向人工观察的 machine-level timeline。原始 `mindstudio_profiler_output/msprof_*.json` 已经是 trace event 格式，但每个文件只覆盖单个 process 的局部视角。本文在合并时不改变事件时间戳和持续时间，而是为每个 process 分配稳定的 `process_key`，重写 trace event 的 `pid` 以避免不同导出文件之间发生冲突，并在 `args` 中保留原始 PROF 目录、原始 pid/tid 和 process key。合并后的 timeline 仍可直接在 Perfetto 中打开，同时具备整机视角：开发者可以在同一时间轴上观察多个 process、device 和 stream 的运行关系，再结合结构化 summary 选择真正值得进行 Loop Analyzer 的热点 stream。

### 4.4 统一事件模型与语义分类

本文将 machine-level runtime profile 中的 profiling 事件抽象为统一事件对象。每个事件至少包含：

- run id；
- process key；
- device id；
- stream id；
- start/end timestamp；
- duration；
- task type；
- semantic bucket；
- raw source file；
- lineage 信息。

可写作如下 schema：

```text
Event = {
  run_id,
  process_key,
  device_id,
  stream_id,
  global_stream_key,
  start_ns,
  end_ns,
  duration_ns,
  raw_task_type,
  raw_name,
  semantic_type,
  phase_id,
  source_ref,
  lineage
}
```

其中 `semantic_type` 是后续聚合分析的基础。本文将原始 task 归入以下语义类别：

| 语义类别 | 含义 |
| --- | --- |
| `exec` | 计算 kernel 或算子执行任务 |
| `comm` | HCCL/all-reduce/all-to-all 等通信相关任务 |
| `wait` | event wait、同步等待或通信等待 |
| `sync` | event record、barrier 等同步辅助事件 |
| `idle` | 由 stream task gap 推导出的空转时间 |
| `other` | 无法稳定归类或对当前分析不关键的任务 |

其中 `idle` 并不一定来自原始 task，而是由相邻任务时间窗之间的 gap 推导得到。`wait` 还可进一步拆分为 `comm_wait`、`sync_wait` 和 `unknown_wait`，用于区分通信路径等待、同步等待和暂时无法解释的等待。

### 4.5 Profiling 信号聚合与降噪

原始 `msprof` timeline 中包含大量细粒度 task。单独观察某个 task 的耗时，很容易受到调度抖动、短任务噪声和局部偶然性的影响。本文采用“先分类、再聚合、再解释”的分析策略，将原始事件转化为稳定的瓶颈信号。

聚合流程包括：

1. 按 task type 和事件语义将事件归入 `exec`、`comm`、`wait`、`other`；
2. 在 run、phase、stream 三个粒度上分别统计总时长、占比和 idle gap；
3. 将 wait 进一步拆分为 `comm_wait`、`sync_wait` 和 `unknown_wait`；
4. 只在聚合后占比高、跨 run 或跨 stream 反复出现的信号上形成瓶颈判断；
5. 对每个结论保留 lineage 和 quality 信息，避免把低覆盖率数据解释为确定结论。

这种方式的目标是从原始噪声中提取“可重复、可追溯、可优化”的信号，而不是简单展示所有事件。

### 4.6 等待与通信分类

分类目标不是替代硬件 profiler，而是在 profiler 输出之上提供稳定的工程解释层。本文根据 task type、事件名称、通信库标识和 wait/record 语义对 task 进行归类。

对于每个 run，系统输出：

```text
total_task_us
span_us
idle_gap_us
idle_ratio_span
wait_ratio
comm_ratio
exec_ratio
```

这些指标分别从全局、stream 和 phase 粒度统计，用于判断瓶颈类型。

### 4.7 跨 Stream 因果边推断

在 Ascend timeline 中，`EVENT_WAIT` 与 `EVENT_RECORD` 可以反映 stream 间同步关系。本文基于时间窗口将 wait 事件与对应 record 事件配对，统计 producer stream 与 consumer stream 之间的等待边。

输出字段包括：

- producer stream；
- consumer stream；
- wait 总时长；
- wait 占比；
- p95 wait；
- unblock delay；
- 匹配率。

需要强调的是，该因果边是时间线启发式推断，不是 runtime 显式依赖表。因此正式论文中应同时报告匹配率和置信边界。

### 4.8 跨 Rank Collective Meta Pattern

在完整 machine-level timeline 中，分布式 collective 通信往往表现为跨 process、跨 device 的同步 pattern。以 all-reduce 为例，单次 prefill 过程中，四个 process 分别驱动四张 NPU；从宏观上看，每个 rank 都在执行相似的模型计算序列，但在 all-reduce 阶段会形成稳定的跨卡同步结构。实验观察发现，一个 process-device 上 `Notify Wait` 事件的结束时刻，常与另一个 process-device 上 `EVENT_WAIT` 事件的开始时刻成对出现。这类现象不是单个 stream 内部的重复结构，而是 collective 通信在多个 rank 之间展开时形成的微观同步图。

本文将这类结构称为 collective meta pattern。其基本对象不是单个 task，而是一组跨 rank 的时间邻接边：

```text
edge = (
  source_process, source_device, source_stream, notify_wait_end,
  target_process, target_device, target_stream, event_wait_start,
  delta_t
)
```

其中 `delta_t = event_wait_start - notify_wait_end`。当 `|delta_t|` 落入较小时间窗口，且该配对在多个 step 中稳定重复出现时，可以认为它构成一个候选同步边。对于四卡 all-reduce，一轮通信 step 可表示为一个小型有向图：

```text
G_step = (V_rank_stream, E_notify_to_event)
```

图中的节点表示参与 collective 的 process-device-stream，边表示由 `Notify Wait` 结束与 `EVENT_WAIT` 开始形成的时间配对关系。若连续多个 step 产生同构或近似同构的 `G_step`，则可进一步抽象为：

```text
Repeat(k, CollectiveMotif(G_step))
```

这种表示能够把“人眼在 Perfetto 中看到的跨卡节奏”转化为机器可统计的 pattern。与单 stream Loop Tree 相比，collective meta pattern 的重点不在于压缩某条 stream 的事件序列，而在于描述多个 rank 之间的通信同步拓扑、时间偏移和重复次数。它可以回答以下问题：

1. 一次 collective 是否在多个 rank 上形成稳定重复结构；
2. 哪些 process-device 对之间存在稳定的 notify/event 时间配对；
3. 每个 step 的同步跨度、rank 间 skew 和最长等待边是多少；
4. 某个 rank 是否在多个 step 中反复成为慢边或被等待对象；
5. all-reduce/all-to-all 等 collective 的微观结构是否能解释全局 wait/comm 高占比。

进一步地，真实 vLLM 推理中的 collective pattern 往往不是严格重复。实验中可以观察到，跨 rank 的通信同步结构相对稳定，但各 rank 主力 stream 上的计算事件并不总是完全一致：某些 step 中 matmul 负载较重，某些 step 中 matmul 较轻，甚至某些候选窗口内是否出现对应 matmul 都不稳定。这种现象可能来自连续 batching、prefill/decode 阶段差异、KV cache 状态、shape 变化、算子选择、runtime 分支以及 vLLM/vLLM-Ascend 内部条件路径。因此，本文不应要求 meta pattern 在事件序列层面严格相等，而应采用“锚点稳定、局部可变”的近似匹配策略。

具体来说，可以将 collective meta pattern 分为两层：

```text
Hard anchors:  Notify Wait / EVENT_WAIT / HCCL collective / stream synchronization
Soft region:   anchors 之间或 anchors 附近的 compute、memory、runtime events
```

硬锚点用于划分 step 和建立跨 rank 同步边；软区域用于描述该 step 中各 rank 实际执行的计算负载。对于软区域，不要求事件逐项完全匹配，而是提取统计和语义特征，例如：

1. 是否包含 matmul、RmsNorm、RoPE、projection 等关键算子族；
2. 每类算子的出现次数、总时长、p95 时长和占比；
3. compute/comm/wait 的比例；
4. rank 间 soft region 的时间跨度和 skew；
5. 与源码候选路径相关的 operator family 或 source anchor。

这样，一个 step 可以表示为：

```text
ApproxCollectiveStep = {
  anchors: E_notify_to_event,
  soft_features_by_rank: {
    rank_i: {op_family_counts, op_family_durations, wait_comm_exec_ratio, source_hints}
  }
}
```

多个 step 是否属于同一 meta pattern，不再由原始事件序列是否完全相同决定，而由硬锚点拓扑相似度与软区域特征相似度共同决定：

```text
similarity =
  alpha * topology_similarity(anchors)
  + beta * timing_similarity(delta_t, skew, span)
  + gamma * soft_feature_similarity(op families, ratios, source hints)
```

当拓扑结构稳定、时间偏移落入同一范围，且软区域在算子族和比例上相近时，即使具体 matmul 数量或某些算子是否出现存在差异，也可以归入同一个 approximate meta pattern。该策略更接近人类阅读 Perfetto 的方式：先识别稳定的跨卡同步骨架，再观察每个同步区间内计算负载的变体。

从源码归因角度看，近似匹配的价值在于帮助定位“稳定同步骨架背后的可变计算区域”。如果同一 collective anchor 周围反复出现 attention projection、MLP projection 或 HCCL 路径相关算子族，则可以把该 meta pattern 关联到对应的模型层或框架通信路径；如果某些 rank 的 soft region 长期缺少预期计算或出现额外 runtime API，则可能提示存在调度分支、shape 特化、buffer 管理或同步等待问题。

需要注意的是，`Notify Wait` 与 `EVENT_WAIT` 的时间配对仍然属于 profiling 层面的时序证据，不能直接等同于运行时显式依赖表。因此，本文在使用 collective meta pattern 时，应同时报告匹配窗口、重复次数、覆盖率和异常边，并结合 HCCL/通信事件、stream id、process-device 信息进行人工复核。

### 4.9 Loop Tree 压缩表示

Loop Tree 的目标是将难以阅读的大规模 stream task 序列压缩为层次化结构。该设计借鉴了 Xu 等人 execution trace loop nest discovery 对重复结构的建模思想，同时来源于人类阅读 Perfetto 或 MindStudio timeline 的实际方式：开发者通常不是逐条检查每个 task，而是观察 stream 上周期性重复的块状结构、计算与通信交替出现的节奏、长时间空白区间以及多个 stream 之间的等待关系。这些视觉上的“形状”本质上是重复时序模式，但原始 profiler 产物通常只保存扁平事件列表，没有将这些模式显式建模。

因此，Loop Analyzer 的目标是将人类在 timeline 中通过视觉经验识别的重复执行形状，转化为机器可读、可统计、可归因的结构化表示。其基本流程为：

1. 将 task 转化为符号序列；
2. 挖掘重复片段并形成 macro；
3. 将 macro 与原始事件实例绑定；
4. 输出 tree、readable report、symbols 和 macro 统计；
5. 对节点进行性能聚合与源码锚点记录。

该方法保留了重复结构、节点顺序和实例时间窗，因此比简单 top-k kernel 表更适合解释模型执行周期和通信等待模式。

#### 4.9.1 事件符号化

Loop Analyzer 首先将 stream 上的 task 序列映射为符号序列。符号不是简单使用原始 task id，而是根据 task label、task type 和语义类别进行规范化，使同类事件在不同时间位置上具有相同符号。例如，一段原始事件序列可以抽象为：

```text
A B C W A B C W A B C W
```

其中 `A/B/C` 可对应计算或通信 task，`W` 可对应等待类事件。符号化的作用是将复杂的原始字段压缩为适合模式挖掘的序列，同时保留每个符号对应的原始时间窗和 task id，便于后续回溯。

#### 4.9.2 重复片段发现

在符号序列上，Loop Analyzer 搜索满足最小重复次数约束的连续重复片段。例如：

```text
A B C W A B C W A B C W
```

可以表示为：

```text
Repeat(3, [A, B, C, W])
```

这类 `Repeat` 节点用于表达单个 stream 内相邻、周期性出现的执行结构。它不是源码层面的 `for` 循环，而是 trace 层面的 recurring motif，即重复执行形状。

这种区分很重要：trace 层面的重复结构并不直接等价于某一个源码语法结构，但它往往能够对应到模型执行中的关键重复区域。例如，Transformer 推理中的 attention、MLP、projection、通信同步和调度步骤会在每一层、每一轮 decode 或每个并行分片中反复出现；当这些步骤被映射为稳定的 `Repeat` 或 macro 后，分析者就可以从“成千上万个离散 task”转向“少数几个具有语义边界的重复执行单元”。如果某个重复单元同时具有较高耗时、较高 wait/comm 占比或明显长尾，它就不仅是一个压缩结果，而是源码审计和优化方向选择的重要抓手。

因此，Loop Analyzer 的价值不只是减少 timeline 阅读成本，还在于把人类在 Perfetto 中观察到的块状 pattern 显式化。结构化 pattern 一旦被发现，就可以继续与 task 名称、通信类型、时间窗、stream id 和 source anchor 结合，帮助开发者判断瓶颈更可能位于 attention 计算路径、通信 collective 路径、buffer 管理路径还是调度同步路径。相比直接查看 top-k kernel，重复结构保留了执行顺序和上下文边界，更适合回答“这段耗时属于哪个模型阶段或框架路径”以及“应该从哪片源码开始审计”。

#### 4.9.3 基于收益的 Macro 选择

仅凭“出现重复”不足以决定是否应该压缩。过短或出现次数过少的 pattern 即使重复，也可能因为需要额外保存 macro 定义而使整体表示更复杂。因此，本文采用基于收益的 macro 选择规则：只有当某个 pattern 被替换为 macro 后能够降低序列描述长度时，才接受该压缩。

设候选 pattern 的长度为 \(m\)，在序列中可进行非重叠替换的次数为 \(k\)。压缩前，该 pattern 对应的符号数量为：

\[
L_{before}=k \times m
\]

压缩后，需要保存 \(k\) 个 macro 引用，同时保存一次 macro 定义。本文用 \(m+1\) 近似表示 macro 定义成本，其中 \(m\) 为定义体长度，额外的 1 表示 macro 名称或定义开销。因此压缩后的近似长度为：

\[
L_{after}=k+(m+1)
\]

于是该候选 pattern 的净收益定义为：

\[
Gain = L_{before}-L_{after}
     = k \times m - (k + m + 1)
     = k(m-1)-(m+1)
\]

当且仅当 \(Gain>0\) 时，Loop Analyzer 才接受该 macro。该规则可以避免把偶然重复或低价值短片段引入 macro 表，使压缩结果更接近“减少阅读复杂度”的目标。

在候选排序上，系统优先选择更长、净收益更高、替换次数更多且出现位置更靠前的 pattern。这样做的原因是：较长 pattern 往往对应更完整的执行阶段，较高收益表示压缩后能显著降低表示长度，较多替换次数说明该 pattern 在 trace 中具有稳定重复性。

该准则与最小描述长度思想相近，也与 loop nest discovery 工作强调“代表性循环结构”的目标一致。但本文并不追求通用最优压缩，而是面向 NPU 分布式推理 profiling 场景，选择一种简单、可解释、可回溯的启发式标准。其重点不是获得最短字符串，而是在压缩后仍保留性能分析所需的顺序、重复次数、时间窗和节点统计。

#### 4.9.4 Loop Tree 构建与节点统计

在完成 repeat 和 macro 替换后，Loop Analyzer 将压缩后的序列组织为树状结构。树中的叶子节点对应原子 task，内部节点对应 `Repeat` 或 `MacroRef`。每个节点保存其覆盖的原始时间窗、实例数量和下属子节点。

在增广阶段，系统进一步对树节点计算性能统计，包括：

1. 节点总耗时和平均耗时；
2. p50/p90 等延迟统计；
3. wait/comm/exec 占比；
4. 节点实例时间窗；
5. macro 内部步骤统计；
6. 可选源码锚点字段。

通过该表示，原始 trace 不再只是不可读的扁平事件列表，而成为可以按节点、macro 和重复实例查询的结构化性能对象。后续分析可以优先检查耗时占比高、重复次数稳定、内部 wait/comm 比例异常的节点，并沿着节点保留的原始 task 实例和源码锚点回溯到框架实现。这样，Loop Tree 就从一种压缩表示进一步转化为 profiling 结果与源码调优之间的中间索引。

### 4.10 优化验证 Gate

为了避免单次 benchmark 噪声导致误判，本文采用一 patch 一试验的 gate 策略。接受条件包括：

1. trial mean throughput 相对 baseline 达到最小增益；
2. 增益超过 baseline 噪声下界；
3. p95 不超过约束；
4. error rate 不超过约束。

对应状态机为：

```text
S4_BASELINE_FREEZE
  -> S5_BOTTLENECK_ANALYZE
  -> S6_PATCH_PROPOSE
  -> S7_PATCH_APPLY_AND_CHECK
  -> S8_PATCH_BENCHMARK
  -> S9_ACCEPT_OR_REJECT
```

## 第 5 章 系统实现

### 5.1 `analyzer/hprofile` 离线分析模块

`hprofile` 是 msprof 采集与处理入口。它支持两种模式：

1. 启动 workload 并采集；
2. 仅处理已有 raw profiling 目录。

处理阶段会发现多个 `PROF_*` 目录和 `msprof_*.db`，聚合其中包含 `TASK` 表的数据库，生成统一 derived 产物和离线 web bundle。

### 5.2 信号聚合分析实现

`hprofile` 的核心实现价值在于将原始 `TASK` 表聚合成可解释信号。当前实现包括：

- 全局 `wait/comm/exec/other` breakdown；
- stream 级 breakdown 与 idle ratio；
- phase-stream breakdown；
- task type 到 semantic bucket 的分类表；
- `EVENT_WAIT -> EVENT_RECORD` 的跨 stream causality edge；
- causality 匹配率与质量元信息；
- top kernels 与 loop candidates。

这些输出共同服务于一个目标：把分散、细碎、带噪声的 profiling 事件聚合为少量高价值瓶颈线索。

### 5.3 Loop Analyzer 实现

`analyzer/hprofile/loop_analyzer` 负责 stream trace 的符号化、macro 挖掘、树结构生成和节点级增广。当前实现支持：

- `*.expr.txt`：符号序列表达；
- `*.macros.csv/json`：macro 定义；
- `*.tree.v2.json`：结构化树；
- `*.tree.readable.md`：可读树；
- `*.node_perf_core.csv`：节点级聚合指标；
- `*.macro_summary.csv`：macro 级统计。

### 5.4 报告与可视化实现

系统生成的 web bundle 是静态离线报告，适合在实验结束后归档和复盘。正式论文中 UI 不作为核心创新，但可作为系统可用性的展示材料。

## 第 6 章 实验与案例分析

### 6.1 实验目标

实验目标包括：

1. 验证系统能够解析 Ascend `msprof` profiling 产物；
2. 验证系统能够输出 wait/comm/exec 分解和 stream causality；
3. 验证 Loop Tree 能压缩重复 trace 并保留可解释结构；
4. 通过真实 patch 说明分析结果能指导优化。

本章实验并不追求覆盖所有 NPU workload，而是围绕“profiling 信号聚合是否能形成有效优化证据链”展开。实验设计包含三类证据：第一，基础产物证明 `hprofile` 能稳定处理原始 `msprof` 数据；第二，信号聚合结果证明系统能从大量细粒度 task 中提取关键 wait/comm/exec 信号；第三，Patch 006 与 rejected patches 共同证明 benchmark gate 能区分有效优化和无效扰动。

### 6.2 Workload 与环境

当前已有实验采用 vLLM-Ascend 分布式推理 workload，固定 TP=4、PP=1、设备 `0,2,4,6`，数据来自：

- `analyzer/out/20260422_163744/...`
- `analyzer/out/autotune_runs/run_20260424_skill01/...`

正式论文需要补充硬件型号、CANN 版本、vLLM/vLLM-Ascend commit、模型路径、输入输出长度、batch 参数等环境表。

论文中建议加入如下实验环境表：

| 项目 | 内容 |
| --- | --- |
| 硬件平台 | 待补充，例如 Ascend NPU 型号、机器节点 |
| CANN/驱动版本 | 待补充 |
| Python/PyTorch 版本 | 待补充 |
| vLLM 版本或 commit | 待补充 |
| vLLM-Ascend 版本或 commit | 待补充 |
| 模型 | 待补充 |
| 并行配置 | TP=4, PP=1 |
| 使用设备 | `0,2,4,6` |
| benchmark rounds | baseline/trial 均采用 3 次重复 |
| 主要指标 | throughput、p95 proxy、error rate |

### 6.3 hprofile 基础解析与信号聚合产物

`hprofile` 对原始 profiling run 的处理结果固定输出到 `hprofile_processed` 目录。核心产物包括：

| 产物 | 作用 |
| --- | --- |
| `derived/unified_profile.json` | 统一 profile 数据，承载 run、device、stream、task 等结构化对象 |
| `derived/lineage.json` | 记录指标来源与处理路径，用于追溯分析结论 |
| `derived/quality_report.json` | 记录数据覆盖率和处理质量 |
| `derived/legacy_stage/global_breakdown.csv` | 全局 wait/comm/exec/other 占比 |
| `derived/legacy_stage/stream_breakdown.csv` | stream 级别时间分解和 idle ratio |
| `derived/legacy_stage/stream_causality_edges.csv` | producer/consumer stream 等待边 |
| `derived/legacy_stage/loop_candidates.csv` | 重复 micro-loop 候选 |
| `derived/loop_analyzer/*` | Loop Tree、macro、符号序列和可读报告 |

这些产物对应本文方法的不同层次：`unified_profile` 负责统一建模，`breakdown` 和 `causality_edges` 负责瓶颈信号聚合，`loop_analyzer` 负责重复结构压缩，`lineage` 与 `quality_report` 负责可追溯性和可信边界。

正式论文中应补一张 “hprofile 输出产物关系图”，展示 raw profiling 数据如何被转换成上述 derived artifacts。

### 6.4 信号提取案例：Wait/Communication 主导的 Stream

在 `analyzer/out/20260422_163744` 对应 run 中，`hprofile` 聚合结果显示多个关键 stream 存在 wait-bound 或 communication-bound 行为。代表性的跨 stream producer/consumer 等待边包括：

```text
1165 -> 1162
1729 -> 1720
315  -> 312
705  -> 702
```

这些边说明部分 consumer stream 的执行进度受其他 producer stream 的 event record 或通信路径影响。与直接阅读完整 timeline 相比，causality edge 将大量分散的 wait/event 记录聚合为少量 stream 对，使后续分析能聚焦到高价值路径。

从方法角度看，这一步完成了从“事件级噪声”到“stream 级等待关系”的降维。它不直接给出源码答案，但为源码审计提供了明确方向：优先检查通信密集路径、同步等待路径以及这些路径附近是否存在可避免的运行时开销。

### 6.5 Loop Tree 压缩能力分析

Loop Analyzer 面向单个 stream 的重复 task 序列进行压缩。其输出包括符号序列、macro 定义、树结构和可读报告。该模块的意义在于：同一个 stream 上的原始 task 数量可能很大，但其中往往存在重复模式；如果只看 top-k kernel，容易丢失顺序结构；如果直接看完整 timeline，又难以阅读。

Loop Tree 通过 macro/tree 表示保留以下信息：

1. 重复结构的边界；
2. 每个 macro 的重复次数；
3. 节点顺序；
4. 节点实例时间窗；
5. 节点级 wait/comm/exec 统计；
6. 后续源码锚点字段。

当前版本的 Loop Analyzer 主要针对 single stream。跨 stream 等待关系由 causality edge 模块独立输出，二者尚未合并为全局执行图。因此，本科论文中应将 Loop Analyzer 的贡献表述为“单 stream 重复结构压缩与节点统计”，而不是宣称已经完成全机 pattern 聚合。

### 6.6 Baseline 与 Patch Gate

已有 autotune 记录中，`patch_001` 为环境变量优化：

```text
HCCL_OP_EXPANSION_MODE=AIV
```

该 patch 将 baseline mean throughput 从 `6.962567` 提升到 `10.952267`，提升 `57.302144%`。

在此基础上，系统继续进行瓶颈分析和 source-level patch 验证。

### 6.7 Patch 006 案例：OProj all-to-all recv buffer 复用

#### 6.7.1 Trace 证据

分析报告显示多个关键 stream 存在 wait-bound 与 communication-bound 行为，代表性 producer/consumer stream 对包括：

```text
1165 -> 1162
1729 -> 1720
315  -> 312
705  -> 702
```

Loop Tree 增广报告中，关键 stream 的 macro 级分类显示 WAIT_BOUND 区段占比较高。

#### 6.7.2 源码定位

结合 vLLM-Ascend 源码检查，发现 `vllm_ascend/ops/linear_op.py` 中：

- `OProjRowParallelOp`
- `Flashcomm2OProjRowParallelOp`

均在 `dist.all_to_all_single(...)` 前每次调用 `torch.empty(...)` 创建 `recv_buf`。这类 per-iteration device allocation 可能增加运行时开销，并放大通信侧气泡。

#### 6.7.3 优化方法

Patch 006 增加 recv buffer 缓存：

1. 为 `OProjRowParallelOp` 添加 `_a2a_recv_buf`；
2. 为 `Flashcomm2OProjRowParallelOp` 添加 `_otp_recv_buf`；
3. 当缓存不存在、容量不足、dtype 或 device 不匹配时重新分配；
4. 否则复用已有 buffer 的切片。

该修改不改变 all-to-all 的语义，只改变接收缓冲区分配策略。

#### 6.7.4 实验结果

固定 workload 下，Patch 006 的 3 次 trial 结果为：

| run | throughput |
| --- | ---: |
| trial006_r1 | `11.2165 rps` |
| trial006_r2 | `11.0852 rps` |
| trial006_r3 | `11.7518 rps` |

聚合结果：

| 指标 | baseline | trial |
| --- | ---: | ---: |
| mean throughput | `10.9523 rps` | `11.3512 rps` |
| p95 proxy | `730.8 ms` | `705.2 ms` |
| error rate | `0.0` | `0.0` |

吞吐提升：

```text
delta = +3.6422%
```

Gate 检查中，gain、noise floor、p95 constraint 和 error constraint 均通过，因此 patch 被接受。该 patch 已整理为 PR：

```text
https://github.com/vLLM-HUST/vllm-ascend-hust/pull/7
```

### 6.8 Rejected Patches 反例分析

为了避免将 benchmark 抖动误判为优化收益，本文采用 gate 策略过滤无效 patch。已有 trial 记录中包含多个 rejected patch，可作为反例说明该验证流程的必要性。

| patch | baseline mean | trial mean | delta | p95 baseline | p95 trial | decision | 说明 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| patch_002 | `10.952267` | `10.454033` | `-4.549134%` | `730.8000` | `765.9333` | reject | 吞吐下降且 p95 变差 |
| patch_003 | `10.952267` | `11.169300` | `+1.981629%` | `730.8000` | `716.6667` | reject | 有轻微提升，但未达到最小增益和噪声门槛 |
| patch_005 | `10.952267` | `10.951667` | `-0.005478%` | `730.8000` | `730.5667` | reject | 基本无收益 |

这些反例说明，仅凭单次或轻微平均值变化不足以判断优化有效。Patch gate 将吞吐增益、baseline 噪声、p95 约束和错误率约束结合起来，能够过滤负收益、弱收益和不可复现收益，使最终接受的 patch 更可信。

### 6.9 实验小结

Patch 006 说明本文系统不仅能生成可视化报告，还能完成：

```text
profiling aggregation
  -> bottleneck classification
  -> stream/macro evidence
  -> source mapping
  -> minimal code patch
  -> repeated benchmark gate
  -> upstream PR
```

这正是本文的核心闭环。

同时，rejected patches 说明该闭环并不是只保留成功案例。本文方法既能形成优化方向，也能通过固定验证协议否定不稳定或无收益的方向。这一点对工程实践很重要，因为真实性能调优中错误方向和噪声收益都很常见。

## 第 7 章 总结与展望

### 7.1 工作总结

本文围绕 Ascend NPU 分布式推理性能分析，设计并实现了一套以 `hprofile` 为核心的离线 profiling 信号分析与优化验证方法。系统覆盖 profiling 解析、统一建模、聚合降噪、等待/通信归因、Loop Tree 压缩、源码锚点和 benchmark gate。实验表明，该系统能够从复杂 tracing 数据中提取可执行优化线索，并通过真实 patch 获得可测收益。

### 7.2 不足

当前系统仍存在以下不足：

1. prefill/decode 阶段标记主要依赖现有 profiling 信息，尚未深度接入 vLLM 内部显式阶段事件；
2. 源码映射仍是证据驱动半自动方法，需要人工复核；
3. NVIDIA Nsight/CUPTI 适配尚未完成；
4. 当前真实优化案例数量有限，后续需要更多 workload 验证。

### 7.3 展望

后续工作可以从三个方向展开：

1. **跨平台扩展**：实现 NVIDIA Nsight/CUPTI adapter，将 CUDA kernel、NCCL、stream sync 和 NVTX range 映射到统一事件模型。
2. **更强源码归因**：结合 Python stack、NVTX、自定义 source notes 和 LLM 重排，提高 source anchor 的置信度与覆盖率。
3. **自动化优化闭环**：在 benchmark gate 基础上，进一步构建 patch hypothesis library 和 ablation 流程，减少调优试错成本。

从研究角度看，本工作可进一步发展为面向异构大模型推理系统的 tracing-to-source performance diagnosis 方法。其长期价值不在于某个具体工具，而在于打通 trace、语义归因、源码优化与验证实验之间的路径。

## 附录 A：当前可引用仓库证据

1. 开题报告底稿：`docs/opening_report_draft.md`
2. hprofile 说明：`analyzer/hprofile/README.md`
3. msprof raw artifacts 说明：`analyzer/MSPROF_RAW_ARTIFACTS.md`
4. Loop Tree 闭环设计：`docs/loop_tree_closure_design.md`
5. Patch 006 发现路径：`PATCH_006_DISCOVERY_PATH.md`
6. Patch 006 evidence：`analyzer/out/autotune_runs/run_20260424_skill01/reports/patch_006_evidence.md`
7. Patch 006 decision：`analyzer/out/autotune_runs/run_20260424_skill01/reports/decision_006.json`
8. Trial ledger：`analyzer/out/autotune_runs/run_20260424_skill01/trials.csv`
9. PR：`https://github.com/vLLM-HUST/vllm-ascend-hust/pull/7`

## 附录 B：后续写作 TODO

1. 补正式论文封面信息；
2. 将本文档迁移到 HUST LaTeX 模板；
3. 补系统架构图、数据流图、Loop Tree 示例图；
4. 补实验环境表；
5. 补 hprofile 输出截图；
6. 在本文档中继续维护参考文献草表，迁移到 LaTeX 时再统一生成 BibTeX；
7. 补充至少一个非 Patch 006 的分析案例，哪怕只是 rejected patch 的反例。
8. 补一张 rejected patch gate 表，说明本文方法能过滤无效优化方向。

## 附录 C：参考文献草表

说明：后续不再单独维护 `document-translation-template/Literature_Review.*`。文献综述内容和参考文献信息统一维护在本文档中，正式迁移到 LaTeX 时再生成 `.bib` 文件。

1. Williams S, Waterman A, Patterson D. Roofline: An Insightful Visual Performance Model for Multicore Architectures[J]. Communications of the ACM, 2009, 52(4): 65-76.
2. Jouppi N P, Young C, Patil N, et al. In-Datacenter Performance Analysis of a Tensor Processing Unit[EB/OL]. arXiv:1704.04760, 2017.
3. Kwon W, Li Z, Zhuang S, et al. Efficient Memory Management for Large Language Model Serving with PagedAttention[EB/OL]. arXiv:2309.06180, 2023.
4. Yu G I, Jeong J S, Kim G W, et al. Orca: A Distributed Serving System for Transformer-Based Generative Models[C]. OSDI, 2022: 521-538.
5. Agrawal A, Kedia N, Panwar A, et al. Taming Throughput-Latency Tradeoff in LLM Inference with Sarathi-Serve[C]. OSDI, 2024: 117-134.
6. Zhong Y, Liu S, Chen J, et al. DistServe: Disaggregating Prefill and Decoding for Goodput-optimized Large Language Model Serving[C]. OSDI, 2024: 193-210.
7. Noeth M, Ratn P, Mueller F, et al. ScalaTrace: Scalable Compression and Replay of Communication Traces for High-Performance Computing[J]. Journal of Parallel and Distributed Computing, 2009, 69(8): 696-710.
8. Krishnamoorthy S, Agarwal K. Scalable Communication Trace Compression[C]. CCGrid, 2010: 408-417.
9. Xu Q, Subhlok J, Hammen N. Efficient Discovery of Loop Nests in Execution Traces[C]. MASCOTS, 2010: 193-202.
10. Adhianto L, Banerjee S, Fagan M W, et al. HPCTOOLKIT: Tools for Performance Analysis of Optimized Parallel Programs[J]. Concurrency and Computation: Practice and Experience, 2010, 22(6): 685-701.
11. Zhou K, Adhianto L, Anderson J, et al. Measurement and Analysis of GPU-accelerated Applications with HPCToolkit[EB/OL]. arXiv:2109.06931, 2021.
12. Adhianto L, Anderson J, Barnett R M, et al. Refining HPCToolkit for Application Performance Analysis at Exascale[J]. The International Journal of High Performance Computing Applications, 2024, 38(6): 612-632.
