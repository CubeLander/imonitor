# nsys / vLLM Profiling Notes (2026-04-07)

## 1) 我们当前环境的关键结论

- `vllm 0.8.5` 环境下，`nsys stats` 新采集结果里经常只看到 `osrt_sum`，`cuda_gpu_kern_sum` 为空。
- 升级到 `vllm 0.19.0` 后，默认路径仍可能看不到完整 GPU kernel 统计。
- 对 `vllm 0.19.0` 增加 `VLLM_ENABLE_V1_MULTIPROCESSING=0` 后，`cuda_api_sum / cuda_gpu_kern_sum / cuda_gpu_mem_*` 可稳定导出。
- 结论：问题不只是版本旧，更和 vLLM v1 默认多进程执行路径有关。

## 2) 如何解读 nsys 报表

- `cuda_api_sum` 是 CPU 侧 API 停留时间，不等于 GPU 真正执行时间。
- CUDA 异步模型下，很多时间会在同步点“收账”，例如 `cudaDeviceSynchronize`。
- `cuda_gpu_kern_sum` 才是 GPU kernel 执行时间分布。
- `cuda_gpu_mem_time_sum / size_sum` 用于判断拷贝时间和数据量占比。
- 分析瓶颈必须联合看 API、kernel、memcpy 三组表，不能只看单表。

## 3) 为什么会出现 Launch 时间大于单个 Kernel 时间

- `cudaLaunchKernel` 的总时间是 CPU 调度与提交成本累计。
- `cuda_gpu_kern_sum` 第一行只是最热点单个 kernel，不是总 kernel 时间。
- 高频小 kernel 场景下，提交开销累计可能非常大。
- 启用 CUDA Graph 后，部分行为会体现在 graph/capture 相关 API 路径，和普通 kernel 统计不一一对应。

## 4) 业内常见工具链与工作流

- 第一步：`Nsight Systems (nsys)` 做全局时序定位。
- 第二步：`nsys stats` 做结构化汇总，形成可比较的指标表。
- 第三步：`Nsight Compute (ncu)` 对热点 kernel 深挖微架构瓶颈。
- 第四步：配合 NVTX 阶段标注，把性能问题映射回业务阶段。
- 第五步：做 A/B 与回归门禁，确认优化收益与稳定性。

## 5) 从数据到优化动作的常见映射

- 现象：`cudaLaunchKernel` 占比高，kernel 短小且碎片化。
- 动作：优先尝试 CUDA Graph、kernel fusion、提升 batch、减少调度碎片。

- 现象：`H2D/D2H memcpy` 时间或次数高。
- 动作：pinned memory、异步拷贝、减少 host-device 往返、提前预取。

- 现象：NCCL 阶段占比高，通信与计算重叠差。
- 动作：调整 bucket、并行策略、拓扑亲和、重叠执行策略。

- 现象：GPU busy 不高但 CPU 等待高。
- 动作：减少同步点、流水化、下放阻塞路径、降低 Python 调度开销。

## 6) nsys 数据可视化窗口建议

- `Overview`：吞吐、GPU busy、memcpy/NCCL 占比、瓶颈类型。
- `Timeline`：按 NVTX 阶段展示 CPU/GPU/通信重叠。
- `Hotspots`：Top API、Top kernel、Top memcpy。
- `Recommendations`：基于规则引擎自动给出优化建议。

## 7) 先学会工具链的建议顺序

- 学习顺序 1：`nsys profile` 参数与采集边界控制。
- 学习顺序 2：`nsys stats` 各报表含义与交叉解读。
- 学习顺序 3：NVTX 标注策略与阶段切分。
- 学习顺序 4：`ncu` 热点 kernel 深挖。
- 学习顺序 5：A/B 评估与回归阈值设计。

## 8) 当前机器可直接复现的命令模板

```bash
CUDA_VISIBLE_DEVICES=1 VLLM_ENABLE_V1_MULTIPROCESSING=0 \
nsys profile --stats=true --trace=cuda,nvtx,osrt --sample=none --cpuctxsw=none \
  --wait=all --trace-fork-before-exec=true --force-overwrite=true \
  -o /root/imonitor/runs/nsys/vllm_gpu1_v019_inproc \
  /root/.venvs/vllm19prof/bin/python /root/imonitor/scripts/vllm_steady_profile.py \
  --model distilgpt2 --tensor-parallel-size 1 --gpu-memory-utilization 0.2 \
  --warmup-iters 1 --profile-iters 2 --max-tokens 24 \
  --capture-mode none --distributed-executor-backend uni
```

```bash
nsys stats --report cuda_api_sum /root/imonitor/runs/nsys/vllm_gpu1_v019_inproc.nsys-rep
nsys stats --report cuda_gpu_kern_sum /root/imonitor/runs/nsys/vllm_gpu1_v019_inproc.nsys-rep
nsys stats --report cuda_gpu_mem_time_sum /root/imonitor/runs/nsys/vllm_gpu1_v019_inproc.nsys-rep
```

## 9) 容器限制说明

- 当前容器内 `perf` 已安装但无采样权限，`perf stat` 会报无权限事件开启失败。
- `py-spy` 可以使用，适合作为 CPU/Python 侧补充剖析手段。

## 10) 标准工作流：Nsight Systems / nsys stats / Nsight Compute 如何协作

- 结论先行：三者不是机械重复跑同一件事。

### 10.1 角色分工

- `Nsight Systems (nsys)`：看端到端时序与重叠关系（CPU 调度、CUDA API、kernel、memcpy、NCCL）。
- `nsys stats`：对同一个 `.nsys-rep` 做结构化聚合，不需要重跑 workload。
- `Nsight Compute (ncu)`：对热点 kernel 做微架构级深挖，通常需要单独再跑定点采集。

