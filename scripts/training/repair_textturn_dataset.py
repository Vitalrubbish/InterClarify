"""Build and audit complete repaired TextTurn source bundles on CPU."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import random
import re
import resource
import shutil
import time

from build_textturn_dataset import ACTIONS, ControlTokenizer, write_json
from build_textturn_duplex_dataset import register_finish
from textturn_input import CONTRACT, render_prompt
from textturn_loss import assign_loss_weights, complete_trajectory_groups

VERSION = 'tt-010-repair-20261027-r3'
BOUNDARY_VERSION = 'prefix-punctuation-v1'
ABBREVIATIONS = ('mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'vs', 'etc', 'e.g', 'i.e', 'fig', 'no', 'inc')
REQUESTS = [
    ('could you explain', 'Could you explain the last point in more detail?'),
    ('add an example', 'Add an example showing how this works.'),
    ('i meant', 'I meant a situation with a smaller budget.'),
    ('focus on', 'Focus on the practical risks instead.'),
    ('use a simpler', 'Use a simpler explanation for this part.'),
    ('compare the', 'Compare the two alternatives before continuing.'),
    ('change the', 'Change the assumption about the available time.'),
    ('include the', 'Include the effect of the extra cost.')]
HELDOUT_REQUESTS = [
    ('walk me through', 'Walk me through a concrete case, please.'),
    ('what happens if', 'What happens if the initial conditions change?'),
    ('set aside', 'Set aside that approach and consider the other option.'),
    ('reconsider the', 'Reconsider the explanation using a different example.')]
STOPS = [('stop speaking', 'Please stop speaking.'), ('stop talking', 'Please stop talking now.')]
HELDOUT_STOPS = [('be quiet', 'Please be quiet.'), ('pause your answer', 'Pause your answer, please.')]
BACKCHANNELS = ('Okay.', 'Right.', 'I see.', 'Yes.', 'Mm-hm.', 'Uh-huh.')


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def rng_for(seed, *parts):
    return random.Random(int(hashlib.sha256(json.dumps([seed, *parts]).encode()).hexdigest(), 16))


def complete_prefix(text):
    prefix = re.sub(r'[\"\'”’）)\]}]+$', '', text.rstrip()).rstrip()
    if not prefix or prefix[-1] not in '.?!。！？':
        return False
    if prefix.endswith(('...', '…', '..')):
        return False
    if prefix[-1] in '?!。！？':
        return True
    if re.search(r'\d\.$|(?:\b[A-Za-z]\.){2,}$', prefix):
        return False
    word = re.search(r'([\w.]+)\.$', prefix)
    return not word or word.group(1).lower() not in ABBREVIATIONS


def anchor_visible(prefix, anchors):
    text = prefix.casefold()
    return any(re.search(r'(?<!\w)' + re.escape(a) + r'(?!\w)', text) for a in anchors)


class ReleaseStream:
    """Keep source time fixed while publishing lossless token-bounded spans."""

    def __init__(self, text, tokenizer, rng, config):
        self.text, self.queue = text, deque()
        offsets = tokenizer.backend.encode(text, add_special_tokens=False).offsets
        self.queue.extend([''] * rng.randint(*config['initial_empty_windows']))
        cursor = start = 0
        while cursor < len(offsets):
            burst = rng.randint(*config['burst_windows'])
            for _ in range(burst):
                if cursor >= len(offsets):
                    break
                width = rng.choice(config['user_token_widths'])
                end = min(cursor + width, len(offsets))
                stop = offsets[end - 1][1]
                if end < len(offsets) and offsets[end][0] < stop:
                    raise ValueError('A Unicode span crosses the authorized token release budget')
                if end == len(offsets):
                    stop = len(text)
                self.queue.append(text[start:stop])
                cursor, start = end, stop
            if cursor < len(offsets):
                if rng.random() < config['short_gap_probability']:
                    count = rng.randint(*config['short_gap_windows'])
                else:
                    lengths = list(range(config['long_gap_windows'][0], config['long_gap_windows'][1] + 1))
                    count = rng.choices(lengths, weights=[config['long_gap_decay'] ** (k-lengths[0]) for k in lengths])[0]
                self.queue.extend([''] * count)
        if ''.join(self.queue) != text:
            raise ValueError('Release stream did not preserve the source')

    def pop(self):
        return self.queue.popleft() if self.queue else ''


class RepairTrace:
    """Own one simulated playback path and an append-only user input cursor."""

    def __init__(self, source, pair, variant, split, tokenizer, config, phrases, heldout=False):
        self.source, self.pair, self.variant, self.split = source, pair, variant, split
        self.tokenizer, self.config, self.phrases, self.heldout = tokenizer, config, phrases, heldout
        self.identity = f'{VERSION}:{source["source_id"]}:{pair}:{variant}:{"heldout" if heldout else "standard"}'
        self.rng = rng_for(config['seed'], self.identity)
        self.natural = ReleaseStream(source['texts'][pair], tokenizer,
                                     rng_for(config['seed'], source['source_id'], pair, 'natural'), config)
        self.natural_prefix, self.user, self.committed = '', '', 0
        self.history = [dict(role='user' if i % 2 == 0 else 'assistant', text=t)
                        for i, t in enumerate(source['texts'][:pair])]
        self.active, self.terminal, self.pending = None, None, []
        self.rows, self.events, self.outputs = [], [], []
        self.now, self.empty, self.version, self.turn = 0, 0, 0, 1
        self.extra, self.extra_kind, self.extra_prefix = None, None, ''
        self.extra_anchors, self.extra_done, self.extra_terminal = [], False, False
        self.has_stopped, self.natural_stops = False, 0
        self.opportunity_assigned, self.plan, self.plan_phase = False, None, None
        self.sampling = Counter()
        self.epoch = 0

    def emit(self, kind, **fields):
        self.events.append(dict(event_seq=len(self.events)+1, kind=kind, occurred_ms=self.now,
                                clock_type='synthetic', **fields))

    def close(self, kind):
        output = self.active
        if not output:
            raise ValueError('No active output')
        if kind == 'finish' and not (output['generation_complete'] and output['played_cursor'] == len(output['offsets'])):
            raise ValueError('Premature finish')
        output.update(status=kind, closed_ms=self.now)
        self.history.append(dict(role='assistant', text=output['generated'], played_text=output['played'],
                                 interrupted=kind == 'stop', completion=kind, output_id=output['output_id']))
        self.terminal = dict(kind=kind, output_id=output['output_id'])
        self.pending.append(dict(self.terminal, **({'marker': '<finish>'} if kind == 'finish' else {})))
        self.emit(kind, output_id=output['output_id'], played_cursor=output['played_cursor'])
        self.active = None

    def progress(self):
        out = self.active
        if not out:
            return
        if not out['generation_complete']:
            count = self.config['assistant_generation_cycle'][out['age'] % 3]
            out['generated_cursor'] = min(len(out['offsets']), out['generated_cursor'] + count)
            out['generated'] = out['text'][:out['offsets'][out['generated_cursor']-1][1]]
            if out['first_packet_ms'] is None:
                out['first_packet_ms'] = self.now
                out['play_at'] = self.now + out['wait'] * 160
            out['generation_complete'] = out['generated_cursor'] == len(out['offsets'])
            if out['generation_complete']:
                self.emit('generation_complete', output_id=out['output_id'])
        if self.now >= out['play_at'] and out['played_cursor'] < out['generated_cursor']:
            if out['played_cursor'] == 0:
                self.emit('playback_started', output_id=out['output_id'])
            out['played_cursor'] += 1
            out['played'] = out['text'][:out['offsets'][out['played_cursor']-1][1]]
        out['age'] += 1
        self.emit('output_progress', output_id=out['output_id'], generated_cursor=out['generated_cursor'],
                  played_cursor=out['played_cursor'], generation_complete=out['generation_complete'])
        if out['generation_complete'] and out['played_cursor'] == len(out['offsets']):
            self.close('finish')

    def start(self, response, background):
        if self.active or not response:
            raise ValueError('Start requires a fresh output and complete response text')
        self.committed = len(self.user)
        self.history.append(dict(role='user', text=self.user))
        self.user = ''
        self.committed = 0
        self.turn += 1
        self.epoch += 1
        offsets = self.tokenizer.backend.encode(response, add_special_tokens=False).offsets
        out = dict(output_id=f'{self.identity}:output-{len(self.outputs)+1}', text=response, offsets=offsets,
                   generated='', played='', generated_cursor=0, played_cursor=0, generation_complete=False,
                   first_packet_ms=None, play_at=float('inf'), wait=self.rng.randint(1, 3), age=0,
                   accepted_ms=self.now, status='open', background=background)
        self.outputs.append(out)
        self.active = out
        self.emit('start_accepted', output_id=out['output_id'], background=background)
        if not self.opportunity_assigned:
            self.opportunity_assigned = True
            self.plan = self.rng.choices(('none', 'backchannel', 'takeover', 'mixed'),
                                         weights=self.config['opportunity_probabilities'])[0]
            if self.variant.startswith('control-'):
                self.plan = self.variant.removeprefix('control-')
            self.plan_phase = ('preparing' if self.variant == 'control-takeover' else
                               'generating' if self.variant in ('control-backchannel', 'control-request', 'control-stop') else
                               self.rng.choice(('preparing', 'generating', 'playback_tail')))
            self.sampling[('contrast_' if self.variant.startswith('control-') else 'base_') + 'allocated_' + self.plan] += 1
            self.emit('opportunity_allocated', plan=self.plan, phase=self.plan_phase)

    def transition(self):
        rows = self.phrases['dev' if self.heldout else 'train']
        return self.rng.choice(rows)['text']

    def schedule_extra(self):
        if not self.active or self.plan in (None, 'none') or self.extra is not None or self.extra_done:
            return
        out = self.active
        phase = 'preparing' if not out['played_cursor'] else 'playback_tail' if out['generation_complete'] else 'generating'
        if phase != self.plan_phase:
            return
        if self.natural.queue or self.user:
            self.sampling['natural_stream_conflict'] += 1
            return
        request = self.rng.random() < self.config['request_probability']
        pool = (HELDOUT_REQUESTS if self.heldout else REQUESTS) if request else (HELDOUT_STOPS if self.heldout else STOPS)
        anchor, text = self.rng.choice(pool)
        if self.variant == 'control-stop':
            anchor, text, request = self.rng.choice(HELDOUT_STOPS if self.heldout else STOPS) + (False,)
        if self.variant == 'control-request':
            anchor, text, request = self.rng.choice(HELDOUT_REQUESTS if self.heldout else REQUESTS) + (True,)
        if self.plan == 'backchannel':
            text, self.extra_kind, anchor = 'Okay.', 'backchannel', ''
            self.extra_terminal = True
        else:
            if self.plan in ('mixed', 'request', 'stop'):
                text = 'Okay. ' + text
            self.extra_kind = 'request' if request else 'stop'
            self.extra_terminal = not request
            self.extra_anchors = [a for a, _ in REQUESTS + HELDOUT_REQUESTS + STOPS + HELDOUT_STOPS]
        self.extra = ReleaseStream(text, self.tokenizer, rng_for(self.config['seed'], self.identity, 'extra'), self.config)
        self.emit('synthetic_user_scheduled', text=text, anchor=anchor, family=self.extra_kind,
                  phase=phase, plan=self.plan)
        self.sampling[('contrast_' if self.variant.startswith('control-') else 'base_') + 'inserted_' + self.plan] += 1

    def update(self, text, version, turn_id):
        if turn_id != self.turn or version <= self.version or text == self.user:
            self.emit('ignored_asr', turn_id=turn_id, version=version)
            return ''
        if not text.startswith(self.user):
            raise ValueError('ASR revisions are outside the append-only contract')
        delta = text[len(self.user):]
        self.user, self.version = text, version
        self.emit('asr_update', text=text, delta=delta, version=version, turn_id=turn_id)
        return delta

    def tick(self):
        self.now = (self.now // 160 + 1)*160
        self.progress()
        self.schedule_extra()
        natural_active = bool(self.natural.queue)
        delta = self.natural.pop() if natural_active else self.extra.pop() if self.extra and self.extra.queue else ''
        origin = 'natural' if natural_active else 'extra' if self.extra and not self.extra_done else 'none'
        if delta:
            delta = self.update(self.user + delta, self.version + 1, self.turn)
            if origin == 'natural':
                self.natural_prefix += delta
            else:
                self.extra_prefix += delta
            self.events[-1]['origin'] = origin
        self.empty = 0 if delta else self.empty + 1
        category, action, response, background = 'no_update', 'keep', None, None
        state = 'Speak' if self.active else 'Listen'
        raw_boundary = complete_prefix(self.user)
        anchors = [a for a, _ in REQUESTS + HELDOUT_REQUESTS + STOPS + HELDOUT_STOPS]
        decidable = bool(delta) and anchor_visible(self.user, anchors)
        if origin == 'natural' and delta and state == 'Speak':
            # Only complete lexical content, visible now, can weakly establish natural continuation.
            words = re.findall(r'\b[A-Za-z]+(?=[\s,.?!;:])', self.user.casefold())
            ambiguous = {'i', 'a', 'an', 'the', 'and', 'but', 'or', 'so', 'well', 'yes', 'okay', 'right', 'uh', 'hm', 'hmm'}
            decidable |= any(w not in ambiguous for w in words)
        if state == 'Speak' and decidable:
            action, category = 'stop', 'interruption'
            if origin == 'natural':
                self.natural_stops += 1
        elif state == 'Speak' and origin == 'extra':
            category = 'backchannel' if not decidable else 'interruption'
        elif state == 'Listen':
            terminal_only = self.extra_terminal and self.extra is not None
            if not delta and raw_boundary and len(self.user) > self.committed and not terminal_only:
                action = 'start'
                category = 'recovery' if self.has_stopped else 'smooth'
                full_natural = not self.natural.queue and self.extra is None
                response = self.source['texts'][self.pair+1] if full_natural else self.transition()
                background = 'real_reply' if full_natural else 'transition'
            else:
                category = 'listen' if delta else 'pause' if self.user and not terminal_only else 'post_output_wait'
        if state == 'Speak' and not delta and self.active['generation_complete']:
            category = 'playback_tail'
        phase = 'idle' if not self.active else 'playing' if self.active['played_cursor'] else 'preparing'
        visible = dict(input_contract=CONTRACT, history=deepcopy(self.history), user_text=self.user,
                       observation=delta, observation_type='text-update' if delta else 'empty-observation',
                       state=state, playback_phase=phase, assistant_visible=self.active['generated'] if self.active else '',
                       played_text=self.active['played'] if self.active else '',
                       assistant_generation_complete=self.active['generation_complete'] if self.active else None,
                       consecutive_empty_observations=self.empty, runtime_events=deepcopy(self.pending),
                       latest_terminal=deepcopy(self.terminal), output_id=self.active['output_id'] if self.active else None,
                       user_version=self.version, user_turn_id=self.turn, cot='')
        self.pending.clear()
        prompt = render_prompt(visible)
        ids = self.tokenizer.encode(prompt) + [self.tokenizer.special[ACTIONS[action]]]
        opportunity = f'{self.identity}:{category}:{self.epoch}'
        row = dict(snapshot_id=f'{self.identity}:{len(self.rows)}', scenario_id=self.identity,
                   source_id=self.source['source_id'], scenario_group=self.source['duplicate_group'],
                   logical_group=f'{self.source["source_id"]}:{self.pair}', split=self.split,
                   category=category, opportunity_id=opportunity, visible_ms=self.now, allowed_visible_ms=self.now,
                   visible=visible, prompt=prompt, input_ids=ids, labels=[-100]*(len(ids)-1)+[ids[-1]],
                   target_action=action, excluded_reason='overlength' if len(ids)>self.config['max_length'] else None,
                   utterance_form='question' if '?' in self.source['texts'][self.pair] else 'declarative',
                   history_position=self.pair, scenario_variant=self.variant,
                   dev_suite='heldout' if self.heldout else 'standard',
                   reply_background=background or (self.active['background'] if self.active else 'none'),
                   annotation=dict(raw_prefix=self.user, raw_complete=raw_boundary, decidable=decidable,
                                   origin=origin, terminal_only=bool(self.extra_terminal and self.extra is not None),
                                   method=BOUNDARY_VERSION), playback_simulated=True)
        self.rows.append(row)
        self.emit('control_request', action=action, snapshot_id=row['snapshot_id'])
        if action == 'start':
            self.start(response, background)
        elif action == 'stop':
            self.emit('stop_requested', output_id=self.active['output_id'])
            self.now += self.config['stop_confirmation_ms']
            self.close('stop')
            self.has_stopped = True
        if self.extra is not None and not self.extra.queue and not self.extra_done:
            self.extra_done = True
            if self.extra_kind == 'backchannel':
                self.history.append(dict(role='user', text=self.user))
                self.user, self.committed = '', 0
                self.turn += 1

    def run(self):
        quiet = 0
        while True:
            self.tick()
            streams_done = not self.natural.queue and (self.extra is None or not self.extra.queue)
            quiet = quiet+1 if streams_done and not self.rows[-1]['visible']['observation'] else 0
            if quiet >= self.config['post_user_windows'] and self.active is None:
                break
            if len(self.rows) > 20000:
                raise ValueError('Trajectory did not close within the CPU safety bound')
        if self.plan not in (None, 'none') and not self.extra:
            self.sampling['unreachable_' + self.plan_phase] += 1
        complete_trajectory_groups(self.rows)
        starts = [e['output_id'] for e in self.events if e['kind']=='start_accepted']
        terminals = [e['output_id'] for e in self.events if e['kind'] in ('stop','finish')]
        if Counter(starts) != Counter(terminals) or len(set(terminals)) != len(terminals):
            raise ValueError('Start/terminal pairing or deduplication failed')
        return dict(scenario_id=self.identity, source_id=self.source['source_id'], split=self.split,
                    events=self.events, outputs=[{k:v for k,v in o.items() if k not in ('offsets','play_at')} for o in self.outputs],
                    sampling=dict(self.sampling), natural_stops=self.natural_stops), self.rows


def load_inputs(legacy):
    manifest = json.loads((legacy/'manifest.json').read_text())
    for name in ('source_records.json','split_index.json','tokenizer.json','tokenizer_config.json'):
        if file_hash(legacy/name) != manifest['files'][name]:
            raise ValueError('Legacy digest mismatch: '+name)
    index = json.loads((legacy/'split_index.json').read_text())
    selected = [i for i in index if i['split'] in ('train','dev')]
    if Counter(i['split'] for i in selected) != {'train':160,'dev':200}:
        raise ValueError('Unexpected source pool')
    groups = defaultdict(set)
    for item in index:
        groups[item['duplicate_group']].add(item['split'])
    if any(len(groups[i['duplicate_group']])!=1 for i in selected):
        raise ValueError('Source isolation failed')
    records = json.loads((legacy/'source_records.json').read_text())
    # Only selected train/dev entries are used below; test text never becomes construction material.
    from tokenizers import Tokenizer
    tokenizer = ControlTokenizer.__new__(ControlTokenizer)
    tokenizer.backend = Tokenizer.from_file(str(legacy/'tokenizer.json'))
    tokenizer.special = dict(manifest['new_token_ids'])
    register_finish(tokenizer)
    return manifest, selected, {i['source_id']:records[i['source_id']] for i in selected}, tokenizer


def choose_pair(source, tokenizer):
    candidates = list(range(4, len(source['texts'])-1, 2))
    return min(candidates, key=lambda p: len(tokenizer.encode(source['texts'][p+1])) +
               len(tokenizer.encode(' '.join(source['texts'][:p]))) * .15)


def source_bundle(source, pair, split, tokenizer, config, phrases):
    traces, rows = [], []
    variants = ['ordinary', 'opportunity']
    for variant in variants:
        trace = RepairTrace(source,pair,variant,split,tokenizer,config,phrases)
        timeline, snapshots = trace.run()
        traces.append(timeline); rows.extend(snapshots)
    if not any(r['target_action']=='stop' for r in rows):
        trace = RepairTrace(source,pair,'control-takeover',split,tokenizer,config,phrases)
        trace.plan_phase = 'preparing'
        timeline, snapshots = trace.run()
        traces.append(timeline); rows.extend(snapshots)
    # A small deterministic subset supplies matched backchannel endings and continuations.
    if int(source['source_id']) % 10 == 0:
        for variant in ('control-backchannel','control-request','control-stop'):
            trace = RepairTrace(source,pair,variant,split,tokenizer,config,phrases)
            timeline,snapshots = trace.run(); traces.append(timeline); rows.extend(snapshots)
    if split == 'dev':
        trace = RepairTrace(source,pair,'control-mixed',split,tokenizer,config,phrases,heldout=True)
        timeline,snapshots = trace.run(); traces.append(timeline); rows.extend(snapshots)
    if split == 'train' and not any(r['target_action'] == 'stop' for r in rows):
        raise ValueError('No causal stop is reachable in this complete source bundle')
    assign_loss_weights(rows,config['loss_policy'])
    return traces, rows


def stratified_select(candidates, limit, minimum):
    buckets = defaultdict(list)
    for item in candidates:
        buckets[(item['form'], item['position'])].append(item)
    for bucket in buckets.values():
        bucket.sort(key=lambda i:(i['windows'],i['tie']))
    selected,used = [],0
    while buckets:
        for key in list(sorted(buckets)):
            item = buckets[key].pop(0)
            if used+item['windows']<=limit:
                selected.append(item); used+=item['windows']
            if not buckets[key]: del buckets[key]
    if len(selected)<minimum:
        raise ValueError(f'Complete source budget conflict: {len(selected)} < {minimum}, windows {used}/{limit}')
    return selected


def build(args):
    started=time.monotonic()
    config=json.loads(args.config.read_text()); phrases=json.loads(args.phrases.read_text())
    if config['seed'] != 20261027 or config['window_ms'] != 160 or config['max_length'] != 2048:
        raise ValueError('Repair input contract differs from the confirmed configuration')
    if not 1 <= config['train_snapshots_max'] <= 100000 or not 1 <= config['pilot_snapshots_max'] <= 10000:
        raise ValueError('Snapshot budget exceeds the confirmed limit')
    if args.output.exists(): raise ValueError('Output must be fresh')
    manifest,index,records,tokenizer=load_inputs(args.legacy)
    for split,expected in (('train',24),('dev',8)):
        if len(phrases[split])!=expected: raise ValueError('Wrong phrase count')
        for phrase in phrases[split]:
            if len(tokenizer.encode(phrase['text']))!=phrase['tokens'] or not 8<=phrase['tokens']<=20:
                raise ValueError('Transition token length changed')
    args.output.mkdir(parents=True)
    cache=args.output/'candidates';cache.mkdir()
    estimate=[]; excluded=[]; aggregate=Counter(); sample=[]
    for ordinal,item in enumerate(index):
        source=records[item['source_id']]
        pair=choose_pair(source,tokenizer)
        try:
            traces,rows=source_bundle(source,pair,item['split'],tokenizer,config,phrases)
        except ValueError as exc:
            excluded.append(dict(source_id=item['source_id'],split=item['split'],reason=str(exc)))
            continue
        record=dict(source_id=item['source_id'],split=item['split'],windows=len(rows),pair=pair,
                    form='question' if '?' in source['texts'][pair] else 'declarative',position=pair,
                    tie=hashlib.sha256(f'{config["seed"]}:{item["source_id"]}'.encode()).hexdigest())
        if any(r['excluded_reason'] for r in rows):
            excluded.append(record|dict(reason='overlength_complete_source',max_tokens=max(len(r['input_ids']) for r in rows)))
        else:
            estimate.append(record)
            with gzip.open(cache/f'{item["source_id"]}.json.gz','wt',encoding='utf-8',compresslevel=1) as f:
                json.dump(dict(traces=traces,rows=rows),f,ensure_ascii=False,separators=(',',':'))
        if ordinal%20==0:
            print(json.dumps(dict(event='cpu_estimate',completed=ordinal+1,planned=len(index),excluded=len(excluded))),flush=True)
        if time.monotonic()-started>config['resources']['timeout_seconds']:
            raise ValueError('CPU estimate time limit exceeded')
        if sum(p.stat().st_size for p in cache.iterdir())>config['resources']['disk_gib']*1024**3:
            raise ValueError('CPU estimate disk limit exceeded')
    write_json(args.output/'estimate.json',dict(candidates=estimate,excluded=excluded,elapsed_seconds=time.monotonic()-started))
    if len([i for i in estimate if i['split']=='dev'])!=200:
        raise ValueError('Not all 200 developer sources fit; exclusions retained for review')
    train=stratified_select([i for i in estimate if i['split']=='train'],config['train_snapshots_max'],config['train_sources_min'])
    pilot=stratified_select(train,config['pilot_snapshots_max'],config['pilot_sources_min'])
    chosen=train+[i for i in estimate if i['split']=='dev']
    pilot_ids={i['source_id'] for i in pilot}; chosen_ids={i['source_id'] for i in chosen}
    write_json(args.output/'selection.json',dict(train=train,pilot=pilot,dev_sources=200,excluded=excluded))
    write_json(args.output/'split_index.json',[i for i in index if i['source_id'] in chosen_ids])
    write_json(args.output/'source_records.json',{key:records[key] for key in chosen_ids})
    handles={s:gzip.open(args.output/f'{s}.jsonl.gz','wt',encoding='utf-8',compresslevel=1) for s in ('train','pilot','dev')}
    counts=defaultdict(Counter);coverage=Counter();sampling=Counter();traces_count=0
    with gzip.open(args.output/'timelines.jsonl.gz','wt',encoding='utf-8',compresslevel=1) as tf:
        try:
            for item in chosen:
                with gzip.open(cache/f'{item["source_id"]}.json.gz','rt',encoding='utf-8') as f:bundle=json.load(f)
                for trace in bundle['traces']:
                    tf.write(json.dumps(trace,ensure_ascii=False,separators=(',',':'))+'\n')
                    traces_count+=1; sampling.update(trace['sampling'])
                    for e in trace['events']:
                        if e['kind']=='synthetic_user_scheduled':coverage[(item['split'],e['family'],e['phase'],e['anchor'])]+=1
                for row in bundle['rows']:
                    audit_row(row,tokenizer)
                    for destination in [item['split']]+(['pilot'] if item['source_id'] in pilot_ids else []):
                        handles[destination].write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
                        counts[destination][row['target_action']]+=1
                if len(sample)<3:sample.append(bundle)
        finally:
            for handle in handles.values():handle.close()
    write_json(args.output/'continuous_examples.json',sample)
    write_json(args.output/'coverage.json',dict(template_phase=[dict(split=k[0],family=k[1],phase=k[2],anchor=k[3],count=v) for k,v in coverage.items()],sampling=dict(sampling)))
    tokenizer.backend.save(str(args.output/'tokenizer.json'))
    token_config=json.loads((args.legacy/'tokenizer_config.json').read_text())
    token_config['added_tokens_decoder']={str(t['id']):{k:v for k,v in t.items() if k!='id'} for t in json.loads(tokenizer.backend.to_str())['added_tokens']}
    token_config['additional_special_tokens']=list(dict.fromkeys(token_config.get('additional_special_tokens',[])+list(tokenizer.special)))
    write_json(args.output/'tokenizer_config.json',token_config)
    # Candidate caches are reproducible intermediates; final complete snapshots remain untouched.
    shutil.rmtree(cache)
    result=dict(version=VERSION,input_contract=CONTRACT,training_allowed=True,complete_trajectories=True,
                model_revision=manifest['model_revision'],new_token_ids=tokenizer.special,
                split_files={s:f'{s}.jsonl.gz' for s in handles},config=config,loss_policy=config['loss_policy'],
                source_dialogues=dict(train=len(train),pilot=len(pilot),dev=200),action_counts={s:dict(c) for s,c in counts.items()},
                complete_traces=traces_count,boundary_version=BOUNDARY_VERSION,abbreviations=ABBREVIATIONS,
                builder_sha256=file_hash(__file__),input_mapper_sha256=file_hash(Path(__file__).with_name('textturn_input.py')),
                config_sha256=file_hash(args.config),phrases_sha256=file_hash(args.phrases),
                legacy_manifest_sha256=file_hash(args.legacy/'manifest.json'),elapsed_seconds=time.monotonic()-started,
                files={p.name:file_hash(p) for p in args.output.iterdir() if p.is_file()})
    write_json(args.output/'manifest.json',result)
    write_json(args.output/'audit.json',dict(status='passed',manifest_sha256=file_hash(args.output/'manifest.json'),
               label_consistency=1.,causal_mapping=True,complete_trajectories=True,old_assets_untouched=True))
    return result


def audit_row(row,tokenizer):
    if row['prompt']!=render_prompt(row['visible']):raise ValueError('Input mapping mismatch')
    if row['input_ids']!=tokenizer.encode(row['prompt'])+[tokenizer.special[ACTIONS[row['target_action']]]]:
        raise ValueError('Tokenization mismatch')
    if row['loss_weight']<=0:raise ValueError('Nonpositive loss')
    annotation=row['annotation']; v=row['visible'];delta=v['observation_type']=='text-update'
    expected='keep'
    if v['state']=='Speak' and delta and annotation['decidable']:expected='stop'
    elif v['state']=='Listen' and not delta and complete_prefix(annotation['raw_prefix']) and annotation['raw_prefix'] and not annotation['terminal_only']:expected='start'
    if row['target_action']!=expected:raise ValueError('Recomputed automatic label mismatch')
    for forbidden in ('source_id','scenario_id','output_id','occurred_ms','published_ms','user_version','plan_phase','raw_complete'):
        if re.search(r'"'+forbidden+r'"\s*:',row['prompt']):raise ValueError('Construction metadata leaked')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=Path('configs/textturn_repair.json'))
    parser.add_argument('--phrases',type=Path,default=Path('configs/textturn_transition_phrases.json'))
    args=parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    print(json.dumps(build(args),ensure_ascii=False,indent=2))
