"""Train and select one bounded TextTurn LoRA candidate using development data only."""
from __future__ import annotations

import argparse
import gc
import gzip
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import random
import shutil
import time

from build_textturn_dataset import ACTIONS, SILENCE
from score_textturn import score_file
from textturn_loss import complete_trajectory_groups, stage_loss_weights, trajectory_order, weighted_action_loss
from textturn_gate import candidate_gate, development_gate, selection_key


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_rows(path):
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def split_path(data_path, manifest, split):
    return data_path / manifest.get('split_files', {}).get(split, f'{split}.jsonl')


def register_dataset_tokens(tokenizer, manifest):
    markers = sorted(manifest['new_token_ids'], key=manifest['new_token_ids'].get)
    expected = list(ACTIONS.values()) + [SILENCE]
    if markers not in (expected, expected + ['<finish>']):
        raise ValueError('Unsupported controller token registry')
    tokenizer.add_special_tokens({'additional_special_tokens': markers})
    actual = {marker: tokenizer.convert_tokens_to_ids(marker) for marker in markers}
    if actual != manifest['new_token_ids'] or any(
            tokenizer.encode(marker, add_special_tokens=False) != [actual[marker]] for marker in markers):
        raise ValueError('Training tokenizer differs from the frozen dataset')
    return list(actual.values())


def load_controller(model_path, data_path, config, adapter=None, is_trainable=False):
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    manifest = json.loads((data_path / 'manifest.json').read_text())
    token_ids = register_dataset_tokens(tokenizer, manifest)
    torch.manual_seed(config['seed'])
    base = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True,
                                               dtype=torch.bfloat16, attn_implementation='sdpa').to('cuda')
    if len(tokenizer) > base.config.vocab_size:
        base.resize_token_embeddings(len(tokenizer))
    with torch.no_grad():
        weights = base.get_input_embeddings().weight
        for token_id, word in zip(token_ids, ('keep', 'start', 'stop', 'silence', 'finish')):
            semantic = tokenizer.encode(word, add_special_tokens=False)
            weights[token_id] = weights[semantic].float().mean(dim=0).to(weights.dtype)
        base.tie_weights()
    base.config.use_cache = False
    if adapter is None:
        model = get_peft_model(base, LoraConfig(
            task_type='CAUSAL_LM', r=config['rank'], lora_alpha=config['alpha'],
            target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj'],
            trainable_token_indices={'embed_tokens': token_ids}, ensure_weight_tying=True,
            lora_dropout=0., bias='none'))
    else:
        model = PeftModel.from_pretrained(base, adapter, is_trainable=is_trainable)
    return model, tokenizer, token_ids


def action_logits(model, ids):
    import torch
    inputs = torch.tensor([ids], dtype=torch.long, device='cuda')
    return model(input_ids=inputs, use_cache=False, logits_to_keep=1).logits[0, -1].float()


def check_budget(started, config, root):
    import torch
    wall_limit = config['max_wall_seconds']
    if wall_limit is not None and time.monotonic() - started > wall_limit:
        raise RuntimeError('Per-job time budget exceeded')
    if torch.cuda.max_memory_reserved() > config['gpu_stop_gib'] * 1024**3:
        raise RuntimeError('GPU 22GiB stop line exceeded')
    if shutil.disk_usage(root).free < 10 * 1024**3:
        raise RuntimeError('Free disk stop line exceeded')


