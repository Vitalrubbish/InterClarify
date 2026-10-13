#!/usr/bin/env bash
# Replay recorded ASR micro-turns through the released DuplexCascade weights.
#
# The probe is text only: it replays the ASR text a recorded A4 run stored in each
# a4_report.json, so one GPU and no audio, ASR or TTS service are required. It exists to
# test whether the text shape we hand the model (sentence punctuation, casing, fragment
# size) changes the interleave marker it emits.
set -uo pipefail

TASK_ROOT="${INTERCLARIFY_DUPLEX_ROOT:?set independent synced source directory}"
MODEL_HOME="${DUPLEX_MODEL_HOME:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope}"
CHECKPOINT="${DUPLEX_CHECKPOINT:-$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28}"
BASE_MODEL="${DUPLEX_BASE_MODEL:-$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a}"
CONDA_SH="${CONDA_SH:-/opt/conda/etc/profile.d/conda.sh}"
MODEL_ENV="${DUPLEX_MODEL_ENV:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/interclarify-dev}"
CLIENT_ENV="${DUPLEX_CLIENT_ENV:-xtalk-round1-client}"
MODEL_PORT="${DUPLEX_PROBE_MODEL_PORT:-8006}"
TAG="${DUPLEX_PROBE_TAG:-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_DIR="${DUPLEX_PROBE_OUTPUT:-$TASK_ROOT/data/runs/duplex_marker_probe/$TAG}"
REPORT_DIR="${DUPLEX_PROBE_REPORT_DIR:-$TASK_ROOT/reports/duplex_marker_probe/$TAG}"
# Recorded samples to replay. Point this at any directory of per-sample subdirectories
# that contain a4_report.json, e.g. a later FDB v1.0 run.
SAMPLE_ROOT="${DUPLEX_PROBE_SAMPLE_ROOT:?set the recorded sample directory}"
SAMPLES="${DUPLEX_PROBE_SAMPLES:-}"
VARIANTS="${DUPLEX_PROBE_VARIANTS:-raw,strip,strip_lower}"
REPEATS="${DUPLEX_PROBE_REPEATS:-1}"
CLOCK="${DUPLEX_PROBE_CLOCK:-grid}"
PROBE="$TASK_ROOT/scripts/remote/probe_duplex_markers.py"

# shellcheck disable=SC1090
source "$CONDA_SH"
if [ -e "$RUN_DIR" ]; then
  echo "probe output directory already exists: $RUN_DIR" >&2
  exit 2
fi
mkdir -p "$RUN_DIR/services" "$REPORT_DIR"
cd "$TASK_ROOT"
export PYTHONNOUSERSITE=1
export TOKENIZERS_PARALLELISM=false
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/tmp/interclarify-probe-cache}"
mkdir -p "$XDG_CACHE_HOME"

IFS=',' read -r -a JOB_GPUS <<< "${CUDA_VISIBLE_DEVICES:-0}"
PIDS=()
stop_services() {
  local pid
  for pid in "${PIDS[@]}"; do
    kill -TERM -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  done
  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}
trap stop_services EXIT

wait_http() {
  local url="$1" timeout="$2" output="$3" log="$4" pid="$5" elapsed=0
  while ! curl -sf --max-time 5 "$url" > "$output" 2>/dev/null; do
    kill -0 "$pid" 2>/dev/null || return 1
    if [ -f "$log" ] && grep -q 'Traceback (most recent call last)' "$log"; then
      return 1
    fi
    if [ "$elapsed" -ge "$timeout" ]; then
      return 1
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
}

for asset in "$CHECKPOINT" "$BASE_MODEL" "$SAMPLE_ROOT"; do
  [ -e "$asset" ] || { echo "missing asset: $asset" >&2; exit 3; }
done

CUDA_VISIBLE_DEVICES="${JOB_GPUS[0]}" setsid conda run --no-capture-output -p "$MODEL_ENV" \
  python scripts/remote/duplex_model_service.py --checkpoint "$CHECKPOINT" \
  --base-model "$BASE_MODEL" --port "$MODEL_PORT" \
  > "$RUN_DIR/services/duplex_model.log" 2>&1 &
MODEL_PID="$!"
PIDS+=("$MODEL_PID")

if ! wait_http "http://127.0.0.1:$MODEL_PORT/health" 1800 "$RUN_DIR/model_health.json" \
  "$RUN_DIR/services/duplex_model.log" "$MODEL_PID"; then
  echo "model service did not become healthy" >&2
  tail -n 20 "$RUN_DIR/services/duplex_model.log" >&2 || true
  exit 4
fi

PROBE_ARGS=(--sample-root "$SAMPLE_ROOT" --model-url "http://127.0.0.1:$MODEL_PORT" \
  --variants "$VARIANTS" --clock "$CLOCK" --repeats "$REPEATS" \
  --out "$RUN_DIR/duplex_marker_probe.json")
[ -n "$SAMPLES" ] && PROBE_ARGS+=(--samples "$SAMPLES")
RC=0
conda run --no-capture-output -n "$CLIENT_ENV" python "$PROBE" "${PROBE_ARGS[@]}" \
  > "$RUN_DIR/probe.log" 2>&1 || RC=$?

# Archive the compact summary; the per-tick log stays in data/runs.
for evidence in duplex_marker_probe.summary.json model_health.json probe.log; do
  [ -f "$RUN_DIR/$evidence" ] && cp "$RUN_DIR/$evidence" "$REPORT_DIR/"
done
printf '[probe] output=%s reports=%s rc=%s\n' "$RUN_DIR" "$REPORT_DIR" "$RC" | tee "$RUN_DIR/run.log"
exit "$RC"
