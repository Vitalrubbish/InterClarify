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
ASR_BACKEND="${DUPLEX_ASR_BACKEND:-qwen}"
if [ "$ASR_BACKEND" != qwen ] && [ "$ASR_BACKEND" != x2 ]; then
  echo "unsupported ASR backend: $ASR_BACKEND" >&2
  exit 2
fi
MOSS_ENV="${DUPLEX_MOSS_ENV:-xtalk-round1-moss}"
MODEL_PORT="${DUPLEX_MODEL_PORT:-8006}"
ASR_PORT="${DUPLEX_ASR_PORT:-8005}"
TTS_PORT="${DUPLEX_TTS_PORT:-8004}"
TAG="${DUPLEX_A4_TAG:-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_ROOT="${DUPLEX_A4_RUN_ROOT:-$TASK_ROOT/data/runs}"
RUN_DIR="${DUPLEX_A4_OUTPUT:-$RUN_ROOT/$TAG}"
REPORT_ROOT="${DUPLEX_A4_REPORT_ROOT:-$TASK_ROOT/reports/duplex_acceptance}"
REPORT_DIR="${DUPLEX_A4_REPORT_DIR:-$REPORT_ROOT/$TAG}"
NORMAL_AUDIO="${DUPLEX_A4_NORMAL_AUDIO:-${DUPLEX_A4_INPUT:-$ROUND1_ROOT/audio/scenarios/regular_answer_01_question.wav}}"
# Interruption uses FDB v1.0 sample 106: a short-answer question plus a real interrupt.
FDB_V1_ROOT="${DUPLEX_A4_FDB_V1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/STS/data/fdb/v1_0}"
INTERRUPTION_SAMPLE_DIR="${DUPLEX_A4_INTERRUPTION_SAMPLE_DIR:-$FDB_V1_ROOT/synthetic_user_interruption/106}"
INTERRUPTION_REQUEST_AUDIO="${DUPLEX_A4_INTERRUPTION_REQUEST_AUDIO:-$INTERRUPTION_SAMPLE_DIR/context.wav}"
INTERRUPTION_WAV="${DUPLEX_A4_INTERRUPPTION_AUDIO:-$INTERRUPTION_SAMPLE_DIR/interrupt.wav}"
PAUSE_FIRST_AUDIO="${DUPLEX_A4_PAUSE_FIRST_AUDIO:-$ROUND1_ROOT/audio/scenarios/pause_then_continue_01_part_one.wav}"
PAUSE_SECOND_AUDIO="${DUPLEX_A4_PAUSE_SECOND_AUDIO:-$ROUND1_ROOT/audio/scenarios/pause_then_continue_02_part_two.wav}"
MULTI_QUESTION_AUDIO="${DUPLEX_A4_MULTI_QUESTION_AUDIO:-$ROUND1_ROOT/audio/scenarios/continuous_two_questions_01_two_questions.wav}"
LONG_SESSION_AUDIO="${DUPLEX_A4_LONG_SESSION_AUDIO:-$NORMAL_AUDIO}"
SCENARIOS="${DUPLEX_A4_SCENARIOS:-normal interruption}"
BARGE_AFTER_SECONDS="${DUPLEX_A4_BARGE_AFTER_SECONDS:-0.6}"
PAUSE_GAP_SECONDS="${DUPLEX_A4_PAUSE_GAP_SECONDS:-1.5}"
REQUIRE_INTERRUPTION="${DUPLEX_A4_REQUIRE_INTERRUPTION:-0}"
FDB_INPUT_ROOT="${DUPLEX_A4_FDB_INPUT_ROOT:-}"
FDB_OUTPUT_ROOT="${DUPLEX_A4_FDB_OUTPUT_ROOT:-$RUN_DIR/fdb}"
FDB_LIMIT="${DUPLEX_A4_FDB_LIMIT:-5}"
FDB_REPO="${DUPLEX_A4_FDB_REPO:-}"
FDB_ENV="${DUPLEX_A4_FDB_ENV:-full-duplex-bench}"
FDB_COMMIT="${DUPLEX_A4_FDB_COMMIT:-3e799c45a045256f47d5f1c9cda90157e2d2ec9e}"
# Keep the official judge model so scores stay comparable with upstream; the
# endpoint must serve it. Overriding triggers a substitution in the work copy.
FDB_JUDGE_MODEL="${DUPLEX_A4_FDB_JUDGE_MODEL:-gpt-4-turbo}"
FDB_SKIP_JUDGE="${DUPLEX_A4_FDB_SKIP_JUDGE:-0}"
FDB_SCORING="${DUPLEX_A4_FDB_SCORING:-0}"
FDB_JUDGE_BASE_URL="${DUPLEX_A4_FDB_BASE_URL:-https://api-2.xi-ai.cn/v1}"
# Raw key file, read only inside the judge step. Kept outside the run tree so the
# secret never reaches job logs, submit logs or archived evidence.
FDB_JUDGE_KEY_FILE="${DUPLEX_A4_FDB_API_KEY_FILE:-$TASK_ROOT/openai_api.txt}"
FDB_AXES="${DUPLEX_A4_FDB_AXES:-pause_handling:candor_pause_handling:default pause_handling:synthetic_pause_handling:default smooth_turn_taking:candor_turn_taking:default user_interruption:synthetic_user_interruption:user_interruption backchannel:icc_backchannel:default}"
LONG_ROUNDS="${DUPLEX_A4_ROUNDS:-30}"
REQUIRE_COMPLETE="${DUPLEX_A4_REQUIRE_COMPLETE:-0}"
ROUND1_PY="$TASK_ROOT/scripts/remote/run_xtalk_round1.py"

