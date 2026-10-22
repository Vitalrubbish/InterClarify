#!/usr/bin/env bash
# Install the pinned X2-Turn vLLM overlay into an isolated conda environment.
#
# vLLM comes from the official 0.19.1 wheel.  A source build needs a full CUDA
# toolchain and far more than the 4 CPU / 16 GiB install budget, and the
# scheduler nodes cannot reach github.com, so the ten pinned source files are
# supplied as a small verified bundle.  Every wheel file is checked against the
# git blob id recorded in the overlay patch before the patch is applied, which
# proves it is byte-identical to the pinned commit.
set -euo pipefail

ROOT="${X2_TURN_ROOT:?set frozen X2 Turn experiment root}"
OUTPUT="${X2_TURN_SETUP_OUTPUT:?set a new setup output directory}"
BUNDLE_SHA256="${X2_TURN_SOURCE_BUNDLE_SHA256:?set the expected source bundle sha256}"
CONDA="${X2_TURN_CONDA:-$HOME/miniconda3/bin/conda}"
ENV_PREFIX="${X2_TURN_CONDA_ENV:-$HOME/miniconda3/envs/interclarify-x2-turn-vllm}"
CONDA_MIRROR="${X2_TURN_CONDA_MIRROR:-https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge}"
PIP_INDEX="${X2_TURN_PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
ARCHIVE="$ROOT/source/x2_turn_sources.tar.gz"
BUNDLE="$ROOT/source/x2_turn_sources"

[ ! -e "$OUTPUT" ] || { echo "Output already exists: $OUTPUT" >&2; exit 2; }
mkdir -p "$OUTPUT" "$ROOT/env" "$ROOT/logs"

export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
export PIP_NO_CACHE_DIR=1

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { echo "FAILED: $*" >&2; exit 1; }
capacity() { df -B1 --output=avail "$ROOT" | tail -1 | awk '{printf "%.1f", $1/1024/1024/1024}'; }

FREE_GIB="$(capacity)"
log "free disk on $ROOT: ${FREE_GIB} GiB"
awk -v free="$FREE_GIB" 'BEGIN { if (free < 100) { print "Need >=100 GiB free"; exit 1 } }'

# 1. Isolated conda environment.  Active component environments are untouched.
if [ ! -x "$ENV_PREFIX/bin/python" ]; then
  log "creating conda environment $ENV_PREFIX"
  "$CONDA" create -y -p "$ENV_PREFIX" --override-channels -c "$CONDA_MIRROR" \
    python=3.11 pip >"$OUTPUT/conda_create.log" 2>&1
else
  log "reusing conda environment $ENV_PREFIX"
fi
PY="$ENV_PREFIX/bin/python"
"$PY" -V >"$OUTPUT/python_version.txt"

# 2. Official vLLM wheel plus the runtime pieces the service and probes need.
if "$PY" -c 'import vllm, sys; sys.exit(0 if vllm.__version__ == "0.19.1" else 1)' 2>/dev/null; then
  log "vllm 0.19.1 already installed in $ENV_PREFIX"
else
  log "installing vllm==0.19.1 from $PIP_INDEX"
  "$PY" -m pip install --index-url "$PIP_INDEX" \
    "vllm==0.19.1" mistral-common soundfile websockets huggingface_hub \
    >"$OUTPUT/pip_install.log" 2>&1
fi
"$PY" -m pip freeze >"$OUTPUT/pip_freeze.txt"

# 3. Verified source bundle.  It is built on a machine with GitHub access and
# transferred once; the expected hash is passed in so corruption is detected.
[ -f "$ARCHIVE" ] || fail "missing source bundle $ARCHIVE"
ACTUAL_SHA="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
[ "$ACTUAL_SHA" = "$BUNDLE_SHA256" ] || fail "source bundle sha256 $ACTUAL_SHA != $BUNDLE_SHA256"
if [ ! -d "$BUNDLE" ]; then
  log "extracting source bundle"
  tar -xzf "$ARCHIVE" -C "$ROOT/source" --no-same-owner
fi
PATCH="$BUNDLE/x2/voxtral-realtime/patches/vllm-voxtral-mtp.patch"
UTILS_REL="vllm/model_executor/models/voxtral_mtp_utils.py"
UTILS_SRC="$BUNDLE/x2/voxtral-realtime/integrations/vllm/$UTILS_REL"
[ -f "$PATCH" ] || fail "missing overlay patch in the bundle"
[ -f "$UTILS_SRC" ] || fail "missing turn-head helper in the bundle"

SITE="$("$PY" -c 'import vllm, pathlib; print(pathlib.Path(vllm.__file__).parent.parent)')"

