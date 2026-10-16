#!/usr/bin/env bash
# Pair synchronous and deferred persistence without changing ASR inference.
set -euo pipefail
ASR_ROOT="${ASR_SELECTION_ROOT:?set ASR_SELECTION_ROOT}"
ASR_SOURCE="${ASR_SELECTION_SOURCE:?set ASR_SELECTION_SOURCE}"
PROBE_RUN="${ASR_LOGGING_RUN:?set ASR_LOGGING_RUN}"
CANDIDATE="${ASR_LOGGING_CANDIDATE:-nemotron_en}"
CHUNK="${ASR_LOGGING_CHUNK:-160}"
mkdir -p "$PROBE_RUN"
exec > >(tee -a "$PROBE_RUN/run.log") 2>&1
sha256sum -c "$ASR_SOURCE.sha256" > "$PROBE_RUN/source_check.txt"
export PYTHONNOUSERSITE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
nvidia-smi --query-gpu=name,uuid,driver_version --format=csv > "$PROBE_RUN/gpu.csv"
"$ASR_ROOT/envs/$CANDIDATE/bin/python" - "$ASR_ROOT" "$PROBE_RUN" <<'PY'
import json, pathlib, sys
root, out = map(pathlib.Path, sys.argv[1:])
manifest = json.loads((root / "dataset/manifest.json").read_text())
bad = {"15094027080386890060.wav", "15667010054869079797.wav", "9492244844910613453.wav",
       "14328568808003469713.wav", "7411546787616977704.wav", "14077379425479054842.wav",
       "12953138808800823203.wav"}
test = [r for r in manifest["samples"] if r["split"] == "test"]
selected = [r for r in test if pathlib.Path(r["path"]).name in bad]
selected += [r for r in test if pathlib.Path(r["path"]).name not in bad][:10-len(selected)]
manifest["samples"] = [r for r in manifest["samples"] if r["split"] == "dev"] + selected
manifest["purpose"] = "Stall-selected diagnostic subset, excluded from accuracy ranking"
(out / "manifest.json").write_text(json.dumps(manifest, indent=2))
PY
failures=0
for mode in synchronous buffered; do
  extra=()
  [ "$mode" = buffered ] && extra+=(--buffer-events)
  mkdir -p "$PROBE_RUN/$mode"
  if timeout 1200 "$ASR_ROOT/envs/$CANDIDATE/bin/python" -u "$ASR_SOURCE/benchmark_asr_selection.py" \
    --root "$ASR_ROOT" --manifest "$PROBE_RUN/manifest.json" --candidate "$CANDIDATE" \
    --chunk-ms "$CHUNK" --limit 10 --output "$PROBE_RUN/$mode" "${extra[@]}" \
    > "$PROBE_RUN/$mode/process.log" 2>&1; then
    code=0
  else
    code=$?
    failures=$((failures+1))
  fi
  printf '%s\n' "$code" > "$PROBE_RUN/$mode/exit_code.txt"
  echo "mode=$mode exit=$code"
done
exit "$(( failures > 0 ))"
