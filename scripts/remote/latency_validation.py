"""Measure paired cache inference and reconstruct response latency milestones."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import time
import uuid


def stats(values):
    """Summarize observed values without treating missing responses as zero."""
    values = sorted(v for v in values if v is not None)
    def percentile(p):
        if not values:
            return None
        position = (len(values) - 1) * p
        low = int(position)
        high = min(low + 1, len(values) - 1)
        return values[low] + (values[high] - values[low]) * (position - low)
    return {'n': len(values), 'mean': statistics.mean(values) if values else None,
            'p50': percentile(.5), 'p95': percentile(.95)}


def logged_events(directory):
    """Read only explicitly serialized, identified observation rows."""
    rows = []
    for path in directory.rglob('*.latency.log'):
        for line in path.read_text().splitlines():
            if line.startswith(('latency_tts ', 'latency_answer ', 'latency_model_client ')):
                kind, payload = line.split(' ', 1)
                rows.append({'source': kind, **json.loads(payload)})
    return rows


def response_rows(report, timeline, diagnostics, models):
    """Join exact response/request identities and retain absent milestones."""
    sid = report['session_id']
    origin = report['client_origin_monotonic']
    input_start = origin + report.get('input_start_seconds', 0)
    events = report['events']
    micro = [r for r in timeline if r['event_type'] == 'duplex.micro_turn_ready']
    responses = {r['response_id']: r for r in report['client_measurements']['responses']}
    for row in timeline:
        if row['event_type'] == 'turn.tts_start_requested' and row['response_id']:
            responses.setdefault(row['response_id'], {'response_id': row['response_id']})
    rows = []
    for rid, response in responses.items():
        texts = [r for r in diagnostics if r.get('response_id') == rid and r['source'] == 'latency_answer']
        texts.sort(key=lambda r: r['at_monotonic'])
        request_id = texts[0]['request_id'] if texts else None
        tick = next((r for r in micro if r['request_id'] == request_id), None)
        model = next((r for r in models if r['session_id'] == sid and r['request_id'] == request_id), None)
        ticks = [r for r in micro if tick and r['monotonic_timestamp'] <= tick['monotonic_timestamp']]
        last_change = None
        previous = ''
        for r in ticks:
            if r['text'] != previous:
                last_change = r
                previous = r['text']
        asr = [r for r in timeline if last_change and r['event_type'] in ('asr.result_partial', 'asr.result_final')
               and r['text'] == last_change['text']
               and r['monotonic_timestamp'] <= last_change['monotonic_timestamp']]
        # Match the published ASR prefix; no nearest-neighbour attribution.
        asr_visible = max((r['monotonic_timestamp'] for r in asr), default=None)
        tts = [r for r in diagnostics if r.get('response_id') == rid and r['source'] == 'latency_tts']
        requests = sorted((r for r in tts if r['kind'] == 'request'), key=lambda r: r['at_monotonic'])
        pcm = sorted((r for r in tts if r['kind'] == 'pcm'), key=lambda r: r['at_monotonic'])
        client = [r for r in events if isinstance(r.get('data'), dict) and r['data'].get('response_id') == rid]
        def client_time(kind):
            return next((origin + r['seconds'] for r in client if r['action'] == kind), None)
        audible = next((r['data']['audible_monotonic'] for r in client if r['action'] == 'audible_proxy'), None)
        anchors = report['client_measurements']['anchors']
        anchor = anchors.get('turn_taking', anchors.get('interruption_end'))
        marks = {
            'anchor': input_start + anchor if anchor is not None else None,
            'asr_visible': asr_visible,
            'text_sampled': last_change['monotonic_timestamp'] if last_change else None,
            'response_tick': tick['monotonic_timestamp'] if tick else None,
            'model_started': model['model_started_monotonic'] if model else None,
            'first_text': texts[0]['at_monotonic'] if texts else None,
            'tts_submit': requests[0]['at_monotonic'] if requests else None,
            'tts_pcm': pcm[0]['at_monotonic'] if pcm else None,
            'client_pcm': client_time('pcm_received'),
            'audible': audible,
        }
        pairs = list(zip(marks, list(marks)[1:]))
        parts = {a + '_to_' + b: marks[b] - marks[a] if marks[a] is not None and marks[b] is not None else None
                 for a, b in pairs}
        total = audible - marks['anchor'] if audible is not None and marks['anchor'] is not None else None
        complete = all(v is not None for v in parts.values())
        first_control = next((r['monotonic_timestamp'] for r in timeline
                              if r['event_type'] == 'duplex.protocol_parsed' and r['request_id'] == request_id), None)
        rows.append({'session_id': sid, 'response_id': rid, 'request_id': request_id,
            'milestones': marks, 'parts_seconds': parts, 'total_audible_seconds': total,
            'decomposition_residual_seconds': total - sum(parts.values()) if complete else None,
            'tts_first_compute_seconds': pcm[0].get('compute_seconds') if pcm else None,
            'model_first_token_seconds': model.get('model_to_first_token_seconds') if model else None,
            'model_first_control_seconds': first_control - marks['model_started'] if first_control and model else None,
            'model_seconds': model.get('seconds') if model else None,
            'cached_tokens': model.get('cached_tokens') if model else None,
            'cache_status': model.get('cache_status') if model else None,
            'playback_started_seconds': response.get('playback_started_seconds'),
            'audible_in_original_window': audible is not None and audible < input_start + report['input_audio_seconds'],
            'playback_gap_seconds': sum(r['data']['seconds'] for r in client if r['action'] == 'playback_gap'),
            'stop_requested': any(r['action'] == 'stop_tts' for r in client),
            'segments': [{k: r.get(k) for k in ('sequence', 'aggregation_seconds', 'request_seconds', 'compute_seconds', 'audio_seconds')}
                         for r in tts if r['kind'] in ('segment', 'pcm')]})
    return rows


def analyze(root):
    """Persist per-response data plus coverage-aware paired condition summaries."""
    models = [json.loads(line) for line in (root / 'model_trace.jsonl').read_text().splitlines()]
    all_rows, conditions = [], {}
    for condition in ('A_baseline', 'B_first300', 'C_first300_cache'):
        directory = root / condition / 'replay'
        diagnostics = logged_events(directory)
        rows, sessions = [], []
        for path in sorted((directory / 'fdb').rglob('a4_report.json')):
            report = json.loads(path.read_text())
            timeline = [json.loads(line) for line in Path(report['timeline_path']).read_text().splitlines()]
            sample = str(path.parent.relative_to(directory / 'fdb'))
            response = response_rows(report, timeline, diagnostics, models)
            for r in response:
                r.update(condition=condition, sample=sample)
            rows.extend(response)
            anchor = report['client_measurements']['anchors'].get('turn_taking',
                report['client_measurements']['anchors'].get('interruption_end'))
            candidates = [r for r in response if anchor is not None
                and r['milestones']['first_text'] is not None
                and r['milestones']['first_text'] >= r['milestones']['anchor']]
            answer = min(candidates, key=lambda r: r['milestones']['first_text']) if candidates else None
            sessions.append({'sample':sample, 'session_id':report['session_id'], 'anchor_seconds':anchor,
                'selected_response_id': answer['response_id'] if answer else None,
                'total_audible_seconds': answer['total_audible_seconds'] if answer else None,
                'audible_in_original_window': answer['audible_in_original_window'] if answer else False,
                'protocol_errors':report['timeline']['protocol_errors'], 'transport_status':report['status']})
        selected_ids = {s['selected_response_id'] for s in sessions if s['audible_in_original_window']}
        selected = [r for r in rows if r['response_id'] in selected_ids]
        conditions[condition] = {'sessions':sessions, 'response_count':len(rows),
            'anchored_sessions':sum(s['anchor_seconds'] is not None for s in sessions),
            'original_window_replies':len(selected),
            'total_audible_seconds':stats([r['total_audible_seconds'] for r in selected]),
            'parts_seconds':{k:stats([r['parts_seconds'][k] for r in selected])
                             for k in (rows[0]['parts_seconds'] if rows else {})}}
        all_rows.extend(rows)
    output = {'conditions':conditions, 'responses':all_rows,
        'scope':'fixed FDB development subset; simulated playback; no official semantic score',
        'units':'seconds; same-node monotonic clock', 'audible_threshold_dbfs':-45}
    (root/'latency_breakdown.json').write_text(json.dumps(output,indent=2)+'\n')
    with (root/'latency_responses.csv').open('w') as stream:
        flat = [{k:v for k,v in r.items() if k not in ('parts_seconds','milestones','segments')} | r['parts_seconds'] for r in all_rows]
        if flat:
            writer = csv.DictWriter(stream,fieldnames=list(flat[0]))
            writer.writeheader()
            writer.writerows(flat)
    print(json.dumps({'conditions':conditions}),flush=True)


def probe(root, url):
    """Replay identical successive prompt IDs, preserving numerical divergences."""
    import requests
    trace = [json.loads(line) for line in (root/'model_trace.jsonl').read_text().splitlines()]
    groups = {}
    for r in trace:
        if r['cache_status'] == 'disabled' and r.get('session_id'):
            groups.setdefault(r['session_id'],[]).append(r)
    groups = sorted(groups.values(),key=lambda rows:max(r['prompt_tokens'] for r in rows))
    chosen = [groups[i] for i in sorted({0,len(groups)//2,len(groups)-1})]
    rows = []
    for group_index, group in enumerate(chosen):
        group = group[max(0,len(group)//2-6):len(group)//2+6]
        for repetition in range(3):
            outputs = {}
            for enabled in (False, True):
                sid = 'probe_' + uuid.uuid4().hex
                for index, source in enumerate(group):
                    body = dict(prompt_token_ids=source['prompt_token_ids'],max_new_tokens=64,
                        session_id=sid,use_cache=enabled,request_id=f'{group_index}_{repetition}_{index}_{enabled}')
                    began = time.monotonic()
                    response = requests.post(url+'/generate_ids',json=body,timeout=120)
                    response.raise_for_status()
                    events = [json.loads(line) for line in response.text.splitlines()]
                    if any('error' in e for e in events):
                        raise RuntimeError(events)
                    end = next(e for e in events if 'finish_reason' in e)
                    if not enabled:
                        outputs[index] = end['token_ids']
                    rows.append({'group':group_index,'repeat':repetition,'index':index,'use_cache':enabled,
                        'ids_match_uncached':end['token_ids'] == outputs[index],
                        'wall_seconds':time.monotonic()-began, **end['metrics']})
                requests.delete(url+'/cache/'+sid,timeout=10).raise_for_status()
    summary = {}
    for enabled in (False, True):
        for status in ('disabled','cold','hit','prefix_invalidated'):
            subset = [r for r in rows if r['use_cache']==enabled and r['cache_status']==status]
            if subset:
                summary[f'{enabled}_{status}'] = {k:stats([r[k] for r in subset]) for k in
                    ('prompt_tokens','cached_tokens','model_to_first_token_seconds','seconds')}
    result = {'rows':rows,'summary':summary,'all_ids_match':all(r['ids_match_uncached'] for r in rows)}
    (root/'cache_probe.json').write_text(json.dumps(result,indent=2)+'\n')
    if not result['all_ids_match']:
        print('CACHE_NUMERICAL_DIVERGENCE: inspect per-request rows',flush=True)


def main():
    """Dispatch fixed-ID probing or offline decomposition."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('probe','analyze'))
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--url')
    args = parser.parse_args()
    if args.command == 'probe':
        probe(args.root,args.url)
    else:
        analyze(args.root)


if __name__ == '__main__':
    main()
