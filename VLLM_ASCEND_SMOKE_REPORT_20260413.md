# vLLM on Ascend Smoke Report (2026-04-13)

## 1. 环境与范围

- 日期：2026-04-13
- 容器：`vllm-workspace`（`quay.io/ascend/vllm-ascend:nightly-releases-v0.18.0-openeuler`）
- 工具链：CANN 8.5（`msprof` 可用）
- 模型：`/data/models/models--Qwen--Qwen3-8B/snapshots/b968826d9c46dd6066d109eabc6255188de91218`

## 2. 基线检查

- `npu-smi info`：8 张 910B3，`Health=OK`
- `torch.npu.device_count()`：`8`
- `msprof --help`：可正常输出参数说明

## 3. vLLM TP/PP Smoke

执行脚本：`scripts/run_vllm_tp_pp_smoke_in_vllm_workspace.sh`

结果目录：`develop/vllm_smoke_20260413`

| Case | 配置 | 退出码 | 结论 | 证据 |
| --- | --- | --- | --- | --- |
| tp2_pp1 | TP=2, PP=1 | 0 | PASS | `logs/tp2_pp1.log` 中有 `[workload] done` |
| tp2_pp2 | TP=2, PP=2 | 0 | PASS | `logs/tp2_pp2.log` 中有 `[workload] done` |

说明：两个 case 均完成文本生成，日志里都出现了收尾阶段的 `EngineCore died unexpectedly`，但对应进程退出码为 0，且 workload 正常产出。

## 4. msprof Smoke（vLLM workload）

执行脚本：`scripts/run_msprof_smoke_in_vllm_workspace.sh`

结果目录：`develop/msprof_smoke_runs_20260413`

| Case | 关键参数 | 退出码 | PROF 目录数 | 结论 |
| --- | --- | --- | --- | --- |
| case1_app | `<app>` 方式 + `--ascendcl --runtime-api --task-time=l1 --aicpu --ai-core --hccl` | 0 | 2 | PASS |
| case2_application | `--application=<app>` 方式 + 同上核心参数 | 0 | 2 | PASS |
| case3_advanced | 在 case1 基础上增加 `--model-execution --aic-mode=sample-based --aic-freq=50 --aic-metrics=PipeUtilization --sys-hardware-mem --sys-hardware-mem-freq=20 --l2 --ge-api=l0 --task-memory` | 0 | 2 | PASS |

日志证据（每个 case）：

- 有 `[workload] done`
- 有 `[INFO] Profiling finished.`
- 有 `[INFO] Process profiling data complete.`

## 5. 产物对照（按 `mindstudio_profiler_output`）

`case1_app` / `case2_application` 主要生成：

- `api_statistic_*.csv`
- `communication_statistic_*.csv`
- `op_statistic_*.csv`
- `op_summary_*.csv`
- `task_time_*.csv`
- `msprof_*.json`

`case3_advanced` 在上述基础上额外生成：

- `ai_core_utilization_*.csv`
- `ai_vector_core_utilization_*.csv`
- `npu_mem_*.csv`
- `npu_module_mem_*.csv`
- `hbm_*.csv`
- `llc_read_write_*.csv`
- `l2_cache_*.csv`

## 6. 文档抓取结果

抓取目录：`develop/cann850_docs_msprof`

- `manifest.json` 中 `page_count=80`
- 目标页面已落地：`markdown/devaids/Profiling/atlasprofiling_16_0011.md`

相关脚本：`scripts/crawl_cann850_docs.py`
