#!/usr/bin/env bash
# Prepare and verify the isolated XTurnix conda environment plus frozen model assets.
#
# Modes:
#   prepare (default): clone the measured ASR seed env, pin Transformers, download
#                      the fixed XTurnix revision, verify hashes and write locks.
#   verify:            re-check the existing environment and model without network
#                      writes or package changes; write a verification report.
set -euo pipefail

MODE="${1:-prepare}"
case "$MODE" in
  prepare|verify) ;;
  *) echo "usage: $0 [prepare|verify]" >&2; exit 2 ;;
esac

ROOT="${XTURNIX_ROOT:-$HOME/interclarify-xturnix-fleurs}"
CONDA="${XTURNIX_CONDA_BIN:-$HOME/miniconda3/bin/conda}"
SEED_ENV="${XTURNIX_CONDA_SEED:-$HOME/interclarify-english-integration-20261018-v1/envs/asr}"
ENV_DIR="$ROOT/envs/xturnix"
MODEL_DIR="$ROOT/models/xturnix-pt"
META_DIR="$ROOT/environment"
ASR_MODEL="${XTURNIX_ASR_MODEL:-$HOME/interclarify-asr-selection/models/nemotron_en}"
ASR_LOCK="${XTURNIX_ASR_LOCK:-$HOME/interclarify-asr-selection/models.lock.json}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="${XTURNIX_CONFIG:-$REPO_ROOT/configs/xturnix_fleurs_test.json}"

XTURNIX_REPO="xcczach/xturnix-pt"
XTURNIX_REVISION="d4b0403e5a6744b46fa7602b6d77bbac2768d5b5"
TRANSFORMERS_VERSION="4.57.1"
ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
MIN_FREE_GIB=30
MAX_ASSET_GIB=10
DOWNLOAD_WORKERS=2

export PYTHONNOUSERSITE=1
export HF_HUB_ENABLE_HF_TRANSFER=0
export HF_HUB_DOWNLOAD_TIMEOUT=60
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4

log() { printf '[setup_xturnix_env] %s\n' "$*"; }
die() { printf '[setup_xturnix_env] error: %s\n' "$*" >&2; exit 1; }

free_gib() {
  df -Pk "$1" | awk 'NR==2 {printf "%.2f", $4/1024/1024}'
}

apparent_bytes() {
  du -sb "$1" 2>/dev/null | awk '{print $1}'
}

[ -f "$CONFIG" ] || die "missing frozen config: $CONFIG"
mkdir -p "$ROOT" "$META_DIR"
START_FREE="$(free_gib "$ROOT")"
awk -v have="$START_FREE" -v need="$MIN_FREE_GIB" 'BEGIN {exit !(have >= need)}' \
  || die "free space ${START_FREE} GiB is below ${MIN_FREE_GIB} GiB"

log "mode=$MODE root=$ROOT config=$CONFIG"
log "free=${START_FREE}GiB endpoint=$ENDPOINT"

if [ "$MODE" = prepare ]; then
  [ -x "$CONDA" ] || die "conda not found: $CONDA"
  [ -f "$SEED_ENV/conda-meta/history" ] || die "seed environment is missing: $SEED_ENV"

  if [ ! -f "$ENV_DIR/conda-meta/history" ]; then
    log "cloning conda env from $SEED_ENV"
    "$CONDA" create -y -p "$ENV_DIR" --clone "$SEED_ENV"
  else
    log "reusing existing conda env: $ENV_DIR"
  fi

  log "pinning transformers==$TRANSFORMERS_VERSION"
  "$ENV_DIR/bin/python" -m pip install --no-input --disable-pip-version-check \
    --no-cache-dir "transformers==$TRANSFORMERS_VERSION"

  "$ENV_DIR/bin/python" - "$ENV_DIR" "$TRANSFORMERS_VERSION" <<'PY'
import sys
import transformers
expected = sys.argv[2]
if transformers.__version__ != expected:
    raise SystemExit(f"transformers {transformers.__version__} != {expected}")
import torch
from transformers import Pipeline
print(f"python={sys.version.split()[0]} torch={torch.__version__} transformers={transformers.__version__}")
PY

  log "downloading and validating $XTURNIX_REPO@$XTURNIX_REVISION"
  if [ ! -f "$MODEL_DIR/model.safetensors" ] || [ -f "$MODEL_DIR/model.safetensors.aria2" ]; then
    command -v aria2c >/dev/null || die "aria2c is required for the large model download"
    log "pre-downloading model.safetensors with aria2c (2 connections)"
    timeout 1800 aria2c -x2 -s2 -c --max-tries=0 --retry-wait=2 \
      --timeout=60 --connect-timeout=20 --file-allocation=none \
      --summary-interval=30 --console-log-level=warn \
      --dir "$MODEL_DIR" --out model.safetensors \
      "$ENDPOINT/$XTURNIX_REPO/resolve/$XTURNIX_REVISION/model.safetensors" \
      || die "aria2c model download failed; rerun to resume"
  fi
  "$ENV_DIR/bin/python" - "$MODEL_DIR" "$XTURNIX_REPO" "$XTURNIX_REVISION" "$ENDPOINT" "$DOWNLOAD_WORKERS" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

