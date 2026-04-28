# vLLM NPU Autotune Best-Practice Hints

## Purpose
Provide structured optimization hints for agent-driven tuning, including source-level interventions beyond environment variable toggles.

## Usage
- Use this document in `S5_BOTTLENECK_ANALYZE` to shortlist candidate interventions.
- In `S6_PATCH_PROPOSE`, each patch should reference a specific hint ID.
- Keep one-patch-per-trial discipline for attribution.

## Hint Taxonomy

### H1: Measurement Hygiene First
- Split metrics into cold-start and warm-serving.
- Do not treat repeated process startup as serving throughput.
- Keep workload shape, seed, dataset order, and cache policy fixed across baseline/trial.
- Signals to check:
  - `init_seconds` dominates `generate_seconds`
  - throughput gains disappear when switching from cold to warm mode

### H2: Remove Harness-Induced Overhead
- Keep engine process long-lived during benchmark loops.
- Avoid per-trial model reload for warm-serving comparisons.
- Separate "startup optimization" experiments from "steady-state throughput" experiments.
- Signals to check:
  - high variance from startup/compile noise
  - large wall time spent before first token

### H3: Increase Effective Request Density
- Use realistic dense request streams and multi-turn datasets.
- Avoid sparse dispatch patterns with long host gaps.
- Test both realistic prefix-cache and cold-cache modes.
- Signals to check:
  - low device busy despite no errors
  - large CPU and NPU idle gaps between API bursts

### H4: CPU-Side Dispatch Path Optimization
- Reduce Python-side per-request overhead in hot loops.
- Reuse immutable prompt templates and precomputed payload pieces.
- Batch host-side work before crossing framework/runtime boundaries.
- Signals to check:
  - dense API calls with long host bubbles
  - high CPU time relative to NPU stream active time

### H5: Communication/Collective Path Optimization
- Tune collective behavior and topology-aware options.
- Favor options that improve comm-compute overlap and reduce collective latency.
- Validate under sustained load, not sparse calls.
- Signals to check:
  - communication-dominant timeline
  - little or no compute/communication overlap

### H6: Copy and Memory-Movement Reduction
- Eliminate unnecessary host<->device copies in hot path.
- Avoid repeated tensor materialization, format conversion, and staging buffers.
- Reuse preallocated buffers where safe.
- Signals to check:
  - frequent memcpy-like kernels around compute kernels
  - high copy duration share without throughput gain

### H7: Kernel Fusion and Operator-Level Optimization
- Fuse adjacent lightweight ops where possible.
- Prefer fused kernels that reduce launch count and memory traffic.
- Validate numerics and determinism after fusion changes.
- Signals to check:
  - many short kernels with high launch overhead
  - repetitive micro-loop motifs with low arithmetic intensity

### H8: Parallelism and Sharding Strategy
- Revisit TP/PP/DP balance for current model and hardware.
- Use sharding only when it improves memory/perf tradeoff in this scenario.
- Verify communication overhead after changing partition strategy.
- Signals to check:
  - memory headroom exists but throughput plateaus early
  - communication overhead rises disproportionately with TP

### H9: KV Cache and Prefix Cache Behavior
- Tune cache policy for target traffic profile.
- Separate cache-hit and cache-miss scenarios in evaluation.
- Optimize KV layout/reuse before adding algorithmic complexity.
- Signals to check:
  - decode latency dominated by cache management
  - inconsistent gains across prompt distributions

### H10: Compiler/Graph Capture Strategy
- Stabilize shapes and dispatch to maximize graph reuse.
- Reduce frequent re-captures or incompatible dynamic paths.
- Compare eager vs graph mode when shape churn is high.
- Signals to check:
  - repeated compile/capture overhead
  - low graph hit rate and unstable latency

## Source-Level Patch Candidates (Non-Env)

### S1: Benchmark Harness Refactor
- Keep one `LLM` instance alive across repeated measurements.
- Add explicit warmup iterations excluded from metrics.
- Emit separate metrics: `startup_*`, `steady_*`.

### S2: Request Construction Fast Path
- Prebuild request payload objects outside hot loop.
- Avoid repeated string concatenation for deterministic prompts.
- Reuse tokenized/preprocessed inputs when pipeline allows.

### S3: Submission and Collection Pipeline
- Separate producer/consumer stages and overlap host prep with device execution.
- Minimize blocking synchronization points in hot path.

### S4: Runtime/Executor Path
- Reduce unnecessary data marshaling between Python and backend runtime.
- Move repeated control-path logic outside per-request execution.

## Patch Proposal Template (for S6)
- `hint_id`: e.g. `H6` or `S1`
- `hypothesis`: one sentence
- `evidence_run_id`: concrete run ID
- `evidence_streams`: concrete producer/consumer stream IDs
- `evidence_refs`: file paths with line references from profiling reports
- `before_metrics`: concrete bottleneck numbers from evidence refs
- `change_scope`: files/env touched
- `expected_effect`: throughput/latency/error direction
- `risk`: correctness/stability risks
- `verification_plan`: baseline/trial protocol and rollback condition

## Hard Gate
- Do not enter `S7_PATCH_APPLY_AND_CHECK` unless the patch proposal has complete evidence fields above.
- Do not enter `S8_PATCH_BENCHMARK` if evidence and hypothesis are not one-to-one with the patch change scope.

## Rejection Is Useful
- Rejected patches are required evidence.
- Keep failed trials with reason codes to prevent rediscovery of ineffective knobs.
