"""Protect complete-corpus coverage and immutable input staging."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('full_fdb_axes',
    Path(__file__).parents[1]/'scripts/remote/full_fdb_two_axes.py')
full=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(full)


class FullCorpusStagingTests(unittest.TestCase):
    """Reject stale manifests and preserve every frozen example."""

    def setUp(self):
        """Create a bounded corpus with old generated files outside its inventory."""
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.axes={'candor_turn_taking':('smooth_turn_taking',1,'turn_taking.json'),
                   'synthetic_user_interruption':('user_interruption',1,'interrupt.json')}
        self.patcher=patch.object(full,'AXES',self.axes)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        samples=[]
        for subset,(_,_,annotation) in self.axes.items():
            directory=self.root/'data'/subset/'1'
            directory.mkdir(parents=True)
            (directory/'input.wav').write_bytes(b'original audio')
            (directory/annotation).write_text('[]')
            (directory/'output.wav').write_bytes(b'old generated audio')
            samples.append({'subset':subset,'id':'1','files':{
                name:{'bytes':(directory/name).stat().st_size,'sha256':full.digest(directory/name)}
                for name in ('input.wav',annotation)}})
        self.manifest=self.root/'manifest.json'
        self.manifest.write_text(json.dumps({'remote_root':str(self.root/'data'),'samples':samples}))
        self.output=self.root/'output'

    def test_full_staging_excludes_old_outputs(self):
        """All frozen inputs arrive while generated artifacts remain excluded."""
        full.stage(self.manifest,self.output)
        self.assertEqual(len(list(self.output.glob('*/*/input.wav'))),2)
        self.assertFalse(list(self.output.rglob('output.wav')))
        with self.assertRaises(FileExistsError):
            full.stage(self.manifest,self.output)

    def test_changed_input_does_not_create_partial_output(self):
        """A single changed source fails before any destination is created."""
        (self.root/'data/candor_turn_taking/1/input.wav').write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            full.stage(self.manifest,self.output)
        self.assertFalse(self.output.exists())

    def test_unfrozen_example_cannot_be_silently_omitted(self):
        """A newly added sample requires a new complete-corpus manifest."""
        (self.root/'data/candor_turn_taking/2').mkdir()
        with self.assertRaises(ValueError):
            full.stage(self.manifest,self.output)
        self.assertFalse(self.output.exists())

    def test_generated_file_in_inventory_is_rejected(self):
        """Historical outputs cannot masquerade as reference inputs."""
        data=json.loads(self.manifest.read_text())
        data['samples'][0]['files']['output.wav']={}
        self.manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            full.stage(self.manifest,self.output)


class OfficialTimingRuleTests(unittest.TestCase):
    """Preserve official timing thresholds without requiring a GPT judge."""

    def test_thresholds_missing_response_and_negative_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            specifications=[('empty',[]),('short3',[(1.1,1.3),(1.4,1.6),(1.7,1.9)]),
                ('short4',[(1.1,1.2)]*4),('one_second',[(.2,.5),(.6,1.2)])]
            for name,words in specifications:
                p=root/name;p.mkdir()
                (p/'interrupt.json').write_text(json.dumps([{'timestamp':[0,1]}]))
                (p/'output.json').write_text(json.dumps({'chunks':[{'timestamp':list(t)} for t in words]}))
            result=full.timing_metrics(root,'user_interruption')
            rows={r['sample']:r for r in result['samples']}
            self.assertEqual(rows['empty']['take_turn'],0)
            self.assertEqual(rows['short3']['take_turn'],0)
            self.assertEqual(rows['short4']['take_turn'],1)
            self.assertEqual(rows['one_second']['take_turn'],1)
            self.assertAlmostEqual(rows['one_second']['raw_latency'],-.8)
            self.assertEqual(rows['one_second']['official_latency'],0)
            self.assertEqual(result['scores']['average_take_turn'],.5)
            self.assertAlmostEqual(result['scores']['average_latency'],.05)

    def test_no_turn_has_no_mean_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'1';p.mkdir()
            (p/'turn_taking.json').write_text(json.dumps([{'timestamp':[1]}]))
            (p/'output.json').write_text(json.dumps({'chunks':[]}))
            result=full.timing_metrics(Path(tmp),'smooth_turn_taking')
            self.assertEqual(result['scores']['average_take_turn'],0)
            self.assertIsNone(result['scores']['average_latency'])
