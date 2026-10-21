"""Freeze, replay and score the complete two selected FDB v1.0 axes."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

AXES = {
    'candor_turn_taking': ('smooth_turn_taking', 119, 'turn_taking.json'),
    'synthetic_user_interruption': ('user_interruption', 200, 'interrupt.json'),
}


def digest(path):
    """Hash a file with bounded temporary memory."""
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    """Persist structured evidence without replacing old run directories."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def freeze(root, manifest, fdb_repo):
    """Freeze every expected input and annotation across both complete axes."""
    import soundfile as sf
    if manifest.exists():
        raise FileExistsError(manifest)
    samples, axes = [], {}
    for subset, (task, count, annotation) in AXES.items():
        directories = sorted(p for p in (root/subset).iterdir() if p.is_dir())
        if len(directories) != count:
            raise ValueError(f'{subset}: expected {count} directories, got {len(directories)}')
        seconds = 0.0
        for directory in directories:
            if directory.name in ('.', '..') or not (directory/'input.wav').is_file():
                raise ValueError('Missing or unsafe full-corpus input: '+str(directory))
            info = sf.info(str(directory/'input.wav'))
            metadata = json.loads((directory/annotation).read_text())
            times = metadata[0]['timestamp']
            anchor = float(times[1] if task == 'user_interruption' else times[0])
            if not 0 <= anchor <= info.duration or info.duration <= 0:
                raise ValueError('Invalid reference anchor: '+str(directory))
            files = {name: {'bytes': (directory/name).stat().st_size,
                            'sha256': digest(directory/name)}
                     for name in ('input.wav', annotation)}
            samples.append({'subset':subset,'task':task,'id':directory.name,
                'input':str((directory/'input.wav').relative_to(root)),
                'audio_seconds':info.duration,'files':files})
            seconds += info.duration
        axes[subset] = {'task':task,'sessions':count,'audio_seconds':seconds}
    commit = subprocess.check_output(['git','-C',str(fdb_repo),'rev-parse','HEAD'],text=True).strip()
    result = {'schema_version':1,'corpus':'FDB v1.0 complete selected axes',
              'remote_root':str(root.resolve()),'fdb_commit':commit,'axes':axes,
              'sessions':len(samples),'samples':samples}
    manifest.parent.mkdir(parents=True,exist_ok=True)
    write_json(manifest,result)
    print(json.dumps({'manifest_sha256':digest(manifest),'sessions':len(samples),'axes':axes}),flush=True)
    return result


def stage(manifest, output):
    """Verify the full inventory before copying inputs into a fresh run tree."""
    data = json.loads(manifest.read_text())
    root = Path(data['remote_root'])
    checked, identities = [], set()
    for sample in data['samples']:
        subset, sid = sample['subset'], sample['id']
        if subset not in AXES or Path(sid).name != sid or sid in ('.','..'):
            raise ValueError('Unsafe sample identity')
        identity = (subset,sid)
        if identity in identities:
            raise ValueError('Duplicate sample identity')
        identities.add(identity)
        expected_names = {'input.wav',AXES[subset][2]}
        if set(sample['files']) != expected_names:
            raise ValueError('Unexpected input inventory')
        for name, record in sample['files'].items():
            path = root/subset/sid/name
            if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
                raise ValueError('Frozen file changed: '+str(path))
            checked.append((path,Path(subset)/sid/name))
    for subset, (_,count,_) in AXES.items():
        actual = {(subset,p.name) for p in (root/subset).iterdir() if p.is_dir()}
        frozen = {i for i in identities if i[0]==subset}
        if actual != frozen or len(frozen)!=count:
            raise ValueError('Full corpus coverage changed: '+subset)
    if len(identities) != sum(v[1] for v in AXES.values()):
        raise ValueError('Unexpected session count')
    output.mkdir(parents=True,exist_ok=False)
    for source, relative in checked:
        destination = output/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
    print(json.dumps({'manifest_sha256':digest(manifest),'sessions':len(identities),'files':len(checked)}),flush=True)


