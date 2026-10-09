#!/usr/bin/env bash
# Launch one service using the round-one model lock and conda configuration.
set -euo pipefail

ROUND1_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${XTALK_ROUND1_MODEL_ROOT:?Set the directory containing models.lock.json}"
exec conda run --no-capture-output -n xtalk-round1-tools python \
  "$ROUND1_SCRIPT_DIR/run_xtalk_round1.py" \
  --model-root "$XTALK_ROUND1_MODEL_ROOT" serve "$@"