# shellcheck disable=SC1090
source "$CONDA_SH"
if [ -e "$RUN_DIR" ]; then
  echo "A4 output directory already exists: $RUN_DIR" >&2
  exit 2
fi
mkdir -p "$RUN_DIR/logs" "$RUN_DIR/tests" "$RUN_DIR/services" "$REPORT_DIR"
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
# The container starts with an empty /tmp cache and cannot reach GitHub raw, so
# seed the Silero VAD weight from the shared drive when the runtime VAD is on.
VAD_CACHE_FILE="${DUPLEX_VAD_CACHE_FILE:-/hpc_stor03/sjtu_home/xuan.zhang/.cache/xtalk/models/silero_vad.onnx}"
if [ -r "$VAD_CACHE_FILE" ]; then
  mkdir -p "$XDG_CACHE_HOME/xtalk/models"
  cp -n "$VAD_CACHE_FILE" "$XDG_CACHE_HOME/xtalk/models/silero_vad.onnx" 2>/dev/null || true
fi

IFS=',' read -r -a JOB_GPUS <<< "${CUDA_VISIBLE_DEVICES:-0,1,2}"
PIDS=()
FAILURES=0

record_step() {
  local name="$1" status="$2" rc="$3" reason="${4:-}"
  # Command substitution strips trailing newlines so the file gets exactly one
  # line per record regardless of how the local conda build buffers stdout.
  local record
  record="$(conda run -n "$CLIENT_ENV" python -c 'import json,sys; print(json.dumps({"step":sys.argv[1],"status":sys.argv[2],"rc":int(sys.argv[3]),"reason":sys.argv[4]}))' "$name" "$status" "$rc" "$reason")"
  printf '%s\n' "$record" >> "$RUN_DIR/steps.jsonl"
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
for asset in "$CHECKPOINT" "$BASE_MODEL" "$MODEL_ROOT/models.lock.json" \
  "$NORMAL_AUDIO" "$INTERRUPTION_REQUEST_AUDIO" "$INTERRUPTION_WAV" \
  "$PAUSE_FIRST_AUDIO" "$PAUSE_SECOND_AUDIO" "$MULTI_QUESTION_AUDIO" \
  "$ROUND1_ROOT/audio/reference.wav"; do
  [ -e "$asset" ] || { printf 'missing asset: %s\n' "$asset" >> "$RUN_DIR/logs/assets.log"; RC=1; }
done
if [ "$ASR_BACKEND" = x2 ]; then
  # Fail here, with the path in assets.log, instead of inside the ASR service.
  for asset in "${DUPLEX_X2_SOURCE:?set X2 source}" "${DUPLEX_X2_MODEL:?set X2 weights}" "${DUPLEX_X2_WARMUP_AUDIO:-$NORMAL_AUDIO}"; do
    [ -e "$asset" ] || { printf 'missing asset: %s\n' "$asset" >> "$RUN_DIR/logs/assets.log"; RC=1; }
  done
fi
[ "$RC" -eq 0 ] && record_step assets PASS 0 || record_step assets FAIL "$RC" "required model or audio asset is missing"

cp "$MODEL_ROOT/models.lock.json" "$RUN_DIR/models.lock.json"
if [ "$ASR_BACKEND" = x2 ]; then
  conda run -n "$CLIENT_ENV" python -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["models"]["asr"]={"model_id":"x-square-robot/X2Streaming-ASR-4B-1009","revision":"4c8df16b8d7f8b50c95590c4d7907436ebe4aa08","snapshot_path":sys.argv[2],"source_commit":"0aca80597bb1399c0be4002de5bc62c0a779c542"}; json.dump(d,open(p,"w"),indent=2)' \
    "$RUN_DIR/models.lock.json" "${DUPLEX_X2_MODEL:?set X2 weights}"
fi
RC=0
{
  if ! conda run -p "$MODEL_ENV" python -c 'import torch,transformers,peft; print("model",torch.__version__,transformers.__version__,peft.__version__)'; then RC=1; fi
  if [ "$ASR_BACKEND" = x2 ]; then
    if ! conda run -p "$ASR_ENV" python -c 'import torch,transformers; print("x2",torch.__version__,transformers.__version__)'; then RC=1; fi
  else
    if ! conda run -n "$ASR_ENV" python -c 'import qwen_asr,transformers; print("asr",transformers.__version__)'; then RC=1; fi
  fi
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

# Start all three services concurrently so every allocated GPU is used promptly;
# sequential startup leaves idle GPUs, which the cluster kills as LowGpuUsage.
CUDA_VISIBLE_DEVICES="${JOB_GPUS[0]}" setsid conda run --no-capture-output -p "$MODEL_ENV" \
  python scripts/remote/duplex_model_service.py --checkpoint "$CHECKPOINT" \
  --base-model "$BASE_MODEL" --port "$MODEL_PORT" \
  > "$RUN_DIR/services/duplex_model.log" 2>&1 &
MODEL_PID="$!"
PIDS+=("$MODEL_PID")

if [ "$ASR_BACKEND" = x2 ]; then
CUDA_VISIBLE_DEVICES="${JOB_GPUS[1]}" setsid conda run --no-capture-output -p "$ASR_ENV" \
  python scripts/remote/x2_asr_service.py --source-root "${DUPLEX_X2_SOURCE:?set X2 source}" \
  --warmup-audio "${DUPLEX_X2_WARMUP_AUDIO:-$NORMAL_AUDIO}" \
  --model "${DUPLEX_X2_MODEL:?set X2 weights}" --language "${DUPLEX_X2_LANGUAGE:-en}" --port "$ASR_PORT" \
  > "$RUN_DIR/services/asr.log" 2>&1 &
else
CUDA_VISIBLE_DEVICES="${JOB_GPUS[1]}" setsid conda run --no-capture-output -n "$TOOLS_ENV" \
  python "$ROUND1_PY" --config "$ROUND1_CONFIG" --model-root "$MODEL_ROOT" serve asr --gpu-index 0 \
  > "$RUN_DIR/services/asr.log" 2>&1 &
fi
ASR_PID="$!"
PIDS+=("$ASR_PID")

CUDA_VISIBLE_DEVICES="${JOB_GPUS[2]}" setsid conda run --no-capture-output -n "$TOOLS_ENV" \
  python "$ROUND1_PY" --config "$ROUND1_CONFIG" --model-root "$MODEL_ROOT" serve tts --gpu-index 0 \
  > "$RUN_DIR/services/tts.log" 2>&1 &
TTS_PID="$!"
PIDS+=("$TTS_PID")

# Regression tests run while the services load, keeping the job productive.
RC=0
(cd "$TASK_ROOT/xtalk" && conda run -n "$CLIENT_ENV" env PYTHONPATH=src python -m unittest \
  tests.test_duplex_protocol tests.test_duplex_observability \
  tests.test_turn_detector_manager tests.test_llm_agent_persistent_stream \
  tests.test_response_identity tests.test_tool_call_playback_barrier \
  tests.test_tts_streaming_playback_alignment) \
  > "$RUN_DIR/tests/a1.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step a1_regression PASS 0 || record_step a1_regression FAIL "$RC"

RC=0
(cd "$TASK_ROOT/xtalk" && conda run -n "$CLIENT_ENV" env PYTHONPATH=src python -m unittest \
  tests.test_duplex_runtime tests.test_x2_streaming_client) \
  > "$RUN_DIR/tests/a2_a3.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step a2_a3_regression PASS 0 || record_step a2_a3_regression FAIL "$RC"

RC=0
conda run -n "$CLIENT_ENV" env PYTHONPATH="$TASK_ROOT/xtalk/src:$TASK_ROOT" python -m unittest \
  tests.test_duplex_a4_replay tests.test_duplex_model_service tests.test_qwen3_asr_service \
  tests.test_x2_asr_service \
  > "$RUN_DIR/tests/a4_driver.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step a4_driver_regression PASS 0 || record_step a4_driver_regression FAIL "$RC"
[ "$FAILURES" -eq 0 ] || exit "$FAILURES"

RC=0
wait_http "http://127.0.0.1:$MODEL_PORT/health" 1800 "$RUN_DIR/model_health.json" "$RUN_DIR/services/duplex_model.log" "$MODEL_PID" || RC=$?
[ "$RC" -eq 0 ] && record_step duplex_model_service PASS 0 || record_step duplex_model_service FAIL "$RC"
[ "$RC" -eq 0 ] || exit "$FAILURES"

RC=0
wait_http "http://127.0.0.1:$ASR_PORT/health" 1800 "$RUN_DIR/asr_health.json" "$RUN_DIR/services/asr.log" "$ASR_PID" || RC=$?
[ "$RC" -eq 0 ] && record_step asr_service PASS 0 || record_step asr_service FAIL "$RC"

RC=0
wait_http "http://127.0.0.1:$TTS_PORT/health" 1800 "$RUN_DIR/tts_health.json" "$RUN_DIR/services/tts.log" "$TTS_PID" || RC=$?
[ "$RC" -eq 0 ] && record_step tts_service PASS 0 || record_step tts_service FAIL "$RC"
[ "$FAILURES" -eq 0 ] || exit "$FAILURES"

# The runtime patch compiles the codebook loop on the first frame it sees, which
# costs ~45s once per service process. Pay it here so the first *measured*
# utterance is not the one that funds the compilation.
RC=0
conda run --no-capture-output -n "$CLIENT_ENV" \
  env PYTHONPATH="$TASK_ROOT/xtalk/src" \
  python "$ROUND1_PY" --config "$ROUND1_CONFIG" --model-root "$MODEL_ROOT" \
  tts-smoke --reference "$ROUND1_ROOT/audio/reference.wav" \
  --output "$RUN_DIR/tts_warmup" --url "http://127.0.0.1:$TTS_PORT" \
  --text "warm up the compiled codebook loop and the audio decoder before the replay starts." \
  --stream-chunk-words 6 --gap-seconds 0.02 \
  > "$RUN_DIR/logs/tts_warmup.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step tts_warmup PASS 0 || record_step tts_warmup FAIL "$RC"

# Sample per-service RSS (process group) alongside the GPU sampler for trend evidence.
{
  echo "timestamp,pid,rss_kb"
  while true; do
    for pid in "${PIDS[@]}"; do
      rss="$(ps -g "$pid" -o rss= 2>/dev/null | awk '{total+=$1} END {print total+0}')"
      [ "${rss:-0}" -gt 0 ] && echo "$(date -u +%Y-%m-%dT%H:%M:%SZ),$pid,$rss"
    done
    sleep 5
  done
} > "$RUN_DIR/resource_samples.csv" 2>&1 &
PIDS+=("$!")

RC=0
conda run --no-capture-output -n "$CLIENT_ENV" python scripts/remote/duplex_runtime_smoke.py \
  --model-url "http://127.0.0.1:$MODEL_PORT" --output "$RUN_DIR/runtime_smoke" \
  > "$RUN_DIR/logs/runtime_smoke.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step official_model_smoke PASS 0 || record_step official_model_smoke FAIL "$RC"

RUNTIME_CONFIG="$RUN_DIR/a4_runtime.json"
RC=0
conda run -n "$CLIENT_ENV" python -c 'import json,sys,pathlib; cfg=json.load(open(sys.argv[1])); cfg["asr"]["params"]["base_url"]="http://127.0.0.1:"+sys.argv[3]; cfg["tts"]["params"]["base_url"]="http://127.0.0.1:"+sys.argv[4]; cfg["tts"]["params"]["voices"][0]["path"]=sys.argv[5]; sc=cfg.setdefault("service_config",{}); sc["duplex_model_url"]="http://127.0.0.1:"+sys.argv[2]; json.dump(cfg,open(sys.argv[6],"w"),indent=2)' \
  "$([ "$ASR_BACKEND" = x2 ] && echo configs/xtalk_duplex_x2_runtime.json || echo configs/xtalk_duplex_runtime.json)" "$MODEL_PORT" "$ASR_PORT" "$TTS_PORT" \
  "$ROUND1_ROOT/audio/reference.wav" "$RUNTIME_CONFIG" || RC=$?
[ "$RC" -eq 0 ] || { record_step runtime_json FAIL "$RC"; exit "$FAILURES"; }

# Build the runtime's model set before spending the job's GPU budget on a replay.
# A missing optional dependency (the backend VAD needs onnxruntime, which the
# silero-vad extra brings) kills the replay server process, and the only symptom
# is a later "X-Talk server did not start in time" timeout.
RC=0
conda run --no-capture-output -n "$CLIENT_ENV" env PYTHONPATH="$TASK_ROOT/xtalk/src:$TASK_ROOT" \
  python -c 'import json,sys; from xtalk.api import Xtalk; from xtalk.models import ASR,VAD; models=Xtalk._load_models(json.load(open(sys.argv[1]))); vad=models.get(VAD); asr=models.require(ASR); assert (vad is None) if asr.continuous_audio else (vad is not None), "runtime VAD does not match ASR lifecycle"; print("vad", type(vad).__name__)' \
  "$RUNTIME_CONFIG" > "$RUN_DIR/logs/runtime_build.log" 2>&1 || RC=$?
[ "$RC" -eq 0 ] && record_step runtime_build PASS 0 || record_step runtime_build FAIL "$RC" "inspect logs/runtime_build.log"
[ "$FAILURES" -eq 0 ] || exit "$FAILURES"

RC=0
EXTRA=()
[ "$REQUIRE_INTERRUPTION" = "1" ] && EXTRA+=(--require-interruption)
SCENARIO_ARGS=()
for scenario in $SCENARIOS; do SCENARIO_ARGS+=(--scenario "$scenario"); done
AUDIO_ARGS=(
  --scenario-audio "normal=$NORMAL_AUDIO"
  --scenario-audio "interruption=$INTERRUPTION_REQUEST_AUDIO"
  --scenario-audio "pause=$PAUSE_FIRST_AUDIO,$PAUSE_SECOND_AUDIO"
  --scenario-audio "multi_question=$MULTI_QUESTION_AUDIO"
  --scenario-audio "long_session=$LONG_SESSION_AUDIO"
)
conda run --no-capture-output -n "$CLIENT_ENV" env PYTHONPATH="$TASK_ROOT/xtalk/src:$TASK_ROOT" \
  python scripts/remote/duplex_a4_replay.py --config "$RUNTIME_CONFIG" \
  --model-url "http://127.0.0.1:$MODEL_PORT" --audio "$NORMAL_AUDIO" \
  "${AUDIO_ARGS[@]}" --interruption-audio "$INTERRUPTION_WAV" \
  --barge-after-seconds "$BARGE_AFTER_SECONDS" --pause-gap-seconds "$PAUSE_GAP_SECONDS" \
  --out "$RUN_DIR/replay" --rounds "$LONG_ROUNDS" "${SCENARIO_ARGS[@]}" "${EXTRA[@]}" \
  > "$RUN_DIR/logs/replay.log" 2>&1 || RC=$?
REPLAY_STATUS="$(conda run -n "$CLIENT_ENV" python -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status","FAIL"))' "$RUN_DIR/replay/summary.json" 2>/dev/null || echo FAIL)"
case "$REPLAY_STATUS" in
  PASS) record_step real_audio_replay PASS 0 ;;
  INCONCLUSIVE) record_step real_audio_replay INCONCLUSIVE "$RC" "model did not cover every semantic scenario" ;;
  *) record_step real_audio_replay FAIL "$RC" "inspect replay reports" ;;
