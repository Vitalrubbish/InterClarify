#!/usr/bin/env bash
# Run one X2Q-014 evaluation stage on a scheduler-allocated GPU.
#
# The script starts the frozen X2-Turn vLLM service, proves the 480 ms delay
# and turn-head mapping, warms the service with the pinned dev input, then runs
# either the fixed five-sample smoke set or the full 100-sample formal set.  It
# scores the same raw traces with the independent ASR and complete scorers and
# stops the service before exit.  It never starts the dialogue LLM, TTS, the
# upstream FrameTurnController or any FDB component.
set -euo pipefail

ROOT="${X2_TURN_ROOT:?set frozen X2 Turn experiment root}"
SOURCE="${X2_TURN_SOURCE:?set the frozen InterClarify source checkout}"
STAGE="${X2_TURN_STAGE:?set smoke or formal}"
TAG="${X2_TURN_TAG:?set a unique run tag}"
RUN_ID="${X2_TURN_RUN_ID:?set a unique replay run id}"
DEV_RUN_ID="${X2_TURN_DEV_RUN_ID:-dev-$TAG}"
OUTPUT="${X2_TURN_OUTPUT:-$ROOT/runs/job-$TAG-$STAGE}"
ENV_PREFIX="${X2_TURN_CONDA_ENV:-$HOME/miniconda3/envs/interclarify-x2-turn-vllm}"
REPLAY_ENV="${X2_TURN_REPLAY_ENV:-$HOME/miniconda3/envs/interclarify-x2-turn-data}"
MODEL="${X2_TURN_MODEL:-$ROOT/models/X2-Turn-4B-0812-vllm}"
PORT="${X2_TURN_PORT:-18011}"
READY_TIMEOUT="${X2_TURN_READY_TIMEOUT:-1200}"
MAX_MODEL_LEN="${X2_TURN_MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${X2_TURN_GPU_MEMORY_UTILIZATION:-0.85}"
SOURCE_COMMIT="${X2_TURN_SOURCE_COMMIT:-unknown}"
MIN_FREE_GIB="${X2_TURN_MIN_FREE_GIB:-100}"
SERVED_NAME="x-square-robot/X2-Turn-4B-0812"
URL="ws://127.0.0.1:$PORT/v1/realtime"

case "$STAGE" in smoke|formal) ;; *) echo "Unsupported stage: $STAGE" >&2; exit 2 ;; esac
[ ! -e "$OUTPUT" ] || { echo "Output already exists: $OUTPUT" >&2; exit 2; }
mkdir -p "$OUTPUT"

export PYTHONNOUSERSITE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
export VLLM_NO_USAGE_STATS=1

