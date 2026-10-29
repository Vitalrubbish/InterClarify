#!/usr/bin/env bash
# Reuse the frozen SoulX and SenseVoice loaders in one isolated scheduler job.
set -euo pipefail

ROOT="${SOULX_ROOT:-$HOME/parathink-soulx-duplug}"
ASSET_ROOT="${SOULX_ASSET_ROOT:-$HOME/turncontrol-comparison}"
CHECK_SOURCE="${SOULX_CHECK_SOURCE:-$ASSET_ROOT/source/6de0d70}"
RUN_ID="${SOULX_RUN_ID:?set a unique run identifier}"
PREFIX="$ASSET_ROOT/envs/soulx"
CHECK="$CHECK_SOURCE/scripts/remote/check_component.py"
EXPECTED="da9602cf09f30e42cdd9b7f43fd81b7519255bf0eb0161bc4af0372efe0e1901"
[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$ ]] || exit 2
[[ -f "$PREFIX/conda-meta/history" && -x "$PREFIX/bin/python" ]] || exit 2
printf '%s  %s\n' "$EXPECTED" "$CHECK" | sha256sum --check --status

mkdir -p "$ROOT/runs"
exec 9>"$ROOT/.check.lock"
flock -n 9 || { echo 'Another frontend check holds the lock' >&2; exit 2; }
RUN="$ROOT/runs/$RUN_ID"
mkdir "$RUN"
trap 'code=$?; printf "%s\n" "$code" > "$RUN/exit_code.txt"' EXIT
AVAILABLE="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
[[ "$AVAILABLE" -ge 31457280 ]] || { echo 'Less than 30 GiB available' >&2; exit 2; }
ulimit -f 131072
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4
export MPLBACKEND=Agg CUDA_MODULE_LOADING=LAZY
export XDG_CACHE_HOME="$RUN/cache" HF_HOME="$RUN/cache/huggingface"
export TMPDIR="$RUN/tmp"
mkdir -p "$TMPDIR" "$HF_HOME"
sha256sum "$CHECK" "${BASH_SOURCE[0]}" \
  "$ASSET_ROOT/upstream/frozen-20261028/soulx-duplug/service/model.py" \
  "$ASSET_ROOT/upstream/frozen-20261028/soulx-duplug/model/asr.py" > "$RUN/source.sha256"
"$PREFIX/bin/python" -B - "$RUN" "$ASSET_ROOT" "$CHECK_SOURCE" <<'PY'
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

run, assets, source = map(Path, sys.argv[1:])
plan_path = assets / "models/download_plan.json"
verification_path = assets / "models/download_verification.json"
plan = json.loads(plan_path.read_text())["models"]
verification = json.loads(verification_path.read_text())
expected = {"soulx-duplug": "61701c4ab8193cc1ee2220d3848872ac6c720142",
            "sensevoice-small": "3847d57b6bdf2dd8875cb1508d2af43d80a16bf7"}
if not verification["passed"]:
    raise ValueError("Shared model verification manifest did not pass")
for name, revision in expected.items():
    if plan[name]["revision"] != revision:
        raise ValueError(f"Unexpected model revision: {name}")
    entries = [entry for entry in verification["files"] if entry["model"] == name]
    if {entry["file"] for entry in entries} != {entry["rfilename"] for entry in plan[name]["files"]}:
        raise ValueError(f"Model verification coverage differs: {name}")
    for entry in entries:
        if (assets / "models" / name / entry["file"]).stat().st_size != entry["bytes"]:
            raise ValueError(f"Shared model file size differs: {name}/{entry['file']}")
record = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "asset_root": str(assets), "check_source": str(source),
    "conda_prefix": sys.prefix,
    "soulx_revision": "61701c4ab8193cc1ee2220d3848872ac6c720142",
    "sensevoice_revision": "3847d57b6bdf2dd8875cb1508d2af43d80a16bf7",
    "upstream_revision": "a0b9063843df69619b087b95b74597b2176910b8",
    "revision_source": "current shared download manifest and file-size checks; no new full-weight hash audit",
    "asset_manifest_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (plan_path, verification_path)},
    "scope": "component loading and forward checks; no Context, LLM, TTS or benchmark",
    "limits": {"gpu": 1, "cpu": 4, "ram_gib": 32, "per_component_seconds": 400,
               "overall_seconds": 900, "result_budget_gib": 2},
}
(run / "deployment.json").write_text(json.dumps(record, indent=2) + "\n")
PY

for component in soulx sensevoice; do
  timeout --signal=TERM --kill-after=20s 400s "$PREFIX/bin/python" -B "$CHECK" \
    --component "$component" --root "$ASSET_ROOT" \
    --upstream "$ASSET_ROOT/upstream/frozen-20261028" \
    --output "$RUN/$component" > "$RUN/$component.log" 2>&1
done
[[ "$(du -sk "$RUN" | awk '{print $1}')" -le 2097152 ]]
echo 'SoulX and SenseVoice component checks completed'
