# Ascend Smoke Report

- Generated at: 2026-04-14 17:01:34
- Ascend dir: `/home/user8/workspace/imonitor/msprof-docs-processed/ascend`

## vLLM 8-NPU Smoke

| run_id | status | rc | tp | pp | total_seconds | output_preview | error_preview |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20260414_163701 | PASS | 0 | 2 | 1 | 100.3302 |  The Microsoft Profiler (msprof) is a tool used to analyze and optimize the perf |  |
| 20260414_162817 | FAIL | 1 | 8 | 1 | 116.2573 |  | Engine core initialization failed. See root cause above. Failed core proc(s): {'EngineCore_DP0': 1} |
| 20260414_162400 | FAIL | None |  |  |  |  |  |

## msprof + vLLM 8-NPU Smoke

| run_id | status | rc | prof_dirs | key_files | profiling_finished |
| --- | --- | --- | --- | --- | --- |
| 20260414_163910 | PASS | 0 | 2 | 18 | True |
| 20260414_163135 | FAIL | None | 0 | 0 | False |

## Paths

- vLLM outputs: `/home/user8/workspace/imonitor/msprof-docs-processed/ascend/out/vllm_smoke`
- msprof outputs: `/home/user8/workspace/imonitor/msprof-docs-processed/ascend/out/msprof_smoke`

