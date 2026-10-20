"""Run bounded official-checkpoint adaptation and audit exact training recovery."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import resource
import shutil
import subprocess
import time

import yaml

from layer1_data import ReleasedTokenizer, SequenceEncoder, digest, write_json
from layer1_model import (LORA_NAME, load_official_checkpoint, sha256_file,
                          state_fingerprints, verify_asset_inventory)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_sequence(row):
    """Reject target leakage, duplicate supervision and invalid event boundaries."""
    ids, labels, attention = row['input_ids'], row['labels'], row['attention_mask']
    require(len(ids) == len(labels) == len(attention) and len(ids) > 1, 'Invalid sequence lengths')
    require(all(x == 1 for x in attention), 'Serialized data must not contain padding')
    require(labels[0] == -100, 'First token cannot be a causal target')
    expected = [-100] * len(ids)
    previous = 0
    for span in row['spans']:
        start, target, end = span['start'], span['target_start'], span['end']
        require(start == previous and start < target < end <= len(ids), 'Invalid target span')
        if span['supervised']:
            expected[target:end] = ids[target:end]
        previous = end
    require(previous == len(ids) and labels == expected, 'User, header or history supervision leak')
    require(sum(x != -100 for x in labels) == row['effective_tokens'] > 0, 'Invalid effective token count')


class ProbeDataset:
    """Index verified train-only dialogue windows without loading all token arrays."""

    def __init__(self, directory, audit_path, tokenizer_dir, count, length, arm, seed,
                 delayed_start_index=False):
        self.directory, self.arm, self.cache = Path(directory), arm, None
        manifest_path = self.directory / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        audit = json.loads(Path(audit_path).read_text())
        require(not delayed_start_index or manifest['identity']['config']['generation'].get(
                'response_start_timing') == 'next_no_voice', 'Machine-only index requires delayed-start data')
        require(manifest['complete'] and audit['machine_passed'] and
                (audit['parent_issue_complete'] or delayed_start_index),
                'A completed and accepted machine audit is required')
        require(audit['manifest_sha256'] == sha256_file(manifest_path), 'Audit manifest mismatch')
        require(count in (32, 100, 1000), 'Only registered probes or full train indexing are allowed')
        require(64 <= length <= manifest['identity']['max_length'], 'Invalid probe window length')
        tokenizer = ReleasedTokenizer(tokenizer_dir, manifest['identity']['config']['token_ids'])
        require(tokenizer.fingerprint == manifest['identity']['tokenizer'], 'Tokenizer identity mismatch')
        selected_path = self.directory / 'dialogues.json'
        require(sha256_file(selected_path) == manifest['selected_sha256'], 'Split digest mismatch')
        selected = json.loads(selected_path.read_text())
        train = [d for d in selected if d['split'] == 'train']
        subset = ([d['dialogue_id'] for d in train] if count == 1000 else
                  json.loads((self.directory / 'smoke_subsets.json').read_text())[str(count)])
        require(len(subset) == count, 'Requested dialogue count unavailable')
        require(subset == [d['dialogue_id'] for d in train[:count]], 'Smoke subset identity mismatch')
        assignments_path = self.directory / 'view_assignments.json'
        require(sha256_file(assignments_path) == manifest['assignments_sha256'], 'View digest mismatch')
        assignments = json.loads(assignments_path.read_text())
        config = manifest['identity']['config']
        self.encoder = SequenceEncoder(tokenizer, config, length)
        original_encoder = SequenceEncoder(tokenizer, config, manifest['identity']['max_length'])
        self.files, self.order = {}, []
        self.statistics = Counter()
        for item in train[:count]:
            identity = item['dialogue_id']
            relative = 'dialogues/' + digest(identity) + '.json'
            path = self.directory / relative
            expected = manifest['artifacts'][relative]
            require(sha256_file(path) == expected, 'Dialogue artifact digest mismatch')
            artifact = json.loads(path.read_text())
            require(artifact['dialogue_id'] == identity and artifact['split'] == 'train', 'Non-train artifact')
            view = {'T1': 'original', 'T2': 'unpunctuated', 'T3': assignments[identity]}[arm]
            original = [r for r in artifact['sequences'] if r['arm'] == arm]
            require(original == list(original_encoder.encode(artifact['plan'], 'train', arm, view)),
                    'Original audited sequence differs from the event plan')
            self.files[identity] = (path, expected, view)
            self.statistics['view_' + view] += 1
            for index, row in enumerate(self.encoder.encode(artifact['plan'], 'train', arm, view)):
                validate_sequence(row)
                self.order.append((identity, index))
                self.statistics['sequences'] += 1
                self.statistics['input_tokens'] += len(row['input_ids'])
                self.statistics['effective_tokens'] += row['effective_tokens']
                self.statistics['max_length'] = max(self.statistics['max_length'], len(row['input_ids']))
        random.Random(seed).shuffle(self.order)
        self.identity = {'manifest_sha256': sha256_file(manifest_path), 'audit_sha256': sha256_file(audit_path),
                         'subset': subset, 'length': length, 'arm': arm,
                         'order_sha256': digest(self.order), 'statistics': dict(self.statistics)}

    def rows(self, cursor, count):
        require(0 <= cursor < len(self.order) and cursor + count <= len(self.order),
                'Probe exhausted its single-epoch sequence budget')
        rows = []
        for identity, index in self.order[cursor:cursor + count]:
            if self.cache is None or self.cache[0] != identity:
                path, expected, view = self.files[identity]
                require(sha256_file(path) == expected, 'Dialogue changed after indexing')
                artifact = json.loads(path.read_text())
                self.cache = (identity, list(self.encoder.encode(artifact['plan'], 'train', self.arm, view)))
            row = self.cache[1][index]
            validate_sequence(row)
            rows.append(row)
        return rows


def collate(rows, pad_id, device):
    import torch
    width = max(len(row['input_ids']) for row in rows)
    return {key: torch.tensor([row[key] + [fill] * (width - len(row[key])) for row in rows],
                              dtype=torch.long, device=device)
            for key, fill in (('input_ids', pad_id), ('labels', -100), ('attention_mask', 0))}


def rng_state():
    import numpy as np
    import torch
    return {'python': random.getstate(), 'numpy': np.random.get_state(),
            'torch': torch.get_rng_state(), 'cuda': torch.cuda.get_rng_state_all()}


def restore_rng(state):
    import numpy as np
    import torch
    random.setstate(state['python'])
    np.random.set_state(state['numpy'])
    torch.set_rng_state(state['torch'])
    torch.cuda.set_rng_state_all(state['cuda'])


def tree_digest(value):
    """Hash typed nested optimizer/RNG state, including every tensor byte."""
    import numpy as np
    import torch
    checksum = hashlib.sha256()

    def visit(item):
        if isinstance(item, torch.Tensor):
            checksum.update(str((str(item.dtype), tuple(item.shape))).encode())
            checksum.update(item.detach().cpu().contiguous().reshape(-1).view(torch.uint8).numpy().tobytes())
        elif isinstance(item, np.ndarray):
            checksum.update(str((str(item.dtype), item.shape)).encode())
            checksum.update(item.tobytes())
        elif isinstance(item, dict):
            for key in sorted(item, key=repr):
                visit(key)
                visit(item[key])
        elif isinstance(item, (tuple, list)):
            checksum.update(type(item).__name__.encode())
            for child in item:
                visit(child)
        else:
            checksum.update((type(item).__name__ + ':' + repr(item)).encode())
    visit(value)
    return checksum.hexdigest()


def check_disk(directory, config):
    used = sum(p.stat().st_size for p in Path(directory).rglob('*') if p.is_file())
    require(used < config['max_output_gib'] * 1024**3, 'Run output budget exceeded')
    require(shutil.disk_usage(directory).free >= config['min_free_gib'] * 1024**3,
            'Insufficient free disk reserve')


def save_checkpoint(path, wrapper, optimizer, scheduler, identity, step, cursor):
    import torch
    started = time.monotonic()
    require(all(p.grad is None for p in wrapper.parameters()), 'Save only at optimizer boundaries')
    payload = {'identity': identity, 'step': step, 'cursor': cursor,
               'lora': {n: p.detach().cpu().clone() for n, p in wrapper.named_parameters() if p.requires_grad},
               'optimizer': optimizer.state_dict(), 'scheduler': scheduler.state_dict(), 'rng': rng_state()}
    temporary = path.with_suffix('.partial')
    torch.save(payload, temporary)
    os.replace(temporary, path)
    return {'seconds': time.monotonic() - started, 'bytes': path.stat().st_size,
            'sha256': sha256_file(path),
            'state_digests': {k: tree_digest(payload[k]) for k in ('lora', 'optimizer', 'scheduler', 'rng')},
            'step': step, 'cursor': cursor}


def restore_checkpoint(path, wrapper, optimizer, scheduler, identity):
    import torch
    state = torch.load(path, map_location='cpu', weights_only=False)
    require(state['identity'] == identity, 'Resume identity mismatch')
    parameters = {n: p for n, p in wrapper.named_parameters() if p.requires_grad}
    require(set(state['lora']) == set(parameters), 'Resume trainable whitelist mismatch')
    with torch.no_grad():
        for name, value in state['lora'].items():
            require(value.shape == parameters[name].shape and value.dtype == parameters[name].dtype,
                    'Resume tensor shape/dtype mismatch')
            parameters[name].copy_(value)
    optimizer.load_state_dict(state['optimizer'])
    scheduler.load_state_dict(state['scheduler'])
    restore_rng(state['rng'])
    return state['step'], state['cursor']


def protocol_probe(loaded, row):
    """Validate actual generated IDs using the existing five-control protocol."""
    import torch
    first = next(s for s in row['spans'] if s['supervised'])
    prompt = row['input_ids'][:first['target_start']]
    loaded.model.eval()
    with torch.no_grad():
        generated = loaded.model.generate(
            input_ids=torch.tensor([prompt], device='cuda'),
            attention_mask=torch.ones((1, len(prompt)), dtype=torch.long, device='cuda'),
            do_sample=False, max_new_tokens=64, eos_token_id=loaded.token_ids['<|im_end|>'],
            pad_token_id=loaded.token_ids['<|im_end|>'], use_cache=True)[0, len(prompt):].tolist()
    controls = set(loaded.token_ids.values()) - {loaded.token_ids['<|no voice|>'], loaded.token_ids['<|im_end|>']}
    forbidden = {loaded.token_ids['<|no voice|>'], loaded.tokenizer.convert_tokens_to_ids('<|im_start|>')}
    positions = [i for i, token in enumerate(generated) if token in controls]
    require(not positions or positions == [0], 'Generated misplaced or repeated control token')
    require(not (set(generated) & forbidden), 'Generated user/header token')
    require(generated and generated[-1] == loaded.token_ids['<|im_end|>'], 'Generated unterminated fragment')
    silent = {loaded.token_ids[t] for t in ('<|user is talking|>', '<|user is thinking|>', '<|user interruption|>')}
    require(generated[0] not in silent or len(generated) == 2, 'Silent control emitted content')
    return {'prompt_ids': prompt, 'generated_ids': generated,
            'text': loaded.tokenizer.decode(generated, skip_special_tokens=False), 'passed': True}


def train(args):
    config = yaml.safe_load(args.config.read_text())
    delayed = config['purpose'] == 'issue040_delayed_start'
    alignment = config['purpose'] in ('issue036_alignment', 'issue040_delayed_start')
    alignment_probe = getattr(args, 'alignment_probe', False)
    require(not alignment_probe or (alignment and not delayed), 'Probe flag is exclusive to alignment configuration')
    formal = config['purpose'] == 'issue006_round1' or (alignment and not alignment_probe)
    protocol = None
    if alignment:
        from prepare_layer1_adaptation import validate_alignment_config, validate_delayed_config
        alignment_protocol = yaml.safe_load(args.protocol.read_text())
        root = Path(__file__).resolve().parents[2]
        if delayed:
            protocol = validate_delayed_config(config, alignment_protocol, root, args.arm,
                        args.dialogues, args.length, args.steps)
        else:
            protocol = validate_alignment_config(config, alignment_protocol, root, args.arm,
                        args.dialogues, args.length, args.steps, alignment_probe)
        require(sha256_file(args.config) == alignment_protocol['training_config_sha256'],
                'Alignment training config digest mismatch')
        require(sha256_file(args.inventory) == sha256_file(root / protocol['assets']['verified_inventory']),
                'Official inventory differs from preregistered initialization')
        config['arm'] = args.arm
    elif formal:
        from prepare_layer1_adaptation import validate_formal_config
        protocol = yaml.safe_load(args.protocol.read_text())
        validate_formal_config(config, protocol, Path(__file__).resolve().parents[2], args.arm,
                               args.dialogues, args.length, args.steps)
        root = Path(__file__).resolve().parents[2]
        require(sha256_file(args.inventory) == sha256_file(root / protocol['assets']['verified_inventory']),
                'Official inventory differs from preregistered initialization')
        config['arm'] = args.arm
    else:
        require(config['purpose'] == 'issue005_probe_only' and config['schema_version'] == 1,
                'Unknown training purpose')
        require(args.dialogues in (32, 100) and args.arm is None, 'Probe-only dialogue/arm scope')
    import numpy as np
    import torch
    require(config['batch_size'] == 1 and config['gradient_accumulation'] > 0, 'Invalid probe batch')
    require(0 < args.steps <= config['scheduler_steps'], 'Invalid step limit')
    require(torch.cuda.is_available() and torch.cuda.device_count() == 1, 'One allocated CUDA device required')
    args.output.mkdir(parents=True, exist_ok=False)
    args.output_created = True
    check_disk(args.output, config)
    started = time.monotonic()
    os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
    torch.use_deterministic_algorithms(config['deterministic'])
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    random.seed(config['seed'])
    np.random.seed(config['seed'])
    torch.manual_seed(config['seed'])
    torch.cuda.manual_seed_all(config['seed'])
    assets = verify_asset_inventory(args.inventory, args.checkpoint, args.base_model, args.official_source)
    dataset = ProbeDataset(args.dataset, args.audit, args.checkpoint / 'tokenizer', args.dialogues,
                           args.length, config['arm'], config['seed'], delayed_start_index=delayed)
    if formal or alignment:
        from prepare_layer1_adaptation import validate_index
        root = Path(__file__).resolve().parents[2]
        index_path = root / protocol['training']['full_train_index']
        full_index = json.loads(index_path.read_text())
        validate_index(full_index, protocol)
        require(dataset.identity == full_index[args.arm], 'Actual dataset differs from frozen full index')
        require(config['scheduler_steps'] == (len(dataset.order) + config['gradient_accumulation'] - 1) //
                config['gradient_accumulation'], 'Single-epoch step count mismatch')
    source_files = [Path(__file__), Path(__file__).with_name('layer1_data.py'),
                    Path(__file__).with_name('layer1_model.py'), Path(__file__).with_name('number_surface.py')]
    if alignment:
        source_files.extend(Path(__file__).with_name(name) for name in
                            ('layer1_loss.py', 'prepare_layer1_adaptation.py', 'layer1_candidate.py'))
    identity = {'config': config, 'data': dataset.identity, 'assets': assets,
                'code': {p.name: sha256_file(p) for p in source_files}}
    if formal or alignment:
        identity['release'] = {'protocol': sha256_file(args.protocol), 'index': sha256_file(index_path),
                               'config': sha256_file(args.config),
                               'validator': sha256_file(Path(__file__).with_name('prepare_layer1_adaptation.py')),
                               'post_training_evaluation': protocol['post_training_evaluation']}
    if alignment:
        identity['alignment_probe'] = alignment_probe
    write_json(args.output / 'manifest.json', {'identity': identity, 'purpose': config['purpose'],
               'formal_training_released': formal, 'source_commit': subprocess.check_output(
                   ['git', 'rev-parse', 'HEAD'], text=True).strip(), 'arguments': vars_for_json(args),
               'device': torch.cuda.get_device_name(), 'torch': torch.__version__})
    loaded = load_official_checkpoint(args.checkpoint, args.base_model, training=True)
    if alignment:
        require(loaded.trainable_audit['tensors'] == 112 and
                loaded.trainable_audit['frozen_embedding_and_head'], 'Alignment trainable whitelist changed')
    write_json(args.output / 'loading.json', {'info': loaded.info, 'load': loaded.load_audit,
                                            'trainable': loaded.trainable_audit})
    before = state_fingerprints(loaded.wrapper)
    write_json(args.output / 'weights_before.json', before)
    loaded.model.config.use_cache = False
    if config['gradient_checkpointing']:
        loaded.model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        loaded.model.enable_input_require_grads()
    parameters = [p for p in loaded.wrapper.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=config['learning_rate'], betas=tuple(config['adam_betas']),
                                 eps=config['adam_eps'], weight_decay=config['weight_decay'], foreach=False)

    def schedule(step):
        if step < config['warmup_steps']:
            return (step + 1) / config['warmup_steps']
        return max(0.0, (config['scheduler_steps'] - step) /
                   max(1, config['scheduler_steps'] - config['warmup_steps']))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, schedule)
    step, cursor = (0, 0)
    if args.resume:
        step, cursor = restore_checkpoint(args.resume, loaded.wrapper, optimizer, scheduler, identity)
        require(0 < step < args.steps, 'Resume must add at least one optimizer step')
        require(cursor == step * config['gradient_accumulation'] * config['batch_size'], 'Resume cursor mismatch')
    initial_step = step
    start_cursor = cursor
    optimizer.zero_grad(set_to_none=True)
    torch.cuda.reset_peak_memory_stats()
    metrics, exposed = [], set()
    loop_started = time.monotonic()
    while step < args.steps:
        if formal or alignment:
            wall_limit = 900 if alignment_probe else config['max_wall_seconds']
            require(time.monotonic() - started < wall_limit, 'Training wall-time budget exhausted')
        check_disk(args.output, config)
        torch.cuda.synchronize()
        tick = time.monotonic()
        count = accumulation_count(len(dataset.order), cursor, config['gradient_accumulation'] *
                                   config['batch_size'], formal)
        rows = dataset.rows(cursor, count)
        wait = time.monotonic() - tick
        tokens = sum(row['effective_tokens'] for row in rows)
        weighted_loss = 0.0
        if alignment:
            from layer1_loss import CONTROL_TOKENS, target_statistics, weighted_causal_loss
            targets = target_statistics(rows, loaded.token_ids, config['loss']['control_weights'])
            require(targets['effective_tokens'] == tokens, 'Causal target count differs from audited data')
            ordinary_nll = 0.0
            control_nll = {name: 0.0 for name in CONTROL_TOKENS}
        for start in range(0, len(rows), config['batch_size']):
            batch_rows = rows[start:start + config['batch_size']]
            batch = collate(batch_rows, loaded.token_ids['<|im_end|>'], 'cuda')
            batch_tokens = sum(row['effective_tokens'] for row in batch_rows)
            if alignment:
                labels = batch.pop('labels')
                outputs = loaded.model(**batch, use_cache=False)
                numerator, diagnostics = weighted_causal_loss(outputs.logits, labels, loaded.token_ids,
                    config['loss']['control_weights'], config['loss']['chunk_size'])
                scaled = numerator / targets['target_weight_sum']
                require(bool(torch.isfinite(scaled)), 'Non-finite weighted training loss')
                scaled.backward()
                weighted_loss += float(scaled.detach())
                ordinary_nll += diagnostics['ordinary_nll_sum']
                for name in control_nll:
                    control_nll[name] += diagnostics['control_nll_sums'][name]
                del outputs, numerator, labels, diagnostics, scaled, batch
            else:
                loss = loaded.model(**batch, use_cache=False).loss
                require(bool(torch.isfinite(loss)), 'Non-finite training loss')
                scaled = loss * (batch_tokens / tokens)
                scaled.backward()
                weighted_loss += float(loss.detach()) * batch_tokens / tokens
                del loss, scaled, batch
        grad_norm = torch.nn.utils.clip_grad_norm_(parameters, config['max_grad_norm'], error_if_nonfinite=True)
        require(float(grad_norm) > 0, 'Zero gradient norm')
        learning_rate = optimizer.param_groups[0]['lr']
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        torch.cuda.synchronize()
        step += 1
        cursor += len(rows)
        exposed.update(row['dialogue_id'] for row in rows)
        entry = {'step': step, 'cursor': cursor, 'loss': weighted_loss, 'grad_norm': float(grad_norm),
                 'learning_rate': learning_rate, 'seconds': time.monotonic() - tick, 'data_wait_seconds': wait,
                 'input_tokens': sum(len(row['input_ids']) for row in rows), 'effective_tokens': tokens,
                 'sequence_ids': [row['sequence_id'] for row in rows],
                 'lengths': [len(row['input_ids']) for row in rows]}
        if alignment:
            entry.update(ordinary_ce=ordinary_nll / tokens, weighted_objective=weighted_loss,
                         target_weight_sum=targets['target_weight_sum'],
                         control_targets={name: {'count': targets['control_counts'][name],
                             'mean_nll': control_nll[name] / targets['control_counts'][name]
                             if targets['control_counts'][name] else None} for name in control_nll})
        free_memory, total_memory = torch.cuda.mem_get_info()
        entry['memory'] = {'allocated_bytes': torch.cuda.memory_allocated(),
                           'reserved_bytes': torch.cuda.memory_reserved(),
                           'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
                           'peak_reserved_bytes': torch.cuda.max_memory_reserved(),
                           'device_free_bytes': free_memory, 'device_total_bytes': total_memory,
                           'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        metrics.append(entry)
        with (args.output / 'steps.jsonl').open('a') as stream:
            stream.write(json.dumps(entry) + '\n')
        print(json.dumps(entry), flush=True)
        if formal and step % config['save_every_steps'] == 0 and step < args.steps:
            saved = save_checkpoint(args.output / f'checkpoint-step-{step:06d}.pt', loaded.wrapper,
                                    optimizer, scheduler, identity, step, cursor)
            write_json(args.output / f'checkpoint-step-{step:06d}.json', saved)
            check_disk(args.output, config)
    loop_seconds = time.monotonic() - loop_started
    checkpoint = save_checkpoint(args.output / 'checkpoint.pt', loaded.wrapper, optimizer, scheduler,
                                 identity, step, cursor)
    after = state_fingerprints(loaded.wrapper)
    changed = [n for n in before if before[n] != after[n]]
    require(changed and all(LORA_NAME.fullmatch(n) for n in changed), 'Frozen parameter changed or no update')
    write_json(args.output / 'weights_after.json', after)
    generation = protocol_probe(loaded, dataset.rows(0, 1)[0])
    report = {'passed': True, 'initial_step': initial_step, 'final_step': step, 'start_cursor': start_cursor,
              'cursor': cursor, 'pool_dialogues': args.dialogues, 'exposed_dialogues': len(exposed),
              'exposed_sequences': cursor - start_cursor, 'changed_tensors': changed,
              'frozen_tensors_unchanged': True, 'checkpoint': checkpoint, 'protocol_probe': generation,
              'loop_seconds': loop_seconds, 'total_seconds': time.monotonic() - started,
              'input_tokens_per_second': sum(m['input_tokens'] for m in metrics) / loop_seconds,
              'effective_tokens_per_second': sum(m['effective_tokens'] for m in metrics) / loop_seconds,
              'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
              'peak_reserved_bytes': torch.cuda.max_memory_reserved(),
              'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              'data_statistics': dict(dataset.statistics), 'formal_training_released': formal}
    write_json(args.output / 'summary.json', report)
    return report


def accumulation_count(total, cursor, batch, partial):
    """Consume the final partial batch once without repeating or dropping targets."""
    remaining = total - cursor
    require(batch > 0 and remaining > 0, 'Single-epoch sequence budget exhausted')
    require(partial or remaining >= batch, 'Probe exhausted its single-epoch sequence budget')
    return min(batch, remaining)


def vars_for_json(args):
    return {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}


def record_failure(args, error):
    """Write failure evidence only inside the directory owned by this invocation."""
    if args.command == 'train' and getattr(args, 'output_created', False):
        write_json(args.output / 'failure.json', {'passed': False, 'error': f'{type(error).__name__}: {error}'})


def compare(args):
    left = json.loads((args.continuous / 'summary.json').read_text())
    right = json.loads((args.resumed / 'summary.json').read_text())
    require(left['passed'] and right['passed'], 'Both training runs must pass')
    keys = ('lora', 'optimizer', 'scheduler', 'rng')
    matches = {key: left['checkpoint']['state_digests'][key] == right['checkpoint']['state_digests'][key]
               for key in keys}
    matches['step_cursor'] = (left['final_step'], left['cursor']) == (right['final_step'], right['cursor'])
    read_steps = lambda path: [json.loads(line) for line in (path / 'steps.jsonl').read_text().splitlines()]
    baseline = {r['step']: r for r in read_steps(args.continuous)}
    fields = ('loss', 'grad_norm', 'learning_rate', 'cursor', 'sequence_ids', 'effective_tokens')
    if any('weighted_objective' in row for row in baseline.values()):
        fields += ('ordinary_ce', 'weighted_objective', 'target_weight_sum', 'control_targets')
    matches['continuation'] = all(all(baseline[r['step']][k] == r[k] for k in fields)
                                  for r in read_steps(args.resumed))
    matches['protocol'] = left['protocol_probe'] == right['protocol_probe']
    report = {'passed': all(matches.values()), 'exact_comparisons': matches,
              'continuous': str(args.continuous), 'resumed': str(args.resumed),
              'tolerance': 'bitwise state and exact subsequent loss; no relaxed tolerance'}
    write_json(args.output, report)
    require(report['passed'], 'Training recovery differs from uninterrupted run')
    return report


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest='command', required=True)
    run = sub.add_parser('train')
    for name in ('checkpoint', 'base-model', 'official-source', 'inventory', 'dataset', 'audit', 'output'):
        run.add_argument('--' + name, type=Path, required=True)
    run.add_argument('--config', type=Path, default=Path('configs/layer1_training.yaml'))
    run.add_argument('--dialogues', type=int, choices=(32, 100, 1000), required=True)
    run.add_argument('--arm', choices=('T1', 'T2', 'T3'))
    run.add_argument('--protocol', type=Path, default=Path('configs/layer1_adaptation_protocol.yaml'))
    run.add_argument('--length', type=int, required=True)
    run.add_argument('--steps', type=int, required=True)
    run.add_argument('--resume', type=Path)
    run.add_argument('--alignment-probe', action='store_true',
                     help='Run at most 100 alignment steps; output cannot be served as a final candidate')
    comp = sub.add_parser('compare')
    for name in ('continuous', 'resumed', 'output'):
        comp.add_argument('--' + name, type=Path, required=True)
    index = sub.add_parser('index')
    for name in ('dataset', 'audit', 'tokenizer', 'output'):
        index.add_argument('--' + name, type=Path, required=True)
    index.add_argument('--length', type=int, required=True)
    index.add_argument('--delayed-start-index', action='store_true',
                       help='Index machine-audited delayed data without claiming human review')
    return result


if __name__ == '__main__':
    arguments = parser().parse_args()
    try:
        if arguments.command == 'index':
            report = {arm: ProbeDataset(arguments.dataset, arguments.audit, arguments.tokenizer,
                      1000, arguments.length, arm, 20261020,
                      delayed_start_index=arguments.delayed_start_index).identity for arm in ('T1', 'T2', 'T3')}
            write_json(arguments.output, report)
        else:
            report = train(arguments) if arguments.command == 'train' else compare(arguments)
        print(json.dumps(report), flush=True)
    except Exception as error:
        record_failure(arguments, error)
        raise
