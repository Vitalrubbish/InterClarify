"""Verify real component transports on allocated GPUs without training or a judge."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
import traceback
import wave

import numpy as np


def write_json(path, value):
    """Persist evidence without dropping failed scenarios."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


async def verify_asr(args):
    """Replay bounded PCM on a real-time clock with independent result reads."""
    from xtalk.models.asr.nemotron_streaming_client import NemotronStreamingClient
    from nemotron_asr_service import load_pcm16
    original = load_pcm16(args.audio)
    middle = len(original) // 4 * 2
    scenarios = [('normal', original), ('pause_resume', original[:middle] + b'\0\0'*48000 + original[middle:]),
                 ('two_turns', original + b'\0\0'*32000 + original),
                 ('serial_session', original), ('eof_short_tail', original[:-137*2])]
    rows = []
    previous_id = None
    for name, pcm in scenarios:
        client = NemotronStreamingClient(args.url)
        events, sends = [], []
        ended = asyncio.Event()
        started = time.monotonic()
        first_id = None
        async def poll():
            previous = ''
            while not ended.is_set():
                text = await asyncio.to_thread(client.recognize_stream, b'')
                if text != previous:
                    events.append({'arrival_seconds': time.monotonic()-started,
                        'raw_text': client.last_result['raw_text'], 'text': text,
                        'delta': text[len(previous):], 'generation': client.last_result['generation'],
                        'prefix_version': client.last_result['prefix_version']})
                    previous = text
                await asyncio.sleep(.03)
        reader = asyncio.create_task(poll())
        error = None
        text = ''
        try:
            for offset in range(0, len(pcm), 2560):
                chunk = pcm[offset:offset+2560]
                scheduled = (offset + len(chunk))/32000
                await asyncio.sleep(max(0, started+scheduled-time.monotonic()))
                sent = time.monotonic()-started
                await asyncio.to_thread(client.recognize_stream, chunk)
                if first_id is None:
                    first_id = client._session_id
                sends.append({'offset_bytes': offset, 'scheduled_seconds': scheduled,
                              'sent_seconds': sent, 'late_seconds': max(0,sent-scheduled),
                              'bytes': len(chunk), 'sha256': hashlib.sha256(chunk).hexdigest()})
                if name == 'pause_resume' and offset <= middle < offset+2560:
                    await asyncio.to_thread(client.recognize_stream, b'', is_final=True)
            text = await asyncio.to_thread(client.finish_stream)
            if not text.strip():
                raise RuntimeError('Native decoder returned no final transcript')
            if previous_id == first_id:
                raise RuntimeError('Session identity reused')
            if reader.done():
                reader.result()
        except Exception:
            error = traceback.format_exc()
        finally:
            ended.set()
            await reader
            await asyncio.to_thread(client.close)
        previous_id = first_id
        row = {'scenario': name, 'generation': first_id, 'text': text, 'error': error,
               'source_type': 'real_audio_replay' if name in ('normal','serial_session','eof_short_tail') else 'constructed_audio_replay',
               'purpose': 'integration_diagnostic_only',
               'input_sha256': hashlib.sha256(pcm).hexdigest(), 'audio_seconds': len(pcm)/32000,
               'events': events, 'sends': sends, 'seconds': time.monotonic()-started}
        rows.append(row)
        write_json(args.output/f'{name}.json', row)
    client = NemotronStreamingClient(args.url)
    try:
        await asyncio.to_thread(client.recognize_stream, original[:5120])
        old_id = client._session_id
        await asyncio.to_thread(client.reset)
        await asyncio.to_thread(client.recognize_stream, original[:5120])
        new_id = client._session_id
        if new_id == old_id:
            raise RuntimeError('Cancellation did not replace decoder generation')
        rows.append({'scenario':'cancel_reconnect','old_generation':old_id,'generation':new_id,'error':None})
    finally:
        await asyncio.to_thread(client.close)
    return rows


