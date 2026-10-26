"""Independently check frozen complete repair data before submitting a pilot job."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import resource
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'training'))
from build_textturn_dataset import ACTIONS
from repair_textturn_dataset import (audit_row, file_hash, complete_prefix, anchor_visible, REQUESTS,
                                     HELDOUT_REQUESTS, STOPS, HELDOUT_STOPS)
from textturn_input import render_prompt
from textturn_loss import logical_groups


def check_trace(trace, stats):
    active=None;starts=Counter();closes=Counter();previous={};requests=[]
    progress=defaultdict(list)
    for event in trace['events']:
        kind=event['kind'];identity=event.get('output_id')
        if kind=='asr_update':
            assert 1 <= len(stats['tokenizer'].encode(event['delta'], add_special_tokens=False).ids) <= 2
        if kind=='start_accepted':
            assert active is None,'Concurrent output owners'
            active=identity;starts[identity]+=1
        elif kind in ('finish','stop'):
            assert active==identity,'Terminal did not match active output'
            active=None;closes[identity]+=1
            if kind=='finish':
                last=progress[identity][-1]
                assert last['generation_complete'] and last['generated_cursor']==last['played_cursor']
            else:
                assert event['occurred_ms']-previous[identity]==80,'Stop confirmation changed'
        elif kind=='stop_requested':
            assert active==identity
            previous[identity]=event['occurred_ms']
        elif kind=='output_progress':
            assert active==identity
            old=progress[identity][-1] if progress[identity] else dict(generated_cursor=0,played_cursor=0)
            assert 0<=event['played_cursor']-old['played_cursor']<=1
            assert event['played_cursor']<=event['generated_cursor']
            assert 0<=event['generated_cursor']-old['generated_cursor']<=3
            progress[identity].append(event)
        elif kind=='control_request':requests.append(event['snapshot_id'])
        elif kind=='synthetic_user_scheduled':
            stats['template_phase'][(trace['split'],event['family'],event['phase'],event['anchor'])]+=1
            if event['family']!='backchannel':assert anchor_visible(event['text'],[event['anchor']])
    assert active is None and starts==closes and all(n==1 for n in closes.values())
    for output in trace['outputs']:
        assert output['status'] in ('finish','stop')
        assert output['played_cursor']<=output['generated_cursor']
        assert output['text'].startswith(output['generated']) and output['generated'].startswith(output['played'])
        if output['status']=='finish':assert output['text']==output['played']
    stats['natural_stops'][trace['split']]+=trace['natural_stops']
    return requests


def check_rows(path, split, stats):
    counts=Counter();sources=set();last_scenario=None;position=0;previous_time=0
    bundle=[];bundle_source=None;requests=[]
    with gzip.open(path,'rt',encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line);source=row['source_id'];sources.add(source)
            if source!=bundle_source and bundle:
                if split!='dev':logical_groups(bundle)
                bundle=[]
            bundle_source=source;bundle.append(row)
            if row['scenario_id']!=last_scenario:
                last_scenario=row['scenario_id'];position=0;previous_time=0
            assert int(row['snapshot_id'].rsplit(':',1)[-1])==position
            assert row['visible_ms']-previous_time==160
            position+=1;previous_time=row['visible_ms']
            assert row['excluded_reason'] is None and len(row['input_ids'])<=2048 and row['loss_weight']>0
            assert row['labels']==[-100]*(len(row['input_ids'])-1)+[row['input_ids'][-1]]
            assert row['prompt']==render_prompt(row['visible'])
            v=row['visible'];a=row['annotation'];delta=v['observation_type']=='text-update'
            assert delta==bool(v['observation'])
            assert a['raw_complete']==complete_prefix(a['raw_prefix'])
            expected='keep'
            if v['state']=='Speak' and delta and a['decidable']:expected='stop'
            if v['state']=='Listen' and not delta and a['raw_complete'] and a['raw_prefix'] and not a['terminal_only']:expected='start'
            assert row['target_action']==expected
            if expected=='stop':
                stats['stop_phase'][(split,v['playback_phase'],v['assistant_generation_complete'])]+=1
            assert row['input_ids'][-1]==stats['token_ids'][ACTIONS[expected]]
            assert row['input_ids'].count(stats['token_ids']['<finish>'])==sum(e['kind']=='finish' for e in v['runtime_events'])
            for field in ('output_id','source_id','scenario_id','occurred_ms','published_ms','user_version','raw_complete'):
                assert '"'+field+'":' not in row['prompt']
            counts[expected]+=1;requests.append(row['snapshot_id'])
            stats['form_position'][(split,row['utterance_form'],row['history_position'])]+=1
    if split!='dev':logical_groups(bundle)
    return dict(sources=len(sources),source_ids=sources,windows=sum(counts.values()),actions=dict(counts)),requests


def audit(args):
    p=args.data;m=json.loads((p/'manifest.json').read_text())
    for name,expected in m['files'].items():assert file_hash(p/name)==expected,name
    assert file_hash(Path(__file__).resolve().parents[1]/'training'/'repair_textturn_dataset.py')==m['builder_sha256']
    assert file_hash(Path(__file__).resolve().parents[1]/'training'/'textturn_input.py')==m['input_mapper_sha256']
    from tokenizers import Tokenizer
    stats=dict(tokenizer=Tokenizer.from_file(str(p/'tokenizer.json')),template_phase=Counter(),stop_phase=Counter(),natural_stops=Counter(),form_position=Counter(),token_ids=m['new_token_ids'])
    all_requests=set();trace_count=0
    with gzip.open(p/'timelines.jsonl.gz','rt',encoding='utf-8') as stream:
        for line in stream:
            trace=json.loads(line);requests=check_trace(trace,stats)
            assert not all_requests.intersection(requests)
            all_requests.update(requests);trace_count+=1
    results={};row_ids={}
    for split in ('train','pilot','dev'):
        results[split],ids=check_rows(p/m['split_files'][split],split,stats)
        assert len(ids)==len(set(ids));row_ids[split]=set(ids)
        assert results[split]['actions']==m['action_counts'][split]
    assert results['train']['sources']>=100 and results['train']['windows']<=100000
    assert results['pilot']['sources']>=20 and results['pilot']['windows']<=10000
    assert results['dev']['sources']==200
    assert results['pilot']['source_ids']<=results['train']['source_ids']
    assert not results['train']['source_ids']&results['dev']['source_ids']
    assert row_ids['pilot']<=row_ids['train']
    assert row_ids['train']|row_ids['dev']==all_requests
    selection=json.loads((p/'selection.json').read_text())
    for split in ('train','pilot'):
        forms=Counter(item['form'] for item in selection[split])
        assert forms['question']==forms['declarative'], 'Source form balance changed'
    estimate=json.loads((p/'estimate.json').read_text())
    forms=Counter(item['form'] for item in estimate['candidates'] if item['split']=='dev')
    assert forms=={'question':100,'declarative':100}
    index=json.loads((p/'split_index.json').read_text());groups=defaultdict(set)
    for item in index:groups[item['duplicate_group']].add(item['split'])
    assert all(len(s)==1 for s in groups.values())
    train_anchors={k[3] for k in stats['template_phase'] if k[0]=='train' and k[1]!='backchannel'}
    assert {a for a,_ in REQUESTS+STOPS}<=train_anchors,'A training template was unreachable'
    heldout_anchors={k[3] for k in stats['template_phase'] if k[0]=='dev' and k[1]!='backchannel'}
    assert {a for a,_ in HELDOUT_REQUESTS+HELDOUT_STOPS}<=heldout_anchors
    assert any(k[0]=='train' and k[1]=='preparing' and v>0 for k,v in stats['stop_phase'].items())
    for result in results.values():result.pop('source_ids')
    result=dict(status='passed',manifest_sha256=file_hash(p/'manifest.json'),splits=results,
                complete_traces=trace_count,label_consistency=1.,input_contract=m['input_contract'],
                training_config_sha256=file_hash(args.config),loss_helper_sha256=file_hash(Path(__file__).resolve().parents[1]/'training'/'textturn_loss.py'),
                coverage={name:{str(k):v for k,v in counter.items()} for name,counter in stats.items() if isinstance(counter,Counter)},
                limitations=['Synthetic clocks and weak lexical labels are not real ASR or semantic gold labels.',
                             'Offline teacher-state scoring does not establish closed-loop deployment quality.'])
    (p/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=Path('configs/textturn_repair_pilot.json'))
    args=parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    audit(args)