async def infer(args):
    """Use the existing real-time driver for every session without sampling."""
    from duplex_a4_replay import run_fdb_batch
    config = json.loads(args.config.read_text())
    assert config['tts']['params']['max_wait_ms']==300
    assert config['tts']['params']['continuation_wait_ms']==1200
    assert config['service_config']['duplex_kv_cache_enabled'] is True
    assert config['service_config']['duplex_micro_turn_seconds']==.6
    config['asr']['params']['base_url']=args.asr_url
    config['tts']['params']['base_url']=args.tts_url
    config['service_config']['duplex_timeout_seconds']=120
    args.output.mkdir(parents=True,exist_ok=False)
    runtime = args.output/'runtime.json'
    write_json(runtime,config)
    rows=[]
    for subset,(task,count,_) in AXES.items():
        parameters=SimpleNamespace(config=runtime,model_url=args.model_url,
            out=args.output/'driver'/subset,fdb_input_root=args.input/subset,
            fdb_output_root=args.output/'fdb'/subset,fdb_limit=0,fdb_tail_seconds=5.0,
            fdb_tail_audio=True,timeout=240.0,server_timeout=120.0)
        result=await run_fdb_batch(parameters)
        rows.append({'subset':subset,'task':task,'expected':count,'sessions':len(result['samples']),
                     'transport_status':result['status']})
        write_json(args.output/'progress.json',rows)
        print(json.dumps(rows[-1]),flush=True)
    passed=all(r['sessions']==r['expected'] and r['transport_status']=='PASS' for r in rows)
    write_json(args.output/'summary.json',{'transport_passed':passed,'axes':rows,
        'sessions':sum(r['sessions'] for r in rows),'official_scoring':'pending'})
    return 0 if passed else 1


def preflight_judge(key_file, base_url, model):
    """Validate existing evaluator credentials/model without logging secrets."""
    from openai import OpenAI
    from run_fdb_llm_judge import read_api_key
    client=OpenAI(api_key=read_api_key(key_file,os.environ),base_url=base_url,timeout=30,max_retries=1)
    client.models.list()
    result=client.chat.completions.create(model=model,messages=[{'role':'user','content':'Reply with OK.'}],
                                          max_tokens=8,seed=0)
    if not result.choices or not result.choices[0].message.content:
        raise RuntimeError('Judge preflight produced no content')
    print(json.dumps({'judge_model':model,'judge_base_url':base_url,'available':True}),flush=True)


def official_step(command, log, environment, cwd, seconds=1800):
    """Stream one official subprocess into a bounded stage log."""
    with log.open('w') as stream:
        try:
            result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,
                env=environment,cwd=cwd,timeout=seconds,check=False)
            return result.returncode
        except subprocess.TimeoutExpired:
            stream.write('\nOfficial stage exceeded its time budget.\n')
            return 124


def timing_metrics(root, task):
    """Apply the pinned official TOR/latency rules and retain per-case evidence."""
    annotation='interrupt.json' if task=='user_interruption' else 'turn_taking.json'
    rows=[]
    for output in sorted(root.glob('*/output.json')):
        metadata=json.loads((output.parent/annotation).read_text())
        anchor=float(metadata[0]['timestamp'][1 if task=='user_interruption' else 0])
        chunks=json.loads(output.read_text())['chunks']
        duration=(chunks[-1]['timestamp'][-1]-chunks[0]['timestamp'][0]) if chunks else 0
        take_turn=bool(chunks) and (duration>=1 or len(chunks)>3)
        raw=chunks[0]['timestamp'][0]-anchor if take_turn else None
        rows.append({'sample':output.parent.name,'take_turn':int(take_turn),
            'raw_latency':raw,'official_latency':max(0,raw) if raw is not None else None})
    latencies=[r['official_latency'] for r in rows if r['take_turn']]
    return {'samples':rows,'scores':{
        'average_take_turn':sum(r['take_turn'] for r in rows)/len(rows) if rows else None,
        'average_latency':sum(latencies)/len(latencies) if latencies else None}}


