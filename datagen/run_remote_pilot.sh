#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: run_remote_pilot.sh CONDA_PREFIX OUTPUT_DIR" >&2
    exit 2
fi
pilot_conda_prefix="$1"
pilot_output_dir="$2"
pilot_source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
test -f "$pilot_conda_prefix/conda-meta/history"
test ! -e "$pilot_output_dir"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
ulimit -v 2097152
ulimit -f 32768
ulimit -t 110
pilot_cpu="$(awk '/Cpus_allowed_list/ {split($2, parts, /[-,]/); print parts[1]}' /proc/self/status)"
exec timeout --signal=TERM --kill-after=5s 120s taskset -c "$pilot_cpu" \
    "$pilot_conda_prefix/bin/python" "$pilot_source_root/datagen/build_pilot.py" \
    --source "$pilot_source_root/datagen/scenarios.json" --output "$pilot_output_dir"
