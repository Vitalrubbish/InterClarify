#!/usr/bin/env bash
# Run complete FDB interruption and smooth-turn axes in one bounded allocation.
set -euo pipefail
ROOT="${FULL_FDB_SOURCE:?set frozen source}"
OUTPUT="${FULL_FDB_OUTPUT:?set new output}"
XTALK_ROOT="${FULL_FDB_XTALK_ROOT:?set frozen X-Talk source}"
TRAIN_RUN="${LAYER1_TRAIN_RUN:?set completed round directory}"
CONDITION=T2_R3_delayed_start
HOME_ROOT=/hpc_stor03/sjtu_home/xuan.zhang
MODEL_ENV="$HOME_ROOT/interclarify-layer1-training-20261019/envs/training"
CLIENT_ENV="$HOME_ROOT/miniconda3/envs/xtalk-round1-client"
COMPONENT_ROOT="$HOME_ROOT/interclarify-english-integration-20261018-v6"
MODEL_HOME="$HOME_ROOT/interclarify-p0-models/modelscope"
CHECKPOINT="$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28"
BASE="$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a"
ASR="$HOME_ROOT/interclarify-asr-selection/models/nemotron_en"
KOKORO="$HOME_ROOT/interclarify-tts-selection-20261018/models/hf/hub/models--hexgrad--Kokoro-82M/snapshots/f3ff3571791e39611d31c381e3a41a3af07b4987"
WARMUP="$HOME_ROOT/interclarify-asr-selection/dataset/dev/786465049904960526.wav"
[[ -n "${JobID:-}" ]] || exit 2
for prefix in "$MODEL_ENV" "$CLIENT_ENV" "$COMPONENT_ROOT/envs/asr" "$COMPONENT_ROOT/envs/tts"; do
  [[ -x "$prefix/bin/python" && -f "$prefix/conda-meta/history" ]] || exit 2
done
mkdir -p "$(dirname "$OUTPUT")"
mkdir "$OUTPUT"
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PYTHONPATH="$XTALK_ROOT/src:$ROOT/scripts/remote:$ROOT/scripts/training"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
ulimit -c 0
ulimit -f 8388608
export TMPDIR="$OUTPUT/tmp"
mkdir -p "$TMPDIR"
IFS=',' read -r -a GPUS <<< "${CUDA_VISIBLE_DEVICES:-${NVIDIA_VISIBLE_DEVICES:-}}"
[[ "${#GPUS[@]}" -eq 2 && "${GPUS[0]}" != all ]] || exit 2
SCORE_ENV="$HOME_ROOT/miniconda3/envs/full-duplex-bench"
FDB_REPO="$HOME_ROOT/Full-Duplex-Bench"
KEY_FILE="$HOME_ROOT/InterClarify/openai_api.txt"
MANIFEST="${FULL_FDB_MANIFEST:?set frozen full-corpus manifest}"
[[ -f "$SCORE_ENV/conda-meta/history" ]] || exit 2
PIDS=()
MODEL_PID=''
cleanup() {
  local rc=$?
  trap - EXIT
  if [[ -n "$MODEL_PID" ]]; then kill -TERM -- "-$MODEL_PID" 2>/dev/null || true; fi
  for pid in "${PIDS[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  if [[ -n "$MODEL_PID" ]]; then wait "$MODEL_PID" 2>/dev/null || true; fi
  for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null || true; done
  printf '%s\n' "$rc" > "$OUTPUT/exit_code.txt"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
check_budget() {
  "$MODEL_ENV/bin/python" - "$OUTPUT" <<'PY'
from pathlib import Path
import shutil
import sys
p = Path(sys.argv[1])
assert shutil.disk_usage(p).free >= 50 * 1024**3, 'FDB disk reserve exhausted'
assert sum(q.stat().st_size for q in p.rglob('*') if q.is_file()) < 30 * 1024**3, 'FDB output budget exceeded'
PY
}
check_budget
sha256sum -c source.sha256 > "$OUTPUT/source_verification.txt"
cp source.sha256 "$OUTPUT/source.sha256"
"$MODEL_ENV/bin/python" - "$TRAIN_RUN" "$OUTPUT/training_completion.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
import yaml
p = Path(sys.argv[1])
condition = 'T2_R3_delayed_start'
steps, sequences = 1235, 2469
exit_code = (p / 'exit_code.txt').read_text().strip()
assert exit_code == '0'
reload = json.loads((p / 'candidate_reload.json').read_text())
assert reload['condition'] == condition and reload['inference_eligible']
assert reload['complete_inference_weights_match_training'] and reload['clean_process_probe_ids_match']
root = p / 'training'
summary = json.loads((root / 'summary.json').read_text())
manifest = json.loads((root / 'manifest.json').read_text())
identity = manifest['identity']
protocol = yaml.safe_load(Path('configs/layer1_delayed_protocol.yaml').read_text())
assert summary['passed'] and summary['final_step'] == steps and summary['cursor'] == sequences
assert reload['final_step'] == steps and reload['cursor'] == sequences
assert reload['checkpoint_sha256'] == summary['checkpoint']['sha256']
assert reload['train_manifest_sha256'] == hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()
assert reload['summary_sha256'] == hashlib.sha256((root / 'summary.json').read_bytes()).hexdigest()
assert summary['formal_training_released'] and manifest['formal_training_released']
assert summary['exposed_dialogues'] == 1000
assert identity['config']['purpose'] == 'issue040_delayed_start'
assert identity['config']['condition'] == condition
assert identity['data']['manifest_sha256'] == protocol['data_manifest_sha256']
assert identity['data']['audit_sha256'] == protocol['data_audit_sha256']
assert identity['release']['config'] == protocol['training_config_sha256']
assert identity['release']['protocol'] == hashlib.sha256(
    Path('configs/layer1_delayed_protocol.yaml').read_bytes()).hexdigest()
assert identity['config']['loss']['type'] == 'control_weighted_ce'
assert identity['config']['loss']['control_weights'] == dict(
    speaking=1, finish=10, interruption=5, backchannel=2, thinking=1)
assert summary['frozen_tensors_unchanged'] and len(summary['changed_tensors']) == 112
assert hashlib.sha256((root / 'checkpoint.pt').read_bytes()).hexdigest() == summary['checkpoint']['sha256']
before = hashlib.sha256((root / 'weights_before.json').read_bytes()).hexdigest()
report = {'conditions': {condition: {'summary': summary, 'weights_before_sha256': before}},
          'original_train_job_exit_code': exit_code, 'candidate_reload': reload}
Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + '\n')
PY

