#!/usr/bin/env bash
# Build (and optionally push) the round-one X-Talk acceptance image.
#
# The image is built directly on the existing xtalk:v0.17 base using named
# BuildKit contexts, so the ~6 GB wheelhouse and the huge model cache under
# $XTALK_ROUND1_ROOT are never sent as ordinary build-context layers.
#
# Usage:
#   bash scripts/remote/build_xtalk_round1_image.sh
#   PUSH=1 bash scripts/remote/build_xtalk_round1_image.sh
#
# Overrides:
#   XTALK_ROUND1_ROOT, XTALK_ROUND1_IMAGE, PUSH
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROUND1_ROOT="${XTALK_ROUND1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1}"
IMAGE="${XTALK_ROUND1_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.2}"
PUSH="${PUSH:-0}"

WHEELS="$ROUND1_ROOT/wheels"
QWEN_ASR="$ROUND1_ROOT/qwen-asr"
MOSS_SOURCE="$ROUND1_ROOT/moss-source"
XTALK="$ROUND1_ROOT/xtalk"

for path in "$WHEELS" "$QWEN_ASR" "$MOSS_SOURCE" "$XTALK"; do
  if [ ! -d "$path" ]; then
    echo "[build] missing build context: $path" >&2
    exit 2
  fi
done

echo "[build] image=$IMAGE"
echo "[build] contexts: wheels=$WHEELS qwen-asr=$QWEN_ASR moss-source=$MOSS_SOURCE xtalk=$XTALK"

if ! DOCKER_BUILDKIT=1 docker build -f "$REPO_ROOT/scripts/remote/Dockerfile.round1" \
  --build-context "wheels=$WHEELS" \
  --build-context "qwen-asr=$QWEN_ASR" \
  --build-context "moss-source=$MOSS_SOURCE" \
  --build-context "xtalk=$XTALK" \
  -t "$IMAGE" \
  "$REPO_ROOT"; then
  echo "[build] docker build failed" >&2
  exit 1
fi

echo "[build] built $IMAGE"

if [ "$PUSH" = "1" ]; then
  docker push "$IMAGE"
  echo "[build] pushed $IMAGE"
fi
