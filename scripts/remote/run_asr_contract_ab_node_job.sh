#!/usr/bin/env bash
# Compare ASR streaming contracts on the FDB corpus.
#
# The question: the released decoder re-decodes its last ``unfixed_chunk_num``
# chunks (official default 2, our config uses 0) and ``unfixed_token_num`` tokens.
# Our runtime cannot show text that changes, so the service hides the still
# revisable tail; the comparison measures what the 2-chunk window would buy us and
# what it would cost, without running the LLM or the duplex runtime.
#
# `asr-smoke --audio-dir` drives the released streaming API *in this process*: one
# run per window needs no service and no port, and every event it writes carries
# both the raw transcript and the committed-prefix transcript, so a single run per
# window measures both exposures at once. The arms are therefore:
#
#   raw text (what the official demo exposes)  vs  committed prefix (our contract)
#   window 0 (our config)                      vs  window 2 (official default)
#
# Environment (set by the submit script):
#   INTERCLARIFY_ROOT, XTALK_ROUND1_ROOT, XTALK_ROUND1_MODEL_ROOT, RUN_TAG,
#   ASR_ENV, CLIENT_ENV, ASR_AB_AUDIO_ROOT, ASR_AB_PER_SUBSET, ASR_AB_WINDOWS
set -uo pipefail

TASK_ROOT="${INTERCLARIFY_ROOT:?set INTERCLARIFY_ROOT}"
ROUND1_ROOT="${XTALK_ROUND1_ROOT:?set XTALK_ROUND1_ROOT}"
MODEL_ROOT="${XTALK_ROUND1_MODEL_ROOT:?set XTALK_ROUND1_MODEL_ROOT}"
RUN_TAG="${RUN_TAG:-$(date -u +%Y%m%dT%H%M%SZ)}"
ASR_ENV="${ASR_ENV:-xtalk-round1-asr}"
CLIENT_ENV="${CLIENT_ENV:-xtalk-round1-client}"
AUDIO_ROOT="${ASR_AB_AUDIO_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/STS/data/fdb/v1_0}"
PER_SUBSET="${ASR_AB_PER_SUBSET:-8}"
WINDOWS="${ASR_AB_WINDOWS:-0 2}"
TOKEN_NUM="${ASR_AB_TOKEN_NUM:-5}"
CONFIG="${XTALK_CONFIG:-$TASK_ROOT/configs/xtalk_round1.yaml}"
ROUND1_PY="$TASK_ROOT/scripts/remote/run_xtalk_round1.py"

RUN_DIR="$TASK_ROOT/data/runs/asr_contract_$RUN_TAG"
REPORT_DIR="$TASK_ROOT/reports/asr_contract/$RUN_TAG"
INPUTS="$RUN_DIR/inputs"
mkdir -p "$RUN_DIR/logs" "$REPORT_DIR" "$INPUTS"
LOG="$RUN_DIR/run.log"
exec > >(tee -a "$LOG") 2>&1

echo "[asr-ab] tag=$RUN_TAG node=$(hostname) $(date -u +%FT%TZ)"
echo "[asr-ab] audio root=$AUDIO_ROOT per_subset=$PER_SUBSET windows='$WINDOWS' token_num=$TOKEN_NUM"

nvidia-smi --query-gpu=index,name,memory.total,driver.version --format=csv > "$RUN_DIR/gpu.csv" 2>&1 || true
RC=0
conda run -n "$CLIENT_ENV" python -c 'import hashlib,json,pathlib; root=pathlib.Path("'"$TASK_ROOT"'"); m=json.loads((root/"source_manifest.json").read_text()); bad=[n for n,d in m["files"].items() if not (root/n).is_file() or hashlib.sha256((root/n).read_bytes()).hexdigest()!=d]; assert not bad, bad[:5]; print("source_verified", len(m["files"]))' > "$RUN_DIR/source_check.txt" 2>&1 || RC=$?
if [ "$RC" -ne 0 ]; then
  echo "[asr-ab] source manifest mismatch; refusing to measure" | tee "$RUN_DIR/source_check.txt"
  exit 1
fi

# A deterministic, per-subset balanced sample: `asr-smoke --audio-dir` takes the
# first N `input.wav` files it walks, which would otherwise all come from the
# alphabetically first subset.
stage_inputs() {
  local subset name sample count
  for subset in "$AUDIO_ROOT"/*/; do
    [ -d "$subset" ] || continue
    name="$(basename "$subset")"
    count=0
    while IFS= read -r sample; do
      [ -f "$sample/input.wav" ] || continue
      # `asr-smoke --audio-dir` writes each result under the *basename* of the
      # input directory, and FDB sample numbers repeat across subsets, so the
      # staged label has to carry the subset or the arms silently overwrite
      # each other's samples.
      label="${name}__$(basename "$sample")"
      mkdir -p "$INPUTS/$label"
      ln -sf "$sample/input.wav" "$INPUTS/$label/input.wav"
      count=$(( count + 1 ))
      [ "$count" -ge "$PER_SUBSET" ] && break
    done < <(find "$subset" -mindepth 1 -maxdepth 1 -type d | sort)
    echo "[asr-ab] staged $count inputs from $name"
  done
}
stage_inputs
STAGED="$(find "$INPUTS" -name input.wav | wc -l)"
echo "[asr-ab] staged $STAGED inputs in total"
[ "$STAGED" -gt 0 ] || { echo "[asr-ab] no inputs staged; refusing to measure"; exit 1; }

declare -a ARM_SUMMARY=()
FAILURES=0
for WINDOW in $WINDOWS; do
  NAME="window-$WINDOW"
  OUT="$RUN_DIR/$NAME"
  echo "[asr-ab] $(date -u +%FT%TZ) arm=$NAME unfixed_chunk_num=$WINDOW unfixed_token_num=$TOKEN_NUM exposure=both"
  rm -rf "$OUT"
  RC=0
  conda run --no-capture-output -n "$ASR_ENV" \
    env PYTHONPATH="$TASK_ROOT/xtalk/src:$TASK_ROOT/scripts/remote" PYTHONUNBUFFERED=1 \
    python "$ROUND1_PY" --config "$CONFIG" --model-root "$MODEL_ROOT" \
    asr-smoke --audio-dir "$INPUTS" --output "$OUT" --gpu-index 0 \
    --unfixed-chunk-num "$WINDOW" --unfixed-token-num "$TOKEN_NUM" \
    --emit-committed-prefix \
    > "$RUN_DIR/logs/$NAME.smoke.log" 2>&1 || RC=$?
  echo "[asr-ab] arm=$NAME rc=$RC"
  if [ "$RC" -eq 0 ]; then
    ARM_SUMMARY+=("$NAME ok")
  else
    ARM_SUMMARY+=("$NAME FAILED")
    FAILURES=$(( FAILURES + 1 ))
    tail -20 "$RUN_DIR/logs/$NAME.smoke.log"
  fi
done

echo "[asr-ab] arms summary: ${ARM_SUMMARY[*]:-none}"
conda run --no-capture-output -n "$CLIENT_ENV" \
  python "$TASK_ROOT/scripts/remote/summarize_asr_contract.py" \
  --run-dir "$RUN_DIR" --report-dir "$REPORT_DIR" --tag "$RUN_TAG" || true

for artifact in asr_contract.md asr_contract.json; do
  [ -f "$REPORT_DIR/$artifact" ] && echo "[asr-ab] report: $REPORT_DIR/$artifact"
done
echo "[asr-ab] $(date -u +%FT%TZ) done; run dir $RUN_DIR"
exit "$FAILURES"
