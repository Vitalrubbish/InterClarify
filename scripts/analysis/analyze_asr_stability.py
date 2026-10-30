"""Measure observed ASR prefix revisions without treating frozen Context as ASR votes."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re


WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*|[\u4e00-\u9fff]")


def words(text):
    """Compare lexical prefixes; case and punctuation are explicitly excluded."""
    return [match.group().casefold() for match in WORD.finditer(text)]


def percentile(values, fraction):
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def distribution(values):
    return {'count': len(values), **{
        name: percentile(values, fraction) for name, fraction in (('p50', .5), ('p90', .9), ('p95', .95))
    }, 'max': max(values)} if values else {'count': 0}


def load_groups(directory):
    groups, manifests = defaultdict(list), []
    excluded = Counter()
    for path in sorted(directory.glob('*.events.jsonl')):
        blob = path.read_bytes()
        manifests.append({'path': str(path), 'sha256': hashlib.sha256(blob).hexdigest()})
        observations = [row for row in map(json.loads, blob.splitlines()) if row['kind'] == 'asr_observation']
        for index, event in enumerate(observations):
            if event['delivery_phase'] != 'online' or event['call_status'] == 'error':
                excluded['not_successful_online'] += 1
                continue
            real = [span for span in event['audio_spans'] if span['kind'] == 'real']
            if not real or not all(a['end'] == b['start'] for a, b in zip(real, real[1:])):
                excluded['synthetic_or_noncontiguous'] += 1
                continue
            key = event['session_id'], event['controller_generation'], real[0]['start']
            groups[key].append({'call_index': index + 1, 'source_index': index,
                                'event_id': event['event_id'], 'call_kind': event['call_kind'],
                                'audio_start': real[0]['start'], 'audio_end': real[-1]['end'],
                                'returned_at': event['asr_returned_at'], 'text': event['text'],
                                'tokens': words(event['text'])})
    return groups, manifests, excluded


def analyze_group(key, rows):
    """Use only hypotheses sharing one real-audio origin and controller generation."""
    if any(b['audio_end'] < a['audio_end'] for a, b in zip(rows, rows[1:])):
        raise ValueError(f'Regressed audio coverage within {key}')
    final = rows[-1]['tokens']
    tracks = []
    for length in range(1, len(final) + 1):
        target = final[:length]
        first_slot = next(index for index, row in enumerate(rows) if len(row['tokens']) >= length)
        first_match = next(index for index, row in enumerate(rows) if row['tokens'][:length] == target)
        last_disagree = max((index for index, row in enumerate(rows) if row['tokens'][:length] != target), default=-1)
        stable = last_disagree + 1
        suffix = rows[stable:]
        # An existing result or newly decoded identical coverage is not a fresh-audio vote.
        evidence = []
        for row in suffix:
            if not evidence or row['audio_end'] > evidence[-1]['audio_end']:
                evidence.append(row)
        confirm = evidence[2] if len(evidence) >= 3 else None
        tracks.append({'case': key[0], 'generation': key[1], 'audio_start': key[2],
                       'prefix_words': length, 'final_prefix': ' '.join(target),
                       'first_slot_call': rows[first_slot]['call_index'],
                       'first_match_call': rows[first_match]['call_index'],
                       'last_revision_call': rows[stable]['call_index'],
                       'last_revision_delay_ms': (rows[stable]['returned_at'] - rows[first_slot]['returned_at']) * 1000,
                       'last_revision_extra_updates': rows[stable]['call_index'] - rows[first_slot]['call_index'],
                       'suffix_fresh_observations': len(evidence), 'confirmed_three': confirm is not None,
                       'confirmation_call': confirm['call_index'] if confirm else None,
                       'confirmation_delay_from_first_slot_ms': (confirm['returned_at'] - rows[first_slot]['returned_at']) * 1000 if confirm else None,
                       'confirmation_delay_from_final_text_ms': (confirm['returned_at'] - rows[stable]['returned_at']) * 1000 if confirm else None,
                       'confirmation_extra_updates': confirm['call_index'] - rows[first_slot]['call_index'] if confirm else None})
    agreements = []
    for required in (2, 3):
        emitted = set()
        for end in range(required - 1, len(rows)):
            candidates = rows[end - required + 1:end + 1]
            if not all(b['source_index'] == a['source_index'] + 1 and b['audio_end'] > a['audio_end']
                       for a, b in zip(candidates, candidates[1:])):
                continue
            common = 0
            for position in range(min(len(row['tokens']) for row in candidates)):
                if len({row['tokens'][position] for row in candidates}) != 1:
                    break
                common += 1
            for length in range(1, common + 1):
                if length in emitted:
                    continue
                emitted.add(length)
                target = rows[end]['tokens'][:length]
                later = rows[end + 1:]
                contradiction = next((row for row in later if row['tokens'][:length] != target), None)
                first_slot = next(row for row in rows[:end + 1] if len(row['tokens']) >= length)
                fresh_later = [row for row in later if row['audio_end'] > rows[end]['audio_end']]
                agreements.append({'case': key[0], 'generation': key[1], 'audio_start': key[2],
                                   'required': required, 'prefix_words': length,
                                   'candidate_prefix': ' '.join(target), 'commit_call': rows[end]['call_index'],
                                   'delay_ms': (rows[end]['returned_at'] - first_slot['returned_at']) * 1000,
                                   'extra_updates': rows[end]['call_index'] - first_slot['call_index'],
                                   'later_observation_count': len(later), 'later_fresh_observation_count': len(fresh_later),
                                   'later_revised': contradiction is not None,
                                   'contradiction_call': contradiction['call_index'] if contradiction else None,
                                   'contradiction_text': contradiction['text'] if contradiction else None})
    return {'case': key[0], 'generation': key[1], 'audio_start': key[2],
            'calls': len(rows), 'call_indices': [row['call_index'] for row in rows],
            'final_text': rows[-1]['text'], 'tracks': tracks, 'agreements': agreements,
            'observations': rows}


def summarize(groups):
    tracks = [track for group in groups for track in group['tracks']]
    confirmed = [track for track in tracks if track['confirmed_three']]
    result = {'groups': len(groups), 'prefix_endpoints': len(tracks),
              'confirmed_three_endpoints': len(confirmed), 'insufficient_followup_endpoints': len(tracks) - len(confirmed),
              'last_revision_delay_ms_confirmed': distribution([row['last_revision_delay_ms'] for row in confirmed]),
              'last_revision_extra_updates_confirmed': distribution([row['last_revision_extra_updates'] for row in confirmed]),
              'three_confirmation_delay_ms': distribution([row['confirmation_delay_from_first_slot_ms'] for row in confirmed]),
              'three_confirmation_extra_updates': distribution([row['confirmation_extra_updates'] for row in confirmed]),
              'confirmation_wait_after_final_text_ms': distribution([row['confirmation_delay_from_final_text_ms'] for row in confirmed]),
              'agreements': {}}
    for required in (2, 3):
        candidates = [a for group in groups for a in group['agreements'] if a['required'] == required]
        later = [a for a in candidates if a['later_fresh_observation_count']]
        result['agreements'][str(required)] = {
            'candidate_endpoints': len(candidates), 'with_later_fresh_observations': len(later),
            'revised_later': sum(a['later_revised'] for a in candidates),
            'revised_later_with_fresh_followup': sum(a['later_revised'] for a in later),
            'delay_ms': distribution([a['delay_ms'] for a in candidates]),
            'extra_updates': distribution([a['extra_updates'] for a in candidates])}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    groups, manifest, excluded = load_groups(args.input_dir)
    eligible = [analyze_group(key, rows) for key, rows in groups.items()
                if len({row['audio_end'] for row in rows}) >= 3]
    primary = [group for group in eligible if group['case'] in ('calibrated_full', 'sensevoice_english')]
    output = {'schema': 'asr-prefix-stability-observed-v1',
              'input_manifest': manifest, 'excluded': dict(excluded),
              'all_source_observations': sum(len(rows) for rows in groups.values()),
              'eligible_source_observations': sum(group['calls'] for group in eligible),
              'excluded_short_groups': sum(len({row['audio_end'] for row in rows}) < 3 for rows in groups.values()),
              'primary_cases': ['calibrated_full', 'sensevoice_english'],
              'primary': summarize(primary), 'all_views': summarize(eligible),
              'per_case': {case: summarize([g for g in eligible if g['case'] == case])
                           for case in sorted({g['case'] for g in eligible})},
              'groups': eligible,
              'limitations': ['Lexical prefix endpoints are correlated; they are not independent words or audio examples.',
                              'Case and punctuation are ignored; no guarantee for punctuation or exact character stability.',
                              'Fixed-origin comparison excludes shifted or noncontiguous windows and splits controller generations.',
                              'First slot means first hypothesis long enough to cover that prefix position, not acoustic word onset.',
                              'The final comparable output is an observed endpoint, not a correctness reference or proof of future stability.',
                              'Three-observation evidence requires fresh audio; missing follow-up is censored, never treated as stable.']}
    (args.output_dir / 'analysis.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: output[key] for key in ('all_source_observations', 'eligible_source_observations',
                                                 'excluded_short_groups', 'primary', 'per_case')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
