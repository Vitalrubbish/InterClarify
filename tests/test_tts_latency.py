"""Check batching, cancellation, history masks and measurement denominators."""
import asyncio
import importlib.util
import json
import os
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/remote'))
import moss_tts_service_patch as service
import tts_latency_benchmark as benchmark
import tts_latency_trace as trace
import moss_tts_patch as inference

try:
    import torch
except ImportError:
    torch = None


class FakeSession:
    """Expose the same token advancement contract as the pinned session."""

    def __init__(self, tokens, threshold=3, ended=False, eos=1000):
        self._pending_tokens = list(tokens)
        self._prefilled = False
        self._text_ended = ended
        self.prefill_text_len = threshold
        self.temperature, self.top_p, self.top_k = .8, .6, 30
        self.do_sample, self.repetition_penalty, self.repetition_window = True, 1.1, 50
        self.inferencer = self
        self.is_finished = False
        self.generated = []
        self.eos = eos

    def _prefill_if_needed(self):
        if self._prefilled or (len(self._pending_tokens) < self.prefill_text_len and not self._text_ended):
            return []
        n = len(self._pending_tokens) if self._text_ended else self.prefill_text_len
        if not n:
            return []
        prefix, self._pending_tokens = self._pending_tokens[:n], self._pending_tokens[n:]
        self._prefilled = True
        self.generated.append(tuple(prefix))
        return [tuple(prefix)]

    def step(self, token, **kwargs):
        self.generated.append(token)
        self.is_finished = token == self.eos
        return token


class BatchTests(unittest.TestCase):
    def test_first_batch_is_bounded_and_remainder_drains(self):
        for limit in (2, 4, 6):
            session = FakeSession(range(20))
            frames = service.bounded_pending(session, limit, lambda: False)
            self.assertEqual(next(frames), (0, 1, 2))
            self.assertEqual(len(session.generated), limit)
            actual = [(0, 1, 2)] + list(frames)
            self.assertEqual(actual, [(0, 1, 2)] + list(range(3, 20)))
            self.assertEqual(session._pending_tokens, [])

    def test_cancel_before_first_batch_and_before_delivery(self):
        session = FakeSession(range(10))
        self.assertEqual(list(service.bounded_pending(session, 4, lambda: True)), [])
        self.assertEqual(session.generated, [])
        cancelled = [False]
        original = session.step
        def step(token, **kwargs):
            result = original(token, **kwargs)
            cancelled[0] = True
            return result
        session.step = step
        self.assertEqual(list(service.bounded_pending(session, 4, lambda: cancelled[0])), [])

    def test_cancel_between_frames_discards_generated_remainder(self):
        session = FakeSession(range(10))
        cancelled = [False]
        frames = service.bounded_pending(session, 4, lambda: cancelled[0])
        next(frames)
        cancelled[0] = True
        self.assertEqual(list(frames), [])
        self.assertEqual(len(session.generated), 4)

    def test_eos_and_short_final_prefill(self):
        session = FakeSession(range(10), eos=4)
        self.assertEqual(list(service.bounded_pending(session, 4, lambda: False)), [(0, 1, 2), 3, 4])
        short = FakeSession([7], ended=True)
        self.assertEqual(list(service.bounded_pending(short, 4, lambda: False)), [(7,)])
        waiting = FakeSession([7])
        self.assertEqual(list(service.bounded_pending(waiting, 4, lambda: False)), [])
        waiting._pending_tokens.extend([8, 9, 10])
        self.assertEqual(list(service.bounded_pending(waiting, 4, lambda: False)), [(7, 8, 9), 10])

    def test_configuration_rejects_invalid_limit(self):
        with patch.dict(os.environ, {'XTALK_TTS_GENERATION_BATCH_FRAMES': '1'}):
            with self.assertRaises(ValueError):
                service.generation_batch_frames()


