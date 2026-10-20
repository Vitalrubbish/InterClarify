#!/usr/bin/env bash
# Evaluate registered final adapters on frozen FDB audio.
set -euo pipefail
ROOT="${LAYER1_FDB_ROOT:?set frozen source}"
OUTPUT="${LAYER1_FDB_OUTPUT:?set new output}"
XTALK_ROOT="${LAYER1_XTALK_ROOT:?set frozen X-Talk source}"
TRAIN_RUN="${LAYER1_TRAIN_RUN:?set completed round directory}"
MODE="${LAYER1_FDB_MODE:-round1}"
[[ "$MODE" == round1 || "$MODE" == round2_t2 ]] || exit 2
CONDITIONS=(B0 T1 T2 T3)
if [[ "$MODE" == round2_t2 ]]; then CONDITIONS=(T2_R2_paper_aligned); fi
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
IFS=',' read -r -a GPUS <<< "${CUDA_VISIBLE_DEVICES:-${NVIDIA_VISIBLE_DEVICES:-}}"
[[ "${#GPUS[@]}" -eq 2 && "${GPUS[0]}" != all ]] || exit 2
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
assert shutil.disk_usage(p).free >= 15 * 1024**3, 'FDB disk reserve exhausted'
assert sum(q.stat().st_size for q in p.rglob('*') if q.is_file()) < 10 * 1024**3, 'FDB output budget exceeded'
PY
}
check_budget
git rev-parse HEAD > "$OUTPUT/source_commit.txt"
git diff --exit-code HEAD -- scripts configs > "$OUTPUT/source_dirty_check.txt"
"$MODEL_ENV/bin/python" - "$XTALK_ROOT" "$OUTPUT/xtalk_source_verification.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
source = Path('reports/full_chain/20261019-b0/source.sha256')
rows = [line.split(None, 1) for line in source.read_text().splitlines()]
rows = [(sha, name.strip()) for sha, name in rows if name.strip().startswith('xtalk/src/')]
assert len(rows) == 134
for sha, name in rows:
    assert hashlib.sha256((root / Path(name).relative_to('xtalk')).read_bytes()).hexdigest() == sha, name
report = {'commit': '419f283e64e4de28b01f84586df779a94b18ede3', 'files_verified': len(rows),
          'source_manifest_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'root': str(root)}
Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + '\n')
PY
"$MODEL_ENV/bin/python" - "$TRAIN_RUN" "$OUTPUT/training_completion.json" "$MODE" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
p = Path(sys.argv[1])
assert (p / 'exit_code.txt').read_text().strip() == '0'
second_round = sys.argv[3] == 'round2_t2'
report = {'conditions': {}}
if not second_round:
    report['round_status'] = json.loads((p / 'status.json').read_text())
else:
    reload = json.loads((p / 'candidate_reload.json').read_text())
    assert reload['condition'] == 'T2_R2_paper_aligned' and reload['inference_eligible']
    assert reload['complete_inference_weights_match_training'] and reload['clean_process_probe_ids_match']
    report['candidate_reload'] = reload
initial = None
for arm in (('T2_R2_paper_aligned',) if second_round else ('T1', 'T2', 'T3')):
    root = p / 'training' if second_round else p / arm / 'training'
    summary = json.loads((root / 'summary.json').read_text())
    assert summary['passed'] and summary['final_step'] == 1214 and summary['cursor'] == 2428
    assert summary['frozen_tensors_unchanged'] and len(summary['changed_tensors']) == 112
    if not second_round:
        assert (p / arm / 'exit_code.txt').read_text().strip() == '0'
    assert hashlib.sha256((root / 'checkpoint.pt').read_bytes()).hexdigest() == summary['checkpoint']['sha256']
    before = hashlib.sha256((root / 'weights_before.json').read_bytes()).hexdigest()
    if initial is not None: assert before == initial
    initial = before
    report['conditions'][arm] = {'summary': summary, 'weights_before_sha256': before}
Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + '\n')
PY
"$MODEL_ENV/bin/python" - "$ROOT" <<'PY'
import hashlib
from pathlib import Path
import sys
import yaml
root = Path(sys.argv[1])
evaluation = yaml.safe_load((root / 'configs/layer1_adaptation_protocol.yaml').read_text())['post_training_evaluation']
p = root / evaluation['sample_manifest']
assert hashlib.sha256(p.read_bytes()).hexdigest() == evaluation['sample_manifest_sha256']
PY
"$MODEL_ENV/bin/python" scripts/remote/layer1_fdb.py prepare \
  --manifest reports/layer1_training/issue030-fdb-protocol-20261020/fdb_subset_manifest.json \
  --output "$OUTPUT/inputs" > "$OUTPUT/input_verification.json"
"$MODEL_ENV/bin/python" - "$OUTPUT/gpu_preflight.json" <<'PY'
import json
from pathlib import Path
import sys
import torch
assert torch.cuda.is_available() and torch.cuda.device_count() == 2
devices = [{'name': torch.cuda.get_device_properties(i).name,
            'total_memory': torch.cuda.get_device_properties(i).total_memory} for i in range(2)]
