"""Diagnose TextTurn checkpoints and run bounded, isolated optimization controls."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gc
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import time

TRAINING = Path(__file__).resolve().parents[1] / 'training'
sys.path.insert(0, str(TRAINING))
from build_textturn_dataset import ACTIONS
from textturn_loss import complete_trajectory_groups, stage_loss_weights, trajectory_order
from score_textturn import score_predictions
from train_textturn import (action_logits, check_budget, file_hash, load_controller, read_rows,
                            save_adapter, split_path, write_json)


def stable_key(seed, value):
    return hashlib.sha256(f'{seed}|diagnostic|{value}'.encode()).hexdigest()


def select_probe(rows, seed, source_count=None, keep_per_bucket=2):
    sources = sorted({r['source_id'] for r in rows}, key=lambda s: stable_key(seed, s))
    sources = set(sources if source_count is None else sources[:source_count])
    selected = set()
    buckets = defaultdict(list)
    groups = defaultdict(list)
    for row in rows:
        if row['source_id'] in sources:
            groups[row['scenario_id']].append(row)
    for windows in groups.values():
        for i, row in enumerate(windows):
            if row['target_action'] != 'keep':
                selected.update(r['snapshot_id'] for r in windows[max(0, i-2):i+3])
            else:
                buckets[(row['scenario_id'], row['visible']['state'], row['category'])].append(row)
    for bucket in buckets.values():
        selected.update(r['snapshot_id'] for r in sorted(
            bucket, key=lambda r: stable_key(seed, r['snapshot_id']))[:keep_per_bucket])
    return [r for r in rows if r['snapshot_id'] in selected]


def action_loss(logits, row, token_ids, objective):
    import torch
    action = row['target_action']
    legal = ('keep', 'start') if row['visible']['state'] == 'Listen' else ('keep', 'stop')
    if action not in legal:
        raise ValueError('Illegal supervised action')
    if objective == 'full':
        scores, target = logits, token_ids[list(ACTIONS).index(action)]
    elif objective == 'legal':
        scores = logits[[token_ids[list(ACTIONS).index(a)] for a in legal]]
        target = legal.index(action)
    else:
        raise ValueError('Unknown diagnostic objective')
    return torch.nn.functional.cross_entropy(scores[None, :], torch.tensor([target], device=logits.device))


def evaluate_rows(model, rows, token_ids, output, started, config, complete=False):
    import torch
    output.mkdir(parents=True, exist_ok=False)
    model.eval()
    confusion, totals = Counter(), defaultdict(lambda: defaultdict(float))
    predictions = []
    with torch.inference_mode(), (output / 'predictions.jsonl').open('w') as stream:
        for i, row in enumerate(rows):
            torch.cuda.synchronize()
            begin = time.monotonic()
            scores = action_logits(model, row['input_ids'][:-1])
            actions = scores[token_ids[:3]]
            legal = [0, 1] if row['visible']['state'] == 'Listen' else [0, 2]
            prediction = legal[int(actions[legal].argmax())]
            elapsed = (time.monotonic()-begin)*1000
            target = list(ACTIONS).index(row['target_action'])
            other = next(a for a in legal if a != target)
            full = float(action_loss(scores, row, token_ids, 'full'))
            restricted = float(action_loss(scores, row, token_ids, 'legal'))
            margin = float(actions[target] - actions[other])
            key = row['target_action']
            stats = totals[key]
            stats['count'] += 1
            stats['correct'] += prediction == target
            stats['full_ce_sum'] += full
            stats['legal_ce_sum'] += restricted
            stats['margin_sum'] += margin
            confusion[(key, list(ACTIONS)[prediction])] += 1
            record = dict(snapshot_id=row['snapshot_id'], target=key, control_ms=elapsed,
                action=list(ACTIONS)[prediction], state=row['visible']['state'],
                action_logits=actions.tolist(), correct_margin=margin,
                full_ce=full, legal_ce=restricted)
            stream.write(json.dumps(record) + '\n')
            if complete:
                predictions.append(record)
            if (i+1) % 500 == 0:
                check_budget(started, config, output)
                print(json.dumps(dict(event='diagnostic_evaluation', output=str(output), completed=i+1,
                                      planned=len(rows))), flush=True)
    result = dict(rows=len(rows), sources=len({r['source_id'] for r in rows}),
                  confusion={f'{a}->{b}': n for (a, b), n in confusion.items()}, by_action={})
    for action, values in totals.items():
        n = int(values['count'])
        result['by_action'][action] = dict(count=n, correct=int(values['correct']),
            accuracy=values['correct']/n, mean_full_ce=values['full_ce_sum']/n,
            mean_legal_ce=values['legal_ce_sum']/n, mean_correct_margin=values['margin_sum']/n)
    if complete:
        result['opportunities'], _ = score_predictions(rows, predictions)
    write_json(output / 'summary.json', result)
    return result


def gradient_norm(model, max_norm=None):
    import torch
    parameters = [p for p in model.parameters() if p.requires_grad and p.grad is not None]
    norm = torch.nn.utils.clip_grad_norm_(parameters, math.inf if max_norm is None else max_norm,
                                         error_if_nonfinite=True)
    return float(norm)


def token_gradient_norms(model):
    return {name: p.grad.detach().float().norm(dim=-1).tolist()
            for name, p in model.named_parameters() if 'trainable_tokens' in name and p.grad is not None}


def audit_gradients(model, rows, token_ids, output, started, config):
    model.train()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    order = trajectory_order(rows, config['seed'])
    weights, _ = stage_loss_weights(rows, config['loss_balance'])
    weights = dict(zip((r['snapshot_id'] for r in rows), weights))
    counts, records = Counter(), []
    for begin in range(0, len(order), config['gradient_accumulation']):
        group = order[begin:begin+config['gradient_accumulation']]
        category = 'stop' if any(r['target_action'] == 'stop' for r in group) else (
            'start' if any(r['target_action'] == 'start' for r in group) else 'keep')
        if counts[category] >= (4 if category == 'keep' else 2):
            continue
        counts[category] += 1
        model.zero_grad(set_to_none=True)
        for row in group:
            scores = action_logits(model, row['input_ids'][:-1])
            (action_loss(scores, row, token_ids, 'full')*weights[row['snapshot_id']]/len(group)).backward()
        norm = gradient_norm(model)
        records.append(dict(group_start=begin, category=category,
            actions=dict(Counter(r['target_action'] for r in group)), norm_before_clip=norm,
            hypothetical_clip1_scale=min(1., 1./(norm+1e-6)), token_row_gradient_norms=token_gradient_norms(model)))
        check_budget(started, config, output.parent)
        if counts['keep'] == 4 and counts['start'] == 2 and counts['stop'] == 2:
            break
    model.zero_grad(set_to_none=True)
    write_json(output, records)
    return records


def compare_arm(model, tokenizer, pilot, probes, token_ids, arm, output, started, config):
    import torch
    from transformers import get_cosine_schedule_with_warmup
    output.mkdir(parents=True, exist_ok=False)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                                 lr=config['learning_rate'], weight_decay=.01)
    accumulation = config['gradient_accumulation']
    steps = math.ceil(len(pilot)/accumulation)*config['epochs']
    scheduler = get_cosine_schedule_with_warmup(optimizer, math.ceil(steps*config['warmup_fraction']), steps)
    weights, summary = stage_loss_weights(pilot, config['loss_balance'])
    weights = dict(zip((r['snapshot_id'] for r in pilot), weights))
    write_json(output / 'loss_weights.json', summary)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    history = []
    with (output / 'updates.jsonl').open('w') as updates:
        for epoch in range(config['epochs']):
            model.train()
            optimizer.zero_grad(set_to_none=True)
            order = trajectory_order(pilot, config['seed']+epoch)
            class_losses, group_actions = defaultdict(list), Counter()
            for i, row in enumerate(order):
                check_budget(started, config, output)
                scores = action_logits(model, row['input_ids'][:-1])
                loss = action_loss(scores, row, token_ids, arm['objective'])
                class_losses[row['target_action']].append(float(loss.detach()))
                begin = i//accumulation*accumulation
                divisor = min(accumulation, len(order)-begin)
                (loss*weights[row['snapshot_id']]/divisor).backward()
                group_actions[row['target_action']] += 1
                if (i+1) % accumulation == 0 or i+1 == len(order):
                    token_norms = token_gradient_norms(model)
                    norm = gradient_norm(model, arm['max_grad_norm'])
                    updates.write(json.dumps(dict(epoch=epoch+1, completed=i+1, actions=dict(group_actions),
                        norm_before_clip=norm, clip_scale=1. if arm['max_grad_norm'] is None else min(
                            1., arm['max_grad_norm']/(norm+1e-6)), token_row_gradient_norms=token_norms,
                        learning_rate=optimizer.param_groups[0]['lr'])) + '\n')
                    optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad(set_to_none=True)
                    group_actions.clear()
                if (i+1) % 256 == 0:
                    updates.flush()
                    print(json.dumps(dict(event='diagnostic_training', arm=arm['name'], epoch=epoch+1,
                        completed=i+1, planned=len(order))), flush=True)
            record = dict(epoch=epoch+1, mean_train_loss={a: sum(v)/len(v) for a, v in class_losses.items()})
            for name, rows in probes.items():
                record[name] = evaluate_rows(model, rows, token_ids, output/f'epoch-{epoch+1}-{name}', started, config)
            history.append(record)
            write_json(output / 'history.json', history)
            print(json.dumps(dict(event='diagnostic_epoch_complete', arm=arm['name'], **record)), flush=True)
    save_adapter(model, tokenizer, output/'final')
    return history


def release_model():
    import torch
    gc.collect()
    torch.cuda.empty_cache()


def main(args):
    import torch
    started = time.monotonic()
    diagnostic = json.loads(args.config.read_text())
    config = json.loads((TRAINING.parents[1]/'configs/textturn_full_trajectory_training.json').read_text())
    config['max_wall_seconds'] = diagnostic['max_wall_seconds']
    if args.output.exists():
        raise ValueError('Use a new diagnostic output directory')
    manifest = json.loads((args.data/'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        if file_hash(args.data/name) != expected:
            raise ValueError(f'Frozen dataset changed: {name}')
    pilot = read_rows(split_path(args.data, manifest, 'pilot'))
    complete_trajectory_groups(pilot)
    if len(pilot) > config['pilot_snapshots']:
        raise ValueError('Diagnostic pilot exceeds the existing budget')
    dev = read_rows(split_path(args.data, manifest, 'dev'))
    dev_probe = select_probe(dev, diagnostic['seed'], diagnostic['dev_sources'], diagnostic['keep_per_bucket'])
    confirmation = []
    if args.phase == 'confirm':
        if args.candidate is None:
            raise ValueError('Confirm requires an explicitly fixed candidate')
        sources = sorted({r['source_id'] for r in dev}, key=lambda s: stable_key(diagnostic['seed'], s))
        sources = set(sources[diagnostic['dev_sources']:diagnostic['dev_sources']+diagnostic['confirmation_sources']])
        confirmation = [r for r in dev if r['source_id'] in sources]
        complete_trajectory_groups(confirmation)
    del dev
    pilot_probe = select_probe(pilot, diagnostic['seed'], keep_per_bucket=diagnostic['keep_per_bucket'])
    args.output.mkdir(parents=True)
    torch.set_num_threads(8)
    torch.backends.cuda.matmul.allow_tf32 = True
    write_json(args.output/'manifest.json', dict(phase=args.phase, diagnostic=diagnostic, training=config,
        dataset_manifest_sha256=file_hash(args.data/'manifest.json'), model_config_sha256=file_hash(args.model/'config.json'),
        packages={name: importlib.metadata.version(name) for name in ('torch', 'transformers', 'peft')},
        pilot_rows=len(pilot), pilot_probe_ids=[r['snapshot_id'] for r in pilot_probe],
        dev_probe_ids=[r['snapshot_id'] for r in dev_probe], dev_source_ids=sorted({r['source_id'] for r in dev_probe}),
        confirmation_source_ids=sorted({r['source_id'] for r in confirmation}),
        candidate_adapter_sha256=file_hash(args.candidate/'adapter_model.safetensors') if args.candidate else None,
        gpu=torch.cuda.get_device_name(0), started_unix=time.time()))
    result = {}
    if args.phase == 'inspect':
        for name in ('base', 'best', 'final'):
            prior = None if name == 'base' else args.prior/name
            model, _, ids = load_controller(args.model, args.data, config, prior, is_trainable=name=='final')
            result[name] = dict(pilot=evaluate_rows(model, pilot, ids, args.output/name/'pilot', started, config),
                dev_probe=evaluate_rows(model, dev_probe, ids, args.output/name/'dev-probe', started, config))
            if name == 'final':
                result[name]['gradients'] = audit_gradients(model, pilot, ids, args.output/'gradients.json', started, config)
            del model
            release_model()
    elif args.phase == 'compare':
        for arm in diagnostic['arms']:
            model, tokenizer, ids = load_controller(args.model, args.data, config)
            result[arm['name']] = compare_arm(model, tokenizer, pilot,
                dict(pilot_probe=pilot_probe, dev_probe=dev_probe), ids, arm, args.output/arm['name'], started, config)
            del model
            release_model()
    else:
        model, _, ids = load_controller(args.model, args.data, config, args.candidate)
        for name, rows in dict(pilot=pilot, dev_confirmation=confirmation).items():
            result[name] = evaluate_rows(model, rows, ids, args.output/name, started, config, complete=True)
        del model
        release_model()
    write_json(args.output/'summary.json', result)
    print(json.dumps(dict(event='diagnostic_finished', phase=args.phase, elapsed_seconds=time.monotonic()-started)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('inspect', 'compare', 'confirm'), required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('configs/textturn_training_diagnostics.json'))
    main(parser.parse_args())
