#!/usr/bin/env sh
set -eu

BASE=/workspace/imonitor/develop/vllm_smoke_20260413
LOG_DIR="$BASE/logs"
mkdir -p "$LOG_DIR"

MODEL=$(find /data/models/models--Qwen--Qwen3-8B/snapshots -maxdepth 1 -mindepth 1 -type d | head -n 1)
if [ -z "$MODEL" ]; then
  echo "[error] cannot find Qwen3-8B snapshot" >&2
  exit 2
fi

echo "[info] model=$MODEL"

cleanup_vllm() {
  pkill -9 -f "VLLM::" || true
  pkill -9 -f "vllm_tp_pp_smoke.py" || true
  pkill -9 -f "multiprocessing.forkserver" || true
  pkill -9 -f "multiprocessing.resource_tracker" || true
}

run_case() {
  name="$1"
  tp="$2"
  pp="$3"
  out="$BASE/$name"
  mkdir -p "$out"
  cleanup_vllm

  cat > /tmp/vllm_tp_pp_smoke.py <<PY
import os
from vllm import LLM, SamplingParams

model = os.environ['SMOKE_MODEL']
tp = int(os.environ['SMOKE_TP'])
pp = int(os.environ['SMOKE_PP'])
print(f"[workload] model={model} tp={tp} pp={pp}")
llm = LLM(
    model=model,
    tensor_parallel_size=tp,
    pipeline_parallel_size=pp,
    dtype='bfloat16',
    max_model_len=1024,
)
params = SamplingParams(max_tokens=24, temperature=0.0)
out = llm.generate(["请用一句话介绍昇腾NPU。"], params)
text = out[0].outputs[0].text if out and out[0].outputs else ''
print('[workload] output:', text[:120])
print('[workload] done')
PY

  echo "[case:$name] start tp=$tp pp=$pp"
  set +e
  SMOKE_MODEL="$MODEL" SMOKE_TP="$tp" SMOKE_PP="$pp" VLLM_PLUGINS=ascend \
    timeout 900s python3 /tmp/vllm_tp_pp_smoke.py >"$LOG_DIR/$name.log" 2>&1
  rc=$?
  set -e
  echo "$rc" >"$out/exit_code.txt"
  echo "[case:$name] rc=$rc"
}

run_case tp2_pp1 2 1
run_case tp2_pp2 2 2
cleanup_vllm

echo "[summary]"
for c in tp2_pp1 tp2_pp2; do
  rc="NA"
  [ -f "$BASE/$c/exit_code.txt" ] && rc=$(cat "$BASE/$c/exit_code.txt")
  echo "$c rc=$rc"
done
