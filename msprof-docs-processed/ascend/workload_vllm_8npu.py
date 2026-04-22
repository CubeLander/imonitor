#!/usr/bin/env python3
import json
import os
import time
import traceback
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return int(value)


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _write_json(path: str, payload: dict) -> None:
    if not path:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    model = os.environ.get("SMOKE_MODEL", "").strip()
    if not model:
        raise RuntimeError("SMOKE_MODEL is required")

    tp = _int_env("SMOKE_TP", 8)
    pp = _int_env("SMOKE_PP", 1)
    max_model_len = _int_env("SMOKE_MAX_MODEL_LEN", 1024)
    max_tokens = _int_env("SMOKE_MAX_TOKENS", 32)
    batch_size = max(1, _int_env("SMOKE_BATCH_SIZE", 1))
    rounds = max(1, _int_env("SMOKE_ROUNDS", 1))
    trust_remote_code = _bool_env("SMOKE_TRUST_REMOTE_CODE", False)
    hf_overrides_json = os.environ.get("SMOKE_HF_OVERRIDES_JSON", "").strip()
    temperature = float(os.environ.get("SMOKE_TEMPERATURE", "0.0"))
    prompt = os.environ.get(
        "SMOKE_PROMPT",
        "Explain the purpose of msprof in one sentence.",
    )
    output_json = os.environ.get("SMOKE_OUTPUT_JSON", "")

    print(f"[workload] model={model}")
    print(f"[workload] tp={tp} pp={pp} max_model_len={max_model_len}")

    total_start = time.time()
    init_seconds = 0.0
    generate_seconds = 0.0
    output_text = ""
    round_latencies = []
    generated_tokens = 0
    hf_overrides = None
    if hf_overrides_json:
        hf_overrides = json.loads(hf_overrides_json)

    try:
        from vllm import LLM, SamplingParams

        init_start = time.time()
        llm = LLM(
            model=model,
            tensor_parallel_size=tp,
            pipeline_parallel_size=pp,
            dtype="bfloat16",
            max_model_len=max_model_len,
            trust_remote_code=trust_remote_code,
            hf_overrides=hf_overrides,
        )
        init_seconds = time.time() - init_start

        params = SamplingParams(max_tokens=max_tokens, temperature=temperature)
        gen_start = time.time()
        for r in range(rounds):
            prompts = [f"{prompt}\n[request={r}-{i}]" for i in range(batch_size)]
            round_start = time.time()
            outputs = llm.generate(prompts, params)
            round_latencies.append(time.time() - round_start)
            for item in outputs:
                if item.outputs:
                    text = item.outputs[0].text or ""
                    generated_tokens += len(text.split())
            if outputs and outputs[0].outputs:
                output_text = outputs[0].outputs[0].text
        generate_seconds = time.time() - gen_start
        total_requests = rounds * batch_size

        total_seconds = time.time() - total_start
        result = {
            "status": "ok",
            "model": model,
            "tp": tp,
            "pp": pp,
            "max_model_len": max_model_len,
            "max_tokens": max_tokens,
            "batch_size": batch_size,
            "rounds": rounds,
            "trust_remote_code": trust_remote_code,
            "hf_overrides": hf_overrides,
            "total_requests": total_requests,
            "temperature": temperature,
            "prompt": prompt,
            "output_text": output_text,
            "generated_tokens_estimate": generated_tokens,
            "request_throughput_rps": round(total_requests / max(generate_seconds, 1e-9), 4),
            "avg_round_seconds": round(sum(round_latencies) / max(len(round_latencies), 1), 4),
            "init_seconds": round(init_seconds, 4),
            "generate_seconds": round(generate_seconds, 4),
            "total_seconds": round(total_seconds, 4),
            "timestamp": int(time.time()),
        }
        _write_json(output_json, result)

        print(f"[workload] init_seconds={result['init_seconds']}")
        print(f"[workload] generate_seconds={result['generate_seconds']}")
        print(f"[workload] total_requests={result['total_requests']} throughput_rps={result['request_throughput_rps']}")
        print(f"[workload] total_seconds={result['total_seconds']}")
        print("[workload] output:", output_text[:200])
        print("[workload] done")
        return 0
    except Exception as exc:
        total_seconds = time.time() - total_start
        failed = {
            "status": "error",
            "model": model,
            "tp": tp,
            "pp": pp,
            "batch_size": batch_size,
            "rounds": rounds,
            "trust_remote_code": trust_remote_code,
            "hf_overrides": hf_overrides,
            "prompt": prompt,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "init_seconds": round(init_seconds, 4),
            "generate_seconds": round(generate_seconds, 4),
            "total_seconds": round(total_seconds, 4),
            "timestamp": int(time.time()),
        }
        _write_json(output_json, failed)
        print("[workload][error]", exc)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
