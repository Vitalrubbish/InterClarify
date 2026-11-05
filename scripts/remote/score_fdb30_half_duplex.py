"""Score immutable FDB30 live recordings with frozen official v1.0 rules."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from score_duplex import (SCORING_COMMIT, align, behavior, compare_official, digest,
                          scoring_view, validate_recording)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run','output','assets','fdb-repo'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if not (Path(sys.prefix)/'conda-meta/history').is_file():
        raise RuntimeError('Use remote conda scoring environment')
    if args.output.resolve().is_relative_to(args.run.resolve()):
        raise ValueError('Keep scoring separate from immutable inference evidence')
    args.output.mkdir(parents=True,exist_ok=False)
    import torch
    import soundfile as sf
    import nemo.collections.asr as nemo_asr
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.83)
    commit=subprocess.check_output(['git','-C',str(args.fdb_repo),'rev-parse','HEAD'],text=True).strip()
    if commit!=SCORING_COMMIT:
        raise ValueError('Official FDB source revision differs')
    report=json.loads((args.run/'result.json').read_text())
    manifest=json.loads((args.run/'input_manifest.json').read_text())
    if not report['passed'] or len(report['cases'])!=30 or report['scope']!='fixed_fdb30':
        raise ValueError('All 30 inference records must be present and complete')
    verification=json.loads((args.assets/'scoring-models/download_verification.json').read_text())
    if not verification['passed']:
        raise ValueError('Scoring assets not verified')
    entry=next(v for v in verification['files'] if v['file'].endswith('.nemo'))
    archive=args.assets/'scoring-models/parakeet-tdt'/entry['file']
    if digest(archive)!=entry['sha256']:
        raise ValueError('Parakeet archive hash mismatch')
    model=nemo_asr.models.ASRModel.restore_from(str(archive),map_location=torch.device('cuda:0')).eval()
    results=[]
    by_id={r['case_id']:r for r in report['cases']}
    for sample in manifest['samples']:
        subset,identifier=sample['subset'],sample['id']
        folder=args.run/'samples'/subset/identifier
        record=by_id[sample['case_id']]
        validate_recording(folder,record['recording'])
        source=Path(sample['input'])
        if digest(source)!=sample['files']['input.wav']:
            raise ValueError('Input audio changed')
        target=args.output/'alignments'/subset/identifier
        target.mkdir(parents=True)
        label='turn_taking.json' if sample['task']=='smooth_turn_taking' else (
            'interrupt.json' if sample['task']=='user_interruption' else 'pause.json')
        if digest(source.parent/label)!=sample['files'][label]:
            raise ValueError('Scoring annotation changed')
        shutil.copyfile(source.parent/label,target/label)
        scoring_view(folder/'output.wav',target/'output.wav',sf.info(source))
        annotation=json.loads((target/label).read_text())
        offset=annotation[0]['timestamp'][1] if sample['task']=='user_interruption' else 0
        origin=annotation[0]['timestamp'][0] if sample['task']=='smooth_turn_taking' else (
            offset if sample['task']=='user_interruption' else None)
        with torch.inference_mode():
            transcript=align(model,target/'output.wav',offset)
        (target/'output.json').write_text(json.dumps(transcript,indent=2)+'\n')
        results.append({'case_id':sample['case_id'],'subset':subset,'id':identifier,
                        **behavior(transcript['chunks'],origin),'transcript':transcript['text'],
                        'first_word_seconds':transcript['chunks'][0]['timestamp'][0] if transcript['chunks'] else None,
                        'raw_first_word_latency':transcript['chunks'][0]['timestamp'][0]-origin
                            if transcript['chunks'] and origin is not None else None})
        (args.output/'progress.json').write_text(json.dumps(results,indent=2)+'\n')
    del model
    torch.cuda.empty_cache()
    aggregates=[]
    for subset in dict.fromkeys(s['subset'] for s in manifest['samples']):
        rows=[r for r in results if r['subset']==subset]
        latencies=[r['latency'] for r in rows if r['latency'] is not None]
        group={'subset':subset,'n':len(rows),'successes':sum(r['tor'] for r in rows),
            'tor':sum(r['tor'] for r in rows)/len(rows),'latency_n':len(latencies),
            'latency_mean':sum(latencies)/len(latencies) if latencies else None}
        group['official_comparison']=compare_official(args.fdb_repo,subset,
            args.output/'alignments'/subset,group)
        aggregates.append(group)
    summary={'scope':'fixed_fdb30_not_full_benchmark','scoring_commit':commit,
             'parakeet_sha256':entry['sha256'],'rows':results,'aggregates':aggregates,
             'scoring_window':'zero_to_original_input_end','judge_status':'excluded_by_user',
             'backchannel':'not_in_fdb30','inference_manifest_sha256':digest(args.run/'input_manifest.json')}
    path=args.output/'summary.json'
    path.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({'aggregates':aggregates,'judge_status':summary['judge_status']}),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
