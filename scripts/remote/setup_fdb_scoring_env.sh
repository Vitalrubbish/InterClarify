#!/usr/bin/env bash
# Pin the FDB scoring environment to a CUDA 12.x torch and a NeMo 2.x release.
#
# The official FDB alignment script calls ASRModel.from_pretrained on a NeMo 1.x
# style parakeet archive. NeMo 3.0 made ASRModel abstract, and the unpinned torch
# that a plain install resolves to is built for CUDA 13, which the cluster driver
# (570.x, CUDA 12.8) cannot run. This script pins both.
set -euo pipefail

ENV_NAME="${FDB_ENV_NAME:-full-duplex-bench}"
CONDA_SH="${CONDA_SH:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/etc/profile.d/conda.sh}"
PYPI_MIRROR="${FDB_PYPI_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
TORCH_INDEX="${FDB_TORCH_INDEX:-https://download.pytorch.org/whl/cu126}"
TORCH_VERSION="${FDB_TORCH_VERSION:-2.6.0}"
NEMO_VERSION="${FDB_NEMO_VERSION:-2.6.2}"
SNAPSHOT="${FDB_PIPFREEZE_SNAPSHOT:-/hpc_stor03/sjtu_home/xuan.zhang/${ENV_NAME}.pipfreeze.$(date -u +%Y%m%d).txt}"

# shellcheck disable=SC1090
source "$CONDA_SH"

# Keep a pre-change snapshot so the downgrade stays auditable and reversible.
conda run -n "$ENV_NAME" python -m pip freeze > "$SNAPSHOT" || true
echo "snapshot: $SNAPSHOT"

# The PyTorch index carries torch and its own runtime dependencies.
conda run --no-capture-output -n "$ENV_NAME" python -m pip install --index-url "$TORCH_INDEX" \
  "torch==${TORCH_VERSION}" "torchaudio==${TORCH_VERSION}"

# NeMo 2.x is the release the official FDB alignment code targets.
conda run --no-capture-output -n "$ENV_NAME" python -m pip install -i "$PYPI_MIRROR" \
  "nemo_toolkit[asr]==${NEMO_VERSION}"

# NeMo 2.6 declares cuda-bindings but guards every use of it in try/except and
# falls back to its partial-graph PyTorch decoder (CudaGraphsMode.NO_WHILE_LOOPS)
# when cuda-python cannot be imported. That fallback is what a 570.x driver needs:
# the conditional-node decoder wants CUDA 13 bindings on a >= 580 driver
# (CUDA 12 bindings return a different tuple arity than NeMo unpacks, and CUDA 13
# bindings fail graph capture with cudaErrorInsufficientDriver), and the official
# get_transcript/asr.py has no switch to disable it. Remove the package that
# NeMo's asr extra pulled in so the supported fallback engages; decoding stays
# numerically identical, only slower.
conda run --no-capture-output -n "$ENV_NAME" python -m pip uninstall -y cuda-bindings

# The same asr extra also pulls numba-cuda, which refuses to import without
# cuda-bindings. Its documented switch makes it use ctypes bindings that talk to
# libcuda directly, so the environment needs both changes to import NeMo's ASR
# stack without cuda-python. Persist the switch so every `conda run -n` inherits it.
conda env config vars set -n "$ENV_NAME" NUMBA_CUDA_USE_NVIDIA_BINDING=0

conda run --no-capture-output -n "$ENV_NAME" python -c "
import os, torch, nemo, nemo.collections.asr as nemo_asr
from numba import cuda  # noqa: F401
print('torch', torch.__version__, 'cuda', torch.version.cuda, 'available', torch.cuda.is_available())
print('nemo', nemo.__version__)
print('ASRModel abstract methods:', getattr(nemo_asr.models.ASRModel, '__abstractmethods__', None))
print('NUMBA_CUDA_USE_NVIDIA_BINDING =', os.environ.get('NUMBA_CUDA_USE_NVIDIA_BINDING'))
try:
    import cuda.bindings  # noqa: F401
    print('cuda-python present: conditional-node graphs would need a driver >= 580')
except ImportError:
    print('cuda-python absent: NeMo uses its partial-graph fallback (NO_WHILE_LOOPS)')
# The partial-graph fallback still captures torch CUDA graphs, so verify that.
stream = torch.cuda.Stream()
stream.wait_stream(torch.cuda.current_stream())
with torch.cuda.stream(stream):
    tensor = torch.ones(2048, 2048, device='cuda')
    for _ in range(3):
        tensor = tensor * 2
torch.cuda.current_stream().wait_stream(stream)
graph = torch.cuda.CUDAGraph()
with torch.cuda.graph(graph):
    tensor = tensor * 2
print('CUDA graph capture OK')
"
