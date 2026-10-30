"""Freeze complete causal trajectories with positive per-window loss weights."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

from build_textturn_dataset import ControlTokenizer, write_json
from build_textturn_duplex_dataset import scenario
from textturn_loss import assign_loss_weights, complete_trajectory_groups, weight_summary

VERSION = 'tt-010-fulltraj-r1'


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def select_whole_sources(order, costs, limit):
    selected, used = [], 0
    for key in order:
        if used + costs[key] > limit:
            break
        selected.append(key)
        used += costs[key]
    if not selected:
        raise ValueError('No complete source bundle fits the snapshot budget')
    return selected, used


def freeze(base, output, config_path):
    started = time.monotonic()
    if output.exists():
        raise ValueError('Output must be fresh')
    config = json.loads(config_path.read_text())
    if not 1 <= config['train_snapshots_max'] <= 10000 or not 1 <= config['pilot_snapshots_max'] <= 2000:
        raise ValueError('Snapshot budget exceeds the approved bounds')
    manifest = json.loads((base / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        if file_hash(base / name) != expected:
            raise ValueError(f'Frozen base changed: {name}')
    source_index = json.loads((base / 'split_index.json').read_text())
    records = json.loads((base / 'source_records.json').read_text())
    costs = Counter()
    base_trace_counts = {}
    for line in (base / 'timelines.jsonl').open():
        trace = json.loads(line)
        count = sum(e['kind'] == 'control_request' for e in trace['events'])
        costs[trace['source_id']] += count
        base_trace_counts[trace['scenario_id']] = count
    train_ids = {i['source_id'] for i in source_index if i['split'] == 'train'}
    priority = config['priority_train_sources']
    if len(set(priority)) != len(priority) or not set(priority) <= train_ids:
        raise ValueError('Priority sources must be unique original training sources')
    order = priority + sorted(train_ids - set(priority), key=lambda key: hashlib.sha256(
        f"{config['seed']}|complete|{key}".encode()).hexdigest())
    train, train_count = select_whole_sources(order, costs, config['train_snapshots_max'])
    pilot, pilot_count = select_whole_sources(train, costs, config['pilot_snapshots_max'])
    selected = set(train) | {i['source_id'] for i in source_index if i['split'] == 'dev'}
    by_key = {i['source_id']: i for i in source_index}
    selected_index = [by_key[key] for key in train] + [i for i in source_index if i['split'] == 'dev']
    ordinal = {item['source_id']: n for n, item in enumerate(source_index)}
    from tokenizers import Tokenizer
    tokenizer = ControlTokenizer.__new__(ControlTokenizer)
    tokenizer.backend = Tokenizer.from_file(str(base / 'tokenizer.json'))
    tokenizer.special = dict(manifest['new_token_ids'])
    output.mkdir(parents=True)
    write_json(output / 'split_index.json', selected_index)
    write_json(output / 'source_records.json', {key: records[key] for key in selected})
    write_json(output / 'selection.json', {
        'policy': 'whole_source_prefix_in_fixed_hash_order', 'priority_train_sources': priority,
        'train_sources': train, 'pilot_sources': pilot, 'train_snapshots': train_count,
        'pilot_snapshots': pilot_count, 'ordered_original_train_sources': order,
        'source_window_counts': dict(costs), 'rejected_train_sources': order[len(train):]})
    files = {s: f'{s}.jsonl.gz' for s in ('train', 'pilot', 'dev')}
    handles = {s: gzip.open(output / name, 'wt', encoding='utf-8', compresslevel=1) for s, name in files.items()}
    counts, forms, categories, masses, row_counts = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter), defaultdict(Counter), Counter()
    trajectory_index, samples = [], []
    with (output / 'timelines.jsonl').open('w') as timelines, (output / 'prefix_annotations.jsonl').open('w') as annotations:
        try:
            for item in selected_index:
                key, split = item['source_id'], item['split']
                source = records[key] | {'source_id': key}
                for form in ('question', 'declarative'):
                    for variant in ('normal', 'interrupt'):
                        trace, rows = scenario(source, split, form, variant, tokenizer, manifest['config'], ordinal[key])
                        if len(rows) != base_trace_counts[trace['scenario_id']] or any(r['excluded_reason'] for r in rows):
                            raise ValueError('A trajectory changed or contains an overlength window; do not delete frames')
                        complete_trajectory_groups(rows)
                        assign_loss_weights(rows, config['loss_policy'])
                        entry = {'scenario_id': trace['scenario_id'], 'source_id': key, 'split': split,
                                 'windows': len(rows), 'first_snapshot': rows[0]['snapshot_id'],
                                 'last_snapshot': rows[-1]['snapshot_id'], 'pilot': key in pilot,
                                 'weight_summary': weight_summary(rows)}
                        trajectory_index.append(entry)
                        timelines.write(json.dumps(trace, ensure_ascii=False, separators=(',', ':')) + '\n')
                        for row in rows:
                            annotations.write(json.dumps({k: row[k] for k in ('snapshot_id', 'annotation', 'target_action', 'loss_weight')}
                                                         | {'selected': True}, ensure_ascii=False, separators=(',', ':')) + '\n')
                            payload = json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n'
                            destinations = [split] + (['pilot'] if split == 'train' and key in pilot else [])
                            for destination in destinations:
                                handles[destination].write(payload)
                                row_counts[destination] += 1
                                counts[destination][row['target_action']] += 1
                                categories[destination][row['category']] += 1
                                masses[destination][row['target_action']] += row['loss_weight']
                                if row['target_action'] == 'start':
                                    forms[destination][form] += 1
                            if key == priority[0] and form == 'question' and variant == 'normal':
                                samples.append({k: row[k] for k in ('snapshot_id', 'visible_ms', 'visible', 'target_action', 'loss_weight')})
                if time.monotonic() - started > 540 or sum(p.stat().st_size for p in output.iterdir()) > 450 * 1024 ** 2:
                    raise ValueError('CPU or disk budget exceeded; partial evidence retained')
        finally:
            for handle in handles.values():
                handle.close()
    if row_counts['train'] != train_count or row_counts['pilot'] != pilot_count:
        raise ValueError('Complete source selection differs from written window counts')
    if any(forms[s]['question'] != forms[s]['declarative'] for s in files):
        raise ValueError('Complete bundles must preserve the declared start balance')
    write_json(output / 'trajectory_index.json', trajectory_index)
    write_json(output / 'continuous_example.json', samples)
    for name in ('tokenizer.json', 'tokenizer_config.json'):
        (output / name).write_bytes((base / name).read_bytes())
    statistics = {s: {'snapshots': row_counts[s], 'actions': dict(counts[s]),
                      'start_forms': dict(forms[s]), 'categories': dict(categories[s]),
                      'raw_weight_sum': sum(masses[s].values()),
                      'mean_weight': sum(masses[s].values()) / row_counts[s],
                      'action_weight_mass': dict(masses[s])} for s in files}
    result = {'schema_version': 4, 'version': VERSION, 'status': 'frozen_complete_weighted_trajectories',
              'training_allowed': True, 'training_executed': False, 'complete_trajectories': True,
              'event_generator_version': manifest['version'], 'model_revision': manifest['model_revision'],
              'new_token_ids': tokenizer.special, 'action_token_ids': manifest['action_token_ids'],
              'finish_encoding': manifest['finish_encoding'], 'playback_simulated': True,
              'config': manifest['config'], 'selection_config': config, 'loss_policy': config['loss_policy'],
              'split_files': files, 'statistics': statistics,
              'source_dialogues': {'train': len(train), 'pilot': len(pilot), 'dev': sum(i['split'] == 'dev' for i in selected_index)},
              'base_manifest_sha256': file_hash(base / 'manifest.json'),
              'freezer_sha256': file_hash(__file__),
              'builder_sha256': file_hash(Path(__file__).with_name('build_textturn_duplex_dataset.py')),
              'loss_helper_sha256': file_hash(Path(__file__).with_name('textturn_loss.py')),
              'elapsed_seconds': round(time.monotonic() - started, 3), 'limitations': manifest['limitations'],
              'files': {p.name: file_hash(p) for p in output.iterdir()}}
    if sum(p.stat().st_size for p in output.iterdir()) > 512 * 1024 ** 2:
        raise ValueError('Disk budget exceeded')
    write_json(output / 'manifest.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('configs/textturn_full_trajectory.json'))
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
    print(json.dumps(freeze(args.base, args.output, args.config), ensure_ascii=False, indent=2))