SERVER=''
GPU_MONITOR=''
PROC_MONITOR=''
cleanup() {
  local rc=$?
  trap - EXIT
  if [ -n "$SERVER" ]; then
    if [ -r "/proc/$SERVER/status" ]; then
      cat "/proc/$SERVER/status" >"$OUTPUT/service_process_status.txt"
    fi
    kill -TERM -- "-$SERVER" 2>/dev/null || true
    wait "$SERVER" 2>/dev/null || true
  fi
  [ -n "$GPU_MONITOR" ] && kill "$GPU_MONITOR" 2>/dev/null || true
  [ -n "$PROC_MONITOR" ] && kill "$PROC_MONITOR" 2>/dev/null || true
  printf '%s\n' "$rc" >"$OUTPUT/exit_code.txt"
  if [ -d "$ROOT/runs/$RUN_ID/job" ]; then
    printf '%s\n' "$rc" >"$ROOT/runs/$RUN_ID/job/exit_code.txt"
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

fail() { echo "FAILED: $*" >&2; exit 1; }
log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

PY="$ENV_PREFIX/bin/python"
REPLAY_PY="$REPLAY_ENV/bin/python"
[ -x "$PY" ] || fail "missing conda environment $ENV_PREFIX"
[ -x "$REPLAY_PY" ] || fail "missing replay environment $REPLAY_ENV"
[ -f "$MODEL/consolidated.safetensors" ] || fail "missing exported weights in $MODEL"
[ -f "$MODEL/params.json" ] || fail "missing params.json in $MODEL"
[ -f "$ROOT/env/x2_turn_vllm_environment.json" ] || fail "missing environment lock"
[ -f "$ROOT/env/x2_turn_model_lock.json" ] || fail "missing model lock"
[ -f "$ROOT/dataset/fleurs_en_us/manifest.json" ] || fail "missing frozen input manifest"
[ -f "$SOURCE/scripts/remote/x2_turn_complete_test.py" ] || fail "missing replay client in frozen source"
command -v nvidia-smi >/dev/null || fail "no GPU is visible to this job"

"$REPLAY_PY" - <<'PY' || fail "replay environment cannot import its pinned modules"
import soundfile
import websockets
import whisper_normalizer
print("soundfile", soundfile.__version__)
print("websockets", websockets.__version__)
PY

FREE_GIB="$(df -B1 --output=avail "$ROOT" | tail -1 | awk '{printf "%.1f", $1/1024/1024/1024}')"
log "free disk: ${FREE_GIB} GiB"
awk -v free="$FREE_GIB" -v need="$MIN_FREE_GIB" 'BEGIN { if (free < need) { print "Need >=" need " GiB free"; exit 1 } }'

DATASET_SHA="$(sha256sum "$ROOT/dataset/fleurs_en_us/manifest.json" | awk '{print $1}')"
MODEL_REVISION="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("revision",""))' "$ROOT/env/x2_turn_model_lock.json")"
SOURCE_CLIENT_SHA="$(sha256sum "$SOURCE/scripts/remote/x2_turn_complete_test.py" | awk '{print $1}')"
JOB_SHA="$(sha256sum "$0" | awk '{print $1}')"

cat >"$OUTPUT/manifest.json" <<JSON
{
  "schema": "x2q-job-v1",
  "stage": "$STAGE",
  "tag": "$TAG",
  "run_id": "$RUN_ID",
  "dev_run_id": "$DEV_RUN_ID",
  "root": "$ROOT",
  "output": "$OUTPUT",
  "source": "$SOURCE",
  "source_commit": "$SOURCE_COMMIT",
  "source_client_sha256": "$SOURCE_CLIENT_SHA",
  "job_script_sha256": "$JOB_SHA",
  "model": "$MODEL",
  "model_revision": "$MODEL_REVISION",
  "dataset_manifest_sha256": "$DATASET_SHA",
  "conda_env": "$ENV_PREFIX",
  "replay_env": "$REPLAY_ENV",
  "port": $PORT,
  "url": "$URL",
  "served_model_name": "$SERVED_NAME",
  "ready_timeout_seconds": $READY_TIMEOUT,
  "max_model_len": $MAX_MODEL_LEN,
  "gpu_memory_utilization": $GPU_MEMORY_UTILIZATION,
  "min_free_gib": $MIN_FREE_GIB,
  "free_disk_gib_before": $FREE_GIB
}
JSON

"$REPLAY_PY" -m pip freeze >"$OUTPUT/replay_pip_freeze.txt"
"$PY" -m pip freeze >"$OUTPUT/server_pip_freeze.txt"

nvidia-smi --query-gpu=index,name,uuid,driver_version,memory.total \
  --format=csv >"$OUTPUT/gpu.csv"
nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu \
  --format=csv -l 1 >"$OUTPUT/gpu_samples.csv" &
GPU_MONITOR=$!

log "starting vLLM service on 127.0.0.1:$PORT"
setsid "$ENV_PREFIX/bin/vllm" serve "$MODEL" \
  --served-model-name "$SERVED_NAME" \
  --host 127.0.0.1 --port "$PORT" --tokenizer-mode mistral \
  --enforce-eager --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --max-model-len "$MAX_MODEL_LEN" \
  >"$OUTPUT/service.log" 2>&1 &
SERVER=$!

{
  while [ -r "/proc/$SERVER/status" ]; do
    awk '/^(VmRSS|VmHWM|VmPeak):/ {print systime(), $1, $2}' "/proc/$SERVER/status" 2>/dev/null
    sleep 5
  done
} >"$OUTPUT/service_memory_samples.txt" 2>/dev/null &
PROC_MONITOR=$!

log "waiting for readiness (timeout ${READY_TIMEOUT}s)"
"$PY" - "$PORT" "$SERVER" "$READY_TIMEOUT" "$OUTPUT/readiness.json" <<'PY'
import json
import os
import sys
import time
import urllib.request

port, pid, timeout, target = sys.argv[1:]
deadline = time.monotonic() + float(timeout)
started = time.monotonic()
while time.monotonic() < deadline:
    os.kill(int(pid), 0)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            response.read()
        with open(target, "w") as stream:
            json.dump({"ready": True, "load_seconds": round(time.monotonic() - started, 1)}, stream)
        break
    except OSError:
        time.sleep(2)
else:
    raise SystemExit("service did not become ready")
PY
log "service ready: $(cat "$OUTPUT/readiness.json")"

grep -q "Loaded Voxtral MTP vad_lm_head" "$OUTPUT/service.log" \
  || fail "service log does not show the turn head being loaded"

"$PY" - "$MODEL" "$OUTPUT/effective_config.json" <<'PY'
import json
import sys
from pathlib import Path

model_dir, target = Path(sys.argv[1]), Path(sys.argv[2])
config = json.loads((model_dir / "config.json").read_text()) if (model_dir / "config.json").exists() else {}
tekken = json.loads((model_dir / "tekken.json").read_text())
audio = tekken["audio"]
encoding = audio["audio_encoding_config"]
frame_rate = float(audio["frame_rate"])
per_token_ms = 1000.0 / frame_rate
declared_ms = float(audio["transcription_delay_ms"])
delay_tokens = round(declared_ms / per_token_ms)
computed_ms = round(delay_tokens * per_token_ms)
payload = {
    "tekken_transcription_delay_ms": declared_ms,
    "tekken_frame_rate": frame_rate,
    "tekken_sampling_rate": audio["sampling_rate"],
    "tekken_hop_length": encoding["hop_length"],
    "config_audio_length_per_tok": config.get("audio_length_per_tok"),
    "config_default_num_delay_tokens": config.get("default_num_delay_tokens"),
    "ms_per_token": per_token_ms,
    "delay_tokens": delay_tokens,
    "computed_delay_ms": computed_ms,
    "sources_agree_on_tokens": config.get("default_num_delay_tokens") in (None, delay_tokens),
}
length = config.get("audio_length_per_tok")
if length is not None:
    from_hops = 1000.0 * int(length) * int(encoding["hop_length"]) / int(audio["sampling_rate"])
    payload["ms_per_token_from_hops"] = from_hops
    payload["sources_agree_on_per_token"] = abs(from_hops - per_token_ms) < 1e-6
try:
    from vllm.tokenizers.registry import get_tokenizer

    tokenizer = get_tokenizer(str(model_dir), tokenizer_mode="mistral")
    audio_config = tokenizer.instruct.audio_encoder.audio_config
    payload["vllm_tokenizer_num_delay_tokens"] = int(audio_config.get_num_delay_tokens())
    payload["vllm_tokenizer_transcription_delay_ms"] = getattr(
        audio_config, "transcription_delay_ms", None
    )
    payload["vllm_tokenizer_frame_rate"] = getattr(audio_config, "frame_rate", None)
except Exception as error:  # pragma: no cover - depends on installed version
    payload["vllm_tokenizer_num_delay_tokens"] = None
    payload["vllm_tokenizer_error"] = repr(error)
from vllm.model_executor.models.voxtral_mtp_utils import TURN_CLASS_IDS, TURN_CLASS_NAMES
payload["turn_id_to_class"] = {str(i): n for i, n in zip(TURN_CLASS_IDS, TURN_CLASS_NAMES, strict=True)}
target.write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps(payload, indent=2))
PY

