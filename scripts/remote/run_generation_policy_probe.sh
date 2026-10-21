#!/usr/bin/env bash
# Validate an explicit online policy on the frozen paired prompt corpus.
set -euo pipefail
ROOT="${GENERATION_POLICY_ROOT:?set isolated run root}"
SOURCE="$ROOT/source"
OUTPUT="$ROOT/output"
HOME_ROOT=/hpc_stor03/sjtu_home/xuan.zhang
MODEL_ENV="$HOME_ROOT/interclarify-layer1-training-20261019/envs/training"
MODEL_HOME="$HOME_ROOT/interclarify-p0-models/modelscope"
TRAIN_RUN="$HOME_ROOT/interclarify-layer1-training-20261019/data/runs/issue040-delayed-start-r1"
[[ -n "${JobID:-}" && -f "$MODEL_ENV/conda-meta/history" ]] || exit 2
mkdir "$OUTPUT"
MODEL_PID=''
cleanup() {
 local rc=$?
 trap - EXIT
 if [[ -n "$MODEL_PID" ]]; then kill -TERM -- "-$MODEL_PID" 2>/dev/null || true; wait "$MODEL_PID" 2>/dev/null || true; fi
 printf '%s\n' "$rc" > "$ROOT/exit_code.txt"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ulimit -c 0
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
export PYTHONPATH="$SOURCE/scripts/remote:$SOURCE/scripts/training"
cd "$SOURCE"
sha256sum -c policy_source.sha256 > "$OUTPUT/source_verification.txt"
"$MODEL_ENV/bin/python" - "$OUTPUT" <<'PY'
import shutil,sys
import torch
assert shutil.disk_usage(sys.argv[1]).free >= 15*1024**3
assert torch.cuda.device_count()==1 and '4090' in torch.cuda.get_device_name(0)
PY
for pattern in test_duplex_model_service.py test_latency_validation.py; do
 CUDA_VISIBLE_DEVICES='' "$MODEL_ENV/bin/python" -m unittest discover -s tests -p "$pattern" -v > "$OUTPUT/$pattern.txt" 2>&1
done
PORT="$("$MODEL_ENV/bin/python" -c "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1]);s.close()")"
setsid "$MODEL_ENV/bin/python" -u scripts/remote/duplex_model_service.py \
 --checkpoint "$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28" \
 --base-model "$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a" \
 --adaptation "$TRAIN_RUN/training/checkpoint.pt" --port "$PORT" \
 --trace-path "$OUTPUT/policy_trace.jsonl" > "$OUTPUT/model.log" 2>&1 &
MODEL_PID="$!"
for attempt in $(seq 1 600); do
 if curl -sf --max-time 2 "http://127.0.0.1:$PORT/health" > "$OUTPUT/model_health.json"; then break; fi
 kill -0 "$MODEL_PID" || exit 1
 sleep 1
done
cp "$HOME_ROOT/interclarify-latency-20261021-r2/data/r2/model_trace.jsonl" "$OUTPUT/model_trace.jsonl"
"$MODEL_ENV/bin/python" scripts/remote/latency_validation.py probe --root "$OUTPUT" \
 --url "http://127.0.0.1:$PORT" > "$OUTPUT/probe.log" 2>&1
"$MODEL_ENV/bin/python" - "$OUTPUT" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);x=json.loads((p/'cache_probe.json').read_text())
policy=x['generation_policy'];assert policy['repetition_penalty']==1.0 and not policy['do_sample']
rows=[r for r in x['rows'] if r['use_cache']]
assert len(rows)==108
bad=[{k:r[k] for k in ('group','repeat','index','prompt_tokens','cache_status')} for r in rows if not r['ids_match_uncached']]
assert all(r['generation_policy']==policy for r in x['rows'])
summary={'generation_policy':policy,'pairs':len(rows),'matching_pairs':sum(r['ids_match_uncached'] for r in rows),
 'all_ids_match':x['all_ids_match'],'mismatches':bad,
 'previous_divergent_input':[{'repeat':r['repeat'],'ids_match':r['ids_match_uncached']} for r in rows if r['group']==0 and r['index']==4],
 'full_conversation_retested':False}
(p/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
assert sum(q.stat().st_size for q in p.rglob('*') if q.is_file()) < 1024**3
print(json.dumps(summary))
PY
