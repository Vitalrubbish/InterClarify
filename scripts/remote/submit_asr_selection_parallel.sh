#!/usr/bin/env bash
# Submit disjoint one-GPU shards and collect their immutable results.
set -euo pipefail
ASR_ROOT="${ASR_SELECTION_ROOT:?set ASR_SELECTION_ROOT}"
ASR_SOURCE="${ASR_SELECTION_SOURCE:?set ASR_SELECTION_SOURCE}"
ASR_RUN="${ASR_SELECTION_RUN:?set ASR_SELECTION_RUN}"
ASR_LIMIT="${ASR_SELECTION_LIMIT:-100}"
ASR_REPEATS="${ASR_SELECTION_REPEATS:-3}"
if [ "${1:-}" = --collect ]; then
  for shard in 0 1 2 3 4; do
    while [ ! -f "$ASR_RUN/shard-$shard/failed_configurations.txt" ]; do
      sleep 15
    done
  done
  "$ASR_ROOT/envs/nemotron_en/bin/python" "$ASR_SOURCE/summarize_asr_selection.py" \
    --run "$ASR_RUN" --output "$ASR_RUN/report" --repeats "$ASR_REPEATS" \
    --samples "$ASR_LIMIT" --sharded
  exit
fi
mkdir -p "$ASR_RUN/submit"
for shard in 0 1 2 3 4; do
  if [ -f "$ASR_RUN/submit/shard-$shard.submitted" ]; then
    echo "Refusing duplicate submission for shard $shard"
    exit 2
  fi
  printf -v command 'ASR_SELECTION_ROOT=%q ASR_SELECTION_SOURCE=%q ASR_SELECTION_RUN=%q ASR_SELECTION_LIMIT=%q ASR_SELECTION_REPEATS=%q ASR_SELECTION_SHARD_INDEX=%q bash %q' \
    "$ASR_ROOT" "$ASR_SOURCE" "$ASR_RUN/shard-$shard" "$ASR_LIMIT" "$ASR_REPEATS" "$shard" \
    "$ASR_SOURCE/run_asr_selection_job.sh"
  vc submit --image "${ASR_SELECTION_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4}" \
    --partition pdgpu-4090 --job "asr-selection-shard-$shard" --num-task 1 \
    --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
    JOB=1:1 "$ASR_RUN/submit/shard-$shard.node.log" --cmd "$command" \
    > "$ASR_RUN/submit/shard-$shard.submitted" 2>&1
  cat "$ASR_RUN/submit/shard-$shard.submitted"
done
nohup bash "$ASR_SOURCE/submit_asr_selection_parallel.sh" --collect \
  > "$ASR_RUN/submit/collect.log" 2>&1 < /dev/null &
echo "Collector PID: $!"
