"""Verify the ASR service's wire contract and append-only visible transcript."""

import base64
import importlib.util
import io
import sys
import unittest
import wave
from pathlib import Path

from fastapi.testclient import TestClient

SPEC = importlib.util.spec_from_file_location(
    'qwen3_service', Path(__file__).parents[1] / 'scripts/remote/qwen3_asr_service.py')
service = importlib.util.module_from_spec(SPEC)
# Pydantic resolves nested model annotations through sys.modules.
sys.modules[SPEC.name] = service
SPEC.loader.exec_module(service)


class FakeTokenizer:
    """Round-trip a tiny whitespace vocabulary through stable integer ids."""

    def __init__(self):
        self._to_id = {}
        self._to_word = {}

    def encode(self, text):
        """Return one id per whitespace separated word, allocating on demand."""
        ids = []
        for word in str(text).split():
            if word not in self._to_id:
                value = len(self._to_id) + 1
                self._to_id[word] = value
                self._to_word[value] = word
            ids.append(self._to_id[word])
        return ids

    def decode(self, ids):
        """Render ids back as the exact words they were encoded from."""
        return ' '.join(self._to_word[token_id] for token_id in ids)


class FakeModel:
    """Serve scripted parsed transcripts one decode step at a time."""

    def __init__(self, steps):
        self.processor = type('Processor', (), {'tokenizer': FakeTokenizer()})()
        self.steps = list(steps)
        self.calls = 0

    def init_streaming_state(self, **kwargs):
        """Return a state whose text the scripted steps advance."""
        state = type('State', (), {})()
        state.chunk_id = 0
        state.force_language = None
        state.language = 'English'
        state.text = ''
        state._raw_decoded = ''
        return state

    def streaming_transcribe(self, samples, state):
        """Advance the scripted parsed transcript by one step."""
        if not len(samples):
            return
        state.text = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1

    def finish_streaming_transcribe(self, state):
        """Release the whole scripted transcript, as the real decoder does on final."""
        state.text = self.steps[-1]


def make_pcm(samples):
    """Return a silent PCM16 payload of ``samples`` frames without a WAV header."""
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b'\x00\x00' * samples)
    return buffer.getvalue()[44:]


def make_service(model, emit_committed_prefix, hidden_token_num=2):
    """Return a service whose model is replaced by ``model``."""
    asr = service.ASRService.__new__(service.ASRService)
    asr.model = model
    asr.emit_committed_prefix = emit_committed_prefix
    asr.hidden_token_num = hidden_token_num
    asr.streaming_kwargs = {'chunk_size_sec': 0.6, 'unfixed_chunk_num': 0,
                            'unfixed_token_num': hidden_token_num}
    asr._sessions = {}
    asr._lock = service.threading.Lock()
    return asr


class CommittedTokenIdsTests(unittest.TestCase):
    """The hidden tail is exactly the decoder's revision window."""

    def test_drops_the_trailing_tokens(self):
        """Token count drives the cut, and a prefix decodes back to text."""
        class OneTokenPerCharacter:
            def encode(self, text):
                return list(range(len(text)))

            def decode(self, ids):
                return 'x' * len(list(ids))

        model = type('M', (), {'processor': type('P', (), {'tokenizer': OneTokenPerCharacter()})()})()
        self.assertEqual(service.committed_token_ids(model, 'aaaaaa', 2), [0, 1, 2, 3])
        self.assertEqual(service.committed_token_ids(model, 'aa', 5), [])
        self.assertEqual(service.decode_token_prefix(model, [0, 1, 2]), 'xxx')
        self.assertEqual(service.decode_token_prefix(model, []), '')


