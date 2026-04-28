---
name: vllm-npu-autotune
description: "Run reproducible vLLM and vLLM-Ascend throughput tuning as a deterministic state machine: bootstrap source repos, preflight runtime dependencies, saturate realistic workloads, analyze profiling bottlenecks, apply one patch at a time, and keep only statistically valid improvements with auditable artifacts."
---

# vLLM NPU Autotune

## Goal
Build a repeatable optimization loop that turns profiling observations into accepted patches with measurable throughput gains.

## Evidence-Driven Constraint
- No evidence, no patch. Every patch must be justified by concrete profiler evidence.
- Every `S6_PATCH_PROPOSE` must include `reports/patch_XXX_evidence.md`.
- Each evidence file must include:
  - exact run ID and profile path,
  - exact stream IDs and file line references,
  - bottleneck metric values before patch,
  - target effect and acceptance metrics.
- `S7` and `S8` are blocked if evidence is missing or not traceable to profile artifacts.

## Execution Model
- The state machine is an execution protocol for the coding agent, not a separate mandatory executor.
- The agent advances one state at a time and persists evidence in run artifacts.
- `state.json` is the source of truth for resume and audit.

## Required Inputs
- Fixed hardware scope: device count, topology, TP/DP/PP plan, memory limits.
- Target objective: primary metric and hard constraints.
- Source control scope: writable repositories and target branches.
- Workload source: real or synthetic dataset that reflects production request distribution.

## Output Contract
- `run_spec.yaml`: frozen experiment scope and thresholds.
- `state.json`: current state and resume point.
- `artifacts/env_manifest.json`: dependency and path preflight report.
- `trials.csv`: one row per evaluated patch.
- `accepted_patches.csv`: accepted patch stack with cumulative gain.
- `reports/`: baseline and trial profiling reports.
- `patches/`: patch artifacts in application order.

## Workflow
1. Initialize workspace with `scripts/bootstrap_run.py`.
2. Fill `run_spec.yaml` with hardware, model, workload, and acceptance gates.
3. Run preflight with `scripts/preflight_check.py` before smoke or benchmark.
4. Run profiler dev-mode smoke (`analyzer/scripts/run_hprofile_smoke.sh`) and confirm processed report output exists.
5. Execute the state machine in [references/state-machine.md](references/state-machine.md).
6. Design workload saturation and cache-policy matrix with [references/workload-design.md](references/workload-design.md).
7. Build patch hypotheses from [references/best-practice-hints.md](references/best-practice-hints.md), including source-level options (copy reduction, dispatch-path simplification, kernel/operator restructuring).
8. For each candidate patch, produce `reports/patch_XXX_evidence.md` before applying patch.
9. Evaluate each patch with `scripts/evaluate_patch.py` and policy in [references/metrics-gates.md](references/metrics-gates.md).

## Execution Modes
1. `real`
- Use real smoke, benchmark, and profiling commands.
- Required for accepting final optimization conclusions.

2. `mock`
- Use representative metrics json to validate state transitions and acceptance gates.
- Allowed only for plumbing/debug when runtime dependencies are blocked.
- Controlled by `workflow.allow_mock_when_blocked` in `run_spec.yaml`.

## State Machine (Short Form)
1. `S0_DEFINE_TARGET`
2. `S1_BOOTSTRAP_SOURCE`
3. `S2_SMOKE_VALIDATE_EFFECTIVE`
4. `S3_WORKLOAD_SATURATION`
5. `S4_BASELINE_FREEZE`
6. `S5_BOTTLENECK_ANALYZE`
7. `S6_PATCH_PROPOSE`
8. `S7_PATCH_APPLY_AND_CHECK`
9. `S8_PATCH_BENCHMARK`
10. `S9_ACCEPT_OR_REJECT`
11. `S10_PRUNE_ABLATION`
12. `S11_FINALIZE`

Read the full transition table before running: [references/state-machine.md](references/state-machine.md).

## Workload Rules
- Do not benchmark with a single repeated prompt.
- Use mature datasets such as ShareGPT or BurstGPT-style traces, or calibrated synthetic distributions.
- Evaluate two cache regimes: `cold` and `realistic`.
- Keep dataset order deterministic per run seed.
- Keep request distribution fixed during patch comparison.

See [references/workload-design.md](references/workload-design.md).

## Patch Policy
- Change one variable per patch.
- Re-benchmark with the same saturated workload and seed.
- Compare trial against current baseline, not initial baseline.
- Accept only when statistical and constraint gates pass.
- Update baseline after each accepted patch.
- Run periodic ablation to remove stale accepted patches.

Gate details are in [references/metrics-gates.md](references/metrics-gates.md).

## Minimal Command Skeleton
```bash
# 1) Initialize a run workspace
python3 skills/vllm-npu-autotune/scripts/bootstrap_run.py \
  --workspace /abs/path/to/autotune_runs \
  --run-id run_001

# 2) Preflight (paths + imports + command readiness)
python3 skills/vllm-npu-autotune/scripts/preflight_check.py \
  --run-spec /abs/path/to/autotune_runs/run_001/run_spec.yaml \
  --repo-root /home/user8/workspace/imonitor \
  --out /abs/path/to/autotune_runs/run_001/artifacts/env_manifest.json

# 3) Profiler dev-mode smoke (docker_exec path)
analyzer/scripts/run_hprofile_smoke.sh

# 4) Smoke validation (real mode)
PYTHONPATH=/home/user8/workspace/imonitor/vllm:${PYTHONPATH} \
python3 analyzer/workload/vllm_distributed_smoke.py \
  --model /abs/path/to/model \
  --tp 4 --pp 1 \
  --rounds 1 --batch-size 1 --max-tokens 8 \
  --dispatch-mode dense \
  --output-json /abs/path/to/autotune_runs/run_001/reports/smoke.json

# 5) Baseline and trial evaluation
python3 skills/vllm-npu-autotune/scripts/evaluate_patch.py \
  --baseline /abs/path/to/baseline_metrics.json \
  --trial /abs/path/to/trial_metrics.json \
  --run-spec /abs/path/to/autotune_runs/run_001/run_spec.yaml \
  --out /abs/path/to/autotune_runs/run_001/reports/decision_001.json
```

## Repositories and Bench Tools
- Prefer `vllm bench serve` for serving throughput when CLI is available.
- If CLI is unavailable, complete editable install first, then re-run preflight.
- For profiling, prefer `target.runtime=docker_exec` with a validated container in `profiler_runtime.container`.
- For multi-turn cache behavior, use `vllm/benchmarks/multi_turn/benchmark_serving_multi_turn.py`.
- Keep benchmark command, dataset file, and seed in artifacts for replay.

## Resource Files
- State machine details: [references/state-machine.md](references/state-machine.md)
- Workload and prefix-cache design: [references/workload-design.md](references/workload-design.md)
- Metrics gates and acceptance logic: [references/metrics-gates.md](references/metrics-gates.md)
- Best-practice hint library: [references/best-practice-hints.md](references/best-practice-hints.md)
- Templates: `assets/templates/*`
- Automation helpers: `scripts/bootstrap_run.py`, `scripts/preflight_check.py`, `scripts/evaluate_patch.py`
