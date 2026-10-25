"""Re-score saved shadow traces with explicit uncertainty and causal annotations."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import re

from score_textturn import metric, outcome_metric

RULE_VERSION = 'textturn-trace-v2-causal-unknown-20261025'
BACKCHANNELS = {'hmm', 'isee', 'right', 'mmhm', 'okay'}
INCOMPLETE = {
    'how', 'how can', 'how do', 'how does', 'how is', 'how are', 'what', 'what is',
    'what are', 'what can', 'what do', 'what does', 'can you', 'could you', 'why',
    'why is', 'why are', 'why do', 'why does', 'are there', 'is there', 'do you',
}


def normalize(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))


def canonical_hash(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(value.encode()).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def is_backchannel(text):
    return ''.join(re.findall(r'[a-z]+', text.casefold())) in BACKCHANNELS


def is_interruption(text):
    """Recognize only unambiguous prefixes from the frozen command inventory."""
    return bool(re.fullmatch(r'(?:please )?(?:stop|pause)(?: for(?: a(?: moment)?)?)?|wait(?: stop)?', normalize(text)))


def valid_result(result):
    visible = result.get('visible', {})
    legal = {'Listen': {'keep', 'start'}, 'Speak': {'keep', 'stop'}}
    return (not result.get('error') and result.get('action') in legal.get(visible.get('state'), set())
            and isinstance(result.get('returned_at'), (int, float))
            and isinstance(result.get('started_at'), (int, float))
            and result['returned_at'] >= result['started_at'])


def validated_review(review, contexts, results):
    """Bind judgments to recorded inputs; reject timestamps supplied by the reviewer."""
    if not review:
        return {}, None
    if not review.get('reviewer') or not review.get('reason'):
        raise ValueError('Semantic review requires reviewer and causal rationale')
    by_step = {r['window']['last_step_seq']: r for r in results}
    decisions = {}
    for item in review.get('decisions', []):
        step = item['last_step_seq']
        if step in decisions or step not in by_step:
            raise ValueError('Duplicate or nonexistent reviewed control snapshot')
        result = by_step[step]
        if not result.get('visible') or canonical_hash(result['visible']) != item['visible_sha256']:
            raise ValueError('Reviewed visible input hash mismatch')
        if item['target'] not in ('keep', 'start', 'unknown') or result['visible']['state'] != 'Listen':
            raise ValueError('Semantic review supports Listen decisions only')
        if item['target'] == 'start' and result['visible'].get('observation') != '<|no-voice|>':
            raise ValueError('A reviewed start requires an actual turn-yield observation')
        decisions[step] = item['target']
    anchor = None
    anchor_item = review.get('anchor')
    if anchor_item:
        event = next((c for c in contexts if c['event_seq'] == anchor_item['context_event_seq']), None)
        if event is None or canonical_hash(event['text']) != anchor_item['text_sha256']:
            raise ValueError('Reviewed anchor must bind to an existing Context version')
        anchor = event
        if any(c['text'] == event['text'] and c['published_at'] < anchor['published_at'] for c in contexts):
            raise ValueError('Anchor must use the first visible identical Context text')
    return decisions, anchor


def score_trace(case, events, review=None):
    contexts = [e for e in events if e['kind'] == 'context_publish']
    steps = [e for e in events if e['kind'] == 'asr_online' and e.get('source_kind') == 'decode_step'
             and not e.get('eof_received')]
    results = [e for e in events if e['kind'] == 'control_result']
    valid = [r for r in results if valid_result(r)]
    malformed = len(results) - len(valid)
    decisions, reviewed_anchor = validated_review(review, contexts, results)
    reference = normalize(case['reference_text'])
    reference_matched = any(normalize(c['text']).startswith(reference) for c in contexts) if reference else False
    category = case['category']
    metric_name = {'smooth_question_pause': 'smooth', 'smooth_declarative': 'declarative',
                   'backchannel': 'backchannel_false_stop', 'interruption': 'interruption'}[category]
    actual_stops = sum(r['action'] == 'stop' for r in valid)
    actual_starts = sum(r['action'] == 'start' for r in valid)
    context_by_seq = {c['event_seq']: c for c in contexts}
    reads = {e['event_seq']: e for e in events if e['kind'] == 'context_read'}
    context_ok = all(seq in reads and reads[seq]['version'] == c['version'] and reads[seq]['text'] == c['text']
                     for seq, c in context_by_seq.items())
    closed = [e for e in events if e['kind'] == 'context_close']
    context_ok = context_ok and len(closed) == 1 and all(
        e['event_seq'] in reads and reads[e['event_seq']]['text'] == e['text'] for e in closed)
    base = {'case_id': case['case_id'], 'source_id': case['source_id'], 'metric': metric_name,
            'outcome': 'unknown', 'actual_error': False, 'reason': 'missing_semantic_review',
            'runtime_ok': bool(steps) and bool(results) and not malformed,
            'context_ok': context_ok, 'reference_matched': reference_matched,
            'actual_stop_count': actual_stops, 'actual_start_count': actual_starts,
            'control_error_count': malformed, 'anchor_at': None, 'response_ms': None}

    def finish(row, eligible, anchor=None, expected='keep', evidence_complete=True):
        row['anchor_at'] = anchor
        errors = [r for r in eligible if r['action'] not in (expected, 'keep')]
        if expected == 'keep':
            errors = [r for r in eligible if r['action'] != 'keep']
        if errors:
            row.update(outcome='fail', actual_error=True, reason='observed_forbidden_action')
        elif not evidence_complete:
            row['reason'] = 'incomplete_input_or_control_coverage'
        elif not eligible:
            row['reason'] = 'no_eligible_control_input'
        elif malformed:
            row['reason'] = 'control_error_or_missing_visible_input'
        elif expected == 'keep':
            row.update(outcome='pass', reason='observed_legal_keep')
        else:
            hits = [r for r in eligible if r['action'] == expected and anchor <= r['returned_at'] <= anchor + 1.]
            if hits:
                row.update(outcome='pass', reason='timely_action_on_eligible_input',
                           response_ms=(min(r['returned_at'] for r in hits) - anchor) * 1000)
            elif any(r['returned_at'] >= anchor + 1. for r in eligible):
                row.update(outcome='fail', reason='observed_deadline_miss')
            else:
                row['reason'] = 'deadline_not_fully_observed'
        return row

    opportunities = []
    if category == 'backchannel':
        recognized = [c for c in contexts if is_backchannel(c['text'])]
        anchor = recognized[0]['published_at'] if recognized else None
        relevant = [r for r in valid if r['visible']['state'] == 'Speak' and is_backchannel(r['visible']['user_text'])]
        # After a stop the later Listen state cannot erase the observed false stop.
        unresolved_stop = any(r['action'] == 'stop' and not is_backchannel(r['visible']['user_text']) for r in valid)
        opportunities.append(finish(base, relevant, anchor, evidence_complete=bool(recognized) and not unresolved_stop))
    elif category == 'interruption':
        recognized = [c for c in contexts if is_interruption(c['text'])]
        anchor = recognized[0]['published_at'] if recognized else None
        relevant = [r for r in valid if r['visible']['state'] == 'Speak' and is_interruption(r['visible']['user_text'])]
        if anchor is None:
            base['reason'] = 'no_unambiguous_interruption_visible'
            opportunities.append(base)
        else:
            premature = any(r['action'] == 'stop' and not is_interruption(r['visible']['user_text']) for r in valid)
            opportunities.append(finish(base, relevant, anchor, 'stop', not premature))
    else:
        annotated = [(r, decisions.get(r['window']['last_step_seq'])) for r in valid if r['visible']['state'] == 'Listen']
        forbidden = any(target == 'keep' and r['action'] == 'start' for r, target in annotated)
        if forbidden:
            base.update(outcome='fail', actual_error=True, reason='reviewed_forbidden_start')
        elif reviewed_anchor is not None:
            anchor_at = reviewed_anchor['published_at']
            eligible = [r for r, target in annotated if target == 'start'
                        and r['window'].get('asr_prefix_version', -1) >= reviewed_anchor['asr_prefix_version']
                        and r['window'].get('text', '').startswith(reviewed_anchor['text'])
                        and r['started_at'] >= anchor_at]
            all_reviewed = all(target in ('keep', 'start') for r, target in annotated
                               if r['started_at'] <= anchor_at + 1.)
            base = finish(base, eligible, anchor_at, 'start', all_reviewed)
        opportunities.append(base)
        if category == 'smooth_question_pause':
            pause = dict(base, metric='pause_false_start', outcome='unknown', actual_error=False,
                         anchor_at=None, response_ms=None, reason='no_reviewable_incomplete_prefix')
            relevant = [r for r in valid if r['visible']['state'] == 'Listen'
                        and normalize(r['visible']['user_text']) in INCOMPLETE
                        and r['visible']['observation'] == '<|no-voice|>']
            opportunities.append(finish(pause, relevant))

    telemetry = {'control_ms': [r['control_ms'] for r in results if isinstance(r.get('control_ms'), (int, float))],
                 'aggregation_wait_ms': [r['window']['aggregation_wait_ms'] for r in results
                                         if isinstance(r.get('window', {}).get('aggregation_wait_ms'), (int, float))],
                 'planned_windows': sum(e['kind'] == 'control_window' for e in events),
                 'merged_windows': sum(r.get('window', {}).get('merged_windows', 0) for r in results)}
    return opportunities, telemetry


def threshold_verdict(value, minimum_groups=100, negative=False):
    if not value['planned']:
        return 'insufficient_evidence'
    lower, upper = value['planned_error_bounds' if negative else 'planned_success_bounds']
    if negative and lower > .15 or not negative and upper < .8:
        return 'not_passed'
    if value['adjudicated'] < minimum_groups:
        return 'insufficient_evidence'
    if negative and upper <= .15 or not negative and lower >= .8:
        return 'pass_initial_screen'
    return 'insufficient_evidence' if value['unknown'] else 'not_passed'


def summarize(opportunities, telemetry):
    result = {'schema_version': 2, 'rule_version': RULE_VERSION, 'metrics': {}}
    for name in ('smooth', 'declarative', 'interruption', 'pause_false_start', 'backchannel_false_stop'):
        selected = [r for r in opportunities if r['metric'] == name or name == 'smooth' and r['metric'] == 'declarative']
        value = outcome_metric(selected, negative='false_' in name)
        value['reason_counts'] = dict(Counter(r['reason'] for r in selected))
        # Smooth and declarative can share sources; do not mistake opportunities for independent groups.
        value['source_groups'] = len({r['source_id'] for r in selected})
        value['adjudicated_source_groups'] = len({r['source_id'] for r in selected if r['outcome'] != 'unknown'})
        value['verdict'] = threshold_verdict(value, negative='false_' in name)
        if value['adjudicated_source_groups'] < 100 and value['verdict'] == 'pass_initial_screen':
            value['verdict'] = 'insufficient_evidence'
        result['metrics'][name] = value
    primary = [r for r in opportunities if r['metric'] != 'pause_false_start']
    result['runtime'] = metric(sum(r['runtime_ok'] for r in primary), len(primary))
    result['context'] = metric(sum(r['context_ok'] for r in primary), len(primary))
    for name in ('control_ms', 'aggregation_wait_ms'):
        values = sorted(v for batch in telemetry for v in batch[name])
        result[name] = {'count': len(values), 'p95': values[math.ceil(.95 * len(values)) - 1] if values else None,
                        'max': values[-1] if values else None}
    verdicts = [v['verdict'] for v in result['metrics'].values()]
    result['conclusion'] = ('not_passed' if 'not_passed' in verdicts else
                            'insufficient_evidence' if 'insufficient_evidence' in verdicts else 'pass_initial_screen')
    if (result['runtime']['numerator'] < .95 * len(primary) or
            result['context']['numerator'] != len(primary) or
            result['control_ms']['p95'] is None or result['control_ms']['p95'] > 500):
        result['conclusion'] = 'not_passed'
    result['actual_actions'] = {name: sum(r[name] for r in primary)
                                for name in ('actual_stop_count', 'actual_start_count', 'control_error_count')}
    result['planned_windows'] = sum(t['planned_windows'] for t in telemetry)
    result['merged_windows'] = sum(t['merged_windows'] for t in telemetry)
    return result


def run(args):
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('Use a fresh scoring output; original results must be preserved')
    manifest = json.loads(args.manifest.read_text())
    cases = manifest['records']
    if len({c['case_id'] for c in cases}) != len(cases):
        raise ValueError('Duplicate planned case identity')
    reviews = json.loads(args.annotations.read_text()) if args.annotations else {}
    if set(reviews) - {c['case_id'] for c in cases}:
        raise ValueError('Review refers to an unplanned case')
    args.output.mkdir(parents=True, exist_ok=True)
    opportunities, telemetry, hashes = [], [], {}
    for case in cases:
        trace = args.traces / f"{case['case_id']}.jsonl"
        if trace.exists():
            hashes[trace.name] = file_hash(trace)
            with trace.open() as stream:
                events = [json.loads(line) for line in stream]
        else:
            hashes[trace.name] = None
            events = []
        rows, times = score_trace(case, events, reviews.get(case['case_id']))
        opportunities.extend(rows)
        telemetry.append(times)
    result = summarize(opportunities, telemetry)
    result['identity'] = {'manifest_sha256': file_hash(args.manifest), 'scorer_sha256': file_hash(__file__),
                          'annotations_sha256': file_hash(args.annotations) if args.annotations else None,
                          'trace_sha256': hashes, 'candidate_reselected': False, 'gpu_used': False}
    (args.output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    with (args.output / 'opportunities.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(opportunities[0]) if opportunities else [], lineterminator='\n')
        writer.writeheader()
        writer.writerows(opportunities)
    print(json.dumps({k: v for k, v in result.items() if k != 'identity'}, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--traces', type=Path, required=True)
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