class SparsePrefillTests(unittest.TestCase):
    """Partial startup must neither terminate text nor reorder later tokens."""

    def make_runtime(self, tokens):
        session = FakeSession(tokens, threshold=12)
        session._drain_pending_tokens = lambda: list(service.bounded_pending(session, 4, lambda: False))
        return types.SimpleNamespace(tts_session=session,
            _xt_cancelled=threading.Event(), _xt_prefill_deadline=None,
            frame_decoder=types.SimpleNamespace(decode_frames=lambda frames: frames))

    def test_prefill_options_reject_invalid_values(self):
        for tokens, wait in [('3', '0'), ('4', '-1'), ('0', '60001')]:
            with patch.dict(os.environ, {'XTALK_TTS_PREFILL_TEXT_TOKENS': tokens,
                                         'XTALK_TTS_PREFILL_MAX_WAIT_MS': wait}):
                with self.assertRaises(ValueError):
                    service.prefill_options()

    def test_deadline_is_not_extended_and_clears_after_prefill(self):
        sess = self.make_runtime([1, 2])
        with patch.object(service.time, 'monotonic', return_value=10.):
            service.update_prefill_deadline(sess, 200)
        self.assertAlmostEqual(sess._xt_prefill_deadline, 10.2)
        sess.tts_session._pending_tokens.append(3)
        with patch.object(service.time, 'monotonic', return_value=10.1):
            service.update_prefill_deadline(sess, 200)
        self.assertAlmostEqual(sess._xt_prefill_deadline, 10.2)
        sess.tts_session._prefilled = True
        service.update_prefill_deadline(sess, 200)
        self.assertIsNone(sess._xt_prefill_deadline)

    def test_timeout_uses_existing_queue_with_real_command_priority(self):
        sess = self.make_runtime([1])
        sess._xt_prefill_deadline = time.monotonic() - 1
        queue = service.ObservedQueue('fixture')
        queue.session = sess
        queue.put({'type': 'finish_turn'})
        self.assertEqual(queue.get()['type'], 'finish_turn')
        internal = queue.get()
        self.assertTrue(internal['_xt_partial_prefill'])
        self.assertEqual(internal['text'], '')
        self.assertIn('_xt_command_id', internal)

    def test_partial_start_keeps_stream_open_and_continues_in_order(self):
        sess = self.make_runtime([1, 2])
        received = []
        manager = types.SimpleNamespace(_emit_audio_chunks=lambda sess, frames: received.extend(frames))
        service.partial_prefill(manager, sess)
        self.assertEqual(received, [(1, 2)])
        self.assertFalse(sess.tts_session._text_ended)
        self.assertEqual(sess.tts_session.prefill_text_len, 12)
        sess.tts_session._pending_tokens.extend([3, 4])
        self.assertEqual(list(service.bounded_pending(sess.tts_session, 4, lambda: False)), [3, 4])
        self.assertEqual(sess.tts_session.generated, [(1, 2), 3, 4])

    def test_cancel_and_exception_do_not_leave_lowered_threshold(self):
        sess = self.make_runtime([1, 2])
        manager = types.SimpleNamespace(_emit_audio_chunks=lambda *args: self.fail('cancel must not emit'))
        sess._xt_cancelled.set()
        service.partial_prefill(manager, sess)
        self.assertFalse(sess.tts_session._prefilled)
        sess._xt_cancelled.clear()
        sess.tts_session._drain_pending_tokens = lambda: (_ for _ in ()).throw(RuntimeError('fixture'))
        with self.assertRaises(RuntimeError):
            service.partial_prefill(manager, sess)
        self.assertEqual(sess.tts_session.prefill_text_len, 12)

    def test_sparse_schedule_preserves_text_and_real_final_delay(self):
        item = {'text': 'Would you like tea or coffee?', 'deltas': []}
        schedule, end = benchmark.text_schedule(item, 'sparse')
        self.assertEqual(''.join(x['text'] for x in schedule), item['text'])
        self.assertEqual([x['at_ms'] for x in schedule], [0, 600, 1200])
        self.assertEqual(end, 1800)
        with self.assertRaises(ValueError):
            benchmark.text_schedule({**item, 'end_at_ms': 100}, 'sparse')


