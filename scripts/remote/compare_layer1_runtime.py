"""Execute the pinned official tick function independently of the X-Talk adapter."""
from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import copy
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace

import requests

OFFICIAL_SHA = '404a1b6f51e87c012e1111cc21a712ed8895e9a5ee99328bd1245a7c6a654037'


class Tensor:
    """Transport-only tensor shim; all actual weight inference is in the GPU service."""

    def __init__(self, data):
        self.data = copy.deepcopy(data)
        self.ndim = 2 if data and isinstance(data[0], list) else 1

    def flatten(self):
        return Tensor(self.data[0] if self.ndim == 2 else self.data)

    def numel(self):
        return len(self.flatten().data)

    def __iter__(self):
        return iter([SimpleNamespace(item=lambda value=value: value) for value in self.data])


class Tokenizer:
    """Expose the released tokenizer through the reference server's narrow API."""

    def __init__(self, path):
        from tokenizers import Tokenizer as FastTokenizer
        self.raw = FastTokenizer.from_file(str(path))
        self.bos_token_id = None
        self.eos_token_id = self.encode('<|im_end|>')[0]

    def encode(self, text, add_special_tokens=False):
        return self.raw.encode(text, add_special_tokens=add_special_tokens).ids

    def decode(self, ids, skip_special_tokens=False):
        return self.raw.decode(ids, skip_special_tokens=skip_special_tokens)


class RawDeltaBuffer(list):
    """Adapt a shared visible raw-prefix contract to one official Word per window.

    Only the ASR transport boundary is adapted: no control, prompt or history
    logic is copied from X-Talk. Original Kyutai Word timing is outside scope.
    """

    def __iter__(self):
        return iter([''.join(list.__iter__(self)).strip()])


def load_reference(path):
    """Compile untouched pinned clock/decoder AST with observable injected I/O."""
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != OFFICIAL_SHA:
        raise ValueError('Reference source differs from the frozen official server')
    tree = ast.parse(raw)
    tick = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == 'llm_tick_task')
    # Observe complete token consumption, rather than only the worker's return.
    for node in ast.walk(tick):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call=node.value
            if isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name) and call.func.value.id=='gen_thread' and call.func.attr=='join':
                node.value=ast.Tuple(elts=[call,ast.Call(func=ast.Name(id='observe_join',ctx=ast.Load()),args=[],keywords=[])],ctx=ast.Load())
    streamer = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == 'TokenQueueStreamer')
    prepare = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'prepare_llm_tokens')
    factory = ast.parse('''def factory(self, first_text_received_event, asr_buffer_words,
    asr_buffer_lock, history_ids, send_json, tts_client):
    tts_speaking_flag = 0
    tts_thinking_flag = 0
''').body[0]
    factory.body += [streamer, tick]
    factory.body += ast.parse('return llm_tick_task, lambda: (tts_speaking_flag, tts_thinking_flag)').body
    module = ast.fix_missing_locations(ast.Module(body=[prepare, factory], type_ignores=[]))
    scope = {'asyncio':asyncio, 'time':time, 'threading':threading, 'queue':queue,
             'BaseStreamer':object, 'torch':SimpleNamespace(
                 tensor=lambda data, **kwargs: Tensor(data), long='long',
                 ones_like=lambda value: value, no_grad=contextlib.nullcontext)}
    exec(compile(module, str(path), 'exec'),scope)
    return scope['prepare_llm_tokens'], scope['factory'], scope


