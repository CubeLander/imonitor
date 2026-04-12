#!/usr/bin/env python3
"""Run vLLM with a warmup phase and a steady-state profiling phase.

Use with Nsight Systems capture-range mode:
  nsys profile --capture-range=cudaProfilerApi --stop-on-range-end=true ...

The script warms up first (excluded from capture), then brackets steady-state
generation with cudaProfilerStart/Stop so nsys only records the steady window.
"""

from __future__ import annotations

import argparse
import itertools
import time

import torch
from vllm import LLM, SamplingParams


def _profiler_start() -> None:
    torch.cuda.synchronize()
    err = int(torch.cuda.cudart().cudaProfilerStart())
    if err != 0:
        raise RuntimeError(f"cudaProfilerStart failed with code={err}")


def _profiler_stop() -> None:
    torch.cuda.synchronize()
    err = int(torch.cuda.cudart().cudaProfilerStop())
    if err != 0:
        raise RuntimeError(f"cudaProfilerStop failed with code={err}")


def _make_prompts(n: int) -> list[str]:
    seeds = [
        "Summarize GPU profiling in one paragraph.",
        "What is the difference between latency and throughput?",
        "Explain why pinned memory helps host-to-device copy.",
        "Give three tips to optimize LLM inference performance.",
    ]
    cyc = itertools.cycle(seeds)
    return [next(cyc) for _ in range(n)]


def main() -> int:
    p = argparse.ArgumentParser(description="vLLM steady-state profiler helper")
    p.add_argument("--model", default="facebook/opt-125m")
    p.add_argument("--tensor-parallel-size", type=int, default=1)
    p.add_argument("--gpu-memory-utilization", type=float, default=0.35)
    p.add_argument("--requests-per-iter", type=int, default=1)
    p.add_argument("--warmup-iters", type=int, default=3)
    p.add_argument("--profile-iters", type=int, default=24)
    p.add_argument("--max-tokens", type=int, default=32)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument(
        "--capture-mode",
        type=str,
        default="cuda-profiler-api",
        choices=["cuda-profiler-api", "none"],
        help=(
            "'cuda-profiler-api' brackets steady phase with cudaProfilerStart/Stop; "
            "'none' runs steady phase without profiler API hooks (use nsys --delay/--duration)."
        ),
    )
    p.add_argument(
        "--distributed-executor-backend",
        type=str,
        default="uni",
        choices=["uni", "mp"],
        help="Use 'uni' so capture-range hooks affect the actual GPU execution process.",
    )
    args = p.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable")

    print(
        f"[steady] model={args.model} tp={args.tensor_parallel_size} "
        f"warmup={args.warmup_iters} profile={args.profile_iters} "
        f"rpi={args.requests_per_iter}",
        flush=True,
    )

    llm = LLM(
        model=args.model,
        tensor_parallel_size=int(args.tensor_parallel_size),
        gpu_memory_utilization=float(args.gpu_memory_utilization),
        distributed_executor_backend=str(args.distributed_executor_backend),
    )
    sampling = SamplingParams(
        temperature=float(args.temperature),
        max_tokens=int(args.max_tokens),
    )

    rpi = max(1, int(args.requests_per_iter))
    warmup_prompts = _make_prompts(max(1, int(args.warmup_iters) * rpi))
    t0 = time.time()
    for i in range(int(args.warmup_iters)):
        s = i * rpi
        llm.generate(warmup_prompts[s : s + rpi], sampling)
    torch.cuda.synchronize()
    print(f"[steady] warmup_done sec={time.time() - t0:.2f}", flush=True)

    profile_prompts = _make_prompts(max(1, int(args.profile_iters) * rpi))
    use_profiler_api = str(args.capture_mode) == "cuda-profiler-api"
    if use_profiler_api:
        _profiler_start()
    t1 = time.time()
    for i in range(int(args.profile_iters)):
        s = i * rpi
        llm.generate(profile_prompts[s : s + rpi], sampling)
    torch.cuda.synchronize()
    if use_profiler_api:
        _profiler_stop()
    prof_sec = time.time() - t1

    print(
        f"[steady] profile_done sec={prof_sec:.2f} "
        f"iters={args.profile_iters} iters_per_sec={args.profile_iters / max(prof_sec, 1e-9):.3f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
