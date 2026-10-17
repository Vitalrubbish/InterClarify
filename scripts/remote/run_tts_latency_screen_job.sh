#!/usr/bin/env bash
# Run the opt-in TTS screen inside one allocated 4090 job.
set -euo pipefail
TASK_ROOT="${TTS_TASK_ROOT:?set independent checkout}"
OUTPUT="${TTS_OUTPUT:?set new output directory}"
ROUND1="${XTALK_ROUND1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1}"
source "${CONDA_SH:-/opt/conda/etc/profile.d/conda.sh}"
cd "$TASK_ROOT"
[ ! -e "$OUTPUT" ] || { echo 'Output already exists' >&2; exit 2; }
mkdir -p "${OUTPUT}.preflight"
export PYTHONNOUSERSITE=1 TOKENIZERS_PARALLELISM=false
export PYTHONPATH="$ROUND1/xtalk/src:$TASK_ROOT/scripts/remote"
export XTALK_ROUND1_ROOT="$ROUND1"
export XTALK_MOSS_SOURCE_ROOT="$ROUND1/moss-source" XTALK_MOSS_SERVICE_ROOT="$ROUND1/moss-service"
export XTALK_TTS_METRICS=0 XTALK_TTS_TRACE= XTALK_TTS_LOCAL_COMPILE=off XTALK_TTS_LOCAL_ATTN=upstream
export XTALK_TTS_EARLY_COMPILE=0 XTALK_TTS_GENERATION_BATCH_FRAMES=0
export XTALK_TTS_PREFILL_TEXT_TOKENS=0 XTALK_TTS_PREFILL_MAX_WAIT_MS=0
conda run --no-capture-output -n xtalk-round1-moss python scripts/remote/run_xtalk_round1.py \
  --model-root "$ROUND1/models" check-deps --role tts > "${OUTPUT}.preflight/dependencies.json" 2>&1
PYTHONPATH="$ROUND1/moss-source/moss_tts_realtime:$PYTHONPATH" \
  conda run --no-capture-output -n xtalk-round1-moss python -m unittest discover -s tests -p 'test_*tts*.py' -q \
  > "${OUTPUT}.preflight/component_tests.log" 2>&1
ONLY_ARGS=()
if [ -n "${TTS_ONLY_ARMS:-}" ]; then
  read -r -a SELECTED <<< "$TTS_ONLY_ARMS"
  ONLY_ARGS=(--only "${SELECTED[@]}")
fi
set +e
conda run --no-capture-output -n xtalk-round1-client python scripts/remote/tts_latency_experiments.py \
  --task-root "$TASK_ROOT" --output "$OUTPUT" --round1-root "$ROUND1" \
  --model-root "$ROUND1/models" --reference "$ROUND1/audio/reference.wav" "${ONLY_ARGS[@]}"
rc=$?
if [ -d "$OUTPUT" ]; then
  cp "${OUTPUT}.preflight/dependencies.json" "${OUTPUT}.preflight/component_tests.log" "$OUTPUT/"
  printf '%s\n' "$rc" > "$OUTPUT/exit_code.txt"
fi
exit "$rc"
