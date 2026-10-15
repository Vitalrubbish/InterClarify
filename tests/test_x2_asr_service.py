"""Exercise the native X2 session protocol without GPU dependencies."""
from __future__ import annotations

import base64
import queue
import unittest
from types import SimpleNamespace

from scripts.remote.x2_asr_service import X2Service, RecognizeRequest


class FakeOnline:
    """Append one output per audio request and track EOF/abort."""

    def __init__(self):
        self.warmup_done = True
        self.error = None
        self.live_text = ""
        self.finished = 0
        self.aborted = False
        self._event_q = queue.Queue()

    def set_language_id(self, language):
        self.language = language

    def start(self):
        pass

    def append_pcm(self, audio):
        if len(audio):
            self.live_text += " word"

    def finish_async(self):
        self.finished += 1
        self.live_text += " tail"
        return SimpleNamespace(join=lambda timeout: None, is_alive=lambda: False)

    def abort(self):
        self.aborted = True


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


if __name__ == "__main__":
    unittest.main()