"$PY" - "$OUTPUT/effective_config.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
if payload["computed_delay_ms"] != 480:
    raise SystemExit(f"effective delay is {payload['computed_delay_ms']} ms, expected 480")
if payload["delay_tokens"] != 6:
    raise SystemExit(f"delay tokens is {payload['delay_tokens']}, expected 6")
if not payload["sources_agree_on_tokens"]:
    raise SystemExit("tekken.json and config.json disagree on the delay tokens")
if payload.get("vllm_tokenizer_num_delay_tokens") != 6:
    raise SystemExit(
        f"the served tokenizer reports {payload.get('vllm_tokenizer_num_delay_tokens')} delay tokens"
    )
if payload.get("vllm_tokenizer_transcription_delay_ms") != 480:
    raise SystemExit(
        "the served tokenizer reports "
        f"{payload.get('vllm_tokenizer_transcription_delay_ms')} ms, expected 480"
    )
if payload["turn_id_to_class"].get("38") != "turn_end":
    raise SystemExit("turn id 38 is not mapped to turn_end")
PY

replay() {
  local mode="$1"
  local run_id="$2"
  local log_name="$3"
  log "replaying $mode input(s) as $run_id"
  set +e
  timeout 13000 "$REPLAY_PY" -u "$SOURCE/scripts/remote/x2_turn_complete_test.py" replay \
    --root "$ROOT" --run-id "$run_id" --mode "$mode" \
    --url "$URL" --model "$SERVED_NAME" >"$OUTPUT/$log_name.log" 2>&1
  local rc=$?
  set -e
  printf '%s\n' "$rc" >"$OUTPUT/$log_name.exit_code"
  log "replay $mode exit code $rc"
  return 0
}

