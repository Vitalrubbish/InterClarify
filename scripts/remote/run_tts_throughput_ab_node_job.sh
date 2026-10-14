#!/usr/bin/env bash
# Measure MOSS-TTS-Realtime synthesis throughput for the T1/T2 patch arms.
#
# One GPU, one node: the TTS service is restarted once per arm with the arm's
# `XTALK_TTS_LOCAL_COMPILE` / `XTALK_TTS_SAMPLE` settings, then the same fixed
# reply is synthesized twice - `cold` (first session, may pay compilation and
# CUDA-graph capture) and `warm` (steady state).  Every arm writes its own
# service log so the `[moss-patch]` arm summary and the `[tts-metric]` per-turn
# real-time factor can be compared with the client-side numbers.
#
# Environment (set by the submit script):
#   INTERCLARIFY_ROOT, XTALK_ROUND1_ROOT, XTALK_ROUND1_MODEL_ROOT, RUN_TAG,
#   MOSS_ENV, CLIENT_ENV, TTS_PORT, TTS_AB_ARMS, TTS_AB_TEXT,
#   TTS_AB_CHUNK_WORDS, TTS_AB_GAP_SECONDS
set -uo pipefail

TASK_ROOT="${INTERCLARIFY_ROOT:?set INTERCLARIFY_ROOT}"
ROUND1_ROOT="${XTALK_ROUND1_ROOT:?set XTALK_ROUND1_ROOT}"
MODEL_ROOT="${XTALK_ROUND1_MODEL_ROOT:?set XTALK_ROUND1_MODEL_ROOT}"
RUN_TAG="${RUN_TAG:-$(date -u +%Y%m%dT%H%M%SZ)}"
MOSS_ENV="${MOSS_ENV:-xtalk-round1-moss}"
CLIENT_ENV="${CLIENT_ENV:-xtalk-round1-client}"
TTS_PORT="${TTS_PORT:-8004}"
CONFIG="${XTALK_CONFIG:-$TASK_ROOT/configs/xtalk_round1.yaml}"
ROUND1_PY="$TASK_ROOT/scripts/remote/run_xtalk_round1.py"
REFERENCE="${TTS_AB_REFERENCE:-$ROUND1_ROOT/audio/reference.wav}"
CHUNK_WORDS="${TTS_AB_CHUNK_WORDS:-6}"
GAP_SECONDS="${TTS_AB_GAP_SECONDS:-0.02}"
TEXT="${TTS_AB_TEXT:-Setting financial goals is crucial for managing your finances effectively and achieving long-term financial security. Here are several types of financial goals you might consider setting: an emergency fund that covers three to six months of essential expenses, a retirement account funded consistently every month, and a dedicated savings plan for large purchases such as a home or a car. Start with one goal, automate the contribution, and review your progress every quarter.}"
ARMS="${TTS_AB_ARMS:-baseline:off:upstream t2-greedy:off:greedy t2-topk:off:topk t1-inductor:inductor:greedy t1-cudagraph:cudagraph:greedy}"

export XTALK_MOSS_SERVICE_ROOT="${XTALK_MOSS_SERVICE_ROOT:-$ROUND1_ROOT/moss-service}"
export XTALK_MOSS_SOURCE_ROOT="${XTALK_MOSS_SOURCE_ROOT:-$ROUND1_ROOT/moss-source}"

RUN_DIR="$TASK_ROOT/data/runs/tts_throughput_$RUN_TAG"
REPORT_DIR="$TASK_ROOT/reports/tts_throughput/$RUN_TAG"
mkdir -p "$RUN_DIR/logs" "$RUN_DIR/metrics" "$REPORT_DIR"
LOG="$RUN_DIR/run.log"
exec > >(tee -a "$LOG") 2>&1

echo "[tts-ab] tag=$RUN_TAG node=$(hostname) $(date -u +%FT%TZ)"
echo "[tts-ab] arms: $ARMS"

nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv > "$RUN_DIR/gpu.csv" 2>&1 || true
RC=0
conda run -n "$CLIENT_ENV" python -c 'import hashlib,json,pathlib; root=pathlib.Path("'"$TASK_ROOT"'"); m=json.loads((root/"source_manifest.json").read_text()); bad=[n for n,d in m["files"].items() if not (root/n).is_file() or hashlib.sha256((root/n).read_bytes()).hexdigest()!=d]; assert not bad, bad[:5]; print("source_verified", len(m["files"]))' > "$RUN_DIR/source_check.txt" 2>&1 || RC=$?
if [ "$RC" -ne 0 ]; then
  echo "[tts-ab] source manifest mismatch; refusing to measure" | tee "$RUN_DIR/source_check.txt"
  exit 1
