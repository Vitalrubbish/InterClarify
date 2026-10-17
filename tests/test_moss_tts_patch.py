"""Verify the MOSS-TTS throughput patch: equivalence, sampling heads and plumbing.

The loop rewrite (T1) is only acceptable if it produces exactly what the upstream
implementation produces, so the equivalence tests compare both on a deterministic
fake local transformer: without history, with the repetition penalty, and with a
saturated history window, both through the greedy head and through the upstream
``sample_token``.  Those cases need the real upstream class (the TTS conda
environment) and are skipped elsewhere; the remaining tests cover the sampling
heads, the attach state of the hot path, the sliding window, the rate-limited
metrics lines, the profiler switch and the import hook.
"""

import importlib
import importlib.util
import logging
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

try:
    import torch
except ImportError:  # pragma: no cover - the TTS conda environment provides torch
    # The patch only runs inside the TTS service environment; other environments
    # have no MOSS stack to verify against, so those cases are skipped.
    torch = None

_NEEDS_TORCH = unittest.skipIf(torch is None, 'torch is only installed in the TTS environment')

SPEC = importlib.util.spec_from_file_location(
    'moss_tts_patch', Path(__file__).parents[1] / 'scripts/remote/moss_tts_patch.py')
patch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = patch
SPEC.loader.exec_module(patch)


def _upstream_inference_class():
    """Return the real upstream inference class, or ``None`` when unavailable."""
    try:
        from mossttsrealtime.streaming_mossttsrealtime import MossTTSRealtimeInference

        return MossTTSRealtimeInference
    except Exception:
        return None


UPSTREAM = _upstream_inference_class()


class FakeLocalTransformer:
    """Deterministic stand-in for the RVQ codebook decoder."""

    def __init__(self, vocab=7):
        self.vocab = vocab

    def __call__(
        self,
        input_ids=None,
        inputs_embeds=None,
        past_key_values=None,
        cache_position=None,
        codebook_idx=0,
        use_cache=True,
        logits_to_keep=1,
    ):
        """Return codebook-dependent logits as a function of the frame and token."""
        seed = float(inputs_embeds.reshape(-1).sum()) if inputs_embeds is not None else 0.0
        seed += float(input_ids.reshape(-1).sum()) if input_ids is not None else 0.0
        grid = torch.arange(self.vocab, dtype=torch.float32)
        logits = torch.sin(grid + codebook_idx * 0.7 + seed).reshape(1, 1, self.vocab)
        return types.SimpleNamespace(logits=logits)


def capture_logs(function):
    """Run ``function`` while capturing this patch module's log lines."""
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger('xtalk.moss_tts_patch')
    handler = Capture()
    previous_level = logger.level
    try:
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        function()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
    return records


class FakeModel:
    """Model container exposing only what the local loop reads."""

    def __init__(self, hidden=4, vocab=7):
        self.config = types.SimpleNamespace(
            local_config=types.SimpleNamespace(hidden_size=hidden))
        self.local_transformer = FakeLocalTransformer(vocab)


