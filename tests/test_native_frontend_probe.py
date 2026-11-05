"""Check real-clock gates, bounded IPC provenance and warmup isolation."""
import base64
import hashlib
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/runtime'))
sys.path.insert(0, str(ROOT / 'scripts/remote'))
sys.path.insert(0, str(ROOT / 'scripts/analysis'))
from dual_audio import DualAudioFrontend, PCMLedger
from independent_x2 import IndependentX2
from native_soulx import NativeSoulX, pcm_digest
from native_frontend_worker import MAX_MESSAGE, RemoteX2, WindowLedger, receive, send
from native_frontend_probe import PREFLIGHT, SingleLane, compare_native, full_warmup, prepare_warmup, quantize, replay, select_samples
from shared_context import SharedContext
from analyze_native_frontend import audit_case, analyze, load_rows
from test_independent_frontend import Clock, FakeEngine
from test_native_soulx import SOURCE, official_model


class ProbeTests(unittest.TestCase):
    def test_formal_suite_requires_verified_gate_and_keeps_all_thirty_cases(self):
        samples = [{'case_id': name} for name in PREFLIGHT + [f'case_{i}' for i in range(27)]]
        manifest = {'samples': samples}
        gate = {'ntf019_candidate_gate': True, 'resource_checks_passed': True,
                'conditions': {'dual-full': {'passed': True, 'cases': [{'case_id': name, 'passed': True} for name in PREFLIGHT]}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gate.json'
            path.write_text(json.dumps(gate))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(select_samples(manifest, 'fdb30', 'dual-full', path, digest), samples)
            with self.assertRaises(ValueError):
                select_samples(manifest, 'fdb30', 'dual-full', path, 'wrong')
            with self.assertRaises(ValueError):
                select_samples(manifest, 'fdb30', 'dual-limited', path, digest)
            gate['ntf019_candidate_gate'] = False
            path.write_text(json.dumps(gate))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                select_samples(manifest, 'fdb30', 'single-full', path, digest)

    def test_compressed_evidence_retains_every_receipt(self):
        frontend, context = self.frontend()
        with tempfile.TemporaryDirectory() as directory, patch('native_frontend_probe.fresh', return_value=(frontend, context)), \
                patch('torch.cuda.synchronize'):
            root = Path(directory)
            result = replay(frontend.controller.model, None, np.full(3000, .1, np.float32), 'case', root, False, compress=True)
            self.assertTrue(result['passed'], result.get('error'))
            self.assertFalse((root / 'case.frames.jsonl').exists())
            rows = load_rows(root, 'case')
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]['snapshot']['text'], 'hello world')
            self.assertEqual(rows[-1]['receipts']['asr']['processed_until'], 3000)

    def test_single_lane_reset_can_produce_more_calls_than_source_batches(self):
        model = official_model([99, 7] * 100)
        with tempfile.TemporaryDirectory() as directory, patch('torch.cuda.synchronize'), \
                patch('native_frontend_probe.NativeSoulX', side_effect=lambda *args, **kwargs:
                      NativeSoulX(*args, source_path=SOURCE, **kwargs)):
            result = replay(model, None, np.full(30000, .1, np.float32), 'single', Path(directory), True)
        self.assertTrue(result['passed'], result.get('error'))
        self.assertGreater(result['frames'], (30000 + 2559) // 2560)
        self.assertTrue(result['diagnostics']['input_eof'])
        self.assertGreaterEqual(result['diagnostics']['unprocessed_real_samples'], 0)

    def test_quiet_warmup_is_normalized_before_quantization_and_silent_input_is_rejected(self):
        audio = (.0005 * np.sin(np.arange(124800) * .1)).astype(np.float32)
        first, evidence = prepare_warmup(audio)
        second, repeated = prepare_warmup(audio)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(evidence, repeated)
        self.assertAlmostEqual(evidence['prepared_rms'], .05, places=4)
        self.assertGreater(evidence['prepared_peak'], .02)
        np.testing.assert_array_equal(first[:124800], quantize(audio * evidence['gain']))
        np.testing.assert_array_equal(first[124800:], np.zeros(25600, np.float32))
        with self.assertRaisesRegex(ValueError, 'silent'):
            prepare_warmup(np.zeros(124800, np.float32))

    def test_warmup_peak_limit_preserves_transient_headroom(self):
        audio = np.zeros(124800, np.float32)
        audio[0] = 1.
        prepared, evidence = prepare_warmup(audio)
        self.assertAlmostEqual(evidence['gain'], .9)
        self.assertLessEqual(float(np.max(np.abs(prepared))), .9)

    def test_offline_audit_accepts_actual_receipts_and_rejects_forged_eos(self):
        frontend, context = self.frontend()
        with tempfile.TemporaryDirectory() as directory, patch('native_frontend_probe.fresh', return_value=(frontend, context)), \
                patch('torch.cuda.synchronize'):
            output = Path(directory)
            result = replay(frontend.controller.model, None, np.full(3000, .1, np.float32),
                            'case', output, False)
            rows = [json.loads(line) for line in (output / 'case.frames.jsonl').read_text().splitlines()]
        # The lightweight engine supplies only its decision; add the real scripted token trace for the audit.
        for row in rows:
            for frame in row['receipts']['asr']['frames']:
                frame['decode']['token_ids'] = [33, 12, 2] if frame['decision'] == 33 else [32]
            row.update(controller_main_lag_ms=2000, asr_main_lag_ms=1900,
                       unread_samples={'controller': 16001, 'asr': 15000})
        self.assertTrue(audit_case(rows, result, True)['passed'])
        pcm_bytes = rows[0]['pcm_bytes']
        rows[0]['pcm_bytes'] = 4 * 2**20 + 1
        self.assertFalse(audit_case(rows, result, True)['passed'])
        rows[0]['pcm_bytes'] = pcm_bytes
        rows[0]['receipts']['asr']['frames'][0]['decode']['token_ids'][-1] = 32
        self.assertFalse(audit_case(rows, result, True)['passed'])

    def test_missing_matrix_cannot_authorize_ntf019(self):
        with tempfile.TemporaryDirectory() as directory:
            result = analyze(Path(directory))
        self.assertFalse(result['ntf019_candidate_gate'])
        self.assertFalse(result['matrix_all_passed'])

    def frontend(self, clock=None, realtime=False):
        import time
        clock = clock or time.monotonic
        model = official_model([99, 6] * 100)
        control = NativeSoulX(model, synchronize=lambda: None, source_path=SOURCE,
                              clock=clock, profile=True, session_id='case', turn_id='input')
        self.addCleanup(lambda: control.detach() if hasattr(model, '_native') else None)
        asr = IndependentX2(FakeEngine([[12, 2]] + [None] * 100), clock=clock,
                            session_id='case', turn_id='input')
        context = SharedContext(clock=clock)
        context.open_user_turn('case', 'input', 'x2_streaming_asr')
        return DualAudioFrontend(control, asr, context=context, clock=clock, realtime=realtime), context

    def test_online_and_warmup_allow_long_backlog_but_keep_pcm_capacity(self):
        for realtime in (True, False):
            with self.subTest(realtime=realtime):
                frontend, _ = self.frontend(Clock(), realtime)
                frontend.started_at = 0
                frontend.append_pcm(np.zeros(16001, np.float32))
                self.assertIsNotNone(frontend.advance())
                self.assertFalse(frontend.closed)
                with self.assertRaises(MemoryError):
                    frontend.append_pcm(np.zeros(2**20, np.float32))

    def test_single_lane_allows_long_backlog_but_keeps_pcm_capacity(self):
        for realtime in (True, False):
            with self.subTest(realtime=realtime):
                control = NativeSoulX(official_model([99, 6] * 100), synchronize=lambda: None,
                                      source_path=SOURCE, clock=Clock(), profile=True)
                self.addCleanup(control.detach)
                frontend = SingleLane(control, realtime)
                frontend.started_at = 0
                frontend.append_pcm(np.zeros(16001, np.float32))
                self.assertIsNotNone(frontend.advance())
                self.assertFalse(frontend.closed)
                with self.assertRaises(MemoryError):
                    frontend.append_pcm(np.zeros(2**20, np.float32))

    def test_warmup_results_stay_in_private_context_and_reset_is_clean(self):
        frontend, context = self.frontend()
        production = SharedContext()
        before = production.open_user_turn('production', 'input', 'x2_streaming_asr')
        with tempfile.TemporaryDirectory() as directory, patch('native_frontend_probe.fresh', return_value=(frontend, context)), \
                patch('torch.cuda.synchronize'):
            record = replay(frontend.controller.model, None, np.full(3000, .1, np.float32),
                            'case', Path(directory), False)
        self.assertTrue(record['passed'], record.get('error'))
        self.assertEqual(record['frames'], 2)
        self.assertEqual(record['online_text'], 'hello world')
        self.assertTrue(record['cleanup']['native_kv_cleared'])
        self.assertTrue(record['cleanup']['callbacks_detached'])
        self.assertEqual(before, production.get_user_turn('production', 'input'))
        self.assertEqual(record['diagnostics']['asr']['open_group_tokens'], [])

    def test_real_clock_replay_preserves_eof_partial_batch(self):
        frontend, context = self.frontend(realtime=True)
        with tempfile.TemporaryDirectory() as directory, patch('native_frontend_probe.fresh', return_value=(frontend, context)), \
                patch('torch.cuda.synchronize'):
            record = replay(frontend.controller.model, None, np.full(3000, .1, np.float32),
                            'case', Path(directory), True)
        self.assertTrue(record['passed'], record.get('error'))
        self.assertGreaterEqual(record['elapsed_seconds'], 3000 / 16000)
        final = record['diagnostics']['last_step']
        self.assertTrue(final['receipts']['asr']['terminal'])
        self.assertEqual(final['receipts']['asr']['processed_until'], 3000)
        self.assertEqual(len(final['receipts']['asr']['frames']), 1)

    def test_late_delivery_and_publication_are_recorded_without_stopping(self):
        import time
        frontend, context = self.frontend(realtime=True)
        append = frontend.append_pcm
        delayed = False

        def slow_first_packet(audio):
            nonlocal delayed
            if not delayed:
                delayed = True
                time.sleep(1.)
            return append(audio)

        frontend.append_pcm = slow_first_packet
        with tempfile.TemporaryDirectory() as directory, patch('native_frontend_probe.fresh', return_value=(frontend, context)), \
                patch('torch.cuda.synchronize'):
            record = replay(frontend.controller.model, None, np.full(3000, .1, np.float32),
                            'case', Path(directory), True)
        self.assertTrue(record['passed'], record.get('error'))
        self.assertEqual(record['frames'], 2)
        self.assertGreater(record['arrival_late_ms']['max'], 800)
        self.assertGreater(record['timing']['controller_main_lag_ms']['max'], 800)
        self.assertEqual(record['diagnostics']['asr']['processed_until'], 3000)

    def test_uncovered_warmup_branch_blocks_acceptance(self):
        empty = {'passed': True, 'coverage': {'sensevoice_text': True}, 'cleanup': {}}
        model = SimpleNamespace(cascade_asr=SimpleNamespace(recognize=lambda *_: 'real text'))
        with tempfile.TemporaryDirectory() as directory, patch('native_frontend_probe.replay', return_value=deepcopy(empty)), \
                patch('native_frontend_probe.compare_native', return_value={'passed': True}), patch('torch.cuda.synchronize'):
            result = full_warmup(model, None, np.full(150400, .1, np.float32), Path(directory))
        self.assertFalse(result['passed'])
        self.assertIn('text_revision', result['missing_by_round'][0])

    def test_real_official_methods_match_after_added_observers(self):
        model = official_model([99, 6] * 100)
        original = model.model.llm

        class LLM:
            forward = staticmethod(original)

            def __call__(self, *args, **kwargs):
                return self.forward(*args, **kwargs)

        model.model.llm = LLM()
        with patch('torch.cuda.synchronize'), patch('native_frontend_probe.NativeSoulX',
                side_effect=lambda *args, **kwargs: NativeSoulX(*args, source_path=SOURCE, **kwargs)):
            result = compare_native(model, np.full(7000, .1, np.float32))
        self.assertTrue(result['passed'])
        self.assertEqual(len(result['reference']['records']), 3)
        self.assertFalse(hasattr(model, '_native'))

    def test_control_comparison_allows_only_complete_service_asr_omission(self):
        model = official_model([99, 5, 99, 3] * 2, ['whole turn'])
        original = model.model.llm

        class LLM:
            forward = staticmethod(original)

            def __call__(self, *args, **kwargs):
                return self.forward(*args, **kwargs)

        model.model.llm = LLM()
        with patch('torch.cuda.synchronize'), patch('native_frontend_probe.NativeSoulX',
                side_effect=lambda *args, **kwargs: NativeSoulX(*args, source_path=SOURCE, **kwargs)):
            result = compare_native(model, np.full(5000, .1, np.float32))
        self.assertTrue(result['passed'])
        self.assertEqual(result['comparison_policy'], 'control_equivalence_skip_complete_asr')
        self.assertEqual(result['authorized_omissions'], 1)
        self.assertEqual(result['reference']['records'][1]['result']['text'], 'whole turn')
        self.assertEqual(result['observed']['records'][1]['result']['text'], '')
        self.assertEqual(len(result['reference']['complete_recognitions']), 1)
        self.assertEqual(result['observed']['complete_recognitions'], [])

    def test_control_comparison_rejects_unexpected_model_input_change(self):
        model = official_model([99, 6] * 100)
        original = model.model.llm

        class LLM:
            forward = staticmethod(original)

            def __call__(self, *args, **kwargs):
                return self.forward(*args, **kwargs)

        model.model.llm = LLM()

        def changed(*args, **kwargs):
            wrapper = NativeSoulX(*args, source_path=SOURCE, **kwargs)
            model.text_embeds = model.text_embeds + 1
            return wrapper

        with patch('torch.cuda.synchronize'), patch('native_frontend_probe.NativeSoulX', side_effect=changed):
            result = compare_native(model, np.full(5000, .1, np.float32))
        self.assertFalse(result['passed'])


class IPCTests(unittest.TestCase):
    def test_message_limit_and_transport_errors_are_explicit(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        stream = child.makefile('rb')
        self.addCleanup(stream.close)
        send(parent, {'ok': True})
        self.assertEqual(receive(stream), {'ok': True})
        with self.assertRaises(ValueError):
            send(parent, {'text': 'a' * MAX_MESSAGE})
        send(parent, {'error': 'worker failed'})
        with self.assertRaisesRegex(RuntimeError, 'worker failed'):
            receive(stream)

    def test_remote_adapter_preserves_exact_pcm_and_closed_group_receipt(self):
        ledger = PCMLedger()
        ledger.append(np.linspace(-.1, .1, 3000, dtype=np.float32))
        engine = IndependentX2(FakeEngine([[12, 2], None]), session_id='session', turn_id='turn')

        class Worker:
            def request(self, operation, **request):
                self.window = WindowLedger(request)
                text, progress = [], []
                engine.on_text, engine.on_progress = text.append, progress.append
                receipt = engine.step(self.window, request['step_id'])
                return json.loads(json.dumps({'receipt': receipt, 'text': text, 'progress': progress,
                                              'diagnostics': engine.diagnostics()}))

        worker, text = Worker(), []
        remote = RemoteX2(worker, 'session', 'turn', {})
        remote.on_text = text.append
        first = remote.step(ledger, 0)
        second = remote.step(ledger, 0)
        self.assertEqual(first['input_sha256'], pcm_digest(ledger.window(-200, 1480)[0]))
        self.assertEqual(text[0]['text'], 'hello world')
        self.assertEqual(second['committed_groups'], 1)
        self.assertEqual(second['decision'], 32)
        self.assertEqual(remote.frame_index, 2)
        with self.assertRaises(ValueError):
            worker.window.window(0, 1680)

    def test_audio_tamper_is_rejected_before_inference(self):
        audio = np.zeros(1680, np.float32)
        request = {'begin': -200, 'end': 1480, 'eof': False,
                   'audio': base64.b64encode(audio.tobytes()).decode(), 'sha256': 'wrong',
                   'spans': [{'kind': 'real', 'start': 0, 'end': 1680, 'samples': 1680}]}
        with self.assertRaisesRegex(ValueError, 'integrity'):
            WindowLedger(request)


if __name__ == '__main__':
    unittest.main()
