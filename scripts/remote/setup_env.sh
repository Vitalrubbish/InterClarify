#!/usr/bin/env bash
# Create / refresh the InterClarify conda environment (P0).
#
# Runs on a login node or inside the P0 container.  Python is pinned through
# environment.yml; third-party packages are pinned through requirements.txt.
#
# Usage:
#   bash scripts/remote/setup_env.sh                 # create if missing
#   IC_RECREATE=1 bash scripts/remote/setup_env.sh   # delete and recreate
#   IC_INSTALL_DEV=1 bash scripts/remote/setup_env.sh
set -euo pipefail

REPO_ROOT="${INTERCLARIFY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ENV_NAME="${INTERCLARIFY_ENV_NAME:-interclarify-dev}"
PYPI_INDEX="${IC_PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
CONDA_BIN="${IC_CONDA_BIN:-conda}"

echo "[setup_env] repo=$REPO_ROOT env=$ENV_NAME"
echo "[setup_env] pip_index=$PYPI_INDEX"

# shellcheck disable=SC1091
source "${IC_CONDA_SH:-$HOME/miniconda3/etc/profile.d/conda.sh}" 2>/dev/null || true

if [[ "${IC_RECREATE:-0}" == "1" ]]; then
  echo "[setup_env] removing existing env $ENV_NAME"
  "$CONDA_BIN" env remove -n "$ENV_NAME" -y || true
fi

if "$CONDA_BIN" env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "[setup_env] env already exists; skipping create"
else
  CONDA_ALWAYS_YES=true "$CONDA_BIN" env create -f "$REPO_ROOT/environment.yml"
fi

ENV_PY="$(conda run -n "$ENV_NAME" python -c 'import sys; print(sys.executable)')"
echo "[setup_env] python=$ENV_PY"
echo "[setup_env] installing pinned requirements"
"$ENV_PY" -m pip install --no-cache-dir --upgrade pip
"$ENV_PY" -m pip install --no-cache-dir --index-url "$PYPI_INDEX" -r "$REPO_ROOT/requirements.txt"

if [[ "${IC_INSTALL_DEV:-0}" == "1" ]]; then
  echo "[setup_env] installing project (editable) + dev extras"
  "$ENV_PY" -m pip install --no-cache-dir --index-url "$PYPI_INDEX" -e "$REPO_ROOT[dev]"
fi

echo "[setup_env] done"