"$MODEL_ENV/bin/python" scripts/remote/full_fdb_two_axes.py stage \
  --manifest "$MANIFEST" --output "$OUTPUT/inputs" > "$OUTPUT/input_verification.json"
git -C "$XTALK_ROOT" rev-parse HEAD > "$OUTPUT/xtalk_commit.txt"
[[ "$(cat "$OUTPUT/xtalk_commit.txt")" == d6dc3bff0a512d13f4352bce6105aec80b7f9960 ]] || exit 2
[[ "$(git -C "$FDB_REPO" rev-parse HEAD)" == 3e799c45a045256f47d5f1c9cda90157e2d2ec9e ]] || exit 2
git -C "$FDB_REPO" diff --exit-code HEAD -- v1_v1.5/get_transcript v1_v1.5/evaluation > "$OUTPUT/fdb_source_check.txt"
"$MODEL_ENV/bin/python" - <<'PYGPU'
import torch
assert torch.cuda.device_count()==2
assert all('4090' in torch.cuda.get_device_name(i) for i in range(2))
PYGPU
# Validate alignment and judge access before spending hours on real-time replay.
"$CLIENT_ENV/bin/python" - "$OUTPUT" <<'PYPREFLIGHT'
from pathlib import Path
import sys
import soundfile as sf
import numpy as np
p=Path(sys.argv[1])
source=sorted((p/'inputs/candor_turn_taking').glob('*/input.wav'))[0]
with sf.SoundFile(source) as audio:
    sr=audio.samplerate
    samples=audio.read(3*sr,always_2d=True).mean(axis=1)
for name,values in [('speech',samples),('silence',np.zeros(2*sr))]:
    folder=p/'scorer_preflight'/name
    folder.mkdir(parents=True)
    sf.write(folder/'output.wav',values,sr,subtype='PCM_16')
PYPREFLIGHT
env -u PYTHONNOUSERSITE NUMBA_CUDA_USE_NVIDIA_BINDING=0 CUDA_VISIBLE_DEVICES="${GPUS[0]}" \
  timeout --signal=TERM --kill-after=30 900 "$SCORE_ENV/bin/python" \
  "$FDB_REPO/v1_v1.5/get_transcript/asr.py" --root_dir "$OUTPUT/scorer_preflight" --task default \
  > "$OUTPUT/scorer_preflight.log" 2>&1
env -u PYTHONNOUSERSITE NUMBA_CUDA_USE_NVIDIA_BINDING=0 CUDA_VISIBLE_DEVICES='' \
  timeout 90 "$SCORE_ENV/bin/python" scripts/remote/full_fdb_two_axes.py preflight-judge \
  --key-file "$KEY_FILE" > "$OUTPUT/judge_preflight.json" 2> "$OUTPUT/judge_preflight.log"