def evaluate(model, rows, token_ids, output, started, config):
    import torch
    output.mkdir(parents=True, exist_ok=True)
    model.eval()
    predictions = []
    with torch.inference_mode(), (output / 'predictions.jsonl').open('w') as stream:
        for position, row in enumerate(rows):
            prediction = {'snapshot_id': row['snapshot_id'], 'action': None, 'control_ms': None}
            if not row['excluded_reason']:
                torch.cuda.synchronize()
                begin = time.monotonic()
                try:
                    scores = action_logits(model, row['input_ids'][:-1])
                    legal = ('keep', 'start') if row['visible']['state'] == 'Listen' else ('keep', 'stop')
                    indices = [token_ids[list(ACTIONS).index(action)] for action in legal]
                    action = legal[int(scores[indices].argmax().item())]
                    torch.cuda.synchronize()
                    prediction.update(action=action, control_ms=(time.monotonic() - begin) * 1000)
                except Exception as exc:
                    prediction['error'] = repr(exc)
                    if isinstance(exc, torch.cuda.OutOfMemoryError):
                        raise
            predictions.append(prediction)
            stream.write(json.dumps(prediction) + '\n')
            if position % 500 == 0:
                stream.flush()
                check_budget(started, config, output)
                print(json.dumps({'event': 'evaluation_progress', 'output': str(output),
                                  'completed': position + 1, 'planned': len(rows)}), flush=True)
    return score_file(rows, predictions, output)


def save_adapter(model, tokenizer, output):
    output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output, safe_serialization=True, save_embedding_layers=False)
    tokenizer.save_pretrained(output)


def train_stage(model, tokenizer, rows, dev, token_ids, args, config, started, stage, best_score, baseline):
    import torch
    from transformers import get_cosine_schedule_with_warmup
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                                  lr=config['learning_rate'], weight_decay=.01)
    steps_per_epoch = math.ceil(len(rows) / config['gradient_accumulation'])
    total_steps = steps_per_epoch * config['epochs']
    scheduler = get_cosine_schedule_with_warmup(optimizer, math.ceil(total_steps * config['warmup_fraction']), total_steps)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    history = []
    weighted = config.get('loss_policy') is not None
    if weighted:
        complete_trajectory_groups(rows)
        effective_weights, weights = stage_loss_weights(rows, config.get('loss_balance'))
        weights_by_id = {row['snapshot_id']: weight for row, weight in zip(rows, effective_weights)}
        if len(weights_by_id) != len(rows):
            raise ValueError('Duplicate snapshot ID in weighted training stage')
        write_json(args.output / f'{stage}-loss_weights.json', weights)
    mean_weight = weights['mean_weight'] if weighted else 1.
    for epoch in range(config['epochs']):
        model.train()
        if weighted:
            order = trajectory_order(rows, config['seed'] + epoch)
        else:
            order = list(rows)
            random.Random(config['seed'] + epoch).shuffle(order)
        optimizer.zero_grad(set_to_none=True)
        loss_sum, last_report = 0., time.monotonic()
        for index, row in enumerate(order):
            check_budget(started, config, args.output)
            if [v for v in row['labels'] if v != -100] != [row['input_ids'][-1]]:
                raise ValueError('Only one final action token may be supervised')
            logits = action_logits(model, row['input_ids'][:-1])
            target = torch.tensor([row['input_ids'][-1]], device='cuda')
            loss = (weighted_action_loss(logits[None, :], target, [weights_by_id[row['snapshot_id']]], mean_weight)
                    if weighted else torch.nn.functional.cross_entropy(logits[None, :], target))
            loss_sum += float(loss.detach())
            group_start = index // config['gradient_accumulation'] * config['gradient_accumulation']
            divisor = min(config['gradient_accumulation'], len(order) - group_start)
            (loss / divisor).backward()
            if index == 0 and epoch == 0:
                token_gradients = [p.grad for name, p in model.named_parameters()
                                   if 'trainable_tokens' in name and p.requires_grad]
                if not token_gradients or not any(g is not None and torch.isfinite(g).all() and g.abs().sum() > 0
                                                  for g in token_gradients):
                    raise RuntimeError('New-token rows did not receive finite nonzero gradients')
            if (index + 1) % config['gradient_accumulation'] == 0 or index + 1 == len(order):
                torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
            if time.monotonic() - last_report > 30:
                print(json.dumps({'event': 'train_progress', 'stage': stage, 'epoch': epoch + 1,
                                  'completed': index + 1, 'planned': len(order),
                                  'mean_loss': loss_sum / (index + 1)}), flush=True)
                last_report = time.monotonic()
        result = evaluate(model, dev, token_ids, args.output / f'{stage}-dev-epoch-{epoch + 1}', started, config)
        record = {'stage': stage, 'epoch': epoch + 1, 'mean_train_loss': loss_sum / len(order), 'dev': result}
        record['development_gate'] = development_gate(baseline, result, config)
        history.append(record)
        write_json(args.output / f'{stage}-history.json', history)
        save_adapter(model, tokenizer, args.output / 'final')
        selection_path = args.output / 'best_selection.json'
        previous = json.loads(selection_path.read_text()) if selection_path.exists() else None
        if previous is None or selection_key(record, baseline, config) > selection_key(previous, baseline, config):
            best_score = result['opportunity_score']
            save_adapter(model, tokenizer, args.output / 'best')
            write_json(args.output / 'best_selection.json', record)
    del optimizer, scheduler
    gc.collect()
    torch.cuda.empty_cache()
    return history, best_score


