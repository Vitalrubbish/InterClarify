"""Audit frozen training-only TextTurn exposure and deterministic label shortcuts."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
from score_textturn_trace import INCOMPLETE, file_hash, is_interruption, normalize


def shortcut(row):
    visible = row['visible']
    text = normalize(visible['user_text'])
    if visible['state'] == 'Speak':
        return 'stop' if is_interruption(text) else 'keep'
    return 'start' if (visible['observation'] == '<|no-voice|>' and text and text not in INCOMPLETE) else 'keep'


def audit_split(path):
    counts = Counter()
    confusion = Counter()
    groups = defaultdict(set)
    fingerprints = defaultdict(set)
    shortcut_errors = Counter()
    action_by_category = Counter()
    no_voice_keep_texts = Counter()
    max_tokens, declarations, starts, mask_errors = 0, 0, 0, 0
    manifest = json.loads((path.parent / 'manifest.json').read_text())
    source_ids = set()
    with path.open() as stream:
        for line in stream:
            row = json.loads(line)
            visible, action = row['visible'], row['target_action']
            source_ids.add(row['source_id'])
            silent = visible['observation'] == '<|no-voice|>'
            counts[f"{visible['state']}/{action}/{'no_voice' if silent else 'text'}"] += 1
            action_by_category[f"{row['category']}/{action}"] += 1
            predicted = shortcut(row)
            confusion[f'{action}->{predicted}'] += 1
            if predicted != action:
                shortcut_errors[f"{row['category']}/{action}"] += 1
            if silent and visible['state'] == 'Listen' and action == 'keep' and visible['user_text']:
                no_voice_keep_texts[normalize(visible['user_text'])] += 1
            groups[row['category']].add(row['source_id'])
            fingerprints[hashlib.sha256(row['prompt'].encode()).hexdigest()].add(action)
            supervised = [v for v in row['labels'] if v != -100]
            expected = manifest['new_token_ids'][f'<|tt_{action}|>']
            mask_errors += supervised != [expected] or len(row['labels']) != len(row['input_ids'])
            max_tokens = max(max_tokens, len(row['input_ids']))
            starts += action == 'start'
            declarations += action == 'start' and row['utterance_form'] == 'declarative'
    total = sum(counts.values())
    return {'snapshots': total, 'source_dialogues': len(source_ids), 'state_action_observation': dict(counts),
            'category_actions': dict(action_by_category),
            'category_source_groups': {k: len(v) for k, v in groups.items()},
            'loss_mask_errors': mask_errors, 'max_input_tokens': max_tokens,
            'declarative_starts': declarations, 'all_starts': starts,
            'identical_prompt_conflicting_labels': sum(len(v) > 1 for v in fingerprints.values()),
            'shortcut_correct': total - sum(shortcut_errors.values()),
            'shortcut_accuracy': (total - sum(shortcut_errors.values())) / total if total else None,
            'shortcut_confusion': dict(confusion), 'shortcut_errors_by_category': dict(shortcut_errors),
            'listen_silent_keep_nonempty_unique_texts': len(no_voice_keep_texts),
            'listen_silent_keep_incomplete_prefix_windows': sum(v for k, v in no_voice_keep_texts.items() if k in INCOMPLETE),
            'listen_silent_keep_other_windows': sum(v for k, v in no_voice_keep_texts.items() if k not in INCOMPLETE),
            'file_sha256': file_hash(path)}


def audit(args):
    if args.output.exists():
        raise ValueError('Use a fresh audit report path')
    manifest = json.loads((args.data / 'manifest.json').read_text())
    for name in ('train.jsonl', 'pilot.jsonl', 'event_plans.json', 'source_records.json'):
        if file_hash(args.data / name) != manifest['files'][name]:
            raise ValueError(f'Frozen training input changed: {name}')
    result = {'scope': 'training_sources_only_no_test_text_or_model_results',
              'identity': {'manifest_sha256': file_hash(args.data / 'manifest.json'),
                           'audit_sha256': file_hash(__file__),
                           'builder_sha256': file_hash(Path(__file__).parents[1] / 'training/freeze_textturn_dataset.py')},
              'splits': {name: audit_split(args.data / f'{name}.jsonl') for name in ('train', 'pilot')}}
    plans = [p for p in json.loads((args.data / 'event_plans.json').read_text()) if p['split'] == 'train']
    sources = json.loads((args.data / 'source_records.json').read_text())
    backchannels, interruptions = Counter(), Counter()
    coverage = Counter()
    for plan in plans:
        for phase in plan['phases']:
            if phase.get('category') == 'backchannel' and 'text' in phase:
                backchannels[phase['text']] += 1
            if phase.get('category') == 'interruption' and 'text' in phase:
                interruptions[phase['text']] += 1
            if phase['channel'] == 'silence' and phase.get('category') == 'pause':
                coverage['explicit_pause_opportunities'] += 1
            if phase['channel'] == 'playback_tail':
                coverage['natural_playback_tail_opportunities'] += 1
        coverage['multi_sentence_declarations'] += len(__import__('re').split(
            r'(?<=[.!?])\s+(?=[A-Z])', sources[plan['source_id']]['texts'][2])) > 1
        channels = [p['channel'] for p in plan['phases']]
        stop_index = next(i for i, p in enumerate(plan['phases']) if p.get('action') == 'stop')
        coverage['interruption_after_playback_tail'] += 'playback_tail' in channels[max(0, stop_index - 1):stop_index]
        coverage['fixed_mixed_trajectory'] += channels == [
            'user', 'silence', 'user', 'silence', 'generation', 'user', 'generation',
            'playback_tail', 'playback_complete', 'post_playback_wait', 'user', 'silence', 'generation', 'user']
    exposures = Counter()
    for name in ('pilot', 'train'):
        for key, count in result['splits'][name]['category_actions'].items():
            exposures[key.rsplit('/', 1)[-1]] += 2 * count
    result.update(templates={'backchannels': dict(backchannels), 'interruptions': dict(interruptions)},
                  construction_coverage=dict(coverage), effective_two_epoch_exposure=dict(exposures),
                  independent_training_sources=len(plans),
                  limitations_zh=['词内突发和真实ASR话中空窗未在该构造中模拟。',
                                  '相同prompt无冲突不能证明语义标签正确；完整子句后keep需要独立因果审核。',
                                  '无模型规则高分仅用于识别时序捷径，不等于真实控制能力。'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    audit(parser.parse_args())
