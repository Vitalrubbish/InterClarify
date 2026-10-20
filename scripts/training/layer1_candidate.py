"""Restore a final adaptation checkpoint on the complete released inference model."""

from __future__ import annotations

import json
from pathlib import Path

from layer1_model import LORA_NAME, sha256_file, state_fingerprints, verify_asset_inventory


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_lora(parameters, supplied):
    """Validate every tensor before permitting the first parameter copy."""
    expected = {name for name in parameters if LORA_NAME.fullmatch(name)}
    require(expected and set(supplied) == expected, 'Candidate must contain exactly the existing q/v LoRA')
    for name, value in supplied.items():
        require(value.shape == parameters[name].shape and value.dtype == parameters[name].dtype,
                'Candidate tensor shape/dtype mismatch: ' + name)


def load_candidate(loaded, path, checkpoint, base_model, *, verification_only=False):
    import torch
    path = Path(path)
    directory = path.parent
    summary = json.loads((directory / 'summary.json').read_text())
    manifest = json.loads((directory / 'manifest.json').read_text())
    identity = manifest['identity']
    alignment = identity['config']['purpose'] == 'issue036_alignment'
    probe = alignment and identity.get('alignment_probe') is True
    require(not probe or verification_only, 'Alignment probe cannot be served as a formal candidate')
    require(summary['passed'] and summary['frozen_tensors_unchanged'] and
            ((probe and verification_only) or
             (summary['formal_training_released'] and manifest['formal_training_released'])),
            'Candidate training was not successfully completed')
    require((identity['config']['purpose'] == 'issue006_round1' and
             identity['config']['arm'] in ('T1', 'T2', 'T3')) or
            (alignment and identity['config']['condition'] == 'T2_R2_paper_aligned' and
             identity['config']['arm'] == 'T2'),
            'Only registered formal candidates can be served')
    if probe:
        require(0 < summary['final_step'] <= 100 and
                summary['cursor'] == summary['final_step'] * 2, 'Invalid alignment probe cursor')
    else:
        require(summary['final_step'] == identity['config']['scheduler_steps'] and
                summary['cursor'] == identity['data']['statistics']['sequences'], 'Candidate is not the final epoch')
    require(sha256_file(path) == summary['checkpoint']['sha256'], 'Final checkpoint digest mismatch')
    args = manifest['arguments']
    assets = verify_asset_inventory(Path(args['inventory']), checkpoint, base_model, Path(args['official_source']))
    require(assets == identity['assets'], 'Candidate fixed assets differ from official initialization')
    before = json.loads((directory / 'weights_before.json').read_text())
    after = json.loads((directory / 'weights_after.json').read_text())
    require(state_fingerprints(loaded.wrapper) == before, 'Restored official weights differ from training initialization')
    payload = torch.load(path, map_location='cpu', weights_only=False)
    require(payload['identity'] == identity and payload['step'] == summary['final_step'] and
            payload['cursor'] == summary['cursor'], 'Checkpoint identity or final cursor mismatch')
    parameters = dict(loaded.wrapper.named_parameters())
    validate_lora(parameters, payload['lora'])
    with torch.no_grad():
        for name, value in payload['lora'].items():
            require(bool(torch.isfinite(value).all()), 'Non-finite candidate parameter')
        for name, value in payload['lora'].items():
            parameters[name].copy_(value)
    del payload
    loaded.wrapper.requires_grad_(False)
    loaded.model.eval()
    require(state_fingerprints(loaded.wrapper) == after, 'Candidate inference weights differ from training final state')
    generation_probe = summary['protocol_probe']
    device = next(loaded.model.parameters()).device
    prompt = torch.tensor([generation_probe['prompt_ids']], dtype=torch.long, device=device)
    with torch.no_grad():
        generated = loaded.model.generate(input_ids=prompt, attention_mask=torch.ones_like(prompt),
            do_sample=False, max_new_tokens=64, eos_token_id=loaded.token_ids['<|im_end|>'],
            pad_token_id=loaded.token_ids['<|im_end|>'], use_cache=True)[0, prompt.shape[1]:].tolist()
    require(generated == generation_probe['generated_ids'], 'Clean-process generation differs from final training probe')
    return {'condition': identity['config'].get('condition', identity['config']['arm']),
            'inference_eligible': not probe, 'checkpoint_sha256': sha256_file(path),
            'final_step': summary['final_step'], 'cursor': summary['cursor'],
            'summary_sha256': sha256_file(directory / 'summary.json'),
            'train_manifest_sha256': sha256_file(directory / 'manifest.json'),
            'complete_inference_weights_match_training': True, 'clean_process_probe_ids_match': True,
            'generated_ids': generated}