model_dir, repo, revision, endpoint, workers = (
    Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
)
from huggingface_hub import HfApi, snapshot_download

api = HfApi(endpoint=endpoint)
info = api.model_info(repo, revision=revision, files_metadata=True)
if info.sha != revision:
    raise SystemExit(f"resolved revision {info.sha} != frozen {revision}")
remote = {item.rfilename: item for item in info.siblings}
model_dir.mkdir(parents=True, exist_ok=True)
snapshot_download(repo_id=repo, revision=revision, local_dir=str(model_dir),
                  endpoint=endpoint, max_workers=workers, etag_timeout=60)

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def git_blob_sha1(path):
    digest = hashlib.sha1()
    size = path.stat().st_size
    digest.update(f"blob {size}\0".encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

files = {}
for path in sorted(model_dir.rglob("*")):
    if (
        not path.is_file()
        or ".cache" in path.parts
        or "__pycache__" in path.parts
        or path.suffix == ".pyc"
    ):
        continue
    relative = path.relative_to(model_dir).as_posix()
    if relative not in remote:
        raise SystemExit(f"unexpected local file {relative}")
    item = remote[relative]
    local_sha = sha256(path)
    lfs = item.lfs
    if lfs:
        expected = lfs["sha256"] if isinstance(lfs, dict) else lfs.sha256
        if local_sha != expected:
            raise SystemExit(f"sha256 mismatch for {relative}")
    else:
        if git_blob_sha1(path) != item.blob_id:
            raise SystemExit(f"git blob mismatch for {relative}")
    files[relative] = {"sha256": local_sha, "bytes": path.stat().st_size}
missing = sorted(set(remote) - set(files))
if missing:
    raise SystemExit(f"missing files: {missing}")
lock = {
    "schema": "xtx-002-xturnix-model-lock-v1",
    "repo": repo,
    "revision": revision,
    "resolved_revision": info.sha,
    "endpoint": endpoint,
    "path": str(model_dir.resolve()),
    "files": files,
    "total_bytes": sum(item["bytes"] for item in files.values()),
    "download_workers": workers,
}
target = model_dir.parent / "xturnix-pt.lock.json"
if target.exists():
    previous = json.loads(target.read_text())
    previous_files = {
        name: entry["sha256"] for name, entry in previous.get("files", {}).items()
    }
    current_files = {name: entry["sha256"] for name, entry in files.items()}
    if previous.get("revision") != revision or previous_files != current_files:
        raise SystemExit(
            f"existing lock {target} does not match the downloaded assets; "
            "refusing to relock silently"
        )
temporary = target.with_name(target.name + ".part")
temporary.write_text(json.dumps(lock, indent=2) + "\n")
os.replace(temporary, target)
print(f"locked {len(files)} files / {lock['total_bytes']} bytes -> {target}")
PY
fi

[ -x "$ENV_DIR/bin/python" ] || die "XTurnix environment is missing: $ENV_DIR"
if [ "$MODE" = verify ]; then
  "$ENV_DIR/bin/python" - "$TRANSFORMERS_VERSION" <<'PY'
import sys
import transformers
expected = sys.argv[1]
if transformers.__version__ != expected:
    raise SystemExit(f"transformers {transformers.__version__} != {expected}")
import torch
from transformers import Pipeline
print(f"verified python={sys.version.split()[0]} torch={torch.__version__} transformers={transformers.__version__}")
PY
fi

log "verifying frozen model and ASR assets"
"$ENV_DIR/bin/python" - "$MODEL_DIR" "$ASR_MODEL" "$ASR_LOCK" "$CONFIG" \
  "$ROOT/environment/model_verification.json" "$XTURNIX_REVISION" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

model_dir = Path(sys.argv[1])
asr_dir = Path(sys.argv[2])
asr_lock = Path(sys.argv[3])
config_path = Path(sys.argv[4])
report_path = Path(sys.argv[5])
revision = sys.argv[6]

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

xturnix_lock = json.loads((model_dir.parent / "xturnix-pt.lock.json").read_text())
if xturnix_lock["revision"] != revision:
    raise SystemExit("XTurnix lock revision mismatch")
local = {}
for path in sorted(model_dir.rglob("*")):
    if (
        not path.is_file()
        or ".cache" in path.parts
        or "__pycache__" in path.parts
        or path.suffix == ".pyc"
    ):
        continue
    local[path.relative_to(model_dir).as_posix()] = sha256(path)
expected = {name: entry["sha256"] for name, entry in xturnix_lock["files"].items()}
if local != expected:
    raise SystemExit("XTurnix model inventory does not match its lock")

asr_expected = json.loads(asr_lock.read_text())["nemotron_en"]
if asr_expected["revision"] != "ebe59e5a817142986528bbbee5dba8db7b38ed50":
    raise SystemExit("unexpected Nemotron revision in the source lock")
asr_local = {}
for path in sorted(asr_dir.rglob("*")):
    if (
        not path.is_file()
        or ".cache" in path.parts
        or "__pycache__" in path.parts
        or path.suffix == ".pyc"
    ):
        continue
    asr_local[path.relative_to(asr_dir).as_posix()] = sha256(path)
if asr_local != asr_expected["files"]:
    raise SystemExit("Nemotron model inventory does not match the read-only source lock")

config = json.loads(config_path.read_text())
if config["xturnix"]["revision"] != revision:
    raise SystemExit("config XTurnix revision mismatch")
if config["asr"]["revision"] != asr_expected["revision"]:
    raise SystemExit("config ASR revision mismatch")
expected_asr_sha = config["asr"]["model_sha256"]["model.safetensors"]
if asr_local["model.safetensors"] != expected_asr_sha:
    raise SystemExit("config ASR model digest mismatch")

report = {
    "schema": "xtx-002-model-verification-v1",
    "xturnix": {
        "repo": xturnix_lock["repo"],
        "revision": xturnix_lock["revision"],
        "path": str(model_dir.resolve()),
        "files": len(local),
        "bytes": xturnix_lock["total_bytes"],
    },
    "asr": {
        "repo": asr_expected["repo"],
        "revision": asr_expected["revision"],
        "path": str(asr_dir.resolve()),
        "files": len(asr_local),
    },
    "config": {"path": str(config_path.resolve()), "sha256": sha256(config_path)},
}
temporary = report_path.with_name(report_path.name + ".part")
temporary.write_text(json.dumps(report, indent=2) + "\n")
temporary.replace(report_path)
print(f"verified XTurnix={len(local)} files ASR={len(asr_local)} files")
PY

if [ "$MODE" = prepare ]; then
  cp "$CONFIG" "$META_DIR/xturnix_fleurs_test.json"
  "$ENV_DIR/bin/python" -m pip freeze > "$META_DIR/xturnix.pip-freeze.txt"
  "$CONDA" list -p "$ENV_DIR" --explicit > "$META_DIR/xturnix.conda-explicit.txt"
fi

END_FREE="$(free_gib "$ROOT")"
MODEL_BYTES="$(apparent_bytes "$MODEL_DIR")"
ENV_BYTES="$(apparent_bytes "$ENV_DIR")"
TOTAL_BYTES=$((MODEL_BYTES + ENV_BYTES))
awk -v bytes="$TOTAL_BYTES" -v limit="$MAX_ASSET_GIB" \
  'BEGIN {exit !(bytes <= limit * 1024 * 1024 * 1024)}' \
  || die "apparent new assets exceed ${MAX_ASSET_GIB} GiB"

SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
"$ENV_DIR/bin/python" - "$MODE" "$ROOT" "$START_FREE" "$END_FREE" \
  "$MODEL_BYTES" "$ENV_BYTES" "$SOURCE_COMMIT" "$CONFIG" "$META_DIR" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

mode, root, start_free, end_free, model_bytes, env_bytes, commit, config, meta = sys.argv[1:]
meta = Path(meta)
report = {
    "schema": "xtx-002-setup-report-v1",
    "mode": mode,
    "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "root": str(Path(root).resolve()),
    "source_commit": commit,
    "apparent_model_bytes": int(model_bytes),
    "apparent_env_bytes": int(env_bytes),
    "start_free_gib": float(start_free),
    "end_free_gib": float(end_free),
    "config": {"path": str(Path(config).resolve()), "sha256": __import__("hashlib").sha256(Path(config).read_bytes()).hexdigest()},
    "model_lock": str((meta.parent / "models" / "xturnix-pt.lock.json").resolve()),
    "verification": str((meta / "model_verification.json").resolve()),
}
target = meta / ("prepare_report.json" if mode == "prepare" else "verify_report.json")
temporary = target.with_name(target.name + ".part")
temporary.write_text(json.dumps(report, indent=2) + "\n")
temporary.replace(target)
print(json.dumps(report, indent=2))
PY

log "done"
