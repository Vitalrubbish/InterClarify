#!/usr/bin/env bash
# Run one bounded real-clock ASR/PT comparison in a scheduler allocation.
set -euo pipefail

ROOT="${XTURNIX_ROOT:-$HOME/interclarify-xturnix-fleurs}"
RUN_ID="${XTURNIX_TIME_RUN_ID:?set a unique run id}"
INPUTS="${XTURNIX_TIME_INPUTS:?set the frozen text input directory}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ASR_ENV="$HOME/interclarify-english-integration-20261018-v1/envs/asr"
PT_ENV="$ROOT/envs/xturnix"
ASR_MODEL="$HOME/interclarify-asr-selection/models/nemotron_en"
PT_MODEL="$ROOT/models/xturnix-pt"
CONFIG="$REPO_ROOT/configs/xturnix_short_latency.json"
LABELS="$REPO_ROOT/reports/xturnix_control/20261024-declarative-score-analysis/cohort_labels.csv"
OUT="$ROOT/runs/$RUN_ID"
PORT=18815
ASR_PID=""
MONITOR_PID=""
PROBE_PID=""

case "$RUN_ID" in *[!A-Za-z0-9._-]*|.*) echo "invalid run id" >&2; exit 2 ;; esac
[ ! -e "$OUT" ] || { echo "output already exists" >&2; exit 2; }
nvidia-smi -L >/dev/null
[ -f "$ASR_ENV/conda-meta/history" ] && [ -f "$PT_ENV/conda-meta/history" ] || { echo "missing conda environments" >&2; exit 2; }
[ "$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')" -ge 31457280 ] || { echo "less than 30 GiB free" >&2; exit 2; }
mkdir "$OUT"
exec > >(tee "$OUT/run.log") 2>&1
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

cleanup() {
  rc=$?
  trap - EXIT
  if [ -n "$MONITOR_PID" ]; then kill "$MONITOR_PID" 2>/dev/null || true; wait "$MONITOR_PID" 2>/dev/null || true; fi
  if [ -n "$PROBE_PID" ]; then
    kill -TERM -- "-$PROBE_PID" 2>/dev/null || true
    for _ in $(seq 1 10); do
      if ! kill -0 "$PROBE_PID" 2>/dev/null; then break; fi
      sleep 1
    done
    kill -KILL -- "-$PROBE_PID" 2>/dev/null || true
    wait "$PROBE_PID" 2>/dev/null || true
  fi
  if [ -n "$ASR_PID" ]; then
    if [ -r "/proc/$ASR_PID/status" ]; then cat "/proc/$ASR_PID/status" > "$OUT/asr_process_status.txt"; fi
    kill -TERM -- "-$ASR_PID" 2>/dev/null || true
    for _ in $(seq 1 10); do
      if ! kill -0 "$ASR_PID" 2>/dev/null; then break; fi
      sleep 1
    done
    kill -KILL -- "-$ASR_PID" 2>/dev/null || true
    wait "$ASR_PID" 2>/dev/null || true
  fi
  printf '%s\n' "$rc" > "$OUT/exit_code.txt"
  du -sk "$OUT" > "$OUT/output_size_kib.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

git -C "$REPO_ROOT" rev-parse HEAD > "$OUT/source_commit.txt"
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv > "$OUT/hardware.csv"
bash "$REPO_ROOT/scripts/remote/setup_xturnix_env.sh" verify > "$OUT/model_verify.log" 2>&1
"$PT_ENV/bin/python" -c 'import socket; s=socket.socket(); s.settimeout(1); occupied=s.connect_ex(("127.0.0.1",18815))==0; s.close(); assert not occupied, "dedicated probe port is already in use"'
"$ASR_ENV/bin/python" "$REPO_ROOT/scripts/analysis/prepare_xturnix_short_latency.py" \
  --inputs "$INPUTS" --labels "$LABELS" --config "$CONFIG" \
  --output "$OUT/inputs" --download-audio

setsid "$ASR_ENV/bin/python" -u "$REPO_ROOT/scripts/remote/nemotron_asr_service.py" \
  --model "$ASR_MODEL" --warmup-audio "$ROOT/dataset/fleurs_en_us/audio/dev/786465049904960526.wav" \
  --warmup-timeout 180 --port "$PORT" > "$OUT/asr.log" 2>&1 &
ASR_PID=$!
health_deadline=$((SECONDS + 420))
ready=false
while [ "$SECONDS" -lt "$health_deadline" ]; do
  kill -0 "$ASR_PID" 2>/dev/null || { echo "ASR service exited" >&2; exit 1; }
  if "$PT_ENV/bin/python" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:18815/health", timeout=2).read()' >/dev/null 2>&1; then ready=true; break; fi
  sleep 5
done
[ "$ready" = true ] || { echo "ASR health deadline exceeded" >&2; exit 1; }
(
  while kill -0 "$ASR_PID" 2>/dev/null; do
    nvidia-smi --query-gpu=timestamp,memory.used --format=csv,noheader,nounits >> "$OUT/gpu_samples.csv"
    used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | awk 'BEGIN {m=0} {if ($1>m) m=$1} END {print m}')"
    size="$(du -sk "$OUT" | awk '{print $1}')"
    if [ "$used" -gt 22528 ] || [ "$size" -gt 1258291 ]; then
      printf 'resource_stop gpu_mib=%s output_kib=%s\n' "$used" "$size" > "$OUT/resource_stop.txt"
      kill -TERM "$$"
      exit 1
    fi
    sleep 2
  done
) &
MONITOR_PID=$!

setsid timeout --signal=TERM --kill-after=30s 6000 "$PT_ENV/bin/python" -u \
  "$REPO_ROOT/scripts/remote/xturnix_time_control_probe.py" \
  --manifest "$OUT/inputs/manifest.json" --config "$CONFIG" \
  --model "$PT_MODEL" --model-lock "$ROOT/models/xturnix-pt.lock.json" \
  --asr-url "http://127.0.0.1:$PORT" --output "$OUT/trace" &
PROBE_PID=$!
wait "$PROBE_PID"
PROBE_PID=""
"$PT_ENV/bin/python" "$REPO_ROOT/scripts/analysis/compare_xturnix_latency.py" \
  --manifest "$OUT/inputs/manifest.json" --run "$OUT/trace" \
  --config "$CONFIG" --output "$OUT/comparison"
