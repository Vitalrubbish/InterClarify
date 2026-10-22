#!/usr/bin/env bash
# Inventory or remove legacy InterClarify assets on the remote login node.
#
# Default is dry-run.  Execution requires both --execute and
# CLEANUP_CONFIRM=YES.  Targets are explicit; the script refuses paths outside
# $HOME and paths under the current keep list.
set -euo pipefail

MODE=dry-run
case "${1:-}" in
  --dry-run|"") MODE=dry-run ;;
  --execute) MODE=execute ;;
  -h|--help)
    printf 'usage: %s [--dry-run|--execute]\n' "$0"
    exit 0
    ;;
  *)
    printf 'unknown argument: %s\n' "$1" >&2
    exit 2
    ;;
esac

HOME_ROOT="$(readlink -f "$HOME")"
LOG="$HOME/cleanup_remote_assets.${MODE}.log"
CONDA_BIN="${CONDA_BIN:-$HOME/miniconda3/bin/conda}"

if [[ "$MODE" == execute && "${CLEANUP_CONFIRM:-}" != "YES" ]]; then
  printf 'refusing --execute without CLEANUP_CONFIRM=YES\n' >&2
  exit 2
fi

log() {
  printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"
}

# Paths that must survive this cleanup.
KEEP_PREFIXES=(
  "$HOME/InterClarify/benchmark"
  "$HOME/InterClarify/assets"
  "$HOME/InterClarify/docs"
  "$HOME/InterClarify/scripts"
  "$HOME/InterClarify/configs"
  "$HOME/InterClarify/tests"
  "$HOME/InterClarify/figures"
  "$HOME/InterClarify/reports"
  "$HOME/InterClarify/.git"
  "$HOME/xtalk/src"
  "$HOME/xtalk/frontend"
  "$HOME/xtalk/docs"
  "$HOME/xtalk/tests"
  "$HOME/xtalk/examples"
  "$HOME/xtalk/scripts"
  "$HOME/xtalk/configs"
  "$HOME/xtalk/.git"
  "$HOME/interclarify-p0-models/modelscope"
  "$HOME/interclarify-p0-models/huggingface"
  "$HOME/interclarify-p0-models/duplexcascade"
  "$HOME/interclarify-asr-selection/models"
  "$HOME/interclarify-tts-selection-20261018/models"
  "$HOME/interclarify-english-integration-20261018-v1/envs"
  "$HOME/interclarify-english-integration-20261018-v6"
  "$HOME/interclarify-runtime-20261021-adopted"
  "$HOME/Full-Duplex-Bench"
  "$HOME/DuplexCascade"
  "$HOME/interclarify-fdb-two-axes-20261021-r4"
  "$HOME/miniconda3/envs/full-duplex-bench"
  "$HOME/miniconda3/envs/interclarify-dev"
)

TARGETS=(
  # xtalk model zoo, caches and logs
  "$HOME/xtalk/models"
  "$HOME/xtalk/.hf_cache"
  "$HOME/xtalk/.modelscope_cache"
  "$HOME/xtalk/logs"
  "$HOME/xtalk/index-tts-vllm"
  "$HOME/xtalk/arXiv-2512.18706v1"

  # old Layer 1 training route
  "$HOME/interclarify-layer1-training-20261019"

  # old selection environments and data
  "$HOME/interclarify-asr-selection/envs"
  "$HOME/interclarify-asr-selection/dataset"
  "$HOME/interclarify-asr-selection/runs"
  "$HOME/interclarify-asr-selection/reports"
  "$HOME/interclarify-asr-selection/logs"
  "$HOME/interclarify-tts-selection-20261018/envs"
  "$HOME/interclarify-tts-selection-20261018/runs"
  "$HOME/interclarify-tts-selection-20261018/logs"
  "$HOME/interclarify-tts-selection-20261018"/export_*

  # retired ASR/TTS stacks
  "$HOME/interclarify-kyutai"
  "$HOME/interclarify-p0-models/kyutai"
  "$HOME/interclarify-x2"
  "$HOME/xtalk-round1"

  # archives and superseded runs
  "$HOME/interclarify-archive"
  "$HOME/interclarify-fdb-two-axes-20261021-r1"
  "$HOME/interclarify-fdb-two-axes-20261021-r2"
  "$HOME/interclarify-fdb-two-axes-20261021-r3"
  "$HOME/interclarify-latency-20261021-r1"
  "$HOME/interclarify-latency-20261021-r2"
  "$HOME/interclarify-kv-diagnosis-20261021-r1"
  "$HOME/interclarify-kv-diagnosis-20261021-r2"
  "$HOME/interclarify-generation-policy-20261021-r1"
  "$HOME/InterClarify/data/runs"

  # temporary files
  "$HOME/ic_p0_tmp"
  "$HOME/logs"
  "$HOME/fdb_env_build.log"
  "$HOME/fdb_env_build.sh"
  "$HOME"/full-duplex-bench.pipfreeze.*
  "$HOME"/interclarify-dev.pipfreeze.*
  "$HOME"/inventory_*.txt
  "$HOME"/inventory_*.sh

  # download caches
  "$HOME/.cache/pip"
  "$HOME/.cache/huggingface"
  "$HOME/.cache/modelscope"
  "$HOME/.cache/puccinialin"
  "$HOME/.cache/vllm"
  "$HOME/.cache/flashinfer"
  "$HOME/.cache/torch"
  "$HOME/.cache/numba"
  "$HOME/.cache/matplotlib"
  "$HOME/.cache/xtalk"
)

