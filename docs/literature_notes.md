# P0 文献笔记（GPU/NPU Profiling + vLLM + Trace）

## 1) Efficient Memory Management for Large Language Model Serving with PagedAttention（2023）
1. 论文关注的问题是：LLM serving 中 KV cache 的碎片化与过度预留会显著浪费显存，导致吞吐受限。
2. 核心方法是提出 PagedAttention，把 KV cache 管理类比为虚拟内存分页，通过块级分配降低碎片并支持更灵活的请求调度。
3. 系统实现对应 vLLM，强调在不改模型结构的前提下提升服务端吞吐和内存利用效率。
4. 论文报告了相较当时主流系统在吞吐上的显著提升；不同模型和采样策略下增益幅度不同，具体百分比在复现实验时需按同口径再核对。
5. 对本课题的直接启发是：profiling 时必须把“显存分配行为”与“调度行为”联动观察，而不能只看 kernel 时间。
6. 另一个启发是可将 KV block 生命周期纳入 trace 事件模型，用于后续压缩和归因分析。

## 2) Orca: A Distributed Serving System for Transformer-Based Generative Models（2022）
1. Orca 针对生成式模型“多 iteration 才完成一次请求”的特性，指出按请求粒度调度会引入明显低效。
2. 其关键设计是 iteration-level scheduling 与 selective batching，把调度粒度从请求切到迭代，并只对适合的算子做批处理。
3. 论文在 GPT-3 175B 场景展示了相对基线系统的显著延迟/吞吐改进，说明调度策略本身是 serving 性能瓶颈的重要来源。
4. 对本课题而言，Orca 提供了“调度器行为可观测性”的分析框架：需要在 trace 中显式标出批次形成、迭代边界和请求进出队列。
5. 该工作也说明仅靠算子级 profiling 不足以解释端到端延迟，应补充调度路径与排队时间归因。
6. 论文中的部分实现细节在公开材料里描述有限，若要精确复现其调度开销分解，仍有参数待核实。

## 3) DistServe: Disaggregating Prefill and Decoding for Goodput-optimized Large Language Model Serving（2024）
1. DistServe 聚焦 prefill 与 decode 共置带来的干扰问题，指出二者在并行策略和资源偏好上存在冲突。
2. 方法上将 prefill/decode 解耦到不同 GPU 资源池，并联合优化每个阶段的并行方案和资源配比。
3. 论文强调在 TTFT 与 TPOT 双约束下，以 goodput（满足 SLO 的有效吞吐）作为优化目标，而不是单一吞吐。
4. 对本课题最关键的启发是：profiling 数据需要按阶段切分，否则聚合统计会掩盖阶段间干扰。
5. 在 trace 设计上，可为每个 token 关联阶段标签、跨阶段传输成本和 SLO 违约信息，以支撑归因。
6. 论文报告了在多种模型与约束下的显著收益，但具体数值受集群带宽和并行配置影响，迁移到本平台时需待核实。

## 4) Taming Throughput-Latency Tradeoff in LLM Inference with Sarathi-Serve（2024）
1. Sarathi-Serve 关注吞吐与时延（尤其 token 间时延）的结构性冲突，目标是在服务级约束下做更稳健的折中。
2. 论文提出了针对 prefill/decode 特性的批处理与调度协同机制，核心是减少阶段互扰并提升资源利用率。
3. 相比“只追求高 batch”的策略，该工作更强调 tail latency 和用户可感知响应的一致性。
4. 对本课题的价值在于给出明确的评估维度：不仅看平均吞吐，还要看 TTFT、TPOT、尾延迟和 SLO 达标率。
5. 在 profiling 层面，我们可把调度决策点作为一等事件写入 trace，用于后续模式挖掘。
6. 论文中不同负载分布下的稳态收益曲线对复现实验较关键，部分实验细节需结合开源实现进一步核对（待核实）。

## 5) In-Datacenter Performance Analysis of a Tensor Processing Unit（2017）
1. 该论文系统评估了 TPU 在数据中心推理负载中的性能表现，是 NPU 侧性能分析的经典起点。
2. 方法上通过真实业务负载与对比平台分析算力、访存与功耗关系，展示“架构特征-工作负载-系统指标”的闭环。
3. 文中强调了矩阵乘单元与片上存储组织对推理吞吐/时延的关键影响，这与当前 NPU profiling 的关注点一致。
4. 对本课题的启发是：NPU profiling 不应局限单算子，应结合模型结构与数据流阶段做分层分析。
5. 另一个启发是建立与 GPU 可比的统一指标口径，避免跨硬件对比时出现指标不可比。
6. 原文涉及具体硬件细节与部署背景，映射到 Ascend 场景时需要做口径换算与参数对齐（待核实）。

## 6) ScalaTrace: Scalable compression and replay of communication traces for high-performance computing（2009）
1. ScalaTrace 解决的是并行程序 trace 体量爆炸问题，目标是在尽量保持信息完整前提下实现高压缩比。
2. 论文采用面向通信结构的压缩策略，并支持 trace replay，这对验证压缩后可分析性非常关键。
3. 其贡献在于把“可扩展 trace 采集”与“可重放分析”结合，避免仅做统计聚合导致信息不可逆损失。
4. 对本课题的启发是：GPU/NPU trace 压缩不能只追求体积，还要保留对归因有用的事件关系。
5. 在实现上可借鉴其分层压缩思路：先保结构再压参数，以兼顾模式挖掘与存储成本。
6. 由于我们的 trace 事件类型与 HPC 通信 trace 存在差异，具体压缩算子需做领域适配（待核实）。

## 7) HPCTOOLKIT: tools for performance analysis of optimized parallel programs（2010）
1. HPCToolkit 的核心问题是：在高优化并行程序中，如何低开销地把性能开销准确映射回源码语义。
2. 方法上通过采样、静态结构恢复与调用上下文树（CCT）统一建模，实现函数/循环/源码行级归因。
3. 该工作证明了“调用上下文 + 源码结构”比平面 profile 更适合定位并行程序瓶颈。
4. 对本课题而言，可直接借鉴其 CCT 思路，把 GPU/NPU stream 事件与上层算子/模块做统一归因树。
5. 这也为“源码映射与归因”章节提供了方法论基础：归因对象应是上下文路径，而非孤立算子。
6. 结合近年 HPCToolkit 的 GPU 扩展工作，可进一步设计跨 CPU 调度与加速器执行的端到端归因链路。