score() {
  local metric="$1"
  local run_id="$2"
  local log_name="$3"
  log "scoring $metric for $run_id"
  set +e
  "$REPLAY_PY" -u "$SOURCE/scripts/remote/x2_turn_complete_test.py" "score-$metric" \
    --run "$ROOT/runs/$run_id" >"$OUTPUT/$log_name.log" 2>&1
  local rc=$?
  set -e
  printf '%s\n' "$rc" >"$OUTPUT/$log_name.exit_code"
  log "score $metric exit code $rc"
  return 0
}

replay dev "$DEV_RUN_ID" dev_warmup
score asr "$DEV_RUN_ID" dev_score_asr
score complete "$DEV_RUN_ID" dev_score_complete
replay "$STAGE" "$RUN_ID" "${STAGE}_replay"
score asr "$RUN_ID" "${STAGE}_score_asr"
score complete "$RUN_ID" "${STAGE}_score_complete"

log "validating scored run"
"$REPLAY_PY" - "$ROOT/runs/$RUN_ID" "$ROOT/runs/$DEV_RUN_ID" "$STAGE" "$OUTPUT" <<'PY'
import json
import sys
from pathlib import Path

run, dev_run, stage, output = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
expected = 5 if stage == "smoke" else 100
plan = json.loads((run / "run.json").read_text())
dev_plan = json.loads((dev_run / "run.json").read_text())
asr = json.loads((run / "asr_scores.json").read_text())
complete = json.loads((run / "complete_scores.json").read_text())
replay_failed = sum(
    json.loads((run / item["trace"]).read_text()).get("status") != "ok"
    for item in plan["samples"]
)
dev_replay_failed = sum(
    json.loads((dev_run / item["trace"]).read_text()).get("status") != "ok"
    for item in dev_plan["samples"]
)
checks = {
    "planned_matches_stage": len(plan["samples"]) == expected,
    "asr_planned_matches_stage": asr["summary"]["planned"] == expected,
    "complete_planned_matches_stage": complete["summary"]["planned"] == expected,
    "asr_rows_match_plan": len(asr["samples"]) == expected,
    "complete_rows_match_plan": len(complete["samples"]) == expected,
    "asr_formal_samples_flag": asr["summary"]["formal_samples"] == (expected if stage == "formal" else 0),
    "complete_formal_samples_flag": complete["summary"]["formal_samples"] == (expected if stage == "formal" else 0),
    "replay_failed_zero": replay_failed == 0,
    "dev_replay_failed_zero": dev_replay_failed == 0,
}
summary = {
    "expected": expected,
    "run": str(run),
    "dev_run": str(dev_run),
    "checks": checks,
    "replay_failed": replay_failed,
    "dev_replay_failed": dev_replay_failed,
    "asr": asr["summary"],
    "complete": complete["summary"],
}
(output / "validation.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
if not all(checks.values()):
    raise SystemExit("scored artifact validation failed")
PY

mkdir -p "$ROOT/runs/$RUN_ID/job"
cp -a "$OUTPUT/." "$ROOT/runs/$RUN_ID/job/"

log "evaluation stage finished"
