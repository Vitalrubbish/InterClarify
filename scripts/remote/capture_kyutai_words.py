"""Capture native Kyutai Word messages for the five frozen reference inputs."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time


def sha256(path):
    """Hash a frozen input or a compact capture."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def capture(url, sample, output):
    """Send real audio on its clock and retain the original server messages."""
    import msgpack
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    import websockets

    path=Path(sample['path'])
    if sha256(path)!=sample['sha256']:
        raise ValueError(f'Audio changed: {path}')
    audio,rate=sf.read(path,dtype='float32',always_2d=True)
    pcm=resample_poly(audio.mean(axis=1),24000,rate).astype('float32')
    audio_seconds=len(pcm)/24000
    pcm=np.concatenate([pcm,np.zeros(48000,dtype='float32')])
    messages=[]
    sends=[]
    async with websockets.connect(url,max_size=8<<20,open_timeout=30,
                                  extra_headers={'kyutai-api-key':'public_token'}) as ws:
        started=time.monotonic()
        async def receive():
            async for raw in ws:
                message=msgpack.unpackb(raw,raw=False)
                messages.append({'arrival_seconds':time.monotonic()-started,'message':message})
                if message.get('type')=='Error':
                    raise RuntimeError(f'Kyutai rejected capture: {message}')
        receiver=asyncio.create_task(receive())
        try:
            for offset in range(0,len(pcm),1920):
                target=offset/24000
                await asyncio.sleep(max(0,started+target-time.monotonic()))
                if receiver.done():
                    receiver.result()
                    raise RuntimeError('Kyutai connection closed before capture completed')
                actual=time.monotonic()-started
                await ws.send(msgpack.packb({'type':'Audio','pcm':pcm[offset:offset+1920].tolist()},
                                          use_bin_type=True,use_single_float=True))
                sends.append({'target_seconds':target,'sent_seconds':actual,
                              'drain_silence':offset>=round(audio_seconds*24000)})
            await asyncio.sleep(2)
            if receiver.done():receiver.result()
        finally:
            receiver.cancel()
            await asyncio.gather(receiver,return_exceptions=True)
            output.write_text(json.dumps({'audio':sample,'audio_seconds':audio_seconds,
                'drain_silence_seconds':2,'receive_tail_seconds':2,
                'sends':sends,'messages':messages},indent=2))
    words=[{'type':'Word','text':row['message']['text'],'arrival_seconds':row['arrival_seconds']}
           for row in messages if row['message'].get('type')=='Word']
    if not any(row['text'].strip() for row in words):
        raise RuntimeError('Capture produced no native Word messages')
    return {'word_events':words,'source_capture_sha256':sha256(output),
            'source_capture_path':str(output),'audio_sha256':sample['sha256'],
            'max_send_lateness_seconds':max(row['sent_seconds']-row['target_seconds'] for row in sends)}


async def main(args):
    """Warm one dev recording, then capture exactly the five frozen test inputs."""
    source=json.loads(args.manifest.read_text())
    samples=[row for row in source['samples'] if row['split']=='test']
    if len(samples)!=5:raise ValueError('Expected exactly five frozen test recordings')
    args.output.mkdir(parents=True,exist_ok=False)
    dev=next(row for row in source['samples'] if row['split']=='dev')
    await capture(args.url,dev,args.output/'warmup.json')
    manifest={'input_contract':'kyutai_word_strip_then_space_join',
              'source_manifest_sha256':sha256(args.manifest),
              'server_binary_sha256':sha256(args.server_binary),
              'server_config_sha256':sha256(args.server_config),'samples':[]}
    for index,sample in enumerate(samples,1):
        result=await capture(args.url,sample,args.output/f'historical-{index}.json')
        result.update(id=f'historical-{index}',sample_id=sample['sample_id'],
                      duration_seconds=sample['boundary_seconds']+12)
        manifest['samples'].append(result)
        (args.output/'word_manifest.json').write_text(json.dumps(manifest,indent=2))
        print(json.dumps({'case':result['id'],'words':len(result['word_events'])}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--server-binary',type=Path,required=True)
    parser.add_argument('--server-config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    asyncio.run(main(parser.parse_args()))
