#!/usr/bin/env python3
"""Run vLLM AsyncLLMEngine with random request arrivals for profiling.

This script is designed for external profiling (e.g. nsys). It supports:
- warmup requests (not profiled)
- profiled phase with random inter-arrival gaps
- real streaming token timestamps (no linear interpolation)
- optional JSONL request event output for timeline visualization
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import itertools
import json
import os
import random
import sys
import time
import uuid
from pathlib import Path

import torch
from vllm import SamplingParams
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.engine.async_llm_engine import AsyncLLMEngine
from vllm.sampling_params import RequestOutputKind


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
        "How do CUDA streams impact overlap between compute and memcpy?",
        "When should we prefer throughput over p99 latency for LLM serving?",
    ]
    cyc = itertools.cycle(seeds)
    return [f"{next(cyc)} [req_seed={i}]" for i in range(n)]


def _extract_token_ids(req_out) -> list[int]:
    outs = getattr(req_out, "outputs", None)
    if not outs:
        return []
    tok = getattr(outs[0], "token_ids", None)
    if not tok:
        return []
    return [int(x) for x in tok]


def _extract_prompt_token_count(req_out) -> int | None:
    ids = getattr(req_out, "prompt_token_ids", None)
    if ids is None:
        return None
    try:
        return int(len(ids))
    except Exception:
        return None


def _sample_gap_s(
    rng: random.Random,
    mean_ms: float,
    std_ms: float,
    min_ms: float,
    max_ms: float,
) -> float:
    if std_ms > 0:
        g = float(rng.gauss(mean_ms, std_ms))
    else:
        g = float(mean_ms)
    g = max(float(min_ms), g)
    if max_ms > 0:
        g = min(float(max_ms), g)
    return max(0.0, g / 1000.0)


async def _write_event(lock: asyncio.Lock, fh, payload: dict) -> None:
    if fh is None:
        return
    async with lock:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


async def _drain_warmup_request(
    engine: AsyncLLMEngine,
    prompt: str,
    sampling: SamplingParams,
    request_id: str,
) -> None:
    async for _ in engine.generate(prompt, sampling, request_id=request_id):
        pass


async def _run_one_profile_request(
    engine: AsyncLLMEngine,
    sampling: SamplingParams,
    prompt: str,
    req_id: int,
    engine_request_id: str,
    submit_idx: int,
    session_id: str,
    profile_start_ns: int,
    event_lock: asyncio.Lock,
    event_fh,
) -> dict:
    submit_ns = time.monotonic_ns()
    submit_rel = int(submit_ns - profile_start_ns)

    await _write_event(
        event_lock,
        event_fh,
        {
            "event_type": "request_in",
            "session_id": session_id,
            "req_id": int(req_id),
            "submit_idx": int(submit_idx),
            "ts_ns": int(submit_ns),
            "rel_ns": int(submit_rel),
            "prompt_chars": int(len(prompt)),
        },
    )
    await _write_event(
        event_lock,
        event_fh,
        {
            "event_type": "prefill_start",
            "session_id": session_id,
            "req_id": int(req_id),
            "submit_idx": int(submit_idx),
            "ts_ns": int(submit_ns),
            "rel_ns": int(submit_rel),
        },
    )

    prev_tokens = 0
    decode_started = False
    input_tokens = None

    try:
        async for out in engine.generate(
            prompt, sampling, request_id=str(engine_request_id)
        ):
            now_ns = time.monotonic_ns()
            now_rel = int(now_ns - profile_start_ns)

            in_tok = _extract_prompt_token_count(out)
            if in_tok is not None:
                input_tokens = int(in_tok)

            tok_ids = _extract_token_ids(out)
            curr_tokens = int(len(tok_ids))

            if curr_tokens > prev_tokens:
                if not decode_started:
                    await _write_event(
                        event_lock,
                        event_fh,
                        {
                            "event_type": "prefill_done",
                            "session_id": session_id,
                            "req_id": int(req_id),
                            "submit_idx": int(submit_idx),
                            "ts_ns": int(now_ns),
                            "rel_ns": int(now_rel),
                            "input_tokens": input_tokens,
                        },
                    )
                    await _write_event(
                        event_lock,
                        event_fh,
                        {
                            "event_type": "decode_start",
                            "session_id": session_id,
                            "req_id": int(req_id),
                            "submit_idx": int(submit_idx),
                            "ts_ns": int(now_ns),
                            "rel_ns": int(now_rel),
                            "input_tokens": input_tokens,
                        },
                    )
                    decode_started = True

                for t_idx in range(prev_tokens + 1, curr_tokens + 1):
                    await _write_event(
                        event_lock,
                        event_fh,
                        {
                            "event_type": "token_out",
                            "session_id": session_id,
                            "req_id": int(req_id),
                            "submit_idx": int(submit_idx),
                            "token_idx": int(t_idx),
                            "token_id": int(tok_ids[t_idx - 1]),
                            "ts_ns": int(now_ns),
                            "rel_ns": int(now_rel),
                            "input_tokens": input_tokens,
                            "output_tokens_so_far": int(t_idx),
                            "timing_source": "async_stream",
                        },
                    )
                prev_tokens = curr_tokens

            if bool(getattr(out, "finished", False)):
                if not decode_started:
                    await _write_event(
                        event_lock,
                        event_fh,
                        {
                            "event_type": "prefill_done",
                            "session_id": session_id,
                            "req_id": int(req_id),
                            "submit_idx": int(submit_idx),
                            "ts_ns": int(now_ns),
                            "rel_ns": int(now_rel),
                            "input_tokens": input_tokens,
                        },
                    )
                latency_ms = max(0.0, (now_ns - submit_ns) / 1e6)
                await _write_event(
                    event_lock,
                    event_fh,
                    {
                        "event_type": "request_done",
                        "session_id": session_id,
                        "req_id": int(req_id),
                        "submit_idx": int(submit_idx),
                        "ts_ns": int(now_ns),
                        "rel_ns": int(now_rel),
                        "input_tokens": input_tokens,
                        "final_output_tokens": int(prev_tokens),
                        "latency_ms": round(float(latency_ms), 6),
                    },
                )
                return {
                    "ok": True,
                    "req_id": int(req_id),
                    "latency_ms": float(latency_ms),
                    "output_tokens": int(prev_tokens),
                }

        raise RuntimeError("stream_ended_without_finished")
    except Exception as e:
        now_ns = time.monotonic_ns()
        now_rel = int(now_ns - profile_start_ns)
        await _write_event(
            event_lock,
            event_fh,
            {
                "event_type": "request_error",
                "session_id": session_id,
                "req_id": int(req_id),
                "submit_idx": int(submit_idx),
                "ts_ns": int(now_ns),
                "rel_ns": int(now_rel),
                "error": str(e),
            },
        )
        try:
            await engine.abort(str(engine_request_id))
        except Exception:
            pass
        return {
            "ok": False,
            "req_id": int(req_id),
            "latency_ms": None,
            "output_tokens": int(prev_tokens),
            "error": str(e),
        }


async def _run_async_workload(args: argparse.Namespace) -> dict:
    patch_dir = str(Path(__file__).resolve().parents[1] / "patches")
    debug_enabled = str(os.environ.get("IMONITOR_CHILD_NVTX_DEBUG", "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    cur_pp = os.environ.get("PYTHONPATH", "")
    if patch_dir not in cur_pp.split(":"):
        os.environ["PYTHONPATH"] = f"{patch_dir}:{cur_pp}" if cur_pp else patch_dir
    if patch_dir not in sys.path:
        sys.path.insert(0, patch_dir)
    os.environ.setdefault("IMONITOR_CHILD_NVTX", "1")
    os.environ.setdefault("IMONITOR_PROFILE_REQ_PREFIX", str(args.profile_request_id_prefix))
    os.environ.setdefault("IMONITOR_PROFILE_NVTX_NAME", "IMONITOR_PROFILE_PHASE")
    patch_loaded = False
    patch_mod = None
    try:
        patch_file = Path(patch_dir) / "sitecustomize.py"
        if patch_file.is_file():
            spec = importlib.util.spec_from_file_location(
                "imonitor_sitecustomize_patch", str(patch_file)
            )
            if spec is not None and spec.loader is not None:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                patch_loaded = True
                patch_mod = mod
        else:
            import sitecustomize  # noqa: F401
            patch_loaded = True
    except Exception as e:
        if debug_enabled:
            print(f"[async] child_nvtx_patch_load_failed err={e!r}", flush=True)
    if debug_enabled:
        print(
            "[async] child_nvtx_patch_loaded="
            f"{int(patch_loaded)} patch_dir={patch_dir} "
            f"env_child={os.environ.get('IMONITOR_CHILD_NVTX','')} "
            f"env_dbg={os.environ.get('IMONITOR_CHILD_NVTX_DEBUG','')} "
            f"env_log={os.environ.get('IMONITOR_CHILD_NVTX_DEBUG_LOG','')}",
            flush=True,
        )
        if patch_mod is not None and hasattr(patch_mod, "_debug"):
            try:
                dbg_on = False
                if hasattr(patch_mod, "_debug_enabled"):
                    dbg_on = bool(patch_mod._debug_enabled())
                print(f"[async] child_nvtx_patch_debug_enabled={int(dbg_on)}", flush=True)
                patch_mod._debug("script_patch_loaded")
            except Exception as e:
                print(f"[async] child_nvtx_patch_debug_failed err={e!r}", flush=True)

    engine_args = AsyncEngineArgs(
        model=str(args.model),
        tensor_parallel_size=int(args.tensor_parallel_size),
        gpu_memory_utilization=float(args.gpu_memory_utilization),
        distributed_executor_backend=str(args.distributed_executor_backend),
        disable_log_stats=True,
    )
    engine = AsyncLLMEngine.from_engine_args(engine_args)

    sampling = SamplingParams(
        temperature=float(args.temperature),
        max_tokens=int(args.max_tokens),
        output_kind=RequestOutputKind.CUMULATIVE,
    )

    prompt_pool = _make_prompts(max(1, int(args.prompt_pool_size)))

    warmup_n = max(0, int(args.warmup_requests))
    if warmup_n > 0:
        t0 = time.time()
        warmup_tasks = [
            asyncio.create_task(
                _drain_warmup_request(
                    engine,
                    prompt_pool[i % len(prompt_pool)],
                    sampling,
                    request_id=f"warmup-{i+1}",
                )
            )
            for i in range(warmup_n)
        ]
        await asyncio.gather(*warmup_tasks)
        torch.cuda.synchronize()
        print(f"[async] warmup_done sec={time.time() - t0:.2f} reqs={warmup_n}", flush=True)

    req_fh = None
    req_lock = asyncio.Lock()
    session_id = f"sess-{uuid.uuid4().hex[:12]}"

    if args.request_events_out:
        out_path = Path(args.request_events_out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        req_fh = out_path.open("w", encoding="utf-8")
        req_fh.write(
            json.dumps(
                {
                    "event_type": "session_meta",
                    "session_id": session_id,
                    "ts_ns": time.monotonic_ns(),
                    "model": str(args.model),
                    "tensor_parallel_size": int(args.tensor_parallel_size),
                    "warmup_requests": int(args.warmup_requests),
                    "profile_requests": int(args.profile_requests),
                    "max_tokens": int(args.max_tokens),
                    "temperature": float(args.temperature),
                    "gap_dist": "normal",
                    "gap_mean_ms": float(args.gap_mean_ms),
                    "gap_std_ms": float(args.gap_std_ms),
                    "gap_min_ms": float(args.gap_min_ms),
                    "gap_max_ms": float(args.gap_max_ms),
                    "max_inflight": int(args.max_inflight),
                    "seed": int(args.seed),
                    "gpu_name": torch.cuda.get_device_name(0),
                    "gpu_count": int(torch.cuda.device_count()),
                    "capture_mode": str(args.capture_mode),
                    "distributed_executor_backend": str(args.distributed_executor_backend),
                    "engine": "AsyncLLMEngine",
                    "profile_request_id_prefix": str(args.profile_request_id_prefix),
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    use_profiler_api = str(args.capture_mode) == "cuda-profiler-api"
    if use_profiler_api:
        _profiler_start()
    profile_start_ns = time.monotonic_ns()
    if req_fh is not None:
        req_fh.write(
            json.dumps(
                {
                    "event_type": "profile_phase_start",
                    "session_id": session_id,
                    "ts_ns": int(profile_start_ns),
                    "rel_ns": 0,
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    t1 = time.time()
    rng = random.Random(int(args.seed))
    profile_n = max(1, int(args.profile_requests))
    sem = asyncio.Semaphore(max(1, int(args.max_inflight)))

    async def _submit_one(i: int):
        req_id = i + 1
        engine_req_id = f"{args.profile_request_id_prefix}{req_id}"
        prompt = prompt_pool[i % len(prompt_pool)]
        async with sem:
            return await _run_one_profile_request(
                engine=engine,
                sampling=sampling,
                prompt=prompt,
                req_id=req_id,
                engine_request_id=engine_req_id,
                submit_idx=i,
                session_id=session_id,
                profile_start_ns=profile_start_ns,
                event_lock=req_lock,
                event_fh=req_fh,
            )

    tasks = []
    for i in range(profile_n):
        if i > 0:
            gap_s = _sample_gap_s(
                rng=rng,
                mean_ms=float(args.gap_mean_ms),
                std_ms=float(args.gap_std_ms),
                min_ms=float(args.gap_min_ms),
                max_ms=float(args.gap_max_ms),
            )
            if gap_s > 0:
                await asyncio.sleep(gap_s)
        tasks.append(asyncio.create_task(_submit_one(i)))

    results = await asyncio.gather(*tasks)

    torch.cuda.synchronize()
    if use_profiler_api:
        _profiler_stop()
    prof_sec = max(1e-9, time.time() - t1)

    if req_fh is not None:
        now_ns = time.monotonic_ns()
        req_fh.write(
            json.dumps(
                {
                    "event_type": "profile_phase_done",
                    "session_id": session_id,
                    "ts_ns": int(now_ns),
                    "rel_ns": int(now_ns - profile_start_ns),
                    "profile_sec": round(float(prof_sec), 6),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        req_fh.close()

    ok = [r for r in results if r.get("ok")]
    err = [r for r in results if not r.get("ok")]
    total_out = sum(int(r.get("output_tokens", 0)) for r in ok)
    lat = [float(r.get("latency_ms", 0.0)) for r in ok if r.get("latency_ms") is not None]
    p50 = sorted(lat)[len(lat) // 2] if lat else 0.0

    try:
        engine.shutdown()
    except Exception:
        pass

    return {
        "profile_sec": float(prof_sec),
        "profile_requests": int(profile_n),
        "success_requests": int(len(ok)),
        "error_requests": int(len(err)),
        "total_output_tokens": int(total_out),
        "throughput_req_s": float(profile_n / prof_sec),
        "throughput_out_tok_s": float(total_out / prof_sec),
        "latency_p50_ms": float(p50),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="AsyncLLMEngine random-arrival profiler helper")
    p.add_argument("--model", default="facebook/opt-125m")
    p.add_argument("--tensor-parallel-size", type=int, default=1)
    p.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    p.add_argument("--distributed-executor-backend", type=str, default="uni", choices=["uni", "mp", "ray"])
    p.add_argument("--warmup-requests", type=int, default=8)
    p.add_argument("--profile-requests", type=int, default=160)
    p.add_argument("--max-inflight", type=int, default=64)
    p.add_argument("--prompt-pool-size", type=int, default=64)
    p.add_argument("--max-tokens", type=int, default=64)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--gap-mean-ms", type=float, default=50.0)
    p.add_argument("--gap-std-ms", type=float, default=15.0)
    p.add_argument("--gap-min-ms", type=float, default=0.0)
    p.add_argument("--gap-max-ms", type=float, default=500.0)
    p.add_argument("--profile-request-id-prefix", type=str, default="profile-")
    p.add_argument("--seed", type=int, default=20260412)
    p.add_argument(
        "--capture-mode",
        type=str,
        default="cuda-profiler-api",
        choices=["cuda-profiler-api", "none"],
        help=(
            "'cuda-profiler-api' brackets steady phase with cudaProfilerStart/Stop; "
            "'none' runs steady phase without profiler API hooks."
        ),
    )
    p.add_argument(
        "--request-events-out",
        type=str,
        default="",
        help="Optional JSONL path to write per-request external events (input/token/done).",
    )
    args = p.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable")

    print(
        f"[async] model={args.model} warmup_req={args.warmup_requests} profile_req={args.profile_requests} "
        f"gap=N({args.gap_mean_ms},{args.gap_std_ms})ms inflight={args.max_inflight}",
        flush=True,
    )

    res = asyncio.run(_run_async_workload(args))

    print(
        "[async] profile_done "
        f"sec={res['profile_sec']:.2f} req={res['profile_requests']} ok={res['success_requests']} err={res['error_requests']} "
        f"req/s={res['throughput_req_s']:.3f} out_tok/s={res['throughput_out_tok_s']:.3f} "
        f"p50_ms={res['latency_p50_ms']:.3f}",
        flush=True,
    )
    if args.request_events_out:
        print(f"[async] request_events={Path(args.request_events_out).resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