class ServicePatchTests(unittest.TestCase):
    """Check the explicit adapter patch and its last PCM commit boundary."""

    def test_start_binding_and_cancel_during_buffer_wait(self):
        import numpy as np

        class Decoder:
            def _decode(self, tokens):
                return tokens

        class VoiceDemo:
            def _encode_audio_tokens(self, *args, **kwargs):
                return None

        class Model:
            def prefill(self, *args, **kwargs):
                return None
            def step(self, *args, **kwargs):
                return None

        class Manager:
            def _start_worker(self, sess):
                pass
            def _session_worker(self, sess):
                pass
            def get(self, sid):
                return self.sess
            def delete(self, sid):
                return None
            def _handle_start_turn(self, sess, cmd):
                sess.tts_session = module.MossTTSRealtimeStreamingSession(range(10))
                sess.frames = list(sess.tts_session._drain_pending_tokens())
            def _handle_push_text(self, sess, cmd):
                pass
            def _handle_finish_turn(self, sess):
                pass

        module = types.SimpleNamespace(SessionManager=Manager,
            MossTTSRealtimeStreamingSession=FakeSession, AudioStreamDecoder=Decoder,
            MossTTSRealtimeInference=Model, StreamingTTSDemo=VoiceDemo,
            np=np, SAMPLE_RATE=24000, TARGET_SR=24000,
            resample_if_needed=lambda x, *args: x,
            float32_to_pcm16_bytes=lambda x: bytes(len(x) * 2))
        with patch.dict(os.environ, {'XTALK_TTS_GENERATION_BATCH_FRAMES': '4', 'XTALK_TTS_SEED': ''}), \
                patch('importlib.metadata.version', return_value='fixture'):
            service.apply_service_patch(module)
        manager = Manager()
        sess = types.SimpleNamespace(session_id='fixture', audio_queue=service.queue.Queue(), codec_stream_cm=None,
            buffer_tracker=types.SimpleNamespace(add_chunk=lambda chunk: None),
            streaming=types.SimpleNamespace(buffer_threshold_seconds=0))
        manager.sess = sess
        manager._start_worker(sess)
        manager._handle_start_turn(sess, {})
        self.assertEqual(sess.frames, [(0, 1, 2)] + list(range(3, 10)))
        module._maybe_wait_for_buffer = lambda *args: manager.delete(sess.session_id)
        manager._emit_audio_chunks(sess, iter([np.ones(240)]))
        self.assertTrue(sess.audio_queue.empty())
        self.assertTrue(sess._xt_cancelled.is_set())
        self.assertEqual(list(sess.tts_session._drain_pending_tokens()), [])
        closed = []
        sess.codec_stream_cm = types.SimpleNamespace(__exit__=lambda *args: closed.append(True))
        manager._session_worker(sess)
        self.assertEqual(closed, [True])
        self.assertIsNone(sess.codec_stream_cm)


