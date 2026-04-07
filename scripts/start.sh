#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${IMONITOR_PYTHON_BIN:-${PYTHON_BIN:-python3}}"
if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  :
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "python executable not found. Set IMONITOR_PYTHON_BIN." >&2
  exit 1
fi

HOST="${IMONITOR_DAEMON_HOST:-${HOST:-127.0.0.1}}"
PORT="${IMONITOR_DAEMON_PORT:-${PORT:-18180}}"
DB_PATH="${IMONITOR_DAEMON_DB:-${IMONITOR_DB:-${HOME:-/root}/.local/state/imonitor/imonitord.sqlite}}"

mkdir -p "$(dirname "$DB_PATH")"

export IMONITOR_DAEMON_DB="$DB_PATH"
export IMONITOR_DB="$DB_PATH"

echo "[start.sh] project_root=${PROJECT_ROOT}" >&2
echo "[start.sh] starting imonitord on ${HOST}:${PORT} with db=${DB_PATH}" >&2
exec "$PYTHON_BIN" -m imonitor.daemon_cli --db "$DB_PATH" --host "$HOST" --port "$PORT" ${IMONITOR_DAEMON_RELOAD:+--reload}