assert all('4090' in d['name'] for d in devices)
Path(sys.argv[1]).write_text(json.dumps(devices, indent=2) + '\n')
PY
for pattern in test_layer1_candidate.py test_layer1_loading.py test_duplex_model_service.py; do
  CUDA_VISIBLE_DEVICES='' "$MODEL_ENV/bin/python" -m unittest discover -s tests -p "$pattern" -v \
    > "$OUTPUT/$pattern.txt" 2>&1
done
CUDA_VISIBLE_DEVICES='' "$CLIENT_ENV/bin/python" -m unittest discover -s tests -p test_duplex_a4_replay.py -v \
  > "$OUTPUT/test_duplex_a4_replay.py.txt" 2>&1
read -r MODEL_PORT ASR_PORT TTS_PORT < <("$MODEL_ENV/bin/python" - <<'PY'
import socket
sockets = [socket.socket() for _ in range(3)]
for s in sockets: s.bind(('127.0.0.1', 0))
print(*(s.getsockname()[1] for s in sockets))
for s in sockets: s.close()
PY
)
setsid nvidia-smi --query-gpu=timestamp,index,memory.used,utilization.gpu --format=csv -l 5 > "$OUTPUT/gpu_samples.csv" &
PIDS+=("$!")
CUDA_VISIBLE_DEVICES="${GPUS[1]}" setsid "$COMPONENT_ROOT/envs/asr/bin/python" -u scripts/remote/nemotron_asr_service.py \
  --model "$ASR" --warmup-audio "$WARMUP" --port "$ASR_PORT" > "$OUTPUT/asr.log" 2>&1 &
PIDS+=("$!")
CUDA_VISIBLE_DEVICES="${GPUS[1]}" setsid "$COMPONENT_ROOT/envs/tts/bin/python" -u scripts/remote/kokoro_tts_service.py \
  --snapshot "$KOKORO" --port "$TTS_PORT" > "$OUTPUT/tts.log" 2>&1 &
PIDS+=("$!")
wait_ready() {
  local port="$1" target="$2"
  for attempt in $(seq 1 600); do
    if curl -sf --max-time 2 "http://127.0.0.1:$port/health" > "$target"; then return 0; fi
    sleep 1
  done
  return 1
}
wait_ready "$ASR_PORT" "$OUTPUT/asr_health.json"
wait_ready "$TTS_PORT" "$OUTPUT/tts_health.json"
FAILED=0
for condition in "${CONDITIONS[@]}"; do
  check_budget
  mkdir "$OUTPUT/$condition"
  ADAPTATION=()
  if [[ "$MODE" == round2_t2 ]]; then
    ADAPTATION=(--adaptation "$TRAIN_RUN/training/checkpoint.pt")
  elif [[ "$condition" != B0 ]]; then
    ADAPTATION=(--adaptation "$TRAIN_RUN/$condition/training/checkpoint.pt")
  fi
  CUDA_VISIBLE_DEVICES="${GPUS[0]}" setsid "$MODEL_ENV/bin/python" -u scripts/remote/duplex_model_service.py \
    --checkpoint "$CHECKPOINT" --base-model "$BASE" --port "$MODEL_PORT" "${ADAPTATION[@]}" \
    > "$OUTPUT/$condition/model.log" 2>&1 &
  MODEL_PID="$!"
  wait_ready "$MODEL_PORT" "$OUTPUT/$condition/model_health.json"
  "$MODEL_ENV/bin/python" - "$OUTPUT/$condition/model_health.json" "$condition" <<'PY'
import json
from pathlib import Path
import sys
health = json.loads(Path(sys.argv[1]).read_text())
assert health['adaptation']['condition'] == sys.argv[2]
if sys.argv[2] != 'B0':
    assert health['adaptation']['complete_inference_weights_match_training']
    assert health['adaptation']['clean_process_probe_ids_match']
PY
  rc=0
  CUDA_VISIBLE_DEVICES='' "$CLIENT_ENV/bin/python" -u scripts/remote/layer1_fdb.py run \
    --input "$OUTPUT/inputs" --output "$OUTPUT/$condition/replay" \
    --config configs/xtalk_duplex_english_runtime.json --asr-url "http://127.0.0.1:$ASR_PORT" \
    --tts-url "http://127.0.0.1:$TTS_PORT" --model-url "http://127.0.0.1:$MODEL_PORT" \
    > "$OUTPUT/$condition/client.log" 2>&1 || rc=$?
  printf '%s\n' "$rc" > "$OUTPUT/$condition/exit_code.txt"
  if [[ "$rc" -ne 0 ]]; then FAILED=1; fi
  kill -TERM -- "-$MODEL_PID" 2>/dev/null || true
  wait "$MODEL_PID" 2>/dev/null || true
  MODEL_PID=''
done
check_budget
exit "$FAILED"
