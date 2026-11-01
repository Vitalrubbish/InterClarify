"""Check EOS-only commits, frame coverage, and strict feasibility gates."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

PATH = Path(__file__).resolve().parents[1] / 'scripts/remote/x2_streaming_probe.py'
SPEC = importlib.util.spec_from_file_location('x2_streaming_probe', PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def groups(self):
        return probe.ClosedGroups(lambda ids: ''.join({10: 'hello', 11: 'world'}[i] for i in ids),
                                  lambda parts: ' '.join(p for p in parts if p))

    def test_unclosed_group_never_commits(self):
        groups = self.groups()
        with self.assertRaises(ValueError):
            groups.append([10])
        self.assertEqual(groups.text, '')
        self.assertEqual(groups.ids, [])

    def test_wait_and_word_do_not_close_groups(self):
        for ids in ([10, 32], [10, 33], [32, 2], [33, 2]):
            with self.assertRaises(ValueError):
                self.groups().append(ids)

    def test_closed_groups_are_immutable(self):
        groups = self.groups()
        self.assertEqual(groups.append([10, 2]), 'hello')
        old_ids = list(groups.ids)
        self.assertEqual(groups.append([11, 2]), ' world')
        self.assertEqual(groups.ids[:len(old_ids)], old_ids)
        self.assertEqual(groups.text, 'hello world')
        self.assertEqual(groups.rewrites, [])

    def test_redecode_detects_rewritten_history(self):
        groups = self.groups()
        groups.append([10, 2])
        groups.decode = lambda ids: 'changed'
        groups.append([11, 2])
        self.assertEqual(len(groups.rewrites), 1)

    def test_decode_generates_many_tokens_in_one_audio_frame(self):
        generated, seen = iter([11, 2]), []
        ids, delay = probe.decode_emit(10, lambda _: next(generated),
                                       lambda token, phase: seen.append((token, phase)), 64)
        self.assertEqual(ids, [10, 11, 2])
        self.assertEqual(seen, [(10, 'decode'), (11, 'decode'), (2, 'decode')])
        self.assertGreaterEqual(delay, 0)

    def test_decode_cap_does_not_synthesize_eos(self):
        with self.assertRaises(RuntimeError):
            probe.decode_emit(10, lambda _: 10, lambda *_: None, 2)

    def test_real_observation_excludes_eof_padding(self):
        self.assertEqual(probe.frame_window(0, 3000), (1280, 1480, 0))
        self.assertEqual(probe.frame_window(1, 3000), (2560, 2760, 0))
        self.assertEqual(probe.frame_window(2, 3000), (3000, 3000, 1040))

    def test_encoder_wrapper_owns_padding_flag_and_retains_caches(self):
        class Features:
            shape = (1, 128, 8)

            def to(self, *args, **kwargs):
                return self

        def cache():
            return SimpleNamespace(layers={
                'conv1': SimpleNamespace(cache=SimpleNamespace(shape=(1, 128, 2))),
                'conv2': SimpleNamespace(cache=SimpleNamespace(shape=(1, 1280, 1)))})

        calls, next_padding, next_past = [], cache(), object()

        def tower(*, input_features, padding_cache, past_key_values, use_padding_cache):
            self.assertTrue(use_padding_cache)
            calls.append((padding_cache, past_key_values))
            return SimpleNamespace(padding_cache=next_padding, past_key_values=next_past,
                                   pooler_output=SimpleNamespace(shape=(1, 1, 3072)))

        def get_audio_features(*, input_features, padding_cache, past_key_values, use_cache, **kwargs):
            return tower(input_features=input_features, padding_cache=padding_cache,
                         past_key_values=past_key_values, use_padding_cache=use_cache, **kwargs)

        engine = probe.X2Engine.__new__(probe.X2Engine)
        initial_padding = cache()
        engine.padding, engine.audio_past = initial_padding, None
        engine.config = {'next_mel_frames': 8}
        engine.processor = lambda *args, **kwargs: SimpleNamespace(input_features=Features())
        embedder = SimpleNamespace(conv1=SimpleNamespace(in_channels=128, left_pad=2),
                                   conv2=SimpleNamespace(in_channels=1280, left_pad=1))
        engine.model = SimpleNamespace(dtype='bf16', model=SimpleNamespace(
            get_audio_features=get_audio_features, audio_tower=SimpleNamespace(embedder=embedder)))
        engine.encode([0] * 1680)
        engine.encode([0] * 1680)
        self.assertIs(calls[0][0], initial_padding)
        self.assertIsNone(calls[0][1])
        self.assertIs(calls[1][0], next_padding)
        self.assertIs(calls[1][1], next_past)

    def test_gate_includes_four_distinct_cases_and_continuous_stream(self):
        cases = [dict(case_id=str(i), completed=True, x2_rtf=.6,
                      backlog_ms={'p95': 320}, rewrite_count=0, unclosed_groups=0)
                 for i in range(4)]
        cases[-1].update(case_id='continuous_60s', backlog_drift_ms=160)
        limits = dict(x2_rtf=.6, backlog_p95_ms=320, drift_ms=160, peak_gpu_mib=12288)
        self.assertEqual(probe.evaluate_gate(cases, 12288, limits), [])
        cases[-1]['backlog_drift_ms'] = 160.1
        self.assertIn('continuous_60s:backlog_drift_ms', probe.evaluate_gate(cases, 12288, limits))
        cases[0]['completed'] = False
        self.assertIn('0:incomplete', probe.evaluate_gate(cases, 12289, limits))
        self.assertIn('peak_gpu_mib', probe.evaluate_gate(cases, 12289, limits))
        self.assertIn('four_distinct_cases_required', probe.evaluate_gate(cases[:3], 1, limits))
        self.assertIn('continuous_60s_required', probe.evaluate_gate(cases[:3], 1, limits))

    def test_distribution_linear_percentiles(self):
        self.assertEqual(probe.distribution([])['count'], 0)
        self.assertEqual(probe.distribution([0, 100])['p95'], 95)


if __name__ == '__main__':
    unittest.main()
