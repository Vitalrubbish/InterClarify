#!/usr/bin/env bash
# Measure MOSS-TTS-Realtime synthesis throughput for the T1/T2 patch arms.
#
# One GPU, one node: the TTS service is restarted once per arm with the arm's
# `XTALK_TTS_LOCAL_COMPILE` / `XTALK_TTS_SAMPLE` settings, then the same fixed
# reply is synthesized twice - `cold` (first session, may pay compilation and
# CUDA-graph capture) and `warm` (steady state).  Every arm writes its own
# service log so the `[moss-patch]` arm summary and the `[tts-metric]` slices can
# be compared with the client-side numbers.
#
# Arm syntax: `name:compile:sample[:flags]`, flags comma separated:
#   sdpa       set XTALK_TTS_LOCAL_ATTN=sdpa: the local transformer runs sdpa on a
#              static local cache instead of flash-attn, which is what makes the
#              codebook loop compilable at all (flash-attn branches on tensor
#              values, and fullgraph=True cannot trace that)
#   profile    also set XTALK_TTS_PROFILE so the patch dumps a torch.profiler
#              kernel table for the first frames of every turn
#   warm-only  skip the cold phase (profiling and compilation dominate cold)
# Each arm gets its own port, so a service that is still shutting down from the
# previous arm can neither answer the health probe nor block the next bind.
#
# Environment (set by the submit script):
#   INTERCLARIFY_ROOT, XTALK_ROUND1_ROOT, XTALK_ROUND1_MODEL_ROOT, RUN_TAG,
#   MOSS_ENV, CLIENT_ENV, TTS_PORT, TTS_AB_ARMS, TTS_AB_TEXT,
#   TTS_AB_CHUNK_WORDS, TTS_AB_GAP_SECONDS, TTS_AB_RESUME
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
# Each T1/T2 arm changes exactly one lever.  The default table targets the
# measured bottleneck: eager launches dominate the frame wall clock (a frame is
# 633 kernels / ~24ms of device time against ~82ms of wall clock), so it isolates
# the attention/cache switch (t1-sdpa) from the two compile backends, and adds a
# profiling copy of the compiled arm for the device-side split.  Sampling arms
# (t2-greedy / t2-topk) are worth ~5% and stay available through TTS_AB_ARMS.
ARMS="${TTS_AB_ARMS:-baseline:off:upstream t1-sdpa:off:upstream:sdpa t1-sdpa-cudagraph:cudagraph:upstream:sdpa t1-sdpa-inductor:inductor:upstream:sdpa t1-sdpa-profile:cudagraph:upstream:sdpa,profile,warm-only}"

# `TTS_AB_RESUME=1` reuses the artifacts of arms that already finished, so a job
# killed mid-sweep (the compiler runs inside the smoke of the first compiled arm,
# and inductor code generation is the memory peak of the whole run) can be
# continued without paying for the arms that are already measured.
RESUME="${TTS_AB_RESUME:-0}"

# Compilation happens in the service process; one codegen worker keeps the peak
# resident set of a 600-op graph well below the pod limit, and expandable
# segments keep the CUDA-graph capture from fragmenting.
export TORCHINDUCTOR_COMPILE_THREADS="${TTS_AB_INDUCTOR_THREADS:-1}"
export PYTORCH_CUDA_ALLOC_CONF="${TTS_AB_ALLOC_CONF:-expandable_segments:True}"

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

port_answers() {
  curl -sf --max-time 5 "$1" > /dev/null 2>&1
}

# Resource snapshots survive on the shared filesystem even when the pod is
# killed, so a run that dies inside a compiler shows what it was consuming.
snapshot_resources() {
  local name="$1" phase="$2"
  {
    echo "# $(date -u +%FT%TZ) arm=$name phase=$phase"
    free -m | sed -n '1,3p'
    nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
    ps -o pid,rss,args -C python --sort=-rss 2>/dev/null | head -3
  } >> "$RUN_DIR/metrics/$name.resources.txt" 2>&1 || true
}

