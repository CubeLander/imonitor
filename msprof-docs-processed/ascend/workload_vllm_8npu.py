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

    try:
        from vllm import LLM, SamplingParams

        init_start = time.time()
        llm = LLM(
            model=model,
            tensor_parallel_size=tp,
            pipeline_parallel_size=pp,
            dtype="bfloat16",
            max_model_len=max_model_len,
        )
        init_seconds = time.time() - init_start

        params = SamplingParams(max_tokens=max_tokens, temperature=temperature)
        gen_start = time.time()
        outputs = llm.generate([prompt], params)
        generate_seconds = time.time() - gen_start

        if outputs and outputs[0].outputs:
            output_text = outputs[0].outputs[0].text

        total_seconds = time.time() - total_start
        result = {
            "status": "ok",
            "model": model,
            "tp": tp,
            "pp": pp,
            "max_model_len": max_model_len,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "prompt": prompt,
            "output_text": output_text,
            "init_seconds": round(init_seconds, 4),
            "generate_seconds": round(generate_seconds, 4),
            "total_seconds": round(total_seconds, 4),
            "timestamp": int(time.time()),
        }
        _write_json(output_json, result)

        print(f"[workload] init_seconds={result['init_seconds']}")
        print(f"[workload] generate_seconds={result['generate_seconds']}")
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
