#!/usr/bin/env bash
# Round-one GPU acceptance job executed inside a cluster container.
#
# Modes:
#   bash run_xtalk_round1_node_job.sh asr
#       1-GPU job: ASR smoke at chunk windows 0.6 / 1.2 / 2.0 s (--gpu-index 0).
#   bash run_xtalk_round1_node_job.sh services
#       4-GPU job: start llm / turn_detector / tts on GPUs 0/1/3, verify all
#       endpoints, run upstream X-Talk tests, then TTS cold/warm/gap smoke.
#   bash run_xtalk_round1_node_job.sh chain
#       4-GPU job: start the three services, then run the full path
#       ASR (gpu2) -> LLM -> TTS on one input wav, measure per-stage latency,
#       and copy the run dir under $INTERCLARIFY_ROOT/fullchain_logs/.
#
# All evidence is written under $XTALK_ROUND1_ARTIFACT_ROOT so it is visible
# from the dev machine.  The script keeps going after individual check
# failures and reports a per-step status JSON at the end.
set -uo pipefail

MODE="${1:?usage: run_xtalk_round1_node_job.sh [asr|services|chain]}"

export INTERCLARIFY_ROOT="${INTERCLARIFY_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/InterClarify}"
export XTALK_ROUND1_ROOT="${XTALK_ROUND1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1}"
export XTALK_ROUND1_MODEL_ROOT="${XTALK_ROUND1_MODEL_ROOT:-$XTALK_ROUND1_ROOT/models}"
export XTALK_ROUND1_ARTIFACT_ROOT="${XTALK_ROUND1_ARTIFACT_ROOT:-$XTALK_ROUND1_ROOT/artifacts}"
export XTALK_MOSS_SERVICE_ROOT="${XTALK_MOSS_SERVICE_ROOT:-$XTALK_ROUND1_ROOT/moss-service}"
export XTALK_MOSS_SOURCE_ROOT="${XTALK_MOSS_SOURCE_ROOT:-$XTALK_ROUND1_ROOT/moss-source}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONNOUSERSITE=1
export TOKENIZERS_PARALLELISM=false

CONDA_SH="${CONDA_SH:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/etc/profile.d/conda.sh}"
# In round-one cluster images the same conda env names live under /opt/conda;
# submit with CONDA_SH=/opt/conda/etc/profile.d/conda.sh to use the image envs.
ROUND1_PY="$INTERCLARIFY_ROOT/scripts/remote/run_xtalk_round1.py"
TAG="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$XTALK_ROUND1_ARTIFACT_ROOT/$MODE/$TAG"
mkdir -p "$RUN_DIR"
LOG="$RUN_DIR/run.log"

# shellcheck disable=SC1091
source "$CONDA_SH"

step_status() {  # step_status <name> <rc>
  echo "{\"step\": \"$1\", \"status\": \"$([ "$2" -eq 0 ] && echo PASS || echo FAIL)\", \"rc\": $2}" >> "$RUN_DIR/steps.jsonl"
  echo "[node-job] step=$1 rc=$2" | tee -a "$LOG"
}

wait_http() {  # wait_http <url> <timeout_seconds> <log_file>
  local url="$1" deadline="$2" log_file="$3" waited=0
  until curl -sf --max-time 10 "$url" > "$log_file" 2>&1; do
    if [ "$waited" -ge "$deadline" ]; then
      echo "[node-job] TIMEOUT waiting for $url after ${deadline}s" | tee -a "$LOG"
      return 1
    fi
    sleep 10
    waited=$((waited + 10))
  done
  echo "[node-job] $url ready after ${waited}s" | tee -a "$LOG"
}

start_service() {  # start_service <role> <gpu_index>
  local role="$1" gpu_index="$2"
  setsid conda run --no-capture-output -n xtalk-round1-tools \
    python "$ROUND1_PY" --model-root "$XTALK_ROUND1_MODEL_ROOT" \
    serve "$role" --gpu-index "$gpu_index" \
    > "$RUN_DIR/service_logs/$role.log" 2>&1 &
  echo $! > "$RUN_DIR/service_logs/$role.pid"
  echo "[node-job] started $role (pgid $(cat "$RUN_DIR/service_logs/$role.pid")) on gpu $gpu_index" | tee -a "$LOG"
}

stop_services() {
  local role
  for role in llm turn_detector tts; do
    local pid_file="$RUN_DIR/service_logs/$role.pid"
    if [ -f "$pid_file" ]; then
      kill -TERM -"$(cat "$pid_file")" 2>/dev/null || true
    fi
    pkill -f "run_xtalk_round1.py.*serve $role" 2>/dev/null || true
  done
  sleep 10
}

