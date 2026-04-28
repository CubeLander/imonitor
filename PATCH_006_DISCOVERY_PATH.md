# Patch 006 Discovery Path (Evidence-Driven)

## 0. Context
- Goal: improve vLLM-Ascend TP workload throughput under fixed hardware/workload protocol.
- Baseline accepted stack before this patch: `patch_001` (`HCCL_OP_EXPANSION_MODE=AIV`).

## 1. Profiling Signal -> Bottleneck Category
We first analyzed the aggregated profiling outputs and loop reports.

Key observations:
- Critical streams are communication/wait dominated with high idle ratio.
- Repeated producer-consumer wait edges appear on top streams (e.g., `1165->1162`, `1729->1720`, `315->312`, `705->702`).
- Macro-level tags on critical stream sections are frequently `WAIT_BOUND`.

This narrowed optimization scope from generic tuning to communication-path overhead.

## 2. Category -> Source Path Mapping
Based on the wait-bound communication signal, we inspected the OProj communication hot path in source code:
- `vllm_ascend/ops/linear_op.py`
- `OProjRowParallelOp`
- `Flashcomm2OProjRowParallelOp`

Finding:
- In both paths, `recv_buf = torch.empty(...)` is allocated immediately before `dist.all_to_all_single(...)` during forward.

## 3. Hypothesis
If receive buffers on the all-to-all path are reused instead of allocated every iteration, then:
- per-iteration device allocation overhead can be reduced,
- communication-side bubbles can shrink,
- end-to-end throughput may improve.

## 4. Minimal Patch Design
Implemented `patch_006` as a minimal source-level change:
- Add cached recv buffer helpers (`_get_a2a_recv_buf`, `_get_otp_recv_buf`).
- Replace per-call `torch.empty(...)` in all-to-all paths with cache reuse.
- Keep tensor shape/dtype/device semantics unchanged.

## 5. Validation via State-Machine Gates
Using the autotune workflow (smoke + 3 repeats + gate checks):
- Baseline mean throughput: `10.9523 rps`
- Trial mean throughput: `11.3512 rps`
- Gain: `+3.6422%`
- p95 proxy: `730.8 ms -> 705.2 ms`
- error rate: unchanged (`0.0`)
- Gate decision: `accept`

Artifacts:
- `analyzer/out/autotune_runs/run_20260424_skill01/reports/patch_006_evidence.md`
- `analyzer/out/autotune_runs/run_20260424_skill01/reports/decision_006.json`
- `analyzer/out/autotune_runs/run_20260424_skill01/reports/patch_006_execution_record.md`

## 6. Conclusion
Patch 006 is not a random tweak; it was discovered through an evidence chain:
profiling aggregation -> bottleneck classification -> source mapping -> minimal patch -> gated validation.
