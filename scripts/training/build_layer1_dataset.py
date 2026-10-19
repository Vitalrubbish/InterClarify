"""Build frozen UltraChat micro-turn plans and three punctuation conditions."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

import yaml

from layer1_data import (
    ARMS, DialogueIndex, MicroTurnPlanner, ReleasedTokenizer, SequenceEncoder,
    canonical, digest, file_digest, mixed_assignments, validate_config,
    verify_sources, write_json,
)


def build(args):
    """Resume only complete dialogue artifacts under an immutable input manifest."""
    config = yaml.safe_load(args.config.read_text())
    validate_config(config)
    if args.max_length < 64 or args.epoch < 0:
        raise ValueError('Invalid sequence length or epoch')
    exclusions = json.loads(args.exclusions.read_text())
    if not all(key in exclusions for key in ('ids', 'normalized_hashes', 'source_refs', 'reviewed')):
        raise ValueError('Explicit external exclusion manifest is required')
    if type(exclusions['reviewed']) is not bool or any(
            not isinstance(exclusions[key], list) or any(not isinstance(x, str) for x in exclusions[key])
            for key in ('ids', 'normalized_hashes', 'source_refs')):
        raise ValueError('Invalid exclusion manifest fields')
    if exclusions['reviewed'] and not exclusions['source_refs']:
        raise ValueError('Reviewed exclusions must identify the checked external sources')
    tokenizer = ReleasedTokenizer(args.tokenizer, config['token_ids'])
    paths = verify_sources(args.source_manifest, args.source_dir, args.download_manifest, config['source'])
    identity = {'schema_version': 1, 'config': config, 'source_manifest_sha256': file_digest(args.source_manifest),
                'download_manifest_sha256': file_digest(args.download_manifest),
                'exclusions_sha256': file_digest(args.exclusions), 'exclusions_reviewed': exclusions['reviewed'],
                'exclusion_source_refs': exclusions['source_refs'], 'tokenizer': tokenizer.fingerprint,
                'max_length': args.max_length, 'epoch': args.epoch,
                'code': {p.name: file_digest(p) for p in (Path(__file__), Path(__file__).with_name('layer1_data.py'))}}
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / 'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest['identity'] != identity:
            raise ValueError('Resume inputs differ from the frozen build')
        if not args.resume:
            raise ValueError('Output already exists; use --resume to verify and continue')
    else:
        if any(args.output.iterdir()):
            raise ValueError('Output is nonempty without a valid build manifest')
        manifest = {'identity': identity, 'complete': False, 'training_allowed': False,
                    'next_dialogue': 0, 'artifacts': {}, 'source_commit': subprocess.check_output(
                        ['git', 'rev-parse', 'HEAD'], text=True).strip()}
        write_json(manifest_path, manifest)
        write_json(args.output / 'exclusions.json', exclusions)
    selected_path = args.output / 'dialogues.json'
    index_path = args.output / 'dialogues.sqlite3'
    index = DialogueIndex(index_path, config)
    try:
        if not manifest.get('index_complete'):
            if index.db.execute('SELECT (SELECT COUNT(*) FROM dialogues)+(SELECT COUNT(*) FROM excluded)').fetchone()[0]:
                raise ValueError('Interrupted source index: start a fresh output directory')
            index.ingest(paths, exclusions)
            selected = index.select()
            write_json(selected_path, selected)
            rejected = dict(index.db.execute('SELECT reason,COUNT(*) FROM excluded GROUP BY reason'))
            accepted = index.db.execute('SELECT COUNT(*) FROM dialogues').fetchone()[0]
            manifest.update(index_complete=True, accepted_source_dialogues=accepted, exclusions=rejected,
                            selected_sha256=file_digest(selected_path))
            write_json(manifest_path, manifest)
        if file_digest(selected_path) != manifest['selected_sha256']:
            raise ValueError('Selected dialogue artifact changed')
        selected = json.loads(selected_path.read_text())
        assignments = mixed_assignments(selected, config['seed'], args.epoch)
        write_json(args.output / 'view_assignments.json', assignments)
        planner = MicroTurnPlanner(tokenizer, config)
        encoder = SequenceEncoder(tokenizer, config, args.max_length)
        (args.output / 'dialogues').mkdir(exist_ok=True)
        review_rows = []
        for position, dialogue in enumerate(selected):
            name = digest(dialogue['dialogue_id']) + '.json'
            relative = 'dialogues/' + name
            target = args.output / relative
            if position < manifest['next_dialogue']:
                if file_digest(target) != manifest['artifacts'].get(relative):
                    raise ValueError(f'Completed dialogue changed: {relative}')
                artifact = json.loads(target.read_text())
            else:
                plan_epoch = args.epoch if dialogue['split'] == 'train' else 0
                plan = planner.plan(dialogue, plan_epoch)
                sequences = []
                for arm in ARMS:
                    view = {'T1': 'original', 'T2': 'unpunctuated', 'T3': assignments[dialogue['dialogue_id']]}[arm]
                    sequences.extend(encoder.encode(plan, dialogue['split'], arm, view))
                if len(sequences) > config['limits']['max_sequences_per_dialogue']:
                    raise ValueError('Per-dialogue sequence budget exceeded')
                artifact = {'dialogue_id': dialogue['dialogue_id'], 'split': dialogue['split'],
                            'plan': plan, 'sequences': sequences}
                write_json(target, artifact)
                manifest['artifacts'][relative] = file_digest(target)
                manifest['next_dialogue'] = position + 1
                write_json(manifest_path, manifest)
                index.check_resources()
            if dialogue['split'] == 'train' and len(review_rows) < 32:
                review_rows.append({'dialogue_id': dialogue['dialogue_id'], 'artifact': relative,
                                    'sha256': file_digest(target), 'reviewer': None, 'accepted': None})
        write_json(args.output / 'smoke_subsets.json', {
            str(n): [d['dialogue_id'] for d in selected if d['split'] == 'train'][:n] for n in (32, 100)})
        review_path = args.output / 'human_review.json'
        if not review_path.exists():
            write_json(review_path, {'schema_version': 1, 'minimum_set': review_rows,
                                    'expanded_behavior_reviews': [], 'complete': False})
        manifest.update(complete=True, training_allowed=False,
                        split_counts=dict(Counter(d['split'] for d in selected)),
                        assignments_sha256=file_digest(args.output / 'view_assignments.json'))
        write_json(manifest_path, manifest)
        return manifest
    finally:
        index.close()


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--config', type=Path, default=Path('configs/layer1_data.yaml'))
    result.add_argument('--source-manifest', type=Path, required=True)
    result.add_argument('--source-dir', type=Path, required=True)
    result.add_argument('--download-manifest', type=Path, required=True)
    result.add_argument('--tokenizer', type=Path, required=True)
    result.add_argument('--exclusions', type=Path, required=True)
    result.add_argument('--max-length', type=int, required=True)
    result.add_argument('--epoch', type=int, default=0)
    result.add_argument('--output', type=Path, required=True)
    result.add_argument('--resume', action='store_true')
    return result


if __name__ == '__main__':
    print(canonical({'complete': build(parser().parse_args())['complete'], 'training_allowed': False}))
