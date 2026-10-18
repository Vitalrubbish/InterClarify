"""Check first-divergence reporting and the declared raw-prefix transport shim."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('runtime_comparison',Path(__file__).parents[1]/'scripts/remote/compare_layer1_runtime.py')
runtime=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class RuntimeComparisonTests(unittest.TestCase):
    """Do not let absent reference evidence or downstream differences look aligned."""

    def test_first_prompt_difference(self):
        record={'prompt_token_ids':[1,2,3],'generated_ids':[7]}
        left={'requests':[record],'history_ids':[1,2,3,7]}
        right={'requests':[{'prompt_token_ids':[1,9,3],'generated_ids':[8]}],'history_ids':[1,9,3,8]}
        self.assertEqual(runtime.compare(left,right),{'request':0,'field':'prompt_token_ids','first_token_offset':1})

    def test_incomplete_history_is_not_success(self):
        left={'requests':[],'history_ids':[1]}
        right={'requests':[],'history_ids':[]}
        self.assertEqual(runtime.compare(left,right),{'field':'committed_history'})

    def test_raw_transport_does_not_insert_spaces_within_word(self):
        buffer=runtime.RawDeltaBuffer(['hel','lo',' world'])
        self.assertEqual(' '.join(buffer),'hello world')
        buffer.clear()
        self.assertFalse(buffer)

    def test_changed_official_source_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'server.py'
            path.write_text('pass\n')
            with self.assertRaises(ValueError):runtime.load_reference(path)

    def test_complete_word_timeout_never_uses_future_characters(self):
        events=[{'arrival_seconds':0.,'text':'hel'},{'arrival_seconds':.2,'text':'hello world'}]
        output=runtime.complete_word_events(events)
        self.assertEqual(output,[{'arrival_seconds':.16,'text':'hel'},
                                 {'arrival_seconds':.2,'text':'hello '},
                                 {'arrival_seconds':.36,'text':'hello world'}])


if __name__=='__main__':unittest.main()