# A stale service from the previous arm may still hold its port for a while after
# SIGTERM: wait for it to stop answering before the next arm starts.
wait_port_free() {
  local url="$1" deadline=$(( $(date +%s) + 120 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    port_answers "$url" || return 0
    sleep 2
  done
  echo "[tts-ab] warning: $url still answers after 120s; continuing"
  return 1
}

SERVICE_PID=""
stop_service() {
  [ -n "$SERVICE_PID" ] || return 0
  kill -TERM -"$SERVICE_PID" 2>/dev/null || kill -TERM "$SERVICE_PID" 2>/dev/null || true
  local deadline=$(( $(date +%s) + 20 ))
  while kill -0 "$SERVICE_PID" 2>/dev/null && [ "$(date +%s)" -lt "$deadline" ]; do
    sleep 1
  done
  kill -KILL -"$SERVICE_PID" 2>/dev/null || true
  wait "$SERVICE_PID" 2>/dev/null || true
  SERVICE_PID=""
}

# Ready means: this process is alive, it finished loading the model, and its own
# port answered twice in a row. A leftover service cannot satisfy that because
# every arm has its own port.
wait_healthy() {
  local url="$1" log="$2" pid="$3" timeout="$4" deadline ok=0
  deadline=$(( $(date +%s) + timeout ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "[tts-ab] service process $pid exited before becoming healthy"
      return 1
    fi
    if grep -qa "\[warmup\] Failed:" "$log" 2>/dev/null; then
      echo "[tts-ab] service reported a backend load failure"
      return 1
    fi
    if grep -qa "\[warmup\] Backend loaded" "$log" 2>/dev/null && port_answers "$url"; then
      ok=$(( ok + 1 ))
      if [ "$ok" -ge 2 ]; then
        return 0
      fi
      sleep 2
    else
      ok=0
      sleep 5
    fi
  done
  return 1
}

collect_arm_logs() {
  local name="$1"
  grep -aE "\[moss-patch\]" "$RUN_DIR/logs/$name.service.log" > "$RUN_DIR/metrics/$name.patch.log" || true
  grep -aE "\[tts-metric\]" "$RUN_DIR/logs/$name.service.log" > "$RUN_DIR/metrics/$name.metric.log" || true
}

declare -a ARM_SUMMARY=()
ARM_INDEX=0
for ARM in $ARMS; do
  NAME="${ARM%%:*}"
  REST="${ARM#*:}"
  COMPILE="${REST%%:*}"
  REST="${REST#*:}"
  SAMPLE="${REST%%:*}"
  FLAGS="${REST#*:}"
  [ "$FLAGS" = "$REST" ] && FLAGS=""
  PROFILE=""
  LOCAL_ATTN="upstream"
  PHASES="cold warm"
  case ",$FLAGS," in
    *,profile,*) PROFILE="$RUN_DIR/metrics/$NAME.profile.txt" ;;
  esac
  case ",$FLAGS," in
    *,sdpa,*) LOCAL_ATTN="sdpa" ;;
  esac
  case ",$FLAGS," in
    *,warm-only,*) PHASES="warm" ;;
  esac

  ARM_INDEX=$(( ARM_INDEX + 1 ))
  ARM_PORT=$(( TTS_PORT + ARM_INDEX ))
  ARM_URL="http://127.0.0.1:$ARM_PORT"
  if [ "$RESUME" = "1" ] && [ -f "$RUN_DIR/$NAME-warm/tts_report.json" ]; then
    echo "[tts-ab] arm=$NAME resume: warm artifact already present, skipping"
    ARM_SUMMARY+=("$NAME skipped")
    continue
  fi
  echo "[tts-ab] $(date -u +%FT%TZ) arm=$NAME compile=$COMPILE sample=$SAMPLE local_attn=$LOCAL_ATTN flags='${FLAGS}' port=$ARM_PORT"

  XTALK_TTS_LOCAL_COMPILE="$COMPILE" \
  XTALK_TTS_LOCAL_ATTN="$LOCAL_ATTN" \
  XTALK_TTS_SAMPLE="$SAMPLE" \
  XTALK_TTS_METRICS=1 \
  XTALK_TTS_PROFILE="$PROFILE" \
    setsid conda run --no-capture-output -n "$MOSS_ENV" \
      env CUDA_VISIBLE_DEVICES=0 PYTHONPATH="$TASK_ROOT/xtalk/src" PYTHONUNBUFFERED=1 \
      python "$ROUND1_PY" --config "$CONFIG" --model-root "$MODEL_ROOT" \
      serve tts --gpu-index 0 --port "$ARM_PORT" \
      > "$RUN_DIR/logs/$NAME.service.log" 2>&1 &
  SERVICE_PID=$!

  if ! wait_healthy "$ARM_URL/health" "$RUN_DIR/logs/$NAME.service.log" "$SERVICE_PID" 2400; then
    echo "[tts-ab] arm=$NAME ENV-FAILED: service never became healthy on port $ARM_PORT"
    tail -30 "$RUN_DIR/logs/$NAME.service.log"
    collect_arm_logs "$NAME"
    stop_service
    wait_port_free "$ARM_URL/health" || true
    ARM_SUMMARY+=("$NAME ENV-FAILED")
    if [ "$ARM_INDEX" -eq 1 ]; then
      echo "[tts-ab] the first arm failed; the node cannot measure anything, aborting"
      break
    fi
    continue
  fi
  echo "[tts-ab] arm=$NAME service healthy $(date -u +%FT%TZ)"
  snapshot_resources "$NAME" "healthy"

  ARM_RC=0
  for PHASE in $PHASES; do
    OUT="$RUN_DIR/$NAME-$PHASE"
    RC=0
    # A resumed arm may still hold the phase directory of the killed attempt;
    # the smoke refuses to write into an existing directory.
    rm -rf "$OUT"
    snapshot_resources "$NAME" "$PHASE-start"
    conda run --no-capture-output -n "$CLIENT_ENV" \
      env PYTHONPATH="$TASK_ROOT/xtalk/src" PYTHONUNBUFFERED=1 \
      python "$ROUND1_PY" --config "$CONFIG" --model-root "$MODEL_ROOT" \
      tts-smoke --reference "$REFERENCE" --output "$OUT" \
      --url "$ARM_URL" --text "$TEXT" \
      --stream-chunk-words "$CHUNK_WORDS" --gap-seconds "$GAP_SECONDS" \
      > "$RUN_DIR/logs/$NAME-$PHASE.smoke.log" 2>&1 || RC=$?
    echo "[tts-ab] arm=$NAME phase=$PHASE rc=$RC"
    snapshot_resources "$NAME" "$PHASE-end"
    [ "$RC" -eq 0 ] || ARM_RC=1
  done
  # Collect the patch and metric lines only now: the compilation happens on the
  # first real frame, i.e. inside the smoke, so an earlier grep would miss it.
  collect_arm_logs "$NAME"
  stop_service
  wait_port_free "$ARM_URL/health" || true
  if [ "$ARM_RC" -eq 0 ]; then
    ARM_SUMMARY+=("$NAME ok")
  else
    ARM_SUMMARY+=("$NAME smoke-failed")
    echo "[tts-ab] arm=$NAME smoke failed; tail of the service log:"
    tail -20 "$RUN_DIR/logs/$NAME.service.log"
  fi
done

echo "[tts-ab] arms summary: ${ARM_SUMMARY[*]:-none}"

conda run --no-capture-output -n "$CLIENT_ENV" \
  python "$TASK_ROOT/scripts/remote/summarize_tts_throughput.py" \
  --run-dir "$RUN_DIR" --report-dir "$REPORT_DIR" --tag "$RUN_TAG" || true

for artifact in tts_throughput.md tts_throughput.json; do
  [ -f "$REPORT_DIR/$artifact" ] && echo "[tts-ab] report: $REPORT_DIR/$artifact"
done
echo "[tts-ab] $(date -u +%FT%TZ) done; run dir $RUN_DIR"
