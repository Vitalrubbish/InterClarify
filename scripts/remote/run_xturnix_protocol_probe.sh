#!/usr/bin/env bash
# Run the XTX-002 dev protocol probe in one scheduler-allocated GPU job.
#
# This is diagnostic evidence, not the formal 100-utterance replay. The job
# starts the frozen Nemotron service, runs the probe serially and stores every
# service log, health response, GPU sample and exit code.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${XTURNIX_ROOT:-$HOME/interclarify-xturnix-fleurs}"
OUTPUT="${XTURNIX_PROBE_OUTPUT:?set a new output directory}"
CONFIG="${XTURNIX_CONFIG:-$REPO_ROOT/configs/xturnix_fleurs_test.json}"
XT_ENV="${XTURNIX_ENV:-$ROOT/envs/xturnix}"
ASR_ENV="${XTURNIX_ASR_ENV:-$HOME/interclarify-english-integration-20261018-v1/envs/asr}"
ASR_MODEL="${XTURNIX_ASR_MODEL:-$HOME/interclarify-asr-selection/models/nemotron_en}"
DEV_AUDIO="${XTURNIX_DEV_AUDIO:-$ROOT/dataset/fleurs_en_us/audio/dev/786465049904960526.wav}"
MODEL_DIR="$ROOT/models/xturnix-pt"
PORT=18805
BASE_URL="http://127.0.0.1:$PORT"
JOB_SECONDS="${XTURNIX_PROBE_TIMEOUT:-1800}"

[ ! -e "$OUTPUT" ] || { echo "Output already exists: $OUTPUT" >&2; exit 2; }
for path in "$CONFIG" "$XT_ENV/bin/python" "$ASR_ENV/bin/python" "$ASR_MODEL/config.json" \
            "$DEV_AUDIO" "$MODEL_DIR/turn_pipeline.py"; do
  [ -e "$path" ] || { echo "Missing input: $path" >&2; exit 2; }
done
mkdir -p "$OUTPUT"
export PYTHONNOUSERSITE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4

SERVER=""
MONITOR=""
cleanup() {
  local rc=$?
  trap - EXIT
  if [ -n "$SERVER" ]; then
    if [ -r "/proc/$SERVER/status" ]; then
      cat "/proc/$SERVER/status" > "$OUTPUT/service_process_status.txt"
    fi
    kill -TERM -- "-$SERVER" 2>/dev/null || true
    wait "$SERVER" 2>/dev/null || true
  fi
  if [ -n "$MONITOR" ]; then
    kill "$MONITOR" 2>/dev/null || true
    wait "$MONITOR" 2>/dev/null || true
  fi
  printf '%s\n' "$rc" > "$OUTPUT/exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cp "$CONFIG" "$OUTPUT/config.json"
git -C "$REPO_ROOT" rev-parse HEAD > "$OUTPUT/source_commit.txt"
git -C "$REPO_ROOT" status --short > "$OUTPUT/source_status.txt"
sha256sum "$REPO_ROOT/scripts/remote/xturnix_protocol_probe.py" \
  "$REPO_ROOT/scripts/remote/nemotron_asr_service.py" \
  "$CONFIG" > "$OUTPUT/source.sha256"
if [ -d "$ROOT/environment" ]; then
  cp "$ROOT/environment/xturnix.pip-freeze.txt" "$OUTPUT/xturnix.pip-freeze.txt"
  cp "$ROOT/environment/xturnix.conda-explicit.txt" "$OUTPUT/xturnix.conda-explicit.txt"
  cp "$ROOT/environment/model_verification.json" "$OUTPUT/model_verification.json" 2>/dev/null || true
  cp "$ROOT/models/xturnix-pt.lock.json" "$OUTPUT/xturnix-pt.lock.json"
fi
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv > "$OUTPUT/gpu.csv"
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv -l 1 > "$OUTPUT/gpu_samples.csv" &
MONITOR=$!

setsid "$ASR_ENV/bin/python" -u "$REPO_ROOT/scripts/remote/nemotron_asr_service.py" \
  --model "$ASR_MODEL" --warmup-audio "$DEV_AUDIO" --port "$PORT" \
  > "$OUTPUT/service.log" 2>&1 &
SERVER=$!

"$XT_ENV/bin/python" - "$BASE_URL" "$SERVER" "$OUTPUT/health.json" <<'PY'
import json, os, sys, time, urllib.request
url, pid, target = sys.argv[1], int(sys.argv[2]), sys.argv[3]
for _ in range(180):
    os.kill(pid, 0)
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=2) as response:
            value = json.load(response)
        with open(target, "w") as stream:
            json.dump(value, stream, indent=2)
        break
    except OSError:
        time.sleep(1)
else:
    raise TimeoutError("ASR service did not complete model loading and real warmup")
PY

timeout "$JOB_SECONDS" "$XT_ENV/bin/python" -u "$REPO_ROOT/scripts/remote/xturnix_protocol_probe.py" \
  --config "$CONFIG" --dev-audio "$DEV_AUDIO" --model "$MODEL_DIR" \
  --asr-url "$BASE_URL" --output "$OUTPUT/probe" > "$OUTPUT/probe.log" 2>&1