@unittest.skipUnless(UPSTREAM is not None, 'upstream moss_tts_realtime is not importable')
@_NEEDS_TORCH
class LoopEquivalenceTests(unittest.TestCase):
    """The caller-owned loop must reproduce upstream's tokens exactly."""

    def _compare(self, filled, penalty, window, mode='greedy', channels=16):
        """Run upstream's loop and the patch's loop on one frame."""
        hidden = torch.randn(1, 1, 4)
        model = FakeModel()
        history = torch.randint(0, 7, (1, patch._HISTORY_CAPACITY, channels))
        generated = None if filled == 0 else history[:, -filled:, :]

        reference = object.__new__(UPSTREAM)
        reference.model = model
        reference.channels = channels
        reference._use_dynamic_local_cache = True
        reference.sample_token = lambda logits, **kwargs: logits.argmax(dim=-1)
        expected = reference._generate_local_transformer_impl(
            hidden_states=hidden,
            temperature=0.8,
            top_p=0.6,
            top_k=30,
            do_sample=False,
            repetition_penalty=penalty,
            repetition_window=window,
            generated_tokens=generated,
            gen_step=filled,
        )

        actual = patch._local_loop(
            model,
            object(),
            torch.zeros(1, dtype=torch.long),
            hidden,
            torch.empty(1, channels, dtype=torch.long),
            history,
            filled,
            float(penalty or 0.0),
            int(window),
            0.8,
            0.6,
            30,
            False,
            lambda logits, **kwargs: logits.argmax(dim=-1),
            mode,
        )
        return expected, actual

    def test_matches_upstream_without_penalty(self):
        """First frame of a turn: no history and no penalty."""
        expected, actual = self._compare(0, None, 50)
        self.assertTrue(torch.equal(expected, actual), (expected, actual))

    def test_matches_upstream_with_penalty(self):
        """Mid-turn frame: the penalty covers the frames seen so far."""
        expected, actual = self._compare(20, 1.1, 50)
        self.assertTrue(torch.equal(expected, actual), (expected, actual))

    def test_matches_upstream_with_saturated_window(self):
        """Saturated window: only the last ``repetition_window`` frames matter."""
        expected, actual = self._compare(120, 1.1, 8)
        self.assertTrue(torch.equal(expected, actual), (expected, actual))

    def test_matches_upstream_through_sample_token(self):
        """``mode='upstream'`` dispatches to the caller's ``sample_token``."""
        calls = []

        def sample_token(logits, **kwargs):
            calls.append(tuple(logits.shape))
            return logits.argmax(dim=-1)

        hidden = torch.randn(1, 1, 4)
        history = torch.randint(0, 7, (1, patch._HISTORY_CAPACITY, 16))
        expected = patch._local_loop(
            FakeModel(), object(), torch.zeros(1, dtype=torch.long), hidden,
            torch.empty(1, 16, dtype=torch.long), history, 0, 0.0, 50,
            0.8, 0.6, 30, True, sample_token, 'greedy')
        actual = patch._local_loop(
            FakeModel(), object(), torch.zeros(1, dtype=torch.long), hidden,
            torch.empty(1, 16, dtype=torch.long), history, 0, 0.0, 50,
            0.8, 0.6, 30, True, sample_token, 'upstream')
        self.assertEqual(len(calls), 16)
        self.assertTrue(torch.equal(expected, actual), (expected, actual))

    def test_greedy_mode_wins_over_do_sample(self):
        """``do_sample=False`` (or zero temperature) falls back to argmax."""
        logits = torch.tensor([[0.0, 5.0, 1.0]])
        self.assertEqual(patch._sample_greedy(logits).tolist(), [1])


@_NEEDS_TORCH
class MaskedLoopTests(unittest.TestCase):
    """The fixed-shape path must preserve every codebook token."""

    def test_masked_loop_matches_sliced_history(self):
        hidden = torch.ones(1, 1, 4)
        history = torch.randint(0, 7, (1, 128, 16))
        for filled in (0, 1, 49, 50, 51, 128):
            for penalty in (0., 1., 1.1):
                args = [FakeModel(), object(), torch.zeros(1, dtype=torch.long),
                        hidden, torch.empty(1, 16, dtype=torch.long), history,
                        filled, penalty, 50, .8, .6, 30, False,
                        lambda logits, **kwargs: logits.argmax(dim=-1), 'upstream']
                expected = patch._local_loop(*args).clone()
                args[6] = 128
                actual = patch._local_loop(*args, valid_length=torch.tensor(filled))
                self.assertTrue(torch.equal(actual, expected), (filled, penalty))

    def test_persistent_history_can_be_updated_after_inference_mode_returns(self):
        from unittest.mock import patch as mock_patch

        class Inference:
            def __init__(self):
                self.model = FakeModel()
                self.channels = 16
            def _build_local_past_key_values(self):
                return object()
            def sample_token(self, logits, **kwargs):
                return logits.argmax(dim=-1)
            def generate_local_transformer(self, **kwargs):
                return torch.zeros(1, 16, dtype=torch.long)
            @torch.inference_mode()
            def prefill(self):
                return self.generate_local_transformer(
                    hidden_states=torch.ones(1, 1, 4), temperature=.8, top_p=.6,
                    top_k=30, do_sample=False, repetition_penalty=None,
                    repetition_window=50, generated_tokens=None, gen_step=0)
            @torch.inference_mode()
            def step(self):
                return self.generate_local_transformer(
                    hidden_states=torch.ones(1, 1, 4), temperature=.8, top_p=.6,
                    top_k=30, do_sample=False, repetition_penalty=1.1,
                    repetition_window=50, generated_tokens=None, gen_step=1)
            def finish(self):
                return []

        module = types.SimpleNamespace(MossTTSRealtimeInference=Inference)
        with mock_patch.dict(os.environ, {'XTALK_TTS_EARLY_COMPILE': '1',
                'XTALK_TTS_LOCAL_COMPILE': 'off', 'XTALK_TTS_METRICS': '0', 'XTALK_TTS_TRACE': ''}), \
                mock_patch.object(patch, '_ensure_runner', return_value=patch._local_loop):
            patch.apply_patch(module)
            inferencer = Inference()
            inferencer.prefill()
            self.assertFalse(inferencer._xt_history.is_inference())
            self.assertFalse(inferencer._xt_valid_length.is_inference())
            self.assertEqual(inferencer._xt_history_filled, 1)
            inferencer.step()
            self.assertEqual(inferencer._xt_history_filled, 2)
            inferencer.prefill()
            self.assertEqual(inferencer._xt_history_filled, 1)

    def test_warmup_preserves_sampling_rng(self):
        inferencer = types.SimpleNamespace()
        patch._attach(inferencer)
        inferencer._xt_runner = lambda *args: torch.rand(30)
        inferencer._build_local_past_key_values = lambda: object()
        inferencer.model = FakeModel()
        from unittest.mock import patch as mock_patch
        with mock_patch.dict(os.environ, {'XTALK_TTS_EARLY_COMPILE': '1'}):
            warmup = {'hidden_states': torch.ones(1, 1, 4), 'penalty': 0.,
                      'configured_penalty': 1.1, 'window': 50, 'temperature': .8,
                      'top_p': .6, 'top_k': 30, 'do_sample': True, 'sample_token': None}
            before = torch.random.get_rng_state().clone()
            patch._warmup_runner(inferencer, warmup)
            self.assertTrue(torch.equal(before, torch.random.get_rng_state()))


