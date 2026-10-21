#!/usr/bin/env bash
# Submit the independently frozen original-1k ASR adaptation condition.
set -euo pipefail
ROOT="${LAYER1_ASR_ROOT:?set frozen training worktree}"
BASE=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019
OUTPUT="${LAYER1_ASR_TRAIN_OUTPUT:?set independent output}"
[[ ! -e "$OUTPUT" && -f "$ROOT/configs/layer1_asr_protocol.yaml" ]] || exit 2
mkdir -p "$BASE/submit_logs"
printf -v command 'env LAYER1_TRAIN_ROOT=%q LAYER1_TRAINING_ROOT=%q LAYER1_TRAINING_ENV=%q LAYER1_TRAIN_OUTPUT=%q LAYER1_TRAIN_ARM=ASR LAYER1_TRAIN_CONFIG=%q LAYER1_TRAIN_PROTOCOL=%q LAYER1_TRAIN_DATA=%q timeout --signal=TERM --kill-after=30 28800 bash %q' \
  "$ROOT" "$BASE" "$BASE/envs/training" "$OUTPUT" \
  "$ROOT/configs/layer1_asr_training.yaml" "$ROOT/configs/layer1_asr_protocol.yaml" \
  "$BASE/data/runs/issue077-asr-punctuation-data-r2" "$ROOT/scripts/remote/run_layer1_delayed_training.sh"
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition pdgpu-4090 --job issue078-asr-punctuation-r1 --num-task 1 \
  --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$BASE/submit_logs/issue078-asr-punctuation-r1.log" --cmd "$command"
