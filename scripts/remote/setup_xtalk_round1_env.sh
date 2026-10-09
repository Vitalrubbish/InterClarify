#!/usr/bin/env bash
# Round-one X-Talk environment preparation (no GPU required).
#
# Creates the round-one roots, clones and pins the four source repositories,
# and creates the five conda environments with their pinned installs.
# Idempotent: existing checkouts must already be at the pinned commit and
# existing conda environments are reused.
#
# Usage:
#   bash scripts/remote/setup_xtalk_round1_env.sh
#
# Optional overrides:
#   XTALK_ROUND1_ROOT, XTALK_ROUND1_MODEL_ROOT, XTALK_ROUND1_ARTIFACT_ROOT
#   XTALK_MOSS_SERVICE_ROOT, XTALK_MOSS_SOURCE_ROOT
#   PIP_INDEX_URL (default: Tsinghua tuna mirror reachable from the cluster)
set -euo pipefail

export XTALK_ROUND1_ROOT="${XTALK_ROUND1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1}"
export XTALK_ROUND1_MODEL_ROOT="${XTALK_ROUND1_MODEL_ROOT:-$XTALK_ROUND1_ROOT/models}"
export XTALK_ROUND1_ARTIFACT_ROOT="${XTALK_ROUND1_ARTIFACT_ROOT:-$XTALK_ROUND1_ROOT/artifacts}"
export XTALK_MOSS_SERVICE_ROOT="${XTALK_MOSS_SERVICE_ROOT:-$XTALK_ROUND1_ROOT/moss-service}"
export XTALK_MOSS_SOURCE_ROOT="${XTALK_MOSS_SOURCE_ROOT:-$XTALK_ROUND1_ROOT/moss-source}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONNOUSERSITE=1
PIP_INDEX="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

# shellcheck disable=SC1091
source "$HOME/miniconda3/etc/profile.d/conda.sh"

mkdir -p "$XTALK_ROUND1_ROOT" "$XTALK_ROUND1_ARTIFACT_ROOT"

clone_pinned() {
  local url="$1" dir="$2" commit="$3"
  if [[ -f "$dir/PINNED_UPSTREAM_COMMIT" ]]; then
    # Tarball import of a pinned upstream commit (fallback when the git
    # protocol is unreachable); PINNED_UPSTREAM_COMMIT carries the upstream
    # SHA and takes precedence over the local import commit.
    local recorded
    recorded="$(cat "$dir/PINNED_UPSTREAM_COMMIT")"
    if [[ "$recorded" != "$commit" ]]; then
      echo "[setup] ERROR: $dir imports $recorded, expected pinned $commit" >&2
      exit 2
    fi
    echo "[setup] $dir imported tree pinned at upstream $commit"
  elif [[ -d "$dir/.git" ]]; then
    local head
    head="$(git -C "$dir" rev-parse HEAD)"
    if [[ "$head" != "$commit" ]]; then
      echo "[setup] ERROR: $dir is at $head, expected pinned $commit" >&2
      exit 2
    fi
    echo "[setup] $dir already pinned at $commit"
  else
    git clone "$url" "$dir"
    git -C "$dir" checkout --detach "$commit"
    echo "[setup] cloned $url at $commit"
  fi
}

echo "[setup] roots under $XTALK_ROUND1_ROOT"
clone_pinned https://github.com/Vitalrubbish/xtalk.git "$XTALK_ROUND1_ROOT/xtalk" 5f0d9959edf1026588246efbed827b078cbb114c
clone_pinned https://github.com/QwenLM/Qwen3-ASR.git "$XTALK_ROUND1_ROOT/qwen-asr" 7c6daf77a2421100f5fb066495372c00129d39ff
clone_pinned https://github.com/xcc-zach/xtalk-moss-tts-realtime.git "$XTALK_MOSS_SERVICE_ROOT" b3306b97f8a64c1a2f25b9803c070ff32ecff6b1
clone_pinned https://github.com/OpenMOSS/MOSS-TTS.git "$XTALK_MOSS_SOURCE_ROOT" 58b20a0d5fcc6766658d50967a90a9d890009a46

create_env() {
  local env="$1"
  if conda env list | awk '{print $1}' | grep -qx "$env"; then
    echo "[setup] conda env $env exists; skipping create"
  else
    conda create -n "$env" python=3.12 pip -y
  fi
}

for env in xtalk-round1-tools xtalk-round1-asr xtalk-round1-moss xtalk-round1-client; do
  create_env "$env"
done

install_env() {
  local env="$1"; shift
  echo "[setup] pip install into $env"
  conda run --no-capture-output -n "$env" python -m pip install --index-url "$PIP_INDEX" "$@"
  echo "[setup] done $env"
}

# The four installs are independent; run them in parallel and wait.  The LLM
# and turn detector reuse the image's base environment (vLLM 0.16.0), so only
# ASR still pins vLLM 0.14.0: qwen_asr is incompatible with 0.16 (see
# Dockerfile.round1).  Do not create an xtalk-round1-vllm environment.
install_env xtalk-round1-tools PyYAML==6.0.3 huggingface_hub &
# tuna's vllm 0.14.0 is an sdist with inconsistent '+cu101' metadata, so vllm
# itself comes from the aliyun mirror (which carries the manylinux wheel).
install_env xtalk-round1-asr --index-url https://mirrors.aliyun.com/pypi/simple/ vllm==0.14.0 &
install_env xtalk-round1-moss --extra-index-url https://download.pytorch.org/whl/cu128 -e "$XTALK_MOSS_SOURCE_ROOT[torch-runtime]" fastapi uvicorn requests soxr websockets &
install_env xtalk-round1-client -e "$XTALK_ROUND1_ROOT/xtalk[example,dev]" PyYAML==6.0.3 aiohttp soundfile soxr &
wait

# qwen-asr pins vllm==0.14.0; install the remaining ASR deps after vllm exists.
install_env xtalk-round1-asr -e "$XTALK_ROUND1_ROOT/qwen-asr[vllm]" soundfile PyYAML==6.0.3

echo "[setup] all environments ready"
