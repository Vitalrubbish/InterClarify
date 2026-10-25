"""Score pre-reviewed causal prefixes separately from action and overlap diagnostics."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from textturn_ultrachat_retest import score_case, write_json


def score(manifest, output):
    rows, groups = [], {}
    for case in manifest['cases']:
        path = output / 'traces' / (case['case_id'] + '.jsonl')
        row = score_case(case, path)
        events = [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []
        controls = [e for e in events if e['kind'] == 'control_result']
        reviews = case.get('prefix_reviews', [])
        row.update(semantic_opportunities=0, timely_1000=0, stop_output_1000=0,
                   natural_before_1000=0, not_speaking=0, observation_missing=0,
                   semantic_unknown_updates=0, reviewed_backchannel_false_stop=0,
                   reviewed_backchannel_stop_output=0, no_update_stop_output=0,
                   effective_no_update_stop=0, post_finish_start=0, tail_stop_output=0,
                   tail_effective_stop=0, normal_start_output=0, declarative_start_output=0,
                   pause_false_start_semantic=None, turn_taking_semantic=None,
                   declarative_turn_taking_semantic=None)
        details = []
        for review in reviews:
            if review['judgment'] != 'non_backchannel':
                continue
            update = next((e for e in events if e['kind'] == 'user_update' and
                           e['turn'] == review['turn'] and e['text'] == review['prefix']), None)
            detail = {**review, 'outcome': None, 'stop_latency_ms': None}
            if not update:
                detail['outcome'] = 'observation_missing'
                row['observation_missing'] += 1
            elif update['state'] != 'Speak':
                detail['outcome'] = 'not_speaking'
                row['not_speaking'] += 1
            else:
                row['semantic_opportunities'] += 1
                at = update['at']
                begin = max((e['at'] for e in events if e['kind'] == 'speak_begin' and e['at'] <= at), default=0.)
                generation = next((e['generation'] for e in events if e['kind'] == 'speak_begin' and e['at'] == begin), 1)
                ends = [e for e in events if e['kind'] in ('stop_applied', 'playback_complete') and
                        e['generation'] == generation and e['at'] >= at]
                end = min(ends, key=lambda e:e['at']) if ends else None
                outputs = [e for e in controls if e['turn'] == review['turn'] and
                           e['generation'] == generation and e['service']['action'] == 'stop' and
                           e['returned_at'] >= at]
                row['stop_output_1000'] += any((e['returned_at'] - at)*1000 <= 1000 for e in outputs)
                stops = [e for e in outputs if e['applied']]
                latency = (stops[0]['at'] - at)*1000 if stops else None
                detail['stop_latency_ms'] = latency
                if latency is not None and latency <= 1000:
                    detail['outcome'] = 'timely_effective_stop'
                    row['timely_1000'] += 1
                elif end and end['kind'] == 'playback_complete' and end['at'] - at < 1:
                    detail['outcome'] = 'natural_completion'
                    row['natural_before_1000'] += 1
                elif not events or events[-1]['at'] - at < 1:
                    detail['outcome'] = 'observation_missing'
                    row['observation_missing'] += 1
                else:
                    detail['outcome'] = 'late_stop' if latency is not None else 'missing_stop'
            details.append(detail)
        for e in events:
            if e['kind'] == 'user_update' and e['delta']:
                known = any(r['turn'] == e['turn'] and e['scheduled_at'] >= r['at'] and
                            r['judgment'] != 'unknown' and e['text'].startswith(r['prefix']) for r in reviews)
                row['semantic_unknown_updates'] += not known
        finished = False
        for e in events:
            if e['kind'] == 'finish':
                finished = True
            if e['kind'] != 'control_result':
                continue
            visible, action = e['visible'], e['service']['action']
            if action == 'start':
                row['post_finish_start'] += finished and e['applied']
                row['declarative_start_output'] += case['category'] == 'smooth_declarative'
                row['normal_start_output'] += case['category'] != 'smooth_declarative'
            if action != 'stop':
                continue
            backchannel = any(r['turn'] == e['turn'] and r['judgment'] == 'backchannel' and
                              visible['user_text'].startswith(r['prefix'].rstrip('.!?,')) for r in reviews)
            row['reviewed_backchannel_stop_output'] += backchannel
            row['reviewed_backchannel_false_stop'] += backchannel and e['applied']
            no_update = visible['observation'] == '<|no-voice|>'
            row['no_update_stop_output'] += no_update
            row['effective_no_update_stop'] += no_update and e['applied']
            tail = visible['assistant_generation_complete'] is True
            row['tail_stop_output'] += tail
            row['tail_effective_stop'] += tail and e['applied']
        row['semantic_details'] = details
        rows.append(row)
    for mode in manifest['protocol']['input_modes']:
        subset = [r for r in rows if r['mode'] == mode]
        totals = {'planned': len(subset)}
        for key in rows[0]:
            if key not in ('planned',) and all(type(r.get(key)) in (int, bool) for r in subset):
                totals[key] = sum(r[key] for r in subset)
        totals['semantic_timing_details'] = [d for r in subset for d in r['semantic_details']]
        totals['coverage_limits'] = manifest['review']['limitations']
        groups[mode] = totals
    write_json(output / 'external_case_scores.json', rows)
    write_json(output / 'external_summary.json', groups)
    with (output / 'external_cases.csv').open('w', newline='') as stream:
        fields = [k for k in rows[0] if not isinstance(rows[0][k], list)]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
    return groups


def score_fdb(manifest, run):
    """Keep legacy behavior measures and add strict wall-clock overlap diagnostics."""
    rows = []
    for case in manifest['records']:
        path = run / 'formal/traces' / (case['case_id'] + '.jsonl')
        events = [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []
        end = next((e for e in events if e['kind'] == 'case_end'), None)
        updates = [e['published_at'] for e in events if e['kind'] == 'context_publish' and e['text'].strip()]
        controls = sorted((e for e in events if e['kind'] == 'control_result' and e.get('state_after')),
                          key=lambda e:e['state_recorded_at'])
        episodes, start = [], None
        stop_count, new_text_stop = 0, 0
        for e in controls:
            at = e['action_returned_at']
            if e['action'] == 'start':
                start = at
            elif e['action'] == 'stop':
                stop_count += 1
                new_text_stop += bool(e['window']['user_delta'].strip())
                if start is not None:
                    episodes.append((start, at)); start = None
        if start is not None and end:
            episodes.append((start, end['ended_at']))
        overlap = max((max(0.,min(b,max(updates))-max(a,min(updates)))*1000
                       for a,b in episodes), default=0.) if updates else None
        rows.append({'case_id':case['case_id'], 'subset':case['subset'],
                     'runtime_success':bool(end and end['runtime_success']),
                     'stop_outputs':stop_count,'stop_with_new_text':new_text_stop,
                     'maximum_continuous_speak_overlap_ms':overlap,
                     'overlap_gt_960':overlap > 960 if overlap is not None else None})
    write_json(run / 'scoring/external_cases.json',rows)
    groups = {}
    for subset in ('candor_turn_taking','candor_pause_handling'):
        selected=[r for r in rows if r['subset']==subset]
        groups[subset]={'planned':50,'runtime_success':sum(r['runtime_success'] for r in selected),
          'stop_outputs':sum(r['stop_outputs'] for r in selected),
          'stop_with_new_text':sum(r['stop_with_new_text'] for r in selected),
          'overlap_gt_960':sum(r['overlap_gt_960'] is True for r in selected),
          'overlap_unknown':sum(r['overlap_gt_960'] is None for r in selected)}
    write_json(run / 'scoring/external_summary.json',groups)
    return groups