{
  echo "[node-job] mode=$MODE tag=$TAG"
  echo "[node-job] run_dir=$RUN_DIR"
  nvidia-smi
} > "$RUN_DIR/nvidia-smi.txt" 2>&1
{ git -C "$INTERCLARIFY_ROOT" rev-parse HEAD; git -C "$INTERCLARIFY_ROOT" status --porcelain; } > "$RUN_DIR/git.txt" 2>&1
cp "$XTALK_ROUND1_MODEL_ROOT/models.lock.json" "$RUN_DIR/models.lock.json"

# Sanity: the conda environments (base + built envs) must import in this
# container (glibc / binary wheel compatibility check).
RC=0
for env in base xtalk-round1-tools xtalk-round1-asr xtalk-round1-moss xtalk-round1-client; do
  conda run -n "$env" python -c "import yaml" >> "$LOG" 2>&1 || { RC=1; echo "[node-job] env $env: basic import FAILED" | tee -a "$LOG"; }
done
step_status "env_imports" "$RC"
[ "$RC" -eq 0 ] || { echo "[node-job] aborting: conda envs not usable in this container" | tee -a "$LOG"; exit "$RC"; }

if [ "$MODE" = "asr" ]; then
  for spec in "0.6:asr-06" "1.2:asr-12" "2.0:asr-20"; do
    chunk="${spec%%:*}"
    label="${spec##*:}"
    conda run --no-capture-output -n xtalk-round1-asr \
      python "$ROUND1_PY" --model-root "$XTALK_ROUND1_MODEL_ROOT" \
      asr-smoke --audio "$XTALK_ROUND1_ROOT/audio/request.wav" \
      --output "$RUN_DIR/$label" --chunk-seconds "$chunk" --gpu-index 0 \
      > "$RUN_DIR/$label.log" 2>&1
    step_status "$label" "$?"
  done
  OVERALL_RC=$(grep -c '"status": "FAIL"' "$RUN_DIR/steps.jsonl" || true)
  echo "[node-job] asr done, failures=$OVERALL_RC" | tee -a "$LOG"
  exit "$OVERALL_RC"
fi

# ---- chain mode: full path ASR -> LLM -> TTS on 4 GPUs ----
if [ "$MODE" = "chain" ]; then
  mkdir -p "$RUN_DIR/service_logs" "$RUN_DIR/curl"
  nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader -l 10 \
    > "$RUN_DIR/gpu_samples.csv" 2>&1 &
  GPU_LOG_PID=$!
  FAILURES=0

  start_service llm 0
  wait_http "http://127.0.0.1:8000/v1/models" 1800 "$RUN_DIR/curl/llm_models.json" || FAILURES=$((FAILURES + 1))
  start_service turn_detector 1
  wait_http "http://127.0.0.1:8003/v1/models" 1800 "$RUN_DIR/curl/turn_detector_models.json" || FAILURES=$((FAILURES + 1))
  start_service tts 3
  wait_http "http://127.0.0.1:8004/health" 1800 "$RUN_DIR/curl/tts_health.json" || FAILURES=$((FAILURES + 1))
  RC=0; [ "$FAILURES" -eq 0 ] || RC=1
  step_status "chain_services_up" "$RC"

  # Stage 1: ASR on GPU 2 (warm-up inside asr-smoke keeps latency clean).
  RC=0
  conda run --no-capture-output -n xtalk-round1-asr \
    python "$ROUND1_PY" --model-root "$XTALK_ROUND1_MODEL_ROOT" \
    asr-smoke --audio "$XTALK_ROUND1_ROOT/audio/request.wav" \
    --output "$RUN_DIR/chain-asr" --chunk-seconds 0.6 --gpu-index 2 \
    > "$RUN_DIR/chain-asr.log" 2>&1 || RC=$?
  step_status "chain_asr" "$RC"

  # Stage 2: LLM on the ASR transcript; measure first-token latency.
  RC=0
  conda run --no-capture-output -n xtalk-round1-client python - \
    "$RUN_DIR/chain-asr/asr_report.json" \
    > "$RUN_DIR/chain-llm.json" 2>"$RUN_DIR/chain-llm.log" <<'PY' || RC=$?
import json, sys, time, urllib.request
report = json.load(open(sys.argv[1]))
prompt = report.get("final_text") or ""
payload = json.dumps({
    "model": "xtalk-round1-llm",
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0, "max_tokens": 256, "stream": True,
}).encode()
request = urllib.request.Request(
    "http://127.0.0.1:8000/v1/chat/completions", data=payload,
    headers={"Content-Type": "application/json"},
)
start = time.monotonic(); first = None; pieces = []
with urllib.request.urlopen(request, timeout=600) as response:
    for raw in response:
        line = raw.decode("utf-8", "ignore").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except Exception:
            continue
        delta = chunk.get("choices", [{}])[0].get("delta", {})
        piece = delta.get("content") or ""
        if piece:
            if first is None:
                first = time.monotonic() - start
            pieces.append(piece)