esac

FDB_READY=0
FDB_WORK_REPO="$RUN_DIR/fdb_repo"
if [ -n "$FDB_INPUT_ROOT" ] && [ -d "$FDB_INPUT_ROOT" ]; then
  FDB_READY=1
  if [ -n "$FDB_REPO" ] && [ -d "$FDB_REPO/v1_v1.5" ]; then
    # Only the official entry points are needed; skipping the rest avoids copying
    # the upstream node_modules tree into every run directory.
    mkdir -p "$FDB_WORK_REPO"
    cp -r "$FDB_REPO/v1_v1.5/get_transcript" "$FDB_REPO/v1_v1.5/evaluation" "$FDB_WORK_REPO/"
    if [ "$FDB_JUDGE_MODEL" != "gpt-4-turbo" ]; then
      sed -i "s/gpt-4-turbo/$FDB_JUDGE_MODEL/g" "$FDB_WORK_REPO/evaluation/eval_user_interruption.py"
    fi
  fi
fi

if [ "$FDB_READY" = "1" ]; then
  RC=0
  for entry in $FDB_AXES; do
    axis="${entry%%:*}"; rest="${entry#*:}"; subset="${rest%%:*}"
    input="$FDB_INPUT_ROOT/$subset"
    output="$FDB_OUTPUT_ROOT/$axis/$subset"
    log="$RUN_DIR/logs/fdb_inference_${axis}_${subset}.log"
    if [ ! -d "$input" ]; then
      printf 'missing FDB subset: %s\n' "$input" >> "$RUN_DIR/logs/fdb_inference.log"
      RC=1
      continue
    fi
    conda run --no-capture-output -n "$CLIENT_ENV" env PYTHONPATH="$TASK_ROOT/xtalk/src:$TASK_ROOT" \
      python scripts/remote/duplex_a4_replay.py --config "$RUNTIME_CONFIG" \
      --model-url "http://127.0.0.1:$MODEL_PORT" --out "$RUN_DIR/fdb_driver/${axis}_${subset}" \
      --fdb-input-root "$input" --fdb-output-root "$output" \
      --fdb-limit "$FDB_LIMIT" > "$log" 2>&1 || RC=$?
  done
  [ "$RC" -eq 0 ] && record_step fdb_inference PASS 0 || record_step fdb_inference FAIL "$RC" "inspect logs/fdb_inference_*.log"
