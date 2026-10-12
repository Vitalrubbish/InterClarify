#!/usr/bin/env bash
# Run Stage A4 acceptance with official DuplexCascade, Qwen3-ASR, and MOSS-TTS.
set -uo pipefail

TASK_ROOT="${INTERCLARIFY_DUPLEX_ROOT:?set independent synced source directory}"
ROUND1_ROOT="${XTALK_ROUND1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1}"
MODEL_ROOT="${XTALK_ROUND1_MODEL_ROOT:-$ROUND1_ROOT/models}"
MODEL_HOME="${DUPLEX_MODEL_HOME:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope}"
CHECKPOINT="${DUPLEX_CHECKPOINT:-$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28}"
BASE_MODEL="${DUPLEX_BASE_MODEL:-$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a}"
CONDA_SH="${CONDA_SH:-/opt/conda/etc/profile.d/conda.sh}"
MODEL_ENV="${DUPLEX_MODEL_ENV:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/interclarify-dev}"
CLIENT_ENV="${DUPLEX_CLIENT_ENV:-xtalk-round1-client}"
TOOLS_ENV="${DUPLEX_TOOLS_ENV:-xtalk-round1-tools}"
ASR_ENV="${DUPLEX_ASR_ENV:-xtalk-round1-asr}"
MOSS_ENV="${DUPLEX_MOSS_ENV:-xtalk-round1-moss}"
MODEL_PORT="${DUPLEX_MODEL_PORT:-8006}"
ASR_PORT="${DUPLEX_ASR_PORT:-8005}"
TTS_PORT="${DUPLEX_TTS_PORT:-8004}"
TAG="${DUPLEX_A4_TAG:-$(date -u +%Y%m%dT%H%M%SZ)}"
ARTIFACT_ROOT="${DUPLEX_A4_ARTIFACT_ROOT:-$TASK_ROOT/artifacts/a4}"
RUN_DIR="${DUPLEX_A4_OUTPUT:-$ARTIFACT_ROOT/$TAG}"
INPUT_WAV="${DUPLEX_A4_INPUT:-$ROUND1_ROOT/audio/request.wav}"
INTERRUPTION_WAV="${DUPLEX_A4_INTERRUPPTION_AUDIO:-$ROUND1_ROOT/audio/scenarios/barge_in_stop_02_barge_in.wav}"
REQUIRE_INTERRUPTION="${DUPLEX_A4_REQUIRE_INTERRUPTION:-0}"
FDB_INPUT_ROOT="${DUPLEX_A4_FDB_INPUT_ROOT:-}"
FDB_OUTPUT_ROOT="${DUPLEX_A4_FDB_OUTPUT_ROOT:-$RUN_DIR/fdb}"
FDB_LIMIT="${DUPLEX_A4_FDB_LIMIT:-5}"
FDB_REPO="${DUPLEX_A4_FDB_REPO:-}"
FDB_ENV="${DUPLEX_A4_FDB_ENV:-full-duplex-bench}"
FDB_TASK="${DUPLEX_A4_FDB_TASK:-}"
FDB_COMMIT="${DUPLEX_A4_FDB_COMMIT:-3e799c45a045256f47d5f1c9cda90157e2d2ec9e}"
LONG_ROUNDS="${DUPLEX_A4_ROUNDS:-3}"
REQUIRE_COMPLETE="${DUPLEX_A4_REQUIRE_COMPLETE:-0}"
ROUND1_PY="$TASK_ROOT/scripts/remote/run_xtalk_round1.py"

# shellcheck disable=SC1090
source "$CONDA_SH"
if [ -e "$RUN_DIR" ]; then
  echo "A4 output directory already exists: $RUN_DIR" >&2
  exit 2
fi
mkdir -p "$RUN_DIR/logs" "$RUN_DIR/tests" "$RUN_DIR/services"
cd "$TASK_ROOT"
export PYTHONPATH="$TASK_ROOT/xtalk/src:$TASK_ROOT"
export PYTHONNOUSERSITE=1
export TOKENIZERS_PARALLELISM=false
export XTALK_MOSS_SERVICE_ROOT="${XTALK_MOSS_SERVICE_ROOT:-$ROUND1_ROOT/moss-service}"
export XTALK_MOSS_SOURCE_ROOT="${XTALK_MOSS_SOURCE_ROOT:-$ROUND1_ROOT/moss-source}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/tmp/interclarify-a4-cache}"
export TORCHINDUCTOR_CACHE_DIR="${TORCHINDUCTOR_CACHE_DIR:-$XDG_CACHE_HOME/torchinductor}"
export TRITON_CACHE_DIR="${TRITON_CACHE_DIR:-$XDG_CACHE_HOME/triton}"
mkdir -p "$XDG_CACHE_HOME" "$TORCHINDUCTOR_CACHE_DIR" "$TRITON_CACHE_DIR"

