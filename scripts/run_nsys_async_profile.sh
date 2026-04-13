#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${IMONITOR_PYTHON_BIN:-${PYTHON_BIN:-python3}}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "python executable not found" >&2
    exit 1
  fi
fi

NSYS_BIN="${NSYS_BIN:-nsys}"
if ! command -v "$NSYS_BIN" >/dev/null 2>&1; then
  echo "nsys not found in PATH" >&2
  exit 1
fi

MODEL="${MODEL:-facebook/opt-125m}"
TP="${TP:-1}"
BACKEND="${BACKEND:-mp}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.05}"
WARMUP_REQ="${WARMUP_REQ:-1}"
PROFILE_REQ="${PROFILE_REQ:-8}"
MAX_INFLIGHT="${MAX_INFLIGHT:-4}"
PROMPT_POOL_SIZE="${PROMPT_POOL_SIZE:-64}"
MAX_TOKENS="${MAX_TOKENS:-12}"
TEMP="${TEMP:-0.0}"
GAP_MEAN_MS="${GAP_MEAN_MS:-20}"
GAP_STD_MS="${GAP_STD_MS:-6}"
GAP_MIN_MS="${GAP_MIN_MS:-0}"
GAP_MAX_MS="${GAP_MAX_MS:-80}"
SEED="${SEED:-20260412}"
PROFILE_REQ_PREFIX="${PROFILE_REQ_PREFIX:-profile-}"
REQ_GROUP_SIZE="${REQ_GROUP_SIZE:-100}"
MAX_API="${MAX_API:-120000}"
MAX_KERN="${MAX_KERN:-120000}"
OUT_DIR="${OUT_DIR:-${PROJECT_ROOT}/runs/nsys/density}"
RUN_TAG="${RUN_TAG:-async_$(date +%Y%m%d_%H%M%S)}"
if [[ $# -ge 1 ]]; then
  RUN_TAG="$1"
fi

mkdir -p "$OUT_DIR"

REP_BASE="${OUT_DIR}/${RUN_TAG}"
REP_FILE="${REP_BASE}.nsys-rep"
REQ_JSON="${REP_BASE}_requests.jsonl"
HTML_OUT="${PROJECT_ROOT}/develop/nsys_timeline_${RUN_TAG}.html"
CHILD_NVTX_LOG="${OUT_DIR}/${RUN_TAG}_childnvtx.log"

export IMONITOR_CHILD_NVTX=1
export IMONITOR_PROFILE_REQ_PREFIX="$PROFILE_REQ_PREFIX"
export IMONITOR_PROFILE_NVTX_NAME="${IMONITOR_PROFILE_NVTX_NAME:-IMONITOR_PROFILE_PHASE}"
if [[ "${IMONITOR_CHILD_NVTX_DEBUG:-0}" == "1" ]]; then
  export IMONITOR_CHILD_NVTX_DEBUG_LOG="$CHILD_NVTX_LOG"
fi

echo "[run_nsys_async_profile] model=${MODEL} tp=${TP} backend=${BACKEND}" >&2
echo "[run_nsys_async_profile] out_base=${REP_BASE}" >&2

"$NSYS_BIN" profile \
  --trace=cuda,nvtx,osrt \
  --trace-fork-before-exec=true \
  --sample=none \
  --capture-range=cudaProfilerApi \
  --capture-range-end=stop \
  --cuda-graph-trace=node \
  --force-overwrite=true \
  -o "$REP_BASE" \
  "$PYTHON_BIN" "$PROJECT_ROOT/scripts/vllm_async_random_profile.py" \
    --model "$MODEL" \
    --tensor-parallel-size "$TP" \
    --distributed-executor-backend "$BACKEND" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --warmup-requests "$WARMUP_REQ" \
    --profile-requests "$PROFILE_REQ" \
    --max-inflight "$MAX_INFLIGHT" \
    --prompt-pool-size "$PROMPT_POOL_SIZE" \
    --max-tokens "$MAX_TOKENS" \
    --temperature "$TEMP" \
    --gap-mean-ms "$GAP_MEAN_MS" \
    --gap-std-ms "$GAP_STD_MS" \
    --gap-min-ms "$GAP_MIN_MS" \
    --gap-max-ms "$GAP_MAX_MS" \
    --profile-request-id-prefix "$PROFILE_REQ_PREFIX" \
    --seed "$SEED" \
    --capture-mode cuda-profiler-api \
    --request-events-out "$REQ_JSON"

"$PYTHON_BIN" "$PROJECT_ROOT/develop/build_nsys_timeline_page.py" \
  --rep "$REP_FILE" \
  --out "$HTML_OUT" \
  --req-events "$REQ_JSON" \
  --req-group-size "$REQ_GROUP_SIZE" \
  --max-api "$MAX_API" \
  --max-kern "$MAX_KERN"

echo "[run_nsys_async_profile] rep=${REP_FILE}" >&2
echo "[run_nsys_async_profile] req_events=${REQ_JSON}" >&2
echo "[run_nsys_async_profile] html=${HTML_OUT}" >&2
if [[ -n "${IMONITOR_CHILD_NVTX_DEBUG_LOG:-}" ]]; then
  echo "[run_nsys_async_profile] child_nvtx_log=${IMONITOR_CHILD_NVTX_DEBUG_LOG}" >&2
fi
