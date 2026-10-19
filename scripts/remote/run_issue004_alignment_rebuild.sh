#!/usr/bin/env bash
# Rebuild Issue 004 data after punctuation-boundary alignment on the debug node.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPECTED_COMMIT="${ISSUE004_SOURCE_COMMIT:?set the reviewed source commit}"
[[ "$(git -C "$ROOT" rev-parse HEAD)" = "$EXPECTED_COMMIT" ]] || {
  echo 'Source commit differs from the reviewed rebuild commit' >&2
  exit 2
}

BASE="/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019"
OUTPUT="$BASE/data/runs/issue004-build-r4"
[[ ! -e "$OUTPUT" ]] || { echo 'Rebuild output already exists' >&2; exit 2; }

export LAYER1_DATA_ROOT="$ROOT"
export LAYER1_TRAINING_ENV="$BASE/envs/training"
export LAYER1_SOURCE_DIR="$BASE/data/ultrachat"
export LAYER1_SOURCE_MANIFEST="$ROOT/reports/layer1_training/issue001-inventory-20261018/data_source_manifest.json"
export LAYER1_TOKENIZER="/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28/tokenizer"
export LAYER1_EXCLUSIONS="$BASE/manifests/exclusions.json"
export LAYER1_DATA_OUTPUT="$OUTPUT"
export LAYER1_DATA_CONFIG="$BASE/manifests/issue004-build-r3-config.yaml"
export LAYER1_DATA_MAX_LENGTH=4096
export LAYER1_DATA_THREADS=1
export LAYER1_DATA_MEMORY_KIB=2097152
export LAYER1_DATA_BUILD_TIMEOUT=1800
export LAYER1_DATA_AUDIT_TIMEOUT=900
export LAYER1_DATA_REVIEW_TIMEOUT=300

ulimit -f 2097152
exec taskset -c 0 nice -n 10 timeout --signal=TERM --kill-after=30 3600 \
  bash "$ROOT/scripts/remote/run_layer1_data.sh"
