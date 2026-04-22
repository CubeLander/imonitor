#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_DIR="$REPO_ROOT/analyzer/config"
OUT_DIR="$REPO_ROOT/analyzer/out"

if [ ! -f "$CONFIG_DIR/hprofile.yaml" ]; then
  echo "[error] missing config: $CONFIG_DIR/hprofile.yaml" >&2
  exit 2
fi

echo "[hprofile-smoke] repo_root=$REPO_ROOT"
echo "[hprofile-smoke] config=$CONFIG_DIR/hprofile.yaml"
echo "[hprofile-smoke] out_dir=$OUT_DIR"

cd "$CONFIG_DIR"
PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 -m analyzer.hprofile

latest_run=$(find "$OUT_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f\n' | sort -nr | awk 'NR==1{print $2}')
if [ -z "${latest_run:-}" ]; then
  echo "[hprofile-smoke][warn] no run directory found under $OUT_DIR"
  exit 0
fi

web_index="$OUT_DIR/$latest_run/hprofile_processed/web/index.html"
if [ -f "$web_index" ]; then
  echo "[hprofile-smoke] latest_run=$latest_run"
  echo "[hprofile-smoke] web=$web_index"
else
  echo "[hprofile-smoke][warn] web index not found: $web_index"
fi
