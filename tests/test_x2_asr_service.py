"""Exercise the native X2 session protocol without GPU dependencies."""
from __future__ import annotations

import base64
import queue
import threading
import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from scripts.remote.x2_asr_service import X2Service, RecognizeRequest, create_app


class FakeOnline:
    """Append one output per audio request and track EOF/abort."""

    def __init__(self):
        self.warmup_done = True
        self.error = None
        self.live_text = ""
        self.finished = 0
        self.aborted = False
        self._event_q = queue.Queue()
        self.append_count = 0

    def set_language_id(self, language):
        self.language = language

    def start(self):
        pass

    def append_pcm(self, audio):
        self.append_count += 1
        if len(audio):
            self.live_text += " word"

    def finish_async(self):
        self.finished += 1
        self.live_text += " tail"
        return SimpleNamespace(join=lambda timeout: None, is_alive=lambda: False)

    def abort(self):
        self.aborted = True


class DeferredOnline(FakeOnline):
    """Commit online text only after the audio request has already returned."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.emitted = threading.Event()
        self.worker = None

    def append_pcm(self, audio):
        """Start a background emit controlled by the test."""
        self.append_count += 1

        def emit():
            """Simulate delayed model completion without another audio request."""
            if self.release.wait(2):
                self.live_text = "Wednesday or Thursday"
                self._event_q.put({"kind": "live_emit", "text": self.live_text})
                self.emitted.set()

        self.worker = threading.Thread(target=emit)
        self.worker.start()

    def abort(self):
        """Release and join the fake model worker."""
        self.aborted = True
        self.release.set()
        if self.worker is not None:
            self.worker.join(2)


class X2ServiceTest(unittest.TestCase):
    """Protect native pause handling and online-only finalization."""

    def test_pause_resume_and_eof(self):
        engine = FakeOnline()
        service = X2Service(lambda: engine)
        sid = service.create()
        audio = base64.b64encode(b"\x00\x00").decode()
        self.assertEqual(service.recognize(RecognizeRequest(session_id=sid, audio=audio)), " word")
        service.recognize(RecognizeRequest(session_id=sid, is_final=True))
        self.assertEqual(engine.finished, 0)
        self.assertEqual(service.recognize(RecognizeRequest(session_id=sid, audio=audio)), " word word")
        self.assertEqual(service.recognize(RecognizeRequest(session_id=sid, end_stream=True)), " word word tail")
        service.recognize(RecognizeRequest(session_id=sid, end_stream=True))
        self.assertEqual(engine.finished, 1)
        service.close(sid)
        self.assertTrue(engine.aborted)

    def test_single_session_and_invalid_pcm(self):
        service = X2Service(FakeOnline)
        sid = service.create()
        with self.assertRaises(RuntimeError):
            service.create()
        with self.assertRaises(KeyError):
            service.recognize(RecognizeRequest(session_id="wrong"))
        with self.assertRaises(ValueError):
            service.recognize(RecognizeRequest(session_id=sid, audio="YQ=="))
        service.close(sid)
        service.create()

    def test_warmup_uses_one_session_and_releases_it(self):
        engine = FakeOnline()
        service = X2Service(lambda: engine, timeout=5)
        service.warmup(seconds=0.08)
        self.assertIsNone(service.session)
        self.assertIsNone(service.session_id)
        self.assertTrue(engine.aborted)
        session_id = service.create()
        # The fake keeps its text across sessions, so the warmup append is still counted.
        self.assertEqual(service.recognize(
            RecognizeRequest(session_id=session_id,
                             audio=base64.b64encode(b"\x00\x00").decode())), " word word")

    def test_read_delivers_late_emit_without_more_audio_or_eof(self):
        """A micro-turn can fetch already completed output after input stops."""
        engine = DeferredOnline()
        service = X2Service(lambda: engine)
        sid = service.create()
        self.addCleanup(service.close, sid)
        text = service.recognize(RecognizeRequest(
            session_id=sid, audio=base64.b64encode(b"\x00\x00").decode()))
        self.assertEqual(text, "")
        self.assertEqual(service.read(sid), "")
        engine.release.set()
        self.assertTrue(engine.emitted.wait(1))
        for _ in range(2):
            self.assertEqual(service.read(sid), "Wednesday or Thursday")
        self.assertEqual(engine.append_count, 1)
        self.assertEqual(engine.finished, 0)
        self.assertEqual(service.audio_samples, 1)
        service.close(sid)
        with self.assertRaises(KeyError):
            service.read(sid)

    def test_read_route_validates_session_and_reports_worker_errors(self):
        """Read-only HTTP requests preserve input and expose model failures."""
        engine = FakeOnline()
        service = X2Service(lambda: engine)
        with TestClient(create_app(service)) as client:
            self.assertEqual(client.get('/v1/session/missing/result').status_code, 404)
            sid = client.post('/v1/session').json()['session_id']
            engine.live_text = 'late text'
            response = client.get(f'/v1/session/{sid}/result')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'text': 'late text', 'language': 'en'})
            self.assertEqual(engine.append_count, 0)
            self.assertEqual(engine.finished, 0)
            engine.error = 'decoder failed'
            self.assertEqual(client.get(f'/v1/session/{sid}/result').status_code, 500)
            client.delete(f'/v1/session/{sid}')
            self.assertEqual(client.get(f'/v1/session/{sid}/result').status_code, 404)


if __name__ == "__main__":
    unittest.main()
