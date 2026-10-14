"""Verify the MOSS-TTS throughput patch: equivalence, sampling heads and plumbing.

The loop rewrite (T1) is only acceptable if it produces exactly what the upstream
implementation produces, so the equivalence tests compare both on a deterministic
fake local transformer with greedy sampling: without history, with the repetition
penalty, and with a saturated history window.  Those cases need the real upstream
class (the TTS conda environment) and are skipped elsewhere; the remaining tests
cover sampling, the sliding window, the metrics line and the import hook.
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

    def _compare(self, filled, penalty, window, channels=16):
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
            'greedy',
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


@_NEEDS_TORCH
class MetricsTests(unittest.TestCase):
    """Metrics count frames and report the real-time factor once per turn."""

    def test_metrics_line_reports_rtf(self):
        """One log line per turn carries frames, audio seconds and rtf."""
        inferencer = types.SimpleNamespace()
        patch._attach(inferencer)
        previous = os.environ.get('XTALK_TTS_METRICS')
        os.environ['XTALK_TTS_METRICS'] = '1'
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = logging.getLogger('xtalk.moss_tts_patch')
        handler = Capture()
        previous_level = logger.level
        try:
            logger.setLevel(logging.INFO)
            for _ in range(25):
                patch._record_frame(inferencer)
            logger.addHandler(handler)
            try:
                patch._log_metrics(inferencer, 'finish')
            finally:
                logger.removeHandler(handler)
        finally:
            logger.setLevel(previous_level)
            if previous is None:
                os.environ.pop('XTALK_TTS_METRICS', None)
            else:
                os.environ['XTALK_TTS_METRICS'] = previous
        self.assertEqual(len(records), 1)
        self.assertIn('frames=25', records[0])
        self.assertIn('audio_s=2.00', records[0])
        self.assertIn('rtf=', records[0])
        self.assertEqual(inferencer._xt_metrics['frames'], 0)


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
