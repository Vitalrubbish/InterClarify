#!/usr/bin/env bash
# Run one bounded XTurnix FLEURS job: preflight, ASR service, replay and offline score.
#
# Modes:
#   smoke:  verify data/models, replay one dev protocol sample and five test samples.
#   formal: verify data/models, replay one dev protocol sample and the frozen 100 test
#           samples, then score the test replay offline after the service is stopped.
set -euo pipefail

# The cluster wrapper rewrites the literal token "JOB" in a submitted command, so
# variables passed through `vc submit --cmd` must not contain it.  The old names
# remain accepted for direct/manual execution outside the scheduler.
MODE="${XTURNIX_MODE:-${XTURNIX_JOB_MODE:-smoke}}"
RUN_ID="${XTURNIX_RUN_ID:-${XTURNIX_JOB_RUN_ID:-}}"
ROOT="${XTURNIX_ROOT:-$HOME/interclarify-xturnix-fleurs}"
REPO_ROOT="${PARATHINK_ROOT:-${INTERCLARIFY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}}"
ENTRY="$REPO_ROOT/scripts/remote/xturnix_fleurs_test.py"
CONFIG="$REPO_ROOT/configs/xturnix_fleurs_test.json"
ENV_DIR="${XTURNIX_ENV_DIR:-$ROOT/envs/xturnix}"
ENV_PY="$ENV_DIR/bin/python"
DATA_PY="${XTURNIX_DATA_PYTHON:-$HOME/miniconda3/envs/interclarify-x2-turn-data/bin/python}"
ASR_MODEL="${XTURNIX_ASR_MODEL:-$HOME/interclarify-asr-selection/models/nemotron_en}"
XTURNIX_MODEL="${XTURNIX_MODEL:-$ROOT/models/xturnix-pt}"
DATASET="$ROOT/dataset/fleurs_en_us"
WARMUP_AUDIO="$DATASET/audio/dev/786465049904960526.wav"
ASR_PORT="${XTURNIX_ASR_PORT:-18805}"
MIN_FREE_GIB=30
TRACE_LIMIT_GIB=2
EXPECTED_CONFIG_SHA256="ae121007859ab3d7c6d07d38688082bffb0a6803cda3490b0c8b34f6b111fb43"

case "$MODE" in
  smoke|formal) ;;
  *) echo "usage: XTURNIX_MODE={smoke|formal} $0" >&2; exit 2 ;;
esac
[ -n "$RUN_ID" ] || { echo "XTURNIX_RUN_ID is required" >&2; exit 2; }
case "$RUN_ID" in
  *[!A-Za-z0-9._-]*|.*) echo "invalid run id: $RUN_ID" >&2; exit 2 ;;
esac
if [ "$MODE" = smoke ]; then
  EXPECTED_PLANNED=5
else
  EXPECTED_PLANNED=100
fi

RUN_DIR="$ROOT/runs/$RUN_ID"
JOB_DIR="$RUN_DIR/job"
SERVER_PID=""
MONITOR_PID=""
SERVICE_STOPPED_ORDERLY="unknown"

log() { printf '[run_xturnix_fleurs_job] %s\n' "$*"; }
die() { printf '[run_xturnix_fleurs_job] error: %s\n' "$*" >&2; exit 1; }
free_gib() { df -Pk "$1" | awk 'NR==2 {printf "%.2f", $4/1024/1024}'; }

stop_monitor() {
  if [ -n "$MONITOR_PID" ]; then
    kill "$MONITOR_PID" 2>/dev/null || true
    wait "$MONITOR_PID" 2>/dev/null || true
    MONITOR_PID=""
  fi
}

stop_service() {
  if [ -z "$SERVER_PID" ]; then
    return 0
  fi
  if [ -r "/proc/$SERVER_PID/status" ]; then
    cat "/proc/$SERVER_PID/status" > "$JOB_DIR/service_process_status.txt"
  fi
  kill -TERM -- "-$SERVER_PID" 2>/dev/null || true
  for _ in $(seq 1 30); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      SERVICE_STOPPED_ORDERLY="true"
      break
    fi
    sleep 1
  done
  if [ "$SERVICE_STOPPED_ORDERLY" != "true" ]; then
    SERVICE_STOPPED_ORDERLY="false"
    printf 'ASR service required SIGKILL after 30 s\n' > "$JOB_DIR/service_force_killed.txt"
    kill -KILL -- "-$SERVER_PID" 2>/dev/null || true
  fi
  wait "$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""
  printf '%s\n' "$SERVICE_STOPPED_ORDERLY" > "$JOB_DIR/service_stopped_orderly.txt"
}

cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  stop_monitor
  stop_service
  {
    printf 'exit_code=%s\n' "$rc"
    pgrep -u "$(id -u)" -af 'nemotron_asr_service.py' || true
    nvidia-smi --query-gpu=timestamp,index,memory.used,utilization.gpu --format=csv 2>/dev/null || true
  } > "$JOB_DIR/post_cleanup.txt" 2>&1 || true
  printf '%s\n' "$rc" > "$JOB_DIR/exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -e "$RUN_DIR" ] && [ -n "$(ls -A "$RUN_DIR" 2>/dev/null)" ]; then
  die "run directory already exists and is not empty: $RUN_DIR"
fi
mkdir -p "$JOB_DIR"
exec > >(tee -a "$JOB_DIR/job.log") 2>&1

START_FREE="$(free_gib "$ROOT")"
log "mode=$MODE run_id=$RUN_ID root=$ROOT source=$REPO_ROOT"
log "start_free_gib=$START_FREE"

# Preflight: frozen source/config, environment, inputs and model inventory.
[ -x "$ENV_PY" ] || die "missing XTurnix environment: $ENV_PY"
[ -x "$DATA_PY" ] || die "missing data/scoring environment: $DATA_PY"
[ -f "$ENTRY" ] || die "missing replay entry: $ENTRY"
[ -f "$CONFIG" ] || die "missing frozen config: $CONFIG"
ACTUAL_CONFIG_SHA="$(sha256sum "$CONFIG" | awk '{print $1}')"
[ "$ACTUAL_CONFIG_SHA" = "$EXPECTED_CONFIG_SHA256" ] \
  || die "config $CONFIG sha256=$ACTUAL_CONFIG_SHA differs from the XTX-002 freeze"
[ -f "$DATASET/manifest.json" ] || die "missing frozen manifest: $DATASET/manifest.json"
[ -f "$WARMUP_AUDIO" ] || die "missing dev warmup audio: $WARMUP_AUDIO"
[ -f "$XTURNIX_MODEL/turn_pipeline.py" ] || die "missing XTurnix model: $XTURNIX_MODEL"
[ -f "$ASR_MODEL/model.safetensors" ] || die "missing ASR model: $ASR_MODEL"
awk -v have="$START_FREE" -v need="$MIN_FREE_GIB" 'BEGIN {exit !(have >= need)}' \
  || die "free space ${START_FREE} GiB is below ${MIN_FREE_GIB} GiB"
if command -v ss >/dev/null 2>&1; then
  ss -ltn | awk '{print $4}' | grep -Eq "[:.]${ASR_PORT}\$" \
    && die "ASR port $ASR_PORT is already in use"
fi

COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
DIRTY="$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | wc -l | awk '{print $1}')"
printf '%s\n' "$COMMIT" > "$JOB_DIR/source_commit.txt"
printf '%s\n' "$ACTUAL_CONFIG_SHA" > "$JOB_DIR/config_sha256.txt"
"$ENV_PY" - "$REPO_ROOT" "$MODE" "$RUN_ID" "$COMMIT" "$DIRTY" "$START_FREE" \
  "$MIN_FREE_GIB" "$TRACE_LIMIT_GIB" "$EXPECTED_PLANNED" "$ASR_PORT" \
  "$JOB_DIR/limits.json" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

