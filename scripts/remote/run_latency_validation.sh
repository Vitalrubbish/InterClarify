#!/usr/bin/env bash
# Validate adopted latency settings on frozen FDB audio with bounded resources.
set -euo pipefail
ROOT="${LATENCY_SOURCE:?set frozen source}"
OUTPUT="${LATENCY_OUTPUT:?set new output}"
XTALK_ROOT="${LAYER1_XTALK_ROOT:?set frozen X-Talk source}"
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
for pattern in test_duplex_model_service.py test_latency_validation.py; do
  CUDA_VISIBLE_DEVICES='' "$MODEL_ENV/bin/python" -m unittest discover -s tests -p "$pattern" -v \
    > "$OUTPUT/$pattern.txt" 2>&1
done
CUDA_VISIBLE_DEVICES='' "$CLIENT_ENV/bin/python" -m unittest discover -s tests -p test_duplex_a4_replay.py -v \
  > "$OUTPUT/test_duplex_a4_replay.py.txt" 2>&1
for pattern in test_kokoro_segmented.py test_duplex_runtime.py; do
  CUDA_VISIBLE_DEVICES='' "$CLIENT_ENV/bin/python" -m unittest discover -s "$XTALK_ROOT/tests" -p "$pattern" -v \
    > "$OUTPUT/$pattern.txt" 2>&1
done
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
CUDA_VISIBLE_DEVICES="${GPUS[0]}" setsid "$MODEL_ENV/bin/python" -u scripts/remote/duplex_model_service.py \
  --checkpoint "$CHECKPOINT" --base-model "$BASE" --port "$MODEL_PORT" \
  --adaptation "$TRAIN_RUN/training/checkpoint.pt" --trace-path "$OUTPUT/model_trace.jsonl" \
  > "$OUTPUT/model.log" 2>&1 &
MODEL_PID="$!"
wait_ready "$MODEL_PORT" "$OUTPUT/model_health.json"
condition=current
check_budget
mkdir "$OUTPUT/$condition"
"$MODEL_ENV/bin/python" - "$OUTPUT/$condition/runtime.json" <<'PYCONFIG'
import json
from pathlib import Path
import sys
config = json.loads(Path('configs/xtalk_duplex_english_runtime.json').read_text())
assert config['tts']['params']['max_wait_ms'] == 300
assert config['tts']['params']['continuation_wait_ms'] == 1200
assert config['service_config']['duplex_kv_cache_enabled'] is True
assert config['service_config']['duplex_micro_turn_seconds'] == 0.6
Path(sys.argv[1]).write_text(json.dumps(config, indent=2)+'\n')
PYCONFIG
FAILED=0
CUDA_VISIBLE_DEVICES='' "$CLIENT_ENV/bin/python" -u scripts/remote/layer1_fdb.py run \
  --input "$OUTPUT/inputs" --output "$OUTPUT/$condition/replay" \
  --config "$OUTPUT/$condition/runtime.json" --asr-url "http://127.0.0.1:$ASR_PORT" \
  --tts-url "http://127.0.0.1:$TTS_PORT" --model-url "http://127.0.0.1:$MODEL_PORT" \
  > "$OUTPUT/$condition/client.log" 2>&1 || FAILED=$?
printf '%s\n' "$FAILED" > "$OUTPUT/$condition/exit_code.txt"
CUDA_VISIBLE_DEVICES='' "$CLIENT_ENV/bin/python" scripts/remote/verify_english_components.py \
  --backend tts --url "http://127.0.0.1:$TTS_PORT" --audio "$WARMUP" \
  --tts-first-wait-ms 300 --tts-continuation-wait-ms 1200 \
  --output "$OUTPUT/tts-300" > "$OUTPUT/tts-300.log" 2>&1
"$MODEL_ENV/bin/python" scripts/remote/latency_validation.py analyze --root "$OUTPUT" \
  > "$OUTPUT/latency_summary.log" 2>&1
check_budget
exit "$FAILED"
