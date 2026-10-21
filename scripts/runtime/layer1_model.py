"""Share strict official checkpoint restoration between serving and training."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any


WIRE_TOKENS = (
    '<|no voice|>', '<|user is talking|>', '<|user finish talking|>',
    '<|user is thinking|>', '<|user interruption|>', '<|user backchannel|>',
)
LORA_NAME = re.compile(r'^llm\.base_model\.model\.model\.layers\.(\d+)\.self_attn\.(q_proj|v_proj)\.lora_([AB])\.default\.weight$')


def validate_prompt_ids(ids, tokenizer):
    """Check token bounds with one vocabulary lookup."""
    size = len(tokenizer)
    if any(token < 0 or token >= size for token in ids):
        raise ValueError('Prompt token ID outside the released vocabulary')


def validate_state_keys(expected, supplied):
    missing, extra = expected - supplied, supplied - expected
    if missing or extra:
        raise ValueError(f'Checkpoint keys mismatch: missing={sorted(missing)[:8]}, extra={sorted(extra)[:8]}')


def normalize_state_dict(state, expected):
    """Preserve all tensors while applying only the registered q/v base mapping."""
    normalized = {}
    for key, tensor in state.items():
        target = key
        if key not in expected:
            candidate = re.sub(r'\.(q_proj|v_proj)\.(weight|bias)$', r'.\1.base_layer.\2', key)
            if candidate in expected:
                target = candidate
        if target in normalized:
            raise ValueError(f'Checkpoint mapping collision: {target}')
        normalized[target] = tensor
    validate_state_keys(expected, set(normalized))
    return normalized


def sha256_file(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def verify_asset_inventory(inventory_path, checkpoint, base_model, official_source=None):
    """Verify complete frozen assets rather than trusting revision hints or paths."""
    inventory = json.loads(Path(inventory_path).read_text())
    roots = {'checkpoint': Path(checkpoint), 'base': Path(base_model)}
    if official_source is not None:
        roots['official_source'] = Path(official_source)
    rows = []
    for name, root in roots.items():
        files = inventory['assets'][name]['files']
        if not files:
            raise ValueError(f'Empty frozen asset inventory: {name}')
        for relative, item in files.items():
            if Path(relative).is_absolute() or '..' in Path(relative).parts:
                raise ValueError('Invalid frozen asset path')
            path = root / relative
            if 'sha256' not in item:
                raise ValueError(f'Frozen asset lacks full content digest: {name}/{relative}')
            if path.stat().st_size != item['bytes'] or sha256_file(path) != item['sha256']:
                raise ValueError(f'Frozen asset content mismatch: {name}/{relative}')
            rows.append({'asset': name, 'file': relative, 'bytes': item['bytes'], 'sha256': item['sha256']})
    return {'inventory_sha256': sha256_file(inventory_path), 'files': rows}


def restore_state(wrapper, state):
    """Check complete keys and shapes before allowing any parameter copy."""
    expected = wrapper.state_dict()
    restored = normalize_state_dict(state, set(expected))
    for key, tensor in restored.items():
        if tuple(tensor.shape) != tuple(expected[key].shape):
            raise ValueError(f'Checkpoint shape mismatch: {key}: {tuple(tensor.shape)} != {tuple(expected[key].shape)}')
    mapping = []
    for original in state:
        target = original if original in expected else re.sub(
            r'\.(q_proj|v_proj)\.(weight|bias)$', r'.\1.base_layer.\2', original)
        mapping.append({'source': original, 'target': target, 'shape': list(restored[target].shape),
                        'source_dtype': str(restored[target].dtype), 'target_dtype': str(expected[target].dtype)})
    wrapper.load_state_dict(restored, strict=True)
    return {'missing': [], 'unexpected': [], 'shape_mismatches': [], 'mapping': mapping,
            'parameter_tensors': len(restored)}


def configure_trainable(wrapper, layers):
    """Enable only the existing, complete official default q/v LoRA A/B set."""
    wrapper.requires_grad_(False)
    selected, observed = [], set()
    for name, parameter in wrapper.named_parameters():
        match = LORA_NAME.fullmatch(name)
        if match:
            layer, projection, part = match.groups()
            observed.add((int(layer), projection, part))
            parameter.requires_grad_(True)
            selected.append({'name': name, 'shape': list(parameter.shape), 'numel': parameter.numel(),
                             'dtype': str(parameter.dtype)})
    expected = {(i, projection, part) for i in range(layers)
                for projection in ('q_proj', 'v_proj') for part in ('A', 'B')}
    if observed != expected:
        wrapper.requires_grad_(False)
        raise ValueError(f'Incomplete existing q/v LoRA set: missing={sorted(expected-observed)}, extra={sorted(observed-expected)}')
    for name, parameter in wrapper.named_parameters():
        if parameter.requires_grad and not LORA_NAME.fullmatch(name):
            raise ValueError(f'Unexpected trainable parameter: {name}')
    return {'parameters': selected, 'tensors': len(selected), 'numel': sum(x['numel'] for x in selected),
            'frozen_embedding_and_head': True, 'adapter': 'existing_default_only'}


def state_fingerprints(wrapper, block_elements=1024 * 1024):
    """Hash tensors in bounded CPU transfers, including frozen embedding/head copies."""
    import torch
    result = {}
    for name, tensor in wrapper.state_dict().items():
        value = tensor.detach().reshape(-1)
        checksum = hashlib.sha256()
        for start in range(0, value.numel(), block_elements):
            block = value[start:start + block_elements].contiguous().to('cpu')
            checksum.update(block.view(torch.uint8).numpy().tobytes())
        result[name] = {'sha256': checksum.hexdigest(), 'dtype': str(tensor.dtype), 'shape': list(tensor.shape)}
    return result


@dataclass
class LoadedCheckpoint:
    tokenizer: Any
    model: Any
    wrapper: Any
    config: dict
    token_ids: dict
    info: dict
    load_audit: dict
    trainable_audit: dict | None


def load_official_checkpoint(checkpoint, base_model, device='cuda', training=False, phase=None):
    """Restore released tensors strictly before selecting an inference/training mode."""
    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from safetensors.torch import load_file
    from transformers import AutoModelForCausalLM, AutoTokenizer

    checkpoint, base_model = Path(checkpoint), Path(base_model)
    started = time.monotonic()
    phase = phase or (lambda name: None)
    cfg = json.loads((checkpoint / 'train_cfg.json').read_text())['model']
    if cfg.get('use_lora') != 'qv' or cfg.get('name') != 'Qwen/Qwen2-7B-Instruct':
        raise ValueError('Expected official Qwen2-7B-Instruct q/v LoRA checkpoint')
    tokenizer = AutoTokenizer.from_pretrained(str(checkpoint / 'tokenizer'), use_fast=True, local_files_only=True)
    token_ids = {}
    for marker in (*WIRE_TOKENS, '<|im_end|>'):
        ids = tokenizer.encode(marker, add_special_tokens=False)
        if len(ids) != 1 or tokenizer.convert_ids_to_tokens(ids[0]) != marker:
            raise ValueError(f'Expected one registered special token for {marker}')
        token_ids[marker] = ids[0]
    tokenizer.add_special_tokens({'additional_special_tokens': list(WIRE_TOKENS)})
    base = AutoModelForCausalLM.from_pretrained(str(base_model), local_files_only=True,
        torch_dtype=torch.bfloat16 if str(device).startswith('cuda') else torch.float32,
        trust_remote_code=bool(cfg.get('trust_remote_code', False)))
    phase('base_loaded')
    base.resize_token_embeddings(len(tokenizer))
    adapted = get_peft_model(base, LoraConfig(
        r=int(cfg.get('lora_r', 16)), lora_alpha=int(cfg.get('lora_alpha', 32)),
        lora_dropout=float(cfg.get('lora_dropout', 0.05)), bias=cfg.get('lora_bias', 'none'),
        task_type=TaskType.CAUSAL_LM, target_modules=['q_proj', 'v_proj'],
        modules_to_save=['embed_tokens', 'lm_head']))
    wrapper = torch.nn.Module()
    wrapper.add_module('llm', adapted)
    wrapper.to(device)
    phase('structure_on_device')
    state = load_file(str(checkpoint / 'model_state.safetensors'), device='cpu')
    phase('published_state_opened')
    load_audit = restore_state(wrapper, state)
    del state
    phase('published_state_restored')
    wrapper.requires_grad_(False)
    trainable = configure_trainable(wrapper, int(base.config.num_hidden_layers)) if training else None
    adapted.train(training)
    info = {'checkpoint': str(checkpoint.resolve()), 'base_model': str(base_model.resolve()),
            'load_seconds': time.monotonic() - started, 'token_ids': token_ids,
            'context_length': int(base.config.max_position_embeddings), 'torch': torch.__version__,
            'tokenizer_class': type(tokenizer).__name__, 'dtype': str(next(adapted.parameters()).dtype),
            'bos_token_id': tokenizer.bos_token_id}
    return LoadedCheckpoint(tokenizer, adapted, wrapper, cfg, token_ids, info, load_audit, trainable)
