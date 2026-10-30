"""Check native delta drafts, completion refinement, and atomic frame writes."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/runtime'))
from shared_context import SharedContext, STATE_IDS
from sensevoice_transcript import SenseVoiceObservation, TurnTranscriptAssembler
from soulx_frontend import SoulXFrontend, slice_spans


def observation(text, start=0, end=16000):
    return dict(SenseVoiceObservation.parse(text), call_status='ok',
                audio_spans=[{'kind': 'real', 'start': start, 'end': end, 'samples': end-start}])


def protocol_frontend():
    # Use the real capture/publication path without importing a GPU backend.
    value = SoulXFrontend.__new__(SoulXFrontend)
    value.context = SharedContext()
    value.session_id, value.turn_id = 's', 't'
    value.controller_generation = value.call_sequence = value.processed_until = 0
    value.asr_generation, value.clock_id = 'g', 'test'
    value.assembler = TurnTranscriptAssembler()
    value.delivery_phase, value.closed = 'online', False
    value.on_commit = value.audit = value.active_output = value.stop_output = None
    value._calls, value._arrays, value._stopped = [], {}, set()
    value._feeding, value._pending_state, value.control = threading.Lock(), None, None
    value.raw_prediction = None, None
    value._check_pcm_bound = lambda: None
    value.snapshot = value.context.open_user_turn('s', 't')
    value.model = SimpleNamespace(speech_detected=False, get_rms=lambda chunk: .1,
        past_state={'delta_text': [], 'cascade_text': ''},
        config=SimpleNamespace(infer_config=SimpleNamespace(far_field_threshold=.02)))
    return value


def run_frame(value, step, token='<|user_nonidle|>'):
    chunk = value._record_array(np.zeros(2560, dtype=np.float32),
        [{'kind': 'real', 'start': step * 2560, 'end': (step + 1) * 2560, 'samples': 2560}])
    ahead = value._record_array(np.zeros(640, dtype=np.float32),
        [{'kind': 'real', 'start': (step + 1) * 2560, 'end': (step + 1) * 2560 + 640, 'samples': 640}])
    value.raw_prediction = STATE_IDS.get(token), token
    return value._state_predict(chunk, None, ahead)


def native_control(value, history):
    before = list(value.model.past_state['delta_text'])
    value.model.past_state = {'delta_text': list(history), 'cascade_text': 'native window'}
    value.observe_control(history[-1] if history else '', before)


class SoulXFrontendTests(unittest.TestCase):
    def test_labels_and_delta_revisions_then_segment_refinement(self):
        raw = '<|en|><|NEUTRAL|><|Speech|><|withitn|>The. 123. I\'m here.'
        parsed = SenseVoiceObservation.parse(raw)
        self.assertEqual(parsed['text'], "The. 123. I'm here.")
        for span in parsed['character_map']:
            self.assertEqual(parsed['text'][span['text_start']:span['text_end']],
                             raw[span['raw_start']:span['raw_end']])
        assembler = TurnTranscriptAssembler()
        assembler.apply_deltas(['我想去', '北京'], 0)
        update = assembler.apply_deltas(['我想去', '上海', '订票', ''], 0)
        self.assertEqual(update['text'], '我想去上海订票')
        self.assertFalse({'asr_version', 'replacement'} & update.keys())
        assembler.apply_deltas(['我想去', '', '订票', ''], 0)
        self.assertEqual(assembler.text, '我想去订票')
        assembler.apply_turn_result(observation('我想去上海订票。', end=5120), 0)
        self.assertTrue(assembler.coverage_complete)
        assembler.begin_generation(1, 5120)
        assembler.apply_deltas(['Another', 'request', ''], 1)
        self.assertEqual(assembler.text, '我想去上海订票。Another request')
        assembler.apply_turn_result(observation('Another request, corrected.', 5120, 10240), 1)
        self.assertEqual(assembler.text, '我想去上海订票。Another request, corrected.')

    def test_failed_refinement_preserves_draft_and_valid_result_recovers(self):
        assembler = TurnTranscriptAssembler()
        assembler.apply_deltas(['book', 'a flight'], 0)
        self.assertFalse(assembler.apply_turn_result(observation(''), 0)['changed'])
        failed = observation('')
        failed['call_status'] = 'error'
        assembler.apply_turn_result(failed, 0)
        self.assertEqual(assembler.text, 'book a flight')
        self.assertFalse(assembler.coverage_complete)
        discontinuous = observation('must not replace')
        discontinuous['audio_spans'] = [
            {'kind': 'real', 'start': 0, 'end': 1280, 'samples': 1280},
            {'kind': 'real', 'start': 2560, 'end': 5120, 'samples': 2560}]
        assembler.apply_turn_result(discontinuous, 0)
        self.assertEqual(assembler.text, 'book a flight')
        assembler.apply_turn_result(observation('Book a flight.', end=5120), 0)
        self.assertTrue(assembler.coverage_complete)
        assembler.begin_generation(1, 5120)
        assembler.apply_deltas(['next', 'request'], 1)
        assembler.apply_turn_result(observation('wrong segment', 0, 7680), 1)
        self.assertEqual(assembler.text, 'Book a flight. next request')
        assembler.apply_turn_result(observation('Next request.', 5120, 7680), 1)
        self.assertEqual(assembler.text, 'Book a flight. Next request.')
        self.assertTrue(assembler.coverage_complete)
        bounded = TurnTranscriptAssembler(max_chars=5)
        bounded.apply_deltas(['book'], 0)
        with self.assertRaises(RuntimeError):
            bounded.apply_turn_result(observation('Too long.'), 0)
        self.assertEqual(bounded.text, 'book')

    def test_no_early_text_publish_and_corrections_replace_next_joint_frame(self):
        value = protocol_frontend()
        writes = []
        value.on_commit = lambda context: writes.append(context.get_user_turn('s', 't'))
        def predict(chunk, back, ahead):
            value.observe_asr('<|en|>raw window is diagnostic', observation('')['audio_spans'], asr_call_id='a', call_kind='window')
            self.assertEqual(value.assembler.text, '')
            native_control(value, ['book', 'Beijing', 'tomorrow'])
            self.assertEqual(value.context.get_user_turn('s', 't')['text'], '')
            value.observe_state('<|user_nonidle|>', 'book')
        value._instrumented_state = predict
        run_frame(value, 0)
        def revise(chunk, back, ahead):
            native_control(value, ['book', 'Shanghai', ''])
            value.observe_state('<|user_incomplete|>', 'Shanghai')
        value._instrumented_state = revise
        run_frame(value, 1, '<|user_incomplete|>')
        value._instrumented_state = lambda *args: value.observe_state('<|user_idle|>', '')
        run_frame(value, 2, '<|user_idle|>')
        self.assertEqual(len(writes), 3)
        self.assertEqual([(v['text'], v['state_token']) for v in writes],
                         [('book Beijing tomorrow', '<|user_nonidle|>'),
                          ('book Shanghai', '<|user_incomplete|>'), ('book Shanghai', '<|user_idle|>')])
        value.close_turn()
        value.observe_asr('<|en|>late', observation('', end=20000)['audio_spans'], asr_call_id='c')
        self.assertEqual(value.context.get_user_turn('s', 't')['text'], 'book Shanghai')

    def test_complete_branch_final_asr_and_reset_precede_joint_publication(self):
        value = protocol_frontend()
        model = value.model
        model.buffer = value._record_array(np.zeros(640, dtype=np.float32),
            [{'kind': 'real', 'start': 2560, 'end': 3200, 'samples': 640}])
        def reset():
            for name in ('buffer', 'buffer_for_asr', 'cascade_buffer'):
                setattr(model, name, np.zeros(640, dtype=np.float32))
        value._original = {'reset': reset}
        def predict(chunk, back, ahead):
            native_control(value, ['book', 'Beijing'])
            value.observe_state('<|user_complete|>', '')
            value.observe_asr('Book Shanghai.', observation('', end=2560)['audio_spans'], asr_call_id='turn', call_kind='turn')
            value._reset_controller()
        value._instrumented_state = predict
        run_frame(value, 0, '<|user_complete|>')
        current = value.context.get_user_turn('s', 't')
        self.assertEqual((current['text'], current['state_token']), ('Book Shanghai.', '<|user_complete|>'))
        self.assertEqual(current['controller_generation'], 0)
        self.assertEqual(value.controller_generation, 1)
        self.assertEqual(value._spans(model.buffer)[0]['start'], 2560)
        self.assertEqual(value.assembler.text, 'Book Shanghai.')
        def following(chunk, back, ahead):
            native_control(value, ['another', 'request'])
            value.observe_state('<|user_nonidle|>', 'request')
        value._instrumented_state = following
        run_frame(value, 1)
        self.assertEqual(value.context.get_user_turn('s', 't')['text'], 'Book Shanghai. another request')

    def test_float32_recognizer_keeps_raw_window_diagnostic(self):
        value = protocol_frontend()
        value._in_asr = True
        audio = value._record_array(np.zeros(16000, dtype=np.float64), observation('')['audio_spans'])
        seen = []
        def generate(**kwargs):
            seen.append(kwargs['input'].dtype)
            return [{'text': '<|en|>The. 123.'}]
        value.model.cascade_asr = SimpleNamespace(language='en', sensevoice_model=SimpleNamespace(generate=generate),
            clean_sensevoice_text=lambda text: text, rich_transcription_postprocess=lambda text: 'CONTROL')
        self.assertEqual(value._recognize(audio), 'CONTROL')
        self.assertEqual(seen, [np.dtype('float32')])
        self.assertEqual(value.assembler.text, '')
        self.assertEqual(value.context.get_user_turn('s', 't')['text'], '')
        native_control(value, ['CONTROL'])
        value.observe_asr('', observation('', end=17000)['audio_spans'], asr_call_id='empty')
        self.assertEqual(value.assembler.text, 'CONTROL')

    def test_all_states_far_field_drain_and_immediate_stop(self):
        value = protocol_frontend()
        stopped = []
        value.active_output = lambda: {'output_id': 'o', 'session_id': 's', 'phase': 'preparing'}
        value.stop_output = lambda state, output: stopped.append((state['processed_until'], output))
        for step, token in enumerate(STATE_IDS):
            value._instrumented_state = lambda *args, token=token: value.observe_state(token, '')
            run_frame(value, step, token)
            self.assertTrue(value.context.get_user_turn('s', 't')['state_accepted'])
        self.assertEqual(len(stopped), 1)
        value.model.get_rms = lambda chunk: 0.
        value._instrumented_state = lambda *args: value.observe_state('<|user_nonidle|>', '')
        run_frame(value, 5)
        self.assertFalse(value.context.get_user_turn('s', 't')['state_accepted'])
        previous = value.context.get_user_turn('s', 't')
        value.delivery_phase = 'drain'
        run_frame(value, 6)
        self.assertEqual(value.context.get_user_turn('s', 't'), previous)
        self.assertEqual(len(stopped), 1)
        value._feeding.acquire()
        with self.assertRaises(RuntimeError):
            value.close_turn()
        value._feeding.release()
        spans = [{'kind': 'synthetic', 'samples': 10},
                 {'kind': 'real', 'start': 20, 'end': 30, 'samples': 10}]
        self.assertEqual(sum(v['samples'] for v in slice_spans(spans, 5, 15)), 10)


if __name__ == '__main__':
    unittest.main()