@_NEEDS_TORCH
class SamplingTests(unittest.TestCase):
    """Cheaper sampling heads keep the upstream contract."""

    def test_greedy_is_argmax(self):
        """Greedy returns the argmax with the upstream shape."""
        logits = torch.randn(1, 1, 9)
        self.assertTrue(torch.equal(patch._sample_greedy(logits), logits.argmax(dim=-1)))

    def test_topk_stays_inside_the_candidate_set(self):
        """Sampled ids come from the top-k and keep the upstream shape."""
        torch.manual_seed(0)
        logits = torch.randn(1, 1, 11)
        top = set(torch.topk(logits, 3, dim=-1).indices.reshape(-1).tolist())
        for _ in range(20):
            token = patch._sample_topk(logits, 1.0, 1.0, 3)
            self.assertEqual(tuple(token.shape), (1, 1))
            self.assertIn(int(token.item()), top)

    def test_patched_sample_token_honours_greedy_mode(self):
        """The patched method honours ``XTALK_TTS_SAMPLE=greedy``."""
        logits = torch.randn(1, 1, 5)
        previous = os.environ.get('XTALK_TTS_SAMPLE')
        os.environ['XTALK_TTS_SAMPLE'] = 'greedy'
        try:
            token = patch._patched_sample_token(None, logits, 1.0)
            self.assertTrue(torch.equal(token, logits.argmax(dim=-1)))
        finally:
            if previous is None:
                os.environ.pop('XTALK_TTS_SAMPLE', None)
            else:
                os.environ['XTALK_TTS_SAMPLE'] = previous


@_NEEDS_TORCH
class HistoryTests(unittest.TestCase):
    """The sliding window stays right-aligned and bounded."""

    def test_window_keeps_the_newest_frames(self):
        """Old frames fall out of the window and order is chronological."""
        inferencer = types.SimpleNamespace()
        patch._attach(inferencer)
        frames = [torch.full((1, inferencer._xt_channels), index) for index in range(3)]
        for frame in frames:
            patch._push_history(inferencer, frame)
        self.assertEqual(inferencer._xt_history_filled, 3)
        self.assertEqual(inferencer._xt_history[0, -3:, 0].tolist(), [0, 1, 2])
        for _ in range(patch._HISTORY_CAPACITY + 5):
            patch._push_history(inferencer, frames[0])
        self.assertEqual(inferencer._xt_history_filled, patch._HISTORY_CAPACITY)


