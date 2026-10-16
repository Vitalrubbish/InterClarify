#!/usr/bin/env bash
# Prepare isolated conda environments without changing the active runtime.
set -euo pipefail
ASR_ROOT="${ASR_SELECTION_ROOT:?set ASR_SELECTION_ROOT}"
ASR_CONDA="${ASR_SELECTION_CONDA:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/bin/conda}"
ASR_SEED="${ASR_SELECTION_SEED:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/xtalk-x2-asr}"
mkdir -p "$ASR_ROOT/envs" "$ASR_ROOT/logs"
export PYTHONNOUSERSITE=1
for candidate in nemotron_en nemotron_multi kyutai; do
  target="$ASR_ROOT/envs/$candidate"
  if [ ! -f "$target/conda-meta/history" ]; then
    "$ASR_CONDA" create -y -p "$target" --clone "$ASR_SEED"
  fi
  "$target/bin/python" -m pip install 'whisper-normalizer==0.1.12'
  if [ "$candidate" = kyutai ]; then
    "$target/bin/python" -m pip install --no-deps 'moshi==0.2.11' 'sphn==0.2.1' 'julius==0.2.7' 'einops==0.8.1' 'sentencepiece==0.2.1'
    "$target/bin/python" -c 'import moshi.models,sphn,julius'
  else
    "$target/bin/python" -c 'from transformers import AutoModelForRNNT,AutoProcessor; print("RNNT streaming imports ready")'
  fi
  "$target/bin/python" -m pip freeze > "$ASR_ROOT/logs/$candidate.pipfreeze.txt"
done
printf 'Environment setup complete\n'