class AdvanceCommittedTests(unittest.TestCase):
    """The committed stream is a token prefix that only ever extends."""

    def test_growing_transcript_hides_the_revision_window(self):
        """While new text arrives, the tail is held back."""
        model = FakeModel(['w1 w2 w3 w4 w5 w6 w7'])
        state = model.init_streaming_state()
        model.streaming_transcribe([1], state)
        ids, visible, stalled = service.advance_committed(model, state.text, 2, [], '')
        self.assertEqual(visible, 'w1 w2 w3 w4 w5')
        self.assertEqual(len(ids), 5)
        self.assertFalse(stalled)

    def test_repunctuated_transcript_keeps_committing(self):
        """A re-decode that only restyles the tail must not stall the stream.

        The regression this guards: comparing *strings* froze the commit as soon
        as the decoder re-emitted an earlier word with different punctuation
        (``'I never like.'`` then ``'I never like I know'``), after which the
        runtime only ever saw the first words of the user's turn.
        """
        model = FakeModel(['I never like.', 'I never like I know',
                           'I never like I know a lot of people'])
        state = model.init_streaming_state()
        model.streaming_transcribe([1], state)
        ids, visible, stalled = service.advance_committed(model, state.text, 5, [], '')
        # Everything so far is inside the revision window: nothing is committed.
        self.assertEqual(visible, '')
        self.assertFalse(stalled)
        model.streaming_transcribe([1], state)
        ids, visible, _ = service.advance_committed(model, state.text, 5, ids, visible)
        self.assertEqual(visible, '')
        model.streaming_transcribe([1], state)
        # nine tokens, five of them held back: four words are committed
        ids, visible, stalled = service.advance_committed(model, state.text, 5, ids, visible)
        self.assertEqual(visible, 'I never like I')
        self.assertFalse(stalled)

    def test_silence_does_not_release_the_held_back_tail(self):
        """Only an explicit boundary releases the tail, not an unchanged decode."""
        model = FakeModel(['w1 w2 w3 w4 w5 w6 w7'])
        state = model.init_streaming_state()
        model.streaming_transcribe([1], state)
        ids, visible, _ = service.advance_committed(model, state.text, 5, [], '')
        self.assertEqual(visible, 'w1 w2')
        # A pause inside the turn leaves the decoder output unchanged; that is not
        # an end of the user's segment, so the tail stays held back.
        model.streaming_transcribe([1], state)
        ids, visible, _ = service.advance_committed(model, state.text, 5, ids, visible)
        self.assertEqual(visible, 'w1 w2')

    def test_revision_deeper_than_the_window_keeps_released_text(self):
        """A revision of released text cannot be taken back; it is reported."""
        model = FakeModel(['w1 w2 w3 w4 w5 w6 w7', 'w1 w2 wX wY w5 w6 w7'])
        state = model.init_streaming_state()
        model.streaming_transcribe([1], state)
        ids, visible, _ = service.advance_committed(model, state.text, 2, [], '')
        released = visible
        self.assertEqual(released, 'w1 w2 w3 w4 w5')
        model.streaming_transcribe([1], state)
        ids, visible, stalled = service.advance_committed(model, state.text, 2, ids, visible)
        self.assertTrue(stalled)
        self.assertEqual(visible, released)

    def test_commit_resumes_once_the_decoder_agrees_again(self):
        """A stall is not permanent: later agreement extends the stream."""
        model = FakeModel(['w1 w2 w3 w4 w5 w6 w7', 'w1 w2 wX wY w5 w6 w7',
                           'w1 w2 w3 w4 w5 w6 w7 w8 w9'])
        state = model.init_streaming_state()
        model.streaming_transcribe([1], state)
        ids, visible, _ = service.advance_committed(model, state.text, 2, [], '')
        model.streaming_transcribe([1], state)
        ids, visible, stalled = service.advance_committed(model, state.text, 2, ids, visible)
        self.assertTrue(stalled)
        model.streaming_transcribe([1], state)
        ids, visible, stalled = service.advance_committed(model, state.text, 2, ids, visible)
        self.assertFalse(stalled)
        self.assertEqual(visible, 'w1 w2 w3 w4 w5 w6 w7')


