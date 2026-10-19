"""Audit serialized supervision, provenance, duplicate groups and view invariants."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from layer1_data import (
    ARMS, CONTROLS, MicroTurnPlanner, ReleasedTokenizer, SequenceEncoder,
    canonical, digest, file_digest, mixed_assignments, shingles, similar, write_json,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(directory, tokenizer_dir):
    """Fail closed on data corruption; keep human approval separate from code checks."""
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    require(manifest.get('complete'), 'Build is incomplete')
    config = manifest['identity']['config']
    tokenizer = ReleasedTokenizer(tokenizer_dir, config['token_ids'])
    require(tokenizer.fingerprint == manifest['identity']['tokenizer'], 'Tokenizer asset changed')
    selected = json.loads((directory / 'dialogues.json').read_text())
    require(file_digest(directory / 'dialogues.json') == manifest['selected_sha256'], 'Split artifact changed')
    require(dict(Counter(d['split'] for d in selected)) == {k: v for k, v in config['splits'].items() if v},
            'Split counts differ from registered sizes')
    require(len({d['dialogue_id'] for d in selected}) == len(selected), 'Repeated dialogue ID')
    require(len({d['duplicate_group'] for d in selected}) == len(selected), 'Duplicate group leakage')
    grams = [set(shingles(d['texts'], config['dedup']['word_ngram'])) for d in selected]
    for i, left in enumerate(selected):
        for j in range(i):
            if left['split'] != selected[j]['split']:
                require(not similar(grams[i], grams[j], config['dedup']['jaccard_threshold']),
                        'Cross-split near duplicate')
    assignments = json.loads((directory / 'view_assignments.json').read_text())
    require(assignments == mixed_assignments(selected, config['seed'], manifest['identity']['epoch']),
            'Invalid view assignment')
    require(file_digest(directory / 'view_assignments.json') == manifest['assignments_sha256'],
            'Assignment artifact changed')
    mix = Counter(assignments[d['dialogue_id']] for d in selected if d['split'] == 'train')
    require(mix['original'] == mix['unpunctuated'] == config['splits']['train'] // 2, 'Unbalanced T3 train')
    planner = MicroTurnPlanner(tokenizer, config)
    encoder = SequenceEncoder(tokenizer, config, manifest['identity']['max_length'])
    controls, kinds, lengths, sampling = Counter(), Counter(), [], Counter()
    sequence_counts, token_counts, events_per_split = Counter(), Counter(), Counter()
    expected_artifacts = set()
    for dialogue in selected:
        relative = 'dialogues/' + digest(dialogue['dialogue_id']) + '.json'
        expected_artifacts.add(relative)
        path = directory / relative
        require(file_digest(path) == manifest['artifacts'].get(relative), 'Dialogue checksum mismatch')
        artifact = json.loads(path.read_text())
        epoch = manifest['identity']['epoch'] if dialogue['split'] == 'train' else 0
        plan = planner.plan(dialogue, epoch)
        sampling.update(plan['sampling'])
        require(artifact['plan'] == plan, 'Event plan is not reproducible')
        require(artifact['dialogue_id'] == dialogue['dialogue_id'] and artifact['split'] == dialogue['split'],
                'Artifact provenance mismatch')
        events = plan['events']
        for event in events:
            kinds[event['kind']] += 1
            controls[event['control'] or 'content_only'] += 1
            origin = event['user_origin']
            if origin:
                require(dialogue['texts'][origin['turn']][origin['start']:origin['end']] == event['user_text'],
                        'User span does not match source')
            if event['control'] in ('speaking', 'thinking', 'interruption'):
                require(not event['assistant_ids'], 'Silent control contains response content')
            if event['kind'] == 'natural_pause':
                require(event['control'] == 'speaking' and not event['user_text'], 'Pause was relabeled as end')
            if event['kind'] == 'user_backchannel':
                require(event['control'] == 'backchannel' and event['assistant_ids'], 'Backchannel stopped answer')
        events_per_split[dialogue['split']] += len(events)
        for arm in ARMS:
            view = {'T1': 'original', 'T2': 'unpunctuated', 'T3': assignments[dialogue['dialogue_id']]}[arm]
            actual = [s for s in artifact['sequences'] if s['arm'] == arm]
            expected = list(encoder.encode(plan, dialogue['split'], arm, view))
            require(actual == expected, 'Serialized IDs, labels or view differ from frozen plan')
            coverage = Counter()
            for row in actual:
                require(len(row['input_ids']) == len(row['labels']) == len(row['attention_mask']), 'Mask length mismatch')
                require(len(row['input_ids']) <= encoder.max_length, 'Length limit exceeded')
                require(row['effective_tokens'] > 0, 'No supervised tokens')
                for span in row['spans']:
                    require(all(x == -100 for x in row['labels'][span['start']:span['target_start']]),
                            'User or message header is supervised')
                    if span['supervised']:
                        coverage[span['event_id']] += 1
                        require(row['input_ids'][span['end'] - 1] == encoder.eos, 'Incomplete message boundary')
                sequence_counts[f'{dialogue["split"]}/{arm}'] += 1
                token_counts[f'{dialogue["split"]}/{arm}'] += row['effective_tokens']
                lengths.append(len(row['input_ids']))
            require(coverage == Counter(range(len(events))), 'Missing or repeated event targets')
        require(len(artifact['sequences']) == sum(1 for s in artifact['sequences'] if s['arm'] in ARMS),
                'Unknown experimental arm')
    require(set(manifest['artifacts']) == expected_artifacts, 'Artifact coverage mismatch')
    require(file_digest(directory / 'exclusions.json') == manifest['identity']['exclusions_sha256'],
            'External exclusion manifest changed')
    review = json.loads((directory / 'human_review.json').read_text())
    minimum = review['minimum_set']
    expected_minimum = [d['dialogue_id'] for d in selected if d['split'] == 'train'][:32]
    minimum_ok = len(minimum) == 32 and [r['dialogue_id'] for r in minimum] == expected_minimum
    for row in minimum:
        minimum_ok = minimum_ok and row.get('accepted') is True and bool(row.get('reviewer'))
        minimum_ok = minimum_ok and manifest['artifacts'].get(row['artifact']) == row.get('sha256')
    reviewed_behaviors = set()
    double_reviewed = 0
    dialogue_lookup = {d['dialogue_id']: d for d in selected}
    for row in review.get('expanded_behavior_reviews', []):
        identity = row.get('dialogue_id')
        if identity not in dialogue_lookup:
            continue
        relative = 'dialogues/' + digest(identity) + '.json'
        if row.get('sha256') != manifest['artifacts'][relative]:
            continue
        artifact = json.loads((directory / relative).read_text())
        event_id = row.get('event_id')
        if type(event_id) is not int or not 0 <= event_id < len(artifact['plan']['events']):
            continue
        event = artifact['plan']['events'][event_id]
        reviewers = {r.get('reviewer') for r in row.get('reviews', []) if r.get('accepted') is True and r.get('reviewer')}
        if reviewers:
            reviewed_behaviors.add(event['control'])
        if len(reviewers) >= 2:
            double_reviewed += 1
    expanded_ok = set(CONTROLS) <= reviewed_behaviors and double_reviewed > 0 and review.get('complete') is True
    rates = {}
    for name, denominator in (('pause', 'pause_eligible_boundaries'),
                              ('interruption', 'interruption_eligible_long_turns'),
                              ('backchannel', 'backchannel_eligible_continuations')):
        rates[name] = {'triggers': sampling[name + '_triggers'], 'eligible': sampling[denominator],
                       'rate': sampling[name + '_triggers'] / sampling[denominator] if sampling[denominator] else None,
                       'sampling_unit': denominator}
    pending = ['issue005_resource_and_recovery', 'issue007_pretraining_evaluation_gates']
    if not minimum_ok:
        pending.append('minimum_32_human_review')
    if not expanded_ok:
        pending.append('expanded_behavior_and_double_review')
    if not manifest['identity']['exclusions_reviewed']:
        pending.append('external_exclusion_review')
    return {'schema_version': 1, 'machine_passed': True, 'training_allowed': False,
            'parent_issue_complete': False, 'minimum_32_human_review_passed': bool(minimum_ok),
            'expanded_review_complete': expanded_ok,
            'double_reviewed_events': double_reviewed,
            'exclusions_reviewed': manifest['identity']['exclusions_reviewed'],
            'exclusion_review_scope': manifest['identity'].get('exclusion_review_scope', 'legacy_manifest'),
            'optional_text_coverage_complete': manifest['identity'].get('optional_text_coverage_complete'),
            'manifest_sha256': file_digest(directory / 'manifest.json'),
            'auditor_sha256': file_digest(__file__), 'dialogues': dict(Counter(d['split'] for d in selected)),
            'sequences': dict(sequence_counts), 'effective_tokens': dict(token_counts),
            'micro_turns': dict(events_per_split), 'controls': dict(controls), 'event_kinds': dict(kinds),
            'sampling': dict(sampling),
            'observed_rates': rates,
            'source': config['source'], 'source_manifest_sha256': manifest['identity']['source_manifest_sha256'],
            'accepted_source_dialogues': manifest['accepted_source_dialogues'], 'exclusion_counts': manifest['exclusions'],
            'length': {'min': min(lengths), 'max': max(lengths), 'mean': sum(lengths) / len(lengths)},
            't3_train_views': dict(mix), 'source_type': 'synthetic_ultrachat',
            'clock_type': 'synthetic_window_only', 'official_pretraining_overlap': 'unknown',
            'near_duplicate_scope': 'normalized_word_shingle_jaccard',
            'pending': pending}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit(args.dataset, args.tokenizer)
    except Exception as error:
        write_json(args.output, {'machine_passed': False, 'training_allowed': False,
                                'error': f'{type(error).__name__}: {error}'})
        raise
    write_json(args.output, report)
    print(canonical(report))
