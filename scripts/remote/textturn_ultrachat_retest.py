"""Freeze and replay causal UltraChat events with a single shadow action owner."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
from build_textturn_dataset import ControlTokenizer, strip_terminal


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            sha.update(block)
    return sha.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def fresh(path):
    path.mkdir(parents=True, exist_ok=False)


def freeze(args):
    protocol = json.loads(args.config.read_text())
    audio = json.loads((args.audio / 'manifest.json').read_text())
    assert audio['complete']
    with (args.data / 'timelines.jsonl').open() as stream:
        timelines = {r['source_id']: r for r in map(json.loads, stream) if r['split'] == 'test'}
    plans = {r['source_id']: r for r in json.loads((args.data / 'event_plans.json').read_text())
             if r['split'] == 'test'}
    sources = json.loads((args.data / 'source_records.json').read_text())
    selected = sorted(timelines, key=lambda key: hashlib.sha256(
        f"{protocol['seed']}|tt008|{key}".encode()).hexdigest())[:protocol['source_limit']]
    cases, failures = [], []
    assets = {str(p.resolve()): digest(p) for p in [args.config, args.audio / 'manifest.json',
        args.data / 'manifest.json', args.data / 'source_records.json',
        args.data / 'timelines.jsonl', args.data / 'event_plans.json']}
    for key in selected:
        timeline = timelines[key]['events']
        tail_ms = sum(e.get('window_ms', 0) for e in timeline if e['kind'] == 'playback_tail')
        wait_ms = sum(e.get('window_ms', 0) for e in timeline if e['kind'] == 'post_playback_wait')
        updates, turn_text = [], {}
        backchannel_closed = False
        for e in timeline:
            if e.get('phase_index') == 6 and not backchannel_closed:
                updates.append({'at': e['visible_ms'] / 1000, 'kind': 'turn_close',
                                'turn': 'phase5'})
                backchannel_closed = True
            if e['kind'] != 'user':
                continue
            phase = e['phase_index']
            turn = 'user0' if phase in (0, 2) else f'phase{phase}'
            category = plans[key]['phases'][phase].get('category', 'smooth')
            turn_text[turn] = turn_text.get(turn, '') + e['user_delta_raw']
            updates.append({'at': e['visible_ms'] / 1000, 'kind': 'user', 'turn': turn,
                            'text': turn_text[turn], 'category': category, 'version': e['step'],
                            'answer': 1 if phase < 10 else 3,
                            'trigger': plans[key]['phases'][phase].get('trigger_text')})
        end = max(e['visible_ms'] for e in timeline) / 1000
        cases.append({'case_id': key + '-clean', 'source_id': key, 'mode': 'clean_text_events',
                      'category': 'mixed', 'initial_state': 'Listen', 'history': [],
                      'answers': [sources[key]['texts'][1], sources[key]['texts'][3]],
                      'tail_ms': tail_ms, 'post_wait_ms': wait_ms, 'duration': end,
                      'updates': updates, 'steps': [i * .16 for i in range(1, round(end / .16) + 1)]})
        records = [r for r in audio['records'] if r['source_id'] == key]
        assert len(records) == 4, f'Expected all four frozen cases: {key}'
        for record in records:
            case = {'case_id': record['case_id'], 'source_id': key, 'mode': 'recorded_online_asr',
                    'category': record['category'], 'initial_state': 'Speak' if record['category'] in
                    ('backchannel', 'interruption') else 'Listen', 'history': record['history'],
                    'answers': [record['assistant_text'], record['assistant_text']],
                    'tail_ms': 480 * (1 + int(key) % 3), 'post_wait_ms': None,
                    'audio_sha256': record['sha256'], 'reference_text': record['reference_text']}
            try:
                path = args.audio / record['path']
                assert digest(path) == record['sha256'], 'Frozen audio changed'
                assets[str(path.resolve())] = record['sha256']
                path = args.traces / (record['case_id'] + '.jsonl')
                assets[str(path.resolve())] = digest(path)
                with path.open() as stream:
                    events = [e for e in map(json.loads, stream) if e['kind'] == 'asr_online'
                              and not e.get('eof_received')]
                steps = [e for e in events if e['source_kind'] == 'decode_step']
                assert steps and [e['step_seq'] for e in steps] == list(range(1, len(steps) + 1))
                origin = steps[0]['published_at'] - steps[0]['nominal_audio_end_ms'] / 1000
                case['origin_rule'] = 'first_decode_publication_minus_nominal_audio_end'
                case['steps'] = [e['published_at'] - origin for e in steps]
                case['duration'] = case['steps'][-1]
                case['updates'] = [{'at': e['published_at'] - origin, 'kind': 'user', 'turn': 'user0',
                    'text': e['text'], 'version': e['prefix_version'], 'category': record['category'],
                    'answer': 1, 'trigger': plans[key]['phases'][13].get('trigger_text')
                    if record['category'] == 'interruption' else None}
                    for e in events if e['source_kind'] == 'transcript' and e['text']]
            except Exception as exc:
                case.update(freeze_error=repr(exc), steps=[], updates=[], duration=0)
                failures.append({'case_id': case['case_id'], 'error': repr(exc)})
            cases.append(case)
    fresh(args.output)
    write_json(args.output / 'manifest.json', {'protocol': protocol, 'protocol_sha256': digest(args.config),
        'sources': selected, 'planned_cases_per_configuration': len(cases), 'cases': cases,
        'assets': assets, 'freeze_failures': failures, 'complete': True,
        'history_use': 'TT-001 test and TT-004 diagnosis; regression, not a new blind test',
        'asr_mode': 'recorded online publication timestamps; no new ASR execution'})
    print(json.dumps({'frozen': len(cases), 'failures': len(failures),
                      'manifest_sha256': digest(args.output / 'manifest.json')}), flush=True)


class ReplayState:
    """Own causal prefixes, user-turn offsets and simulated output lifecycle."""

    def __init__(self, case, tokenizer, config, emit):
        self.case, self.tokenizer, self.emit = case, tokenizer, emit
        self.period, self.width = config['control_ms'] / 1000, config['assistant_tokens']
        self.history = deepcopy(case['history'])
        self.state = case['initial_state']
        self.turn, self.text, self.offset, self.category = None, '', 0, 'none'
        self.answer_index, self.version = 0, 0
        self.visible, self.chunks, self.count = '', [], 0
        self.release_at, self.complete_at, self.close_at = None, None, None
        self.generation = 0
        self.empty_streak = 0
        if self.state == 'Speak':
            self.begin(0.)

    def begin(self, at):
        self.generation += 1
        self.state, self.visible, self.count = 'Speak', '', 0
        self.chunks = list(self.tokenizer.chunks(self.case['answers'][self.answer_index],
                                               self.width, merge_terminal=False))
        self.release_at = at + self.period
        self.complete_at = None
        self.close_at = at + len(self.chunks) * self.period + self.case['tail_ms'] / 1000
        self.emit('speak_begin', at=at, generation=self.generation)

    def advance(self, at):
        while self.state == 'Speak' and self.count < len(self.chunks) and self.release_at <= at + 1e-9:
            due = self.release_at
            piece = self.chunks[self.count]
            self.visible += piece
            self.count += 1
            self.release_at += self.period
            self.emit('assistant_publish', at=at, scheduled_at=due, generation=self.generation,
                      delta=piece, visible=self.visible, delta_tokens=len(self.tokenizer.encode(piece)),
                      cumulative_tokens=len(self.tokenizer.encode(self.visible)),
                      sha256=hashlib.sha256(self.visible.encode()).hexdigest())
            if self.count == len(self.chunks):
                self.complete_at = due
                self.emit('generation_complete', at=at, scheduled_at=due, generation=self.generation)
        if self.state == 'Speak' and at + 1e-9 >= self.close_at:
            self.history.append({'role': 'assistant', 'text': self.visible})
            self.state = 'Listen'
            self.emit('playback_complete', at=at, scheduled_at=self.close_at,
                      generation=self.generation)

    def update(self, event, at):
        if event['kind'] == 'turn_close':
            if self.turn == event['turn']:
                remaining = self.text[self.offset:]
                if remaining:
                    self.history.append({'role': 'user', 'text': remaining})
                self.offset = len(self.text)
                self.category = 'none'
                self.emit('user_turn_close', at=at, turn=self.turn)
            return
        if event['turn'] != self.turn:
            remaining = self.text[self.offset:]
            if remaining:
                self.history.append({'role': 'user', 'text': remaining})
            self.turn, self.text, self.offset = event['turn'], '', 0
        if not event['text'].startswith(self.text):
            raise ValueError('Published user prefix rewrote committed text')
        delta = event['text'][len(self.text):]
        self.text, self.version, self.category = event['text'], event['version'], event['category']
        self.answer_index = 0 if event['answer'] == 1 else 1
        self.emit('user_update', at=at, scheduled_at=event['at'], turn=self.turn, delta=delta,
                  text=self.text, state=self.state, category=self.category, version=self.version,
                  trigger_visible=bool(event.get('trigger') and event['trigger'].casefold() in self.text.casefold()))

    def snapshot(self, delta, windows):
        observation = strip_terminal(delta) or '<|no-voice|>'
        self.empty_streak = self.empty_streak + windows if observation == '<|no-voice|>' else 0
        return {'history': deepcopy(self.history), 'user_text': strip_terminal(self.text[self.offset:]),
                'assistant_visible': self.visible if self.state == 'Speak' else '', 'state': self.state,
                'observation': observation, 'window_ms': round(windows * self.period * 1000),
                'consecutive_no_voice_windows': self.empty_streak,
                'assistant_generation_complete': self.count == len(self.chunks) if self.state == 'Speak' else None,
                'cot': ''}

    def apply(self, action, snapshot, generation, at, turn=None, committed_end=None):
        legal = ('keep', 'stop') if snapshot['state'] == 'Speak' else ('keep', 'start')
        if action not in legal:
            raise ValueError('Illegal controller action')
        if action == 'keep':
            return True
        if self.state != snapshot['state'] or self.generation != generation:
            self.emit('stale_action', at=at, action=action)
            return False
        if action == 'start':
            if self.turn != turn:
                self.emit('stale_action', at=at, action=action)
                return False
            # Commit only the prefix actually observed by this request.
            consumed = len(self.text) if committed_end is None else committed_end
            if consumed > self.offset:
                self.history.append({'role': 'user', 'text': self.text[self.offset:consumed]})
            self.offset = consumed
            self.begin(at)
        else:
            self.history.append({'role': 'assistant', 'text': self.visible,
                                 'interrupted': True, 'generated_only': True})
            self.state = 'Listen'
            self.emit('stop_applied', at=at, generation=self.generation)
        return True


class DuplexReplayState(ReplayState):
    """Expose versioned generated/played output and exactly one terminal per output."""

    def __init__(self, case, tokenizer, config, emit):
        self.pending_events, self.latest_terminal = [], None
        self.played, self.output_id, self.runtime_sequence = '', None, 0
        self.snapshot_at = 0.
        super().__init__(case, tokenizer, config, emit)

    def begin(self, at):
        super().begin(at)
        self.output_id = f"{self.case.get('case_id', 'case')}:output-{self.generation}"
        self.played = ''

    def terminal(self, kind, at, output_id):
        if self.state != 'Speak' or self.output_id != output_id:
            self.emit('stale_callback', at=at, output_id=output_id, callback=kind)
            return False
        if kind == 'finish' and (self.complete_at is None or self.played != self.visible or
                                 at + 1e-9 < self.close_at):
            raise ValueError('Finish requires completed simulated playback')
        self.history.append({'role': 'assistant', 'text': self.visible, 'played_text': self.played,
                             'interrupted': kind == 'stop', 'output_id': output_id,
                             'completion': kind, 'playback_simulated': True})
        self.latest_terminal = {'kind': kind, 'output_id': output_id}
        self.runtime_sequence += 1
        event = {'event_seq': self.runtime_sequence, 'kind': kind, 'output_id': output_id,
                 'occurred_ms': at * 1000, 'published_ms': at * 1000, 'reason': kind}
        if kind == 'finish':
            event['marker'] = '<finish>'
        self.pending_events.append(event)
        self.emit(kind, at=at, **{k: v for k, v in event.items() if k != 'kind'})
        self.state, self.output_id = 'Listen', None
        return True

    def advance(self, at):
        if self.state != 'Speak':
            return
        # Generation has its own clock; simulated playback trails it by one period.
        while self.count < len(self.chunks) and self.release_at <= at + 1e-9:
            due = self.release_at
            self.visible += self.chunks[self.count]
            piece = self.chunks[self.count]
            self.count += 1
            self.release_at += self.period
            self.emit('assistant_publish', at=at, scheduled_at=due, generation=self.generation,
                      output_id=self.output_id, delta=piece, visible=self.visible,
                      delta_tokens=len(self.tokenizer.encode(piece)),
                      cumulative_tokens=len(self.tokenizer.encode(self.visible)),
                      sha256=hashlib.sha256(self.visible.encode()).hexdigest())
            if self.count == len(self.chunks):
                self.complete_at = due
                self.emit('generation_complete', at=at, scheduled_at=due,
                          output_id=self.output_id, generation=self.generation)
        begin = self.close_at - len(self.chunks) * self.period - self.case['tail_ms'] / 1000
        played_count = max(0, min(len(self.chunks), math.floor((at - begin + 1e-9) / self.period) - 1))
        self.played = ''.join(self.chunks[:played_count])
        if at + 1e-9 >= self.close_at:
            output_id = self.output_id
            self.terminal('finish', at, output_id)
            self.emit('playback_complete', at=at, scheduled_at=self.close_at,
                      output_id=output_id, generation=self.generation)

    def snapshot(self, delta, windows):
        visible = super().snapshot(delta, windows)
        visible['history'] = [{**item, 'text': strip_terminal(item['text'])}
                              if item.get('role') == 'user' else item
                              for item in visible['history']]
        events = [dict(event) for event in self.pending_events]
        self.pending_events.clear()
        # All runtime times use the same replay-relative clock as the trace.
        for event in events:
            event['consumed_ms'] = max(event['published_ms'], self.snapshot_at * 1000)
        visible.update(observation_type='text-update' if delta else 'empty-observation',
                       playback_phase='idle' if self.state == 'Listen' else 'playing' if self.played else 'preparing',
                       user_turn_id=self.turn, user_version=self.version, played_text=self.played if
                       self.state == 'Speak' else '', output_id=self.output_id,
                       runtime_events=events, latest_terminal=deepcopy(self.latest_terminal))
        return visible

    def apply(self, action, snapshot, generation, at, turn=None, committed_end=None):
        if action == 'stop' and self.state == snapshot['state'] == 'Speak' and self.generation == generation:
            self.terminal('stop', at, self.output_id)
            self.emit('stop_applied', at=at, generation=self.generation)
            return True
        return super().apply(action, snapshot, generation, at, turn, committed_end)


def replay_case(case, config, tokenizer, decide, trace_path):
    if 'freeze_error' in case:
        raise ValueError(case['freeze_error'])
    started = time.monotonic()
    with trace_path.open('w') as trace, ThreadPoolExecutor(max_workers=1) as executor:
        def emit(kind, **value):
            trace.write(json.dumps({'kind': kind, **value}, ensure_ascii=False) + '\n')
            trace.flush()
        emit('case_begin', at=0., started_monotonic=started, case_id=case['case_id'], config=config,
             mode=case['mode'], initial_state=case['initial_state'])
        state_type = DuplexReplayState if config.get('full_lifecycle') else ReplayState
        state = state_type(case, tokenizer, config, emit)
        events = [(e['at'], 0, e) for e in case['updates']]
        stride = config['control_ms'] // 160
        events += [(at, 1, {'step': index + 1}) for index, at in enumerate(case['steps'])
                   if (index + 1) % stride == 0]
        events.sort(key=lambda row: (row[0], row[1]))
        index, future, pending, request = 0, None, None, None
        user_delta, calls, errors, merged = '', 0, [], 0
        while index < len(events) or future is not None or pending is not None:
            now = time.monotonic() - started
            state.advance(now)
            if future is not None and future.done():
                try:
                    result, returned = future.result()
                    applied = state.apply(result['action'], request['visible'], request['generation'], now,
                                          request['turn'], request['committed_end'])
                    emit('control_result', at=now, returned_at=returned - started,
                         applied=applied, service=result, **request)
                except Exception as exc:
                    errors.append(repr(exc))
                    emit('control_error', at=now, error=repr(exc), **request)
                calls += 1
                future = None
            while index < len(events) and events[index][0] <= now + 1e-9:
                due, kind, value = events[index]
                if kind == 0:
                    old_turn, old_text = state.turn, state.text
                    state.update(value, now)
                    if value['kind'] == 'user':
                        user_delta = (user_delta + value['text'][len(old_text):] if old_turn == value['turn']
                                      else value['text'])
                else:
                    if pending is None:
                        pending = {'ready_at': due, 'windows': 1, 'last_step': value['step']}
                    else:
                        pending['windows'] += 1
                        pending['last_step'] = value['step']
                        merged += 1
                index += 1
            if future is None and pending is not None:
                state.snapshot_at = now
                request = {**pending, 'requested_at': time.monotonic() - started,
                           'generation': state.generation, 'turn': state.turn, 'version': state.version,
                           'committed_end': len(state.text),
                           'category': state.category, 'visible': state.snapshot(user_delta, pending['windows'])}
                user_delta, pending = '', None
                payload = request['visible']
                def invoke(payload=payload):
                    result = decide(payload)
                    return result, time.monotonic()
                future = executor.submit(invoke)
            if time.monotonic() - started > case['duration'] + 30:
                raise TimeoutError('Recorded replay exceeded bounded drain')
            time.sleep(.002)
        end = time.monotonic() - started
        state.advance(end)
        emit('case_end', at=end, state=state.state, generation_complete=state.complete_at is not None,
             tail_observed=state.complete_at is not None and end > state.complete_at,
             calls=calls, errors=errors, merged=merged)
    return {'case_id': case['case_id'], 'source_id': case['source_id'], 'mode': case['mode'],
            'category': case['category'], 'runtime_success': calls > 0 and not errors,
            'control_calls': calls, 'errors': errors, 'merged_windows': merged, 'elapsed_seconds': end}


def score_case(case, trace):
    row = {'case_id': case['case_id'], 'source_id': case['source_id'], 'mode': case['mode'],
           'category': case['category'], 'runtime_success': False, 'stop_count': 0,
           'stop_opportunities': 0, 'opportunities': 0, 'timely_960': 0, 'insufficient_960': 0,
           'natural_before_960': 0, 'backchannel_false_stop': 0, 'no_input_false_stop': 0,
           'backchannel_speak_calls': 0, 'no_input_speak_calls': 0, 'overlap_gt_960': 0,
           'anchor_opportunities': 0, 'anchor_timely_1000': 0, 'tail_observed': False}
    row.update(online_user_intervals=0, updates_outside_speak=0, generation_completions=0,
               natural_completions=0, tail_speak_calls=0, post_completion_listen_calls=0)
    if not trace.exists():
        return row
    with trace.open() as stream:
        events = list(map(json.loads, stream))
    end = next((e for e in reversed(events) if e['kind'] == 'case_end'), None)
    row['runtime_success'] = bool(end and end['calls'] and not end['errors'])
    row['tail_observed'] = bool(end and end['tail_observed'])
    if not end:
        return row
    episodes, speak_start, turns, opportunities, stops = [], None, {}, {}, []
    if case['initial_state'] == 'Speak':
        speak_start = 0.
    for e in events:
        kind, at = e['kind'], e.get('at', 0.)
        if kind == 'speak_begin':
            speak_start = at
        elif kind in ('stop_applied', 'playback_complete') and speak_start is not None:
            episodes.append((speak_start, at, kind))
            speak_start = None
        if kind == 'generation_complete':
            row['generation_completions'] += 1
        if kind == 'playback_complete':
            row['natural_completions'] += 1
        if kind == 'user_update' and e['delta']:
            times = turns.setdefault(e['turn'], [])
            times.append(at)
            if e['state'] == 'Speak':
                opportunities.setdefault(e['turn'], {'at': at, 'anchor': None})
            else:
                row['updates_outside_speak'] += 1
            if e['trigger_visible'] and e['turn'] in opportunities and opportunities[e['turn']]['anchor'] is None:
                opportunities[e['turn']]['anchor'] = at
        elif kind == 'control_result':
            visible = e['visible']
            if visible['state'] == 'Listen' and row['natural_completions']:
                row['post_completion_listen_calls'] += 1
            if visible['state'] == 'Speak' and visible['assistant_generation_complete']:
                row['tail_speak_calls'] += 1
                row['tail_observed'] = True
            if visible['state'] != 'Speak':
                continue
            if e['category'] == 'backchannel':
                row['backchannel_speak_calls'] += 1
            elif not visible['user_text'] and visible['observation'] == '<|no-voice|>':
                row['no_input_speak_calls'] += 1
            if e['service']['action'] == 'stop':
                row['stop_count'] += 1
                if e['applied']:
                    stops.append((e['turn'], e['returned_at']))
                if e['category'] == 'backchannel':
                    row['backchannel_false_stop'] += 1
                elif not visible['user_text'] and visible['observation'] == '<|no-voice|>':
                    row['no_input_false_stop'] += 1
    if speak_start is not None:
        episodes.append((speak_start, end['at'], 'observation_end'))
    latencies, anchor_latencies = [], []
    details = []
    for turn, opportunity in opportunities.items():
        start = opportunity['at']
        matched = [at for key, at in stops if key == turn and at >= start]
        latency = (min(matched) - start) * 1000 if matched else None
        closed = next(((b, reason) for a, b, reason in episodes if a <= start <= b), None)
        row['opportunities'] += 1
        row['stop_opportunities'] += bool(matched)
        row['timely_960'] += latency is not None and latency <= 960
        if latency is not None:
            latencies.append(latency)
        if latency is None or latency > 960:
            if closed and closed[1] == 'playback_complete' and closed[0] - start < .96:
                row['natural_before_960'] += 1
            elif end['at'] - start < .96:
                row['insufficient_960'] += 1
        anchor = opportunity['anchor']
        if anchor is not None:
            row['anchor_opportunities'] += 1
            anchored = [at for key, at in stops if key == turn and at >= anchor]
            if anchored:
                delay = (min(anchored) - anchor) * 1000
                anchor_latencies.append(delay)
                row['anchor_timely_1000'] += delay <= 1000
        details.append({'turn': turn, **opportunity, 'stop_latency_ms': latency,
                        'speak_end': closed})
    overlaps = []
    for turn, times in turns.items():
        first, last = min(times), max(times)
        overlap = max((max(0., min(b, last) - max(a, first)) * 1000 for a, b, _ in episodes), default=0.)
        row['overlap_gt_960'] += overlap > 960 + 1e-6
        overlaps.append({'turn': turn, 'first_update': first, 'last_update': last,
                         'max_continuous_speak_overlap_ms': overlap})
    row['online_user_intervals'] = len(turns)
    row['latencies_ms'] = latencies
    row['anchor_latencies_ms'] = anchor_latencies
    row['opportunity_details'] = details
    row['overlap_details'] = overlaps
    return row


def summarize(manifest, output):
    rows = [score_case(c, output / 'traces' / (c['case_id'] + '.jsonl')) for c in manifest['cases']]
    write_json(output / 'case_scores.json', rows)
    scalar = [key for key in rows[0] if not key.endswith('_ms') and not key.endswith('_details')]
    with (output / 'cases.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=scalar, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    groups = {}
    for mode in manifest['protocol']['input_modes']:
        subset = [r for r in rows if r['mode'] == mode]
        totals = {key: sum(r.get(key, 0) for r in subset) for key in (
            'runtime_success', 'stop_count', 'stop_opportunities', 'opportunities', 'timely_960',
            'insufficient_960', 'natural_before_960', 'backchannel_false_stop', 'no_input_false_stop',
            'backchannel_speak_calls', 'no_input_speak_calls', 'overlap_gt_960', 'online_user_intervals',
            'anchor_opportunities', 'anchor_timely_1000', 'tail_observed')}
        for key in ('updates_outside_speak', 'generation_completions', 'natural_completions',
                    'tail_speak_calls', 'post_completion_listen_calls'):
            totals[key] = sum(r[key] for r in subset)
        totals['planned'] = len(subset)
        delays = sorted(x for r in subset for x in r.get('latencies_ms', []))
        totals['stop_latency_ms'] = {'n': len(delays), 'median': delays[len(delays)//2] if delays else None,
            'p95': delays[min(len(delays)-1, math.ceil(len(delays)*.95)-1)] if delays else None}
        groups[mode] = totals
    write_json(output / 'summary.json', groups)
    return groups


def run(args):
    import requests
    manifest = json.loads(args.manifest.read_text())
    assert manifest['complete']
    config = next(c for c in manifest['protocol']['configurations'] if c['control_ms'] == args.control_ms)
    for path, expected in manifest['assets'].items():
        assert digest(path) == expected, f'Frozen asset changed: {path}'
    fresh(args.output)
    (args.output / 'traces').mkdir()
    write_json(args.output / 'identity.json', {'manifest_sha256': digest(args.manifest), 'config': config,
                                             'candidate_sha256': manifest['protocol']['candidate_sha256']})
    tokenizer = ControlTokenizer(args.tokenizer)
    def decide(visible):
        result = requests.post(args.controller_url + '/decide', json=visible, timeout=10)
        result.raise_for_status()
        result = result.json()
        assert result['candidate_sha256'] == manifest['protocol']['candidate_sha256']
        assert set(result['legal_logits']) == ({'keep','stop'} if visible['state']=='Speak' else {'keep','start'})
        return result
    completed, successful = 0, 0
    with (args.output / 'runtime.jsonl').open('w') as stream:
        for case in manifest['cases']:
            try:
                result = replay_case(case, config, tokenizer, decide,
                                     args.output / 'traces' / (case['case_id'] + '.jsonl'))
            except Exception as exc:
                result = {'case_id': case['case_id'], 'runtime_success': False, 'error': repr(exc)}
            stream.write(json.dumps(result, ensure_ascii=False) + '\n')
            stream.flush()
            completed += 1
            successful += result['runtime_success']
            progress = {'control_ms': args.control_ms, 'completed': completed,
                        'planned': len(manifest['cases']), 'runtime_successful': successful,
                        'last_case': case['case_id'], 'updated_at': time.time()}
            write_json(args.output / 'progress.json', progress)
            print(json.dumps(progress), flush=True)
    summary = summarize(manifest, args.output)
    if successful != completed:
        raise RuntimeError(f'{completed - successful} replay cases failed')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    f = commands.add_parser('freeze')
    for name in ('data', 'audio', 'traces', 'config', 'output'):
        f.add_argument('--' + name, type=Path, required=True)
    r = commands.add_parser('run')
    for name in ('manifest', 'tokenizer', 'output'):
        r.add_argument('--' + name, type=Path, required=True)
    r.add_argument('--control-ms', type=int, choices=(160,480), required=True)
    r.add_argument('--controller-url', default='http://127.0.0.1:18816')
    args = parser.parse_args()
    if args.command == 'freeze':
        freeze(args)
    else:
        print(json.dumps(run(args), ensure_ascii=False, indent=2))
