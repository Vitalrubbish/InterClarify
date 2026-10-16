#!/usr/bin/env bash
# Run frozen ASR configurations serially on one allocated GPU.
set -uo pipefail
ASR_ROOT="${ASR_SELECTION_ROOT:?set ASR_SELECTION_ROOT}"
ASR_SOURCE="${ASR_SELECTION_SOURCE:-$ASR_ROOT/source}"
ASR_RUN="${ASR_SELECTION_RUN:?set ASR_SELECTION_RUN}"
ASR_LIMIT="${ASR_SELECTION_LIMIT:-100}"
ASR_REPEATS="${ASR_SELECTION_REPEATS:-3}"
ASR_TIMEOUT="${ASR_SELECTION_TIMEOUT_SECONDS:-3600}"
mkdir -p "$ASR_RUN"
exec > >(tee -a "$ASR_RUN/run.log") 2>&1
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4
if [ ! -f "$ASR_SOURCE.sha256" ] || ! sha256sum -c "$ASR_SOURCE.sha256" > "$ASR_RUN/source_check.txt" 2>&1; then
  echo "Source snapshot verification failed"
  exit 2
fi
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv > "$ASR_RUN/gpu.csv"
sha256sum "$ASR_SOURCE/benchmark_asr_selection.py" "$ASR_ROOT/models.lock.json" \
  "$ASR_ROOT/dataset/manifest.json" > "$ASR_RUN/input.sha256"
cp "$ASR_ROOT/models.lock.json" "$ASR_ROOT/dataset/manifest.json" "$ASR_RUN/"
if [ -f "$ASR_ROOT/dataset/alignments.json" ]; then
  cp "$ASR_ROOT/dataset/alignments.json" "$ASR_RUN/"
  sha256sum "$ASR_ROOT/dataset/alignments.json" >> "$ASR_RUN/input.sha256"
fi
configurations=(nemotron_en:160 nemotron_en:560 nemotron_multi:320 nemotron_multi:560 kyutai:500)
failures=0
for ((repeat=0; repeat<ASR_REPEATS; repeat++)); do
  for ((offset=0; offset<5; offset++)); do
    index=$(( (offset + repeat) % 5 ))
    config="${configurations[$index]}"
    candidate="${config%:*}"
    chunk="${config#*:}"
    out="$ASR_RUN/repeat-$repeat/$candidate-$chunk"
    mkdir -p "$out"
    echo "START repeat=$repeat config=$config utc=$(date -u +%FT%TZ)"
    timeout "$ASR_TIMEOUT" "$ASR_ROOT/envs/$candidate/bin/python" -u "$ASR_SOURCE/benchmark_asr_selection.py" \
      --root "$ASR_ROOT" --candidate "$candidate" --chunk-ms "$chunk" \
      --limit "$ASR_LIMIT" --output "$out" > "$out/process.log" 2>&1
    code=$?
    printf '%s\n' "$code" > "$out/exit_code.txt"
    echo "END repeat=$repeat config=$config exit=$code"
    if [ "$code" -ne 0 ]; then
      failures=$((failures+1))
      tail -20 "$out/process.log"
    fi
  done
done
printf '%s\n' "$failures" > "$ASR_RUN/failed_configurations.txt"
"$ASR_ROOT/envs/nemotron_en/bin/python" "$ASR_SOURCE/summarize_asr_selection.py" \
  --run "$ASR_RUN" --output "$ASR_RUN/report" \
  --repeats "$ASR_REPEATS" --samples "$ASR_LIMIT" || failures=$((failures+1))
exit "$(( failures > 0 ))"
