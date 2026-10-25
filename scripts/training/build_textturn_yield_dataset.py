"""Build a versioned, causal yield corpus without modifying the legacy dataset."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import resource
import time

from build_textturn_dataset import ACTIONS, SILENCE, ControlTokenizer, prompt_for, seeded_rng, write_json

WINDOW = 480
VERSION = 'tt-010-yield-v2'
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


class YieldTrace:
    """Own one synthetic output path and retain causal decision snapshots."""

    def __init__(self, identity, tokenizer, source, split):
        self.identity, self.tokenizer, self.source, self.split = identity, tokenizer, source, split
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
                      chunks=list(self.tokenizer.chunks(text, 8, merge_terminal=False)),
                      generation_complete=False, tail_windows=0, accepted_ms=self.now)
        self.outputs.append(output)
        self.active, self.state = output, 'Speak'
        self.history.append(dict(role='user', text=self.user, turn_id=self.turn))
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
        self.emit('output_progress', output_id=output['output_id'], generated=output['generated'],
                  played=output['played'], generation_complete=output['generation_complete'])

    def callback(self, output_id, kind='finish'):
        output = self.active
        if not output or output['output_id'] != output_id:
            self.emit('stale_callback', output_id=output_id, callback=kind)
            return
        if kind == 'finish' and not (output['generation_complete'] and
                                    output['played'] == output['generated'] and output['tail_windows'] >= 2):
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
            self.emit('ignored_asr', turn_id=turn_id, version=version, text=text)
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
        if advance:
            self.progress()
        if category == 'no_update' and self.active and self.active['generation_complete']:
            category = 'playback_tail'
        if update is not None:
            delta = self.update(**update)
        if action not in (None, 'keep', 'start', 'stop'):
            raise ValueError('Unknown model action')
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
        output = self.active
        visible = dict(history=deepcopy(self.history), user_text=self.user, user_turn_id=self.turn,
                       user_version=self.version, observation=delta or SILENCE,
                       assistant_visible=output['generated'] if output else '',
                       played_text=output['played'] if output else '',
                       assistant_generation_complete=output['generation_complete'] if output else None,
                       state=self.state, output_id=output['output_id'] if output else None,
                       runtime_events=consumed, latest_terminal=deepcopy(self.terminal), window_ms=WINDOW, cot='')
        prompt = prompt_for(visible)
        ids = self.tokenizer.encode(prompt)
        labels = [-100] * len(ids)
        if action:
            target = self.tokenizer.special[ACTIONS[action]]
            ids.append(target)
            labels.append(target)
        request = self.emit('control_request', state=self.state, observation=delta or SILENCE)
        row = dict(snapshot_id=f'{self.identity}:{len(self.rows)}', scenario_id=self.identity,
                   source_id=self.source['source_id'], scenario_group=self.source['duplicate_group'],
                   split=self.split, category=category, opportunity_id=f'{self.identity}:{category}',
                   visible_ms=self.now, visible=visible, target_action=action,
                   annotation=dict(visible_prefix=self.user, judgment=judgment,
                                   fallback_keep=fallback_keep,
                                   method='authored_synthetic_prefix_annotation'),
                   first_effective_update_ms=self.first_update, request_event_seq=request['event_seq'],
                   prompt=prompt, input_ids=ids, labels=labels, playback_simulated=True,
                   excluded_reason='overlength' if len(ids) > 2048 else None)
        self.rows.append(row)
        if action == 'start':
            self.accept_start(response)
        elif action == 'stop':
            output_id = self.active['output_id']
            row['decidable_update_ms'] = self.now
            self.emit('stop_requested', output_id=output_id, returned_ms=self.now, state_after='Speak')
            self.now += 80
            self.callback(output_id, 'stop')
            row['stop_confirmed_ms'] = self.now
        return row

    def user_segment(self, text, category, decide_at=None, backchannel=False, advance=True):
        """Materialize authored prefix judgments separately from model-visible inputs."""
        prefix = ''
        sampling_identity = self.identity.replace(VERSION, 'tt-010-yield-v1', 1)
        for piece in self.tokenizer.chunks(text, (1, 2), rng=seeded_rng(20261025, sampling_identity, category)):
            prefix += piece
            judgment = None
            if backchannel and prefix.strip().rstrip('.!,') in ('Right', 'Mm-hm', 'Okay', 'I see', 'Yes'):
                judgment = 'backchannel'
            if decide_at is not None and len(prefix) >= decide_at:
                judgment = 'non_backchannel'
            if self.state == 'Speak':
                action = 'stop' if judgment == 'non_backchannel' else ('keep' if judgment == 'backchannel' else None)
            else:
                action = None
            self.step(category, action, judgment=judgment, advance=advance,
                      update=dict(text=self.user + piece, version=self.version + 1, turn_id=self.turn))

    def drain(self):
        while self.active and not (self.active['generation_complete'] and self.active['tail_windows'] >= 2):
            self.step('no_update')
        if self.active:
            self.callback(self.active['output_id'])

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
                    truncated=truncated)


# These annotations describe constructed prefixes, never a runtime word filter.
UPDATES = [('Add a practical example.', 3), ('Use a simpler explanation.', 3),
           ('I meant a different situation.', 6), ('Could you explain the last part?', 9),
           ('Change the topic to the next step.', 6), ('Please stop speaking.', 11),
           ('Instead, focus on the cost.', 7), ('That should include the risks.', 11)]
VARIANTS = ('ordinary', 'backchannel', 'transition', 'tail', 'pretext', 'finish', 'repeat',
            'truncated', 'multiple', 'finish_first', 'update_first', 'error')


def scenario(source, split, variant, tokenizer, ordinal):
    trace = YieldTrace(f'{VERSION}:{source["source_id"]}:{variant}', tokenizer, source, split)
    response = source['texts'][1]
    trace.user_segment(source['texts'][0], 'listen')
    trace.step('turn_start', 'start', response=response)
    output_id = trace.active['output_id']
    text, boundary = UPDATES[ordinal % len(UPDATES)]
    if variant in ('finish_first', 'update_first'):
        while not (trace.active['generation_complete'] and trace.active['tail_windows'] >= 2):
            trace.step('no_update')
        if variant == 'finish_first':
            trace.callback(output_id)
        trace.step('same_time_update', None if variant == 'finish_first' else 'stop',
                   judgment='non_backchannel', advance=False, advance_clock=False,
                   update=dict(text='Add', version=1, turn_id=trace.turn))
        trace.callback(output_id)
        trace.step('after_race')
    elif variant == 'error':
        trace.step('no_update')
        trace.callback(output_id, 'error')
        trace.step('after_error')
    elif variant == 'finish':
        trace.drain()
        trace.callback(output_id)
        trace.user_segment(source['texts'][2], 'next_turn')
        trace.step('next_start', 'start', response=source['texts'][3])
        trace.drain()
    elif variant == 'repeat':
        trace.user_segment('Right.', 'backchannel', backchannel=True)
        for version, turn_id, value in [(trace.version, trace.turn, trace.user),
                                         (trace.version + 1, trace.turn, trace.user),
                                         (trace.version + 1, trace.turn - 1, source['texts'][0])]:
            trace.step('repeat', update=dict(text=value, version=version, turn_id=turn_id))
        trace.drain()
    elif variant == 'backchannel':
        trace.user_segment('Right.', 'backchannel', backchannel=True)
        trace.drain()
    elif variant == 'truncated':
        trace.step('no_update')
    else:
        if variant == 'tail':
            while not trace.active['generation_complete']:
                trace.step('no_update')
        elif variant == 'transition':
            trace.user_segment('Right', 'backchannel', backchannel=True)
            text, boundary = ', but use a different example.', 5
        elif variant != 'pretext':
            for _ in range(ordinal % 3 + 1):
                trace.step('no_update')
        trace.user_segment(text, 'non_backchannel', boundary, advance=variant != 'pretext')
        trace.callback(output_id)
        if variant == 'multiple':
            trace.step('restart', 'start', response=source['texts'][3])
            trace.user_segment('Add the limitations.', 'second_update', 3)
        trace.step('after_stop')
    timeline = trace.validate(truncated=variant == 'truncated')
    return timeline, trace.rows


def build(legacy, output):
    started = time.monotonic()
    if output.exists():
        raise ValueError('Output must be a fresh version directory')
    manifest = json.loads((legacy / 'manifest.json').read_text())
    for name in ('source_records.json', 'split_index.json', 'tokenizer.json', 'tokenizer_config.json'):
        if file_hash(legacy / name) != manifest['files'][name]:
            raise ValueError(f'Legacy input digest mismatch: {name}')
    from tokenizers import Tokenizer
    tokenizer = ControlTokenizer.__new__(ControlTokenizer)
    tokenizer.backend = Tokenizer.from_file(str(legacy / 'tokenizer.json'))
    tokenizer.special = manifest['new_token_ids']
    for marker, token_id in tokenizer.special.items():
        if tokenizer.encode(marker) != [token_id]:
            raise ValueError('Frozen token encoding differs')
    finish_id = register_finish(tokenizer)
    index = json.loads((legacy / 'split_index.json').read_text())
    sources = json.loads((legacy / 'source_records.json').read_text())
    selected = []
    for split, count in [('train', 24), ('dev', 12)]:
        candidates = sorted((r for r in index if r['split'] == split),
                            key=lambda r: hashlib.sha256(('tt010|' + r['source_id']).encode()).hexdigest())
        if len(candidates) < count:
            raise ValueError('Insufficient frozen sources')
        selected += candidates[:count]
    groups = defaultdict(set)
    for item in index:
        groups[item['duplicate_group']].add(item['split'])
    if any(len(groups[item['duplicate_group']]) != 1 for item in selected):
        raise ValueError('Source group crosses legacy splits')
    output.mkdir(parents=True)
    write_json(output / 'split_index.json', selected)
    write_json(output / 'source_records.json', {i['source_id']: sources[i['source_id']] for i in selected})
    stats, opportunity_counts, terminal_stats, category_counts = Counter(), Counter(), Counter(), Counter()
    annotations, samples, fallback_counts = [], [], Counter()
    handles = {split: (output / f'{split}.jsonl').open('w') for split in ('train', 'dev')}
    try:
        with (output / 'timelines.jsonl').open('w') as timelines:
            for ordinal, item in enumerate(selected):
                source = sources[item['source_id']] | {'source_id': item['source_id']}
                for variant in VARIANTS:
                    timeline, rows = scenario(source, item['split'], variant, tokenizer, ordinal)
                    timelines.write(json.dumps(timeline, ensure_ascii=False) + '\n')
                    terminal_stats.update(o['status'] for o in timeline['outputs'])
                    retained = Counter()
                    for row in rows:
                        bucket = (row['category'], row['target_action'], row['annotation']['fallback_keep'])
                        selected_row = not row['excluded_reason'] and (row['target_action'] in ('start', 'stop') or retained[bucket] < 2)
                        annotations.append({k: row[k] for k in ('snapshot_id', 'annotation', 'target_action', 'excluded_reason')}
                                           | {'selected': selected_row})
                        if not selected_row:
                            continue
                        retained[bucket] += 1
                        handles[item['split']].write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
                        stats[(item['split'], row['target_action'] or 'unknown')] += 1
                        fallback_counts[item['split']] += row['annotation']['fallback_keep']
                        category_counts[(item['split'], row['category'])] += 1
                        opportunity_counts[(item['split'], row['opportunity_id'])] += 1
                        if ordinal == 0 and variant in ('ordinary', 'transition', 'tail', 'finish', 'pretext'):
                            samples.append({k: row[k] for k in ('snapshot_id', 'visible_ms', 'visible', 'target_action', 'annotation')})
                    if time.monotonic() - started > 540 or sum(p.stat().st_size for p in output.iterdir()) > 450 * 1024 ** 2:
                        raise ValueError('CPU or disk budget exceeded; partial output retained')
    finally:
        for handle in handles.values():
            handle.close()
    if sum(v for (split, _), v in stats.items() if split == 'train') > 10000:
        raise ValueError('Snapshot budget exceeded')
    write_json(output / 'prefix_annotations.json', annotations)
    write_json(output / 'samples.json', samples)
    tokenizer.backend.save(str(output / 'tokenizer.json'))
    tokenizer_config = json.loads((legacy / 'tokenizer_config.json').read_text())
    added = json.loads(tokenizer.backend.to_str())['added_tokens']
    tokenizer_config['added_tokens_decoder'] = {
        str(token['id']): {k: v for k, v in token.items() if k != 'id'} for token in added}
    tokenizer_config['additional_special_tokens'] = list(dict.fromkeys(
        tokenizer_config.get('additional_special_tokens', []) + list(tokenizer.special)))
    write_json(output / 'tokenizer_config.json', tokenizer_config)
    result = dict(schema_version=2, version=VERSION, status='frozen_synthetic_prefix_annotated',
                  training_executed=False, model_quality_verified=False, playback_simulated=True,
                  training_allowed=False, model_revision=manifest['model_revision'],
                  new_token_ids=tokenizer.special,
                  action_token_ids={a: tokenizer.special[t] for a, t in ACTIONS.items()},
                  ambiguity_policy='keep', fallback_keep_snapshots=dict(fallback_counts),
                  finish_encoding={'kind': 'finish', 'marker': FINISH, 'token_id': finish_id,
                                   'special_token_added': True, 'loss': 'masked_input',
                                   'embedding_policy': 'initialize_and_train_on_future_authorized_training'},
                  window_ms=480, user_tokens_per_step=[1, 2], assistant_tokens_per_step=8,
                  playback_tail_ms=960, stop_confirmation_ms=80, max_length=2048,
                  source_dialogues=dict(Counter(i['split'] for i in selected)),
                  action_counts={s: {a: n for (split, a), n in stats.items() if split == s} for s in handles},
                  category_counts={s: {c: n for (split, c), n in category_counts.items() if split == s} for s in handles},
                  opportunities={s: sum(split == s for split, _ in opportunity_counts) for s in handles},
                  terminal_counts=dict(terminal_stats),
                  legacy_manifest_sha256=file_hash(legacy / 'manifest.json'),
                  builder_sha256=file_hash(__file__), elapsed_seconds=round(time.monotonic() - started, 3),
                  limits={'threads': 1, 'address_space_gib': 2, 'timeout_seconds': 600, 'disk_mib': 512},
                  limitations=['合成文本及播放器，非真实ASR或音频验证。', '有限手写前缀语义及对照，不代表开放域泛化。',
                               '继承旧来源隔离范围，未做全历史语义去重。', '噪声来源覆盖为0，不将噪声标成附和。'],
                  files={p.name: file_hash(p) for p in output.iterdir()})
    if sum(p.stat().st_size for p in output.iterdir()) > 512 * 1024 ** 2:
        raise ValueError('Disk budget exceeded')
    write_json(output / 'manifest.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
    print(json.dumps(build(args.legacy, args.output), ensure_ascii=False, indent=2))
