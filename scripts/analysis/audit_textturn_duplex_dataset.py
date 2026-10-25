"""Audit frozen 160ms data and materialize diagnostic lifecycle boundaries."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys
from transformers import AutoTokenizer
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'training'))
from build_textturn_dataset import strip_terminal, ControlTokenizer
from build_textturn_duplex_dataset import DuplexTrace
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data', type=Path, required=True)
parser.add_argument('--legacy', type=Path, required=True)
args = parser.parse_args()
p = args.data
m=json.loads((p/'manifest.json').read_text())
for root in (p,args.legacy):
    manifest=json.loads((root/'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        h=hashlib.sha256()
        with (root/name).open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024),b''): h.update(block)
        assert h.hexdigest()==expected,(root,name)
assert hashlib.sha256((ROOT / 'scripts/training/build_textturn_duplex_dataset.py').read_bytes()).hexdigest()==m['builder_sha256']
old=args.legacy
idx=json.loads((p/'split_index.json').read_text())
oldidx=json.loads((old/'split_index.json').read_text())
assert idx==[r for r in oldidx if r['split'] in ('train','dev')]
testgroups={r['duplicate_group'] for r in oldidx if r['split']=='test'}
assert not (testgroups & {r['duplicate_group'] for r in idx})
assert {r['duplicate_group'] for r in idx if r['split']=='train'}.isdisjoint({r['duplicate_group'] for r in idx if r['split']=='dev'})
t=AutoTokenizer.from_pretrained(p,local_files_only=True)
for marker, number in m['new_token_ids'].items(): assert t.encode(marker,add_special_tokens=False)==[number]
finish=m['new_token_ids']['<finish>']
assert finish in t.all_special_ids and finish not in m['action_token_ids'].values()
expected={}
snapshot_requests={}
metrics=Counter()
by_split=defaultdict(Counter)
examples=[]
for line in (p/'timelines.jsonl').open():
    trace=json.loads(line)
    sid=trace['scenario_id']; split=trace['split']; ev=trace['events']
    assert [e['event_seq'] for e in ev]==list(range(1,len(ev)+1))
    assert [e['occurred_ms'] for e in ev]==sorted(e['occurred_ms'] for e in ev)
    ncontrols=sum(e['kind']=='control_request' for e in ev)
    snapshot_requests[sid] = [e['event_seq'] for e in ev if e['kind'] == 'control_request']
    nsourcepieces=sum(e['kind']=='control_request' and e['category'] in ('listen','interruption') for e in ev)
    assert trace['sampling']['pause_trials']==nsourcepieces-(1 if trace['variant']=='normal' else 2)
    pauses=[e for e in ev if e['kind']=='pause_inserted']
    assert len(pauses)==trace['sampling'].get('pause_insertions',0)
    assert sum(e['kind']=='control_request' and e['category']=='pause' for e in ev)==sum(e['windows'] for e in pauses)
    assert all(e['remaining_pieces']>0 and 1<=e['windows']<=5 for e in pauses)
    inserted=sum(e['kind']=='backchannel_inserted' for e in ev)
    closed=sum(e['kind']=='backchannel_closed' for e in ev)
    assert inserted==closed==trace['sampling'].get('backchannel_insertions',0)
    raw=''; live_bc=False; bc_first=False; regular=False; active=False; trials=0
    for e in ev:
        kind=e['kind']
        if kind=='backchannel_inserted': live_bc=True; bc_first=True
        if kind in ('asr_update','ignored_asr') and 'text' in e:
            if kind=='asr_update' or e.get('reason')=='whitespace_only': raw=e['text']
            if active and not live_bc: regular=True
        if kind=='control_request':
            expected[(sid,e['event_seq'])]=(e['occurred_ms'],e['state'],e['observation'],strip_terminal(raw))
            if e['state']=='Speak' and not regular:
                if not live_bc or bc_first: trials+=1
                bc_first=False
            if e['category']=='pause':
                assert e['observation']=='<|no-voice|>'
        if kind=='start_accepted': active=True; regular=False; raw=''
        if kind in ('finish','stop','error'): active=False
        if kind=='backchannel_closed': live_bc=False; raw=''
    assert trials==trace['sampling'].get('backchannel_trials',0),(sid,trials,trace['sampling'])
    for o in trace['outputs']:
        terminals=[e for e in ev if e.get('output_id')==o['output_id'] and e['kind'] in ('finish','stop','error')]
        assert len(terminals)==1
        assert o['generated'].startswith(o['played'])
        if o['status']=='finish':
            assert o['generation_complete'] and o['generated']==o['played'] and o['tail_windows']>=6
        if o['status']=='stop':
            stop=next(e for e in ev if e['kind']=='stop_requested')
            assert terminals[0]['occurred_ms']-stop['occurred_ms']==80
    metrics['trajectories']+=1
    metrics['full_control_requests']+=ncontrols
    metrics['pause_events']+=len(pauses)
    metrics['backchannel_events']+=inserted
    by_split[split].update(trace['sampling'])
    if pauses and inserted and len(examples)<2:
        examples.append({'scenario':sid,'pause':pauses[0],
                         'backchannel':next(e for e in ev if e['kind']=='backchannel_inserted')})
forms=defaultdict(Counter)
for split in ('train','dev'):
    seen=set()
    for line in (p/f'{split}.jsonl').open():
        r=json.loads(line)
        assert r['snapshot_id'] not in seen
        seen.add(r['snapshot_id'])
        assert len(r['input_ids'])==len(r['labels'])<=2048
        assert [v for v in r['labels'] if v!=-100]==[m['action_token_ids'][r['target_action']]]
        assert t.encode(r['prompt'],add_special_tokens=False)==r['input_ids'][:-1]
        key=(r['scenario_id'],r['request_event_seq'])
        ms,state,observation,prefix=expected[key]
        assert r['visible_ms']==ms and r['visible']['state']==state
        assert r['visible']['observation']==observation
        assert r['visible']['user_text']==prefix,(r['snapshot_id'],r['visible']['user_text'],prefix)
        assert strip_terminal(prefix)==prefix and strip_terminal(observation)==observation
        assert not ({'judgment','fallback_keep','annotation'} & set(r['visible']))
        for h in r['visible']['history']:
            if h['role']=='user': assert strip_terminal(h['text'])==h['text']
        if r['target_action']=='start':
            assert state=='Listen'
            forms[split][r['utterance_form']]+=1
        if r['target_action']=='stop':
            assert state=='Speak' and observation!='<|no-voice|>'
            assert r['annotation']['judgment']=='non_backchannel'
            assert r['decidable_update_ms']==ms
            metrics['stop_anchors']+=1
        if r['annotation']['fallback_keep']:
            assert r['target_action']=='keep'
        positions=[i for i,v in enumerate(r['input_ids']) if v==finish]
        assert len(positions)==sum(e['kind']=='finish' for e in r['visible']['runtime_events'])
        assert all(r['labels'][i]==-100 for i in positions)
        if positions: metrics['finish_consumption_snapshots']+=1
        if r['category']=='pause': assert r['target_action']=='keep'
        if r['category']=='backchannel': assert r['target_action']=='keep'
        metrics[f'{split}_snapshots']+=1
    assert forms[split]['declarative']==forms[split]['question']
    assert forms[split]['declarative']*3>=sum(forms[split].values())
    assert dict(forms[split])==m['start_forms'][split]
assert metrics['train_snapshots']<=10000
first_decidable = set()
for line in (p / 'prefix_annotations.jsonl').open():
    record = json.loads(line)
    sid, position = record['snapshot_id'].rsplit(':', 1)
    request_seq = snapshot_requests[sid][int(position)]
    _, state, observation, prefix = expected[(sid, request_seq)]
    assert record['annotation']['visible_prefix'] == prefix
    assert record['target_action'] in m['action_token_ids']
    if record['annotation']['judgment'] == 'non_backchannel' and sid not in first_decidable:
        assert record['target_action'] == 'stop' and state == 'Speak' and observation != '<|no-voice|>'
        first_decidable.add(sid)
assert len(first_decidable) == metrics['stop_anchors']
summary=dict(status='passed',metrics=dict(metrics),start_forms=dict(forms),
             sampling={s:dict(v) for s,v in by_split.items()},test_source_groups_used=0,
             legacy_hashes_unchanged=True,tokenizer_reload_verified=True,finish_token_id=finish,
             snapshots_normalized_and_action_masked=True,
             first_decidable_stop_checks=len(first_decidable),
             asset_bytes=sum(f.stat().st_size for f in p.iterdir()),examples=examples)
# Diagnostic fixtures are excluded from the formal train/dev counts.
from tokenizers import Tokenizer
control = ControlTokenizer.__new__(ControlTokenizer)
control.backend = Tokenizer.from_file(str(p / 'tokenizer.json'))
control.special = m['new_token_ids']
source = json.loads((p / 'source_records.json').read_text())[idx[0]['source_id']] | {'source_id': idx[0]['source_id']}
config = m['config'] | {'pause_probability': 0., 'backchannel_probability': 0.}


def begin(name):
    trace = DuplexTrace('diagnostic:' + name, control, source, 'diagnostic', config)
    trace.user_segment(source['texts'][0], 'listen')
    trace.step('smooth', 'start', response=source['texts'][1])
    return trace


def interrupt(trace, text='Add'):
    trace.step('interruption', 'stop', judgment='non_backchannel', advance=False,
               update=dict(text=trace.user + text, version=trace.version + 1, turn_id=trace.turn))


boundaries = []
trace = begin('multiple_outputs')
interrupt(trace)
trace.user_segment(' a practical example', 'continuation')
trace.step('smooth', 'start', response=source['texts'][3])
trace.drain()
trace.step('wait')
trace.user_segment(source['texts'][2], 'next_turn')
trace.step('smooth', 'start', response=source['texts'][3])
interrupt(trace, 'Change')
trace.step('wait')
assert [o['status'] for o in trace.outputs] == ['stop', 'finish', 'stop']
boundaries.append(trace.validate())
trace = begin('finish_before_update')
while not (trace.active['generation_complete'] and trace.active['tail_windows'] == 5):
    trace.speaking_step()
row = trace.step('same_time', 'stop', judgment='non_backchannel',
                 update=dict(text='Add', version=1, turn_id=trace.turn))
assert row['target_action'] == 'keep' and trace.outputs[0]['status'] == 'finish'
boundaries.append(trace.validate())
trace = begin('stop_before_finish')
output_id = trace.active['output_id']
interrupt(trace)
trace.callback(output_id)
assert trace.events[-1]['kind'] == 'stale_callback'
boundaries.append(trace.validate())
trace = begin('repeat_old_text')
for value, version, turn in [('', 1, trace.turn), (source['texts'][0], 2, trace.turn - 1)]:
    row = trace.step('repeat', update=dict(text=value, version=version, turn_id=turn))
    assert row['target_action'] == 'keep' and row['visible']['observation'] == '<|no-voice|>'
trace.drain()
boundaries.append(trace.validate())
trace = begin('playback_error')
trace.callback(trace.active['output_id'], 'error')
assert trace.outputs[0]['status'] == 'error' and not any(e['kind'] == 'finish' for e in trace.events)
boundaries.append(trace.validate())
trace = begin('truncated_output')
trace.speaking_step()
boundaries.append(trace.validate(truncated=True))
assert boundaries[-1]['outputs'][0]['status'] == 'truncated'
(p / 'boundary_cases.json').write_text(json.dumps(boundaries, ensure_ascii=False, indent=2) + '\n')
summary['diagnostic_cases'] = len(boundaries)
summary['diagnostic_cases_sha256'] = hashlib.sha256((p / 'boundary_cases.json').read_bytes()).hexdigest()
(p/'audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