fi

wait_http() {
  local url="$1" timeout="$2" pid="$3" elapsed=0
  while ! curl -sf --max-time 5 "$url" > /dev/null 2>&1; do
    kill -0 "$pid" 2>/dev/null || return 1
    [ "$elapsed" -ge "$timeout" ] && return 1
    sleep 5
    elapsed=$((elapsed + 5))
  done
  return 0
}

SERVICE_PID=""
stop_service() {
  if [ -n "$SERVICE_PID" ]; then
    kill -TERM -"$SERVICE_PID" 2>/dev/null || kill "$SERVICE_PID" 2>/dev/null || true
    wait "$SERVICE_PID" 2>/dev/null || true
    SERVICE_PID=""
  fi
}
trap 'stop_service' EXIT

declare -a ARM_SUMMARY=()
for ARM in $ARMS; do
  NAME="${ARM%%:*}"
  REST="${ARM#*:}"
  COMPILE="${REST%%:*}"
  SAMPLE="${REST#*:}"
  echo "[tts-ab] $(date -u +%FT%TZ) arm=$NAME compile=$COMPILE sample=$SAMPLE"
  stop_service

  XTALK_TTS_LOCAL_COMPILE="$COMPILE" \
  XTALK_TTS_SAMPLE="$SAMPLE" \
  XTALK_TTS_METRICS=1 \
    setsid conda run --no-capture-output -n "$MOSS_ENV" \
      env CUDA_VISIBLE_DEVICES=0 PYTHONPATH="$TASK_ROOT/xtalk/src" \
      python "$ROUND1_PY" --config "$CONFIG" --model-root "$MODEL_ROOT" \
      serve tts --gpu-index 0 \
      > "$RUN_DIR/logs/$NAME.service.log" 2>&1 &
  SERVICE_PID=$!

  if ! wait_http "http://127.0.0.1:$TTS_PORT/health" 2400 "$SERVICE_PID"; then
    echo "[tts-ab] arm=$NAME service failed to become healthy"
    ARM_SUMMARY+=("$NAME FAILED")
    tail -20 "$RUN_DIR/logs/$NAME.service.log"
    continue
  fi
  echo "[tts-ab] arm=$NAME service healthy $(date -u +%FT%TZ)"
  grep -aE "\[moss-patch\]" "$RUN_DIR/logs/$NAME.service.log" > "$RUN_DIR/metrics/$NAME.patch.log" || true

  for PHASE in cold warm; do
    OUT="$RUN_DIR/$NAME-$PHASE"
    RC=0
    conda run --no-capture-output -n "$CLIENT_ENV" \
      env PYTHONPATH="$TASK_ROOT/xtalk/src" \
      python "$ROUND1_PY" --config "$CONFIG" --model-root "$MODEL_ROOT" \
      tts-smoke --reference "$REFERENCE" --output "$OUT" \
      --url "http://127.0.0.1:$TTS_PORT" --text "$TEXT" \
      --stream-chunk-words "$CHUNK_WORDS" --gap-seconds "$GAP_SECONDS" \
      > "$RUN_DIR/logs/$NAME-$PHASE.smoke.log" 2>&1 || RC=$?
    echo "[tts-ab] arm=$NAME phase=$PHASE rc=$RC"
  done
  grep -aE "\[tts-metric\]" "$RUN_DIR/logs/$NAME.service.log" > "$RUN_DIR/metrics/$NAME.metric.log" || true
  stop_service
done

conda run --no-capture-output -n "$CLIENT_ENV" \
  python "$TASK_ROOT/scripts/remote/summarize_tts_throughput.py" \
  --run-dir "$RUN_DIR" --report-dir "$REPORT_DIR" --tag "$RUN_TAG" || true

for artifact in tts_throughput.md tts_throughput.json; do
  [ -f "$REPORT_DIR/$artifact" ] && echo "[tts-ab] report: $REPORT_DIR/$artifact"
done
echo "[tts-ab] $(date -u +%FT%TZ) done; run dir $RUN_DIR"
