"""Verify frozen inputs, paced replay and independently recomputable metrics."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/remote'))
import x2_turn_complete_test as x2


def write_wav(path: Path, frames: int = 1600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x00\x00' * frames)


def sample(split: str, name: str, reference: str, path: Path) -> dict:
    return {
        'sample_id': f'{split}/{name}',
        'split': split,
        'relative_path': str(Path('audio') / split / name),
        'selection_sha256': hashlib.sha256(name.encode()).hexdigest(),
        'sentence_id': '1',
        'gender': 'MALE',
        'reference': reference,
        'dataset_normalized_reference': reference.lower(),
        'normalized_reference': reference.lower(),
        'normalized_reference_words': len(reference.split()),
        'audio_sha256': x2.sha256_file(path),
        'audio_bytes': path.stat().st_size,
        'channels': 1,
        'sample_rate': 16000,
        'frames': 1600,
        'duration_seconds': 0.1,
        'resampled': False,
        'channels_converted': False,
        'trimmed_silence': False,
    }


class FleursDataTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        rows = [['1', f'{index}.wav', 'Hello world', 'hello world', '', '', 'MALE'] for index in range(4)]
        wanted = x2.select_rows(rows, 2)
        manifest_dir = root / 'dataset' / 'fleurs_en_us'
        samples = []
        for split, name, text in (
            ('test', wanted[0][1][1], 'Hello world'),
            ('dev', wanted[1][1][1], 'Hello world'),
        ):
            audio = manifest_dir / 'audio' / split / name
            write_wav(audio)
            samples.append(sample(split, name, text, audio))
        source = manifest_dir / 'source' / 'en_us' / 'test.tsv'
        source.parent.mkdir(parents=True)
        source.write_text('fixture\n')
        totals = {
            'test': {'samples': 1, 'duration_seconds': 0.1, 'normalized_words': 2,
                     'audio_bytes': samples[0]['audio_bytes']},
            'dev': {'samples': 1, 'duration_seconds': 0.1, 'normalized_words': 2,
                    'audio_bytes': samples[1]['audio_bytes']},
        }
        manifest = {
            'repo': x2.FLEURS_REPO,
            'revision': x2.FLEURS_REVISION,
            'totals': totals,
            'samples': samples,
            'source_copies': {'data/en_us/test.tsv': {
                'relative_path': 'source/en_us/test.tsv',
                'sha256': x2.sha256_file(source),
            }},
        }
        path = manifest_dir / 'manifest.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest))
        return path

    def test_selection_uses_ascending_filename_hash(self):
        rows = [['1', name, 'a b', 'a b', '', '', 'MALE']
                for name in ('c.wav', 'a.wav', 'b.wav')]
        selected = x2.select_rows(rows, 2)
        expected = sorted(rows, key=lambda row: hashlib.sha256(row[1].encode()).hexdigest())[:2]
        self.assertEqual([row[1] for _, row in selected], [row[1] for row in expected])
        self.assertEqual([key for key, _ in selected],
                         [hashlib.sha256(row[1].encode()).hexdigest() for row in expected])

    def test_verification_accepts_frozen_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.fixture(Path(tmp))
            result = x2.verify_manifest(
                path,
                expected=x2.Expectations(test_count=1, dev_count=1,
                                        test_duration_seconds=0.1, test_normalized_words=2),
                normalizer=lambda text: text.lower(),
            )
            self.assertEqual((result['test_samples'], result['dev_samples']), (1, 1))

    def test_verification_rejects_modified_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.fixture(Path(tmp))
            write_wav(path.parent / 'audio' / 'test' / sorted(
                item.name for item in (path.parent / 'audio' / 'test').glob('*.wav'))[0], frames=1601)
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                x2.verify_manifest(
                    path,
                    expected=x2.Expectations(test_count=1, dev_count=1,
                                            test_duration_seconds=0.1, test_normalized_words=2),
                    normalizer=lambda text: text.lower(),
                )

    def test_verification_rejects_mixed_split_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.fixture(Path(tmp))
            manifest = json.loads(path.read_text())
            manifest['samples'][1]['sample_id'] = 'test/' + Path(manifest['samples'][1]['relative_path']).name
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'mixes split identity'):
                x2.verify_manifest(
                    path,
                    expected=x2.Expectations(test_count=1, dev_count=1,
                                            test_duration_seconds=0.1, test_normalized_words=2),
                    normalizer=lambda text: text.lower(),
                )




def event(received, kind="turn.delta", **fields):
    payload = {"type": kind, **fields}
    if kind == "turn.delta":
        payload = {"type": kind, "turn_id": 38, "turn_class": "turn_end", **fields}
    return {"received": received, "payload": payload,
            "cumulative_text": fields.get("text", fields.get("delta", ""))}


def trace(events=(), **fields):
    return {"status": "ok", "events": list(events), "t_end": 10., "window_end": 15.,
            "t_eof": 15.1, "window_observed": True, "final_text": "hello world", **fields}


class MetricTests(unittest.TestCase):
    def test_complete_closed_boundaries_and_duplicate_frames(self):
        for received, hit in ((9.999, False), (10., True), (15., True), (15.001, False)):
            result = x2.score_complete(trace([event(received), event(received)]))
            self.assertEqual(result['hit'], hit)
            self.assertEqual(result['latency_ms'], (received - 10) * 1000 if hit else None)
        self.assertEqual(x2.score_complete(trace([event(11), event(12)]))['latency_ms'], 1000)

    def test_complete_early_eof_absent_and_native_validation(self):
        self.assertTrue(x2.score_complete(trace([event(9)]))['only_before'])
        self.assertTrue(x2.score_complete(trace([event(16)]))['only_after_eof'])
        self.assertTrue(x2.score_complete(trace())['never_observed'])
        for payload in ({'turn_id': 37}, {'turn_id': 99}, {'turn_id': '38'}):
            result = x2.score_complete(trace([event(11, **payload)]))
            self.assertFalse(result['hit'])
            self.assertFalse(result['replay_ok'])
            self.assertEqual(len(result['protocol_anomalies']), 1)
        result = x2.score_complete(trace([event(11, 'controller.accept'),
                                          event(11, 'transcription.delta', delta='turn_end')]))
        self.assertFalse(result['hit'])

    def test_partial_failure_retains_hits_without_claiming_full_window(self):
        result = x2.score_complete(trace([event(11)], status='failed', window_observed=False))
        self.assertTrue(result['hit'])
        self.assertFalse(result['replay_ok'])
        self.assertIsNone(result['complete_absent_full_window'])

    def test_hand_counted_edit_operations(self):
        for reference, hypothesis, expected in (
            ('a b c', 'a x c', (1, 0, 0)),
            ('a b c', 'a c', (0, 1, 0)),
            ('a b c', 'a b c d', (0, 0, 1)),
            ('a b c d', 'a x c e f', (2, 0, 1)),
            ('a b', '', (0, 2, 0)),
        ):
            result = x2.word_errors(reference.split(), hypothesis.split())
            self.assertEqual(tuple(result[k] for k in ('S', 'D', 'I')), expected)
            self.assertEqual(result['N_ref'], len(reference.split()))

    def test_online_negative_latency_punctuation_and_eof_text(self):
        events = [event(9, 'transcription.delta', delta='hello world'),
                  event(14, 'transcription.delta', text='hello world!'),
                  event(16, 'transcription.done', text='hello world again')]
        result = x2.score_asr(trace(events, final_text='hello world again'),
                              'hello world', str.lower)
        self.assertEqual(result['text_latency_ms'], -1000)
        self.assertEqual(result['errors']['I'], 1)
        self.assertEqual(result['eof_last_update_ms'], (16 - 15.1) * 1000)
        self.assertEqual(result['online_text'], 'hello world!')
        self.assertTrue(result['eof_text_changed'])

    def test_empty_failure_and_missing_complete_do_not_drop_asr(self):
        result = x2.score_asr(trace(final_text=''), 'hello world', str.lower)
        self.assertEqual(result['errors']['D'], 2)
        self.assertIsNone(result['text_latency_ms'])
        failed = x2.score_asr(trace(status='failed'), 'hello world', str.lower)
        self.assertIsNone(failed['errors'])
        self.assertIsNone(failed['text_latency_ms'])
        result = x2.score_asr(trace([event(9, 'transcription.delta', delta='hello world')]),
                              'hello world', str.lower)
        self.assertEqual(result['errors']['wer'], 0)
        self.assertEqual(result['text_latency_ms'], -1000)

    def test_pinned_normalizer_and_distribution(self):
        normalizer = x2.load_english_normalizer()
        self.assertEqual(normalizer('Hello, WORLD!'), 'hello world')
        self.assertEqual(x2.distribution([])['mean_ms'], None)
        self.assertEqual(x2.distribution([-1000, 1000])['mean_ms'], 0)
        self.assertEqual(x2.distribution([0, 100])['p95_ms'], 95)

    def test_run_summary_preserves_planned_denominators(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {'normalizer': {'package': x2.NORMALIZER_PACKAGE, 'version': x2.NORMALIZER_VERSION},
                        'samples': [{'sample_id': 'test/a', 'split': 'test', 'reference': 'alpha beta'},
                                    {'sample_id': 'test/b', 'split': 'test', 'reference': 'gamma'},
                                    {'sample_id': 'test/c', 'split': 'test', 'reference': 'delta'}]}
            x2.write_json(root / 'manifest.json', manifest)
            x2.write_json(root / 'run.json', {'mode': 'formal',
                          'manifest_sha256': x2.sha256_file(root / 'manifest.json'),
                          'samples': [{'sample_id': 'test/a', 'trace': '000.json'},
                                      {'sample_id': 'test/b', 'trace': '001.json'},
                                      {'sample_id': 'test/c', 'trace': '002.json'}]})
            x2.write_json(root / '000.json', trace(final_text='alpha', sample_id='test/a'))
            x2.write_json(root / '001.json', trace(final_text='gamma', sample_id='test/b'))
            with patch.object(x2, 'EXPECTED_TEST_NORMALIZED_WORDS', 4):
                asr = x2.score_run(root, 'asr')['summary']
            self.assertEqual(asr['planned'], 3)
            self.assertEqual(asr['failed'], 1)
            self.assertEqual(asr['counts']['N_ref'], 3)
            self.assertEqual(asr['corpus_wer'], 1/3)
            complete = x2.score_run(root, 'complete')['summary']
            self.assertEqual(complete['complete_rate'], 0)
            self.assertEqual(complete['failed'], 1)
            self.assertIsNone(complete['latency']['mean_ms'])
            self.assertEqual(complete['incomplete_windows'], 1)


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_websocket_pacing_full_tail_and_eof(self):
        import asyncio
        import base64
        import time
        import websockets

        received = []
        async def server(socket):
            await socket.send(json.dumps({'type': 'session.created'}))
            async for message in socket:
                payload = json.loads(message)
                received.append((time.monotonic(), payload))
                if payload['type'] == 'input_audio_buffer.append':
                    await socket.send(json.dumps({'type': 'transcription.delta', 'delta': 'a'}))
                    await socket.send(json.dumps({'type': 'turn.delta', 'turn_id': 38,
                                                  'turn_class': 'turn_end', 'probs': [.8]}))
                if payload.get('final'):
                    await socket.send(json.dumps({'type': 'transcription.delta', 'delta': ' done'}))
                    await socket.send(json.dumps({'type': 'transcription.done',
                                                  'text': 'a' * 65 + ' done'}))
                    break
        async with websockets.serve(server, '127.0.0.1', 0) as service:
            port = service.sockets[0].getsockname()[1]
            result = await x2.StreamingReplay(f'ws://127.0.0.1:{port}', 'mock').run(b'\x01\0' * 2560)
        self.assertEqual(result['status'], 'ok', result['errors'])
        self.assertEqual(len(result['sends']), 65)
        self.assertEqual(sum(r['frames'] for r in result['sends'] if r['phase'] == 'silence'), 80000)
        self.assertGreaterEqual(result['t_eof'] - result['t_end'], 5.)
        self.assertGreaterEqual(result['t_done'], result['t_eof'])
        self.assertEqual(result['sends'][-1]['frames'], 640)
        self.assertGreaterEqual(result['t_end'] - result['t_start'], .16)
        inputs = [r for r in result['sends'] if r['phase'] == 'input']
        self.assertAlmostEqual(inputs[-1]['deadline'], result['planned_file_end'])
        self.assertTrue(any(e['received'] < result['t_end'] and e['payload']['type'] == 'turn.delta'
                            for e in result['events']))
        appends = [(t, base64.b64decode(p['audio'])) for t, p in received
                   if p['type'] == 'input_audio_buffer.append']
        self.assertGreater(appends[1][0] - appends[0][0], .04)
        self.assertTrue(all(not any(audio) for _, audio in appends[2:]))
        self.assertTrue(x2.score_complete(result)['hit'])
        self.assertTrue(x2.score_asr(result, '', str.lower)['eof_lexical_updates'])

    async def test_run_records_all_failures_and_rejects_reused_id(self):
        from argparse import Namespace
        from unittest.mock import AsyncMock, patch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = FleursDataTests().fixture(root)
            args = Namespace(root=root, mode='dev', run_id='dev-mock', url='ws://mock', model='mock')
            with patch.object(x2, 'verify_manifest'), patch.object(
                    x2.StreamingReplay, 'run', new=AsyncMock(side_effect=ConnectionError('mock offline'))):
                result = await x2.replay_run(args)
                with self.assertRaises(FileExistsError):
                    await x2.replay_run(args)
            output = Path(result['run'])
            plan = json.loads((output / 'run.json').read_text())
            self.assertEqual(plan['mode'], 'dev')
            self.assertEqual(len(plan['samples']), 1)
            self.assertEqual(x2.sha256_file(output / 'manifest.json'), x2.sha256_file(manifest))
            record = json.loads((output / '000.json').read_text())
            self.assertEqual(record['status'], 'failed')
            self.assertEqual(record['errors'][0]['type'], 'ConnectionError')
            self.assertEqual(x2.score_run(output, 'complete')['summary']['formal_samples'], 0)

    async def test_disconnect_error_invalid_json_and_drain_timeout(self):
        import websockets
        from unittest.mock import patch

        for behavior in ('disconnect', 'error', 'json', 'timeout'):
            async def server(socket):
                if behavior == 'disconnect':
                    await socket.close()
                elif behavior == 'error':
                    await socket.send(json.dumps({'type': 'error', 'error': 'mock failure'}))
                    await socket.wait_closed()
                elif behavior == 'json':
                    await socket.send('invalid')
                    await socket.wait_closed()
                else:
                    async for message in socket:
                        if json.loads(message).get('final'):
                            await socket.wait_closed()
            async with websockets.serve(server, '127.0.0.1', 0) as service:
                port = service.sockets[0].getsockname()[1]
                with patch.object(x2, 'WINDOW_SECONDS', .08), patch.object(x2, 'DRAIN_SECONDS', .02):
                    result = await x2.StreamingReplay(f'ws://127.0.0.1:{port}', 'mock').run(b'\0\0' * 1280)
            self.assertEqual(result['status'], 'failed')
            self.assertTrue(result['errors'])
            self.assertEqual(result['window_observed'], behavior == 'timeout')
            if behavior == 'timeout':
                self.assertEqual(result['errors'][0]['type'], 'TimeoutError')


if __name__ == '__main__':
    unittest.main()
