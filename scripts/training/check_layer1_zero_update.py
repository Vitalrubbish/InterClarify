"""Compare strict training restoration against the pinned official Model independently."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

from layer1_data import digest, write_json
from layer1_model import (
    load_official_checkpoint, sha256_file, state_fingerprints, verify_asset_inventory,
)


def freeze_prompts(config, root):
    """Freeze pre-existing reference prompt IDs before either model is sampled."""
    result = []
    if config['prompts_per_case'] < 2:
        raise ValueError('At least two preregistered prompts per case are required')
    for case in config['cases']:
        path = root / config['reference_report_root'] / (case + '-independent_free_replay.json')
        report = json.loads(path.read_text())
        eligible = [r for r in report['reference']['requests']
                    if 0 < len(r['prompt_token_ids']) <= config['max_prompt_tokens'] and 'error' not in r]
        if len(eligible) < config['prompts_per_case']:
            raise ValueError(f'Insufficient frozen reference prompts: {case}')
        indices = [round(i * (len(eligible) - 1) / (config['prompts_per_case'] - 1))
                   for i in range(config['prompts_per_case'])]
        for i in indices:
            result.append({'case': case, 'request_index': report['reference']['requests'].index(eligible[i]),
                           'prompt_token_ids': eligible[i]['prompt_token_ids'],
                           'source_sha256': sha256_file(path)})
    return result


def load_reference(args, inventory):
    """Use untouched official Model source without the candidate loader or mapper."""
    import torch
    from safetensors.torch import load_file
    from transformers import AutoTokenizer

    source = args.official_source / 'model.py'
    expected = inventory['assets']['official_source']['files']['model.py']['sha256']
    if sha256_file(source) != expected:
        raise ValueError('Official reference source digest mismatch')
    spec = importlib.util.spec_from_file_location('pinned_duplex_reference_model', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cfg = json.loads((args.checkpoint / 'train_cfg.json').read_text())['model']
    tokenizer = AutoTokenizer.from_pretrained(str(args.checkpoint / 'tokenizer'), use_fast=True, local_files_only=True)
    reference = module.Model(tokenizer=tokenizer, model_name=str(args.base_model),
                             trust_remote_code=False, torch_dtype=torch.bfloat16)
    reference.enable_lora_adapter(mode=cfg['use_lora'], r=cfg['lora_r'], alpha=cfg['lora_alpha'],
                                  dropout=cfg['lora_dropout'], bias=cfg['lora_bias'])
    reference.to(args.device)
    state = load_file(str(args.checkpoint / 'model_state.safetensors'), device='cpu')
    expected_state = reference.state_dict()
    copied, mappings = {}, []
    for key, tensor in state.items():
        target = key
        if key not in expected_state:
            for projection in ('q_proj', 'v_proj'):
                for suffix in ('weight', 'bias'):
                    ending = f'.{projection}.{suffix}'
                    if key.endswith(ending):
                        target = key[:-len(ending)] + f'.{projection}.base_layer.{suffix}'
        if target not in expected_state or target in copied:
            raise ValueError(f'Unexpected/colliding reference tensor: {key}')
        if tuple(tensor.shape) != tuple(expected_state[target].shape):
            raise ValueError(f'Reference shape mismatch: {key}')
        copied[target] = tensor
        mappings.append({'source': key, 'target': target})
    if set(copied) != set(expected_state):
        raise ValueError('Reference is missing published tensors')
    reference.load_state_dict(copied, strict=True)
    del state, copied, expected_state
    reference.requires_grad_(False)
    reference.eval()
    return reference.llm, reference, tokenizer, {'mapping': mappings, 'strict': True, 'source_sha256': expected}


def worker(args):
    """Write full-vocabulary raw logits and tensor hashes in an isolated GPU process."""
    import torch
    from safetensors.torch import save_file

    config = yaml.safe_load(args.config.read_text())
    inventory = json.loads(args.inventory.read_text())
    torch.manual_seed(20261018)
    torch.cuda.manual_seed_all(20261018)
    torch.backends.cuda.matmul.allow_tf32 = False
    if args.worker == 'reference':
        model, wrapper, tokenizer, audit = load_reference(args, inventory)
        trainable = None
    else:
        loaded = load_official_checkpoint(args.checkpoint, args.base_model, args.device, training=True)
        model, wrapper, tokenizer = loaded.model, loaded.wrapper, loaded.tokenizer
        audit, trainable = loaded.load_audit, loaded.trainable_audit
        model.eval()
    before = state_fingerprints(wrapper)
    rows = []
    prompts = json.loads((args.output / 'prompts.json').read_text())
    destination = args.output / args.worker
    destination.mkdir(exist_ok=False)
    for index, row in enumerate(prompts):
        ids = row['prompt_token_ids']
        if len(ids) + config['max_new_tokens'] > model.config.max_position_embeddings:
            raise ValueError('Frozen prompt exceeds actual context')
        inputs = torch.tensor([ids], dtype=torch.long, device=args.device)
        with torch.inference_mode():
            generated = model.generate(input_ids=inputs, attention_mask=torch.ones_like(inputs),
                max_new_tokens=config['max_new_tokens'], do_sample=False,
                eos_token_id=tokenizer.eos_token_id, pad_token_id=tokenizer.pad_token_id,
                return_dict_in_generate=True, output_logits=True, use_cache=True, num_logits_to_keep=1)
        output_ids = generated.sequences[0, len(ids):].tolist()
        logits = torch.stack([x[0].float().cpu() for x in generated.logits])
        if not torch.isfinite(logits).all() or len(output_ids) != logits.shape[0]:
            raise ValueError('Invalid raw generation logits')
        path = destination / f'{index:03d}.safetensors'
        save_file({'logits': logits}, str(path))
        rows.append({'case': row['case'], 'prompt_sha256': digest(ids), 'generated_ids': output_ids,
                     'logits_file': path.name, 'logits_sha256': sha256_file(path), 'shape': list(logits.shape)})
    after = state_fingerprints(wrapper)
    if before != after:
        raise ValueError('Parameters changed during zero-update inference')
    write_json(destination / 'weights.json', before)
    write_json(destination / 'report.json', {'rows': rows, 'load_audit': audit, 'trainable_audit': trainable,
        'weights_unchanged': True, 'weights_sha256': digest(before), 'torch': torch.__version__,
        'dtype': str(next(model.parameters()).dtype), 'peak_cuda_bytes': torch.cuda.max_memory_allocated(),
        'training_allowed': False})


def compare_outputs(directory, config):
    """Use frozen elementwise tolerances and exact generation/control identity."""
    import torch
    from safetensors.torch import load_file
    reports = [json.loads((directory / name / 'report.json').read_text()) for name in ('reference', 'candidate')]
    if len(reports[0]['rows']) != len(reports[1]['rows']) or not reports[0]['rows']:
        raise ValueError('Missing zero-update cases')
    weights = [json.loads((directory / name / 'weights.json').read_text()) for name in ('reference', 'candidate')]
    if weights[0] != weights[1]:
        raise ValueError('Independent restored tensor fingerprints differ')
    rows = []
    for left, right in zip(reports[0]['rows'], reports[1]['rows']):
        if left['case'] != right['case'] or left['prompt_sha256'] != right['prompt_sha256']:
            raise ValueError('Reference and candidate prompts differ')
        tensors = []
        for name, row in zip(('reference', 'candidate'), (left, right)):
            path = directory / name / row['logits_file']
            if sha256_file(path) != row['logits_sha256']:
                raise ValueError('Raw logit artifact changed')
            tensors.append(load_file(str(path))['logits'])
        a, b = tensors
        same_shape = a.shape == b.shape
        logits_ok = same_shape and torch.isfinite(a).all().item() and torch.isfinite(b).all().item() and torch.allclose(
            b, a, atol=config['logits_atol'], rtol=config['logits_rtol'])
        ids_ok = left['generated_ids'] == right['generated_ids']
        rows.append({'case': left['case'], 'prompt_sha256': left['prompt_sha256'], 'ids_equal': ids_ok,
                     'logits_passed': bool(logits_ok), 'max_abs_error': (a-b).abs().max().item() if same_shape else None,
                     'generated_tokens': len(left['generated_ids'])})
    return {'passed': all(r['ids_equal'] and r['logits_passed'] for r in rows), 'rows': rows,
            'weights_identical': True, 'weights_unchanged': all(r['weights_unchanged'] for r in reports),
            'trainable_audit': reports[1]['trainable_audit'], 'training_allowed': False}


def run(args):
    config = yaml.safe_load(args.config.read_text())
    if config['schema_version'] != 1 or config['dtype'] != 'bfloat16' or config['do_sample'] is not False:
        raise ValueError('Unsupported zero-update configuration')
    if config['max_new_tokens'] != 64 or config['logits_atol'] != 0.02 or config['logits_rtol'] != 0.01:
        raise ValueError('Zero-update tolerances/settings differ from the registered protocol')
    if args.device != 'cuda':
        raise ValueError('Registered BF16 zero-update comparison requires an allocated CUDA device')
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / 'config.json', config)
    assets = verify_asset_inventory(args.inventory, args.checkpoint, args.base_model, args.official_source)
    write_json(args.output / 'assets.json', assets)
    prompts = freeze_prompts(config, args.root)
    write_json(args.output / 'prompts.json', prompts)
    write_json(args.output / 'preregistered.json', {'config_sha256': sha256_file(args.config),
        'prompts_sha256': digest(prompts), 'assets_sha256': digest(assets),
        'code_sha256': {p.name: sha256_file(p) for p in (Path(__file__), Path(__file__).with_name('layer1_model.py'))}})
    for kind in ('reference', 'candidate'):
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', kind,
                   '--config', str(args.config.resolve()), '--inventory', str(args.inventory.resolve()),
                   '--checkpoint', str(args.checkpoint), '--base-model', str(args.base_model),
                   '--official-source', str(args.official_source), '--output', str(args.output.resolve()),
                   '--device', args.device, '--root', str(args.root.resolve())]
        with (args.output / (kind + '.log')).open('w') as log:
            subprocess.run(command, check=True, timeout=600, stdout=log, stderr=subprocess.STDOUT)
    result = compare_outputs(args.output, config)
    write_json(args.output / 'comparison.json', result)
    if not result['passed']:
        raise ValueError('Zero-update comparison failed')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/layer1_zero_update.yaml'))
    parser.add_argument('--inventory', type=Path, default=Path('reports/layer1_training/issue001-inventory-20261018/inventory_summary.json'))
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--base-model', type=Path, required=True)
    parser.add_argument('--official-source', type=Path, required=True)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', choices=('reference', 'candidate'))
    args = parser.parse_args()
    if args.worker:
        worker(args)
    else:
        try:
            print(json.dumps({'passed': run(args)['passed'], 'training_allowed': False}))
        except Exception as error:
            if args.output.exists():
                write_json(args.output / 'failure.json', {'passed': False, 'training_allowed': False,
                    'error': f'{type(error).__name__}: {error}'})
            raise