@unittest.skipIf(torch is None, 'CPU torch required for numerical comparison')
class MaskTests(unittest.TestCase):
    def test_codec_loading_restores_inference_threads_on_success_and_error(self):
        before = torch.get_num_threads()
        observed = []
        def loader():
            observed.append(torch.get_num_threads())
            return 'codec'
        with patch.dict(os.environ, {'XTALK_TTS_CODEC_LOAD_THREADS': '1'}):
            self.assertEqual(service.load_codec(loader), 'codec')
            self.assertEqual(observed, [1])
            self.assertEqual(torch.get_num_threads(), before)
            def failed_loader():
                self.assertEqual(torch.get_num_threads(), 1)
                raise RuntimeError('fixture')
            with self.assertRaises(RuntimeError):
                service.load_codec(failed_loader)
            self.assertEqual(torch.get_num_threads(), before)

    def test_mask_matches_valid_slice_including_zero_and_negative_logits(self):
        torch.manual_seed(17)
        history = torch.randint(0, 7, (1, 128, 2))
        history[:, :-50] = 0
        logits = torch.tensor([[-3., 2., -1., 4., .5, -6., 7.]])
        for filled in (0, 1, 12, 49, 50, 51, 128):
            for window in (0, 3, 50):
                for penalty in (.8, 1., 1.1):
                    count = min(filled, window) if window > 0 else filled
                    expected = logits.clone()
                    if count:
                        codes = history[:, -count:, 0]
                        current = logits.gather(1, codes)
                        expected.scatter_(1, codes, torch.where(current < 0, current * penalty, current / penalty))
                    actual = inference._apply_history_penalty(logits, history, torch.tensor(filled), 0, penalty, window)
                    self.assertTrue(torch.equal(actual, expected), (filled, window, penalty))

    def test_valid_lengths_share_one_compiled_graph(self):
        compiled_graphs = []
        def backend(graph, inputs):
            compiled_graphs.append(graph)
            return graph.forward
        fn = torch.compile(inference._apply_history_penalty, backend=backend, fullgraph=True)
        logits = torch.randn(1, 7)
        history = torch.zeros(1, 128, 2, dtype=torch.long)
        for n in (0, 1, 49, 50, 128, 0):
            fn(logits, history, torch.tensor(n), 0, 1.1, 50)
        self.assertEqual(len(compiled_graphs), 1)


