#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKLOAD_PY="$ROOT_DIR/workload_vllm_8npu.py"
OUT_BASE="${OUT_BASE:-$ROOT_DIR/out/msprof_smoke}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
LOCAL_OUT="$OUT_BASE/$RUN_ID"

CONTAINER_NAME="${CONTAINER_NAME:-}"
MODEL_PATH="${MODEL_PATH:-}"
SMOKE_TP="${SMOKE_TP:-2}"
SMOKE_PP="${SMOKE_PP:-1}"
SMOKE_VISIBLE_DEVICES="${SMOKE_VISIBLE_DEVICES:-}"
SMOKE_MAX_MODEL_LEN="${SMOKE_MAX_MODEL_LEN:-1024}"
SMOKE_MAX_TOKENS="${SMOKE_MAX_TOKENS:-32}"
SMOKE_BATCH_SIZE="${SMOKE_BATCH_SIZE:-1}"
SMOKE_ROUNDS="${SMOKE_ROUNDS:-1}"
SMOKE_TRUST_REMOTE_CODE="${SMOKE_TRUST_REMOTE_CODE:-off}"
SMOKE_HF_OVERRIDES_JSON="${SMOKE_HF_OVERRIDES_JSON:-}"
SMOKE_TEMPERATURE="${SMOKE_TEMPERATURE:-0.0}"
SMOKE_PROMPT="${SMOKE_PROMPT:-Explain the purpose of msprof in one sentence.}"
TARGET_PROGRAM="${TARGET_PROGRAM:-}"
TARGET_SCRIPT="${TARGET_SCRIPT:-}"
TARGET_ARGS="${TARGET_ARGS:-}"
TARGET_COMMAND="${TARGET_COMMAND:-}"
MSPROF_TIMEOUT_SECONDS="${MSPROF_TIMEOUT_SECONDS:-1200}"
KEEP_REMOTE="${KEEP_REMOTE:-0}"

MSPROF_ASCENDCL="${MSPROF_ASCENDCL:-on}"
MSPROF_RUNTIME_API="${MSPROF_RUNTIME_API:-on}"
MSPROF_TASK_TIME="${MSPROF_TASK_TIME:-l1}"
MSPROF_AICPU="${MSPROF_AICPU:-on}"
MSPROF_AI_CORE="${MSPROF_AI_CORE:-on}"
MSPROF_HCCL="${MSPROF_HCCL:-on}"
MSPROF_MODEL_EXECUTION="${MSPROF_MODEL_EXECUTION:-on}"
MSPROF_AIC_MODE="${MSPROF_AIC_MODE:-sample-based}"
MSPROF_AIC_FREQ="${MSPROF_AIC_FREQ:-50}"
MSPROF_AIC_METRICS="${MSPROF_AIC_METRICS:-PipeUtilization}"
MSPROF_TYPE="${MSPROF_TYPE:-db}"
MSPROF_SYS_HARDWARE_MEM="${MSPROF_SYS_HARDWARE_MEM:-on}"
MSPROF_SYS_HARDWARE_MEM_FREQ="${MSPROF_SYS_HARDWARE_MEM_FREQ:-20}"
MSPROF_L2="${MSPROF_L2:-on}"
MSPROF_GE_API="${MSPROF_GE_API:-l0}"
MSPROF_TASK_MEMORY="${MSPROF_TASK_MEMORY:-on}"

resolve_container() {
  if [ -n "$CONTAINER_NAME" ]; then
    echo "$CONTAINER_NAME"
    return 0
  fi
  local picked
  picked=$(docker ps --format '{{.Names}}\t{{.Image}}' | awk '$2 ~ /vllm-ascend/ {print $1; exit}')
  if [ -z "$picked" ]; then
    echo "[error] no running vllm-ascend container found; set CONTAINER_NAME explicitly" >&2
    return 1
  fi
  echo "$picked"
}

resolve_visible_devices() {
  if [ -n "$SMOKE_VISIBLE_DEVICES" ]; then
    echo "$SMOKE_VISIBLE_DEVICES"
    return 0
  fi

  local need
  need=$((SMOKE_TP * SMOKE_PP))
  if [ "$need" -le 0 ]; then
    echo "[error] invalid TP/PP: tp=$SMOKE_TP pp=$SMOKE_PP" >&2
    return 1
  fi

  mapfile -t free_ids < <(npu-smi info | sed -n 's/.*No running processes found in NPU \([0-9]\+\).*/\1/p')
  if [ "${#free_ids[@]}" -lt "$need" ]; then
    echo "[error] not enough free NPUs: need=$need, free=${#free_ids[@]}" >&2
    echo "[error] free_ids=${free_ids[*]}" >&2
    return 1
  fi

  local picked=("${free_ids[@]:0:$need}")
  local joined
  joined=$(IFS=,; echo "${picked[*]}")
  echo "$joined"
}

