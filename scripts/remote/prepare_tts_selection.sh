#!/usr/bin/env bash
# Prepare isolated benchmark dependencies without running model inference.
set -euo pipefail
ROOT="${TTS_SELECTION_ROOT:?set experiment directory}"
CONDA_ROOT="${TTS_CONDA_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/miniconda3}"
BASE="${TTS_KYUTAI_ENV:-/hpc_stor03/sjtu_home/xuan.zhang/interclarify-asr-selection/envs/kyutai}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HOME="$ROOT/models/hf"
export HF_HUB_DISABLE_XET=1 HF_HUB_DOWNLOAD_TIMEOUT=120 HF_HUB_ETAG_TIMEOUT=20
mkdir -p "$ROOT/envs" "$ROOT/models"
if [ ! -e "$ROOT/envs/pocket/conda-meta/history" ]; then
  "$CONDA_ROOT/bin/conda" create -p "$ROOT/envs/pocket" --clone "$BASE" --offline -y
fi
"$ROOT/envs/pocket/bin/python" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple 'pocket-tts==3.3.0' 'kokoro==0.9.4'
"$ROOT/envs/pocket/bin/python" - <<'PYCODE'
import json
import os
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download
root = Path(os.environ['TTS_SELECTION_ROOT'])
# Read existing credentials only in memory; do not print them.
key = Path('/hpc_stor03/sjtu_home/xuan.zhang/InterClarify/hf_token.txt')
token = key.read_text().strip() if key.exists() else None
api = HfApi(token=token)
manifest = {}
def download(repo, filename, revision):
    path = hf_hub_download(repo, filename, revision=revision, token=token)
    manifest[f'{repo}/{filename}@{revision}'] = {'path': path, 'revision': revision}
    (root/'models'/'manifest.json').write_text(json.dumps(manifest, indent=2))
    return path
import pocket_tts
import re
config = Path(pocket_tts.__file__).parent/'config'/'english.yaml'
config_text = config.read_text()
(root/'models'/'pocket_english.yaml').write_text(config_text)
for source in re.findall(r'hf://([^\s]+)', config_text):
    parts = source.split('/', 2)
    repo = '/'.join(parts[:2])
    filename, revision = parts[2].rsplit('@', 1)
    try:
        download(repo, filename, revision)
    except Exception as exc:
        # The official loader falls back to weights without cloning when access is unavailable.
        if repo != 'kyutai/pocket-tts':
            raise
        print('Voice cloning weights unavailable:', type(exc).__name__, flush=True)
download('kyutai/pocket-tts-without-voice-cloning', 'languages/english/embeddings/alba.safetensors',
         '4e1e0a3e611c51c0b4ed8174fc10f32a54644303')
repo = 'hexgrad/Kokoro-82M'
info = api.model_info(repo)
for filename in ['config.json', 'kokoro-v1_0.pth', 'voices/af_heart.pt']:
    download(repo, filename, info.sha)
PYCODE
SPACY_WHEEL="$ROOT/models/en_core_web_sm-3.8.0-py3-none-any.whl"
[ -r "$SPACY_WHEEL" ] || { echo "Stage the official en_core_web_sm 3.8.0 wheel at $SPACY_WHEEL" >&2; exit 2; }
"$ROOT/envs/pocket/bin/python" -m pip install --no-deps "$SPACY_WHEEL"
"$ROOT/envs/pocket/bin/python" -m pip freeze > "$ROOT/models/packages.txt"
