"""Load pinned local SoulX/SenseVoice assets through the official entry point."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch

try:
    from .native_soulx import NativeSoulX
except ImportError:
    from native_soulx import NativeSoulX


CONFIG = Path(__file__).parents[2] / 'configs/native_soulx.json'
_LOAD_LOCK = threading.Lock()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def verify_files(root, files):
    observed = {}
    for name, expected in files.items():
        observed[name] = digest(Path(root) / name)
        if observed[name] != expected:
            raise ValueError(f'Frozen file digest differs: {name}')
    return observed


def verify_source(upstream, frozen):
    upstream = Path(upstream).resolve()
    commit = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(upstream), 'status', '--porcelain'], text=True).strip()
    if commit != frozen['source_commit'] or dirty:
        raise ValueError('Official SoulX checkout must be pinned and clean')
    return verify_files(upstream, frozen['source_files'])


def load_native_controller(upstream, soulx_assets, sensevoice_assets, run_dir, **callbacks):
    """Resolve asset paths only; preserve native initialization and inference."""
    import yaml
    frozen = json.loads(CONFIG.read_text())
    upstream, soulx_assets, sensevoice_assets = [Path(p).resolve() for p in (upstream, soulx_assets, sensevoice_assets)]
    run_dir = Path(run_dir)
    evidence = {'frozen_config_sha256': digest(CONFIG), 'source': verify_source(upstream, frozen),
                'soulx': verify_files(soulx_assets, frozen['soulx_files']),
                'sensevoice': verify_files(sensevoice_assets, frozen['sensevoice_files']),
                'source_commit': frozen['source_commit'], 'soulx_revision': frozen['soulx_revision'],
                'sensevoice_revision': frozen['sensevoice_revision']}
    config = deepcopy(frozen['runtime_config'])
    for key in ('glm_tokenizer_path', 'model_name', 'init_ckpt_path_lora'):
        config['model_config'][key] = str(soulx_assets / Path(config['model_config'][key]).relative_to('pretrained_models'))
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / 'native_soulx.yaml'
    with config_path.open('x') as stream:
        yaml.safe_dump(config, stream, sort_keys=False)
    with (run_dir / 'native_assets.json').open('x') as stream:
        json.dump(evidence, stream, indent=2)
        stream.write('\n')
    with _LOAD_LOCK:
        # Official modules have generic names; never reuse an unrelated cached module.
        for name in ('service', 'model', 'config', 'utils'):
            module = sys.modules.get(name)
            if module:
                paths = list(getattr(module, '__path__', []))
                if not paths or any(not Path(p).resolve().is_relative_to(upstream) for p in paths):
                    raise RuntimeError(f'Conflicting Python module: {name}; use a fresh worker')
        sys.path.insert(0, str(upstream))
        import torch
        import funasr
        auto_model = funasr.AutoModel

        def local_sensevoice(*args, **kwargs):
            if args or kwargs.get('model') != 'iic/SenseVoiceSmall':
                raise ValueError('Unexpected native ASR asset request')
            return auto_model(**dict(kwargs, model=str(sensevoice_assets)))

        offline = {'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'MODELSCOPE_OFFLINE': '1'}
        with patch.dict(os.environ, offline), patch.object(funasr, 'AutoModel', local_sensevoice):
            module = importlib.import_module('service.model')
            model = module.TurnModel(config_path=str(config_path))
        tokenizer = model.model.tokenizer
        for token, token_id in (('<|user_complete|>', 151676), ('<|user_backchannel|>', 151677),
                                ('<|user_incomplete|>', 151678), ('<|user_idle|>', 151680),
                                ('<|user_nonidle|>', 151681)):
            if (tokenizer.encode(token, add_special_tokens=False) != [token_id]
                    or tokenizer.decode([token_id], skip_special_tokens=False) != token):
                raise ValueError(f'Frozen SoulX state vocabulary differs: {token}')
        torch.cuda.synchronize()
    result = NativeSoulX(model, synchronize=torch.cuda.synchronize, **callbacks)
    result.asset_manifest = evidence
    return result
