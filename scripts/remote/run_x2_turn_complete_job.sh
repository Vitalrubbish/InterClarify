#!/usr/bin/env bash
# Run one X2-Turn vLLM service on a scheduler-allocated GPU and diagnose it.
#
# The deployment stage starts the pinned service, proves that the turn head and
# the 480 ms transcription delay are really active, and streams the dev input
# once.  Replay of the formal subset and the complete-rate metric are later
# work items; this script never starts the dialogue LLM, TTS or the upstream
# FrameTurnController.
set -euo pipefail

ROOT="${X2_TURN_ROOT:?set frozen X2 Turn experiment root}"
OUTPUT="${X2_TURN_OUTPUT:?set a new output directory}"
STAGE="${X2_TURN_STAGE:-deploy}"
ENV_PREFIX="${X2_TURN_CONDA_ENV:-$HOME/miniconda3/envs/interclarify-x2-turn-vllm}"
MODEL="${X2_TURN_MODEL:-$ROOT/models/X2-Turn-4B-0812-vllm}"
PORT="${X2_TURN_PORT:-18011}"
DEV_AUDIO="${X2_TURN_DEV_AUDIO:-$ROOT/dataset/fleurs_en_us/audio/dev}"
SMOKE_AUDIO="${X2_TURN_SMOKE_AUDIO:-}"
READY_TIMEOUT="${X2_TURN_READY_TIMEOUT:-1200}"
DRAIN_SECONDS="${X2_TURN_DRAIN_SECONDS:-5}"
SOURCE_COMMIT="${X2_TURN_SOURCE_COMMIT:-unknown}"
SOURCE="${X2_TURN_SOURCE:?set the frozen InterClarify source checkout}"
SERVED_NAME="x-square-robot/X2-Turn-4B-0812"

case "$STAGE" in deploy) ;; *) echo "Unsupported stage: $STAGE" >&2; exit 2 ;; esac
[ ! -e "$OUTPUT" ] || { echo "Output already exists: $OUTPUT" >&2; exit 2; }
mkdir -p "$OUTPUT"

export PYTHONNOUSERSITE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
export VLLM_NO_USAGE_STATS=1

SERVER=''
MONITOR=''
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
  if [ -n "$MONITOR" ]; then
    kill "$MONITOR" 2>/dev/null || true
  fi
  printf '%s\n' "$rc" >"$OUTPUT/exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

fail() { echo "FAILED: $*" >&2; exit 1; }

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

PY="$ENV_PREFIX/bin/python"
[ -x "$PY" ] || fail "missing conda environment $ENV_PREFIX; run the setup stage"
[ -f "$MODEL/consolidated.safetensors" ] || fail "missing exported weights in $MODEL"
[ -f "$MODEL/params.json" ] || fail "missing params.json in $MODEL"
[ -f "$ROOT/env/x2_turn_vllm_environment.json" ] || fail "missing environment lock"
[ -f "$ROOT/env/x2_turn_model_lock.json" ] || fail "missing model lock"
command -v nvidia-smi >/dev/null || fail "no GPU is visible to this job"

FREE_GIB="$(df -B1 --output=avail "$ROOT" | tail -1 | awk '{printf "%.1f", $1/1024/1024/1024}')"
log "free disk: ${FREE_GIB} GiB"
awk -v free="$FREE_GIB" 'BEGIN { if (free < 100) { print "Need >=100 GiB free"; exit 1 } }'

cat >"$OUTPUT/manifest.json" <<JSON
{
  "stage": "$STAGE",
  "root": "$ROOT",
  "output": "$OUTPUT",
  "model": "$MODEL",
  "conda_env": "$ENV_PREFIX",
  "source_commit": "$SOURCE_COMMIT",
  "port": $PORT,
  "served_model_name": "$SERVED_NAME",
  "ready_timeout_seconds": $READY_TIMEOUT,
  "drain_seconds": $DRAIN_SECONDS,
  "free_disk_gib_before": $FREE_GIB
}
JSON

nvidia-smi --query-gpu=index,name,uuid,driver_version,memory.total \
  --format=csv >"$OUTPUT/gpu.csv"
nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu \
  --format=csv -l 1 >"$OUTPUT/gpu_samples.csv" &
MONITOR=$!

log "starting vLLM service on 127.0.0.1:$PORT"
setsid "$ENV_PREFIX/bin/vllm" serve "$MODEL" \
  --served-model-name "$SERVED_NAME" \
  --host 127.0.0.1 --port "$PORT" --tokenizer-mode mistral \
  --enforce-eager --gpu-memory-utilization 0.8 \
  >"$OUTPUT/service.log" 2>&1 &
SERVER=$!

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

probe() {
  local audio="$1"
  local name="$2"
  "$PY" -u "$SOURCE/scripts/remote/x2_turn_service_probe.py" \
    --url "ws://127.0.0.1:$PORT/v1/realtime" --model "$SERVED_NAME" \
    --audio "$audio" --output "$OUTPUT/$name" --drain-seconds "$DRAIN_SECONDS" \
    >"$OUTPUT/$name.log" 2>&1
}

DEV_FILE="$(find "$DEV_AUDIO" -maxdepth 1 -name '*.wav' | sort | head -1)"
[ -n "$DEV_FILE" ] || fail "no dev wav under $DEV_AUDIO"
log "probing dev input: $DEV_FILE"
probe "$DEV_FILE" probe_dev
log "dev probe: $(cat "$OUTPUT/probe_dev/summary.json" | "$PY" -c 'import json,sys; s=json.load(sys.stdin); print(s["turn_class_counts"], s["complete"])')"

if [ -n "$SMOKE_AUDIO" ]; then
  log "probing smoke input: $SMOKE_AUDIO"
  probe "$SMOKE_AUDIO" probe_smoke
fi

log "deployment diagnostics finished"