# 4. Compare every wheel file with the patch pre-image: the wheel is only
# interchangeable with the pinned source if the git blob ids agree.
"$PY" - "$PATCH" "$OUTPUT/patched_files.tsv" <<'PY'
import re
import sys

patch, target = sys.argv[1], sys.argv[2]
text = open(patch, encoding="utf-8").read()
entries = re.findall(
    r"^diff --git a/(\S+) b/\S+\nindex ([0-9a-f]+)\.\.([0-9a-f]+)", text, re.M
)
if len(entries) != 10:
    raise SystemExit(f"expected 10 patched files, found {len(entries)}")
with open(target, "w", encoding="utf-8") as stream:
    for path, pre, post in entries:
        stream.write(f"{path}\t{pre}\t{post}\n")
PY
: >"$OUTPUT/wheel_vs_source.tsv"
FRESH=0
PATCHED=0
while IFS=$'\t' read -r rel pre post; do
  wheel_sha="$(git hash-object "$SITE/$rel")"
  bundle_sha="$(git hash-object "$BUNDLE/vllm/$rel")"
  printf '%s\t%s\t%s\t%s\t%s\n' "$rel" "$wheel_sha" "$bundle_sha" "$pre" "$post" \
    >>"$OUTPUT/wheel_vs_source.tsv"
  [ "$bundle_sha" = "$pre" ] || fail "$rel: bundle blob $bundle_sha != pinned pre-image $pre"
  case "$wheel_sha" in
    "$pre") FRESH=$((FRESH + 1)) ;;
    "$post") PATCHED=$((PATCHED + 1)) ;;
    *) fail "$rel: wheel blob $wheel_sha matches neither pinned pre-image $pre nor post-image $post" ;;
  esac
done <"$OUTPUT/patched_files.tsv"
if [ "$FRESH" -ne 0 ] && [ "$PATCHED" -ne 0 ]; then
  fail "site-packages is in a mixed overlay state ($FRESH fresh, $PATCHED patched)"
fi
if [ "$PATCHED" -ne 0 ]; then
  MODE=patched
  log "wheel files already carry the pinned overlay; skipping patch application"
else
  MODE=fresh
  log "wheel and bundle match the pinned pre-image for all ${FRESH} files"
fi

# 5. Apply the overlay in a throwaway git index so `git apply --index` verifies
# both the pre-image and the post-image blob ids.
STAGE="$OUTPUT/overlay_stage"
if [ "$MODE" = fresh ]; then
  rm -rf "$STAGE"
  mkdir -p "$STAGE"
  while IFS=$'\t' read -r rel _ _; do
    install -Dm644 "$BUNDLE/vllm/$rel" "$STAGE/$rel"
  done <"$OUTPUT/patched_files.tsv"
  git init -q "$STAGE"
  git -C "$STAGE" add -A
  git -C "$STAGE" apply --index "$PATCH" >"$OUTPUT/overlay_install.log" 2>&1
  git -C "$STAGE" ls-files -s >"$OUTPUT/overlay_index.txt"
  "$PY" - "$OUTPUT/patched_files.tsv" "$OUTPUT/overlay_index.txt" <<'PY'
import sys

expected = {}
for line in open(sys.argv[1], encoding="utf-8"):
    rel, pre, post = line.rstrip("\n").split("\t")
    expected[rel] = post
actual = {}
for line in open(sys.argv[2], encoding="utf-8"):
    _, blob, _, rel = line.split()
    actual[rel] = blob
if set(actual) != set(expected):
    raise SystemExit(f"staged file set differs: {sorted(actual)} vs {sorted(expected)}")
bad = [rel for rel, post in expected.items() if actual[rel] != post]
if bad:
    raise SystemExit(f"post-image blob mismatch: {bad}")
print("all post-image blob ids match the overlay patch")
PY

  # 6. Install the patched modules and the new helper over the wheel.
  while IFS=$'\t' read -r rel _ _; do
    install -Dm644 "$STAGE/$rel" "$SITE/$rel"
  done <"$OUTPUT/patched_files.tsv"
fi
: >"$OUTPUT/installed_files.tsv"
while IFS=$'\t' read -r rel _ _; do
  printf '%s\t%s\n' "$rel" "$(sha256sum "$SITE/$rel" | cut -d' ' -f1)" \
    >>"$OUTPUT/installed_files.tsv"
done <"$OUTPUT/patched_files.tsv"
install -Dm644 "$UTILS_SRC" "$SITE/$UTILS_REL"
UTILS_SHA="$(sha256sum "$SITE/$UTILS_REL" | cut -d' ' -f1)"
[ "$UTILS_SHA" = "$(sha256sum "$UTILS_SRC" | cut -d' ' -f1)" ] || fail "helper copy mismatch"