CONTAINER_NAME="$(resolve_container)"
SMOKE_VISIBLE_DEVICES="$(resolve_visible_devices)"
REMOTE_ROOT="/tmp/ascend_msprof_smoke_${RUN_ID}"
REMOTE_OUT="$REMOTE_ROOT/out"

mkdir -p "$LOCAL_OUT"

tmp_runner="$(mktemp)"
cleanup_local() {
  rm -f "$tmp_runner"
}
trap cleanup_local EXIT

cat > "$tmp_runner" <<'RSH'
#!/usr/bin/env sh
set -eu

: "${REMOTE_ROOT:?REMOTE_ROOT is required}"
REMOTE_OUT="$REMOTE_ROOT/out"
mkdir -p "$REMOTE_OUT"

if [ -z "${MODEL_PATH:-}" ]; then
  MODEL_PATH=$(find /data/models/models--Qwen--Qwen3-8B/snapshots -maxdepth 1 -mindepth 1 -type d | head -n 1 || true)
fi

if [ -z "${MODEL_PATH:-}" ]; then
  echo "[error] cannot resolve MODEL_PATH" >"$REMOTE_OUT/msprof.log"
  echo "2" >"$REMOTE_OUT/exit_code.txt"
  exit 2
fi

if [ -n "${SMOKE_VISIBLE_DEVICES:-}" ]; then
  export ASCEND_RT_VISIBLE_DEVICES="$SMOKE_VISIBLE_DEVICES"
  export ASCEND_VISIBLE_DEVICES="$SMOKE_VISIBLE_DEVICES"
  export NPU_VISIBLE_DEVICES="$SMOKE_VISIBLE_DEVICES"
fi

if [ -z "${TARGET_PROGRAM:-}" ]; then
  TARGET_PROGRAM="python3"
fi

if [ -z "${TARGET_SCRIPT:-}" ]; then
  TARGET_SCRIPT="$REMOTE_ROOT/workload_vllm_8npu.py"
fi

