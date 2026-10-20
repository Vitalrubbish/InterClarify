"""Diagnose waiting controls and ASR reference disagreements in frozen FDB runs."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re


ARMS = ('B0', 'T1', 'T2', 'T3')
TALKING = '<|user is talking|>'


def words(text):
    text = text.lower().replace('\u2019', "'").replace('\u2018', "'")
    text = re.sub(r'\[(pause|turn-taking|interrupt|interruption|backchannel)\]', ' ', text)
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text)


def reference_text(record):
    annotations = record['annotations']
    if 'transcription.json' in annotations:
        return ' '.join(row['text'] for row in annotations['transcription.json']), 'transcription.json'
    if 'interrupt.json' in annotations:
        return ' '.join(' '.join((row['context'], row['interrupt']))
                        for row in annotations['interrupt.json']), 'interrupt.json context+interrupt'
    return None, None


def edit_counts(reference, hypothesis):
    """Return a minimum-edit word alignment with deterministic tie breaking."""
    table = [[0] * (len(hypothesis) + 1) for _ in range(len(reference) + 1)]
    for i in range(len(reference) + 1): table[i][0] = i
    for j in range(len(hypothesis) + 1): table[0][j] = j
    for i, expected in enumerate(reference, 1):
        for j, actual in enumerate(hypothesis, 1):
            table[i][j] = min(table[i-1][j-1] + (expected != actual),
                              table[i-1][j] + 1, table[i][j-1] + 1)
    i, j = len(reference), len(hypothesis)
    operations = []
    while i or j:
        if i and j and table[i][j] == table[i-1][j-1] + (reference[i-1] != hypothesis[j-1]):
            if reference[i-1] != hypothesis[j-1]:
                operations.append({'op': 'substitution', 'reference': reference[i-1], 'hypothesis': hypothesis[j-1]})
            i -= 1; j -= 1
        elif i and table[i][j] == table[i-1][j] + 1:
            operations.append({'op': 'deletion', 'reference': reference[i-1], 'hypothesis': ''})
            i -= 1
        else:
            operations.append({'op': 'insertion', 'reference': '', 'hypothesis': hypothesis[j-1]})
            j -= 1
    counts = Counter(row['op'] for row in operations)
    return {'reference_words': len(reference), 'hypothesis_words': len(hypothesis),
            'substitutions': counts['substitution'], 'deletions': counts['deletion'],
            'insertions': counts['insertion'], 'errors': len(operations),
            'wer': len(operations) / len(reference) if reference else None,
            'alignment_errors': list(reversed(operations))}


def aggregate(rows):
    scored = [r for r in rows if r['asr_score'] is not None]
    denominator = sum(r['asr_score']['reference_words'] for r in scored)
    errors = sum(r['asr_score']['errors'] for r in scored)
    return {'samples': len(rows), 'voice_samples_any_time': sum(r['has_voice'] for r in rows),
            'new_response_playback_in_original_window_samples': sum(r['new_response_playback_in_original_window'] for r in rows),
            'only_talking_samples': sum(r['only_talking'] for r in rows),
            'only_talking_after_final_asr_samples': sum(r['only_talking_after_final_asr'] for r in rows),
            'prefix_delivery_mismatches': sum(not r['final_prefix_matches_asr'] for r in rows),
            'asr_reference_samples': len(scored), 'asr_missing_reference_samples': len(rows) - len(scored),
            'reference_words': denominator, 'word_errors': errors,
            'wer': errors / denominator if denominator else None,
            'controls': dict(sum((Counter(r['controls']) for r in rows), Counter()))}


def analyze(observation):
    conditions, all_rows = {}, []
    assert observation['round_exit_code'] == '0'
    for arm in ARMS:
        condition = observation['conditions'][arm]
        assert condition['exit_code'] == '0' and len(condition['rows']) == 25
        assert condition['health']['adaptation']['condition'] == arm
        rows = []
        for row in condition['rows']:
            ref, source = reference_text(observation['references'][row['sample']])
            score = edit_counts(words(ref), words(row['final_asr'])) if ref else None
            tail = row['controls_after_final_asr']
            key = ('turn_taking' if row['sample'].startswith('candor_turn_taking/') else
                   'interruption_end' if row['sample'].startswith('synthetic_user_interruption/') else None)
            metrics = row['client_measurements'].get('latencies', {}).get(key, {}) if key else {}
            delay = metrics.get('to_playback_started_seconds')
            onset = metrics.get('anchor_seconds', 0) + delay if delay is not None else None
            item = {**row, 'condition': arm, 'reference': ref, 'reference_source': source, 'asr_score': score,
                    'has_voice': row['tts_audio_bytes'] > 0,
                    'new_response_playback_delay_seconds': delay,
                    'new_response_playback_in_original_window': onset is not None and delay >= 0 and onset <= row['duration_seconds'],
                    'asr_has_terminal_punctuation': bool(re.search(r'[.!?]$', row['final_asr'].rstrip())),
                    'only_talking': bool(row['controls']) and set(row['controls']) == {TALKING},
                    'only_talking_after_final_asr': bool(tail) and set(tail) == {TALKING},
                    'final_prefix_matches_asr': row['final_asr'] == row['final_model_prefix']}
            rows.append(item)
        assert len({r['sample'] for r in rows}) == 25
        all_rows.extend(rows)
        subsets = sorted({row['sample'].split('/')[0] for row in rows})
        conditions[arm] = {'all': aggregate(rows), 'subsets': {
            subset: aggregate([r for r in rows if r['sample'].startswith(subset + '/')]) for subset in subsets}}
    comparison = []
    for sample in sorted(observation['references']):
        rows = {r['condition']: r for r in all_rows if r['sample'] == sample}
        texts = {arm: row['final_asr'] for arm, row in rows.items()}
        comparison.append({'sample': sample, 'exact_final_asr_equal': len(set(texts.values())) == 1,
                           'normalized_final_asr_equal': len({tuple(words(t)) for t in texts.values()}) == 1,
                           'texts': texts})
    return {'observed_at': observation['observed_at'], 'conditions': conditions,
            'cross_condition_asr': comparison,
            'exact_final_asr_equal_samples': sum(r['exact_final_asr_equal'] for r in comparison),
            'normalized_final_asr_equal_samples': sum(r['normalized_final_asr_equal'] for r in comparison),
            'official_scoring': 'pending', 'human_audio_transcription_review': 'not_performed',
            'normalization': 'lowercase, curly apostrophe normalization, punctuation/behavior markers removed; fillers and contractions retained',
            'rows': all_rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(json.loads(args.input.read_text()))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    with (args.output / 'samples.csv').open('w', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['condition', 'sample', 'voice_any_time', 'only_talking_after_final_asr',
                         'wer', 'reference', 'final_asr'])
        for row in report['rows']:
            writer.writerow([row['condition'], row['sample'], row['has_voice'],
                             row['only_talking_after_final_asr'],
                             row['asr_score']['wer'] if row['asr_score'] else None,
                             row['reference'], row['final_asr']])
    print(json.dumps({'conditions': report['conditions'],
                      'exact_final_asr_equal_samples': report['exact_final_asr_equal_samples']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
