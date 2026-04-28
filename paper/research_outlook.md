# 研究展望：Tracing 驱动的异构推理性能归因与优化闭环

## 1. 当前工作的研究定位

当前 `hprofile` 工作不应定位为 profiling 结果展示工具，而应抽象为一条面向异构推理系统的性能分析与优化路径：

```text
raw trace
  -> unified event model
  -> wait/comm/exec 分类
  -> stream causality
  -> loop/macro 压缩表示
  -> source anchor
  -> patch proposal
  -> benchmark gate
```

该路径的核心价值是把原始 tracing 数据转化为可解释、可追溯、可验证的优化证据链。与传统 profiler 只提供时间线和统计表不同，本工作强调从 trace 到源码，再到真实优化 patch 的闭环。

## 2. 期刊化空间

如果只写成 `hprofile` 工具介绍，论文空间有限；如果进一步抽象为“面向异构大模型推理的 tracing-driven performance diagnosis and optimization pipeline”，具备工程类期刊或系统性能分析方向论文的空间。

可强调的贡献点包括：

1. **统一事件模型**：把 Ascend `msprof` 中的 task、stream、event wait、communication 等异构事件转化为统一语义对象，为跨 run 和跨平台分析提供基础。
2. **跨 stream 等待归因**：基于 `EVENT_WAIT -> EVENT_RECORD` 的时间配对推断 producer/consumer stream 因果边，解释同步等待和通信等待来源。
3. **Loop Tree 压缩表示**：将重复 stream 事件序列压缩为 macro/tree 结构，在降低 trace 阅读成本的同时保留节点级统计与时间窗。
4. **源码锚点与优化闭环**：将 wait-bound 或 comm-bound 子结构映射到框架源码位置，并通过 benchmark gate 验证优化收益。
5. **真实案例验证**：Patch 006 通过 OProj all-to-all recv buffer 复用获得 `+3.6422%` 吞吐提升，并降低 p95 proxy，说明系统能指导实际优化。

## 3. 从本科毕设到论文投稿的差距

本科毕设版本重点在“系统设计与实现”，证明系统可以端到端运行并支撑一次真实优化案例。

期刊/会议版本需要补足：

1. **方法形式化**：
   - 统一事件模型字段定义；
   - wait/comm/exec 分类规则；
   - stream causality 推断条件与置信度；
   - Loop Tree 生成、压缩率和节点统计口径。

2. **实验规模扩大**：
   - 多个 vLLM workload；
   - 不同 TP/PP 配置；
   - 不同模型规模；
   - 至少 2-3 个可解释优化案例，而不只 Patch 006。

3. **对比实验**：
   - 与原始 msprof 报告对比：人工定位成本、数据体量、可解释结论数量；
   - 与纯聚合统计对比：Loop Tree 是否能保留可定位结构；
   - 与无 gate 优化流程对比：benchmark gate 是否降低误判。

4. **跨平台验证**：
   - 至少给出 NVIDIA Nsight/CUPTI adapter 原型或字段映射；
   - 证明核心分析算法不依赖 Ascend 私有字段。

## 4. 扩展到 NVIDIA 的路线

当前实现以 Ascend `msprof` 为主，但方法层应设计为平台无关。

### 4.1 Ascend 侧输入

- `msprof_*.db`
- `TASK` 表
- stream/task/event wait/record
- HCCL 通信事件
- NPU kernel 与同步任务

### 4.2 NVIDIA 侧输入

- Nsight Systems trace
- CUPTI activity records
- CUDA API/kernel/memcpy events
- CUDA stream/event/synchronization
- NCCL communication events

### 4.3 统一语义层

不同平台适配器最终应输出统一事件类别：

| 统一类别 | Ascend 来源 | NVIDIA 来源 |
| --- | --- | --- |
| `EXEC` | NPU kernel/task | CUDA kernel |
| `COMM` | HCCL task | NCCL kernel/API |
| `WAIT` | EVENT_WAIT 等同步等待 | cudaStreamSynchronize/cudaEventSynchronize/host wait |
| `SYNC` | EVENT_RECORD、barrier 类任务 | cudaEventRecord、stream event |
| `MEMCPY` | device copy / host-device copy | cudaMemcpy / CUPTI memcpy |
| `HOST_API` | runtime/driver host 调用 | CUDA API records |
| `PHASE` | MODEL_EXECUTE 或业务阶段标记 | NVTX range / vLLM phase marker |
| `SOURCE_ANCHOR` | 算子名、框架函数、源码注释 | NVTX、Python stack、kernel launch site |

### 4.4 复用的分析算法

平台适配层之后，以下模块可以复用：

1. 全局 breakdown；
2. stream breakdown；
3. wait/comm/sync 分类；
4. producer/consumer causality edge；
5. Loop Tree / macro 模式压缩；
6. 节点级性能聚合；
7. 源码锚点与置信度；
8. patch benchmark gate。

## 5. 可能投稿方向

比较现实的路线：

1. **本科毕业设计**：系统设计与实现，重点是 Ascend/vLLM 主线和 Patch 006 案例。
2. **中文工程类期刊/会议**：面向异构推理系统的可追溯性能分析工具链，强调工程闭环和案例。
3. **系统性能分析方向论文**：Tracing-to-source attribution for LLM serving，重点转向 Loop Tree、跨 stream causality 和多平台验证。

短期目标是先把本科论文写扎实；长期如果继续推进，需要围绕“可复用方法”而不是“某个工具”来组织材料。
