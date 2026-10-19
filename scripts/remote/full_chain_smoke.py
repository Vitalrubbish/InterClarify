"""Measure real Nemotron, official DuplexCascade and Kokoro handover coverage."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import traceback
import wave

import numpy as np


async def run_sample(args, sample, output):
    """Run native managers on real audio, retaining responses and played PCM."""
    from nemotron_asr_service import load_pcm16
    from xtalk.models import ASR, TTS, Models
    from xtalk.models.asr.nemotron_streaming_client import NemotronStreamingClient
    from xtalk.models.tts.kokoro_segmented import KokoroSegmented
    from xtalk.duplex_control.micro_turn import MicroTurnAssembler
    from xtalk.duplex_control.runtime_adapter import DuplexRuntimeAdapter
    from xtalk.serving.event_bus import EventBus, EventDispatchMode
    from xtalk.serving.events import (AudioFrameReceived, ASRResultPartial, LLMAgentLoop,
        DuplexMicroTurnReady, DuplexProtocolParsed, DuplexProtocolError,
        LLMAgentResponseUpdate, TTSChunkReady, TTSChunkPlayed, TurnTTSStopRequested,
        TTSFinished, TTSPlaybackFinished, ErrorOccurred)
    from xtalk.serving.modules.asr_manager import ASRManager
    from xtalk.serving.modules.tts_manager import TTSManager
    from xtalk.serving.modules.tts_response_coordinator import TTSResponseCoordinator
    from xtalk.serving.modules.tts_playback_manager import TTSPlaybackManager

    path=Path(sample['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sample['sha256']:
        raise ValueError('Frozen audio changed')
    pcm=load_pcm16(path)
    original_seconds=len(pcm)/32000
    pcm+=b'\0\0'*16000*12
    session=output.name
    output.mkdir(parents=True,exist_ok=False)
    bus=EventBus(enable_history=True,max_history=30000)
    asr_client=NemotronStreamingClient(args.asr_url)
    tts_client=KokoroSegmented(args.tts_url)
    models=Models({ASR:asr_client,TTS:tts_client})
    config={'duplex_auto_tick':True,'duplex_micro_turn_seconds':.6,'acoustic_vad_enabled':False}
    asr=ASRManager(bus,session,models,config)
    assembler=MicroTurnAssembler(bus,session,config)
    adapter=DuplexRuntimeAdapter(bus,session,{'duplex_model_url':args.model_url,
                                             'duplex_timeout_seconds':120})
    synthesis=TTSManager(bus,session,models)
    coordinator=TTSResponseCoordinator(bus,session)
    playback=TTSPlaybackManager(bus,session)
    events=[];sends=[];heard=[];stopped=set();queue=asyncio.Queue()
    started=time.monotonic()
    wav=wave.open(str(output/'played.wav'),'wb')
    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(48000)
    written=0

    async def observe(event):
        data=asdict(event)
        data.pop('audio_chunk',None)
        events.append({'at':time.monotonic()-started,'type':event.TYPE,**data})
        if isinstance(event,TTSChunkReady):await queue.put(event)
        elif isinstance(event,TurnTTSStopRequested):stopped.add(event.response_id)
        elif isinstance(event,TTSFinished):await queue.put(event)

    async def play():
        nonlocal written
        while True:
            event=await queue.get()
            try:
                if event.response_id in stopped:continue
                if isinstance(event,TTSFinished):
                    await bus.publish(TTSPlaybackFinished(session_id=session,response_id=event.response_id),
                                      mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
                    continue
                at=time.monotonic()-started
                audio=event.audio_chunk
                samples=np.frombuffer(audio,dtype='<i2').astype(np.float64)/32768
                active=np.flatnonzero(np.abs(samples)>10**(-45/20))
                heard.append({'at':at,'response_id':event.response_id,'bytes':len(audio),
                              'audible_at':at+int(active[0])/48000 if len(active) else None})
                target=round(at*48000)
                if target>written:wav.writeframes(b'\0\0'*(target-written));written=target
                wav.writeframes(audio);written+=len(audio)//2
                await asyncio.sleep(len(audio)/96000)
                await bus.publish(TTSChunkPlayed(session_id=session,response_id=event.response_id),
                                  mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
            finally:queue.task_done()

    for cls in (ASRResultPartial,DuplexMicroTurnReady,DuplexProtocolParsed,DuplexProtocolError,
                LLMAgentResponseUpdate,TTSChunkReady,TurnTTSStopRequested,TTSFinished,ErrorOccurred):
        bus.subscribe(cls,observe,priority=-50)
    player=asyncio.create_task(play())
    error=None
    try:
        await bus.publish(LLMAgentLoop(session_id=session),mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
        for offset in range(0,len(pcm),2560):
            target=(offset+len(pcm[offset:offset+2560]))/32000
            await asyncio.sleep(max(0,started+target-time.monotonic()))
            sends.append({'scheduled':target,'at':time.monotonic()-started,
                          'diagnostic_silence':offset>=original_seconds*32000})
            await bus.publish(AudioFrameReceived(session_id=session,audio_data=pcm[offset:offset+2560]),
                              mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
        await asyncio.sleep(.1)
    except Exception:
        error=traceback.format_exc()
    finally:
        history=adapter._request_history()
        for manager in (assembler,adapter,asr,synthesis,coordinator,playback):
            await manager.shutdown()
        player.cancel();await asyncio.gather(player,return_exceptions=True)
        await bus.shutdown();await asyncio.to_thread(asr_client.close);wav.close()
    first={}
    texts={}
    for event in events:
        if event['type']==LLMAgentResponseUpdate.TYPE and event.get('text','').strip():
            first.setdefault(event['response_id'],event['at'])
            texts[event['response_id']]=event['text']
    boundary=sample['boundary_seconds']
    replies=[{'response_id':rid,'started_at':at,'text':texts[rid],
              'latency_seconds':at-boundary,
              'first_audible_at':next((p['audible_at'] for p in heard if p['response_id']==rid and p['audible_at'] is not None),None)}
             for rid,at in first.items()]
    errors=[e for e in events if e['type'] in (DuplexProtocolError.TYPE,ErrorOccurred.TYPE)]
    result={'sample_id':sample['sample_id'],'input_sha256':sample['sha256'],
            'original_audio_seconds':original_seconds,'diagnostic_silence_seconds':12,
            'boundary_seconds_offline_only':boundary,'replies':replies,'error':error,
            'protocol_or_component_errors':errors,'history':history,'events':events,
            'played':heard,'sends':sends,'source_type':'real_audio_native_manager_chain',
            'new_text_within':{str(t):any(0<=r['latency_seconds']<=t for r in replies) for t in (2,5,12)},
            'new_voice_within':{str(t):any(0<=r['latency_seconds'] and r['first_audible_at'] is not None and
                boundary<=r['first_audible_at']<=boundary+t for r in replies) for t in (2,5,12)}}
    (output/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


async def run(args):
    """Freeze five historic inputs and report missing handovers separately from errors."""
    args.output.mkdir(parents=True,exist_ok=False)
    samples=[s for s in json.loads(args.manifest.read_text())['samples'] if s['split']=='test']
    if len(samples)!=5:raise ValueError('Expected five historical inputs')
    rows=[]
    for index,sample in enumerate(samples,1):
        row=await run_sample(args,sample,args.output/f'sample-{index}')
        rows.append(row)
        print(json.dumps({'sample':index,'text':row['new_text_within'],'voice':row['new_voice_within'],
                          'errors':len(row['protocol_or_component_errors']),'error':row['error']}),flush=True)
    summary={'samples':len(rows),'text_12s':sum(r['new_text_within']['12'] for r in rows),
             'voice_12s':sum(r['new_voice_within']['12'] for r in rows),
             'errors':sum(bool(r['error'] or r['protocol_or_component_errors']) for r in rows),
             'physical_playback_measured':False,'training_released':False}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2))
    return int(bool(summary['errors']))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--asr-url',required=True)
    parser.add_argument('--tts-url',required=True)
    parser.add_argument('--model-url',required=True)
    parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
