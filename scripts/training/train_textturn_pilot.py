"""Run finite old/new pilot arms with balanced logical updates and no full stage."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gc
import json
import math
from pathlib import Path
import random
import sys
import time

from build_textturn_dataset import ACTIONS
from score_textturn import metric
from textturn_loss import logical_groups
from train_textturn import (action_logits, check_budget, file_hash, load_controller, read_rows,
                            save_adapter, split_path, write_json)


def score_opportunities(rows, predictions, config):
    """Report complete opportunity diagnostics separately by development background."""
    by_id={p['snapshot_id']:p for p in predictions}
    reports={}
    suites={'all':rows}
    for suite in ('standard','heldout'):
        suites[suite]=[r for r in rows if r.get('dev_suite')==suite]
    real_traces={r['scenario_id'] for r in rows if r.get('reply_background')=='real_reply'}
    suites['real_reply']=[r for r in rows if r['scenario_id'] in real_traces]
    for suite,selected in suites.items():
        groups=defaultdict(list)
        cycles=defaultdict(list)
        for row in selected:
            cycles[(row['scenario_id'],row['opportunity_id'].rsplit(':',1)[-1])].append(row)
        for row in selected:
            if row['category'] in ('smooth','recovery','interruption','pause','backchannel'):
                groups[(row['category'],row['opportunity_id'])].append(row)
        outcomes=defaultdict(list)
        for (category,identity),windows in groups.items():
            expected={'smooth':'start','recovery':'start','interruption':'stop'}.get(category)
            bad=any(r['target_action']=='keep' and by_id[r['snapshot_id']]['action']!='keep' for r in windows)
            anchors=[r for r in windows if r['target_action']==expected] if expected else []
            timely=any(by_id[r['snapshot_id']]['action']==expected and
                       r['visible_ms']-r['allowed_visible_ms']+by_id[r['snapshot_id']]['control_ms']<=1000 for r in anchors)
            if expected and not anchors:continue
            if anchors:
                first=anchors[0]
                cycle=cycles[(first['scenario_id'],first['opportunity_id'].rsplit(':',1)[-1])]
                state='Speak' if expected=='stop' else 'Listen'
                bad=any(r['visible']['state']==state and r['target_action']=='keep' and
                        by_id[r['snapshot_id']]['action']!='keep' for r in cycle)
            passed=timely and not bad if expected else bad
            outcomes[category].append(passed)
            if category=='smooth' and any(r.get('utterance_form')=='declarative' for r in anchors):
                outcomes['declarative'].append(passed)
        report={}
        for name in ('smooth','declarative','interruption','recovery','pause','backchannel'):
            values=outcomes[name];m=metric(sum(values),len(values))
            enough=len(values)>=config['minimum_opportunities']
            limit=config['false_action_max'] if name in ('pause','backchannel') else config['positive_coverage']
            passed=(m['rate']<=limit if name in ('pause','backchannel') else m['rate']>=limit) if enough else False
            report[name]=m|dict(sufficient_evidence=enough,passed=passed)
        durations=sorted(by_id[r['snapshot_id']]['control_ms'] for r in selected)
        p95=durations[max(0,math.ceil(.95*len(durations))-1)] if durations else None
        report['control_ms_p95']=p95
        report['passed']=all(report[n]['passed'] for n in outcomes if n in report) and all(
            report[n]['sufficient_evidence'] for n in ('smooth','declarative','interruption','recovery','pause','backchannel')) and p95 is not None and p95<=config['control_ms_p95_max']
        reports[suite]=report
    return reports


def evaluate(model, rows, token_ids, output, started, config):
    import torch
    output.mkdir(parents=True,exist_ok=False)
    model.eval(); predictions=[]; totals=defaultdict(Counter)
    margins=defaultdict(float)
    with torch.inference_mode(),gzip_predictions(output) as stream:
        for i,row in enumerate(rows):
            torch.cuda.synchronize(); begin=time.monotonic()
            logits=action_logits(model,row['input_ids'][:-1])
            legal=('keep','start') if row['visible']['state']=='Listen' else ('keep','stop')
            indices=[token_ids[list(ACTIONS).index(a)] for a in legal]
            action=legal[int(logits[indices].argmax())]
            torch.cuda.synchronize();elapsed=(time.monotonic()-begin)*1000
            scores={a:float(logits[token_ids[list(ACTIONS).index(a)]]) for a in legal}
            target=row['target_action'];totals[target]['count']+=1;totals[target]['correct']+=action==target
            margins[legal[1]]+=scores[legal[1]]-scores['keep']
            totals[legal[1]]['margin_count']+=1
            record=dict(snapshot_id=row['snapshot_id'],action=action,control_ms=elapsed,legal_logits=scores)
            stream.write(json.dumps(record)+'\n');predictions.append(record)
            if i%500==0:
                check_budget(started,config,output)
                print(json.dumps(dict(event='pilot_evaluation',output=str(output),completed=i+1,planned=len(rows))),flush=True)
    result=dict(by_action={a:dict(count=v['count'],correct=v['correct'],recall=v['correct']/v['count'] if v['count'] else None)
                           for a,v in totals.items()},
                mean_margin_vs_keep={a:v/totals[a]['margin_count'] for a,v in margins.items()},
                opportunities=score_opportunities(rows,predictions,config),rows=len(rows),
                evaluation_mode='offline_given_state_synthetic_diagnostic')
    write_json(output/'summary.json',result)
    return result


def gzip_predictions(output):
    import gzip
    return gzip.open(output/'predictions.jsonl.gz','wt',encoding='utf-8',compresslevel=1)


def verify_dataset(path, expected_revision):
    manifest=json.loads((path/'manifest.json').read_text())
    if not manifest['training_allowed'] or manifest['model_revision']!=expected_revision:
        raise ValueError('Dataset does not permit the frozen model')
    for name,expected in manifest['files'].items():
        if file_hash(path/name)!=expected:raise ValueError('Dataset digest mismatch: '+name)
    return manifest


def train_arm(args, config, name, data, epochs):
    import torch
    from transformers import get_cosine_schedule_with_warmup
    started=time.monotonic();out=args.output/name;out.mkdir()
    manifest=verify_dataset(data,config['model_revision'])
    pilot=read_rows(split_path(data,manifest,'pilot'))
    if len(pilot)>config['pilot_snapshots']:raise ValueError('Pilot window cap exceeded')
    groups=logical_groups(pilot)
    dev=read_rows(split_path(data,manifest,'dev'))
    if name=='old':
        # Only the old optimization control uses a fixed source-isolated diagnostic subset.
        ids=sorted({r['source_id'] for r in dev},key=lambda s:file_hash_string(f'{config["seed"]}:{s}'))[:20]
        dev=[r for r in dev if r['source_id'] in set(ids)]
    write_json(out/'arm_manifest.json',dict(config=config,arm=name,epochs=epochs,pilot_windows=len(pilot),
               pilot_sources=len({r['source_id'] for r in pilot}),logical_updates_per_epoch=len(groups),
               total_logical_updates=len(groups)*epochs,total_window_exposure=len(pilot)*epochs,
               development_windows=len(dev),development_sources=len({r['source_id'] for r in dev}),
               dataset_manifest_sha256=file_hash(data/'manifest.json'),full_training=False,external_evaluation=False))
    torch.manual_seed(config['seed'])
    model,tokenizer,token_ids=load_controller(args.model,data,config)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
    model.enable_input_require_grads()
    parameters=[p for p in model.parameters() if p.requires_grad]
    optimizer=torch.optim.AdamW(parameters,lr=config['learning_rate'],weight_decay=.01)
    steps=len(groups)*epochs
    scheduler=get_cosine_schedule_with_warmup(optimizer,math.ceil(steps*config['warmup_fraction']),steps)
    probe=[next(r for r in pilot if r['target_action']==a) for a in ACTIONS]
    history=[]
    with (out/'updates.jsonl').open('w') as update_log:
        for epoch in range(epochs):
            model.train();order=list(groups);random.Random(config['seed']+epoch).shuffle(order)
            for position,(key,windows,scales) in enumerate(order):
                optimizer.zero_grad(set_to_none=True); losses=defaultdict(float);gradient_checked=False
                for i,(row,scale) in enumerate(zip(windows,scales)):
                    check_budget(started,config,out)
                    if [v for v in row['labels'] if v!=-100]!=[row['input_ids'][-1]]:
                        raise ValueError('Only the final action token may be supervised')
                    logits=action_logits(model,row['input_ids'][:-1])
                    target=torch.tensor([row['input_ids'][-1]],device='cuda')
                    loss=torch.nn.functional.cross_entropy(logits[None,:],target)*scale
                    losses[row['target_action']]+=float(loss.detach());loss.backward()
                    if not gradient_checked:
                        grads=[p.grad for n,p in model.named_parameters() if 'trainable_tokens' in n and p.requires_grad]
                        if not grads or not any(g is not None and torch.isfinite(g).all() and g.abs().sum()>0 for g in grads):
                            raise RuntimeError('Action token gradients are missing or nonfinite')
                        gradient_checked=True
                    if i%250==0:
                        print(json.dumps(dict(event='logical_group_progress',arm=name,epoch=epoch+1,
                                              group=position+1,groups=len(groups),completed=i+1,windows=len(windows))),flush=True)
                norm=float(torch.nn.utils.clip_grad_norm_(parameters,1.,error_if_nonfinite=True))
                optimizer.step();scheduler.step()
                record=dict(epoch=epoch+1,group=list(key),windows=len(windows),actions=dict(Counter(r['target_action'] for r in windows)),
                            norm_before_clip=norm,clip_coefficient=min(1.,1./(norm+1e-6)),effective_loss_by_action=dict(losses),
                            learning_rate=scheduler.get_last_lr()[0])
                update_log.write(json.dumps(record)+'\n');update_log.flush()
            checkpoint=out/f'epoch-{epoch+1}';save_adapter(model,tokenizer,checkpoint)
            pilot_result=evaluate(model,pilot,token_ids,out/f'pilot-epoch-{epoch+1}',started,config)
            dev_result=evaluate(model,dev,token_ids,out/f'dev-epoch-{epoch+1}',started,config)
            history.append(dict(epoch=epoch+1,pilot=pilot_result,dev=dev_result,elapsed_seconds=time.monotonic()-started))
            write_json(out/'history.json',history)
    model.eval()
    with torch.inference_mode():
        before=torch.stack([action_logits(model,r['input_ids'][:-1])[token_ids].cpu() for r in probe])
        saved_rows=model.get_input_embeddings().weight[token_ids].detach().float().cpu().clone()
    del model,optimizer,scheduler,parameters,logits,loss,grads;gc.collect();torch.cuda.empty_cache()
    model,_,loaded_ids=load_controller(args.model,data,config,checkpoint)
    model.eval()
    with torch.inference_mode():
        after=torch.stack([action_logits(model,r['input_ids'][:-1])[loaded_ids].cpu() for r in probe])
        after_rows=model.get_input_embeddings().weight[loaded_ids].detach().float().cpu()
    verified=torch.equal(before,after) and torch.equal(saved_rows,after_rows)
    write_json(out/'reload_verification.json',dict(identical_action_scores=torch.equal(before,after),
                identical_token_rows=torch.equal(saved_rows,after_rows),passed=verified))
    if not verified:raise RuntimeError('Saved pilot checkpoint reload mismatch')
    write_json(out/'summary.json',dict(arm=name,epochs=epochs,logical_updates=steps,window_exposure=len(pilot)*epochs,
                elapsed_seconds=time.monotonic()-started,final=history[-1],reload_passed=True,
                full_training=False,external_evaluation=False))
    del model;gc.collect();torch.cuda.empty_cache()


def file_hash_string(value):
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()


def main(args):
    import torch
    config=json.loads(args.config.read_text())
    if config['full_training'] or config['external_evaluation'] or not 1<=config['epochs']<=5:
        raise ValueError('This runner permits at most five pilot passes and no full stage')
    if args.output.exists():raise ValueError('Run directory must be fresh')
    args.output.mkdir(parents=True)
    torch.set_num_threads(8)
    write_json(args.output/'run_manifest.json',dict(config=config,started_unix=time.time(),gpu=torch.cuda.get_device_name(0),
               model_weights_sha256=file_hash(args.model/'model.safetensors'),old_data=str(args.old_data),new_data=str(args.data)))
    train_arm(args,config,'old',args.old_data,min(2,config['epochs']))
    train_arm(args,config,'repaired',args.data,config['epochs'])
    write_json(args.output/'completed.json',dict(status='completed',full_training=False,external_evaluation=False))
    print(json.dumps(dict(event='finite_pilot_training_finished')),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--old-data',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=Path('configs/textturn_repair_pilot.json'))
    parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args())