class AttachStateTests(unittest.TestCase):
    """The hot path may only read attributes ``_attach`` actually creates."""

    def test_attach_defines_every_attribute_the_hot_path_reads(self):
        """Guards against the class of bug where a gate read an unset field."""
        inferencer = types.SimpleNamespace()
        patch._attach(inferencer)
        for name in (
            '_xt_history', '_xt_history_filled', '_xt_capacity', '_xt_channels',
            '_xt_cache_positions', '_xt_runner', '_xt_runner_ready', '_xt_runner_used',
            '_xt_turn_frames', '_xt_turns', '_xt_local_events', '_xt_backbone_events',
            '_xt_profiler', '_xt_profile_frames', '_xt_profile_disabled', '_xt_metrics',
        ):
            self.assertTrue(hasattr(inferencer, name), name)


class CompileGateTests(unittest.TestCase):
    """The compiled loop takes over only once the penalty window is saturated."""

    def test_target_is_the_repetition_window(self):
        """A 50-frame window lets the compiled path start after 50 frames."""
        self.assertEqual(patch._compile_target(128, 50), 50)

    def test_target_is_bounded_by_the_capacity(self):
        """A window wider than the sliding window saturates at the capacity."""
        self.assertEqual(patch._compile_target(128, 4096), 128)

    def test_target_is_the_capacity_without_a_window(self):
        """No repetition window means the whole stored history is read."""
        self.assertEqual(patch._compile_target(128, 0), 128)


class EventAccountingTests(unittest.TestCase):
    """CUDA-event pairs are summed once their end event has completed."""

    class _Event:
        """Minimal event double: ``elapsed_time`` in milliseconds."""

        def __init__(self, milliseconds=None):
            self.milliseconds = milliseconds

        def query(self):
            return self.milliseconds is not None

        def elapsed_time(self, other):
            return other.milliseconds

    def test_only_completed_pairs_are_consumed(self):
        """Finished pairs add up; the running one stays for the next line."""
        done = (self._Event(), self._Event(4.0))
        also_done = (self._Event(), self._Event(6.0))
        running = (self._Event(), self._Event(None))
        pairs = [done, also_done, running]
        self.assertAlmostEqual(patch._consume_events(pairs), 0.01, places=6)
        self.assertEqual(pairs, [running])
        self.assertEqual(patch._consume_events([]), 0.0)


@_NEEDS_TORCH
class MetricsTests(unittest.TestCase):
    """Metrics report slices of synthesis, rate-limited by size or wall clock."""

    def _capture(self, function):
        """Run ``function`` while capturing this module's log lines."""
        return capture_logs(function)

    def _with_metrics(self, function):
        """Run ``function`` with ``XTALK_TTS_METRICS=1`` and restore the env."""
        previous = os.environ.get('XTALK_TTS_METRICS')
        os.environ['XTALK_TTS_METRICS'] = '1'
        try:
            return function()
        finally:
            if previous is None:
                os.environ.pop('XTALK_TTS_METRICS', None)
            else:
                os.environ['XTALK_TTS_METRICS'] = previous

    def test_metrics_line_reports_rtf(self):
        """One line per slice carries frames, audio seconds, rtf and the split."""
        def run():
            inferencer = types.SimpleNamespace()
            patch._attach(inferencer)
            for _ in range(25):
                patch._record_frame(inferencer)
            records = self._capture(lambda: patch._log_metrics(inferencer, 'finish'))
            self.assertEqual(inferencer._xt_metrics['frames'], 0)
            return records

        records = self._with_metrics(run)
        self.assertEqual(len(records), 1)
        self.assertIn('frames=25', records[0])
        self.assertIn('audio_s=2.00', records[0])
        self.assertIn('rtf=', records[0])
        self.assertIn('local_s=', records[0])
        self.assertIn('backbone_s=', records[0])

    def test_small_slices_are_skipped_unless_forced(self):
        """Two frames stay silent, and ``force`` emits them at a turn end."""
        def run():
            inferencer = types.SimpleNamespace()
            patch._attach(inferencer)
            for _ in range(2):
                patch._record_frame(inferencer)
            quiet = self._capture(lambda: patch._log_metrics(inferencer, 'drain'))
            forced = self._capture(
                lambda: patch._log_metrics(inferencer, 'end_text', force=True))
            self.assertEqual(inferencer._xt_metrics['frames'], 0)
            return quiet, forced

        quiet, forced = self._with_metrics(run)
        self.assertEqual(quiet, [])
        self.assertEqual(len(forced), 1)
        self.assertIn('frames=2', forced[0])

    def test_metrics_are_silent_without_the_switch(self):
        """Without ``XTALK_TTS_METRICS`` the counters still work, logging does not."""
        inferencer = types.SimpleNamespace()
        patch._attach(inferencer)
        for _ in range(25):
            patch._record_frame(inferencer)
        records = self._capture(lambda: patch._log_metrics(inferencer, 'finish'))
        self.assertEqual(records, [])