class ReferenceKernel:
    """Send original reference IDs to the common frozen greedy inference kernel."""

    def __init__(self, args, tokenizer, records, started, fixed):
        self.args, self.tokenizer, self.records = args, tokenizer, records
        self.started, self.fixed = started, fixed

    def generate(self, input_ids, streamer, **kwargs):
        prompt = input_ids.data[0]
        record = {'at':time.monotonic()-self.started,'prompt_token_ids':prompt,'generated_ids':[]}
        self.records.append(record)
        streamer.put(input_ids)
        try:
            if self.fixed:
                text = self.fixed[(len(self.records)-1) % len(self.fixed)]
                ids = self.tokenizer.encode(text)
                for value in ids:
                    streamer.put(Tensor([value]))
                    record['generated_ids'].append(value)
            else:
                with requests.post(self.args.model_url+'/generate_ids', json={
                    'prompt_token_ids':prompt,'max_new_tokens':64},stream=True,timeout=120) as response:
                    response.raise_for_status()
                    for line in response.iter_lines(chunk_size=1):
                        item=json.loads(line)
                        if 'error' in item:
                            raise RuntimeError(item['error'])
                        if 'generated_token_id' in item:
                            value=item['generated_token_id']
                            record['generated_ids'].append(value)
                            streamer.put(Tensor([value]))
                        if 'finish_reason' in item and item['token_ids'] != record['generated_ids']:
                            raise RuntimeError('Raw reference token stream was incomplete')
        except Exception as exc:
            record['error']=repr(exc)
        finally:
            record['finished_at']=time.monotonic()-self.started
            streamer.end()


async def reference(args, events, duration, tokenizer, clock, fixed=None):
    """Run the original tick body and decoder with explicit transport-only stubs."""
    prepare,factory,scope=load_reference(args.official_source)
    started=time.monotonic()
    records, output, history = [], [], []
    kernel=ReferenceKernel(args,tokenizer,records,started,fixed)
    def observe_join():
        if records:
            records[-1]['committed_at']=time.monotonic()-started
        if time.monotonic()-started >= duration:
            raise asyncio.CancelledError()
    scope['observe_join']=observe_join
    self=SimpleNamespace(tokenizer=tokenizer,llm=kernel,llm_device='remote',
                         overlap_window_s=.6,max_new_tokens=64,
                         filter_period_for_tts=lambda text:text.replace('.',''))
    prepare(self)
    if self.bos_id is not None:
        history.append(self.bos_id)
    ready, words, lock=asyncio.Event(),RawDeltaBuffer(),asyncio.Lock()
    async def send(value):
        output.append({'at':time.monotonic()-started,**value})
    class TTS:
        async def send_text(self,text,send_eos=False):
            await send({'type':'tts_text','text':text,'eos':send_eos})
        async def send_eos(self):
            await send({'type':'tts_eos'})
        async def reset(self,reason=''):
            await send({'type':'stop','reason':reason})
    tick,state=factory(self,ready,words,lock,history,send,TTS())
    async def produce():
        previous=''
        for event in events:
            await asyncio.sleep(max(0,started+event['arrival_seconds']-time.monotonic()))
            text=event['text']
            if not text.startswith(previous):
                raise ValueError('Fixed trace rewrites a delivered prefix')
            async with lock:
                words.append(text[len(previous):])
            previous=text
            if text.strip():ready.set()
    if clock=='session_start':ready.set()
    producer=asyncio.create_task(produce())
    ticker=asyncio.create_task(tick())
    try:
        await asyncio.sleep(duration)
        producer.cancel()
        # Finish already submitted inference before cancelling the reference loop.
        for _ in range(2000):
            if not records or 'committed_at' in records[-1]:break
            await asyncio.sleep(.005)
        ticker.cancel()
        await asyncio.gather(producer,ticker,return_exceptions=True)
        if producer.done() and not producer.cancelled():producer.result()
        return {'requests':records,'events':output,'history_ids':history,'state':state()}
    finally:
        producer.cancel();ticker.cancel()
        await asyncio.gather(producer,ticker,return_exceptions=True)


