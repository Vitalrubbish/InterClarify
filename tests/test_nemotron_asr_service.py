"""Test live native ASR ownership and failure paths without model weights."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

SPEC = importlib.util.spec_from_file_location('nemotron_service', Path(__file__).parents[1] / 'scripts/remote/nemotron_asr_service.py')
service = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = service
SPEC.loader.exec_module(service)


class FakeEngine:
    """Consume actual windows and emit asynchronously without future input."""

    info = {'backend': 'nemotron_en'}

    def run(self, source, emit):
        index = 0
        while source.read(index * 1280, 1280) is not None:
            index += 1
            emit('word ' * index, [index])


class NemotronServiceTests(unittest.TestCase):
    """Verify read-without-audio, EOF, pause, cancellation and strict identities."""

    def test_float_wav_keeps_speech_amplitude(self):
        """Float WAV must be normalized before PCM16 conversion, not rounded to zero."""
        import soundfile as sf
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'speech.wav'
            sf.write(str(path),np.array([.25,-.5,.125],dtype=np.float32),16000,subtype='FLOAT')
            pcm=service.load_pcm16(path)
            self.assertEqual(np.frombuffer(pcm,dtype='<i2').tolist(),[8191,-16383,4095])

    def test_pause_read_and_cancel(self):
        model = service.NemotronService(FakeEngine(), timeout=1)
        model.ready = True
        with TestClient(service.create_app(model)) as client:
            identity = client.post('/v1/session').json()['session_id']
            self.assertEqual(client.post('/v1/session').status_code, 409)
            import base64
            payload = {'session_id': identity, 'audio': base64.b64encode(b'\0\0'*1280).decode()}
            self.assertEqual(client.post('/v1/recognize', json=payload).status_code, 200)
            for _ in range(100):
                result = client.get(f'/v1/session/{identity}/result').json()
                if result['text']:
                    break
                time.sleep(.001)
            self.assertEqual(result['text'], 'word ')
            self.assertFalse(result['ended'])
            self.assertEqual(client.post('/v1/recognize', json={'session_id': identity, 'is_final': True}).status_code, 200)
            self.assertFalse(model.session.source.eof)
            self.assertEqual(client.delete(f'/v1/session/{identity}').status_code, 200)
            self.assertEqual(client.get(f'/v1/session/{identity}/result').status_code, 404)
            other = client.post('/v1/session').json()['session_id']
            self.assertNotEqual(identity, other)
            self.assertEqual(client.get(f'/v1/session/{other}/result').json()['text'], '')
            client.delete(f'/v1/session/{other}')

    def test_eof_tail_and_input_bounds(self):
        source = service.AudioBuffer(max_pending_seconds=1, drain_seconds=.08)
        source.append(b'\x01\0'*10, eof=True)
        self.assertEqual(len(source.read(0,1280)),1280)
        self.assertEqual(source.received,10)
        self.assertIsNone(source.read(1290,1280))
        with self.assertRaises(ValueError):
            source.append(b'\0\0')
        source = service.AudioBuffer(max_pending_seconds=.01)
        with self.assertRaises(ValueError):
            source.append(b'\0\0'*1000)

    def test_rewrite_fails_closed(self):
        model = service.NemotronService(FakeEngine(), timeout=1)
        identity = model.create()
        session = model.get(identity)
        session.emit('hello', [1])
        with self.assertRaises(RuntimeError):
            session.emit('world', [2])
        model.close(identity)


if __name__ == '__main__':
    unittest.main()
