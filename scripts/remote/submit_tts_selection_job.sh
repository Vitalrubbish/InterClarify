#!/usr/bin/env bash
# Freeze the node entrypoint and submit one candidate without overwriting prior runs.
set -euo pipefail
ROOT="${TTS_SELECTION_ROOT:?set absolute shared experiment directory}"
BACKEND="${TTS_BACKEND:?choose pocket, kokoro, kyutai or moss}"
OUTPUT="${TTS_SELECTION_OUTPUT:-$ROOT/runs/$BACKEND}"
[[ "$ROOT" = /* && "$OUTPUT" = /* ]] || { echo 'Absolute paths required' >&2; exit 2; }
[ ! -e "$OUTPUT" ] || { echo "Output already exists: $OUTPUT" >&2; exit 2; }
case "$BACKEND" in
  pocket) PARTITION=pdcpu; GPUS=0 ;;
  kokoro|kyutai|moss) PARTITION=pdgpu-4090; GPUS=1 ;;
  *) echo "Unsupported backend: $BACKEND" >&2; exit 2 ;;
esac
TAG="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ROOT/logs" "$ROOT/source/jobs"
ENTRY="$ROOT/source/jobs/$BACKEND-$TAG.sh"
cp "$ROOT/scripts/run_tts_selection_job.sh" "$ENTRY"
printf -v NODE 'TTS_SELECTION_ROOT=%q TTS_SELECTION_OUTPUT=%q TTS_BACKEND=%q bash %q' "$ROOT" "$OUTPUT" "$BACKEND" "$ENTRY"
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition "$PARTITION" --job "tts-selection-$BACKEND" --num-task 1 \
  --cpu-per-task 8 --mem-per-task 32G --gpu-per-task "$GPUS" \
  JOB=1:1 "$ROOT/logs/$BACKEND-$TAG-submit.log" --cmd "$NODE"
