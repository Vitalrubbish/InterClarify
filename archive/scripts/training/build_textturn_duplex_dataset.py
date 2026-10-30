"""Build a versioned, 160ms duplex corpus without modifying the legacy dataset."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import resource
import time

from build_textturn_dataset import ACTIONS, SILENCE, ControlTokenizer, strip_terminal, prompt_for, seeded_rng, write_json

WINDOW = 160
VERSION = 'tt-010-duplex160-r2'
FINISH = '<finish>'


def register_finish(tokenizer):
    """Append an input-only completion marker without changing existing IDs."""
    from tokenizers import AddedToken
    if tokenizer.backend.token_to_id(FINISH) is not None:
        raise ValueError('Finish registration requires a legacy tokenizer')
    next_id = tokenizer.backend.get_vocab_size()
    tokenizer.backend.add_special_tokens([AddedToken(FINISH, special=True, normalized=False)])
    token_id = tokenizer.backend.token_to_id(FINISH)
    if token_id != next_id or tokenizer.encode(FINISH) != [token_id]:
        raise ValueError('Finish must use one new token ID')
    tokenizer.special = dict(tokenizer.special) | {FINISH: token_id}
    return token_id


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class DuplexTrace:
    """Own one synthetic output path and retain causal decision snapshots."""

    def __init__(self, identity, tokenizer, source, split, config):
        self.identity, self.tokenizer, self.source, self.split = identity, tokenizer, source, split
        self.config = config
        self.rng = seeded_rng(config["seed"], identity, "events")
        self.backchannel_queue = []
        self.empty_streak = 0
        self.sampling = Counter()
        self.now = 0
        self.state = 'Listen'
        self.history, self.events, self.rows, self.outputs = [], [], [], []
        self.user, self.turn, self.version = '', 1, 0
        self.active, self.terminal = None, None
        self.pending = []
        self.first_update = None

    def emit(self, kind, **fields):
        event = dict(event_seq=len(self.events) + 1, kind=kind, occurred_ms=self.now,
                     published_ms=self.now, clock_type='synthetic', **deepcopy(fields))
        self.events.append(event)
        return event

    def accept_start(self, text):
        if self.state != 'Listen' or self.active:
            raise ValueError('Start requires Listen with no active output')
        output_id = f'{self.identity}:output-{len(self.outputs) + 1}'
        output = dict(output_id=output_id, status='open', generated='', played='', cursor=0,
                      chunks=assistant_chunks(text, self.tokenizer, self.config['assistant_tokens_per_window_cycle']),
                      generation_complete=False, tail_windows=0, accepted_ms=self.now)
        self.outputs.append(output)
        self.active, self.state = output, 'Speak'
        self.history.append(dict(role='user', text=strip_terminal(self.user), turn_id=self.turn))
        self.user, self.version, self.first_update = '', 0, None
        self.turn += 1
        self.emit('start_accepted', output_id=output_id)
        self.emit('playback_started', output_id=output_id)

    def progress(self):
        output = self.active
        if not output:
            return
        output['played'] = output['generated']
        if output['cursor'] < len(output['chunks']):
            output['generated'] += output['chunks'][output['cursor']]
            output['cursor'] += 1
            if output['cursor'] == len(output['chunks']):
                output['generation_complete'] = True
                self.emit('generation_complete', output_id=output['output_id'])
        else:
            output['tail_windows'] += 1
        self.emit('output_progress', output_id=output['output_id'],
                  generated_chars=len(output['generated']), played_chars=len(output['played']),
                  generation_complete=output['generation_complete'])

    def callback(self, output_id, kind='finish'):
        output = self.active
        if not output or output['output_id'] != output_id:
            self.emit('stale_callback', output_id=output_id, callback=kind)
            return
        if kind == 'finish' and not (output['generation_complete'] and
                                    output['played'] == output['generated'] and output['tail_windows'] >= self.config['playback_tail_ms'] // WINDOW):
            raise ValueError('Finish requires fully drained playback and completed generation')
        if kind not in ('finish', 'stop', 'error'):
            raise ValueError('Unknown output terminal')
        output.update(status=kind, closed_ms=self.now)
        self.history.append(dict(role='assistant', text=output['generated'], played_text=output['played'],
                                 interrupted=kind == 'stop', output_id=output_id,
                                 completion=kind, playback_simulated=True))
        self.terminal = dict(kind=kind, output_id=output_id)
        event = self.emit(kind, output_id=output_id, reason=kind, state_after='Listen')
        if kind == 'finish':
            event['marker'] = FINISH
        self.pending.append(event)
        self.active, self.state = None, 'Listen'

    def update(self, text, version, turn_id):
        if turn_id != self.turn or version <= self.version or text == self.user:
            self.emit('ignored_asr', turn_id=turn_id, version=version, text=text)
            return ''
        if not text.startswith(self.user):
            raise ValueError('ASR revisions are outside the append-only contract')
        delta = text[len(self.user):]
        if not delta.strip():
            self.user, self.version = text, version
            self.emit('ignored_asr', turn_id=turn_id, version=version, text=text, reason='whitespace_only')
            return ''
        self.user, self.version = text, version
        if self.first_update is None:
            self.first_update = self.now
        self.emit('asr_update', turn_id=turn_id, version=version, text=text, delta=delta,
                  source='synthetic_unique_asr_stream')
        return delta

    def step(self, category, action='keep', delta='', judgment=None, advance=True, response=None,
             update=None, advance_clock=True):
        if advance_clock:
            self.now = (self.now // WINDOW + 1) * WINDOW
        finished_before_update = False
        if advance:
            self.progress()
            if self.active and self.active['generation_complete'] and self.active['tail_windows'] >= self.config['playback_tail_ms'] // WINDOW:
                self.callback(self.active['output_id'])
                finished_before_update = True
        if category == 'no_update' and self.active and self.active['generation_complete']:
            category = 'playback_tail'
        if update is not None:
            delta = self.update(**update)
        if action not in (None, 'keep', 'start', 'stop'):
            raise ValueError('Unknown model action')
        if action == 'stop' and finished_before_update:
            action = 'keep'
        fallback_keep = action is None
        if fallback_keep:
            action = 'keep'
        if action == 'stop' and (self.state != 'Speak' or not delta or judgment != 'non_backchannel'):
            raise ValueError('Stop needs a decidable effective non-backchannel update in Speak')
        if action == 'start' and (self.state != 'Listen' or not response):
            raise ValueError('Start needs Listen and a continuing output')
        consumed = []
        for event in self.pending:
            event['consumed_ms'] = self.now
            consumed.append({k: event[k] for k in ('event_seq', 'kind', 'output_id',
                                                   'occurred_ms', 'published_ms', 'consumed_ms', 'reason')})
            if event['kind'] == 'finish':
                consumed[-1]['marker'] = event['marker']
        self.pending.clear()
        self.empty_streak = 0 if strip_terminal(delta) else self.empty_streak + 1
        output = self.active
        visible = dict(history=deepcopy(self.history), user_text=strip_terminal(self.user), user_turn_id=self.turn,
                       user_version=self.version, observation=strip_terminal(delta) or SILENCE,
                       assistant_visible=output['generated'] if output else '',
                       played_text=output['played'] if output else '',
                       assistant_generation_complete=output['generation_complete'] if output else None,
                       state=self.state, output_id=output['output_id'] if output else None,
                       runtime_events=consumed, latest_terminal=deepcopy(self.terminal), window_ms=WINDOW,
                       consecutive_no_voice_windows=self.empty_streak, cot='')
        prompt = prompt_for(visible)
        ids = self.tokenizer.encode(prompt)
        labels = [-100] * len(ids)
        if action:
            target = self.tokenizer.special[ACTIONS[action]]
            ids.append(target)
            labels.append(target)
        request = self.emit('control_request', state=self.state, observation=strip_terminal(delta) or SILENCE,
                            category=category)
        row = dict(snapshot_id=f'{self.identity}:{len(self.rows)}', scenario_id=self.identity,
                   source_id=self.source['source_id'], scenario_group=self.source['duplicate_group'],
                   split=self.split, category=category, opportunity_id=f'{self.identity}:{category}',
                   visible_ms=self.now, visible=visible, target_action=action,
                   annotation=dict(visible_prefix=strip_terminal(self.user), judgment=judgment,
                                   fallback_keep=fallback_keep,
                                   method='authored_synthetic_prefix_annotation'),
                   first_effective_update_ms=self.first_update, request_event_seq=request['event_seq'],
                   prompt=prompt, input_ids=ids, labels=labels, playback_simulated=True,
                   excluded_reason='overlength' if len(ids) > self.config['max_length'] else None)
        self.rows.append(row)
        if action == 'start':
            self.accept_start(response)
        elif action == 'stop':
            output_id = self.active['output_id']
            row['decidable_update_ms'] = self.now
            self.emit('stop_requested', output_id=output_id, returned_ms=self.now, state_after='Speak')
            self.now += self.config['stop_confirmation_ms']
            self.callback(output_id, 'stop')
            row['stop_confirmed_ms'] = self.now
        return row

    def user_segment(self, text, category, decide_at=None, advance=True):
        prefix = ''
        pieces = list(self.tokenizer.chunks(text, self.config['user_tokens_per_480ms'], rng=seeded_rng(
            self.config['seed'], self.identity, category, self.turn)))
        for index, piece in enumerate(pieces):
            prefix += piece
            judgment = 'non_backchannel' if decide_at is not None and len(prefix) >= decide_at else None
            action = 'stop' if self.state == 'Speak' and judgment else None
            self.step(category, action, judgment=judgment, advance=advance,
                      update=dict(text=self.user + piece, version=self.version + 1, turn_id=self.turn))
            if index == len(pieces) - 1:
                continue
            for _ in range(2):
                self.step('inter_chunk_gap')
            self.sampling['pause_trials'] += 1
            if self.rng.random() < self.config['pause_probability']:
                self.sampling['pause_insertions'] += 1
                count = self.rng.randint(*self.config['pause_windows'])
                self.emit('pause_inserted', windows=count, user_prefix=strip_terminal(self.user),
                          after_piece=index, remaining_pieces=len(pieces) - index - 1)
                for _ in range(count):
                    self.step('pause')

    def speaking_step(self):
        output = self.active
        if not output and not self.backchannel_queue:
            raise ValueError('A speaking tick requires an active output')
        finishing = output and output['generation_complete'] and output['tail_windows'] + 1 >= self.config['playback_tail_ms'] // WINDOW
        if output and not self.backchannel_queue and not self.user and not finishing:
            self.sampling['backchannel_trials'] += 1
            if self.rng.random() < self.config['backchannel_probability']:
                self.sampling['backchannel_insertions'] += 1
                text = self.rng.choice(self.config['backchannels'])
                self.backchannel_queue = list(self.tokenizer.chunks(text, (1, 2), rng=self.rng))
                self.emit('backchannel_inserted', text=text, output_id=output['output_id'])
        if self.backchannel_queue:
            piece = self.backchannel_queue.pop(0)
            self.step('backchannel', 'keep', judgment='backchannel',
                      update=dict(text=self.user + piece, version=self.version + 1, turn_id=self.turn))
            if not self.backchannel_queue:
                self.history.append(dict(role='user', kind='backchannel', text=strip_terminal(self.user)))
                self.emit('backchannel_closed', text=strip_terminal(self.user), turn_id=self.turn)
                self.user, self.version, self.first_update = '', 0, None
                self.turn += 1
        else:
            self.step('no_update')

    def drain(self):
        while self.active or self.backchannel_queue:
            self.speaking_step()

    def validate(self, truncated=False):
        terminal_counts = Counter(e['output_id'] for e in self.events if e['kind'] in ('stop', 'finish', 'error'))
        for output in self.outputs:
            expected = 0 if output['status'] == 'open' else 1
            if terminal_counts[output['output_id']] != expected:
                raise ValueError('Output terminal pairing failed')
            if output['status'] == 'open':
                if not truncated:
                    raise ValueError('Unmarked open output')
                output['status'] = 'truncated'
        for row in self.rows:
            expected = [self.tokenizer.special[ACTIONS[row['target_action']]]]
            if [v for v in row['labels'] if v != -100] != expected:
                raise ValueError('Action-only loss mask failed')
        return dict(scenario_id=self.identity, source_id=self.source['source_id'], split=self.split,
                    events=self.events, outputs=[{k: v for k, v in o.items() if k != 'chunks'} for o in self.outputs],
                    truncated=truncated, sampling=dict(self.sampling))


# These are authored causal prefix boundaries for synthetic user takeovers.
UPDATES = [('Add a practical example.', 3), ('Use a simpler explanation.', 3),
           ('I meant a different situation.', 6), ('Could you explain the last part?', 9),
           ('Change the topic to the next step.', 6), ('Please stop speaking.', 11),
           ('Instead, focus on the cost.', 7), ('That should include the risks.', 11)]


def assistant_chunks(text, tokenizer, widths=(3, 3, 2)):
    """Preserve character spans while emitting a repeating 3/3/2 token schedule."""
    offsets = tokenizer.backend.encode(text, add_special_tokens=False).offsets
    result, cursor, start = [], 0, 0
    while cursor < len(offsets):
        width = widths[len(result) % len(widths)]
        end = min(cursor + width, len(offsets))
        stop = offsets[end - 1][1]
        while end < len(offsets) and offsets[end][0] < stop:
            stop = max(stop, offsets[end][1])
            end += 1
        if end == len(offsets):
            stop = len(text)
        result.append(text[start:stop])
        cursor, start = end, stop
    return result


def scenario(source, split, form, variant, tokenizer, config, ordinal=0):
    identity = f'{VERSION}:{source["source_id"]}:{form}:{variant}'
    trace = DuplexTrace(identity, tokenizer, source, split, config)
    turn = 0 if form == 'question' else 2
    trace.history = [dict(role='user' if i % 2 == 0 else 'assistant',
                          text=strip_terminal(text) if i % 2 == 0 else text)
                     for i, text in enumerate(source['texts'][:turn])]
    trace.user_segment(source['texts'][turn], 'listen')
    trace.step('smooth', 'start', response=source['texts'][turn + 1])
    if variant == 'interrupt':
        phase = ordinal % 4
        if phase == 2:
            while trace.active and not trace.active['generation_complete']:
                trace.speaking_step()
        elif phase in (1, 3):
            count = len(trace.active['chunks'])
            target = max(1, count // 2) if phase == 1 else trace.rng.randrange(1, max(2, count))
            for _ in range(target):
                if trace.active:
                    trace.speaking_step()
        while trace.backchannel_queue:
            trace.speaking_step()
        text, boundary = UPDATES[0] if phase in (0, 2) else UPDATES[ordinal % len(UPDATES)]
        trace.user_segment(text, 'interruption', boundary, advance=phase != 0)
    trace.drain()
    for _ in range(trace.rng.randint(1, 20)):
        trace.step('post_output_wait')
    timeline = trace.validate()
    timeline.update(form=form, variant=variant)
    for row in trace.rows:
        row.update(utterance_form=form, scenario_variant=variant,
                   review_status='synthetic_prefix_annotated', allowed_visible_ms=row['visible_ms'])
        if row['target_action'] == 'stop':
            row['category'] = 'interruption'
        elif row['target_action'] == 'start':
            row['category'] = 'smooth'
    return timeline, trace.rows


def build(legacy, output, config_path):
    started = time.monotonic()
    config = json.loads(config_path.read_text())
    if config['window_ms'] != WINDOW or not 0 <= config['pause_probability'] <= 1 or not 0 <= config['backchannel_probability'] <= 1:
        raise ValueError('Invalid event probabilities or control period')
    if config['pause_windows'] != [1, 5] or config['playback_tail_ms'] % WINDOW:
        raise ValueError('Expected a frozen pause and playback duration contract')
    if config['assistant_tokens_per_window_cycle'] != [3, 3, 2] or config['user_tokens_per_480ms'] != [1, 2]:
        raise ValueError('Text release rate differs from the frozen contract')
    if config['max_length'] != 2048 or not 1 <= config['train_snapshots_max'] <= 10000:
        raise ValueError('Snapshot length or count exceeds the authorized contract')
    if output.exists():
        raise ValueError('Output must be fresh')
    manifest = json.loads((legacy / 'manifest.json').read_text())
    for name in ('source_records.json', 'split_index.json', 'tokenizer.json', 'tokenizer_config.json'):
        if file_hash(legacy / name) != manifest['files'][name]:
            raise ValueError(f'Legacy input digest mismatch: {name}')
    from tokenizers import Tokenizer
    tokenizer = ControlTokenizer.__new__(ControlTokenizer)
    tokenizer.backend = Tokenizer.from_file(str(legacy / 'tokenizer.json'))
    tokenizer.special = dict(manifest['new_token_ids'])
    for marker, token_id in tokenizer.special.items():
        if tokenizer.encode(marker) != [token_id]:
            raise ValueError('Legacy token ID changed')
    finish_id = register_finish(tokenizer)
    index = json.loads((legacy / 'split_index.json').read_text())
    sources = json.loads((legacy / 'source_records.json').read_text())
    selected = [i for i in index if i['split'] in ('train', 'dev')]
    if dict(Counter(i['split'] for i in selected)) != {'train': 160, 'dev': 200}:
        raise ValueError('Expected original train/dev sources')
    groups = defaultdict(set)
    for item in index:
        groups[item['duplicate_group']].add(item['split'])
    if any(len(groups[i['duplicate_group']]) != 1 for i in selected):
        raise ValueError('Source group crosses legacy splits')
    output.mkdir(parents=True)
    write_json(output / 'split_index.json', selected)
    write_json(output / 'source_records.json', {i['source_id']: sources[i['source_id']] for i in selected})
    stats, categories, forms, events, pause_lengths = Counter(), Counter(), Counter(), Counter(), Counter()
    sampling = defaultdict(Counter)
    annotation_counts, bytes_written = 0, 0
    handles = {s: (output / f'{s}.jsonl').open('w') for s in ('train', 'dev')}
    sample = []
    with (output / 'timelines.jsonl').open('w') as timelines, (output / 'prefix_annotations.jsonl').open('w') as annotations:
        try:
            for ordinal, item in enumerate(selected):
                source = sources[item['source_id']] | {'source_id': item['source_id']}
                if any(FINISH in text for text in source['texts']):
                    raise ValueError('Source contains reserved completion marker')
                for form in ('question', 'declarative'):
                    for variant in ('normal', 'interrupt'):
                        timeline, rows = scenario(source, item['split'], form, variant, tokenizer, config, ordinal)
                        sampling[item['split']].update(timeline['sampling'])
                        payload = json.dumps(timeline, ensure_ascii=False, separators=(',', ':')) + '\n'
                        timelines.write(payload)
                        bytes_written += len(payload.encode())
                        keep_counts = Counter()
                        for event in timeline['events']:
                            events[(item['split'], event['kind'])] += 1
                            if event['kind'] == 'pause_inserted':
                                pause_lengths[event['windows']] += 1
                        for row in rows:
                            bucket = row['category']
                            selected_row = not row['excluded_reason'] and (
                                row['target_action'] != 'keep' or row['visible']['runtime_events'] or keep_counts[bucket] < 2)
                            selected_row = bool(selected_row)
                            record = {k: row[k] for k in ('snapshot_id', 'annotation', 'target_action', 'excluded_reason')}
                            record['selected'] = selected_row
                            payload = json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n'
                            annotations.write(payload)
                            bytes_written += len(payload.encode())
                            annotation_counts += 1
                            if not selected_row:
                                continue
                            keep_counts[bucket] += 1
                            payload = json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n'
                            handles[item['split']].write(payload)
                            bytes_written += len(payload.encode())
                            stats[(item['split'], row['target_action'])] += 1
                            categories[(item['split'], row['category'])] += 1
                            if row['target_action'] == 'start':
                                forms[(item['split'], form)] += 1
                            if ordinal == 0:
                                sample.append({k: row[k] for k in ('snapshot_id', 'visible_ms', 'visible', 'target_action', 'annotation')})
                if time.monotonic() - started > 540 or bytes_written > 450 * 1024 ** 2:
                    raise ValueError('CPU or disk budget exceeded; partial evidence retained')
        finally:
            for handle in handles.values():
                handle.close()
    if sum(n for (s, _), n in stats.items() if s == 'train') > config['train_snapshots_max']:
        raise ValueError('Training snapshot budget exceeded')
    for split in handles:
        if forms[(split, 'declarative')] * 3 < sum(n for (s, _), n in forms.items() if s == split):
            raise ValueError('Declarative start share below one third')
    write_json(output / 'samples.json', sample)
    tokenizer.backend.save(str(output / 'tokenizer.json'))
    token_config = json.loads((legacy / 'tokenizer_config.json').read_text())
    token_config['added_tokens_decoder'] = {str(t['id']): {k: v for k, v in t.items() if k != 'id'}
                                           for t in json.loads(tokenizer.backend.to_str())['added_tokens']}
    token_config['additional_special_tokens'] = list(dict.fromkeys(
        token_config.get('additional_special_tokens', []) + list(tokenizer.special)))
    write_json(output / 'tokenizer_config.json', token_config)
    result = dict(schema_version=3, version=VERSION, training_allowed=False, training_executed=False,
                  status='frozen_synthetic_prefix_annotated', model_revision=manifest['model_revision'],
                  playback_simulated=True, new_token_ids=tokenizer.special,
                  action_token_ids={a: tokenizer.special[t] for a, t in ACTIONS.items()},
                  finish_encoding=dict(marker=FINISH, token_id=finish_id, input_only=True, loss='masked'),
                  config=config, source_dialogues=dict(Counter(i['split'] for i in selected)),
                  action_counts={s: {a: n for (split, a), n in stats.items() if split == s} for s in handles},
                  category_counts={s: {a: n for (split, a), n in categories.items() if split == s} for s in handles},
                  start_forms={s: {a: n for (split, a), n in forms.items() if split == s} for s in handles},
                  event_counts={s: {a: n for (split, a), n in events.items() if split == s} for s in handles},
                  pause_length_windows=dict(pause_lengths), full_annotations=annotation_counts,
                  sampling={s: dict(c) for s, c in sampling.items()},
                  builder_sha256=file_hash(__file__), config_sha256=file_hash(config_path),
                  legacy_manifest_sha256=file_hash(legacy / 'manifest.json'),
                  elapsed_seconds=round(time.monotonic() - started, 3),
                  limitations=['合成时序、播放和用户插入，尚无真实ASR或噪声覆盖。',
                               '非附和可判定前缀为有限手写标注，不代表开放域泛化。',
                               '来源隔离继承TT-001范围，不证明全历史语义去重。'],
                  files={p.name: file_hash(p) for p in output.iterdir()})
    if sum(p.stat().st_size for p in output.iterdir()) > 512 * 1024 ** 2:
        raise ValueError('Disk budget exceeded')
    write_json(output / 'manifest.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('configs/textturn_duplex_dataset.json'))
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
    print(json.dumps(build(args.legacy, args.output, args.config), ensure_ascii=False, indent=2))
