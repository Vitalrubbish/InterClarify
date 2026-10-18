"""Ensure an explicit wrapper exception cannot admit incomplete benchmark evidence."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('tts_report',Path(__file__).parents[1]/'scripts/tts_selection_report.py')
report=importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class CollectionGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'run'
        measurements=self.source/'measurements'
        measurements.mkdir(parents=True)
        (self.source/'exit_code.txt').write_text('127\n')
        (self.source/'client.log').write_text('measurements completed\n')
        (measurements/'corpus_sha256.txt').write_text('test-fixture')
        (measurements/'summary.json').write_text(json.dumps({'attempted':60,'successful':60}))
        for index in range(60):
            row={'error':None,'id':str(index),'listening':'no','audio_seconds':1.,'sample_rate':1000,
                 'chunks':[{'samples':1000,'arrival_seconds':.1}]}
            (measurements/f'measured_{index:02d}.json').write_text(json.dumps(row))

    def args(self, accept):
        return argparse.Namespace(output=self.root/'collected',candidate=[f'moss={self.source}'],
                                  accept_wrapper_failure=['moss'] if accept else [])

    def test_wrapper_failure_is_rejected_by_default(self):
        with self.assertRaises(ValueError):
            report.collect(self.args(False))

    def test_explicit_exception_preserves_nonzero_status(self):
        report.collect(self.args(True))
        self.assertEqual((self.root/'collected/moss/exit_code.txt').read_text(),'127\n')

    def test_exception_does_not_admit_missing_sample(self):
        (self.source/'measurements/measured_00.json').unlink()
        with self.assertRaises(ValueError):
            report.collect(self.args(True))

    def test_exception_does_not_admit_truncated_audio(self):
        path=self.source/'measurements/measured_00.json'
        row=json.loads(path.read_text())
        row['audio_seconds']=2.
        path.write_text(json.dumps(row))
        with self.assertRaises(ValueError):
            report.collect(self.args(True))


if __name__=='__main__':
    unittest.main()
