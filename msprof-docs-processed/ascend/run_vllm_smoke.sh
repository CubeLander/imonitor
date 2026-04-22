#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKLOAD_PY="$ROOT_DIR/workload_vllm_8npu.py"
OUT_BASE="$ROOT_DIR/out/vllm_smoke"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
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
KEEP_REMOTE="${KEEP_REMOTE:-0}"

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
REMOTE_ROOT="/tmp/ascend_vllm_smoke_${RUN_ID}"
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
  echo "[error] cannot resolve MODEL_PATH" >"$REMOTE_OUT/workload.log"
  echo "2" >"$REMOTE_OUT/exit_code.txt"
  exit 2
fi

# Limit NPU visibility to the selected cards.
if [ -n "${SMOKE_VISIBLE_DEVICES:-}" ]; then
  export ASCEND_RT_VISIBLE_DEVICES="$SMOKE_VISIBLE_DEVICES"
  export ASCEND_VISIBLE_DEVICES="$SMOKE_VISIBLE_DEVICES"
  export NPU_VISIBLE_DEVICES="$SMOKE_VISIBLE_DEVICES"
fi

export VLLM_PLUGINS=ascend
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

set +e
python3 "$REMOTE_ROOT/workload_vllm_8npu.py" >"$REMOTE_OUT/workload.log" 2>&1
rc=$?
set -e

echo "$rc" >"$REMOTE_OUT/exit_code.txt"
{
  echo "model=$MODEL_PATH"
  echo "tp=$SMOKE_TP"
  echo "pp=$SMOKE_PP"
  echo "visible_devices=$SMOKE_VISIBLE_DEVICES"
  echo "max_model_len=$SMOKE_MAX_MODEL_LEN"
  echo "max_tokens=$SMOKE_MAX_TOKENS"
  echo "batch_size=$SMOKE_BATCH_SIZE"
  echo "rounds=$SMOKE_ROUNDS"
  echo "trust_remote_code=$SMOKE_TRUST_REMOTE_CODE"
  echo "hf_overrides_json=$SMOKE_HF_OVERRIDES_JSON"
  echo "temperature=$SMOKE_TEMPERATURE"
  echo "prompt=$SMOKE_PROMPT"
} >"$REMOTE_OUT/run_meta.env"

exit "$rc"
RSH
chmod +x "$tmp_runner"

# Stage files into container.
docker exec "$CONTAINER_NAME" /bin/sh -c "mkdir -p '$REMOTE_ROOT'"
docker cp "$WORKLOAD_PY" "$CONTAINER_NAME:$REMOTE_ROOT/workload_vllm_8npu.py"
docker cp "$tmp_runner" "$CONTAINER_NAME:$REMOTE_ROOT/run_vllm_smoke.sh"

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
  "$CONTAINER_NAME" /bin/sh "$REMOTE_ROOT/run_vllm_smoke.sh"
rc=$?
set -e

if docker exec "$CONTAINER_NAME" /bin/sh -c "test -d '$REMOTE_OUT'"; then
  docker cp "$CONTAINER_NAME:$REMOTE_OUT/." "$LOCAL_OUT/"
fi

if [ "$KEEP_REMOTE" != "1" ]; then
  docker exec "$CONTAINER_NAME" /bin/sh -c "rm -rf '$REMOTE_ROOT'" || true
fi

ln -sfn "$RUN_ID" "$OUT_BASE/latest"

echo "[vllm-smoke] container=$CONTAINER_NAME"
echo "[vllm-smoke] visible_devices=$SMOKE_VISIBLE_DEVICES"
echo "[vllm-smoke] run_id=$RUN_ID rc=$rc"
echo "[vllm-smoke] out_dir=$LOCAL_OUT"
exit "$rc"
