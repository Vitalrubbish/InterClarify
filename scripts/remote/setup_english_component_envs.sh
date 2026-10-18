#!/usr/bin/env bash
# Clone measured conda environments; never mutate the historical component seeds.
set -euo pipefail
TASK_ROOT="${ENGLISH_COMPONENT_ROOT:?set independent experiment root}"
CONDA_BIN="${ENGLISH_CONDA_BIN:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/bin/conda}"
ASR_SEED="${ENGLISH_ASR_SEED:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-asr-selection/envs/nemotron_en}"
TTS_SEED="${ENGLISH_TTS_SEED:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-tts-selection-20261018/envs/pocket}"
mkdir -p "$TASK_ROOT/envs" "$TASK_ROOT/environment"
for component in asr tts; do
  seed="$ASR_SEED"
  if [ "$component" = tts ]; then seed="$TTS_SEED"; fi
  target="$TASK_ROOT/envs/$component"
  if [ ! -f "$target/conda-meta/history" ]; then
    "$CONDA_BIN" create -y -p "$target" --clone "$seed"
  fi
  "$target/bin/python" -m pip freeze > "$TASK_ROOT/environment/$component.packages.txt"
  "$CONDA_BIN" list -p "$target" --explicit > "$TASK_ROOT/environment/$component.conda.txt"
done
"$TASK_ROOT/envs/asr/bin/python" -c 'from transformers import AutoModelForRNNT,AutoProcessor; import fastapi,uvicorn'
"$TASK_ROOT/envs/tts/bin/python" -c 'from kokoro import KModel,KPipeline; import fastapi,uvicorn,scipy'
