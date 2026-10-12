#!/usr/bin/env bash
# Validate the exact synced worktree with released DuplexCascade weights.
set -euo pipefail
TASK_ROOT="${INTERCLARIFY_DUPLEX_ROOT:?set independent synced source directory}"
MODEL_HOME="${DUPLEX_MODEL_HOME:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope}"
CHECKPOINT="$MODEL_HOME/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28"
BASE_MODEL="$MODEL_HOME/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a"
TASK_OUTPUT="${DUPLEX_OUTPUT:-$TASK_ROOT/artifacts}"
CONDA_SH="${CONDA_SH:-/opt/conda/etc/profile.d/conda.sh}"
MODEL_ENV="${DUPLEX_MODEL_ENV:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/interclarify-dev}"
MODEL_PORT="${DUPLEX_MODEL_PORT:-8006}"
source "$CONDA_SH"
mkdir -p "$TASK_OUTPUT"
cd "$TASK_ROOT"
export PYTHONPATH="$TASK_ROOT/xtalk/src:$TASK_ROOT"
export PYTHONNOUSERSITE=True
conda run -n xtalk-round1-client python -c 'import hashlib,json,pathlib; root=pathlib.Path("."); manifest=json.loads((root/"source_manifest.json").read_text()); bad=[name for name,digest in manifest["files"].items() if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest]; assert not bad, bad; print(json.dumps({"source_verified":True,"files":len(manifest["files"]),"xtalk_parent":manifest["xtalk_parent"]}))' > "$TASK_OUTPUT/source_check.json"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv > "$TASK_OUTPUT/gpu.csv"
conda run -p "$MODEL_ENV" python -c 'import torch,transformers,peft; print(torch.__version__,transformers.__version__,peft.__version__)' > "$TASK_OUTPUT/environment.txt"
CUDA_VISIBLE_DEVICES=0 conda run --no-capture-output -p "$MODEL_ENV" python scripts/remote/duplex_model_service.py --checkpoint "$CHECKPOINT" --base-model "$BASE_MODEL" --port "$MODEL_PORT" > "$TASK_OUTPUT/model_service.log" 2>&1 &
MODEL_PID=$!
trap 'kill "$MODEL_PID" 2>/dev/null || true; wait "$MODEL_PID" 2>/dev/null || true' EXIT
conda run -n xtalk-round1-client python -c 'import json,time,urllib.request,pathlib; log=pathlib.Path("'"$TASK_OUTPUT"'/model_service.log"); target="http://127.0.0.1:'"$MODEL_PORT"'/health"; deadline=time.monotonic()+600
while time.monotonic()<deadline:
 try:
  health=json.load(urllib.request.urlopen(target,timeout=2)); print(json.dumps(health)); break
 except OSError:
  text=log.read_text(errors="replace") if log.exists() else ""
  if "Traceback (most recent call last)" in text: raise SystemExit("model service failed; inspect model_service.log")
  time.sleep(2)
else: raise SystemExit("official model service did not become healthy")' > "$TASK_OUTPUT/model_health.json"
conda run --no-capture-output -n xtalk-round1-client python scripts/remote/duplex_runtime_smoke.py --model-url "http://127.0.0.1:$MODEL_PORT" --output "$TASK_OUTPUT/runtime" > "$TASK_OUTPUT/runtime.log" 2>&1
