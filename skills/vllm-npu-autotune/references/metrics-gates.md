# Metrics and Acceptance Gates

## Inputs
- Baseline repeated runs (`throughput_tok_s` array required)
- Trial repeated runs (`throughput_tok_s` array required)
- Constraint arrays as available (`p95_latency_ms`, `error_rate`)
- Gate thresholds from `run_spec.yaml`

## Default Acceptance Policy
1. Throughput improvement percent must be at least `min_gain_pct`.
2. Improvement must exceed baseline noise floor:
- `delta_tok_s > z * baseline_std_tok_s`
- `z` defaults to `1.5` unless overridden.
3. Constraints must hold:
- `trial_p95_latency_ms <= baseline_p95_latency_ms * max_p95_multiplier`
- `trial_error_rate <= max_error_rate`

## One-Patch Attribution Rule
- Accept or reject a single patch only.
- Do not mix multiple source edits inside one trial.
- Update current baseline only after accept.

## Periodic Ablation Rule
- Every `ablation_interval_accepts` accepted patches, run leave-one-out checks.
- Remove accepted patches with no measurable marginal contribution.
- Rewrite `accepted_patches.csv` preserving effective order.

## Suggested Report Fields
- `patch_id`
- `state_before`, `state_after`
- `baseline_mean_tok_s`, `trial_mean_tok_s`, `delta_pct`
- `baseline_cv`, `trial_cv`
- `p95_baseline_ms`, `p95_trial_ms`
- `decision`, `decision_reason`
