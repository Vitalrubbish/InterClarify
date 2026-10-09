#!/usr/bin/env bash
# Archive round-one environment records and source pins.
#
# Writes pip freeze / conda explicit lists for the five round-one conda
# environments, the resolved model lock, and the pinned source commits into
# $XTALK_ROUND1_ARTIFACT_ROOT/env/.  Run on a node that has the environments;
# GPU/driver evidence is archived separately by the compute-node job.
#
# Usage:
#   bash scripts/remote/archive_xtalk_round1_env.sh
set -euo pipefail

XTALK_ROUND1_ROOT="${XTALK_ROUND1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1}"
XTALK_ROUND1_MODEL_ROOT="${XTALK_ROUND1_MODEL_ROOT:-$XTALK_ROUND1_ROOT/models}"
XTALK_ROUND1_ARTIFACT_ROOT="${XTALK_ROUND1_ARTIFACT_ROOT:-$XTALK_ROUND1_ROOT/artifacts}"
XTALK_MOSS_SERVICE_ROOT="${XTALK_MOSS_SERVICE_ROOT:-$XTALK_ROUND1_ROOT/moss-service}"
XTALK_MOSS_SOURCE_ROOT="${XTALK_MOSS_SOURCE_ROOT:-$XTALK_ROUND1_ROOT/moss-source}"
ENV_DIR="$XTALK_ROUND1_ARTIFACT_ROOT/env"
mkdir -p "$ENV_DIR"

# shellcheck disable=SC1091
source "$HOME/miniconda3/etc/profile.d/conda.sh"

for env in base xtalk-round1-tools xtalk-round1-asr xtalk-round1-moss xtalk-round1-client; do
  conda run -n "$env" python -m pip freeze > "$ENV_DIR/$env.pip.txt"
  conda list -n "$env" --explicit > "$ENV_DIR/$env.conda.txt"
  echo "[archive] $env recorded"
done

cp "$XTALK_ROUND1_MODEL_ROOT/models.lock.json" "$ENV_DIR/models.lock.json"

{
  for repo in xtalk qwen-asr "$XTALK_MOSS_SERVICE_ROOT" "$XTALK_MOSS_SOURCE_ROOT"; do
    dir="$XTALK_ROUND1_ROOT/$repo"
    [[ "$repo" = /* ]] && dir="$repo"
    if [[ -f "$dir/PINNED_UPSTREAM_COMMIT" ]]; then
      echo "$repo upstream $(cat "$dir/PINNED_UPSTREAM_COMMIT") (tarball import)"
    else
      echo "$repo $(git -C "$dir" rev-parse HEAD)"
    fi
  done
} > "$ENV_DIR/source_commits.txt"

echo "[archive] environment records in $ENV_DIR"
