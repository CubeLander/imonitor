# 采集AI任务运行性能数据（项目精简版）

## 1. 文档目的

本页只保留和当前项目相关的高价值信息：

- 用 `msprof` 采集 AI 任务运行性能数据。
- 采集完成后自动解析并落盘。
- 重点面向 vLLM on Ascend 工作负载。

## 2. 命令形式

推荐方式一（稳定，参数解析更直观）：

```bash
msprof [options] <app>
```

方式二（可用，但对引号和特殊字符更敏感）：

```bash
msprof [options] --application=<app>
```

## 3. 本项目推荐命令模板

基础采集模板（优先用于 smoke）：

```bash
msprof \
  --output=<output_dir> \
  --ascendcl=on \
  --runtime-api=on \
  --task-time=l1 \
  --aicpu=on \
  --ai-core=on \
  --hccl=on \
  <app>
```

增强采集模板（用于深度分析）：

```bash
msprof \
  --output=<output_dir> \
  --ascendcl=on \
  --runtime-api=on \
  --task-time=l1 \
  --aicpu=on \
  --ai-core=on \
  --hccl=on \
  --model-execution=on \
  --aic-mode=sample-based \
  --aic-freq=50 \
  --aic-metrics=PipeUtilization \
  --sys-hardware-mem=on \
  --sys-hardware-mem-freq=20 \
  --l2=on \
  --ge-api=l0 \
  --task-memory=on \
  <app>
```

## 4. 关键参数速查（仅保留高价值）

| 参数 | 建议值 | 作用 | 常见产物 |
| --- | --- | --- | --- |
| `--output` | 明确指定目录 | 统一管理本次采集数据 | `PROF_*` |
| `--ascendcl` | `on` | 采集 ACL 接口数据 | `api_statistic_*.csv` |
| `--runtime-api` | `on` | 采集 Runtime API 耗时 | `api_statistic_*.csv` |
| `--task-time` | `l1` | 采集任务/算子耗时与基础信息 | `task_time_*.csv`, `op_summary_*.csv`, `op_statistic_*.csv` |
| `--aicpu` | `on` | 采集 AICPU 算子信息 | `aicpu_*.csv`（按场景） |
| `--ai-core` | `on` | 开启 AI Core 维度采集 | `op_summary_*.csv` |
| `--hccl` | `on`（多卡） | 采集通信相关数据 | `communication_statistic_*.csv` |
| `--aic-mode` | `sample-based` | AI Core 按采样方式采集 | AI Core 利用率类 CSV |
| `--aic-freq` | `50` | 采样频率（Hz） | 影响采样粒度与开销 |
| `--aic-metrics` | `PipeUtilization` | 指定 AI Core 指标组 | 利用率/瓶颈相关字段 |
| `--sys-hardware-mem` | `on` | 采集片上内存相关数据 | `npu_mem_*.csv`, `npu_module_mem_*.csv`, `hbm_*.csv`, `llc_read_write_*.csv` |
| `--sys-hardware-mem-freq` | `20` | 内存采样频率（Hz） | 影响粒度与开销 |
| `--l2` | `on` | 采集 L2 Cache 命中率 | `l2_cache_*.csv` |
| `--ge-api` | `l0` | 采集动态 shape host 调度阶段耗时 | `api_statistic_*.csv` |
| `--task-memory` | `on` | 采集算子级内存占用 | `memory_record_*.csv`, `operator_memory_*.csv`, `static_op_mem_*.csv`（按场景） |

## 5. 建议执行流程

1. 准备一个可快速退出的 workload 脚本（例如单次 prompt 推理后退出）。
2. 使用“基础采集模板”先做一次可用性验证。
3. 可用性通过后，再使用“增强采集模板”做深度分析。
4. 每次采集后检查：
   - 命令退出码是否为 `0`
   - 输出目录下是否生成 `PROF_*`
   - `mindstudio_profiler_output` 下是否有关键 CSV/JSON 文件

## 6. 结果判定（面向本项目）

最小通过标准：

- workload 正常执行并结束。
- `msprof` 输出包含 `Profiling finished`。
- 输出目录存在 `PROF_*` 且包含 `mindstudio_profiler_output`。

深度分析标准：

- 在基础产物外，还看到 `l2_cache_*`、`npu_module_mem_*`、`ai_core_utilization_*` 等增强数据文件。

## 7. 高价值注意事项

- 优先使用命令方式一（`<app>`），可减少引号和转义问题。
- `--task-time=l1` 是通用分析起点，覆盖面和可读性较好。
- 多卡场景建议开启 `--hccl`，单卡场景通信数据价值较低。
- 使用采样类参数时，频率越高开销越大；先用保守频率再逐步提高。
- `--output` 建议总是显式指定，避免结果散落和权限问题。
