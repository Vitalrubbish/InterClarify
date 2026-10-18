"""Check the native Word contract and first-divergence reporting."""
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest

SPEC=importlib.util.spec_from_file_location('runtime_comparison',Path(__file__).parents[1]/'scripts/remote/compare_layer1_runtime.py')
runtime=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class RuntimeComparisonTests(unittest.TestCase):
    """Keep diagnostic or missing input from being reported as official alignment."""

    def manifest(self):
        return {'input_contract':'kyutai_word_strip_then_space_join','samples':[
            {'id':f'historical-{i}','duration_seconds':2.,'source_capture_sha256':'0'*64,
             'word_events':[{'type':'Word','arrival_seconds':.1,'text':' Hello '},
                            {'type':'Word','arrival_seconds':.2,'text':'world'}]}
            for i in range(1,6)]}

    def load(self,manifest):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'words.json'
            path.write_text(json.dumps(manifest))
            return runtime.load_word_cases(path)

    def test_word_events_retain_original_boundaries_and_time(self):
        manifest=self.manifest()
        cases=self.load(manifest)
        self.assertEqual(len(cases),5)
        self.assertEqual(cases[0][1],manifest['samples'][0]['word_events'])

    def test_invalid_word_sources_are_rejected(self):
        invalid=[]
        for field,value in [('type','Partial'),('arrival_seconds',-.1),
                            ('arrival_seconds',float('nan')),('arrival_seconds',3.)]:
            manifest=self.manifest()
            manifest['samples'][0]['word_events'][0][field]=value
            invalid.append(manifest)
        manifest=self.manifest()
        manifest['samples'][0]['word_events'].reverse()
        invalid.append(manifest)
        manifest=self.manifest()
        manifest['samples'][1]['id']=manifest['samples'][0]['id']
        invalid.append(manifest)
        manifest=self.manifest()
        manifest['samples'][0]['source_capture_sha256']='unknown'
        invalid.append(manifest)
        manifest=self.manifest()
        manifest['samples']=[]
        invalid.append(manifest)
        for manifest in invalid:
            with self.subTest(manifest=manifest),self.assertRaises(ValueError):
                self.load(manifest)

    def test_first_prompt_difference(self):
        record={'prompt_token_ids':[1,2,3],'generated_ids':[7]}
        left={'requests':[record],'history_ids':[1,2,3,7]}
        right={'requests':[{'prompt_token_ids':[1,9,3],'generated_ids':[8]}],'history_ids':[1,9,3,8]}
        self.assertEqual(runtime.compare(left,right),{'request':0,'field':'prompt_token_ids','first_token_offset':1})

    def test_missing_requests_and_history_are_not_success(self):
        empty={'requests':[],'history_ids':[]}
        self.assertEqual(runtime.compare(empty,empty),{'field':'missing_requests'})
        left={'requests':[{'prompt_token_ids':[1],'generated_ids':[2]}],'history_ids':[1,2]}
        right=copy.deepcopy(left)
        right['history_ids']=[]
        self.assertEqual(runtime.compare(left,right),{'field':'committed_history'})

    def test_changed_official_source_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'server.py'
            path.write_text('pass\n')
            with self.assertRaises(ValueError):runtime.load_reference(path)

    @unittest.skipUnless(os.environ.get('DUPLEX_XTALK_LIFECYCLE'),'Remote X-Talk environment not requested')
    def test_cancelled_session_does_not_commit_into_restarted_session(self):
        from xtalk.duplex_control.micro_turn import MicroTurnAssembler
        from xtalk.duplex_control.model_client import GenerationEnd
        from xtalk.duplex_control.runtime_adapter import DuplexRuntimeAdapter
        from xtalk.serving.event_bus import EventBus, EventDispatchMode
        from xtalk.serving.events import ASRResultPartial, LLMAgentResponseUpdate

        async def check():
            entered=asyncio.Event()
            stopped=asyncio.Event()
            class OldClient:
                async def stream(self,history):
                    try:
                        yield '<|user finish talking|>Old partial answer'
                        entered.set()
                        await asyncio.Event().wait()
                        yield GenerationEnd('stop',(151648,151645))
                    finally:
                        stopped.set()
            class NewClient:
                async def stream(self,history):
                    self.prompt=copy.deepcopy(history)
                    yield '<|user finish talking|>New answer<|im_end|>'
                    yield GenerationEnd('stop',(151648,151645))
            old_bus=EventBus(enable_history=True,max_history=1000)
            old_assembler=MicroTurnAssembler(old_bus,'old',{'duplex_auto_tick':False})
            old_adapter=DuplexRuntimeAdapter(old_bus,'old',{'duplex_model_client':OldClient()})
            await old_bus.publish(ASRResultPartial(session_id='old',text='Old question'),
                                  mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
            pending=asyncio.create_task(old_assembler.flush())
            await asyncio.wait_for(entered.wait(),2)
            await old_adapter.shutdown()
            self.assertTrue(pending.cancelled())
            self.assertTrue(stopped.is_set())
            self.assertFalse(any(turn['role']=='assistant' for turn in old_adapter.history))
            updates=len(old_bus.get_history(event_type=LLMAgentResponseUpdate.TYPE))
            await old_assembler.flush()
            self.assertEqual(len(old_bus.get_history(event_type=LLMAgentResponseUpdate.TYPE)),updates)
            await old_assembler.shutdown()
            await old_bus.shutdown()
            new_bus=EventBus(enable_history=True,max_history=1000)
            client=NewClient()
            assembler=MicroTurnAssembler(new_bus,'new',{'duplex_auto_tick':False})
            adapter=DuplexRuntimeAdapter(new_bus,'new',{'duplex_model_client':client})
            try:
                await new_bus.publish(ASRResultPartial(session_id='new',text='New question'),
                                      mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
                await assembler.flush()
                self.assertEqual(client.prompt,[{'role':'user','text':'New question'}])
                self.assertEqual(adapter.history[-1]['token_ids'],[151648,151645])
                self.assertNotIn('Old',json.dumps(adapter.history))
            finally:
                await adapter.shutdown()
                await assembler.shutdown()
                await new_bus.shutdown()
        asyncio.run(check())

    @unittest.skipUnless(os.environ.get('DUPLEX_OFFICIAL_SOURCE'),'Pinned official source not provided')
    def test_official_ast_preserves_word_spacing_and_empty_window(self):
        class Tokenizer:
            bos_token_id=None
            eos_token_id=151645
            special={'<|im_start|>':151644,'<|im_end|>':151645,'<|no voice|>':151646,
                     '<|user is talking|>':151647,'<|user finish talking|>':151648,
                     '<|user is thinking|>':151649,'<|user interruption|>':151650,
                     '<|user backchannel|>':151651}
            def encode(self,text,add_special_tokens=False):
                return [self.special[part] if part in self.special else ord(part)+1000
                        for part in re.findall(r'<\|[^>]*\|>|.',text,re.DOTALL)]
            def decode(self,ids,skip_special_tokens=False):
                inverse={value:key for key,value in self.special.items()}
                return ''.join(inverse.get(value,'') if value in inverse else chr(value-1000) for value in ids)
        tokenizer=Tokenizer()
        args=SimpleNamespace(official_source=Path(os.environ['DUPLEX_OFFICIAL_SOURCE']))
        events=[{'type':'Word','arrival_seconds':.01,'text':' Hello '},
                {'type':'Word','arrival_seconds':.1,'text':'world'},
                {'type':'Word','arrival_seconds':.8,'text':' again '}]
        result=asyncio.run(runtime.reference(args,events,1.9,tokenizer,
                                            ['<|user is talking|><|im_end|>']))
        prompts=[tokenizer.decode(row['prompt_token_ids']) for row in result['requests']]
        self.assertEqual(len(prompts),3)
        self.assertIn('user\nHello world<|im_end|>',prompts[0])
        self.assertIn('user\nagain<|im_end|>',prompts[1])
        self.assertIn('user\n<|no voice|><|im_end|>',prompts[2])


if __name__=='__main__':unittest.main()