async def integrated(args, events, duration, tokenizer, clock, fixed=None):
    """Use the existing assembler, raw bridge and protocol executor unchanged."""
    from retest_asr_official_input import HTTPModelProxy, OfficialBridge
    from xtalk.duplex_control.micro_turn import MicroTurnAssembler
    from xtalk.duplex_control.runtime_adapter import DuplexRuntimeAdapter
    from xtalk.duplex_control.model_client import GenerationEnd
    from xtalk.serving.event_bus import EventBus,EventDispatchMode
    from xtalk.serving.events import (ASRResultPartial,LLMAgentLoop,DuplexMicroTurnReady,
        DuplexProtocolParsed,DuplexProtocolError,TurnTTSStopRequested,LLMAgentResponseUpdate)
    bus=EventBus(enable_history=True,max_history=10000)
    started=time.monotonic();records=[];output=[]
    class Client:
        async def stream(self, history):
            from retest_asr_official_input import reference_prompt_ids
            prompt=reference_prompt_ids(tokenizer.raw,history)
            row={'at':time.monotonic()-started,'prompt_token_ids':prompt,'generated_ids':[]}
            records.append(row)
            text=fixed[(len(records)-1)%len(fixed)]
            row['generated_ids']=tokenizer.encode(text)
            yield text
            row['finished_at']=time.monotonic()-started
            yield GenerationEnd('stop',tuple(row['generated_ids']))
    if fixed:
        client=Client()
    else:
        response=await asyncio.to_thread(requests.get,args.model_url+'/health',timeout=30)
        response.raise_for_status()
        proxy=HTTPModelProxy(args.model_url,response.json())
        proxy.tokenizer=tokenizer.raw;proxy.arm='official'
        client=OfficialBridge(proxy,records)
    assembler=MicroTurnAssembler(bus,'comparison',{'duplex_auto_tick':False})
    adapter=DuplexRuntimeAdapter(bus,'comparison',{'duplex_model_client':client})
    async def observe(event):
        output.append({'at':time.monotonic()-started,'type':event.TYPE,
                       'response_id':event.response_id if isinstance(event,LLMAgentResponseUpdate) else '',
                       'text':event.text if isinstance(event,LLMAgentResponseUpdate) else '',
                       'state_token':event.state_token if isinstance(event,DuplexProtocolParsed) else '',
                       'reason':event.reason if isinstance(event,TurnTTSStopRequested) else '',
                       'delta':event.delta_text if isinstance(event,DuplexMicroTurnReady) else ''})
    for cls in (DuplexMicroTurnReady,DuplexProtocolParsed,DuplexProtocolError,TurnTTSStopRequested,LLMAgentResponseUpdate):
        bus.subscribe(cls,observe,priority=-50)
    ready=asyncio.Event()
    async def produce():
        for event in events:
            await asyncio.sleep(max(0,started+event['arrival_seconds']-time.monotonic()))
            await bus.publish(ASRResultPartial(session_id='comparison',text=event['text']),
                              mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
            if event['text'].strip():ready.set()
    async def ticks():
        await ready.wait()
        next_tick=time.monotonic()+.6
        while True:
            await asyncio.sleep(max(.001,next_tick-time.monotonic()))
            if time.monotonic()-started>=duration:return
            next_tick=max(time.monotonic(),next_tick+.6)
            await assembler.flush()
    if clock=='session_start':
        await bus.publish(LLMAgentLoop(session_id='comparison'),mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
        ready.set()
    producer=asyncio.create_task(produce());ticker=asyncio.create_task(ticks())
    try:
        await asyncio.sleep(duration)
        producer.cancel()
        await asyncio.wait_for(ticker,10)
        await asyncio.gather(producer,return_exceptions=True)
        history=adapter._request_history()
        from retest_asr_official_input import reference_prompt_ids
        # The renderer adds a final assistant header, absent from committed history.
        header=tokenizer.encode('<|im_start|>assistant\n')
        history_ids=reference_prompt_ids(tokenizer.raw,history)
        history_ids=history_ids[:-len(header)]
        return {'requests':records,'events':output,'history_ids':history_ids}
    finally:
        producer.cancel();ticker.cancel()
        await asyncio.gather(producer,ticker,return_exceptions=True)
        await assembler.shutdown();await adapter.shutdown();await bus.shutdown()


def compare(left,right):
    """Locate the first request divergence rather than counting its descendants."""
    for index,(a,b) in enumerate(zip(left['requests'],right['requests'])):
        for field in ('prompt_token_ids','generated_ids'):
            if a.get(field)!=b.get(field):
                av,bv=a.get(field,[]),b.get(field,[])
                offset=next((i for i,(x,y) in enumerate(zip(av,bv)) if x!=y),min(len(av),len(bv)))
                return {'request':index,'field':field,'first_token_offset':offset}
        if a.get('error') or b.get('error'):
            return {'request':index,'field':'request_error'}
    if len(left['requests'])!=len(right['requests']):
        return {'field':'request_count','reference':len(left['requests']),'integrated':len(right['requests'])}
    if left['history_ids']!=right['history_ids']:
        return {'field':'committed_history'}
    reference_controls=[e['text'] for e in left.get('events',[]) if e['type']=='assistant_special']
    integrated_controls=[e['state_token'] for e in right.get('events',[]) if e.get('state_token')]
    if reference_controls != integrated_controls:
        return {'field':'control_actions','reference':reference_controls,'integrated':integrated_controls}
    reference_stops=[e['reason'] for e in left.get('events',[]) if e['type']=='stop']
    integrated_stops=[e['reason'] for e in right.get('events',[]) if e.get('reason') and e['reason'] not in ('shutdown','cancelled')]
    if reference_stops != integrated_stops:
        return {'field':'stop_actions','reference':reference_stops,'integrated':integrated_stops}
    reference_text=''.join(e['text'] for e in left.get('events',[]) if e['type']=='assistant_text')
    previous={};parts=[]
    for event in right.get('events',[]):
        if event.get('response_id') and event.get('text'):
            identity=event['response_id'];text=event['text'];old=previous.get(identity,'')
            parts.append(text[len(old):] if text.startswith(old) else text)
            previous[identity]=text
    if reference_text != ''.join(parts):
        return {'field':'submitted_text','reference':reference_text,'integrated':''.join(parts)}
    return None


def complete_word_events(events, max_hold=.16):
    """Publish arrived complete words or expire a causal bounded partial-word hold."""
    output=[];visible='';raw='';deadline=None
    def publish(text,at):
        nonlocal visible
        if text != visible:
            if not text.startswith(visible):raise ValueError('Publication would rewrite delivered text')
            output.append({'arrival_seconds':at,'text':text})
            visible=text
    for event in events:
        at=event['arrival_seconds']
        if deadline is not None and deadline <= at:
            publish(raw,deadline);deadline=None
        text=event['text']
        if not text.startswith(raw):raise ValueError('Complete-word view is inapplicable to a rewriting trace')
        raw=text
        boundary=max((i+1 for i,char in enumerate(text) if char.isspace()),default=0)
        if boundary > len(visible):publish(text[:boundary],at)
        if len(raw)>len(visible) and deadline is None:deadline=at+max_hold
        if raw==visible:deadline=None
    if deadline is not None:publish(raw,deadline)
    return output


async def run(args):
    """Write both raw timelines and mark incomplete coverage explicitly."""
    args.output.mkdir(parents=True,exist_ok=False)
    tokenizer=Tokenizer(args.tokenizer)
    warmup=None
    if args.model_url:
        prompt=tokenizer.encode('<|im_start|>user\nHello<|im_end|>\n<|im_start|>assistant\n')
        started=time.monotonic()
        response=await asyncio.to_thread(requests.post,args.model_url+'/generate_ids',
            json={'prompt_token_ids':prompt,'max_new_tokens':64},timeout=120)
        response.raise_for_status()
        warmup={'seconds':time.monotonic()-started,'rows':[json.loads(line) for line in response.text.splitlines()]}
        if not any('finish_reason' in row for row in warmup['rows']):
            raise RuntimeError('Model warmup did not finish')
        (args.output/'kernel_warmup.json').write_text(json.dumps(warmup,indent=2))
    fixed=['<|user is talking|><|im_end|>', '<|user finish talking|>Yes.<|im_end|>',
           '<|user backchannel|><|im_end|>', '<|user interruption|><|im_end|>',
           '<|user finish talking|>Tuesday.<|im_end|>','<|user is thinking|><|im_end|>']
    cases=[('single-step', [{'arrival_seconds':.05,'text':'  Hello '}],.7),
           ('protocol', [{'arrival_seconds':.05,'text':'Cou'},
                         {'arrival_seconds':.25,'text':'Could'},
                         {'arrival_seconds':.7,'text':'Could you'},
                         {'arrival_seconds':1.3,'text':'Could you confirm Tuesday at 9:30?'}],8.0)]
    if args.manifest:
        manifest=json.loads(args.manifest.read_text())
        samples=[row for row in manifest['samples'] if row['split']=='test']
        for index,row in enumerate(samples,1):
            path=args.asr_run/'nemotron_en-160'/f'sample-{index:04d}.jsonl'
            events=[json.loads(line) for line in path.read_text().splitlines()]
            cases.append((f'historical-{index}',events,row['boundary_seconds']+12))
    results=[]
    if args.cases:
        selected=set(args.cases)
        unknown=selected-{case[0] for case in cases}
        if unknown:raise ValueError(f'Unknown cases: {sorted(unknown)}')
        cases=[case for case in cases if case[0] in selected]
    for name,events,duration in cases:
      for publication in args.publications:
        visible=complete_word_events(events) if publication=='complete_word' else events
        modes=args.modes or (['fixed_output_debug','independent_free_replay'] if args.model_url else ['fixed_output_debug'])
        for mode in modes:
            if mode=='independent_free_replay' and not args.model_url:
                raise ValueError('Free replay requires the fixed GPU model service')
            for clock in args.clocks:
                outputs=fixed if mode=='fixed_output_debug' else None
                left=await reference(args,visible,duration,tokenizer,clock,outputs)
                right=await integrated(args,visible,duration,tokenizer,clock,outputs)
                # Normalize the service bridge's real request timestamps only.
                for row in right['requests']:
                    if 'at' not in row:row['at']=row['started_monotonic']
                difference=compare(left,right)
                row={'case':name,'mode':'same_prompt_single_step' if name=='single-step' and not outputs else mode,'clock':clock,'first_difference':difference,
                     'publication':publication,'requests':len(left['requests'])}
                results.append(row)
                stem=f'{name}-{mode}-{clock}-{publication}'
                (args.output/f'{stem}.json').write_text(json.dumps({'reference':left,'integrated':right,'comparison':row,'input_events':visible},indent=2))
                print(json.dumps(row),flush=True)
    summary={'rows':results,'reference_sha256':OFFICIAL_SHA,
             'kernel_warmup':warmup,
             'input_shim':'raw-prefix delta coalesced to one Word per micro-turn; fixed ASR input only',
             'kernel':'same frozen GPU service; independent reference raw IDs bypass integration renderer',
             'coverage_gaps':['actual Kyutai Word transport','in-flight reset/cancel','separate checkpoint loading'],
             'fully_aligned':False,'passed_declared_prompt_and_history_scope':not any(row['first_difference'] for row in results)}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2))
    return int(not summary['passed_declared_prompt_and_history_scope'])


def main():
    """Require pinned source and released tokenizer; real weights stay remote."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--official-source',type=Path,required=True)
    parser.add_argument('--tokenizer',type=Path,required=True)
    parser.add_argument('--model-url')
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--asr-run',type=Path)
    parser.add_argument('--clocks',nargs='+',choices=['session_start','first_nonempty'],default=['first_nonempty'])
    parser.add_argument('--cases',nargs='+')
    parser.add_argument('--modes',nargs='+',choices=['fixed_output_debug','independent_free_replay'])
    parser.add_argument('--publications',nargs='+',choices=['raw','complete_word'],default=['raw'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.manifest and not args.asr_run:parser.error('--manifest requires --asr-run')
    raise SystemExit(asyncio.run(run(args)))


if __name__=='__main__':
    main()