# 7. Import check: the served model only reports turns if this module loads and
# the realtime protocol exposes turn.delta.
"$PY" - >"$OUTPUT/import_check.json" 2>"$OUTPUT/import_check.log" <<'PY'
import json
import vllm
from vllm.entrypoints.openai.realtime.protocol import TurnDelta
from vllm.model_executor.models.voxtral_mtp_utils import (
    TURN_CLASS_IDS,
    TURN_CLASS_NAMES,
)
print(json.dumps({
    "vllm_version": vllm.__version__,
    "vllm_module": vllm.__file__,
    "turn_delta": TurnDelta.__name__,
    "turn_class_ids": TURN_CLASS_IDS,
    "turn_class_names": TURN_CLASS_NAMES,
}, indent=2))
PY

"$PY" - "$OUTPUT" "$ROOT" "$ENV_PREFIX" "$SITE" "$BUNDLE" "$ARCHIVE" \
  "$BUNDLE_SHA256" "$UTILS_REL" "$UTILS_SHA" "$PIP_INDEX" "$CONDA_MIRROR" \
  "$(capacity)" "$MODE" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

(output, root, prefix, site, bundle, archive, bundle_sha, utils_rel, utils_sha,
 pip_index, conda_mirror, free_gib, mode) = sys.argv[1:]
output = Path(output)
bundle = Path(bundle)

pre = {}
for line in (output / "patched_files.tsv").read_text().splitlines():
    rel, pre_hash, post_hash = line.split("\t")
    pre[rel] = {"pre_image_blob": pre_hash, "post_image_blob": post_hash}
wheel = {}
for line in (output / "wheel_vs_source.tsv").read_text().splitlines():
    rel, wheel_hash, bundle_hash, expected, post = line.split("\t")
    wheel[rel] = {"wheel_blob": wheel_hash, "bundle_blob": bundle_hash,
                  "pinned_blob": expected, "post_image_blob": post}
installed = {}
for line in (output / "installed_files.tsv").read_text().splitlines():
    rel, digest = line.split("\t")
    installed[rel] = digest
manifest = json.loads((bundle / "manifest.json").read_text())
transfer = Path(root) / "source" / "x2_turn_sources.manifest.json"
transfer_manifest = (
    json.loads(transfer.read_text()).get("archive", {}).get("sha256")
    if transfer.is_file()
    else None
)
import_check = json.loads((output / "import_check.json").read_text())
packages = {}
for wanted in ("vllm", "torch", "mistral-common", "huggingface_hub", "websockets", "soundfile"):
    for line in (output / "pip_freeze.txt").read_text().splitlines():
        if line.lower().replace("_", "-").startswith(wanted.lower() + "=="):
            packages[wanted] = line.split("==", 1)[1]
            break
lock = {
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "root": root,
    "conda_env": prefix,
    "python": (output / "python_version.txt").read_text().strip(),
    "install_method": "official wheel + overlay applied to pinned pre-image blobs",
    "overlay_state": mode,
    "pip_index": pip_index,
    "conda_mirror": conda_mirror,
    "free_disk_gib_after": float(free_gib),
    "source_bundle": {
        "archive": str(archive),
        "sha256": bundle_sha,
        "manifest": str(bundle / "manifest.json"),
        "manifest_archive_sha256": transfer_manifest,
        "x2_turn_commit": manifest["x2_turn"]["commit"],
        "vllm_commit": manifest["vllm"]["commit"],
        "vllm_tag": manifest["vllm"]["tag"],
        "patched_files": {
            rel: {**pre[rel], **wheel[rel], "installed_sha256": installed[rel]}
            for rel in pre
        },
        "overlay_helper": {
            "path": utils_rel,
            "sha256": utils_sha,
            "bundle_sha256": manifest["x2_turn"]["files"][
                "voxtral-realtime/integrations/vllm/" + utils_rel
            ]["sha256"],
        },
    },
    "vllm": {
        "version": import_check["vllm_version"],
        "site_packages": site,
        "wheel_matches_pinned_commit": all(
            item["wheel_blob"] == item["pinned_blob"] for item in wheel.values()
        ),
    },
    "packages": packages,
    "import_check": import_check,
    "pip_freeze": (output / "pip_freeze.txt").read_text().splitlines(),
}
target = Path(root) / "env" / "x2_turn_vllm_environment.json"
temporary = target.with_name(target.name + ".part")
temporary.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
os.replace(temporary, target)
print(f"wrote {target}")
PY

log "environment ready: $ENV_PREFIX"
log "free disk after install: $(capacity) GiB"
