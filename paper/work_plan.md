# 论文工作计划与后续深化路线

## 1. 本科毕业论文需要补完的工作

本科毕业论文的目标是把当前 `hprofile` 方法讲清楚，并用已有 vLLM-Ascend 实验说明它能从原始 profiling 信号中提取瓶颈线索，形成可验证的优化方向。

### 1.1 必须补充的论文内容

1. **方法总图**
   - 图名建议：`hprofile 离线 Profiling 信号分析流程`
   - 内容：
     ```text
     msprof raw
       -> event normalization
       -> wait/comm/exec classification
       -> stream causality
       -> loop analyzer
       -> source evidence
       -> patch gate
     ```
   - 作用：让评审一眼看出本文不是做监控面板，而是在做 profiling 信号聚合分析。

2. **实验环境表**
   - Ascend/NPU 型号；
   - CANN/driver 版本；
   - vLLM 与 vLLM-Ascend commit；
   - 模型名称与路径；
   - TP/PP；
   - 使用设备；
   - 输入输出长度、batch、rounds；
   - benchmark 重复次数。

3. **hprofile 基础输出实验**
   - global breakdown；
   - stream breakdown；
   - top-k causality edges；
   - loop candidates；
   - quality report 或 matching rate。

4. **瓶颈定位正例**
   - 使用 Patch 006：
     ```text
     wait/comm-bound stream
       -> all-to-all path
       -> recv_buf per-iteration allocation
       -> buffer reuse patch
       -> +3.6422% throughput
     ```

5. **Rejected patch 反例**
   - 使用已有 trial 记录说明 benchmark gate 能过滤噪声和错误方向。
   - 候选：
     - patch_002：负收益，p95 变差；
     - patch_003：`+1.9816%`，但未过 gain/noise gate；
     - patch_005：几乎无收益。

6. **Loop Tree 示例**
   - 放一个 readable tree 或 macro 表片段；
   - 说明 Loop Tree 如何把重复 stream event 压缩为结构；
   - 明确当前 Loop Analyzer 主要针对 single stream。

7. **限制说明**
   - 当前 Loop Analyzer 是 single-stream pattern；
   - cross-stream causality 已有，但尚未与 Loop Tree 合并成全局执行图；
   - cross-process / cross-rank / whole-machine pattern 聚合属于后续工作。

### 1.2 本科论文建议实验组织

本科论文实验章节建议分为四组：

1. **解析与聚合能力实验**
   - 输入：已有 `msprof` run；
   - 输出：derived artifacts；
   - 证明：系统能稳定生成统一 profile、lineage、quality 和 breakdown。

2. **信号提取能力实验**
   - 输入：vLLM-Ascend profiling；
   - 输出：wait/comm/exec 占比、top stream、causality edge；
   - 证明：系统能从噪声中提取少数关键瓶颈信号。

3. **Loop Tree 压缩实验**
   - 输入：关键 stream trace；
   - 输出：macro/tree/readable report；
   - 证明：系统能把重复事件序列压缩成可解释结构。

4. **优化验证实验**
   - 正例：Patch 006；
   - 反例：patch_002/003/005；
   - 证明：系统能支持有效优化，也能通过 gate 过滤无效修改。

## 2. 后续深化到期刊/论文需要做的工作

如果后续希望扩展成工程期刊或系统性能分析方向论文，需要从“单案例工具链”升级成“可复用方法”。

### 2.1 多 workload 验证

至少覆盖三类 workload：

1. vLLM 分布式推理 TP workload；
2. 通信密集型 NPU workload；
3. 计算密集型或 memory-bound workload。

目标是证明 `hprofile` 不只适用于一个 vLLM case。

### 2.2 多瓶颈类型优化案例

至少形成 2-3 个完整闭环：

1. 通信等待瓶颈：类似 Patch 006；
2. host/runtime 调度或 allocation overhead；
3. HCCL/env/config 类瓶颈；
4. kernel/算子热点或 shape/graph 稳定性瓶颈。

每个案例都应包含：

```text
signal
  -> hypothesis
  -> patch/config
  -> repeated benchmark
  -> accept/reject
```

### 2.3 Cross-Stream Loop Dependency Graph

当前 Loop Analyzer 主要针对 single stream。下一阶段最有研究价值的方向是将 single-stream loop 与 cross-stream causality 结合，构建跨 stream 的重复依赖图：

1. stream 内 macro；
2. stream 间 wait edge；
3. macro 到 macro 的依赖；
4. producer macro / consumer macro；
5. “某个重复结构总是在等另一个重复结构”的全局 pattern。

该方向可以回答核心问题：

```text
什么地方在等另一个地方？
```

### 2.4 Cross-Process / Cross-Rank 聚合

vLLM TP 多进程场景适合进一步扩展：

1. 每个 rank 一个 `msprof` db；
2. 对齐多 rank timeline；
3. 聚合相同 stream pattern；
4. 识别 rank imbalance；
5. 定位某 rank 是否作为 producer 导致其他 rank wait。

这会把工作从“单 stream 分析”提升为“分布式推理归因框架”。

### 2.5 全机 Pattern 聚合

进一步可以做 whole-machine pattern：

1. device-level pattern；
2. rank-level pattern；
3. stream group pattern；
4. collective communication pattern；
5. repeated global iteration pattern。

目标是回答：

```text
整个机器/多卡集群在等什么？
```

### 2.6 源码归因增强

当前源码定位偏证据驱动和人工复核。深化版本应加入：

1. op/kernel name 到源码候选；
2. vLLM/vLLM-Ascend call path；
3. source notes；
4. confidence score；
5. evidence text。

每个瓶颈节点应具备：

```text
source_anchor + confidence + evidence_kind
```

### 2.7 NVIDIA 适配原型

为了证明方法可迁移，需要实现最小 NVIDIA adapter：

1. Nsight Systems SQLite/export；
2. CUDA stream/kernel/memcpy；
3. NCCL events；
4. NVTX phase。

只要能映射到同一 unified schema，就能支撑跨平台论点。

### 2.8 量化评价指标

期刊版本需要评价方法本身，而不只是报告 patch 收益：

1. trace 压缩率；
2. causality 匹配率；
3. top-k 瓶颈稳定性；
4. 分析耗时；
5. 人工定位步骤减少；
6. patch gate 过滤率；
7. 优化收益分布。

## 3. 推荐推进顺序

短期本科论文：

```text
hprofile 离线 profiling 信号分析
  + single-stream Loop Tree
  + cross-stream causality
  + Patch 006 正例
  + rejected patch 反例
```

长期研究深化：

```text
Cross-stream / cross-rank pattern graph
  -> whole-machine bottleneck attribution
  -> cross-platform adapter
  -> multi-workload evaluation
```

