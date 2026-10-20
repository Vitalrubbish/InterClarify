#!/usr/bin/env bash
# Rebuild delayed-start supervision without authorizing a training run.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ "$(git -C "$ROOT" rev-parse HEAD)" = "${ISSUE040_SOURCE_COMMIT:?set frozen source commit}" ]] || exit 2
BASE="/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019"
PYTHON="$BASE/envs/training/bin/python"
OUTPUT="$BASE/data/runs/issue040-delayed-start-data"
BASELINE="$BASE/data/runs/issue004-build-r5/dataset"
TOKENIZER="/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28/tokenizer"
[[ -f "$BASE/envs/training/conda-meta/history" && ! -e "$OUTPUT" ]] || exit 2
mkdir -p "$OUTPUT"
trap 'rc=$?; printf "%s\n" "$rc" > "$OUTPUT/exit_code.txt"' EXIT
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
ulimit -v 2097152
ulimit -f 2097152
ulimit -c 0
taskset -pc 0 "$$"
renice 10 -p "$$"
git rev-parse HEAD > "$OUTPUT/source_commit.txt"
"$PYTHON" -c 'from importlib.metadata import distributions; print("\n".join(sorted((d.metadata.get("Name") or "unknown") + "==" + d.version for d in distributions())))' > "$OUTPUT/environment.txt"
"$PYTHON" - "$ROOT/configs/layer1_data.yaml" "$OUTPUT/config.yaml" <<'PY'
import sys
from pathlib import Path
import yaml
config = yaml.safe_load(Path(sys.argv[1]).read_text())
assert config['generation']['response_start_timing'] == 'next_no_voice'
config['limits']['max_disk_gib'] = 10
Path(sys.argv[2]).write_text(yaml.safe_dump(config, sort_keys=False))
PY
timeout --signal=TERM --kill-after=30 1800 "$PYTHON" -u scripts/training/build_layer1_dataset.py \
  --config "$OUTPUT/config.yaml" \
  --source-manifest "$ROOT/reports/layer1_training/issue001-inventory-20261018/data_source_manifest.json" \
  --source-dir "$BASE/data/ultrachat" --download-manifest "$BASE/data/ultrachat/download_manifest.json" \
  --tokenizer "$TOKENIZER" --exclusions "$BASE/manifests/exclusions.json" \
  --max-length 2048 --output "$OUTPUT/dataset" > "$OUTPUT/build.log" 2>&1
timeout --signal=TERM --kill-after=30 900 "$PYTHON" -u scripts/training/audit_layer1_dataset.py \
  --dataset "$OUTPUT/dataset" --tokenizer "$TOKENIZER" --baseline-dataset "$BASELINE" \
  --output "$OUTPUT/audit.json" > "$OUTPUT/audit.log" 2>&1
timeout --signal=TERM --kill-after=30 300 "$PYTHON" - "$OUTPUT" <<'PY'
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, 'scripts/training')
from layer1_data import ARMS, digest, write_json
root = Path(sys.argv[1])
selected = json.loads((root / 'dataset/dialogues.json').read_text())
indices = {arm: [] for arm in ARMS}
tokens = dict.fromkeys(ARMS, 0)
for dialogue in selected:
    if dialogue['split'] != 'train':
        continue
    path = root / 'dataset/dialogues' / (digest(dialogue['dialogue_id']) + '.json')
    artifact = json.loads(path.read_text())
    for sequence in artifact['sequences']:
        arm = sequence['arm']
        indices[arm].append(sequence['sequence_id'])
        tokens[arm] += sequence['effective_tokens']
report = {'training_allowed': False, 'length': 2048,
          'manifest_sha256': hashlib.sha256((root / 'dataset/manifest.json').read_bytes()).hexdigest(),
          'effective_batch': 2, 'arms': {}}
for arm in ARMS:
    steps = math.ceil(len(indices[arm]) / 2)
    report['arms'][arm] = {'sequence_ids': indices[arm], 'sequences': len(indices[arm]),
                           'effective_tokens': tokens[arm], 'single_epoch_steps': steps,
                           'warmup_steps_preview': math.ceil(steps * 0.1)}
write_json(root / 'sequence_inventory.json', report)
PY
