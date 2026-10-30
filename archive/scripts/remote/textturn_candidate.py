"""Validate a trained candidate and its frozen five-token input contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

TOKENS = {'<|tt_keep|>': 151669, '<|tt_start|>': 151670, '<|tt_stop|>': 151671,
          '<|no-voice|>': 151672, '<finish>': 151673}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def validate_candidate(training, data, config, model=None):
    """Reject incomplete, changed or unapproved training artifacts before loading weights."""
    training, data, config = map(Path, (training, data, config))
    candidate = read(training / 'candidate.json')
    run = read(training / 'run_manifest.json')
    manifest = read(data / 'manifest.json')
    reload = read(training / 'reload_verification.json')
    learning = read(training / 'learning_verification.json')
    gate = read(training / 'pilot_gate.json')
    if (candidate.get('continue_online') is not True or candidate.get('stage_completed') != 'full' or
            gate.get('continue_full') is not True or candidate.get('independent_test_used') is not False):
        raise ValueError('Training did not complete full stage with development permission')
    if (run['config'] != read(config) or run['dataset_manifest_sha256'] != digest(data / 'manifest.json') or
            manifest.get('new_token_ids') != TOKENS):
        raise ValueError('Training config, dataset or five-token identity changed')
    if (not all(reload.get(k) is True for k in
                ('identical_action_scores', 'identical_new_token_rows', 'new_rows_updated')) or
            learning.get('mean_loss_improved') is not True):
        raise ValueError('Learning or save/reload verification did not pass')
    adapter = training / 'best'
    if (Path(candidate['adapter']).resolve() != adapter.resolve() or
            digest(adapter / 'adapter_model.safetensors') != candidate['adapter_sha256']):
        raise ValueError('Selected adapter identity changed')
    adapter_config = read(adapter / 'adapter_config.json')
    if adapter_config.get('trainable_token_indices', {}).get('embed_tokens') != list(TOKENS.values()):
        raise ValueError('Saved weights do not register all five learned token rows')
    if read(adapter / 'tokenizer_config.json').get('added_tokens_decoder') is None:
        raise ValueError('Saved tokenizer missing')
    decoder = read(adapter / 'tokenizer_config.json')['added_tokens_decoder']
    if any(decoder.get(str(i), {}).get('content') != token for token, i in TOKENS.items()):
        raise ValueError('Saved tokenizer token IDs differ')
    if model is not None:
        model = Path(model)
        if (digest(model / 'config.json') != run['model_config_sha256'] or
                digest(model / 'model.safetensors') != run['model_weights_sha256']):
            raise ValueError('Base model identity changed')
    return {'training': str(training.resolve()), 'data': str(data.resolve()),
            'config': str(config.resolve()), 'adapter_sha256': candidate['adapter_sha256'],
            'dataset_manifest_sha256': digest(data / 'manifest.json'),
            'candidate_sha256': digest(training / 'candidate.json'), 'token_ids': TOKENS,
            'stage_completed': candidate['stage_completed']}
