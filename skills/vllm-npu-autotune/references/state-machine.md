# Autotune State Machine

## Notes
- This state machine is an agent protocol, not a mandatory standalone runtime.
- After each state exit, update `state.json` with the transition and artifact pointers.
- When blocked by environment dependency failures, switch to `mock` mode only if `workflow.allow_mock_when_blocked=true`.

## State List
- `S0_DEFINE_TARGET`
- `S1_BOOTSTRAP_SOURCE`
- `S2_SMOKE_VALIDATE_EFFECTIVE`
- `S3_WORKLOAD_SATURATION`
- `S4_BASELINE_FREEZE`
- `S5_BOTTLENECK_ANALYZE`
- `S6_PATCH_PROPOSE`
- `S7_PATCH_APPLY_AND_CHECK`
- `S8_PATCH_BENCHMARK`
- `S9_ACCEPT_OR_REJECT`
- `S10_PRUNE_ABLATION`
- `S11_FINALIZE`

## Transition Table

| state | entry conditions | required artifacts | success condition | on success | on fail |
| --- | --- | --- | --- | --- | --- |
| `S0_DEFINE_TARGET` | run initialized | `run_spec.yaml` | objective, constraints, hardware frozen | `S1_BOOTSTRAP_SOURCE` | stop |
| `S1_BOOTSTRAP_SOURCE` | source paths known | `artifacts/env_manifest.json` | preflight pass, editable installs complete, repo SHAs recorded | `S2_SMOKE_VALIDATE_EFFECTIVE` | stay in `S1` |
| `S2_SMOKE_VALIDATE_EFFECTIVE` | smoke command and profiler smoke command available | smoke logs, smoke json, profiler smoke run logs | workload smoke passes and profiler dev-mode smoke passes | `S3_WORKLOAD_SATURATION` | back to `S1` |
| `S3_WORKLOAD_SATURATION` | benchmark command available | `profiles/saturation_profile.json` | throughput reaches plateau without instability | `S4_BASELINE_FREEZE` | stay in `S3` |
| `S4_BASELINE_FREEZE` | saturated workload fixed | `reports/baseline_metrics.json` | repeated baseline runs complete | `S5_BOTTLENECK_ANALYZE` | stay in `S4` |
| `S5_BOTTLENECK_ANALYZE` | baseline profiling available | bottleneck notes, hint shortlist | ranked hypotheses exist and are mapped to hint IDs with stream-level evidence anchors | `S6_PATCH_PROPOSE` | stay in `S5` |
| `S6_PATCH_PROPOSE` | hypothesis selected | `patches/patch_XXX.diff`, patch rationale, `reports/patch_XXX_evidence.md` | one patch prepared with rationale, linked hint ID, and traceable evidence chain | `S7_PATCH_APPLY_AND_CHECK` | back to `S5` |
| `S7_PATCH_APPLY_AND_CHECK` | patch and evidence file exist | apply and smoke logs | patch applies and correctness smoke passes; evidence contract remains valid | `S8_PATCH_BENCHMARK` | revert patch and back to `S6` |
| `S8_PATCH_BENCHMARK` | patched build available | `reports/trial_metrics_XXX.json` | repeated trial runs complete | `S9_ACCEPT_OR_REJECT` | revert patch and back to `S6` |
| `S9_ACCEPT_OR_REJECT` | baseline and trial metrics present | `reports/decision_XXX.json`, csv rows | decision emitted by metrics gate | accept: `S5`; reject: `S6` | stay in `S9` |
| `S10_PRUNE_ABLATION` | accepted patch count reaches checkpoint | ablation report | stale patches removed or confirmed | `S5_BOTTLENECK_ANALYZE` | stay in `S10` |
| `S11_FINALIZE` | termination criterion met | final report | ranked patch list and cumulative gain exported | stop | stop |

## Required Check in `S1_BOOTSTRAP_SOURCE`
- Run `scripts/preflight_check.py`.
- Verify `import torch` and `import vllm` in the configured profiler runtime:
  - `local`: check host python imports.
  - `docker_exec`: check imports with `docker exec <container>`.
- Verify model path exists.
- Verify benchmark and profiler smoke command entries are callable or explain fallback plan.

## Execution Rules
- Keep one-patch-per-trial discipline.
- Keep workload and random seed fixed within a baseline/trial comparison.
- Treat accepted patch stack as current baseline branch.
- Trigger `S10_PRUNE_ABLATION` every `K` accepted patches from `run_spec.yaml`.
- Persist state transitions to `state.json` after each state exits.
- In `S5`, generate `reports/hint_shortlist.md` using the best-practice hints library.
- In `S6`, bind each patch to one `hint_id` and record expected effect and risk.
- In `S6`, block transition if `reports/patch_XXX_evidence.md` is missing.
- In `S7` and `S8`, block execution if evidence does not include run ID, stream IDs, and line-level references.

## Evidence File Contract (`reports/patch_XXX_evidence.md`)
- `Patch Candidate`: patch ID, hint ID, change scope.
- `Evidence Sources`: at least one global source and one stream-level source.
- `Trace Anchors`: absolute or repo-relative file paths with line references.
- `Before Metrics`: concrete values (for example wait%, p95 wait, comm ratio).
- `Hypothesis`: why this patch should help this bottleneck.
- `Target Effect`: which metric should move and acceptable regression bounds.

## Suggested `state.json` Fields
- `run_id`
- `current_state`
- `mode` (`real` or `mock`)
- `accepted_patch_count`
- `trial_index`
- `baseline_ref`
- `latest_trial_ref`
- `history` (append-only transition records)

## Termination Criteria
- No acceptable patch found for `N` consecutive attempts.
- Cumulative gain reaches target objective.
- Time budget exhausted.
- User stop signal.