class MeasurementTests(unittest.TestCase):
    def test_queue_correlates_and_scope_does_not_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.jsonl'
            with patch.dict(os.environ, {'XTALK_TTS_TRACE': str(path)}):
                queue = service.ObservedQueue('response-A')
                queue.put({'type': 'push_text'})
                self.assertEqual(queue.get()['type'], 'push_text')
                trace.emit('outside')
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r['response_id'] for r in rows[:2]], ['response-A'] * 2)
            self.assertNotIn('response_id', rows[-1])

    def test_waveform_onset_and_underrun(self):
        pcm = struct.pack('<' + 'h' * 480, *([0] * 240 + [5000] * 240))
        self.assertEqual(benchmark.pcm_onset(pcm, 24000), 240)
        self.assertIsNone(benchmark.pcm_onset(bytes(480), 24000))
        buffer = benchmark.PlaybackEstimate()
        buffer.push(.2, .1)
        buffer.push(.25, .1)
        buffer.push(.5, .1)
        self.assertEqual(buffer.underruns, 1)
        self.assertAlmostEqual(buffer.underrun_seconds, .1)

    def test_summary_separates_modes_and_failure_denominators(self):
        base = {'mode': 'whole', 'error': None, 'samples': 240,
                'onset_seconds': 0., 'first_pcm_seconds': .2, 'audible_estimate_seconds': .2,
                'audio_per_wall': 2., 'simulated_underruns': 0, 'first_packet_samples': 240}
        rows = [base, {**base, 'error': 'timeout', 'samples': 0, 'onset_seconds': None},
                {**base, 'mode': 'incremental', 'first_pcm_seconds': .8}]
        result = benchmark.summarize(rows)
        self.assertEqual(result['whole']['attempts'], 2)
        self.assertEqual(result['whole']['failure_ratio'], .5)
        self.assertEqual(result['whole']['first_pcm_seconds']['n'], 1)
        self.assertEqual(result['incremental']['first_pcm_seconds']['mean'], .8)

    def test_first_pcm_partition_does_not_double_count_nested_spans(self):
        events = [{'response_id': 'a', 'clock_domain': 'p1', 'monotonic_ns': t * 1000000,
                   'event': event, 'samples': 20}
                  for t, event in [(0, 'queue.put'), (10, 'model.prefill.start'),
                                   (20, 'codec.decode.start'), (30, 'codec.decode.end'),
                                   (40, 'model.prefill.end'), (50, 'pcm.enqueued')]]
        row = benchmark.first_pcm_stages(events)[0]
        self.assertAlmostEqual(sum(row['seconds'].values()), .05)
        self.assertAlmostEqual(row['seconds']['overlapping_spans'], .01)
        self.assertAlmostEqual(sum(row['fractions'].values()), 1.)

    def test_formal_trace_excludes_warmup_responses(self):
        events = [{'response_id': response, 'clock_domain': 'p',
                   'event': event, 'monotonic_ns': stamp}
                  for response, end in [('cold', 10000000000), ('formal', 200000000)]
                  for event, stamp in [('model.prefill.start', 0), ('model.prefill.end', end)]]
        result = benchmark.analyze_server_trace(events, response_ids={'formal'})
        self.assertEqual(result['cpu_span_seconds']['model.prefill']['n'], 1)
        self.assertAlmostEqual(result['cpu_span_seconds']['model.prefill']['mean'], .2)

    def test_corpus_and_cross_process_spans(self):
        rows = benchmark.corpus()
        self.assertGreaterEqual(sum(r['category'] == 'short' for r in rows), 30)
        for row in rows:
            self.assertEqual(''.join(d['text'] for d in row['deltas']), row['text'])
        events = [{'event': 'model.prefill.start', 'response_id': 'a', 'clock_domain': 'p1', 'monotonic_ns': 10},
                  {'event': 'model.prefill.end', 'response_id': 'a', 'clock_domain': 'p2', 'monotonic_ns': 20}]
        report = benchmark.analyze_server_trace(events)
        self.assertEqual(report['cpu_span_seconds'], {})
        self.assertEqual(report['unclosed_spans'], 1)
        self.assertIn('physical_playback', report['missing_events'])


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the complete sender/receiver without weights or a cluster."""

    async def test_fixed_deltas_and_completion_save_artifacts(self):
        import websockets
        received = []

        async def handler(ws):
            start = json.loads(await ws.recv())
            self.assertEqual(start['prompt_audio'], '/fixed/reference.wav')
            self.assertTrue(start['session_id'])
            await ws.send(json.dumps({'type': 'started', 'sample_rate': 24000}))
            async for message in ws:
                event = json.loads(message)
                received.append(event['text'])
                if event['is_final']:
                    await ws.send(struct.pack('<240h', *([5000] * 240)))
                    await ws.send(json.dumps({'type': 'completed'}))
                    return

        async with websockets.serve(handler, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            args = types.SimpleNamespace(url=f'ws://127.0.0.1:{port}', reference='/fixed/reference.wav', timeout=2.)
            item = {'id': 'fixture', 'text': 'Yes, please.',
                    'deltas': [{'at_ms': 0, 'text': 'Yes, '}, {'at_ms': 1, 'text': 'please.'}]}
            with tempfile.TemporaryDirectory() as directory:
                row = await benchmark.run_case(args, item, 'incremental', 0, Path(directory))
                self.assertIsNone(row['error'])
                self.assertEqual(row['samples'], 240)
                self.assertIsNotNone(row['audible_estimate_seconds'])
                self.assertEqual(received, ['Yes, ', 'please.', ''])
                self.assertTrue((Path(directory) / 'fixture_incremental_0.wav').is_file())

    async def test_timeout_keeps_failure_and_empty_wave(self):
        import websockets

        async def handler(ws):
            await ws.recv()
            await ws.send(json.dumps({'type': 'started', 'sample_rate': 24000}))
            async for message in ws:
                if json.loads(message)['is_final']:
                    await ws.wait_closed()
                    return

        async with websockets.serve(handler, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            args = types.SimpleNamespace(url=f'ws://127.0.0.1:{port}', reference='/fixed/reference.wav', timeout=.05)
            item = {'id': 'timeout', 'text': 'Yes.', 'deltas': []}
            with tempfile.TemporaryDirectory() as directory:
                row = await benchmark.run_case(args, item, 'whole', 0, Path(directory))
                self.assertIn('TimeoutError', row['error'])
                self.assertEqual(row['samples'], 0)
                self.assertIsNone(row['first_pcm_seconds'])


if __name__ == '__main__':
    unittest.main()