@_NEEDS_TORCH
class CompileSupportTests(unittest.TestCase):
    """The compile path declares what dynamo needs and parses its own switches."""

    def test_logger_methods_are_ignored_by_dynamo(self):
        """``Logger.warning_once`` must not abort a full graph trace."""
        import torch._dynamo

        original = torch._dynamo.config.ignore_logger_methods.copy()
        self.addCleanup(setattr, torch._dynamo.config, "ignore_logger_methods", original)
        patch.relax_dynamo_logging()
        if hasattr(logging.Logger, "warning_once"):
            self.assertIn(logging.Logger.warning_once, torch._dynamo.config.ignore_logger_methods)
        self.assertIn(logging.Logger.warning, torch._dynamo.config.ignore_logger_methods)

    def test_backbone_event_list_is_shared_across_turns(self):
        """The service builds one inference object per turn, the model lives on."""

        class FakeModule:
            def forward(self, value):
                """Mirror ``nn.Module.forward``."""
                return value

        model = FakeModule()
        first = types.SimpleNamespace(model=model)
        second = types.SimpleNamespace(model=model)
        patch._wrap_backbone(first)
        patch._wrap_backbone(second)
        self.assertIs(first._xt_backbone_events, second._xt_backbone_events)
        self.assertTrue(getattr(model, '_xt_timed', False))

    def test_local_attention_switch_moves_to_sdpa_and_static_cache(self):
        """The switch rewrites the local transformer only, not the backbone."""
        inferencer = types.SimpleNamespace(
            model=types.SimpleNamespace(
                local_transformer=types.SimpleNamespace(
                    config=types.SimpleNamespace(_attn_implementation='flash_attention_2')),
                config=types.SimpleNamespace(_attn_implementation='flash_attention_2'),
            ),
            _use_dynamic_local_cache=True,
            _should_compile_local_transformer=True,
        )
        patch.switch_local_attention(inferencer)
        self.assertEqual(
            inferencer.model.local_transformer.config._attn_implementation, 'sdpa')
        self.assertEqual(inferencer.model.config._attn_implementation, 'flash_attention_2')
        self.assertFalse(inferencer._use_dynamic_local_cache)
        self.assertFalse(inferencer._should_compile_local_transformer)

    def test_local_attention_switch_parses_env(self):
        """``XTALK_TTS_LOCAL_ATTN=sdpa`` is the only enabling spelling."""
        previous = os.environ.get('XTALK_TTS_LOCAL_ATTN')
        try:
            os.environ.pop('XTALK_TTS_LOCAL_ATTN', None)
            self.assertEqual(patch.local_attention_mode(), 'upstream')
            os.environ['XTALK_TTS_LOCAL_ATTN'] = 'SDPA'
            self.assertEqual(patch.local_attention_mode(), 'sdpa')
        finally:
            if previous is None:
                os.environ.pop('XTALK_TTS_LOCAL_ATTN', None)
            else:
                os.environ['XTALK_TTS_LOCAL_ATTN'] = previous

    def test_profile_summary_line_is_parseable(self):
        """The summary names the device time and the heaviest kernels."""

        class Entry:
            def __init__(self, key, device, cpu, count):
                self.key = key
                self.self_device_time_total = device
                self.self_cpu_time_total = cpu
                self.count = count

        records = capture_logs(lambda: patch._log_profile_summary(
            60, [Entry('aten::mm', 1_200_000.0, 300_000.0, 640),
                 Entry('flash::flash_fwd', 200_000.0, 10_000.0, 64)]))
        self.assertEqual(len(records), 1)
        self.assertIn('frames=60', records[0])
        self.assertIn('device_s=1.400', records[0])
        self.assertIn('cpu_s=0.310', records[0])
        self.assertIn('aten::mm:1.200s:640', records[0])

    def test_profile_dump_appends_one_table_per_call(self):
        """A finished profiler appends exactly one table with its frame count."""

        class FakeProfiler:
            def stop(self):
                """Mirror ``torch.profiler.profile.stop``."""

            def key_averages(self):
                """Mirror ``torch.profiler.profile.key_averages``."""
                return self

            def table(self, sort_by=None, row_limit=None):
                """Mirror the event list's text table."""
                return 'KERNEL 1.00ms'

        inferencer = types.SimpleNamespace()
        patch._attach(inferencer)
        inferencer._xt_profiler = FakeProfiler()
        inferencer._xt_profile_frames = 12
        previous = os.environ.get('XTALK_TTS_PROFILE')
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'profile.txt'
            os.environ['XTALK_TTS_PROFILE'] = str(target)
            try:
                patch._dump_profile(inferencer, 'frames')
                patch._dump_profile(inferencer, 'frames')
            finally:
                if previous is None:
                    os.environ.pop('XTALK_TTS_PROFILE', None)
                else:
                    os.environ['XTALK_TTS_PROFILE'] = previous
            text = target.read_text(encoding='utf-8')
        self.assertEqual(text.count('KERNEL 1.00ms'), 1)
        self.assertIn('profiled_frames=12', text)

    def test_profile_switch_parses_env(self):
        """The profiler target and frame budget come from the environment."""
        previous_path = os.environ.get('XTALK_TTS_PROFILE')
        previous_frames = os.environ.get('XTALK_TTS_PROFILE_FRAMES')
        os.environ['XTALK_TTS_PROFILE'] = '/tmp/x.profile.txt'
        os.environ['XTALK_TTS_PROFILE_FRAMES'] = '7'
        try:
            self.assertEqual(patch.profile_path(), '/tmp/x.profile.txt')
            self.assertEqual(patch.profile_frames(), 7)
            del os.environ['XTALK_TTS_PROFILE_FRAMES']
            self.assertEqual(patch.profile_frames(), patch._PROFILE_DEFAULT_FRAMES)
        finally:
            if previous_path is None:
                os.environ.pop('XTALK_TTS_PROFILE', None)
            else:
                os.environ['XTALK_TTS_PROFILE'] = previous_path
            if previous_frames is None:
                os.environ.pop('XTALK_TTS_PROFILE_FRAMES', None)
            else:
                os.environ['XTALK_TTS_PROFILE_FRAMES'] = previous_frames


