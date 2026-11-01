"""Check source preservation and one text/state overwrite per audio step."""
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
        config=SimpleNamespace(infer_config=SimpleNamespace(far_field_threshold=.02)))
    return value


def run_frame(value, step, token='<|user_nonidle|>'):
    chunk = value._record_array(np.zeros(2560, dtype=np.float32),
        [{'kind': 'real', 'start': step * 2560, 'end': (step + 1) * 2560, 'samples': 2560}])
    ahead = value._record_array(np.zeros(640, dtype=np.float32),
        [{'kind': 'real', 'start': (step + 1) * 2560, 'end': (step + 1) * 2560 + 640, 'samples': 640}])
    value.raw_prediction = STATE_IDS.get(token), token
    return value._state_predict(chunk, None, ahead)


class SoulXFrontendTests(unittest.TestCase):
    def test_labels_digits_and_window_corrections_remain_source_text(self):
        raw = '<|en|><|NEUTRAL|><|Speech|><|withitn|>The. 123. I\'m here.'
        parsed = SenseVoiceObservation.parse(raw)
        self.assertEqual(parsed['text'], "The. 123. I'm here.")
        for span in parsed['character_map']:
            self.assertEqual(parsed['text'][span['text_start']:span['text_end']],
                             raw[span['raw_start']:span['raw_end']])
        assembler = TurnTranscriptAssembler()
        assembler.apply_window(observation('I want to book a flight to Paris', end=32000))
        update = assembler.apply_window(observation('book a flight to London', 16000, 48000))
        self.assertEqual(update['text'], 'I want to book a flight to London')
        self.assertFalse({'asr_version', 'replacement'} & update.keys())
        self.assertEqual(assembler.apply_window(observation('yes yes', 32000, 64000))['assembly_status'], 'gap')
        self.assertEqual(assembler.text, 'I want to book a flight to London')
        assembler.apply_window(observation('Corrected full turn.', 0, 64000))
        self.assertTrue(assembler.coverage_complete)
        assembler.apply_window(observation('New segment.', 64000, 80000))
        self.assertEqual(assembler.text, 'Corrected full turn. New segment.')
        partial = TurnTranscriptAssembler()
        partial.apply_window(observation('inter', end=16000))
        self.assertEqual(partial.apply_window(observation('net', 16000, 32000))['assembly_status'], 'gap')

    def test_no_early_text_publish_and_corrections_replace_next_joint_frame(self):
        value = protocol_frontend()
        writes = []
        value.on_commit = lambda context: writes.append(context.get_user_turn('s', 't'))
        def predict(chunk, back, ahead):
            value.observe_asr('<|en|>book Beijing tomorrow', observation('')['audio_spans'], asr_call_id='a')
            self.assertEqual(value.context.get_user_turn('s', 't')['text'], '')
            value.observe_state('<|user_nonidle|>', 'book')
        value._instrumented_state = predict
        run_frame(value, 0)
        def revise(chunk, back, ahead):
            value.observe_asr('<|en|>book Shanghai', observation('', end=17000)['audio_spans'], asr_call_id='b')
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
            value.observe_asr('book Beijing', observation('')['audio_spans'], asr_call_id='window')
            value.observe_state('<|user_complete|>', '')
            value.observe_asr('book Shanghai', observation('', end=17000)['audio_spans'], asr_call_id='turn', call_kind='turn')
            value._reset_controller()
        value._instrumented_state = predict
        run_frame(value, 0, '<|user_complete|>')
        current = value.context.get_user_turn('s', 't')
        self.assertEqual((current['text'], current['state_token']), ('book Shanghai', '<|user_complete|>'))
        self.assertEqual(current['controller_generation'], 0)
        self.assertEqual(value.controller_generation, 1)
        self.assertEqual(value._spans(model.buffer)[0]['start'], 2560)
        self.assertEqual(value.assembler.text, 'book Shanghai')

    def test_float32_recognizer_returns_native_control_text_but_stages_raw_text(self):
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
        self.assertEqual(value.assembler.text, 'The. 123.')
        self.assertEqual(value.context.get_user_turn('s', 't')['text'], '')
        value.observe_asr('', observation('', end=17000)['audio_spans'], asr_call_id='empty')
        self.assertEqual(value.assembler.text, 'The. 123.')

    def test_wait_fallback_is_visible_without_rewriting_native_state_or_text(self):
        value = protocol_frontend()
        value.observe_asr('<|en|>Nemotron body', observation('', end=2560)['audio_spans'], asr_call_id='a')
        calls = {'count': 0}
        def predict(chunk, back, ahead):
            calls['count'] += 1
            if calls['count'] == 1:
                value.observe_state('<|user_incomplete|>', 'body')
                return {'state': 'idle'}
            value.observe_state('<|user_idle|>', '')
            if calls['count'] <= 8:
                return {'state': 'idle'}
            return {'state': 'speak', 'text': 'official whole-turn text'}
        value._instrumented_state = predict
        for step in range(9):
            token = '<|user_incomplete|>' if step == 0 else '<|user_idle|>'
            run_frame(value, step, token)
            current = value.context.get_user_turn('s', 't')
            if step < 8:
                self.assertIsNone(current['service_completion_source'])
                self.assertEqual(current['service_state'], 'idle')
        final = value.context.get_user_turn('s', 't')
        self.assertEqual(final['service_state'], 'speak')
        self.assertEqual(final['service_completion_source'], 'wait_fallback')
        self.assertEqual(final['state_token'], '<|user_idle|>')
        self.assertTrue(final['state_accepted'])
        self.assertEqual(final['text'], 'Nemotron body')
        self.assertEqual(final['service_text'], 'official whole-turn text')
        self.assertFalse(final['speech_detected'])

    def test_direct_complete_requires_speech_and_reports_model_completion(self):
        value = protocol_frontend()
        value.model.speech_detected = True
        def predict(chunk, back, ahead):
            value.observe_state('<|user_complete|>', '')
            return {'state': 'speak', 'text': 'official whole-turn text'}
        value._instrumented_state = predict
        run_frame(value, 0, '<|user_complete|>')
        current = value.context.get_user_turn('s', 't')
        self.assertTrue(current['state_accepted'])
        self.assertEqual(current['service_completion_source'], 'model_complete')
        self.assertEqual(current['service_text'], 'official whole-turn text')
        self.assertEqual(current['text'], '')

    def test_complete_without_speech_is_rejected_for_every_service_result(self):
        for result in ({'state': 'idle'}, {'state': 'speak', 'text': 'ignored'}):
            with self.subTest(result=result):
                value = protocol_frontend()
                value.model.speech_detected = False
                def predict(chunk, back, ahead, result=result):
                    value.observe_state('<|user_complete|>', '')
                    return result
                value._instrumented_state = predict
                run_frame(value, 0, '<|user_complete|>')
                current = value.context.get_user_turn('s', 't')
                self.assertFalse(current['state_accepted'])
                self.assertEqual(current['rejection_reason'], 'no_speech')
                self.assertIsNone(current['service_completion_source'])
                self.assertFalse(current['speech_detected'])

    def test_frozen_run_config_matches_official_overrides(self):
        import yaml
        path = (Path(__file__).parents[1] / 'reports/soulx/20261029-frontend-deployment'
                / 'evidence/soulx/soulx_config.yaml')
        infer = yaml.safe_load(path.read_text())['infer_config']
        self.assertEqual((infer['max_wait_num'], infer['max_mistake_num'],
                          infer['far_field_threshold']), (8, 3, .02))

    def test_all_states_far_field_drain_and_immediate_stop(self):
        value = protocol_frontend()
        stopped = []
        value.active_output = lambda: {'output_id': 'o', 'session_id': 's', 'phase': 'preparing'}
        value.stop_output = lambda state, output: stopped.append((state['processed_until'], output))
        for step, token in enumerate(STATE_IDS):
            if token == '<|user_complete|>':
                value.model.speech_detected = True
            value._instrumented_state = lambda *args, token=token: value.observe_state(token, '')
            run_frame(value, step, token)
            self.assertTrue(value.context.get_user_turn('s', 't')['state_accepted'])
        self.assertEqual(len(stopped), 1)
        value.model.speech_detected = False
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