class OwnedServiceContractTests(unittest.TestCase):
    """HTTP exposes extensions and ``is_final`` releases the whole transcript."""

    def test_pause_resume_uses_fresh_decoder_and_preserves_repetitions(self):
        """Finalized punctuation cannot lock the following acoustic segment."""
        class SegmentModel(FakeModel):
            def finish_streaming_transcribe(self, state):
                state.text += '.'

        model = SegmentModel(['I know', 'I know people well'])
        asr = make_service(model, True, hidden_token_num=1)
        sid = asr.create_session()
        pcm = base64.b64encode(make_pcm(600)).decode('ascii')
        def recognize(audio='', final=False):
            return asr.recognize(service.RecognizeRequest(
                session_id=sid, audio=audio, is_final=final))[0]
        first_state = asr._sessions[sid].state
        self.assertEqual(recognize(pcm), 'I')
        self.assertEqual(recognize(final=True), 'I know.')
        self.assertIsNot(asr._sessions[sid].state, first_state)
        self.assertEqual(recognize(final=True), 'I know.')
        self.assertEqual(asr._sessions[sid].segment_index, 1)
        self.assertEqual(recognize(pcm), 'I know. I know people')
        self.assertEqual(recognize(final=True), 'I know. I know people well.')
        self.assertEqual(model.calls, 2)

    def test_final_cannot_rewrite_released_prefix(self):
        """A final decode conflict is observable and cannot replace visible text."""
        class ConflictingModel(FakeModel):
            def finish_streaming_transcribe(self, state):
                state.text = 'changed words completely'

        asr = make_service(ConflictingModel(['old words tail']), True, hidden_token_num=1)
        sid = asr.create_session()
        pcm = base64.b64encode(make_pcm(600)).decode('ascii')
        asr.recognize(service.RecognizeRequest(session_id=sid, audio=pcm))
        with self.assertLogs(service.logger, level='WARNING'):
            text, _ = asr.recognize(service.RecognizeRequest(session_id=sid, is_final=True))
        self.assertEqual(text, 'old words')
        self.assertEqual(asr._sessions[sid].stalls, 1)

    def test_chinese_segment_join(self):
        """Chinese boundaries do not insert ASCII word spaces."""
        self.assertEqual(service.join_segments('你好。', '你好'), '你好。你好')

    def test_session_lifecycle(self):
        """Sessions can be created, updated, finalized and released."""
        model = FakeModel(['w1 w2 w3 w4 w5 w6 w7', 'w1 w2 w3 w4 w5 w6 w7 w8 w9'])
        asr = make_service(model, emit_committed_prefix=True)
        pcm = base64.b64encode(make_pcm(600)).decode('ascii')
        with TestClient(service.build_app(asr)) as client:
            self.assertEqual(client.get('/health').json(), {'status': 'ok'})
            session_id = client.post('/v1/session').json()['session_id']
            body = {'session_id': session_id, 'audio': pcm, 'is_final': False}
            first = client.post('/v1/recognize', json=body).json()['text']
            second = client.post('/v1/recognize', json=body).json()['text']
            self.assertTrue(second.startswith(first), (first, second))
            released = client.post('/v1/recognize', json=dict(body, is_final=True)).json()['text']
            self.assertTrue(released.startswith(second), (second, released))
            self.assertEqual(client.post('/v1/recognize',
                                        json={'session_id': 'missing', 'audio': pcm}).status_code, 404)
            self.assertEqual(client.delete(f'/v1/session/{session_id}').json(), {'ok': True})

    def test_visible_text_never_carries_a_language_header(self):
        """The header of the raw decode must not reach the caller.

        The regression this guards: truncating the *raw* string cut inside
        ``language English<asr_text>`` and handed the model the word "language".
        """
        model = FakeModel(['language English'])
        asr = make_service(model, emit_committed_prefix=True)
        session_id = asr.create_session()
        text, _language = asr.recognize(service.RecognizeRequest(
            session_id=session_id, audio=base64.b64encode(make_pcm(600)).decode('ascii')))
        self.assertNotIn('language', text.lower())

    def test_default_mode_still_returns_the_raw_transcript(self):
        """Without the flag the service keeps its historical contract."""
        model = FakeModel(['w1 w2 w3 w4 w5 w6 w7'])
        asr = make_service(model, emit_committed_prefix=False)
        session_id = asr.create_session()
        text, language = asr.recognize(service.RecognizeRequest(
            session_id=session_id, audio=base64.b64encode(make_pcm(600)).decode('ascii')))
        self.assertEqual(text, 'w1 w2 w3 w4 w5 w6 w7')
        self.assertEqual(language, 'English')


if __name__ == '__main__':
    unittest.main()