IFS=',' read -r -a JOB_GPUS <<< "${CUDA_VISIBLE_DEVICES:-0,1,2}"
PIDS=()
FAILURES=0

record_step() {
  local name="$1" status="$2" rc="$3" reason="${4:-}"
  conda run -n "$CLIENT_ENV" python -c 'import json,sys; print(json.dumps({"step":sys.argv[1],"status":sys.argv[2],"rc":int(sys.argv[3]),"reason":sys.argv[4]}))' "$name" "$status" "$rc" "$reason" >> "$RUN_DIR/steps.jsonl"
  printf '[a4] step=%s status=%s rc=%s %s\n' "$name" "$status" "$rc" "$reason" | tee -a "$RUN_DIR/run.log"
  if [ "$status" = "FAIL" ]; then
    FAILURES=$((FAILURES + 1))
  fi
}

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

if [ ! -f "$TASK_ROOT/source_manifest.json" ]; then
  record_step source_manifest FAIL 1 "missing source_manifest.json"
  exit 1
fi
RC=0
conda run -n "$CLIENT_ENV" python -c 'import hashlib,json,pathlib; root=pathlib.Path("."); m=json.loads((root/"source_manifest.json").read_text()); missing=[n for n in m["files"] if not (root/n).is_file()]; bad=[n for n,d in m["files"].items() if (root/n).is_file() and hashlib.sha256((root/n).read_bytes()).hexdigest()!=d]; assert not missing and not bad, {"missing":missing,"bad":bad}; print(json.dumps({"source_verified":True,"files":len(m["files"]),"interclarify_commit":m.get("interclarify_commit"),"xtalk_parent":m.get("xtalk_parent"),"snapshot":m.get("snapshot")}))' > "$RUN_DIR/source_check.json" 2> "$RUN_DIR/logs/source_check.log" || RC=$?
[ "$RC" -eq 0 ] && record_step source_manifest PASS 0 || record_step source_manifest FAIL "$RC" "manifest mismatch"
[ "$RC" -eq 0 ] || exit "$FAILURES"

{
  git rev-parse HEAD
  git status --short --branch
  git -C xtalk rev-parse HEAD
  git -C xtalk status --short --branch
} > "$RUN_DIR/git.txt" 2>&1
RC=0
nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv > "$RUN_DIR/gpu.csv" 2>&1 || RC=$?
GPU_COUNT="$(nvidia-smi -L 2>/dev/null | wc -l)"
[ "$GPU_COUNT" -ge 3 ] && [ "${#JOB_GPUS[@]}" -ge 3 ] || RC=1
[ "$RC" -eq 0 ] && record_step gpu_allocation PASS 0 || record_step gpu_allocation FAIL "$RC" "A4 requires three visible GPUs"

RC=0
for asset in "$CHECKPOINT" "$BASE_MODEL" "$MODEL_ROOT/models.lock.json" "$INPUT_WAV" "$INTERRUPTION_WAV" "$ROUND1_ROOT/audio/reference.wav"; do
  [ -e "$asset" ] || { printf 'missing asset: %s\n' "$asset" >> "$RUN_DIR/logs/assets.log"; RC=1; }
done
[ "$RC" -eq 0 ] && record_step assets PASS 0 || record_step assets FAIL "$RC" "required model or audio asset is missing"

cp "$MODEL_ROOT/models.lock.json" "$RUN_DIR/models.lock.json"
RC=0
{
  if ! conda run -p "$MODEL_ENV" python -c 'import torch,transformers,peft; print("model",torch.__version__,transformers.__version__,peft.__version__)'; then RC=1; fi
  if ! conda run -n "$ASR_ENV" python -c 'import qwen_asr,transformers; print("asr",transformers.__version__)'; then RC=1; fi
  if ! conda run -n "$MOSS_ENV" python -c 'import torch,transformers; print("tts",torch.__version__,transformers.__version__)'; then RC=1; fi
  if ! conda run -n "$CLIENT_ENV" python -c 'import xtalk; print("client",xtalk.__file__)'; then RC=1; fi
} > "$RUN_DIR/environment.txt" 2>&1
[ "$RC" -eq 0 ] && record_step environment PASS 0 || record_step environment FAIL "$RC" "conda import failed"
[ "$FAILURES" -eq 0 ] || exit "$FAILURES"

