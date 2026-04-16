#!/usr/bin/env sh
set -eu

BASE=/workspace/imonitor/develop/msprof_smoke_runs_20260413
LOG_DIR="$BASE/logs"
mkdir -p "$LOG_DIR"

MODEL=$(find /data/models/models--Qwen--Qwen3-8B/snapshots -maxdepth 1 -mindepth 1 -type d | head -n 1)
if [ -z "$MODEL" ]; then
  echo "[error] cannot find Qwen3-8B snapshot" >&2
  exit 2
fi

echo "[info] model=$MODEL"

cat > /tmp/vllm_msprof_workload.py <<'PY'
import os
from vllm import LLM, SamplingParams

model = os.environ["SMOKE_MODEL"]
tp = int(os.environ.get("SMOKE_TP", "2"))
print(f"[workload] model={model} tp={tp}")
llm = LLM(model=model, tensor_parallel_size=tp, dtype="bfloat16", max_model_len=1024)
params = SamplingParams(max_tokens=24, temperature=0.0)
out = llm.generate(["请用一句话说明msprof的用途。"], params)
text = out[0].outputs[0].text if out and out[0].outputs else ""
print("[workload] output:", text[:120])
print("[workload] done")
PY

cat > /tmp/run_vllm_msprof_workload.sh <<SH2
#!/usr/bin/env sh
set -eu
export VLLM_PLUGINS=ascend
export SMOKE_MODEL="$MODEL"
export SMOKE_TP=2
exec python3 /tmp/vllm_msprof_workload.py
SH2
chmod +x /tmp/run_vllm_msprof_workload.sh

cleanup_vllm() {
  pkill -9 -f "VLLM::" || true
  pkill -9 -f "vllm_msprof_workload.py" || true
  pkill -9 -f "multiprocessing.forkserver" || true
  pkill -9 -f "multiprocessing.resource_tracker" || true
}

run_case() {
  name="$1"
  shift
  out="$BASE/$name"
  mkdir -p "$out"
  cleanup_vllm
  echo "[case:$name] start"
  set +e
  timeout 900s msprof --output="$out" "$@" >"$LOG_DIR/$name.log" 2>&1
  rc=$?
  set -e
  echo "$rc" >"$out/exit_code.txt"
  echo "[case:$name] rc=$rc"

  # Collect quick artifact index.
  find "$out" -maxdepth 3 -type d -name 'PROF_*' >"$out/prof_dirs.txt" || true
  find "$out" -maxdepth 4 -type f \( -name 'op_summary*.csv' -o -name 'task_time*.csv' -o -name 'api_statistic*.csv' -o -name 'communication_statistic*.csv' -o -name 'aicpu*.csv' -o -name 'npu_module_mem*.csv' -o -name 'l2_cache*.csv' -o -name 'memory_record*.csv' -o -name 'operator_memory*.csv' -o -name 'static_op_mem*.csv' \) >"$out/key_files.txt" || true
}

# Case 1: <app> 方式（文档方式一）
run_case case1_app \
  --ascendcl=on --runtime-api=on --task-time=l1 --aicpu=on --ai-core=on --hccl=on \
  /tmp/run_vllm_msprof_workload.sh

# Case 2: --application 方式（文档方式二）
run_case case2_application \
  --ascendcl=on --runtime-api=on --task-time=l1 --aicpu=on --ai-core=on \
  --application=/tmp/run_vllm_msprof_workload.sh

# Case 3: 高级参数组合
run_case case3_advanced \
  --ascendcl=on --runtime-api=on --task-time=l1 --aicpu=on --ai-core=on --hccl=on --model-execution=on \
  --aic-mode=sample-based --aic-freq=50 --aic-metrics=PipeUtilization \
  --sys-hardware-mem=on --sys-hardware-mem-freq=20 --l2=on --ge-api=l0 --task-memory=on \
  /tmp/run_vllm_msprof_workload.sh

cleanup_vllm

echo "[summary]"
for c in case1_app case2_application case3_advanced; do
  out="$BASE/$c"
  rc="NA"
  [ -f "$out/exit_code.txt" ] && rc=$(cat "$out/exit_code.txt")
  prof_cnt=0
  [ -f "$out/prof_dirs.txt" ] && prof_cnt=$(grep -c . "$out/prof_dirs.txt" || true)
  key_cnt=0
  [ -f "$out/key_files.txt" ] && key_cnt=$(grep -c . "$out/key_files.txt" || true)
  echo "$c rc=$rc prof_dirs=$prof_cnt key_files=$key_cnt"
done
