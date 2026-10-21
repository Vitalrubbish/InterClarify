"""Rebuild the frozen 1k dataset with a causal delayed-punctuation view."""

import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import time

import yaml

from audit_layer1_dataset import audit, require
from asr_surface import VERSION
from layer1_data import (MicroTurnPlanner, ReleasedTokenizer, SequenceEncoder, arm_view,
                         arms_for_config, digest, file_digest, validate_config, write_json)
from train_layer1 import ProbeDataset

BASELINE_SHA = '86c0faca1e1a12d3c7cf1fa0144e53a6a83166a8454ad48d986b24d40a97761d'
SELECTED_SHA = '98fe4d085a8258566f3e08eeee119f324b5708eb68b4a31f5f4de2d82a75f401'


def load(path):
    return json.loads(path.read_text())


def rebuild(args):
    require(file_digest(args.baseline / 'manifest.json') == BASELINE_SHA, 'Wrong 040a baseline')
    old = load(args.baseline / 'manifest.json')
    require(old['complete'] and file_digest(args.baseline / 'dialogues.json') == SELECTED_SHA == old['selected_sha256'],
            'Original source split changed')
    config = yaml.safe_load(args.config.read_text())
    validate_config(config)
    expected = copy.deepcopy(old['identity']['config'])
    expected['generation']['asr_surface'] = VERSION
    require(config == expected, 'Only the ASR view may change in this rebuild')
    tokenizer = ReleasedTokenizer(args.tokenizer, config['token_ids'])
    require(tokenizer.fingerprint == old['identity']['tokenizer'], 'Tokenizer changed')
    args.output.mkdir(parents=True, exist_ok=False)
    directory = args.output / 'dataset'
    (directory / 'dialogues').mkdir(parents=True)
    for name in ('dialogues.json', 'view_assignments.json', 'exclusions.json'):
        shutil.copyfile(args.baseline / name, directory / name)
    identity = copy.deepcopy(old['identity'])
    identity.update(config=config, human_review_waiver_reason=None,
                    baseline_manifest_sha256=BASELINE_SHA,
                    code={p.name: file_digest(p) for p in (Path(__file__), Path(__file__).with_name('layer1_data.py'),
                         Path(__file__).with_name('asr_surface.py'), Path(__file__).with_name('number_surface.py'))})
    manifest = {k: copy.deepcopy(old[k]) for k in ('source_sampling', 'accepted_source_dialogues', 'exclusions',
                'selected_sha256', 'assignments_sha256', 'split_counts')}
    manifest.update(identity=identity, artifacts={}, complete=False, training_allowed=False,
                    source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
    write_json(directory / 'manifest.json', manifest)
    selected = load(directory / 'dialogues.json')
    assignments = load(directory / 'view_assignments.json')
    planner = MicroTurnPlanner(tokenizer, config)
    encoder = SequenceEncoder(tokenizer, config, 2048)
    minimum, cards = [], []
    source_cards = load(args.review_source)['cards']
    card_lookup = {}
    for card in source_cards:
        card_lookup.setdefault(card['dialogue_id'], []).append(card)
    for position, dialogue in enumerate(selected):
        relative = 'dialogues/' + digest(dialogue['dialogue_id']) + '.json'
        baseline_path = args.baseline / relative
        require(file_digest(baseline_path) == old['artifacts'][relative], 'Baseline artifact changed')
        baseline = load(baseline_path)
        epoch = identity['epoch'] if dialogue['split'] == 'train' else 0
        plan = planner.plan(dialogue, epoch)
        projection = copy.deepcopy(plan)
        for key in ('asr_surface', 'asr_pending'):
            projection.pop(key)
        for event in projection['events']:
            for key in ('user_asr', 'asr_spans'):
                event.pop(key)
        require(projection == baseline['plan'], 'Original event targets or random schedule changed')
        sequences = []
        for arm in arms_for_config(config):
            sequences.extend(encoder.encode(plan, dialogue['split'], arm, arm_view(arm, assignments[dialogue['dialogue_id']])))
        require(len(sequences) <= config['limits']['max_sequences_per_dialogue'], 'Dialogue exceeds sequence budget')
        write_json(directory / relative, {'dialogue_id': dialogue['dialogue_id'], 'split': dialogue['split'],
                                         'plan': plan, 'sequences': sequences})
        manifest['artifacts'][relative] = file_digest(directory / relative)
        if dialogue['split'] == 'train' and len(minimum) < 32:
            minimum.append({'dialogue_id': dialogue['dialogue_id'], 'artifact': relative,
                            'sha256': manifest['artifacts'][relative], 'reviewer': None, 'accepted': None})
        for card in card_lookup.get(dialogue['dialogue_id'], []):
            event_id = card['event_id']
            cards.append({'dialogue_id': dialogue['dialogue_id'], 'split': dialogue['split'],
                          'turn': card['turn'], 'group': card['group'], 'event_id': event_id,
                          'artifact_sha256': manifest['artifacts'][relative], 'human_review': None,
                          'events': [{k: e[k] for k in ('event_id', 'kind', 'user_text', 'user_asr', 'control')}
                              for e in plan['events'][max(0, event_id - 2):event_id + 3]]})
        if position % 100 == 0:
            require(shutil.disk_usage(args.output).free > 20 * 1024**3, 'Less than 20 GiB free')
            require(sum(p.stat().st_size for p in (directory / 'dialogues').iterdir()) < 10 * 1024**3,
                    'Dataset exceeds 10 GiB')
            print('rebuilt', position + 1, flush=True)
    write_json(directory / 'human_review.json', {'schema_version': 1, 'minimum_set': minimum,
               'policy': 'minimum_and_expanded_review', 'expanded_behavior_reviews': [], 'complete': False})
    manifest.update(complete=True, index_complete=True, next_dialogue=len(selected))
    write_json(directory / 'manifest.json', manifest)
    print('Reauditing full dataset', flush=True)
    machine = audit(directory, args.tokenizer)
    write_json(args.output / 'audit.json', machine)
    dataset = ProbeDataset(directory, args.output / 'audit.json', args.tokenizer, 1000, 2048, 'ASR', 20261020)
    write_json(args.output / 'full_train_index.json', {'ASR': dataset.identity})
    require(len(cards) == 60 and len({(r['dialogue_id'], r['turn']) for r in cards}) == 60, 'Review coverage drift')
    write_json(args.output / 'review_cards.json', {'cards': cards, 'source_sha256': file_digest(args.review_source),
                                                 'human_review_complete': False})
    summary = {'machine_passed': machine['machine_passed'], 'baseline_manifest_sha256': BASELINE_SHA,
               'manifest_sha256': file_digest(directory / 'manifest.json'), 'selected_sha256': SELECTED_SHA,
               'audit_sha256': file_digest(args.output / 'audit.json'),
               'index_sha256': file_digest(args.output / 'full_train_index.json'),
               'statistics': dataset.identity['statistics'], 'asr_surface': machine['asr_surface'],
               'review_cards': len(cards), 'original_events_and_targets_unchanged': True,
               'training_allowed': False, 'human_review_complete': False}
    write_json(args.output / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'tokenizer', 'config', 'review-source', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    result = rebuild(args)
    print(json.dumps({'complete': True, 'elapsed_seconds': time.monotonic() - started, **result}), flush=True)
