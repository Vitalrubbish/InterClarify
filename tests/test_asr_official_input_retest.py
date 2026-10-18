"""Verify official frame formatting and endpoint counting without model weights."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

spec=importlib.util.spec_from_file_location('input_retest',Path(__file__).parents[1]/'scripts/remote/retest_asr_official_input.py')
retest=importlib.util.module_from_spec(spec)
spec.loader.exec_module(retest)


class OfficialInputRetestTests(unittest.TestCase):
    """Check token boundaries and distinguish new replies from old continuations."""

    def test_official_text_boundaries_and_generated_history(self):
        class Tokenizer:
            def encode(self,text,add_special_tokens=False):
                return SimpleNamespace(ids=[ord(c) for c in text])
        history=[{'role':'user','text':' hello '},
                 {'role':'assistant','token_ids':[999,998]},
                 {'role':'user','text':' world. '},
                 {'role':'assistant','token_ids':[997]},
                 {'role':'user','text':' \t '}]
        first='<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n'
        second='<|im_start|>user\nworld.<|im_end|>\n<|im_start|>assistant\n'
        final='<|im_start|>user\n<|no voice|><|im_end|>\n<|im_start|>assistant\n'
        expected=[ord(c) for c in first]+[999,998]+[ord(c) for c in second]+[997]+[ord(c) for c in final]
        self.assertEqual(retest.reference_prompt_ids(Tokenizer(),history),expected)
        self.assertEqual(retest.reference_prompt_ids(Tokenizer(),history,7),[7]+expected)

    def test_old_response_continuation_is_not_a_new_reply(self):
        events=[{'kind':'text','at':1.,'response_id':'old','text':'Hello'},
                {'kind':'text','at':3.,'response_id':'old','text':'Hello again'},
                {'kind':'control','at':3.1,'response_id':'old','state_token':'<|user finish talking|>'}]
        result=retest.response_metrics(events,2.,14.)
        self.assertFalse(result['new_reply_within_2s'])
        self.assertEqual(result['cross_boundary_continuation_ids'],['old'])

    def test_new_reply_keeps_later_cancellation(self):
        events=[{'kind':'text','at':2.5,'response_id':'new','text':'Answer'},
                {'kind':'cancel','at':3.,'response_id':'new'}]
        result=retest.response_metrics(events,2.,14.)
        self.assertTrue(result['new_reply_within_2s'])
        self.assertEqual(result['first_new_reply_seconds'],.5)
        self.assertTrue(result['first_new_reply_later_cancelled'])

    def test_unverified_official_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'server.py'
            path.write_text('pass\n')
            with self.assertRaises(ValueError):
                retest.verify_official_reference(path,None,None)


if __name__=='__main__':
    unittest.main()