def score(args):
    """Align complete outputs, score timing, and honor explicitly deferred judging."""
    from run_fdb_llm_judge import prepare_work_repo, read_api_key, parse_scores
    args.output.mkdir(parents=True,exist_ok=False)
    rows=[]
    for subset,(task,count,_) in AXES.items():
        root=args.input/subset
        wavs=list(root.glob('*/output.wav'))
        if len(wavs)!=count:
            raise ValueError(f'{subset}: missing inference outputs ({len(wavs)}/{count})')
        out=args.output/task
        out.mkdir()
        work=prepare_work_repo(args.fdb_repo,out,args.judge_model)
        environment=dict(os.environ)
        environment.pop('PYTHONNOUSERSITE',None)
        environment.update(NUMBA_CUDA_USE_NVIDIA_BINDING='0',HF_HUB_OFFLINE='1')
        align_task='user_interruption' if task=='user_interruption' else 'default'
        align=official_step([str(args.scorer_python),str(work/'get_transcript/asr.py'),
            '--root_dir',str(root),'--task',align_task,'--audio_name','output.wav'],
            out/'alignment.log',environment,str(out))
        aligned=len(list(root.glob('*/output.json')))
        evaluation=None
        timings=None
        scores={}
        deferred=task=='user_interruption' and args.defer_judge
        judge_status='deferred_by_user' if deferred else ('not_required' if task=='smooth_turn_taking' else 'pending')
        if align==0 and aligned==count:
            timings=timing_metrics(root,task)
            write_json(out/'timing_metrics.json',timings)
            scores=dict(timings['scores'])
            if deferred:
                scores['average_rating']=None
            else:
                if task=='user_interruption':
                    environment['OPENAI_API_KEY']=read_api_key(args.key_file,os.environ)
                    environment['OPENAI_BASE_URL']=args.base_url
                evaluation=official_step([str(args.scorer_python),str(work/'evaluation/evaluate.py'),
                    '--task',task,'--root_dir',str(root)],out/'evaluation.log',environment,str(out))
                official=parse_scores(out/'evaluation.log')
                for name in ('average_take_turn','average_latency'):
                    if name in official and scores[name] is not None and abs(official[name]-scores[name])>1e-8:
                        raise ValueError('Official/recomputed timing discrepancy: '+name)
                scores.update(official)
                if task=='user_interruption':
                    judge_status='complete' if evaluation==0 and 'average_rating' in official else 'failed'
        timing_passed=align==0 and aligned==count and timings is not None and len(timings['samples'])==count
        row={'task':task,'subset':subset,'expected':count,'aligned':aligned,'alignment_rc':align,
             'evaluation_rc':evaluation,'ratings':len(list(root.glob('*/rating.json'))),
             'judge_model':args.judge_model if task=='user_interruption' and not deferred else None,
             'judge_status':judge_status,'scores':scores,'timing_passed':timing_passed,
             'timing_source':'recomputed_pinned_official_rules' if deferred else 'official_evaluator_and_rule_crosscheck'}
        row['requested_scope_passed']=timing_passed and (deferred or evaluation==0)
        rows.append(row)
        write_json(args.output/'summary.json',{'axes':rows,
            'requested_scope_passed':all(r['requested_scope_passed'] for r in rows),
            'full_scoring_complete':all(r['requested_scope_passed'] and r['judge_status']!='deferred_by_user' for r in rows)})
        print(json.dumps(row),flush=True)
    return 0 if all(r['requested_scope_passed'] for r in rows) else 1


def main():
    """Dispatch bounded preparation, full inference and official scoring stages."""
    from run_fdb_llm_judge import DEFAULT_BASE_URL, DEFAULT_JUDGE_MODEL
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    freeze_parser=sub.add_parser('freeze')
    for name in ('root','manifest','fdb-repo'):
        freeze_parser.add_argument('--'+name,type=Path,required=True)
    stage_parser=sub.add_parser('stage')
    for name in ('manifest','output'):
        stage_parser.add_argument('--'+name,type=Path,required=True)
    replay=sub.add_parser('infer')
    for name in ('input','output','config'):
        replay.add_argument('--'+name,type=Path,required=True)
    for name in ('asr-url','tts-url','model-url'):
        replay.add_argument('--'+name,required=True)
    for command in ('preflight-judge','score'):
        target=sub.add_parser(command)
        target.add_argument('--key-file',type=Path,required=True)
        target.add_argument('--base-url',default=DEFAULT_BASE_URL)
        target.add_argument('--judge-model',default=DEFAULT_JUDGE_MODEL)
        if command=='score':
            target.add_argument('--defer-judge',action='store_true')
            for name in ('input','output','fdb-repo','scorer-python'):
                target.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if args.command=='freeze':
        freeze(args.root,args.manifest,args.fdb_repo)
    elif args.command=='stage':
        stage(args.manifest,args.output)
    elif args.command=='infer':
        raise SystemExit(asyncio.run(infer(args)))
    elif args.command=='preflight-judge':
        preflight_judge(args.key_file,args.base_url,args.judge_model)
    else:
        raise SystemExit(score(args))


if __name__=='__main__':
    main()
