"""Exercise X2 commitment, source identity, ordered pairs and cancellation."""
from contextlib import nullcontext
import hashlib
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts/remote'))
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts/runtime'))
from x2_teacher_frontend import X2TeacherFrontend, ClosedTextBuffer
from x2_teacher_worker import X2Session
from shared_context import STATE_IDS
from test_nemotron_teacher import FakeModel


class X2TeacherTests(unittest.TestCase):
    def make(self, predictions):
        import test_nemotron_teacher
        source_hash = hashlib.sha256(Path(test_nemotron_teacher.__file__).read_bytes()).hexdigest()
        with patch('nemotron_teacher_frontend.UPSTREAM_SHA256',source_hash), patch('nemotron_teacher_frontend.verify_tools'):
            return X2TeacherFrontend(FakeModel(predictions),'x2')

    def step(self, front, seq, text, **extra):
        import numpy as np
        step = dict(step_seq=seq,text=text,x2_open_group_tokens=0,x2_frames_consumed=2,x2_closed_groups=1)
        step.update(extra)
        return front.process_step(step,np.ones(2560,np.float32)*.01,None,None,seq*2560,seq*2560+640)

    def test_closed_text_is_injected_immediately_and_empty_steps_append_nothing(self):
        front = self.make([STATE_IDS['<|user_nonidle|>']]*3)
        a = self.step(front,1,'internet')
        b = self.step(front,2,'internet works')
        c = self.step(front,3,'internet works',x2_closed_groups=0)
        self.assertEqual(a['teacher_token_ids'],[1002])
        self.assertEqual(c['teacher_token_ids'],[])
        self.assertEqual(front.teacher_ids,front.model.model.tokenizer.encode('internet works'))
        self.assertEqual(b['text_commit_index'],c['text_commit_index'])
        for frame in (a,b,c):
            self.assertEqual(frame['source'],'x2_streaming_asr')
            self.assertTrue(frame['canonical_token_match'])
            self.assertFalse(any(frame[k] for k in ('pending_text','pending_token_ids','tail_reencode_count',
                                                     'tail_replace_tokens','post_pause_extension')))
        self.assertEqual(c['empty_run_length'],1)
        self.assertEqual(front.close()['source'],'x2_streaming_asr')

    def test_open_groups_and_wrong_pair_size_fail_before_injection(self):
        for extra in ({'x2_open_group_tokens':1},{'x2_frames_consumed':1}):
            front = self.make([])
            with self.assertRaises(ValueError):
                self.step(front,1,'unclosed',**extra)
            self.assertEqual(front.model.calls,[])

    def test_canonical_prefix_mismatch_fails_without_suffix_degradation(self):
        front = self.make([STATE_IDS['<|user_nonidle|>']]*2)
        self.step(front,1,'inter')
        with self.assertRaisesRegex(ValueError,'Canonical tokenization'):
            self.step(front,2,'internet')
        self.assertEqual(len(front.model.calls),1)
        with self.assertRaises(ValueError):
            front.text._extension('internet')

    def test_rule_attribution_reports_actual_rewrite(self):
        front = self.make([STATE_IDS['<|user_nonidle|>']]*3)
        rows = [self.step(front,i,'',x2_closed_groups=0) for i in (1,2,3)]
        self.assertEqual([r['empty_run_length'] for r in rows],[1,2,3])
        self.assertEqual([r['rule_applied'] for r in rows],[False,False,True])
        self.assertAlmostEqual(rows[-1]['chunk_rms'],.01,places=6)

    def test_x2_source_cannot_switch_mid_turn(self):
        front = self.make([STATE_IDS['<|user_nonidle|>']])
        self.step(front,1,'hello')
        context = front.context.context
        frame = context.get_user_turn('x2','user-1')
        frame.update(source='nemotron',processed_until=5120,audio_observed_until=5760)
        with self.assertRaises(ValueError):
            context.publish_user_frame(frame)


class X2SessionTests(unittest.TestCase):
    def test_two_frames_aggregate_in_order_and_cancel_terminates(self):
        import numpy as np
        class Engine:
            torch = SimpleNamespace(inference_mode=nullcontext)
            groups = SimpleNamespace(text='')
            memory_samples = [100]

            def reset(self):
                self.groups.text = ''
                self.count = 0

            def step(self, audio, on_token):
                self.groups.text += chr(97+self.count)
                token = 100+self.count
                self.count += 1
                return {'compute_ms':1.,'closed_groups':1,'token_ids':[33,token,2]}

        session = X2Session(Engine())
        try:
            session.source.append(np.zeros(4000,dtype='<i2').tobytes())
            deadline = time.monotonic()+2
            while not session.poll(0)['steps'] and time.monotonic()<deadline:
                time.sleep(.001)
            step = session.poll(0)['steps'][0]
            self.assertEqual(step['text'],'ab')
            self.assertEqual(step['x2_frame_tokens'],[[33,100,2],[33,101,2]])
            self.assertEqual(step['consumed_samples'],2760)
            self.assertEqual(step['main_audio_end_sample'],2560)
            self.assertEqual(step['x2_frames_consumed'],2)
            self.assertEqual(step['x2_closed_groups'],2)
            with self.assertRaises(ValueError):
                session.release(2,time.monotonic())
            session.release(1,time.monotonic())
            with self.assertRaises(ValueError):
                session.release(1,time.monotonic())
        finally:
            session.close()
        self.assertFalse(session.worker.is_alive())
        self.assertIsNone(session.error)


if __name__=='__main__':
    unittest.main()