def main(args):
    import torch
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('Use a fresh run directory')
    args.output.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.config.read_text())
    started = time.monotonic()
    manifest = json.loads((args.data / 'manifest.json').read_text())
    if not manifest['training_allowed'] or manifest['model_revision'] != config['model_revision']:
        raise ValueError('Dataset does not permit this training configuration')
    if manifest.get('complete_trajectories') and config.get('loss_policy') != manifest.get('loss_policy'):
        raise ValueError('Training loss policy differs from the complete-trajectory dataset')
    if config.get('loss_balance') is not None and not manifest.get('complete_trajectories'):
        raise ValueError('Stage action balancing requires complete weighted trajectories')
    for name, expected in manifest['files'].items():
        if file_hash(args.data / name) != expected:
            raise ValueError(f'Frozen dataset changed: {name}')
    write_json(args.output / 'run_manifest.json', {
        'config': config, 'dataset_manifest_sha256': file_hash(args.data / 'manifest.json'),
        'packages': {name: importlib.metadata.version(name) for name in ('torch', 'transformers', 'peft', 'tokenizers')},
        'gpu': torch.cuda.get_device_name(0), 'started_unix': time.time(),
        'model_config_sha256': file_hash(args.model / 'config.json'),
        'model_weights_sha256': file_hash(args.model / 'model.safetensors')})
    torch.set_num_threads(8)
    torch.backends.cuda.matmul.allow_tf32 = True
    model, tokenizer, token_ids = load_controller(args.model, args.data, config)
    trainable = {name: p.numel() for name, p in model.named_parameters() if p.requires_grad}
    if not any('trainable_tokens' in name for name in trainable):
        raise RuntimeError('New input/output token rows are not trainable')
    write_json(args.output / 'trainable_parameters.json', trainable)
    pilot = read_rows(split_path(args.data, manifest, 'pilot'))
    if manifest.get('complete_trajectories'):
        complete_trajectory_groups(pilot)
    probe = [next(r for r in pilot if r['target_action'] == action) for action in ACTIONS]
    model.eval()
    with torch.inference_mode():
        probe_losses = [float(torch.nn.functional.cross_entropy(
            action_logits(model, row['input_ids'][:-1])[None, :],
            torch.tensor([row['input_ids'][-1]], device='cuda'))) for row in probe]
    if not all(math.isfinite(loss) for loss in probe_losses):
        raise RuntimeError('Initial action loss is not finite')
    dev = read_rows(split_path(args.data, manifest, 'dev'))
    if manifest.get('complete_trajectories'):
        complete_trajectory_groups(dev)
    baseline = evaluate(model, dev, token_ids, args.output / 'baseline-dev', started, config)
    if len(pilot) > config['pilot_snapshots']:
        raise ValueError('Pilot snapshot budget exceeded')
    initial_rows = model.get_input_embeddings().weight[token_ids].detach().float().cpu().clone()
    history, best_score = train_stage(model, tokenizer, pilot, dev, token_ids, args, config, started,
                                     'pilot', -1., baseline)
    selected = json.loads((args.output / 'best_selection.json').read_text())
    candidate_dev = selected['dev']
    pilot_gate = development_gate(baseline, candidate_dev, config)
    gate = pilot_gate['passed']
    write_json(args.output / 'pilot_gate.json', {'continue_full': gate, 'baseline': baseline,
                                               'candidate': candidate_dev,
                                               'tolerance': config['false_action_regression_tolerance'],
                                               'gate': pilot_gate})
    stage = 'pilot'
    if gate:
        del model
        gc.collect()
        torch.cuda.empty_cache()
        model, tokenizer, token_ids = load_controller(args.model, args.data, config,
                                                       args.output / 'best', is_trainable=True)
        full = read_rows(split_path(args.data, manifest, 'train'))
        if manifest.get('complete_trajectories'):
            complete_trajectory_groups(full)
        if len(full) > config['full_snapshots']:
            raise ValueError('Full snapshot budget exceeded')
        _, best_score = train_stage(model, tokenizer, full, dev, token_ids, args, config, started,
                                    'full', best_score, baseline)
        stage = 'full'
    del model
    gc.collect()
    torch.cuda.empty_cache()
    best = args.output / 'best'
    model, tokenizer, token_ids = load_controller(args.model, args.data, config, best)
    model.eval()
    with torch.inference_mode():
        before = torch.stack([action_logits(model, row['input_ids'][:-1])[token_ids[:3]].cpu() for row in probe])
        saved_rows = model.get_input_embeddings().weight[token_ids].detach().float().cpu().clone()
    del model
    gc.collect()
    torch.cuda.empty_cache()
    reloaded, _, _ = load_controller(args.model, args.data, config, best)
    reloaded.eval()
    with torch.inference_mode():
        after = torch.stack([action_logits(reloaded, row['input_ids'][:-1])[token_ids[:3]].cpu() for row in probe])
        loaded_rows = reloaded.get_input_embeddings().weight[token_ids].detach().float().cpu()
        trained_probe_losses = [float(torch.nn.functional.cross_entropy(
            action_logits(reloaded, row['input_ids'][:-1])[None, :],
            torch.tensor([row['input_ids'][-1]], device='cuda'))) for row in probe]
    reload_ok = torch.equal(saved_rows, loaded_rows) and torch.equal(before, after)
    learned_rows = not torch.equal(initial_rows, saved_rows)
    write_json(args.output / 'reload_verification.json', {'identical_action_scores': torch.equal(before, after),
                'identical_new_token_rows': torch.equal(saved_rows, loaded_rows), 'new_rows_updated': learned_rows})
    write_json(args.output / 'learning_verification.json', {'probe_actions': list(ACTIONS),
                'initial_losses': probe_losses, 'trained_losses': trained_probe_losses,
                'mean_loss_improved': sum(trained_probe_losses) < sum(probe_losses)})
    if not reload_ok or not learned_rows:
        raise RuntimeError('Saved candidate failed new-token/reload verification')
    selection = json.loads((args.output / 'best_selection.json').read_text())
    online_gate = candidate_gate(baseline, selection, config, stage)
    continue_online = gate and online_gate['passed']
    write_json(args.output / 'online_gate.json', online_gate)
    write_json(args.output / 'candidate.json', {'adapter': str(best.resolve()), 'stage_completed': stage,
               'selected_stage': selection['stage'], 'selected_epoch': selection['epoch'],
               'dev': selection['dev'], 'continue_online': continue_online, 'independent_test_used': False,
               'development_gate': online_gate,
               'adapter_sha256': file_hash(best / 'adapter_model.safetensors'),
               'elapsed_seconds': time.monotonic() - started,
               'gpu_peak_reserved_gib': torch.cuda.max_memory_reserved() / 1024**3})
    print(json.dumps({'event': 'training_finished', 'stage': stage, 'continue_online': continue_online}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('configs/textturn_training.json'))
    main(parser.parse_args())