case "$TARGET_SCRIPT" in
  /*) ;;
  *) TARGET_SCRIPT="$REMOTE_ROOT/$TARGET_SCRIPT" ;;
esac
export TARGET_PROGRAM TARGET_SCRIPT TARGET_ARGS

workload_wrapper="$REMOTE_ROOT/workload_wrapper.sh"
cat >"$workload_wrapper" <<'EOF'
#!/usr/bin/env sh
set -eu
REMOTE_OUT="$REMOTE_ROOT/out"
mkdir -p "$REMOTE_OUT"
export VLLM_PLUGINS=ascend
export ASCEND_RT_VISIBLE_DEVICES="$SMOKE_VISIBLE_DEVICES"
export ASCEND_VISIBLE_DEVICES="$SMOKE_VISIBLE_DEVICES"
export NPU_VISIBLE_DEVICES="$SMOKE_VISIBLE_DEVICES"
export SMOKE_MODEL="$MODEL_PATH"
export SMOKE_TP="$SMOKE_TP"
export SMOKE_PP="$SMOKE_PP"
export SMOKE_MAX_MODEL_LEN="$SMOKE_MAX_MODEL_LEN"
export SMOKE_MAX_TOKENS="$SMOKE_MAX_TOKENS"
export SMOKE_BATCH_SIZE="$SMOKE_BATCH_SIZE"
export SMOKE_ROUNDS="$SMOKE_ROUNDS"
export SMOKE_TRUST_REMOTE_CODE="$SMOKE_TRUST_REMOTE_CODE"
export SMOKE_HF_OVERRIDES_JSON="$SMOKE_HF_OVERRIDES_JSON"
export SMOKE_TEMPERATURE="$SMOKE_TEMPERATURE"
export SMOKE_PROMPT="$SMOKE_PROMPT"
export SMOKE_OUTPUT_JSON="$REMOTE_OUT/workload_result.json"
export TARGET_PROGRAM="$TARGET_PROGRAM"
export TARGET_SCRIPT="$TARGET_SCRIPT"
export TARGET_ARGS="$TARGET_ARGS"
export TARGET_COMMAND="$TARGET_COMMAND"

if [ -n "${TARGET_COMMAND:-}" ]; then
  exec /bin/sh -lc "$TARGET_COMMAND"
fi

if [ -n "${TARGET_ARGS:-}" ]; then
  # shellcheck disable=SC2086
  exec "$TARGET_PROGRAM" "$TARGET_SCRIPT" $TARGET_ARGS
fi

exec "$TARGET_PROGRAM" "$TARGET_SCRIPT"
EOF
chmod +x "$workload_wrapper"

set +e
timeout "${MSPROF_TIMEOUT_SECONDS}s" \
  msprof \
  --output="$REMOTE_OUT" \
  --ascendcl="$MSPROF_ASCENDCL" \
  --runtime-api="$MSPROF_RUNTIME_API" \
  --task-time="$MSPROF_TASK_TIME" \
  --aicpu="$MSPROF_AICPU" \
  --ai-core="$MSPROF_AI_CORE" \
  --hccl="$MSPROF_HCCL" \
  --model-execution="$MSPROF_MODEL_EXECUTION" \
  --aic-mode="$MSPROF_AIC_MODE" \
  --aic-freq="$MSPROF_AIC_FREQ" \
  --aic-metrics="$MSPROF_AIC_METRICS" \
  --type="$MSPROF_TYPE" \
  --sys-hardware-mem="$MSPROF_SYS_HARDWARE_MEM" \
  --sys-hardware-mem-freq="$MSPROF_SYS_HARDWARE_MEM_FREQ" \
  --l2="$MSPROF_L2" \
  --ge-api="$MSPROF_GE_API" \
  --task-memory="$MSPROF_TASK_MEMORY" \
  "$workload_wrapper" >"$REMOTE_OUT/msprof.log" 2>&1
rc=$?
set -e

echo "$rc" >"$REMOTE_OUT/exit_code.txt"
find "$REMOTE_OUT" -maxdepth 2 -type d -name "PROF_*" >"$REMOTE_OUT/prof_dirs.txt" || true
find "$REMOTE_OUT" -type f -path "*/mindstudio_profiler_output/*" >"$REMOTE_OUT/key_files.txt" || true

{
  echo "model=$MODEL_PATH"
  echo "tp=$SMOKE_TP"
  echo "pp=$SMOKE_PP"
  echo "max_model_len=$SMOKE_MAX_MODEL_LEN"
  echo "max_tokens=$SMOKE_MAX_TOKENS"
  echo "batch_size=$SMOKE_BATCH_SIZE"
  echo "rounds=$SMOKE_ROUNDS"
  echo "trust_remote_code=$SMOKE_TRUST_REMOTE_CODE"
  echo "hf_overrides_json=$SMOKE_HF_OVERRIDES_JSON"
  echo "temperature=$SMOKE_TEMPERATURE"
  echo "prompt=$SMOKE_PROMPT"
  echo "target_program=$TARGET_PROGRAM"
  echo "target_script=$TARGET_SCRIPT"
  echo "target_args=$TARGET_ARGS"
  echo "target_command=$TARGET_COMMAND"
  echo "visible_devices=$SMOKE_VISIBLE_DEVICES"
  echo "timeout_seconds=$MSPROF_TIMEOUT_SECONDS"
  echo "ascendcl=$MSPROF_ASCENDCL"
  echo "runtime_api=$MSPROF_RUNTIME_API"
  echo "task_time=$MSPROF_TASK_TIME"
  echo "aicpu=$MSPROF_AICPU"
  echo "ai_core=$MSPROF_AI_CORE"
  echo "hccl=$MSPROF_HCCL"
  echo "model_execution=$MSPROF_MODEL_EXECUTION"
  echo "aic_mode=$MSPROF_AIC_MODE"
  echo "aic_freq=$MSPROF_AIC_FREQ"
  echo "aic_metrics=$MSPROF_AIC_METRICS"
  echo "type=$MSPROF_TYPE"
  echo "sys_hardware_mem=$MSPROF_SYS_HARDWARE_MEM"
  echo "sys_hardware_mem_freq=$MSPROF_SYS_HARDWARE_MEM_FREQ"
  echo "l2=$MSPROF_L2"
  echo "ge_api=$MSPROF_GE_API"
  echo "task_memory=$MSPROF_TASK_MEMORY"
} >"$REMOTE_OUT/run_meta.env"

exit "$rc"
RSH
chmod +x "$tmp_runner"

# Stage files into container.
docker exec "$CONTAINER_NAME" /bin/sh -c "mkdir -p '$REMOTE_ROOT'"
docker cp "$WORKLOAD_PY" "$CONTAINER_NAME:$REMOTE_ROOT/workload_vllm_8npu.py"
docker cp "$tmp_runner" "$CONTAINER_NAME:$REMOTE_ROOT/run_msprof_smoke.sh"

set +e
docker exec \
  -e REMOTE_ROOT="$REMOTE_ROOT" \
  -e MODEL_PATH="$MODEL_PATH" \
  -e SMOKE_TP="$SMOKE_TP" \
  -e SMOKE_PP="$SMOKE_PP" \
  -e SMOKE_VISIBLE_DEVICES="$SMOKE_VISIBLE_DEVICES" \
  -e SMOKE_MAX_MODEL_LEN="$SMOKE_MAX_MODEL_LEN" \
  -e SMOKE_MAX_TOKENS="$SMOKE_MAX_TOKENS" \
  -e SMOKE_BATCH_SIZE="$SMOKE_BATCH_SIZE" \
  -e SMOKE_ROUNDS="$SMOKE_ROUNDS" \
  -e SMOKE_TRUST_REMOTE_CODE="$SMOKE_TRUST_REMOTE_CODE" \
  -e SMOKE_HF_OVERRIDES_JSON="$SMOKE_HF_OVERRIDES_JSON" \
  -e SMOKE_TEMPERATURE="$SMOKE_TEMPERATURE" \
  -e SMOKE_PROMPT="$SMOKE_PROMPT" \
  -e TARGET_PROGRAM="$TARGET_PROGRAM" \
  -e TARGET_SCRIPT="$TARGET_SCRIPT" \
  -e TARGET_ARGS="$TARGET_ARGS" \
  -e TARGET_COMMAND="$TARGET_COMMAND" \
  -e MSPROF_TIMEOUT_SECONDS="$MSPROF_TIMEOUT_SECONDS" \
  -e MSPROF_ASCENDCL="$MSPROF_ASCENDCL" \
  -e MSPROF_RUNTIME_API="$MSPROF_RUNTIME_API" \
  -e MSPROF_TASK_TIME="$MSPROF_TASK_TIME" \
  -e MSPROF_AICPU="$MSPROF_AICPU" \
  -e MSPROF_AI_CORE="$MSPROF_AI_CORE" \
  -e MSPROF_HCCL="$MSPROF_HCCL" \
  -e MSPROF_MODEL_EXECUTION="$MSPROF_MODEL_EXECUTION" \
  -e MSPROF_AIC_MODE="$MSPROF_AIC_MODE" \
  -e MSPROF_AIC_FREQ="$MSPROF_AIC_FREQ" \
  -e MSPROF_AIC_METRICS="$MSPROF_AIC_METRICS" \
  -e MSPROF_TYPE="$MSPROF_TYPE" \
  -e MSPROF_SYS_HARDWARE_MEM="$MSPROF_SYS_HARDWARE_MEM" \
  -e MSPROF_SYS_HARDWARE_MEM_FREQ="$MSPROF_SYS_HARDWARE_MEM_FREQ" \
  -e MSPROF_L2="$MSPROF_L2" \
  -e MSPROF_GE_API="$MSPROF_GE_API" \
  -e MSPROF_TASK_MEMORY="$MSPROF_TASK_MEMORY" \
  "$CONTAINER_NAME" /bin/sh "$REMOTE_ROOT/run_msprof_smoke.sh"
rc=$?
set -e

if docker exec "$CONTAINER_NAME" /bin/sh -c "test -d '$REMOTE_OUT'"; then
  docker cp "$CONTAINER_NAME:$REMOTE_OUT/." "$LOCAL_OUT/"
fi

if [ "$KEEP_REMOTE" != "1" ]; then
  docker exec "$CONTAINER_NAME" /bin/sh -c "rm -rf '$REMOTE_ROOT'" || true
fi

ln -sfn "$RUN_ID" "$OUT_BASE/latest"

echo "[msprof-smoke] container=$CONTAINER_NAME"
echo "[msprof-smoke] visible_devices=$SMOKE_VISIBLE_DEVICES"
echo "[msprof-smoke] run_id=$RUN_ID rc=$rc"
echo "[msprof-smoke] out_dir=$LOCAL_OUT"
exit "$rc"
