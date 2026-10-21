#!/usr/bin/env bash
# Finish diagnostics and official timing scores from an already completed replay.
set -euo pipefail
ROOT="${LAYER1_FDB_ROOT:?set frozen scoring checkout}"
REPLAY="${LAYER1_FDB_REPLAY:?set completed original replay run}"
OUTPUT="${LAYER1_FDB_SCORE_OUTPUT:?set independent scoring output}"
BASE=/hpc_stor03/sjtu_home/xuan.zhang
MODEL_PY="$BASE/interclarify-layer1-training-20261019/envs/training/bin/python"
CLIENT_PY="$BASE/miniconda3/envs/xtalk-round1-client/bin/python"
SCORE_PY="$BASE/miniconda3/envs/full-duplex-bench/bin/python"
FDB_REPO="$BASE/Full-Duplex-Bench"
[[ -n "${JobID:-}" && ! -e "$OUTPUT" ]] || exit 2
mkdir "$OUTPUT"
trap 'rc=$?; printf "%s\n" "$rc" > "$OUTPUT/exit_code.txt"' EXIT
cd "$ROOT"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
export PYTHONPATH="$ROOT/scripts/remote:$ROOT/scripts/training"
ulimit -c 0
ulimit -f 8388608
export TMPDIR="$OUTPUT/tmp"
mkdir "$TMPDIR"
git rev-parse HEAD > "$OUTPUT/source_commit.txt"
[[ "$(git -C "$FDB_REPO" rev-parse HEAD)" == 3e799c45a045256f47d5f1c9cda90157e2d2ec9e ]] || exit 2
git -C "$FDB_REPO" diff --exit-code HEAD -- v1_v1.5/get_transcript v1_v1.5/evaluation > "$OUTPUT/fdb_source_check.txt"
"$MODEL_PY" - "$REPLAY" "$OUTPUT" <<'PY'
from pathlib import Path
import hashlib,json,shutil,sys
import torch
assert torch.cuda.device_count() == 1 and '4090' in torch.cuda.get_device_name(0)
source,output=map(Path,sys.argv[1:])
assert shutil.disk_usage(output).free >= 50*1024**3
replay=source/'ASR_R4_delayed_punctuation/replay'
summary=json.loads((replay/'summary.json').read_text())
assert summary['transport_passed'] and summary['sessions']==25
assert (source/'ASR_R4_delayed_punctuation/exit_code.txt').read_text().strip()=='0'
health=json.loads((source/'ASR_R4_delayed_punctuation/model_health.json').read_text())
assert health['adaptation']['condition']=='ASR_R4_delayed_punctuation'
assert health['adaptation']['checkpoint_sha256']=='d1f4d05e4ed1b29dbe8550ffaa02be389673975f7929b33ec1420ef2d70c44a1'
assert health['generation_policy']['id']=='duplex_greedy_v1'
assets={}
for subset,annotation in [('candor_turn_taking','turn_taking.json'),('synthetic_user_interruption','interrupt.json')]:
 folders=sorted((replay/'fdb'/subset).iterdir())
 assert len(folders)==5
 for folder in folders:
  target=output/'scoring_inputs'/subset/folder.name
  target.mkdir(parents=True)
  for name in ('input.wav','output.wav',annotation):
   original=folder/name; copied=target/name
   shutil.copyfile(original,copied)
   sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
   assert sha(original)==sha(copied)
   assets[str(copied.relative_to(output))]=sha(copied)
report={'source_run':str(source),'source_run_exit_code':int((source/'exit_code.txt').read_text()),
        'source_replay_exit_code':0,'source_commit':(source/'source_commit.txt').read_text().strip(),
        'replay_summary_sha256':hashlib.sha256((replay/'summary.json').read_bytes()).hexdigest(),
        'model_health_sha256':hashlib.sha256((source/'ASR_R4_delayed_punctuation/model_health.json').read_bytes()).hexdigest(),
        'copied_assets':assets,'new_replay_performed':False}
(output/'replay_reuse.json').write_text(json.dumps(report,indent=2)+'\n')
PY
CUDA_VISIBLE_DEVICES='' "$CLIENT_PY" -m unittest discover -s tests -p test_fdb_subset_report.py -v \
  > "$OUTPUT/float_wav_tests.txt" 2>&1
CUDA_VISIBLE_DEVICES='' "$CLIENT_PY" scripts/remote/fdb_subset_report.py summarize \
  --root "$REPLAY/ASR_R4_delayed_punctuation/replay" --output "$OUTPUT/diagnostics.json" \
  > "$OUTPUT/diagnostics.log" 2>&1
SCORING_RC=0
env -u PYTHONNOUSERSITE NUMBA_CUDA_USE_NVIDIA_BINDING=0 "$MODEL_PY" -u scripts/remote/fdb_subset_report.py score \
  --input "$OUTPUT/scoring_inputs" --output "$OUTPUT/scoring" --fdb-repo "$FDB_REPO" \
  --scorer-python "$SCORE_PY" > "$OUTPUT/scoring.log" 2>&1 || SCORING_RC=$?
printf '%s\n' "$SCORING_RC" > "$OUTPUT/scoring_exit_code.txt"
"$MODEL_PY" - "$OUTPUT" <<'PY'
from pathlib import Path
import shutil,sys
p=Path(sys.argv[1])
assert shutil.disk_usage(p).free>=50*1024**3
assert sum(f.stat().st_size for f in p.rglob('*') if f.is_file())<10*1024**3
PY
exit "$SCORING_RC"
