#!/usr/bin/env bash
# Register B0 and train T1/T2/T3 serially inside one allocated GPU job.
set -euo pipefail
ROOT="${LAYER1_TRAIN_ROOT:?set frozen source checkout}"
ENV_PREFIX="${LAYER1_TRAINING_ENV:?set independent training conda prefix}"
OUTPUT="${LAYER1_ROUND_OUTPUT:?set new round output}"
[[ -x "$ENV_PREFIX/bin/python" && -f "$ENV_PREFIX/conda-meta/history" ]] || exit 2
[[ -n "${JobID:-}" && ( -n "${CUDA_VISIBLE_DEVICES:-}" || -n "${NVIDIA_VISIBLE_DEVICES:-}" ) ]] || exit 2
mkdir -p "$(dirname "$OUTPUT")"
mkdir "$OUTPUT"
trap 'rc=$?; printf "%s\n" "$rc" > "$OUTPUT/exit_code.txt"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd "$ROOT"
export PYTHONNOUSERSITE=1 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
ulimit -c 0

check_budget() {
  "$ENV_PREFIX/bin/python" - "$OUTPUT" <<'PY'
from pathlib import Path
import shutil
import sys
path = Path(sys.argv[1])
assert shutil.disk_usage(path).free >= 15 * 1024**3, 'Round free disk reserve exhausted'
assert sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) < 16 * 1024**3, 'Round output cap exceeded'
PY
}

record_state() {
  "$ENV_PREFIX/bin/python" - "$OUTPUT/status.json" "$1" "$2" "$3" <<'PY'
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
path = Path(sys.argv[1])
state = json.loads(path.read_text()) if path.exists() else {
    'job_id': os.environ['JobID'], 'arms': {arm: {'status': 'pending'} for arm in ('T1', 'T2', 'T3')},
    'B0': {'status': 'registered_untrained_baseline', 'optimizer_steps': 0},
    'training_order': ['T1', 'T2', 'T3'], 'evaluation_status': 'not_run'}
status, arm, code = sys.argv[2:]
now = datetime.now(timezone.utc).isoformat()
state.update(status=status, updated_at=now)
if arm:
    state['arms'][arm].update(status=status, updated_at=now)
    if code:
        state['arms'][arm]['exit_code'] = int(code)
if status == 'completed' and not arm:
    state['status'] = 'training_execution_completed_evaluation_not_run'
temporary = path.with_suffix('.partial')
temporary.write_text(json.dumps(state, indent=2) + '\n')
temporary.replace(path)
PY
}

check_budget
git rev-parse HEAD > "$OUTPUT/source_commit.txt"
"$ENV_PREFIX/bin/python" scripts/training/prepare_layer1_adaptation.py \
  --output "$OUTPUT/plan.json" --require-release > "$OUTPUT/preflight.txt" 2>&1
record_state running '' ''
for pattern in test_layer1_adaptation.py test_layer1_training.py; do
  rc=0
  CUDA_VISIBLE_DEVICES='' "$ENV_PREFIX/bin/python" -m unittest discover -s tests -p "$pattern" -v \
    > "$OUTPUT/$pattern.txt" 2>&1 || rc=$?
  if [[ "$rc" -ne 0 ]]; then record_state preflight_failed '' "$rc"; exit "$rc"; fi
done
mkdir "$OUTPUT/B0"
"$ENV_PREFIX/bin/python" - "$OUTPUT/plan.json" "$OUTPUT/B0/baseline.json" <<'PY'
import json
from pathlib import Path
import sys
plan = json.loads(Path(sys.argv[1]).read_text())
baseline = {'condition': 'B0', 'optimizer_steps': 0, 'updated': False,
            'status': 'registered_untrained_official_baseline', 'assets': plan['assets'],
            'inputs': plan['inputs'], 'post_training_evaluation': plan['post_training_evaluation']}
Path(sys.argv[2]).write_text(json.dumps(baseline, indent=2) + '\n')
PY
for arm in T1 T2 T3; do
  check_budget
  record_state running "$arm" ''
  rc=0
  LAYER1_ARM="$arm" LAYER1_TRAIN_OUTPUT="$OUTPUT/$arm" \
    bash scripts/remote/run_layer1_adaptation.sh > "$OUTPUT/$arm.log" 2>&1 || rc=$?
  if [[ "$rc" -ne 0 ]]; then record_state failed "$arm" "$rc"; exit "$rc"; fi
  rc=0
  "$ENV_PREFIX/bin/python" - "$OUTPUT/$arm/training/summary.json" <<'PY' || rc=$?
import json
from pathlib import Path
import sys
summary = json.loads(Path(sys.argv[1]).read_text())
assert summary['passed'] and summary['formal_training_released']
assert summary['final_step'] == 1214 and summary['cursor'] == 2428
PY
  if [[ "$rc" -ne 0 ]]; then record_state failed "$arm" "$rc"; exit "$rc"; fi
  record_state completed "$arm" 0
done
check_budget
record_state completed '' 0