setsid nvidia-smi --query-gpu=timestamp,index,memory.used,memory.total,utilization.gpu --format=csv,noheader -l 5 \
  > "$RUN_DIR/gpu_samples.csv" 2>&1 &
PIDS+=("$!")

ROUND1_CONFIG="$RUN_DIR/xtalk_round1.yaml"
RC=0
conda run -n "$TOOLS_ENV" python -c 'import sys,yaml; source,target=sys.argv[1:3]; cfg=yaml.safe_load(open(source)); cfg["services"]["asr"]["port"]=int(sys.argv[3]); cfg["services"]["tts"]["port"]=int(sys.argv[4]); yaml.safe_dump(cfg,open(target,"w"),sort_keys=False)' \
  configs/xtalk_round1.yaml "$ROUND1_CONFIG" "$ASR_PORT" "$TTS_PORT" \
  > "$RUN_DIR/logs/round1_config.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step runtime_config PASS 0 || record_step runtime_config FAIL "$RC"
[ "$RC" -eq 0 ] || exit "$FAILURES"

RC=0
(cd "$TASK_ROOT/xtalk" && conda run -n "$CLIENT_ENV" env PYTHONPATH=src python -m unittest \
  tests.test_duplex_protocol tests.test_duplex_observability \
  tests.test_turn_detector_manager tests.test_llm_agent_persistent_stream \
  tests.test_response_identity tests.test_tool_call_playback_barrier \
  tests.test_tts_streaming_playback_alignment) \
  > "$RUN_DIR/tests/a1.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step a1_regression PASS 0 || record_step a1_regression FAIL "$RC"

RC=0
(cd "$TASK_ROOT/xtalk" && conda run -n "$CLIENT_ENV" env PYTHONPATH=src python -m unittest tests.test_duplex_runtime) \
  > "$RUN_DIR/tests/a2_a3.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step a2_a3_regression PASS 0 || record_step a2_a3_regression FAIL "$RC"

RC=0
conda run -n "$CLIENT_ENV" env PYTHONPATH="$TASK_ROOT/xtalk/src:$TASK_ROOT" python -m unittest \
  tests.test_duplex_a4_replay tests.test_duplex_model_service \
  > "$RUN_DIR/tests/a4_driver.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step a4_driver_regression PASS 0 || record_step a4_driver_regression FAIL "$RC"
[ "$FAILURES" -eq 0 ] || exit "$FAILURES"

CUDA_VISIBLE_DEVICES="${JOB_GPUS[0]}" setsid conda run --no-capture-output -p "$MODEL_ENV" \
  python scripts/remote/duplex_model_service.py --checkpoint "$CHECKPOINT" \
  --base-model "$BASE_MODEL" --port "$MODEL_PORT" \
  > "$RUN_DIR/services/duplex_model.log" 2>&1 &
PIDS+=("$!")
RC=0
wait_http "http://127.0.0.1:$MODEL_PORT/health" 900 "$RUN_DIR/model_health.json" "$RUN_DIR/services/duplex_model.log" "${PIDS[-1]}" || RC=$?
[ "$RC" -eq 0 ] && record_step duplex_model_service PASS 0 || record_step duplex_model_service FAIL "$RC"
[ "$RC" -eq 0 ] || exit "$FAILURES"

CUDA_VISIBLE_DEVICES="${JOB_GPUS[1]}" setsid conda run --no-capture-output -n "$TOOLS_ENV" \
  python "$ROUND1_PY" --config "$ROUND1_CONFIG" --model-root "$MODEL_ROOT" serve asr --gpu-index 0 \
  > "$RUN_DIR/services/asr.log" 2>&1 &
PIDS+=("$!")
RC=0
wait_http "http://127.0.0.1:$ASR_PORT/health" 1200 "$RUN_DIR/asr_health.json" "$RUN_DIR/services/asr.log" "${PIDS[-1]}" || RC=$?
[ "$RC" -eq 0 ] && record_step asr_service PASS 0 || record_step asr_service FAIL "$RC"