for pattern in test_full_fdb_two_axes.py test_duplex_model_service.py; do
  CUDA_VISIBLE_DEVICES='' "$MODEL_ENV/bin/python" -m unittest discover -s tests -p "$pattern" -v \
    > "$OUTPUT/$pattern.txt" 2>&1
done
read -r MODEL_PORT ASR_PORT TTS_PORT < <("$MODEL_ENV/bin/python" - <<'PYPORT'
import socket
sockets=[socket.socket() for _ in range(3)]
for s in sockets:s.bind(('127.0.0.1',0))
print(*(s.getsockname()[1] for s in sockets))
for s in sockets:s.close()
PYPORT
)
CUDA_VISIBLE_DEVICES="${GPUS[1]}" setsid "$COMPONENT_ROOT/envs/asr/bin/python" -u scripts/remote/nemotron_asr_service.py \
  --model "$ASR" --warmup-audio "$WARMUP" --port "$ASR_PORT" > "$OUTPUT/asr.log" 2>&1 &
PIDS+=("$!")
CUDA_VISIBLE_DEVICES="${GPUS[1]}" setsid "$COMPONENT_ROOT/envs/tts/bin/python" -u scripts/remote/kokoro_tts_service.py \
  --snapshot "$KOKORO" --port "$TTS_PORT" > "$OUTPUT/tts.log" 2>&1 &
PIDS+=("$!")
CUDA_VISIBLE_DEVICES="${GPUS[0]}" setsid "$MODEL_ENV/bin/python" -u scripts/remote/duplex_model_service.py \
  --checkpoint "$CHECKPOINT" --base-model "$BASE" --adaptation "$TRAIN_RUN/training/checkpoint.pt" \
  --port "$MODEL_PORT" --trace-path "$OUTPUT/model_trace.jsonl" > "$OUTPUT/model.log" 2>&1 &
MODEL_PID="$!"
wait_ready() {
  local port="$1" target="$2"
  for attempt in $(seq 1 600); do
    if curl -sf --max-time 2 "http://127.0.0.1:$port/health" > "$target"; then return 0; fi
    kill -0 "$MODEL_PID" || return 1
    sleep 1
  done
  return 1
}
wait_ready "$ASR_PORT" "$OUTPUT/asr_health.json"
wait_ready "$TTS_PORT" "$OUTPUT/tts_health.json"
wait_ready "$MODEL_PORT" "$OUTPUT/model_health.json"
"$MODEL_ENV/bin/python" - "$OUTPUT/model_health.json" <<'PYHEALTH'
import json,sys
from pathlib import Path
x=json.loads(Path(sys.argv[1]).read_text())
assert x['adaptation']['condition']=='T2_R3_delayed_start'
assert x['adaptation']['checkpoint_sha256']=='266a37a28699d0c3f36b6a6305374bc89a1a2ff2af7a37fd1eb4caf1ad915346'
assert x['generation_policy']['id']=='duplex_greedy_v1'
assert x['generation_policy']['repetition_penalty']==1.0
PYHEALTH
check_budget
INFER_RC=0
CUDA_VISIBLE_DEVICES='' "$CLIENT_ENV/bin/python" -u scripts/remote/full_fdb_two_axes.py infer \
  --input "$OUTPUT/inputs" --output "$OUTPUT/replay" --config configs/xtalk_duplex_english_runtime.json \
  --asr-url "http://127.0.0.1:$ASR_PORT" --tts-url "http://127.0.0.1:$TTS_PORT" \
  --model-url "http://127.0.0.1:$MODEL_PORT" > "$OUTPUT/inference.log" 2>&1 || INFER_RC=$?
printf '%s\n' "$INFER_RC" > "$OUTPUT/inference_exit_code.txt"
kill -TERM -- "-$MODEL_PID" 2>/dev/null || true
wait "$MODEL_PID" 2>/dev/null || true
MODEL_PID=''
for pid in "${PIDS[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null || true; done
PIDS=()
check_budget
SCORE_RC=0
env -u PYTHONNOUSERSITE NUMBA_CUDA_USE_NVIDIA_BINDING=0 CUDA_VISIBLE_DEVICES="${GPUS[0]}" \
  "$MODEL_ENV/bin/python" -u scripts/remote/full_fdb_two_axes.py score \
  --input "$OUTPUT/replay/fdb" --output "$OUTPUT/scoring" --fdb-repo "$FDB_REPO" \
  --scorer-python "$SCORE_ENV/bin/python" --key-file "$KEY_FILE" > "$OUTPUT/scoring.log" 2>&1 || SCORE_RC=$?
printf '%s\n' "$SCORE_RC" > "$OUTPUT/scoring_exit_code.txt"
check_budget
[[ "$INFER_RC" -eq 0 && "$SCORE_RC" -eq 0 ]]