repo, mode, run_id, commit, dirty, free, min_free, trace_limit, planned, port, output = sys.argv[1:]
payload = {
    "schema": "xtx-005-job-limits-v1",
    "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "mode": mode,
    "run_id": run_id,
    "source_commit": commit,
    "source_dirty_entries": int(dirty),
    "start_free_gib": float(free),
    "limits": {
        "max_gpu": 1,
        "max_gpu_memory_gib": 24,
        "max_cpu": 8,
        "max_ram_gib": 32,
        "batch_size": 1,
        "max_hours": 4,
        "min_free_gib": int(min_free),
        "max_trace_gib": int(trace_limit),
        "scoring_workers": 2,
        "asr_port": int(port),
    },
    "expected_planned_test_samples": int(planned),
    "repo_root": repo,
}
Path(output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

log "verifying frozen dataset"
"$DATA_PY" "$ENTRY" verify-data --root "$ROOT" > "$JOB_DIR/verify_data.json"
log "verifying frozen environment and model inventory"
bash "$REPO_ROOT/scripts/remote/setup_xturnix_env.sh" verify > "$JOB_DIR/model_verify.log" 2>&1
cp "$ROOT/environment/model_verification.json" "$JOB_DIR/model_verification.json"
cp "$ROOT/environment/verify_report.json" "$JOB_DIR/verify_report.json"

nvidia-smi --query-gpu=index,name,uuid,driver_version,memory.total \
  --format=csv > "$JOB_DIR/gpu.csv"
nvidia-smi --query-gpu=timestamp,index,memory.used,utilization.gpu --format=csv -l 1 \
  > "$JOB_DIR/gpu_samples.csv" &
MONITOR_PID=$!
"$ENV_PY" - "$JOB_DIR/resources.json" "$(nproc)" <<'PY'
import json
import sys
from pathlib import Path

output, cpus = sys.argv[1], int(sys.argv[2])
memory_kib = 0
for line in Path("/proc/meminfo").read_text().splitlines():
    if line.startswith("MemTotal:"):
        memory_kib = int(line.split()[1])
        break
Path(output).write_text(
    json.dumps(
        {"visible_cpu": cpus, "mem_total_kib": memory_kib,
         "mem_total_gib": round(memory_kib / 1024**2, 2)},
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY

export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=8
export MKL_NUM_THREADS=8

log "starting frozen Nemotron service on port $ASR_PORT"
setsid "$ENV_PY" -u "$REPO_ROOT/scripts/remote/nemotron_asr_service.py" \
  --model "$ASR_MODEL" --warmup-audio "$WARMUP_AUDIO" --warmup-timeout 60 \
  --port "$ASR_PORT" > "$JOB_DIR/asr_service.log" 2>&1 &
SERVER_PID=$!

log "waiting for real ASR readiness"
"$ENV_PY" - "$ASR_PORT" "$SERVER_PID" "$JOB_DIR/health.json" <<'PY'
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

port, pid, output = int(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
deadline = time.monotonic() + 240
while time.monotonic() < deadline:
    try:
        os.kill(pid, 0)
    except OSError:
        raise SystemExit("ASR service exited before becoming ready")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            value = json.load(response)
    except OSError:
        time.sleep(1)
        continue
    if value.get("status") != "ok" or value.get("warmup_sessions") != 2:
        raise SystemExit(f"unexpected ASR health: {value!r}")
    output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False))
    break
else:
    raise SystemExit("ASR service did not become ready within 240 s")
PY

log "replaying one dev protocol sample"
"$ENV_PY" -u "$ENTRY" replay --root "$ROOT" --config "$CONFIG" \
  --output "$RUN_DIR/replay-dev" --split dev --limit 1 \
  --model "$XTURNIX_MODEL" --asr-url "http://127.0.0.1:$ASR_PORT" \
  > "$JOB_DIR/replay_dev.json"

log "replaying $EXPECTED_PLANNED test samples ($MODE)"
"$ENV_PY" -u "$ENTRY" replay --root "$ROOT" --config "$CONFIG" \
  --output "$RUN_DIR/replay" --split test --limit "$EXPECTED_PLANNED" \
  --model "$XTURNIX_MODEL" --asr-url "http://127.0.0.1:$ASR_PORT" \
  > "$JOB_DIR/replay_test.json"

log "stopping ASR service before offline scoring"
stop_service
stop_monitor

log "scoring saved traces offline"
"$DATA_PY" "$ENTRY" score --root "$ROOT" --input "$RUN_DIR/replay" \
  --output "$RUN_DIR/replay/score" --workers 2 > "$JOB_DIR/score_test.json"
"$DATA_PY" "$ENTRY" score --root "$ROOT" --input "$RUN_DIR/replay-dev" \
  --output "$RUN_DIR/replay-dev/score" --workers 2 > "$JOB_DIR/score_dev.json"

END_FREE="$(free_gib "$ROOT")"
log "building job summary (end_free_gib=$END_FREE)"
"$ENV_PY" - "$RUN_DIR" "$JOB_DIR" "$MODE" "$RUN_ID" "$COMMIT" "$START_FREE" \
  "$END_FREE" "$EXPECTED_PLANNED" "$TRACE_LIMIT_GIB" "$SERVICE_STOPPED_ORDERLY" <<'PY'
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

(run_dir, job_dir, mode, run_id, commit, start_free, end_free,
 expected_planned, trace_limit_gib, orderly) = sys.argv[1:]
run_dir, job_dir = Path(run_dir), Path(job_dir)
expected_planned = int(expected_planned)
trace_limit = int(trace_limit_gib) * 1024**3


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def trace_bytes(root):
    return sum(path.stat().st_size for path in root.rglob("*.jsonl") if path.is_file())


status = read(run_dir / "replay" / "status.json")
report = read(run_dir / "replay" / "replay_report.json")
score = read(run_dir / "replay" / "score" / "summary.json")
dev_status = read(run_dir / "replay-dev" / "status.json")
dev_score = read(run_dir / "replay-dev" / "score" / "summary.json")
counts = status["counts"]
if counts["planned"] != expected_planned:
    raise SystemExit(
        f"planned test samples {counts['planned']} != expected {expected_planned}"
    )
if counts["completed"] + counts["failed"] + counts["skipped"] != counts["planned"]:
    raise SystemExit("replay status does not account for every planned sample")
if score["main_metrics"]["denominator"] != expected_planned:
    raise SystemExit(
        f"score denominator {score['main_metrics']['denominator']} != {expected_planned}"
    )
if mode == "smoke" and counts["completed"] != expected_planned:
    raise SystemExit(f"smoke requires all samples completed, got {counts}")
if dev_status["counts"]["planned"] != 1 or dev_status["counts"]["completed"] != 1:
    raise SystemExit(f"dev protocol sample did not complete: {dev_status['counts']}")
test_trace_bytes = trace_bytes(run_dir / "replay" / "traces")
dev_trace_bytes = trace_bytes(run_dir / "replay-dev" / "traces")
if test_trace_bytes + dev_trace_bytes > trace_limit:
    raise SystemExit(
        f"trace bytes {test_trace_bytes + dev_trace_bytes} exceed {trace_limit}"
    )

rss_kib = None
service_status = job_dir / "service_process_status.txt"
if service_status.is_file():
    for line in service_status.read_text().splitlines():
        if line.startswith("VmHWM:"):
            rss_kib = int(line.split()[1])

gpu_peak_mib = None
samples = job_dir / "gpu_samples.csv"
if samples.is_file():
    values = []
    for line in samples.read_text().splitlines()[1:]:
        columns = [item.strip() for item in line.split(",")]
        if len(columns) >= 3 and columns[2].isdigit():
            values.append(int(columns[2]))
    gpu_peak_mib = max(values) if values else None

leftover = subprocess.run(
    ["pgrep", "-u", str(__import__("os").getuid()), "-f", "nemotron_asr_service.py"],
    capture_output=True,
    text=True,
    check=False,
)
job_summary = {
    "schema": "xtx-005-job-summary-v1",
    "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "mode": mode,
    "run_id": run_id,
    "source_commit": commit,
    "paths": {
        "run": str(run_dir),
        "replay_test": str(run_dir / "replay"),
        "replay_dev": str(run_dir / "replay-dev"),
        "score_test": str(run_dir / "replay" / "score" / "summary.json"),
        "score_dev": str(run_dir / "replay-dev" / "score" / "summary.json"),
    },
    "replay": {
        "counts": counts,
        "fatal_reason": report.get("fatal_reason"),
        "elapsed_seconds": report.get("elapsed_seconds"),
    },
    "dev_protocol": {
        "counts": dev_status["counts"],
        "elapsed_seconds": read(run_dir / "replay-dev" / "replay_report.json").get(
            "elapsed_seconds"
        ),
    },
    "score": {
        "counts": score["counts"],
        "main_metrics": score["main_metrics"],
        "wer": score["wer"],
        "chain_estimate": score["chain_estimate"],
    },
    "dev_score": {
        "counts": dev_score["counts"],
        "main_metrics": dev_score["main_metrics"],
    },
    "resources": {
        "start_free_gib": float(start_free),
        "end_free_gib": float(end_free),
        "service_peak_rss_kib": rss_kib,
        "gpu_peak_memory_mib": gpu_peak_mib,
        "test_trace_bytes": test_trace_bytes,
        "dev_trace_bytes": dev_trace_bytes,
        "service_stopped_orderly": orderly == "true",
    },
    "leftover_asr_processes": leftover.stdout.strip().splitlines(),
}
if leftover.returncode == 0:
    raise SystemExit(
        f"leftover ASR service process after cleanup: {leftover.stdout.strip()}"
    )
if orderly != "true":
    raise SystemExit("ASR service did not stop orderly within 30 s")
(job_dir / "job_summary.json").write_text(
    json.dumps(job_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(job_summary, ensure_ascii=False, indent=2))
PY

log "job completed; evidence=$RUN_DIR"