CUDA_VISIBLE_DEVICES="${JOB_GPUS[2]}" setsid conda run --no-capture-output -n "$TOOLS_ENV" \
  python "$ROUND1_PY" --config "$ROUND1_CONFIG" --model-root "$MODEL_ROOT" serve tts --gpu-index 0 \
  > "$RUN_DIR/services/tts.log" 2>&1 &
PIDS+=("$!")
RC=0
wait_http "http://127.0.0.1:$TTS_PORT/health" 1800 "$RUN_DIR/tts_health.json" "$RUN_DIR/services/tts.log" "${PIDS[-1]}" || RC=$?
[ "$RC" -eq 0 ] && record_step tts_service PASS 0 || record_step tts_service FAIL "$RC"
[ "$FAILURES" -eq 0 ] || exit "$FAILURES"

RC=0
conda run --no-capture-output -n "$CLIENT_ENV" python scripts/remote/duplex_runtime_smoke.py \
  --model-url "http://127.0.0.1:$MODEL_PORT" --output "$RUN_DIR/runtime_smoke" \
  > "$RUN_DIR/logs/runtime_smoke.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step official_model_smoke PASS 0 || record_step official_model_smoke FAIL "$RC"

RUNTIME_CONFIG="$RUN_DIR/a4_runtime.json"
RC=0
conda run -n "$CLIENT_ENV" python -c 'import json,sys,pathlib; cfg=json.load(open(sys.argv[1])); cfg["asr"]["params"]["base_url"]="http://127.0.0.1:"+sys.argv[3]; cfg["tts"]["params"]["base_url"]="http://127.0.0.1:"+sys.argv[4]; cfg["tts"]["params"]["voices"][0]["path"]=sys.argv[5]; sc=cfg.setdefault("service_config",{}); sc["duplex_model_url"]="http://127.0.0.1:"+sys.argv[2]; json.dump(cfg,open(sys.argv[6],"w"),indent=2)' \
  configs/xtalk_duplex_runtime.json "$MODEL_PORT" "$ASR_PORT" "$TTS_PORT" \
  "$ROUND1_ROOT/audio/reference.wav" "$RUNTIME_CONFIG" || RC=$?
[ "$RC" -eq 0 ] || { record_step runtime_json FAIL "$RC"; exit "$FAILURES"; }

RC=0
EXTRA=()
[ "$REQUIRE_INTERRUPTION" = "1" ] && EXTRA+=(--require-interruption)
conda run --no-capture-output -n "$CLIENT_ENV" env PYTHONPATH="$TASK_ROOT/xtalk/src:$TASK_ROOT" \
  python scripts/remote/duplex_a4_replay.py --config "$RUNTIME_CONFIG" \
  --model-url "http://127.0.0.1:$MODEL_PORT" --audio "$INPUT_WAV" \
  --interruption-audio "$INTERRUPTION_WAV" --out "$RUN_DIR/replay" --rounds "$LONG_ROUNDS" "${EXTRA[@]}" \
  > "$RUN_DIR/logs/replay.log" 2>&1 || RC=$?
REPLAY_STATUS="$(conda run -n "$CLIENT_ENV" python -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status","FAIL"))' "$RUN_DIR/replay/summary.json" 2>/dev/null || echo FAIL)"
case "$REPLAY_STATUS" in
  PASS) record_step real_audio_replay PASS 0 ;;
  INCONCLUSIVE) record_step real_audio_replay INCONCLUSIVE "$RC" "model did not cover every semantic scenario" ;;
  *) record_step real_audio_replay FAIL "$RC" "inspect replay reports" ;;
esac

if [ -n "$FDB_INPUT_ROOT" ] && [ -d "$FDB_INPUT_ROOT" ]; then
  RC=0
  conda run --no-capture-output -n "$CLIENT_ENV" env PYTHONPATH="$TASK_ROOT/xtalk/src:$TASK_ROOT" \
    python scripts/remote/duplex_a4_replay.py --config "$RUNTIME_CONFIG" \
    --model-url "http://127.0.0.1:$MODEL_PORT" --out "$RUN_DIR/fdb_driver" \
    --fdb-input-root "$FDB_INPUT_ROOT" --fdb-output-root "$FDB_OUTPUT_ROOT" \
    --fdb-limit "$FDB_LIMIT" > "$RUN_DIR/logs/fdb_inference.log" 2>&1 || RC=$?
  [ "$RC" -eq 0 ] && record_step fdb_inference PASS 0 || record_step fdb_inference FAIL "$RC" "inspect fdb_driver/fdb_summary.json"
