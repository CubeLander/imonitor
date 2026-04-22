#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Stable 2x2 preset:
# - prioritize successful export of msprof_*.db
# - keep task/comm timeline needed by analyzer
# - disable heavyweight metrics that can slow or complicate export
export SMOKE_TP="${SMOKE_TP:-2}"
export SMOKE_PP="${SMOKE_PP:-2}"
export SMOKE_MAX_TOKENS="${SMOKE_MAX_TOKENS:-128}"
export MSPROF_TIMEOUT_SECONDS="${MSPROF_TIMEOUT_SECONDS:-1800}"

export MSPROF_ASCENDCL="${MSPROF_ASCENDCL:-on}"
export MSPROF_RUNTIME_API="${MSPROF_RUNTIME_API:-on}"
export MSPROF_TASK_TIME="${MSPROF_TASK_TIME:-l1}"
export MSPROF_HCCL="${MSPROF_HCCL:-on}"

export MSPROF_AICPU="${MSPROF_AICPU:-off}"
export MSPROF_AI_CORE="${MSPROF_AI_CORE:-off}"
export MSPROF_MODEL_EXECUTION="${MSPROF_MODEL_EXECUTION:-off}"
export MSPROF_TYPE="${MSPROF_TYPE:-db}"
export MSPROF_SYS_HARDWARE_MEM="${MSPROF_SYS_HARDWARE_MEM:-off}"
export MSPROF_L2="${MSPROF_L2:-off}"
export MSPROF_TASK_MEMORY="${MSPROF_TASK_MEMORY:-off}"
export MSPROF_GE_API="${MSPROF_GE_API:-off}"

exec "$SCRIPT_DIR/run_msprof_vllm_smoke.sh" "$@"
