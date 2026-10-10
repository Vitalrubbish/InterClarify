#!/usr/bin/env bash
# Build (and optionally push) the round-one X-Talk acceptance image.
#
# The image is built directly on the existing xtalk-lean base using named
# BuildKit contexts, so the ~6 GB wheelhouse and the huge model cache under
# $XTALK_ROUND1_ROOT are never sent as ordinary build-context layers.
#
# The MOSS env consumes a *prebuilt* flash-attn wheel from the wheelhouse (see
# Dockerfile.round1), so the image build performs no CUDA compilation.  The
# official flash-attn wheels carry a local version in the filename
# (`2.8.3.post1+cu12torch2.8...`) while their METADATA `Version` is plain
# `2.8.3.post1`; pip >= 24 rejects that as "inconsistent version" and would fall
# back to the sdist (a minutes-long, memory-hungry compile).  To avoid that we
# stage a filename-normalized copy of the wheel whose name matches its metadata.
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

FLASH_WHEEL="$(ls "$WHEELS"/flash_attn-*.whl 2>/dev/null | head -n1 || true)"
if [ -z "$FLASH_WHEEL" ]; then
  echo "[build] missing prebuilt flash-attn wheel in $WHEELS" >&2
  echo "[build] download flash_attn-2.8.3+cu12torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl" >&2
  echo "[build] from https://github.com/Dao-AILab/flash-attention/releases/tag/v2.8.3" >&2
  echo "[build] (byte-identical mirror: https://hf-mirror.com/gueraf/flash-attn-wheels)" >&2
  exit 2
fi

# Normalize `<dist>-<ver>+<local>-<py>-<abi>-<plat>.whl` to
# `<dist>-<ver>-<py>-<abi>-<plat>.whl` so the filename matches the wheel's
# METADATA version and pip accepts it.
if [[ "$(basename "$FLASH_WHEEL")" == *"+"* ]]; then
  base="$(basename "$FLASH_WHEEL")"
  dist="${base%%-*}"
  rest="${base#*-}"
  ver="${rest%%-*}"
  tail="${rest#*-}"
  ver="${ver%%+*}"
  normalized="$WHEELS/${dist}-${ver}-${tail}"
  if [ ! -f "$normalized" ]; then
    echo "[build] normalizing flash wheel -> $(basename "$normalized")"
    cp -f "$FLASH_WHEEL" "$normalized"
  fi
  FLASH_WHEEL="$normalized"
fi

echo "[build] image=$IMAGE"
echo "[build] contexts: wheels=$WHEELS qwen-asr=$QWEN_ASR moss-source=$MOSS_SOURCE xtalk=$XTALK"
echo "[build] flash-attn wheel: $FLASH_WHEEL"

# This host's docker CLI returns exit code 0 even when BuildKit reports
# "ERROR: failed to solve" (see the wrapper), so we cannot trust the exit
# status alone: capture the log and treat the build as failed if it contains
# the BuildKit error marker or the image tag is missing afterwards.
BUILD_LOG="$(mktemp -t build_round1.XXXXXX.log)"
set +e
DOCKER_BUILDKIT=1 docker build -f "$REPO_ROOT/scripts/remote/Dockerfile.round1" \
  --build-context "wheels=$WHEELS" \
  --build-context "qwen-asr=$QWEN_ASR" \
  --build-context "moss-source=$MOSS_SOURCE" \
  --build-context "xtalk=$XTALK" \
  -t "$IMAGE" \
  "$REPO_ROOT" 2>&1 | tee "$BUILD_LOG"
rc="${PIPESTATUS[0]}"
set -e

if [ "$rc" != "0" ] || grep -q "ERROR: failed to solve" "$BUILD_LOG" \
  || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "[build] docker build failed (rc=$rc); full log: $BUILD_LOG" >&2
  exit 1
fi

echo "[build] built $IMAGE (log: $BUILD_LOG)"

if [ "$PUSH" = "1" ]; then
  docker push "$IMAGE"
  echo "[build] pushed $IMAGE"
fi
