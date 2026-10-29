"""Check label preservation, ambiguous windows and real capture transactions."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/runtime'))
from shared_context import FrontendConsumer, SharedContext, STATE_IDS
from sensevoice_transcript import SenseVoiceObservation, TurnTranscriptAssembler
from soulx_frontend import SoulXFrontend, slice_spans


def observation(text, start=0, end=16000):
    return dict(SenseVoiceObservation.parse(text), call_status='ok',
                audio_spans=[{'kind': 'real', 'start': start, 'end': end, 'samples': end-start}])


def protocol_frontend():
    # Exercise the real publication methods without importing any GPU backend.
    frontend = SoulXFrontend.__new__(SoulXFrontend)
    frontend.context = SharedContext()
    frontend.session_id, frontend.turn_id = 's', 't'
    frontend.producer_seq = frontend.controller_generation = frontend.control_revision = 0
    frontend.asr_generation, frontend.clock_id = 'g', 'test'
    frontend.assembler = TurnTranscriptAssembler()
    frontend.delivery_phase, frontend.closed = 'online', False
    frontend.on_commit = frontend.audit = None
    frontend._calls = []
    frontend.active_output = frontend.stop_output = None
    frontend._stopped = set()
    frontend.processed_until = 16000
    event = frontend._event('user_transcript', source='sensevoice_small', version=0,
                            asr_version=0, text='', status='open')
    frontend._commit([event])
    frontend.snapshot = event
    return frontend


class SoulXFrontendTests(unittest.TestCase):
    def test_raw_labels_preserve_digits_punctuation_and_unknowns(self):
        raw = '<|en|><|NEUTRAL|><|Speech|><|withitn|>The. 123. I\'m here.'
        parsed = SenseVoiceObservation.parse(raw)
        self.assertEqual(parsed['text'], "The. 123. I'm here.")
        self.assertEqual([t['token'] for t in parsed['tags']],
                         ['<|en|>', '<|NEUTRAL|>', '<|Speech|>', '<|withitn|>'])
        for span in parsed['character_map']:
            self.assertEqual(parsed['text'][span['text_start']:span['text_end']],
                             raw[span['raw_start']:span['raw_end']])
        unknown = SenseVoiceObservation.parse('<|en|><|future|>hello<|Speech|>!')
        self.assertEqual(unknown['text'], '<|future|>hello!')
        self.assertFalse(unknown['tags'][1]['known'])

    def test_same_origin_revision_unique_slide_and_ambiguous_gap(self):
        assembler = TurnTranscriptAssembler()
        assembler.apply_window(observation('I want to book a flight to Paris', end=32000))
        update = assembler.apply_window(observation('book a flight to London tomorrow', 16000, 48000))
        self.assertEqual(update['text'], 'I want to book a flight to London tomorrow')
        self.assertEqual(update['base_asr_version'], 1)
        update = assembler.apply_window(observation('yes yes', 32000, 64000))
        self.assertEqual(update['assembly_status'], 'gap')
        self.assertEqual(update['asr_version'], 2)
        assembler.apply_window(observation('Corrected full turn.', 0, 64000))
        self.assertEqual(assembler.text, 'Corrected full turn.')
        self.assertTrue(assembler.coverage_complete)
        repeat = TurnTranscriptAssembler()
        repeat.apply_window(observation('yes yes yes yes done', end=32000))
        self.assertEqual(repeat.apply_window(observation('yes yes done', 16000, 48000))['assembly_status'], 'gap')

    def test_capture_is_visible_before_state_and_close_preserves_text(self):
        frontend = protocol_frontend()
        readers = [FrontendConsumer('s'), FrontendConsumer('s')]
        frontend.observe_asr('<|en|>hello', observation('')['audio_spans'], asr_call_id='a', call_kind='window')
        for reader in readers:
            events = reader.consume(frontend.context)
            self.assertEqual(reader.turns['t']['text'], 'hello')
            self.assertFalse(any(e['kind'] == 'user_state' for e in events))
        frontend.observe_asr('', observation('')['audio_spans'], asr_call_id='b', call_kind='window', call_status='error')
        self.assertEqual(frontend.snapshot['text'], 'hello')
        frontend.close_turn()
        frontend.observe_asr('<|en|>late', observation('')['audio_spans'], asr_call_id='c', call_kind='turn')
        self.assertEqual(frontend.context.get_user_turn('s', 't')['transcript']['text'], 'hello')

    def test_all_five_tokens_and_far_field_do_not_become_service_actions(self):
        frontend = protocol_frontend()
        frontend.current_chunk, frontend.current_ahead = object(), object()
        frontend.model = SimpleNamespace(speech_detected=False,
             config=SimpleNamespace(infer_config=SimpleNamespace(far_field_threshold=.02)),
             get_rms=lambda chunk: .1)
        frontend._spans = lambda array: observation('')['audio_spans']
        control = frontend._event('control_observation', control_revision=1, asr_call_ids=[])
        frontend._commit([control])
        frontend.control = control
        for token, token_id in STATE_IDS.items():
            frontend.raw_prediction = token_id, token
            state = frontend.observe_state(token, '')
            self.assertTrue(state['accepted'])
            self.assertEqual(state['token_id'], token_id)
        frontend.model.get_rms = lambda chunk: 0.
        state = frontend.observe_state('<|user_nonidle|>', '')
        self.assertFalse(state['accepted'])
        self.assertEqual(state['rejection_reason'], 'far_field')
        stored = [e for e in frontend.context.read_frontend_updates('s')['updates'] if e['kind'] == 'user_state']
        self.assertEqual(len(stored), 6)

    def test_stop_deduplicates_one_output_and_ledger_keeps_disjoint_ranges(self):
        frontend = protocol_frontend()
        frontend.current_chunk = frontend.current_ahead = object()
        frontend._spans = lambda array: observation('')['audio_spans']
        frontend.model = SimpleNamespace(speech_detected=True,
             config=SimpleNamespace(infer_config=SimpleNamespace(far_field_threshold=.02)))
        control = frontend._event('control_observation', control_revision=1, asr_call_ids=[])
        frontend._commit([control])
        frontend.control, frontend.raw_prediction = control, (151681, '<|user_nonidle|>')
        frontend.active_output = lambda: {'output_id': 'old', 'phase': 'preparing', 'session_id': 's'}
        stopped = []
        frontend.stop_output = lambda event, output_id: stopped.append(output_id)
        frontend.observe_state('<|user_nonidle|>', 'hello')
        frontend.observe_state('<|user_nonidle|>', 'hello')
        self.assertEqual(stopped, ['old'])
        spans = [{'kind': 'synthetic', 'samples': 10},
                 {'kind': 'real', 'start': 20, 'end': 30, 'samples': 10},
                 {'kind': 'real', 'start': 40, 'end': 50, 'samples': 10}]
        sliced = slice_spans(spans, 5, 25)
        self.assertEqual([s.get('start') for s in sliced], [None, 20, 40])
        self.assertEqual(sum(s['samples'] for s in sliced), 20)


if __name__ == '__main__':
    unittest.main()