seconds = time.monotonic() - start
print(json.dumps({
    "prompt": prompt, "response": "".join(pieces),
    "first_token_seconds": first, "total_seconds": seconds,
}, ensure_ascii=False))
PY
  step_status "chain_llm" "$RC"

  # Stage 3: TTS on the LLM response; measure first audio.
  RESP="$(conda run -n xtalk-round1-client python -c "import json;print(json.load(open('$RUN_DIR/chain-llm.json')).get('response',''))" 2>/dev/null)"
  RC=0
  if [ -n "$RESP" ]; then
    conda run --no-capture-output -n xtalk-round1-client \
      python "$ROUND1_PY" --model-root "$XTALK_ROUND1_MODEL_ROOT" \
      tts-smoke --reference "$XTALK_ROUND1_ROOT/audio/reference.wav" \
      --output "$RUN_DIR/chain-tts" --text "$RESP" \
      > "$RUN_DIR/chain-tts.log" 2>&1 || RC=$?
  else
    RC=1
    echo "[node-job] empty LLM response; skipping TTS" | tee -a "$LOG"
  fi
  step_status "chain_tts" "$RC"

  # Aggregate the three stages into one report.
  conda run -n base python - "$RUN_DIR" > "$RUN_DIR/chain_report.json" 2>>"$LOG" <<'PY'
import json, pathlib, sys
run = pathlib.Path(sys.argv[1])
def load(path):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except Exception:
        return {}
asr = load(run / "chain-asr/asr_report.json")
llm = load(run / "chain-llm.json")
tts = load(run / "chain-tts/tts_report.json")
report = {
    "asr": {
        "final_text": asr.get("final_text"),
        "first_partial_audio_seconds": asr.get("first_partial_audio_seconds"),
        "decode_rtf": asr.get("decode_rtf"),
    },
    "llm": {
        "response": llm.get("response"),
        "first_token_seconds": llm.get("first_token_seconds"),
        "total_seconds": llm.get("total_seconds"),
    },
    "tts": {
        "first_audio_seconds": tts.get("first_audio_seconds"),
        "audio_seconds": tts.get("audio_seconds"),
        "audio_before_flush": tts.get("audio_before_flush"),
        "sample_rate": tts.get("sample_rate"),
    },
}
report["content_ok"] = bool(asr.get("final_text")) and bool(llm.get("response")) and bool(tts.get("audio_seconds"))
report["note"] = "Sequential stage measurement (ASR final -> LLM first token -> TTS first audio); not concurrent duplex."
print(json.dumps(report, ensure_ascii=False, indent=2))
PY
  step_status "chain_report" "$?"

  stop_services
  kill "$GPU_LOG_PID" 2>/dev/null || true

  # Copy the whole run dir under the repository root as requested.
  DEST="$INTERCLARIFY_ROOT/fullchain_logs/$TAG"
  mkdir -p "$(dirname "$DEST")"
  cp -r "$RUN_DIR/." "$DEST/"
  CHAIN_FAILURES=$(grep -c '"status": "FAIL"' "$RUN_DIR/steps.jsonl" || true)
  echo "[node-job] chain done, failures=$CHAIN_FAILURES, logs copied to $DEST" | tee -a "$LOG"
  exit "$CHAIN_FAILURES"
fi

# ---- services mode: 4 GPUs allocated ----
mkdir -p "$RUN_DIR/service_logs" "$RUN_DIR/curl" "$RUN_DIR/pytest"
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader -l 10 \
  > "$RUN_DIR/gpu_samples.csv" 2>&1 &
GPU_LOG_PID=$!

FAILURES=0

start_service llm 0
RC=0
wait_http "http://127.0.0.1:8000/v1/models" 1800 "$RUN_DIR/curl/llm_models.json" || RC=$?
[ "$RC" -eq 0 ] || FAILURES=$((FAILURES + 1))
step_status "llm_service_up" "$RC"

start_service turn_detector 1
RC=0
wait_http "http://127.0.0.1:8003/v1/models" 1800 "$RUN_DIR/curl/turn_detector_models.json" || RC=$?
[ "$RC" -eq 0 ] || FAILURES=$((FAILURES + 1))
step_status "turn_detector_service_up" "$RC"

