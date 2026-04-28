# GPU/NPU Profiling + vLLM 文献阅读 Backlog

## GPU/NPU Profiling

| 题目 | 年份 | 来源链接 | 为什么与本课题相关 | 优先级 |
|---|---:|---|---|---|
| In-Datacenter Performance Analysis of a Tensor Processing Unit | 2017 | https://arxiv.org/abs/1704.04760 | 早期大规模 NPU（TPU）性能分析基线，包含算力/带宽/延迟协同分析框架，可借鉴到 Ascend/NPU 侧 profiling 指标体系。 | P0 |
| Roofline: An Insightful Visual Performance Model for Multicore Architectures | 2009 | https://doi.org/10.1145/1498765.1498785 | Roofline 仍是 GPU/NPU 算力-带宽瓶颈定位的核心分析框架，可直接映射到算子级性能上界评估。 | P1 |
| Hierarchical Roofline Performance Analysis for Deep Learning Applications | 2020 | https://arxiv.org/abs/2009.05257 | 给出面向深度学习 workload 的分层 Roofline 采样与分析方法，对 GPU kernel 级 profiling 路线非常直接。 | P1 |
| Time-Based Roofline for Deep Learning Performance Analysis | 2020 | https://arxiv.org/abs/2009.04598 | 将运行时信息显式纳入 Roofline，适合解释推理阶段时延构成（prefill/decode）与吞吐折中。 | P1 |
| Measurement and Analysis of GPU-accelerated Applications with HPCToolkit | 2021 | https://arxiv.org/abs/2109.06931 | 提供 CPU/GPU 跨端调用路径和归因分析能力，与“trace 到源码映射”子任务高度契合。 | P1 |

## LLM Serving (vLLM)

| 题目 | 年份 | 来源链接 | 为什么与本课题相关 | 优先级 |
|---|---:|---|---|---|
| Efficient Memory Management for Large Language Model Serving with PagedAttention | 2023 | https://arxiv.org/abs/2309.06180 | vLLM 核心论文，定义了 PagedAttention 与 KV cache 内存管理问题，是本课题“vLLM 性能剖析”主线起点。 | P0 |
| Orca: A Distributed Serving System for Transformer-Based Generative Models | 2022 | https://www.usenix.org/conference/osdi22/presentation/yu | 迭代级调度与 selective batching 的代表工作，可作为对比 vLLM 调度策略的历史基线。 | P0 |
| Taming Throughput-Latency Tradeoff in LLM Inference with Sarathi-Serve | 2024 | https://www.usenix.org/conference/osdi24/presentation/agrawal | 聚焦吞吐与 token 间时延（TBT）折中，直接对应我们实验目标中的多目标性能分析。 | P0 |
| DistServe: Disaggregating Prefill and Decoding for Goodput-optimized Large Language Model Serving | 2024 | https://www.usenix.org/conference/osdi24/presentation/zhong-yinmin | prefill/decode 解耦的代表方案，为“分布式推理阶段拆分 + tracing 归因”提供结构化分析对象。 | P0 |
| S-LoRA: Serving Thousands of Concurrent LoRA Adapters | 2024 | https://arxiv.org/abs/2311.03285 | 多租户/多适配器场景下的 serving 与内存管理机制，扩展了 vLLM 在真实服务中的复杂负载研究范围。 | P1 |
| vAttention: Dynamic Memory Management for Serving LLMs without PagedAttention | 2025 | https://arxiv.org/abs/2405.04437 | 对 PagedAttention 替代路径进行系统化比较，有助于界定本文方案的创新边界与可替代实现。 | P1 |

## Trace Compression/Attribution

| 题目 | 年份 | 来源链接 | 为什么与本课题相关 | 优先级 |
|---|---:|---|---|---|
| ScalaTrace: Scalable compression and replay of communication traces for high-performance computing | 2009 | https://doi.org/10.1016/j.jpdc.2008.09.001 | 面向大规模并行 trace 的压缩与重放，提供“低开销保真压缩”思路，可迁移到 GPU/NPU trace 管线。 | P0 |
| Scalable Communication Trace Compression | 2010 | https://doi.org/10.1109/CCGRID.2010.111 | 聚焦通信 trace 的可扩展无损压缩，可用于我们后续 trace 存储成本与分析时延优化。 | P1 |
| HPCTOOLKIT: tools for performance analysis of optimized parallel programs | 2010 | https://doi.org/10.1002/cpe.1553 | 经典源码级归因工具链，强调调用上下文树（CCT）归因，对“源码映射与归因”章节最直接。 | P0 |
| Refining HPCToolkit for application performance analysis at exascale | 2024 | https://doi.org/10.1177/10943420241277839 | 新版本 HPCToolkit 对 CPU/GPU 统一 CCT 与大规模分析的改造，可借鉴到异构推理场景归因设计。 | P1 |
