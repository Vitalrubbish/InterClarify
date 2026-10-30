"""Collect existing FDB traces and measure source-confirmation waits on CPU only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import time

from analyze_asr_stability import analyze_group, distribution, summarize, words


EXPECTED_MODEL = '85d9d049c47d42fda2797806024044d141e2703fd6a63ef2853cbd29887f2a52'
SUBSETS = ('candor_turn_taking', 'synthetic_user_interruption',
           'candor_pause_handling', 'synthetic_pause_handling')
KEPT = {'input_started', 'controller_begin', 'controller_raw', 'controller_state',
        'asr_begin', 'asr_result'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(root, output):
    """Freeze compact, auditable copies without modifying any inference run."""
    source = root / 'campaigns/20261030-syn-r1/final-report.json'
    report = json.loads(source.read_text())
    if not report['passed'] or report['n'] != 1344:
        raise ValueError('Expected the complete frozen FDB report')
    model = root / 'upstream/frozen-20261028/soulx-duplug/service/model.py'
    if digest(model) != EXPECTED_MODEL:
        raise ValueError('SoulX implementation differs from ledger reconstruction')
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'report': str(source), 'report_sha256': digest(source),
                'model_sha256': digest(model), 'samples': []}
    deadline, input_bytes = time.monotonic() + 150, 0
    with gzip.open(output / 'traces.jsonl.gz', 'wt', encoding='utf-8') as target:
        for row in report['rows']:
            if row['controller'] != 'soulx' or row['subset'] not in SUBSETS:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError('Trace collection exceeded 150 seconds')
            path = Path(row['recorded_audio']).parent / 'events.jsonl'
            data = path.read_bytes()
            input_bytes += len(data)
            if len(data) > 32 * 1024 * 1024 or input_bytes > 1024 * 1024 * 1024:
                raise RuntimeError('Existing trace read budget exceeded')
            events = []
            for event in map(json.loads, data.splitlines()):
                kind = event['event']
                if kind not in KEPT:
                    continue
                if kind in ('asr_begin', 'asr_result') and event['source'] != 'native_cascade':
                    continue
                events.append(event)
            sample = {'subset': row['subset'], 'id': row['id'], 'trace': str(path),
                      'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'events': events}
            target.write(json.dumps(sample, ensure_ascii=False) + '\n')
            manifest['samples'].append({k: v for k, v in sample.items() if k != 'events'})
    if len(manifest['samples']) != 672:
        raise ValueError('Expected exactly 672 SoulX sample traces')
    manifest['input_bytes'] = input_bytes
    manifest['compact_sha256'] = digest(output / 'traces.jsonl.gz')
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'samples': len(manifest['samples']), 'input_bytes': input_bytes,
                      'compact_bytes': (output / 'traces.jsonl.gz').stat().st_size,
                      'compact_sha256': manifest['compact_sha256']}, indent=2))


def synthetic(count):
    return [(None, count)] if count else []


def count(spans):
    return sum(length for _, length in spans)


def take(spans, start, end):
    result, offset = [], 0
    for origin, length in spans:
        left, right = max(start, offset), min(end, offset + length)
        if left < right:
            result.append((None if origin is None else origin + left - offset, right - left))
        offset += length
    if count(result) != end - start:
        raise ValueError('Ledger slice outside the recorded audio range')
    return result


def real_range(spans):
    real = [(start, length) for start, length in spans if start is not None]
    if not real:
        return None
    if any(a + length != b for (a, length), (b, _) in zip(real, real[1:])):
        return None
    return real[0][0], real[-1][0] + real[-1][1]


class Ledger:
    """Replay only frozen model buffer lengths and reset branches, never inference."""

    def __init__(self, sample):
        self.sample = sample
        self.generation, self.previous_packet_end = -1, 0
        self.reset()
        self.groups = defaultdict(list)
        self.coverage_epochs = Counter()
        self.observations, self.reasons = [], Counter()
        self.processing = None
        self.call_index = 0
        self.input_samples = round(next(v['input_seconds'] for v in sample['events'] if v['event'] == 'input_started') * 16000)

    def reset(self):
        self.generation += 1
        self.first = True
        self.cascade, self.turn = synthetic(51200), synthetic(25600)
        self.history = []
        self.speech, self.monitoring, self.wait, self.history_len = False, False, 0, 0

    def begin_step(self, event):
        if self.processing is not None:
            raise ValueError('Nested or unfinished controller step')
        end = event['end_sample']
        packet = self.previous_packet_end
        if end <= packet or end - packet > 2560:
            raise ValueError('Packet sample positions are not ordered chunks')
        # Frozen reset drops old lookahead. On the next process call the first
        # 640 samples of process_chunk come from synthetic initialization.
        if self.first:
            spans = synthetic(640) + [(packet, 1920)]
        else:
            spans = [(packet - 640, 2560)]
        self.chunk = spans
        self.previous_packet_end = end
        self.first = False
        self.cascade += spans
        self.processing = {'end_sample': end, 'raw_state': None, 'pending_asr': None,
                           'raw_seen': False, 'before_raw_calls': 0, 'after_raw_calls': 0}

    def observe(self, event, begin):
        if begin['available_end_sample'] != self.processing['end_sample']:
            raise ValueError('ASR result belongs to a different input packet')
        if begin['audio_samples'] != count(self.cascade if not self.processing['raw_seen'] else self.expected_turn()):
            raise ValueError(f'ASR input length disagrees with reconstructed ledger: {begin["audio_samples"]}')
        spans = self.cascade if not self.processing['raw_seen'] else self.expected_turn()
        self.processing['before_raw_calls' if not self.processing['raw_seen'] else 'after_raw_calls'] += 1
        self.call_index += 1
        coverage = real_range(spans)
        row = {'call_index': self.call_index, 'source_index': self.call_index - 1,
               'event_id': f'{self.sample["subset"]}:{self.sample["id"]}:asr:{self.call_index}',
               'call_kind': 'window' if not self.processing['raw_seen'] else 'turn',
               'returned_at': event['time'], 'text': event['text'], 'tokens': words(event['text']),
               'audio_start': coverage[0] if coverage else None,
               'audio_end': coverage[1] if coverage else None,
               'generation': self.generation, 'packet_end': self.processing['end_sample'],
               'audio_samples': begin['audio_samples'], 'asr_seconds': event['generate_seconds']}
        self.observations.append(row)
        if self.processing['end_sample'] > self.input_samples:
            self.reasons['after_original_input_end'] += 1
        elif coverage is None:
            self.reasons['synthetic_or_noncontiguous'] += 1
        else:
            base = (f'{self.sample["subset"]}/{self.sample["id"]}', self.generation, coverage[0])
            key = (*base, self.coverage_epochs[base])
            if self.groups[key] and coverage[1] < self.groups[key][-1]['audio_end']:
                # A final recognition can omit recent idle frames. It is not a
                # fresh expanding-window vote and must start a new evidence epoch.
                self.reasons['coverage_regression_boundaries'] += 1
                self.coverage_epochs[base] += 1
                key = (*base, self.coverage_epochs[base])
            self.groups[key].append(row)

    def expected_turn(self):
        state = self.processing['raw_state']
        if state == '<|user_complete|>' and self.speech:
            return self.turn + self.chunk
        if state == '<|user_idle|>' and self.monitoring and self.wait + 1 >= 8 and self.speech:
            return self.turn
        raise ValueError('Unexpected whole-turn ASR branch in frozen state machine')

    def finish_step(self, event):
        step = self.processing
        if step is None or not step['raw_seen'] or step['pending_asr'] is not None:
            raise ValueError('Incomplete controller or ASR trace')
        state, result = step['raw_state'], event['result']
        if step['before_raw_calls'] > 1 or step['after_raw_calls'] > 1:
            raise ValueError('Unexpected number of model ASR calls in one chunk')
        if bool(step['after_raw_calls']) != (result['state'] == 'speak'):
            raise ValueError('Whole-turn ASR calls do not match the service completion branch')
        # Every infer call trims cascade_buffer after optional recognition.
        if count(self.cascade) > 51200:
            self.cascade = take(self.cascade, count(self.cascade) - 51200, count(self.cascade))
        far_field = state == '<|user_nonidle|>' and result['state'] == 'idle'
        if far_field:
            if self.speech:
                raise ValueError('Far-field reset contradicts speech_detected')
            self.reasons['far_field_resets'] += 1
            self.reset()
        else:
            self.history_len += 1
            self.history = (self.history + [(self.chunk, state)])[-5:]
            if state == '<|user_nonidle|>':
                self.speech = True
                if self.monitoring:
                    self.monitoring, self.wait = False, 0
                previous = []
                for spans, old_state in reversed(self.history[:-1]):
                    if old_state not in ('<|user_idle|>', '<|user_backchannel|>'):
                        break
                    previous.append(spans)
                self.turn += [span for block in reversed(previous) for span in block] + self.chunk
                if result['state'] != 'nonidle':
                    raise ValueError('Unexpected service result for accepted nonidle')
            elif state == '<|user_incomplete|>':
                self.monitoring, self.wait = True, 0
                self.turn += self.chunk
            elif state == '<|user_complete|>':
                self.reasons['complete_resets'] += 1
                self.reset()
            elif state == '<|user_backchannel|>':
                if not self.speech:
                    self.reasons['backchannel_resets'] += 1
                    self.reset()
                if self.monitoring:
                    self.wait = 1
            elif state == '<|user_idle|>':
                if self.monitoring:
                    self.wait += 1
                    if self.wait >= 8 and self.speech:
                        self.reasons['wait_fallback_resets'] += 1
                        self.reset()
                if self.history_len > 200 and not self.monitoring and not self.speech:
                    self.reasons['long_idle_resets'] += 1
                    self.reset()
            else:
                self.reasons['unknown_resets'] += 1
                self.reset()
        self.processing = None

    def run(self):
        for event in self.sample['events']:
            kind = event['event']
            if kind == 'controller_begin':
                self.begin_step(event)
            elif kind == 'controller_raw':
                if self.processing is None or self.processing['raw_seen']:
                    raise ValueError('Raw state is not paired with one model step')
                self.processing.update(raw_seen=True, raw_state=event['state'])
            elif kind == 'asr_begin':
                if self.processing is None or self.processing['pending_asr']:
                    raise ValueError('ASR begin is not paired with a model step')
                self.processing['pending_asr'] = event
            elif kind == 'asr_result':
                begin = self.processing['pending_asr']
                if begin is None or begin['available_end_sample'] != event['available_end_sample']:
                    raise ValueError('ASR begin/result pairing mismatch')
                self.observe(event, begin)
                self.processing['pending_asr'] = None
            elif kind == 'controller_state':
                self.finish_step(event)
        if self.processing is not None:
            raise ValueError('Unfinished model trace')
        return self


def analyze(input_dir, output):
    manifest = json.loads((input_dir / 'manifest.json').read_text())
    compact = input_dir / 'traces.jsonl.gz'
    if digest(compact) != manifest['compact_sha256']:
        raise ValueError('Collected trace digest differs')
    output.mkdir(parents=True, exist_ok=False)
    valid, failures, excluded = [], [], Counter()
    per_sample, all_observations = [], 0
    with gzip.open(compact, 'rt', encoding='utf-8') as source:
        samples = [json.loads(line) for line in source]
    for sample in samples:
        try:
            ledger = Ledger(sample).run()
            all_observations += len(ledger.observations)
            excluded.update(ledger.reasons)
            eligible = []
            for key, rows in ledger.groups.items():
                if len({row['audio_end'] for row in rows}) < 3:
                    excluded['short_groups'] += 1
                    continue
                group = analyze_group(key, rows)
                group['coverage_epoch'] = key[3]
                for track in group['tracks']:
                    evidence = final_evidence(rows, track['last_revision_call'], 3)
                    track['confirmed_three'] = bool(evidence)
                    first = next(row for row in rows if row['call_index'] == track['first_slot_call'])
                    stable = next(row for row in rows if row['call_index'] == track['last_revision_call'])
                    confirmation = evidence[-1] if evidence else None
                    track['confirmation_call'] = confirmation['call_index'] if confirmation else None
                    track['confirmation_delay_from_first_slot_ms'] = (confirmation['returned_at'] - first['returned_at']) * 1000 if confirmation else None
                    track['confirmation_delay_from_final_text_ms'] = (confirmation['returned_at'] - stable['returned_at']) * 1000 if confirmation else None
                    track['confirmation_extra_updates'] = confirmation['call_index'] - first['call_index'] if confirmation else None
                group['subset'], group['sample_id'] = sample['subset'], sample['id']
                eligible.append(group)
            valid.extend(eligible)
            per_sample.append({'subset': sample['subset'], 'id': sample['id'],
                               'native_asr_calls': len(ledger.observations), 'eligible_groups': len(eligible),
                               'reconstruction': 'length_and_branch_validated'})
        except Exception as exc:
            failures.append({'subset': sample['subset'], 'id': sample['id'],
                             'error': f'{type(exc).__name__}: {exc}'})
    result = {'schema': 'fdb-asr-stability-v1', 'source_report_sha256': manifest['report_sha256'],
              'analysis_source_sha256': digest(Path(__file__)),
              'prefix_analysis_source_sha256': digest(Path(__file__).with_name('analyze_asr_stability.py')),
              'compact_sha256': manifest['compact_sha256'], 'sample_count': len(samples),
              'validated_samples': len(per_sample), 'failed_samples': failures,
              'native_asr_calls_validated': all_observations,
              'exclusions_and_reset_counts': dict(excluded),
              'overall': summarize(valid),
              'by_subset': {subset: summarize([g for g in valid if g['subset'] == subset]) for subset in SUBSETS},
              'samples': per_sample, 'groups': valid}
    result['confirmation_policies'] = confirmation_policies(valid)
    result['confirmation_policies_by_subset'] = {
        subset: confirmation_policies([g for g in valid if g['subset'] == subset]) for subset in SUBSETS}
    result['common_cohort'] = common_cohort(result['confirmation_policies'])
    (output / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    printable = {k: v for k, v in result.items() if k not in ('groups', 'samples', 'confirmation_policies', 'confirmation_policies_by_subset')}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


def common_cohort(policies):
    """Compare two and three confirmations on exactly the same prefix endpoints."""
    def key(row):
        return row['case'], row['generation'], row['coverage_epoch'], row['audio_start'], row['prefix_words']
    doubles = {key(row): row for row in policies['2']['rows']}
    triples = policies['3']['rows']
    paired = [doubles[key(row)] for row in triples]
    return {'n': len(triples),
            'two_wait_ms': distribution([row['wait_ms'] for row in paired]),
            'three_wait_ms': distribution([row['wait_ms'] for row in triples]),
            'two_after_final_ms': distribution([row['after_final_ms'] for row in paired]),
            'three_after_final_ms': distribution([row['after_final_ms'] for row in triples]),
            'two_extra_updates': distribution([row['extra_updates'] for row in paired]),
            'three_extra_updates': distribution([row['extra_updates'] for row in triples]),
            'three_minus_two_ms': distribution([row['wait_ms'] - doubles[key(row)]['wait_ms'] for row in triples])}


def final_evidence(rows, final_start_call, required):
    """Require genuinely consecutive model ASR calls, each with fresh audio."""
    run = []
    for row in rows:
        if row['call_index'] < final_start_call:
            continue
        if run and (row['source_index'] != run[-1]['source_index'] + 1
                    or row['audio_end'] <= run[-1]['audio_end']):
            run = []
        run.append(row)
        if len(run) >= required:
            return run[-required:]
    return []


def confirmation_policies(groups):
    """Separate first-hypothesis waiting from extra evidence after final text appears."""
    result = {}
    for required in (2, 3):
        confirmed, wait, revision, extra, after_final, unfinished = [], [], [], [], [], 0
        for group in groups:
            rows = group['observations']
            by_call = {row['call_index']: row for row in rows}
            for track in group['tracks']:
                final_start = by_call[track['last_revision_call']]
                evidence = final_evidence(rows, final_start['call_index'], required)
                if not evidence:
                    unfinished += 1
                    continue
                confirmation = evidence[-1]
                first = by_call[track['first_slot_call']]
                wait.append((confirmation['returned_at'] - first['returned_at']) * 1000)
                revision.append((final_start['returned_at'] - first['returned_at']) * 1000)
                after_final.append((confirmation['returned_at'] - final_start['returned_at']) * 1000)
                extra.append(confirmation['call_index'] - first['call_index'])
                confirmed.append({'case': group['case'], 'generation': group['generation'],
                                  'coverage_epoch': group['coverage_epoch'], 'audio_start': group['audio_start'],
                                  'prefix_words': track['prefix_words'], 'final_prefix': track['final_prefix'],
                                  'first_call': first['call_index'], 'last_revision_call': final_start['call_index'],
                                  'confirmation_call': confirmation['call_index'], 'wait_ms': wait[-1],
                                  'last_revision_ms': revision[-1], 'after_final_ms': after_final[-1],
                                  'extra_updates': extra[-1]})
        result[str(required)] = {'confirmed_endpoints': len(confirmed), 'insufficient_followup_endpoints': unfinished,
                                 'wait_from_initial_hypothesis_ms': distribution(wait),
                                 'last_revision_from_initial_ms': distribution(revision),
                                 'extra_wait_after_final_form_ms': distribution(after_final),
                                 'extra_updates_from_initial': distribution(extra), 'rows': confirmed}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('collect', 'analyze'))
    parser.add_argument('--root', type=Path)
    parser.add_argument('--input-dir', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'collect':
        collect(args.root, args.output_dir)
    else:
        analyze(args.input_dir, args.output_dir)


if __name__ == '__main__':
    main()
