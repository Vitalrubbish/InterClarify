#!/usr/bin/env bash
# Submit the frozen original-1k ASR candidate on the historical 25 FDB cases.
set -euo pipefail
ROOT="${LAYER1_FDB_ROOT:?set frozen evaluation checkout}"
OUTPUT="${LAYER1_FDB_OUTPUT:?set independent output}"
BASE=/hpc_stor03/sjtu_home/xuan.zhang
[[ ! -e "$OUTPUT" ]] || exit 2
LOG_ROOT="$BASE/interclarify-layer1-training-20261019/submit_logs"
mkdir -p "$LOG_ROOT"
printf -v command 'env LAYER1_FDB_ROOT=%q LAYER1_FDB_OUTPUT=%q LAYER1_XTALK_ROOT=%q LAYER1_TRAIN_RUN=%q timeout --signal=TERM --kill-after=30 14400 bash %q' \
  "$ROOT" "$OUTPUT" "$BASE/interclarify-fdb-two-axes-20261021-r4/source/xtalk" \
  "$BASE/interclarify-layer1-training-20261019/data/runs/issue078-asr-punctuation-r1" \
  "$ROOT/scripts/remote/run_layer1_fdb.sh"
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition pdgpu-4090 --job issue081-asr-fdb-subset-r1 --num-task 1 \
  --cpu-per-task 16 --mem-per-task 64G --gpu-per-task 2 \
  JOB=1:1 "$LOG_ROOT/issue081-asr-fdb-subset-r1.log" --cmd "$command"