else
  record_step fdb_inference BLOCKED 0 "set DUPLEX_A4_FDB_INPUT_ROOT to the FDB v1.0 root"
fi

stop_services
PIDS=()

FDB_SCORING_READY=0
FDB_SCORING_BLOCKED=0
# NeMo's alignment importers abort on this image without the ctypes binding path,
# which would otherwise report the environment as lacking NeMo (observed
# 2026-10-15); the flag only affects how numba talks to the driver.
export NUMBA_CUDA_USE_NVIDIA_BINDING=0
if [ "$FDB_SCORING" != "1" ]; then
  # Scoring keeps GPUs idle, which the cluster kills as LowGpuUsage; run it in a
  # dedicated single-GPU job instead of the three-GPU model job.
  record_step fdb_scoring SKIPPED 0 "scoring deferred (set DUPLEX_A4_FDB_SCORING=1)"
  FDB_SCORING_READY=-1
  FDB_SCORING_BLOCKED=1
else
  [ "$FDB_READY" = "1" ] && [ -n "$FDB_REPO" ] && [ -d "$FDB_WORK_REPO" ] && [ -d "$FDB_OUTPUT_ROOT" ] || FDB_SCORING_READY=-1
  if [ "$FDB_SCORING_READY" = "0" ] && ! conda run -n "$FDB_ENV" python -c 'import nemo.collections.asr' >/dev/null 2>&1; then
    record_step fdb_scoring BLOCKED 0 "conda env $FDB_ENV lacks NeMo alignment dependencies"
    FDB_SCORING_READY=-1
    FDB_SCORING_BLOCKED=1
  fi
