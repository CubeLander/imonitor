#!/usr/bin/env python3
"""Run vLLM with a warmup phase and a steady-state profiling phase.

Use with Nsight Systems capture-range mode:
  nsys profile --capture-range=cudaProfilerApi --stop-on-range-end=true ...

The script warms up first (excluded from capture), then brackets steady-state
generation with cudaProfilerStart/Stop so nsys only records the steady window.
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import time
import uuid
from pathlib import Path

import torch
from vllm import LLM, SamplingParams
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
    ]
    cyc = itertools.cycle(seeds)
    return [next(cyc) for _ in range(n)]


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


def _write_event(fh, payload: dict) -> None:
    fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _sampling_for_stream(base_sampling: SamplingParams) -> SamplingParams:
    stream_sampling = copy.deepcopy(base_sampling)
    stream_sampling.output_kind = RequestOutputKind.CUMULATIVE
    return stream_sampling


def _run_streaming_iter(
    llm: LLM,
    prompts: list[str],
    sampling: SamplingParams,
    req_ids: list[int],
    iter_id: int,
    session_id: str,
    profile_start_ns: int,
    req_fh,
) -> None:
    iter_start_ns = time.monotonic_ns()
    rel = int(iter_start_ns - profile_start_ns)

    req_state: dict[int, dict] = {}
    for idx, prompt in enumerate(prompts):
        rid = int(req_ids[idx])
        common = {
            "session_id": session_id,
            "req_id": rid,
            "iter_id": int(iter_id),
            "ts_ns": int(iter_start_ns),
            "rel_ns": int(rel),
        }
        _write_event(
            req_fh,
            {
                "event_type": "request_in",
                **common,
                "prompt_chars": int(len(prompt)),
            },
        )
        _write_event(req_fh, {"event_type": "prefill_start", **common})

        engine_input = llm._preprocess_cmpl_one(prompt, None)
        llm.llm_engine.add_request(
            str(rid),
            engine_input,
            _sampling_for_stream(sampling),
            lora_request=None,
            priority=0,
        )
        req_state[rid] = {
            "start_ns": int(iter_start_ns),
            "prev_tokens": 0,
            "decode_started": False,
            "input_tokens": None,
        }

    finished: set[int] = set()
    while len(finished) < len(req_ids):
        step_outputs = llm.llm_engine.step()
        step_ts = int(time.monotonic_ns())
        step_rel = int(step_ts - profile_start_ns)

        for out in step_outputs:
            rid = int(getattr(out, "request_id", -1))
            if rid not in req_state:
                continue
            st = req_state[rid]
            tok_ids = _extract_token_ids(out)
            curr = int(len(tok_ids))

            in_tok = _extract_prompt_token_count(out)
            if in_tok is not None:
                st["input_tokens"] = int(in_tok)

            if curr > int(st["prev_tokens"]):
                if not bool(st["decode_started"]):
                    _write_event(
                        req_fh,
                        {
                            "event_type": "prefill_done",
                            "session_id": session_id,
                            "req_id": rid,
                            "iter_id": int(iter_id),
                            "ts_ns": int(step_ts),
                            "rel_ns": int(step_rel),
                            "input_tokens": st["input_tokens"],
                        },
                    )
                    _write_event(
                        req_fh,
                        {
                            "event_type": "decode_start",
                            "session_id": session_id,
                            "req_id": rid,
                            "iter_id": int(iter_id),
                            "ts_ns": int(step_ts),
                            "rel_ns": int(step_rel),
                            "input_tokens": st["input_tokens"],
                        },
                    )
                    st["decode_started"] = True

                for t_idx in range(int(st["prev_tokens"]) + 1, curr + 1):
                    _write_event(
                        req_fh,
                        {
                            "event_type": "token_out",
                            "session_id": session_id,
                            "req_id": rid,
                            "iter_id": int(iter_id),
                            "token_idx": int(t_idx),
                            "token_id": int(tok_ids[t_idx - 1]),
                            "ts_ns": int(step_ts),
                            "rel_ns": int(step_rel),
                            "input_tokens": st["input_tokens"],
                            "output_tokens_so_far": int(t_idx),
                            "timing_source": "stream",
                        },
                    )
                st["prev_tokens"] = curr

            if bool(getattr(out, "finished", False)) and rid not in finished:
                if not bool(st["decode_started"]):
                    _write_event(
                        req_fh,
                        {
                            "event_type": "prefill_done",
                            "session_id": session_id,
                            "req_id": rid,
                            "iter_id": int(iter_id),
                            "ts_ns": int(step_ts),
                            "rel_ns": int(step_rel),
                            "input_tokens": st["input_tokens"],
                        },
                    )
                latency_ms = max(0.0, (step_ts - int(st["start_ns"])) / 1e6)
                _write_event(
                    req_fh,
                    {
                        "event_type": "request_done",
                        "session_id": session_id,
                        "req_id": rid,
                        "iter_id": int(iter_id),
                        "ts_ns": int(step_ts),
                        "rel_ns": int(step_rel),
                        "input_tokens": st["input_tokens"],
                        "final_output_tokens": int(st["prev_tokens"]),
                        "latency_ms": round(float(latency_ms), 6),
                    },
                )
                finished.add(rid)


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
    req_fh = None
    session_id = f"sess-{uuid.uuid4().hex[:12]}"
    if args.request_events_out:
        out_path = Path(args.request_events_out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        req_fh = out_path.open("w", encoding="utf-8")
        _write_event(
            req_fh,
            {
                "event_type": "session_meta",
                "session_id": session_id,
                "ts_ns": time.monotonic_ns(),
                "model": str(args.model),
                "tensor_parallel_size": int(args.tensor_parallel_size),
                "requests_per_iter": int(args.requests_per_iter),
                "warmup_iters": int(args.warmup_iters),
                "profile_iters": int(args.profile_iters),
                "max_tokens": int(args.max_tokens),
                "temperature": float(args.temperature),
                "gpu_name": torch.cuda.get_device_name(0),
                "gpu_count": int(torch.cuda.device_count()),
                "capture_mode": str(args.capture_mode),
                "distributed_executor_backend": str(args.distributed_executor_backend),
            },
        )
    use_profiler_api = str(args.capture_mode) == "cuda-profiler-api"
    profile_start_ns = time.monotonic_ns()
    if req_fh is not None:
        _write_event(
            req_fh,
            {
                "event_type": "profile_phase_start",
                "session_id": session_id,
                "ts_ns": profile_start_ns,
                "rel_ns": 0,
            },
        )
    torch.cuda.nvtx.range_push("IMONITOR_PROFILE_PHASE")
    if use_profiler_api:
        _profiler_start()
    t1 = time.time()
    req_id_base = 0
    for i in range(int(args.profile_iters)):
        s = i * rpi
        prompts = profile_prompts[s : s + rpi]
        req_ids = list(range(req_id_base + 1, req_id_base + 1 + len(prompts)))
        req_id_base += len(prompts)
        if req_fh is None:
            llm.generate(prompts, sampling)
            continue

        _run_streaming_iter(
            llm=llm,
            prompts=prompts,
            sampling=sampling,
            req_ids=req_ids,
            iter_id=i,
            session_id=session_id,
            profile_start_ns=profile_start_ns,
            req_fh=req_fh,
        )

    torch.cuda.synchronize()
    if use_profiler_api:
        _profiler_stop()
    torch.cuda.nvtx.range_pop()
    prof_sec = time.time() - t1

    if req_fh is not None:
        _write_event(
            req_fh,
            {
                "event_type": "profile_phase_done",
                "session_id": session_id,
                "ts_ns": time.monotonic_ns(),
                "rel_ns": int(time.monotonic_ns() - profile_start_ns),
                "profile_sec": round(prof_sec, 6),
            },
        )
        req_fh.close()

    print(
        f"[steady] profile_done sec={prof_sec:.2f} "
        f"iters={args.profile_iters} iters_per_sec={args.profile_iters / max(prof_sec, 1e-9):.3f}",
        flush=True,
    )
    if args.request_events_out:
        print(f"[steady] request_events={Path(args.request_events_out).resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