start_service tts 3
RC=0
wait_http "http://127.0.0.1:8004/health" 1800 "$RUN_DIR/curl/tts_health.json" || RC=$?
[ "$RC" -eq 0 ] || FAILURES=$((FAILURES + 1))
step_status "tts_service_up" "$RC"

# Endpoint checks per job document section 5.
RC=0
curl -sf http://127.0.0.1:8000/v1/models > "$RUN_DIR/curl/llm_models_final.json" || RC=1
curl -sf http://127.0.0.1:8003/v1/models > "$RUN_DIR/curl/turn_detector_models_final.json" || RC=1
curl -sf http://127.0.0.1:8004/health > "$RUN_DIR/curl/tts_health_final.json" || RC=1
curl -sf -N http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"xtalk-round1-llm","messages":[{"role":"user","content":"请用一句话介绍自己。"}],"temperature":0,"max_tokens":64,"stream":true}' \
  > "$RUN_DIR/curl/llm_chat_stream.txt" || RC=1
step_status "endpoint_checks" "$RC"
[ "$RC" -eq 0 ] || FAILURES=$((FAILURES + 1))

grep -q '"id":"xturnix"' "$RUN_DIR/curl/turn_detector_models_final.json" && echo "[node-job] turn detector served model name: xturnix" | tee -a "$LOG" \
  || { echo "[node-job] WARNING: xturnix name not confirmed" | tee -a "$LOG"; }

# Adapter-level keep/start/stop probe against the live XTurnix service.
RC=0
conda run --no-capture-output -n xtalk-round1-client python - \
  > "$RUN_DIR/curl/xturnix_adapter_probe.json" 2>&1 <<'PY' || RC=$?
import json

from xtalk.models.turn_detector.interfaces import TurnDetectionAction
from xtalk.models.turn_detector.xturnix import XTurnix

detector = XTurnix(base_url="http://127.0.0.1:8003", timeout=60)
question = "明天下午三点能帮我安排一个会议吗？"
detector.listening = True
listening_result = detector.detect(
    text=question, speech_start=True, speech_pause=True
)
detector.listening = False
speaking_result = detector.detect(
    text="等一下，我突然想到一个更重要的问题。", speech_start=True, speech_pause=True
)
report = {
    "listening_action": listening_result.action.name,
    "speaking_action": speaking_result.action.name,
    "listening_valid": listening_result.action
    in (TurnDetectionAction.DO_NOTHING, TurnDetectionAction.START_GENERATION),
    "speaking_valid": speaking_result.action
    in (TurnDetectionAction.DO_NOTHING, TurnDetectionAction.STOP_SPEAKING),
}
print(json.dumps(report, ensure_ascii=False))
PY
step_status "xturnix_adapter_probe" "$RC"
[ "$RC" -eq 0 ] || FAILURES=$((FAILURES + 1))

# Upstream X-Talk tests in the client environment.
RC=0
(cd "$XTALK_ROUND1_ROOT/xtalk" && conda run --no-capture-output -n xtalk-round1-client \
  python -m pytest tests/test_moss_tts_realtime.py -q) > "$RUN_DIR/pytest/moss_tts_realtime.txt" 2>&1 || RC=$?
step_status "pytest_moss_tts_realtime" "$RC"
[ "$RC" -eq 0 ] || FAILURES=$((FAILURES + 1))

RC=0
(cd "$XTALK_ROUND1_ROOT/xtalk" && conda run --no-capture-output -n xtalk-round1-client \
  python -m pytest -q) > "$RUN_DIR/pytest/full.txt" 2>&1 || RC=$?
step_status "pytest_full" "$RC"
[ "$RC" -eq 0 ] || FAILURES=$((FAILURES + 1))

# MOSS cold / warm / two-stream TTS smoke against the running service.
for run in tts-cold tts-warm tts-gap2; do
  extra=()
  [ "$run" = "tts-gap2" ] && extra=(--gap-seconds 2)
  RC=0
  conda run --no-capture-output -n xtalk-round1-client \
    python "$ROUND1_PY" --model-root "$XTALK_ROUND1_MODEL_ROOT" \
    tts-smoke --reference "$XTALK_ROUND1_ROOT/audio/reference.wav" \
    --output "$RUN_DIR/$run" "${extra[@]}" > "$RUN_DIR/$run.log" 2>&1 || RC=$?
  step_status "$run" "$RC"
  [ "$RC" -eq 0 ] || FAILURES=$((FAILURES + 1))
done

stop_services
kill "$GPU_LOG_PID" 2>/dev/null || true

{
  echo "failures=$FAILURES"
  echo "tag=$TAG"
} >> "$LOG"
echo "[node-job] services done, failures=$FAILURES" | tee -a "$LOG"
exit "$FAILURES"