def tts_timing_metrics(chunks, packets, timeline):
    """Separate queue starvation, PCM edge silence and compute/audio durations."""
    playback_end, gaps, audible, run = 0., 0., None, 0
    played=[]
    for data,event in zip(chunks,packets):
        start=max(playback_end,event['arrival_seconds'])
        gap=max(0,start-playback_end) if playback_end else 0.
        if gap:
            gaps+=gap
            played.append(bytes(round(gap*48000)*2))
        played.append(data)
        samples=np.frombuffer(data,dtype='<i2').astype(np.float64)/32768
        if gap:run=0
        for index in range(0,len(samples)-479,480):
            loud=np.sqrt(np.mean(samples[index:index+480]**2)) > 10**(-45/20)
            run=run+1 if loud else 0
            if run>=3 and audible is None:audible=start+(index-960)/48000
        playback_end=start+len(samples)/48000
    pcm=b''.join(chunks)
    segments=[]
    cursor=0
    for event in [row for row in timeline if row['kind']=='pcm']:
        size=event['bytes']
        values=np.frombuffer(pcm[cursor:cursor+size],dtype='<i2').astype(np.float64)/32768
        cursor+=size
        frames=values[:len(values)//480*480].reshape(-1,480)
        active=np.flatnonzero(np.sqrt(np.mean(frames**2,axis=1))>10**(-45/20))
        duration=len(values)/48000
        leading=active[0]*.01 if len(active) else duration
        trailing=(len(frames)-active[-1]-1)*.01 if len(active) else duration
        compute=event.get('compute_seconds')
        segments.append({'audio_seconds':duration,'raw_audio_seconds':event.get('raw_audio_seconds',duration),
                         'compute_seconds':compute,'request_seconds':event.get('request_seconds'),
                         'compute_realtime_factor':compute/duration if compute is not None and duration else None,
                         'leading_silence_seconds':float(leading),'trailing_silence_seconds':float(trailing),
                         'leading_trim_seconds':event.get('leading_trim_seconds',0),
                         'trailing_trim_seconds':event.get('trailing_trim_seconds',0)})
    boundaries=[left['trailing_silence_seconds']+right['leading_silence_seconds']
                for left,right in zip(segments,segments[1:])]
    return {'first_audible_proxy_seconds':audible,'simulated_underflow_seconds':gaps,
            'audio_seconds':len(pcm)/96000,'played_audio_seconds':sum(map(len,played))/96000,
            'segment_timing':segments,'boundary_silence_seconds':boundaries,
            'max_boundary_silence_seconds':max(boundaries,default=0),
            'segments_shorter_than_600ms':sum(row['audio_seconds']<.6 for row in segments)},b''.join(played)


async def verify_tts(args):
    """Supply actual timed fragments, retain playable WAV and audible proxies."""
    from xtalk.models.tts.kokoro_segmented import KokoroSegmented
    texts = [('confirmation','Yes, Tuesday at nine thirty works.',5,.05),
             ('clarification','Did you mean Tuesday at 9:30, or Thursday at 3:15?',5,.05),
             ('long_answer','I can help with that appointment. First, please confirm the date and time. '
              'Then I will check the calendar and summarize the arrangement before proceeding. '
              'If you need to change the date, tell me and we can update the same appointment.',5,.05),
             ('micro_turn_supply','Yes, Tuesday at nine thirty works.',12,.6),
             ('slow_text_supply','Yes, Tuesday at nine thirty works.',3,.6)]
    rows = []
    for name,text,chars,interval in texts:
        client = KokoroSegmented(args.url, max_wait_ms=args.tts_first_wait_ms,
                                 continuation_wait_ms=args.tts_continuation_wait_ms)
        started = time.monotonic()
        chunks, audio_events = [], []
        await client.start()
        async def receive():
            async for pcm in client.audio_stream():
                chunks.append(pcm)
                audio_events.append({'arrival_seconds':time.monotonic()-started,'bytes':len(pcm)})
        receiver = asyncio.create_task(receive())
        error = None
        try:
            for offset in range(0,len(text),chars):
                await client.append_text(text[offset:offset+chars])
                await asyncio.sleep(interval)
            await client.flush()
            await asyncio.wait_for(receiver,60)
            await client.stop()
            if not chunks:
                raise RuntimeError('No synthesized PCM')
        except Exception:
            error = traceback.format_exc()
        finally:
            timeline = list(client.timeline)
            await client.cancel()
            receiver.cancel()
            await asyncio.gather(receiver,return_exceptions=True)
        metrics,played=tts_timing_metrics(chunks,audio_events,timeline)
        with wave.open(str(args.output/f'{name}.wav'),'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(48000)
            output.writeframes(played)
        row = {'scenario':name,'text':text,'source_type':'fixed_script_incremental_text',
               'scope':'primary' if interval==.05 else 'supply_diagnostic',
               'input_chars_per_fragment':chars,'input_interval_seconds':interval,
               'first_pcm_seconds': audio_events[0]['arrival_seconds'] if audio_events else None,
               **metrics,'error':error,'timeline':timeline,'packets':audio_events}
        rows.append(row)
        write_json(args.output/f'{name}.json',row)
    client = KokoroSegmented(args.url,max_wait_ms=20)
    await client.start()
    await client.append_text('This old response must be discarded after cancellation.')
    await asyncio.sleep(.03)
    old = client._generation
    cancelled = time.monotonic()
    await client.cancel()
    released = time.monotonic()
    await client.start()
    new = client._generation
    await client.append_text('A fresh response.')
    await client.flush()
    chunks = [pcm async for pcm in client.audio_stream()]
    await client.stop()
    rows.append({'scenario':'cancel_reconnect','old_generation':old,'generation':new,
                 'cancel_transport_seconds':released-cancelled,'new_pcm_bytes':sum(map(len,chunks)),
                 'error':None if new != old and chunks else 'generation isolation failed',
                 'limitation':'underlying server GPU computation may complete after cancellation'})
    await client.cancel()
    rows.append(await verify_native_playback(args.url, args.output))
    return rows


async def verify_native_playback(url, output):
    """Drive real Kokoro through the existing protocol and unique playback managers."""
    from xtalk.models import Models, TTS
    from xtalk.models.tts.kokoro_segmented import KokoroSegmented
    from xtalk.duplex_control.micro_turn import MicroTurnAssembler
    from xtalk.duplex_control.model_client import GenerationEnd
    from xtalk.duplex_control.runtime_adapter import DuplexRuntimeAdapter
    from xtalk.serving.event_bus import EventBus, EventDispatchMode
    from xtalk.serving.events import (ASRResultPartial, TTSChunkReady, TTSChunkPlayed,
        TTSFinished, TTSPlaybackFinished, TurnTTSStopRequested, TTSStopped, ErrorOccurred)
    from xtalk.serving.modules.tts_manager import TTSManager
    from xtalk.serving.modules.tts_response_coordinator import TTSResponseCoordinator
    from xtalk.serving.modules.tts_playback_manager import TTSPlaybackManager
    bus=EventBus(enable_history=True,max_history=10000)
    client=KokoroSegmented(url)
    models=Models({TTS:client})
    synthesis=TTSManager(bus,'native',models)
    coordinator=TTSResponseCoordinator(bus,'native')
    playback=TTSPlaybackManager(bus,'native')
    assembler=MicroTurnAssembler(bus,'native',{'duplex_auto_tick':False})
    texts=iter(['<|user finish talking|>I will explain the appointment details and then confirm your calendar. '
                'We can keep listening while this response is being spoken.<|im_end|>',
                '<|user backchannel|><|im_end|>','<|user interruption|><|im_end|>',
                '<|user finish talking|>Tuesday at nine thirty works.<|im_end|>',
                '<|user is thinking|><|im_end|>'])
    class Scripted:
        """Fix control decisions to isolate component execution from model quality."""
        async def stream(self, history):
            yield next(texts)
            yield GenerationEnd('stop',(151645,))
    adapter=DuplexRuntimeAdapter(bus,'native',{'duplex_model_client':Scripted()})
    events=[]
    first=asyncio.Event();finished=asyncio.Event()
    started=time.monotonic()
    async def observe(event):
        events.append({'type':event.TYPE,'at':time.monotonic()-started,
                       'response_id':event.response_id if hasattr(event,'response_id') else ''})
        if isinstance(event,TTSChunkReady):
            first.set()
            await bus.publish(TTSChunkPlayed(session_id='native',response_id=event.response_id),
                              mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
        if isinstance(event,TTSFinished):finished.set()
    for cls in (TTSChunkReady,TTSStopped,TurnTTSStopRequested,TTSFinished,ErrorOccurred):
        bus.subscribe(cls,observe,priority=-20)
    error=None
    try:
        await bus.publish(ASRResultPartial(session_id='native',text='Explain my appointment'),
                          mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
        await assembler.flush()
        await asyncio.wait_for(first.wait(),15)
        old=adapter._response_id
        await assembler.flush()
        if any(e['type']==TurnTTSStopRequested.TYPE for e in events):
            raise RuntimeError('User backchannel stopped playback')
        await assembler.flush()
        stopped=time.monotonic()-started
        await asyncio.sleep(.3)
        if any(e['type']==TTSChunkReady.TYPE and e['response_id']==old and e['at']>stopped for e in events):
            raise RuntimeError('Old PCM delivered after interruption completed')
        await bus.publish(ASRResultPartial(session_id='native',text='Explain my appointment. Confirm Tuesday'),
                          mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
        first.clear();finished.clear()
        await assembler.flush()
        new=adapter._response_id
        await assembler.flush()
        await asyncio.wait_for(finished.wait(),20)
        if not new or new==old or not any(e['type']==TTSChunkReady.TYPE and e['response_id']==new for e in events):
            raise RuntimeError('No isolated second response audio')
        await bus.publish(TTSPlaybackFinished(session_id='native',response_id=new),
                          mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
        if any(e['type']==ErrorOccurred.TYPE for e in events):
            raise RuntimeError('Native playback chain reported an error')
    except Exception:
        error=traceback.format_exc()
    finally:
        for manager in (assembler,adapter,synthesis,coordinator,playback):
            await manager.shutdown()
        await bus.shutdown()
    row={'scenario':'native_playback_chain','source_type':'scripted_control_with_real_kokoro',
         'error':error,'events':events,'limitation':'headless PCM acknowledgements, not physical speaker measurement'}
    write_json(output/'native_playback_chain.json',row)
    return row


async def run(args):
    """Keep partial outputs and a nonzero exit on failed component evidence."""
    args.output.mkdir(parents=True,exist_ok=False)
    rows, error = [], None
    try:
        rows = await (verify_asr(args) if args.backend == 'asr' else verify_tts(args))
    except Exception:
        error = traceback.format_exc()
    result = {'backend':args.backend,'rows':rows,'error':error,
              'passed':not error and bool(rows) and not any(row['error'] for row in rows),
              'full_chain_accepted':False}
    write_json(args.output/'collection_manifest.json',{
        'backend':args.backend,'purpose':'integration_diagnostic_only','training_allowed':False,
        'source_audio':str(args.audio),'source_audio_sha256':hashlib.sha256(args.audio.read_bytes()).hexdigest(),
        'scenarios':[{'scenario':r['scenario'],'generation':r.get('generation'),
                      'input_sha256':r.get('input_sha256'),'error':r['error']} for r in rows]})
    write_json(args.output/'summary.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return int(not result['passed'])


def main():
    """Run a single explicit backend; never substitute another model."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['asr','tts'],required=True)
    parser.add_argument('--url',required=True)
    parser.add_argument('--tts-first-wait-ms',type=float,default=300)
    parser.add_argument('--tts-continuation-wait-ms',type=float,default=1200)
    parser.add_argument('--audio',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == '__main__':
    main()