CONDA_ENVS=(
  moss-debug
  xtalk-round1-client
  xtalk-round1-moss
  xtalk-round1-tools
  xtalk-round1-turnsense
  xtalk-round1-vllm
  xtalk-x2-asr
)

CONDA_ENV_PATHS=(
  "$HOME/.conda/envs/verify312"
  "$HOME/.conda/envs/xtalk"
)

safe_target() {
  local target="$1" real keep
  real="$(readlink -m "$target")"
  case "$real" in
    "$HOME_ROOT"/*) ;;
    *) log "REFUSE outside home: $target -> $real"; return 1 ;;
  esac
  for keep in "${KEEP_PREFIXES[@]}"; do
    keep="$(readlink -m "$keep")"
    case "$real" in
      "$keep"|"$keep"/*) log "REFUSE keep path: $target -> $real"; return 1 ;;
    esac
  done
  return 0
}

log "mode=$MODE home=$HOME_ROOT log=$LOG"
if [[ "$MODE" == execute ]]; then
  df -h "$HOME_ROOT" | tee -a "$LOG"
else
  printf 'DRY RUN: no files will be removed\n'
  df -h "$HOME_ROOT" | tee -a "$LOG"
fi

for target in "${TARGETS[@]}"; do
  if [[ ! -e "$target" && ! -L "$target" ]]; then
    continue
  fi
  if ! safe_target "$target"; then
    continue
  fi
  if [[ "$MODE" == dry-run ]]; then
    size="$(timeout 20 du -sh -- "$target" 2>/dev/null | cut -f1 || true)"
    log "WOULD REMOVE ${size:-size-timeout} $target"
  else
    log "REMOVE $target"
    rm -rf -- "$target"
  fi
done

for env in "${CONDA_ENVS[@]}"; do
  if ! "$CONDA_BIN" env list | awk '{print $1}' | grep -qx "$env"; then
    continue
  fi
  if [[ "$MODE" == dry-run ]]; then
    log "WOULD REMOVE conda env $env"
  else
    log "REMOVE conda env $env"
    "$CONDA_BIN" env remove -n "$env" -y
  fi
done

for env_path in "${CONDA_ENV_PATHS[@]}"; do
  if [[ ! -d "$env_path" ]]; then
    continue
  fi
  if ! safe_target "$env_path"; then
    continue
  fi
  if [[ "$MODE" == dry-run ]]; then
    log "WOULD REMOVE conda env path $env_path"
  else
    log "REMOVE conda env path $env_path"
    "$CONDA_BIN" env remove -p "$env_path" -y
    rmdir "$env_path" 2>/dev/null || true
  fi
done

if [[ "$MODE" == dry-run ]]; then
  log "WOULD RUN $CONDA_BIN clean -a -y"
else
  log "RUN $CONDA_BIN clean -a -y"
  "$CONDA_BIN" clean -a -y
  log "after:"
  df -h "$HOME_ROOT" | tee -a "$LOG"
fi

log "done mode=$MODE"