else
  record_step fdb_inference BLOCKED 0 "set DUPLEX_A4_FDB_INPUT_ROOT after staging FDB v1/v1.5"
fi

stop_services
PIDS=()

if [ -n "$FDB_REPO" ] && [ -d "$FDB_REPO/v1_v1.5" ] && [ -n "$FDB_TASK" ] && [ -d "$FDB_OUTPUT_ROOT" ]; then
  RC=0
  git -C "$FDB_REPO" rev-parse HEAD > "$RUN_DIR/fdb_commit.txt"
  if [ "$(cat "$RUN_DIR/fdb_commit.txt")" != "$FDB_COMMIT" ] || ! git -C "$FDB_REPO" diff --quiet HEAD; then
    record_step fdb_revision FAIL 1 "FDB checkout differs from fixed commit"
    exit "$FAILURES"
  fi
  ASR_TASK=default
  [ "$FDB_TASK" = "user_interruption" ] && ASR_TASK=user_interruption
  conda run --no-capture-output -n "$FDB_ENV" python "$FDB_REPO/v1_v1.5/get_transcript/asr.py" \
    --root_dir "$FDB_OUTPUT_ROOT" --task "$ASR_TASK" --audio_name output.wav \
    > "$RUN_DIR/logs/fdb_alignment.log" 2>&1 || RC=$?
  if find "$FDB_OUTPUT_ROOT" -name clean_output.wav -print -quit | grep -q .; then
    conda run --no-capture-output -n "$FDB_ENV" python "$FDB_REPO/v1_v1.5/get_transcript/asr.py" \
      --root_dir "$FDB_OUTPUT_ROOT" --task "$ASR_TASK" --audio_name clean_output.wav \
      >> "$RUN_DIR/logs/fdb_alignment.log" 2>&1 || RC=$?
  fi
  if [ "$RC" -eq 0 ] && [ "$FDB_TASK" = "behavior" ]; then
    conda run --no-capture-output -n "$FDB_ENV" python "$FDB_REPO/v1_v1.5/evaluation/get_timing.py" --root_dir "$FDB_OUTPUT_ROOT" > "$RUN_DIR/logs/fdb_timing.log" 2>&1 || RC=$?
  fi
  if [ "$RC" -eq 0 ]; then
    (cd "$RUN_DIR" && conda run --no-capture-output -n "$FDB_ENV" \
      python "$FDB_REPO/v1_v1.5/evaluation/evaluate.py" --task "$FDB_TASK" --root_dir "$FDB_OUTPUT_ROOT") \
      > "$RUN_DIR/logs/fdb_evaluation.log" 2>&1 || RC=$?
  fi
  [ "$RC" -eq 0 ] && record_step fdb_scoring PASS 0 || record_step fdb_scoring FAIL "$RC" "official FDB alignment or evaluation failed"
else
  record_step fdb_scoring BLOCKED 0 "set DUPLEX_A4_FDB_REPO, DUPLEX_A4_FDB_TASK, and stage FDB outputs"
fi

conda run -n "$CLIENT_ENV" python -c 'import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); steps=[json.loads(x) for x in (p/"steps.jsonl").read_text().splitlines()]; replay=json.load(open(p/"replay/summary.json")) if (p/"replay/summary.json").exists() else None; status="FAIL" if any(x["status"]=="FAIL" for x in steps) else ("PASS" if all(x["status"]=="PASS" for x in steps) else "INCOMPLETE"); json.dump({"status":status,"steps":steps,"replay":replay,"note":"A4 requires PASS for FDB and all real semantic scenarios."},open(p/"a4_summary.json","w"),indent=2)' "$RUN_DIR"

printf '[a4] output=%s failures=%s\n' "$RUN_DIR" "$FAILURES" | tee -a "$RUN_DIR/run.log"
if [ "$REQUIRE_COMPLETE" = "1" ]; then
  COMPLETE_STATUS="$(conda run -n "$CLIENT_ENV" python -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$RUN_DIR/a4_summary.json")"
  if [ "$COMPLETE_STATUS" != "PASS" ]; then
    exit 2
  fi
fi
exit "$FAILURES"
