# Workload Design for Throughput Autotuning

## Goal
Use request streams that represent production behavior and avoid synthetic artifacts that overstate improvements.

## Baseline Recommendation
- Prefer mature datasets already supported by vLLM benchmark tooling.
- Use `vllm bench serve` for serving throughput.
- Prefer ShareGPT-like conversation distributions for general LLM serving.
- Add BurstGPT-style bursty workloads if production has traffic bursts.
- If CLI is unavailable, finish editable install and preflight before workload runs.

## Prefix Cache Safety Rules
- Do not run throughput tuning on a single repeated prompt.
- Track unique-prefix ratio and keep it above threshold in cold-cache mode.
- Evaluate two cache regimes:
- `cold`: prefix cache disabled or mostly unique prefixes.
- `realistic`: prefix cache enabled with bounded reuse ratio aligned to production.
- Record cache mode in every trial artifact.

## Suggested Dataset Modes
1. `sharegpt_realistic`
- Source: ShareGPT-compatible prompt corpus.
- Use `vllm bench serve --dataset-name sharegpt`.
- Good for user-facing chat throughput.

2. `custom_jsonl_realistic`
- Source: production-like `.jsonl` prompts with heterogeneous lengths.
- Use `vllm bench serve --dataset-name custom`.
- Good when team has internal request traces.

3. `multi_turn_cache_stress`
- Source: converted ShareGPT conversations or synthetic multi-turn config.
- Use `vllm/benchmarks/multi_turn/benchmark_serving_multi_turn.py`.
- Good for measuring cache policy and long-session behavior.

## Saturation Procedure
1. Fix model, parallelism, and cache policy.
2. Sweep request concurrency upward.
3. Measure output token throughput, queueing delay, and error rate.
4. Select the smallest concurrency where throughput plateaus and instability is acceptable.
5. Freeze this workload setting for baseline/trial comparison.

## Reproducibility Fields to Log
- dataset identifier and checksum
- request count and seed
- prompt length distribution summary
- output length cap and sampling parameters
- cache mode
- benchmark command line

## Practical Command Notes
- `vllm bench serve` replaces deprecated `benchmarks/benchmark_serving.py`.
- Save benchmark outputs in a per-trial folder and reference them from `trials.csv`.
- A temporary `mock` mode is allowed for gate-plumbing checks when runtime dependencies are blocked.