### 10.2 推荐执行顺序

- 步骤 1：固定可复现 workload（尽量 steady-state，降低冷启动干扰）。
- 步骤 2：先跑一次 `nsys profile`，拿全局时序。
- 步骤 3：基于同一份 `.nsys-rep` 跑 `nsys stats`，看 `cuda_api_sum / cuda_gpu_kern_sum / cuda_gpu_mem_*`。
- 步骤 4：选出 Top 热点 kernel 或阶段（例如 launch-bound / memcpy-bound / NCCL-bound）。
- 步骤 5：用 `ncu` 定点采这个热点 kernel，分析 occupancy、memory bound、stall 原因。
- 步骤 6：做优化后回到 `nsys` 复测端到端收益，再用 `ncu` 验证热点指标是否改善。

### 10.3 一句话关系

- `nsys` 回答“哪里慢”。
- `nsys stats` 回答“慢多少、占比多少”。
- `ncu` 回答“为什么慢、该怎么改 kernel/访存/并行参数”。


## 11) 稀疏时间线问题：后续实现方向（已定，明天落地）

### 11.1 结论

- 稀疏负载下，时间线主要用于排障，不足以直接驱动细粒度优化决策。
- 需要同时做两件事：
- 提高负载密度（让可分析事件更连续）。
- 从宽窗口中自动提取“有效窗口”（让高价值区段被重点展示）。

### 11.2 Best Practice（执行顺序）

- 优先固定 steady-state 采样边界。
- 预热后再采样，避免冷启动和收尾噪声稀释信号。

- 提高负载密度。
- 增加并发、batch、profile 迭代数，形成连续 kernel 带。

- 自动提取 Focus Window。
- 在宽窗口中识别 GPU 活跃片段并高亮展示。
- 初始启发式阈值：GPU 活跃占比 > 30%，连续时长 > 200ms。

- 双视图并行展示。
- Full Timeline：保留全局上下文（排障视角）。
- Focus Timeline：仅展示高价值片段（优化视角）。

- 空洞原因分类。
- 将空白区分为 CPU wait / cuda sync / I/O wait / NCCL wait。
- 让“空白”转化为可执行优化动作。

### 11.3 与现有页面的对接计划

- 在 `develop/nsys_timeline_v019_inproc.html` 对应生成链路中新增：
- Focus Window 自动识别与跳转按钮。
- Full/Focus 切换。
- 按原因着色的 Idle 区段标注。

- 保留 `nsys stats` 聚合指标联动：
- `cuda_api_sum`
- `cuda_gpu_kern_sum`
- `cuda_gpu_mem_time_sum`

### 11.4 明日待办（明确范围）

- 在时间线生成脚本中实现 Focus Window 提取逻辑。
- 在页面增加 Full/Focus 视图切换与窗口导航。
- 增加空洞分类规则并在页面中可视化标注。
- 选一组高密度 workload 与当前稀疏 workload 做前后对比验证。


## 12) 负载密度提升实验（2026-04-09）

### 12.1 实验配置

- 统一条件：`vllm 0.19.0`, `VLLM_ENABLE_V1_MULTIPROCESSING=0`, `model=distilgpt2`, `gpu-memory-utilization=0.2`
- GPU：`CUDA_VISIBLE_DEVICES=1`

- Baseline:
- `warmup-iters=1`
- `profile-iters=2`
- `max-tokens=24`
- 输出：`runs/nsys/density/vllm_density_baseline.nsys-rep`

- Medium:
- `warmup-iters=2`
- `profile-iters=20`
- `max-tokens=64`
- 输出：`runs/nsys/density/vllm_density_medium.nsys-rep`

- Dense:
- `warmup-iters=2`
- `profile-iters=80`
- `max-tokens=128`
- 输出：`runs/nsys/density/vllm_density_dense.nsys-rep`

### 12.2 密度统计结果

- 指标定义：
- `span_ms`：GPU trace 的总时间跨度。
- `gpu_active_ms`：GPU trace 事件时间并集（至少有一个 GPU 事件活跃）。
- `gpu_active_ratio = gpu_active_ms / span_ms`。
- `gpu_events_per_ms = gpu_events / span_ms`。

- Baseline:
- `gpu_events=9671`, `api_events=25911`
- `span_ms=10281.300`
- `gpu_active_ms=106.401`
- `gpu_active_ratio=0.0103`
- `gpu_events_per_ms=0.941`

- Medium:
- `gpu_events=43337`, `api_events=82555`
- `span_ms=11501.449`
- `gpu_active_ms=264.952`
- `gpu_active_ratio=0.0230`
- `gpu_events_per_ms=3.768`

- Dense:
- `gpu_events=271377`, `api_events=465931`
- `span_ms=25540.372`
- `gpu_active_ms=1391.001`
- `gpu_active_ratio=0.0545`
- `gpu_events_per_ms=10.625`

### 12.3 结论与建议

- 相比 Baseline，Dense 的 `gpu_active_ratio` 提升约 `5.3x`，`gpu_events_per_ms` 提升约 `11.3x`。
- 结论：提高 `profile-iters` 与 `max-tokens` 能显著提升时间线密度，明显改善可分析性。
- 建议默认使用 Medium 或 Dense 作为“优化分析负载”：
- 日常快速分析：Medium。
- 深度分析与可视化：Dense。

### 12.4 可视化页面产物

- Medium 页面：`develop/nsys_timeline_density_medium.html`
- Dense 页面：`develop/nsys_timeline_density_dense.html`