fi

if [ "$FDB_SCORING_READY" = "0" ]; then
  git -C "$FDB_REPO" rev-parse HEAD > "$RUN_DIR/fdb_commit.txt"
  if [ "$(cat "$RUN_DIR/fdb_commit.txt")" != "$FDB_COMMIT" ] || ! git -C "$FDB_REPO" diff --quiet HEAD; then
    record_step fdb_revision FAIL 1 "FDB checkout differs from fixed commit"
    exit "$FAILURES"
  fi
  RC=0
  JUDGE_DEFERRED=0
  JUDGE_BLOCKED=0
  # The official evaluate.py builds OpenAI(api_key=...) and reads OPENAI_BASE_URL
  # from the environment. Only the source of the key is logged, never its value.
  export OPENAI_BASE_URL="$FDB_JUDGE_BASE_URL"
  if [ -z "${OPENAI_API_KEY:-}" ] && [ -r "$FDB_JUDGE_KEY_FILE" ] && [ -s "$FDB_JUDGE_KEY_FILE" ]; then
    OPENAI_API_KEY="$(head -n 1 "$FDB_JUDGE_KEY_FILE" | tr -d '[:space:]')"
    export OPENAI_API_KEY
  fi
  if [ -n "${OPENAI_API_KEY:-}" ]; then
    printf 'judge credentials loaded from %s for %s\n' "$FDB_JUDGE_KEY_FILE" "$OPENAI_BASE_URL" \
      >> "$RUN_DIR/logs/fdb_scoring_credentials.log"
  else
    printf 'judge credentials missing (file: %s)\n' "$FDB_JUDGE_KEY_FILE" \
      >> "$RUN_DIR/logs/fdb_scoring_credentials.log"
  fi
  for entry in $FDB_AXES; do
    axis="${entry%%:*}"; rest="${entry#*:}"; subset="${rest%%:*}"; asr_task="${rest#*:}"
    output="$FDB_OUTPUT_ROOT/$axis/$subset"
    log="$RUN_DIR/logs/fdb_scoring_${axis}_${subset}.log"
    if [ ! -d "$output" ]; then
      printf 'missing FDB output: %s\n' "$output" >> "$RUN_DIR/logs/fdb_alignment.log"
      RC=1
      continue
    fi
    if ! conda run --no-capture-output -n "$FDB_ENV" python "$FDB_WORK_REPO/get_transcript/asr.py" \
      --root_dir "$output" --task "$asr_task" --audio_name output.wav >> "$log" 2>&1; then
      RC=1
    fi
    if find "$output" -name clean_output.wav -print -quit | grep -q .; then
      conda run --no-capture-output -n "$FDB_ENV" python "$FDB_WORK_REPO/get_transcript/asr.py" \
        --root_dir "$output" --task "$asr_task" --audio_name clean_output.wav >> "$log" 2>&1 || RC=1
    fi
    if [ "$axis" = "behavior" ]; then
      conda run --no-capture-output -n "$FDB_ENV" python "$FDB_WORK_REPO/evaluation/get_timing.py" \
        --root_dir "$output" >> "$log" 2>&1 || RC=1
    fi
    if [ "$axis" = "user_interruption" ] && [ "$FDB_SKIP_JUDGE" = "1" ]; then
      printf 'GPT judge deferred for %s\n' "$output" >> "$RUN_DIR/logs/fdb_alignment.log"
      JUDGE_DEFERRED=1
      continue
    fi
    if [ "$axis" = "user_interruption" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
      printf 'no judge credentials for %s\n' "$output" >> "$RUN_DIR/logs/fdb_alignment.log"
      JUDGE_BLOCKED=1
      continue
    fi
    (cd "$RUN_DIR" && conda run --no-capture-output -n "$FDB_ENV" \
      python "$FDB_WORK_REPO/evaluation/evaluate.py" --task "$axis" --root_dir "$output") >> "$log" 2>&1 || RC=1
  done
  [ "$RC" -eq 0 ] && record_step fdb_scoring PASS 0 || record_step fdb_scoring FAIL "$RC" "official FDB alignment or evaluation failed"
  [ "$JUDGE_DEFERRED" = "1" ] && record_step fdb_judge BLOCKED 0 "GPT judge deferred (DUPLEX_A4_FDB_SKIP_JUDGE=1)"
  [ "$JUDGE_BLOCKED" = "1" ] && record_step fdb_judge BLOCKED 0 "no OpenAI-compatible judge credentials"
elif [ "$FDB_SCORING_BLOCKED" = "0" ]; then
  record_step fdb_scoring BLOCKED 0 "set DUPLEX_A4_FDB_REPO and stage FDB v1.0 outputs"
fi

# Read steps.jsonl defensively: skip blank lines so a stray newline can never
# abort summary generation, and always leave a summary file behind.
conda run -n "$CLIENT_ENV" python -c '
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
steps = []
for line in (p / "steps.jsonl").read_text().splitlines():
    line = line.strip()
    if line:
        steps.append(json.loads(line))
replay_path = p / "replay" / "summary.json"
replay = None
if replay_path.exists():
    raw_replay = json.load(open(replay_path))
    replay = {"status": raw_replay.get("status"),
              "scenarios": {s.get("scenario"): s.get("status") for s in raw_replay.get("scenarios", [])}}
axes = {}
for summary in sorted((p / "fdb_driver").glob("*/fdb_summary.json")):
    axes[summary.parent.name] = json.load(open(summary)).get("status")
if any(s["status"] == "FAIL" for s in steps):
    status = "FAIL"
elif steps and all(s["status"] == "PASS" for s in steps):
    status = "PASS"
else:
    status = "INCOMPLETE"
json.dump({"status": status, "steps": steps, "fdb_axes": axes, "replay": replay,
           "note": "Stage A requires PASS for the FDB v1.0 axes and all real semantic scenarios."},
          open(p / "a4_summary.json", "w"), indent=2)
' "$RUN_DIR" || printf '{"status": "INCOMPLETE", "error": "failed to build a4_summary"}\n' > "$RUN_DIR/a4_summary.json"

# Copy the key evidence into the tracked report directory, leaving heavy audio in data/runs.
mkdir -p "$REPORT_DIR/replay" "$REPORT_DIR/tests"
for report in source_check.json environment.txt git.txt model_health.json steps.jsonl \
  a4_summary.json resource_samples.csv gpu.csv gpu_samples.csv; do
  [ -f "$RUN_DIR/$report" ] && cp "$RUN_DIR/$report" "$REPORT_DIR/"
done
[ -f "$RUN_DIR/replay/summary.json" ] && cp "$RUN_DIR/replay/summary.json" "$REPORT_DIR/replay/"
for scenario_report in "$RUN_DIR"/replay/*/report.json; do
  [ -f "$scenario_report" ] || continue
  cp "$scenario_report" "$REPORT_DIR/replay/$(basename "$(dirname "$scenario_report")")_report.json"
done
for driver_summary in "$RUN_DIR"/fdb_driver/*/fdb_summary.json; do
  [ -f "$driver_summary" ] || continue
  cp "$driver_summary" "$REPORT_DIR/$(basename "$(dirname "$driver_summary")")_fdb_summary.json"
done
cp "$RUN_DIR"/tests/*.log "$REPORT_DIR/tests/" 2>/dev/null || true
cp "$RUN_DIR"/logs/fdb_scoring_*.log "$REPORT_DIR/tests/" 2>/dev/null || true

# Compact the tracked evidence: verdicts, ids, timings and per-token counts stay,
# the per-tick arrays and sampler CSVs are summarized - the raw streams remain in
# data/runs/<tag>/.  See docs/scripts/remote/compact_a4_report.md.
conda run --no-capture-output -n "$CLIENT_ENV" \
  python "$TASK_ROOT/scripts/remote/compact_a4_report.py" --report-dir "$REPORT_DIR" \
  >> "$RUN_DIR/run.log" 2>&1 || true

printf '[a4] output=%s reports=%s failures=%s\n' "$RUN_DIR" "$REPORT_DIR" "$FAILURES" | tee -a "$RUN_DIR/run.log"
if [ "$REQUIRE_COMPLETE" = "1" ]; then
  COMPLETE_STATUS="$(conda run -n "$CLIENT_ENV" python -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$RUN_DIR/a4_summary.json")"
  if [ "$COMPLETE_STATUS" != "PASS" ]; then
    exit 2
  fi
fi
exit "$FAILURES"