@_NEEDS_TORCH
class ImportHookTests(unittest.TestCase):
    """The import hook patches the target module without editing the checkout."""

    def test_install_wraps_the_target_module(self):
        """A fake target module is patched as soon as it is imported."""
        source = (
            'class MossTTSRealtimeInference:\n'
            '    """Fake inference class."""\n\n'
            '    def __init__(self):\n'
            '        self.model = None\n'
            '        self.channels = 16\n'
            '        self.repetition_window = 50\n\n'
            '    def generate_local_transformer(self, **kwargs):\n'
            '        return None\n\n'
            '    def prefill(self, *args, **kwargs):\n'
            '        return None\n\n'
            '    def step(self, *args, **kwargs):\n'
            '        return None\n\n'
            '    def finish(self, *args, **kwargs):\n'
            '        return None\n\n'
            '    def sample_token(self, logits, **kwargs):\n'
            '        return logits\n\n'
            '    def reset_generation_state(self, keep_cache=True):\n'
            '        return None\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'mossttsrealtime'
            root.mkdir()
            (root / '__init__.py').write_text('', encoding='utf-8')
            (root / 'streaming_mossttsrealtime.py').write_text(source, encoding='utf-8')
            patch.install()
            sys.path.insert(0, tmp)
            try:
                for name in [name for name in sys.modules if name.startswith('mossttsrealtime')]:
                    del sys.modules[name]
                module = importlib.import_module('mossttsrealtime.streaming_mossttsrealtime')
            finally:
                sys.path.remove(tmp)
        self.assertTrue(getattr(module.MossTTSRealtimeInference, '_xt_patched', False))


if __name__ == '__main__':
    unittest.main()
