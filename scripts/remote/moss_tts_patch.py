"""Runtime patch that raises MOSS-TTS-Realtime streaming throughput.

The TTS service loads the pinned upstream package (``moss_tts_realtime``) from
``$XTALK_MOSS_SOURCE_ROOT``.  Editing that checkout would make the pinned commit
unreviewable (``run_xtalk_round1.py`` even asserts ``git diff --quiet``), so the
patch is injected at interpreter startup through the ``sitecustomize`` shim that
the same launcher ships for the dynamo dynamic-shape fix.  This module installs a
meta-path hook that patches the inference class right after it is imported.

The streaming hot path is ``MossTTSRealtimeInference`` (in
``mossttsrealtime/streaming_mossttsrealtime.py``): ``MossTTSRealtimeStreamingSession``
only buffers text and delegates ``prefill`` / ``step`` / ``finish`` to it.  Every
audio frame costs one backbone forward plus 16 serial local-transformer forwards
(one per RVQ codebook, ``rvq=16``) plus sampling.

Two independent levers, both measured by
``scripts/remote/run_tts_throughput_ab_node_job.sh``:

**T1 - local transformer execution backend.**  Upstream compiles the codebook loop
only on the non-flash-attention path (``_should_compile_local_transformer =
not _use_dynamic_local_cache``), so our ``attn_impl=flash_attention_2`` deployment
runs all 17 forwards eagerly.  ``XTALK_TTS_LOCAL_COMPILE`` replaces the loop with
:func:`_local_loop`, a faithful re-implementation that keeps the local cache outside
the compiled region (so nothing has to construct a Python cache object inside the
graph), and compiles the loop itself - ``inductor`` or ``cudagraph``.

**T2 - per-codebook sampling.**  Upstream ``sample_token`` divides by the
temperature, runs a full-vocabulary ``topk``, then a full-vocabulary ``sort`` for
nucleus sampling, a ``softmax`` and a ``multinomial``: seven-plus tensor ops per
codebook, over a hundred per frame.  ``XTALK_TTS_SAMPLE`` selects a cheaper head:
``greedy`` (one ``argmax``) or ``topk`` (top-k, then nucleus over the k candidates
only).

``XTALK_TTS_METRICS=1`` adds one log line per turn: frames, audio seconds,
synthesis wall time and the resulting real-time factor.  Frame counting is always
patched; the two levers are not.

The patch never raises at import time: a failure falls back to the upstream code
path and is logged.  Only the single-session (batch size 1) service is supported,
which is how the TTS service is configured.
"""

from __future__ import annotations

import importlib.abc
import logging
import os
import sys
import time
from typing import Any, Optional

logger = logging.getLogger("xtalk.moss_tts_patch")

#: Module that owns the streaming inference class used by the service.
_TARGET_MODULE = "mossttsrealtime.streaming_mossttsrealtime"

#: Audio frame duration produced by the codec (24000 Hz / downsample_rate 1920).
FRAME_SECONDS = 1920.0 / 24000.0

#: Rows kept per codebook for the repetition penalty; the service uses window 50.
_HISTORY_CAPACITY = 128

_METRICS_ATTR = "_xt_metrics"
_INSTALLED = False
_COMPILED: dict[str, Any] = {}


def _env_value(name: str, default: str = "") -> str:
    """Return a normalized environment value."""
    return os.environ.get(name, default).strip().lower()


def local_compile_mode() -> str:
    """Return the requested local-transformer backend: ``off``, ``inductor`` or ``cudagraph``."""
    value = _env_value("XTALK_TTS_LOCAL_COMPILE", "off")
    if value in {"off", "0", "none", "eager"}:
        return "off"
    if value in {"inductor", "default", "compile"}:
        return "inductor"
    if value in {"cudagraph", "reduce-overhead", "graph"}:
        return "cudagraph"
    logger.warning("[moss-patch] unknown XTALK_TTS_LOCAL_COMPILE=%r; using off", value)
    return "off"


def sample_mode() -> str:
    """Return the requested sampling head: ``upstream``, ``greedy`` or ``topk``."""
    value = _env_value("XTALK_TTS_SAMPLE", "upstream")
    if value in {"greedy", "argmax"}:
        return "greedy"
    if value in {"topk", "nucleus"}:
        return "topk"
    return "upstream"


def metrics_enabled() -> bool:
    """Return whether per-turn synthesis metrics are logged."""
    return _env_value("XTALK_TTS_METRICS", "0") in {"1", "true", "yes", "on"}


def _sample_greedy(logits: Any) -> Any:
    """Return the argmax token, keeping the upstream output shape."""
    return logits.argmax(dim=-1)


def _sample_topk(logits: Any, temperature: float, top_p: float, top_k: int) -> Any:
    """Sample from the top-k candidates with nucleus filtering over those k only."""
    import torch

    scores = logits / temperature
    vocab = scores.shape[-1]
    k = max(1, min(int(top_k), vocab))
    values, indices = torch.topk(scores, k, dim=-1)
    probs = torch.softmax(values, dim=-1)
    cumulative = torch.cumsum(probs, dim=-1)
    keep = (cumulative - probs) <= float(top_p)
    keep[..., 0] = True
    probs = probs * keep
    probs = probs / probs.sum(dim=-1, keepdim=True)
    choice = torch.multinomial(probs.reshape(-1, k), 1)
    chosen = indices.reshape(-1, k).gather(1, choice)
    return chosen.view(*logits.shape[:-1])


def _local_loop(
    model: Any,
    past_key_values: Any,
    cache_positions: Any,
    hidden_states: Any,
    output_token: Any,
    history: Any,
    history_filled: int,
    repetition_penalty: float,
    repetition_window: int,
    temperature: float,
    top_p: float,
    top_k: int,
    mode: str,
) -> Any:
    """Fill ``output_token`` with one audio frame of ``channels`` codebooks.

    Mirrors upstream ``_generate_local_transformer_impl`` except that the local
    cache and the cache-position tensor are owned by the caller, so the loop body
    contains no Python object construction that a compiler would have to break on.

    Parameters
    ----------
    model : MossTTSRealtime
        Model whose ``local_transformer`` decodes the RVQ codebooks.
    past_key_values : Cache
        Fresh per-frame cache over the frame's codebooks.
    cache_positions : torch.Tensor
        Scalar tensor holding the codebook index, mutated in place.
    hidden_states : torch.Tensor
        Backbone hidden state of the frame, ``[B, 1, H]``.
    output_token : torch.Tensor
        Output buffer, ``[B, channels]``.
    history : torch.Tensor
        Right-aligned sliding window of previous frames, ``[B, cap, C]``.
    history_filled : int
        Number of valid rows at the end of ``history``.
    repetition_penalty, repetition_window : float, int
        Upstream repetition-penalty settings; a window of 0 means "whole history".
    temperature, top_p, top_k : float, float, int
        Sampling settings.
    mode : str
        Sampling head, see :func:`sample_mode`.

    Returns
    -------
    torch.Tensor
        ``output_token``.
    """
    import torch

    batch_size = output_token.shape[0]
    channels = output_token.shape[1]
    local_inputs = hidden_states.reshape(-1, 1, model.config.local_config.hidden_size)
    token = None
    for codebook in range(channels):
        cache_positions.fill_(codebook)
        outputs = model.local_transformer(
            input_ids=token,
            inputs_embeds=local_inputs,
            past_key_values=past_key_values,
            cache_position=cache_positions,
            codebook_idx=codebook,
            use_cache=True,
            logits_to_keep=1,
        )
        logits = outputs.logits[:, -1, :]
        if history_filled > 0 and repetition_penalty and repetition_penalty != 1.0:
            rows = history_filled
            if repetition_window > 0:
                rows = min(rows, repetition_window)
            codes = history[:, history.shape[1] - rows : history.shape[1], codebook]
            current = logits.gather(1, codes)
            adjusted = torch.where(
                current < 0, current * repetition_penalty, current / repetition_penalty
            )
            logits = logits.scatter(1, codes, adjusted)
        if mode == "greedy":
            token = _sample_greedy(logits).reshape(batch_size, 1)
        else:
            token = _sample_topk(logits, temperature, top_p, top_k).reshape(batch_size, 1)
        output_token[:, codebook] = token.reshape(batch_size)
        if codebook == 0:
            local_inputs = None
    return output_token


def _patched_sample_token(self, logits, temperature, top_p=0.6, top_k=30, do_sample=True):
    """Replace upstream sampling with the cheaper selected head."""
    if sample_mode() == "greedy" or not do_sample or temperature == 0:
        return _sample_greedy(logits)
    return _sample_topk(logits, temperature, top_p, top_k)


class _PatchLoader(importlib.abc.Loader):
    """Loader wrapper that patches the module right after it is executed."""

    def __init__(self, wrapped: importlib.abc.Loader) -> None:
        self._wrapped = wrapped

    def create_module(self, spec):
        """Delegate module creation to the wrapped loader."""
        return self._wrapped.create_module(spec)

    def exec_module(self, module) -> None:
        """Execute the module, then apply the throughput patch."""
        self._wrapped.exec_module(module)
        try:
            apply_patch(module)
        except Exception as error:  # pragma: no cover - defensive
            logger.warning("[moss-patch] patch failed, running upstream code: %s", error)


class _PatchFinder(importlib.abc.MetaPathFinder):
    """Finder that wraps the loader of the streaming inference module."""

    def find_spec(self, fullname, path=None, target=None):
        """Return a wrapped spec for the target module, else ``None``."""
        if fullname != _TARGET_MODULE:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            spec = finder.find_spec(fullname, path, target)
            if spec is not None and spec.loader is not None:
                spec.loader = _PatchLoader(spec.loader)
                return spec
        return None


def install() -> None:
    """Install the import hook; safe to call more than once."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    # The service runs under uvicorn, whose root configuration usually leaves the
    # default level at WARNING.  Metrics and the arm summary are informational, so
    # raise this module's level and make sure a handler exists at all.
    logger.setLevel(logging.INFO)
    logging.basicConfig(level=logging.INFO)
    for finder in list(sys.meta_path):
        if isinstance(finder, _PatchFinder):
            return
    sys.meta_path.insert(0, _PatchFinder())
    logger.info(
        "[moss-patch] armed local_compile=%s sample=%s metrics=%s",
        local_compile_mode(),
        sample_mode(),
        metrics_enabled(),
    )


def _attach(inferencer: Any) -> None:
    """Add the patch state to a freshly created inference object."""
    inferencer._xt_history = None
    inferencer._xt_history_filled = 0
    inferencer._xt_capacity = _HISTORY_CAPACITY
    inferencer._xt_channels = int(getattr(inferencer, "channels", 16))
    inferencer._xt_cache_positions = None
    inferencer._xt_runner = None
    inferencer._xt_runner_ready = False
    inferencer._xt_metrics = {"frames": 0, "started": None, "finished": None, "turns": 0}
    logger.info(
        "[moss-patch] inference ready channels=%d capacity=%d compile=%s sample=%s",
        inferencer._xt_channels,
        inferencer._xt_capacity,
        local_compile_mode(),
        sample_mode(),
    )


def _record_frame(inferencer: Any) -> None:
    """Advance the per-turn frame counters used by the metrics line."""
    metrics = getattr(inferencer, _METRICS_ATTR, None)
    if metrics is None:
        return
    if metrics["started"] is None:
        metrics["started"] = time.perf_counter()
    metrics["frames"] += 1
    metrics["finished"] = time.perf_counter()


def _log_metrics(inferencer: Any, reason: str) -> None:
    """Log one metrics line for the finished turn, when metrics are enabled."""
    metrics = getattr(inferencer, _METRICS_ATTR, None)
    if metrics is None or not metrics_enabled():
        return
    frames = metrics["frames"]
    if not frames or metrics["started"] is None:
        return
    wall = max(1e-9, (metrics["finished"] or time.perf_counter()) - metrics["started"])
    audio = frames * FRAME_SECONDS
    metrics["turns"] += 1
    metrics["frames"] = 0
    metrics["started"] = None
    metrics["finished"] = None
    logger.info(
        "[tts-metric] reason=%s turn=%d frames=%d audio_s=%.2f wall_s=%.2f rtf=%.2f",
        reason,
        metrics["turns"],
        frames,
        audio,
        wall,
        audio / wall,
    )


def _reset_metrics(inferencer: Any) -> None:
    """Start a fresh metrics turn."""
    metrics = getattr(inferencer, _METRICS_ATTR, None)
    if metrics is None:
        return
    metrics["frames"] = 0
    metrics["started"] = None
    metrics["finished"] = None


def _push_history(inferencer: Any, audio_tokens: Any) -> None:
    """Append one generated frame to the right-aligned sliding window."""
    import torch

    history = inferencer._xt_history
    capacity = inferencer._xt_capacity
    if history is None or history.shape[0] != audio_tokens.shape[0]:
        history = torch.zeros(
            (audio_tokens.shape[0], capacity, inferencer._xt_channels),
            dtype=audio_tokens.dtype,
            device=audio_tokens.device,
        )
        inferencer._xt_history = history
        inferencer._xt_history_filled = 0
    history[:, :-1, :] = history[:, 1:, :].clone()
    history[:, -1, :] = audio_tokens
    inferencer._xt_history_filled = min(
        inferencer._xt_history_filled + 1, inferencer._xt_capacity
    )


def _compile_local_loop(mode: str) -> Optional[Any]:
    """Compile :func:`_local_loop` once per backend, returning ``None`` on failure."""
    import torch

    if mode in _COMPILED:
        return _COMPILED[mode]
    compiled = None
    try:
        compiled = torch.compile(_local_loop, fullgraph=True, dynamic=False, mode=mode)
        logger.info("[moss-patch] torch.compile(_local_loop) ready mode=%s", mode)
    except Exception as error:  # pragma: no cover - defensive
        logger.warning("[moss-patch] torch.compile failed mode=%s: %s", mode, error)
    _COMPILED[mode] = compiled
    return compiled


def _ensure_runner(inferencer: Any) -> Optional[Any]:
    """Return this session's compiled local loop, warming it up once."""
    mode = local_compile_mode()
    if mode == "off":
        return None
    if inferencer._xt_runner_ready:
        return inferencer._xt_runner
    inferencer._xt_runner = _compile_local_loop(
        "default" if mode == "inductor" else "reduce-overhead"
    )
    inferencer._xt_runner_ready = True
    if inferencer._xt_runner is None:
        return None
    try:
        _warmup_runner(inferencer)
    except Exception as error:  # pragma: no cover - defensive
        logger.warning("[moss-patch] compiled warmup failed, falling back to eager: %s", error)
        inferencer._xt_runner = None
    return inferencer._xt_runner


def _warmup_runner(inferencer: Any) -> None:
    """Capture every codebook shape once so the first real frame is not delayed."""
    import torch

    device = inferencer.device
    hidden = int(inferencer.model.config.local_config.hidden_size)
    history = torch.zeros(
        (1, inferencer._xt_capacity, inferencer._xt_channels), dtype=torch.long, device=device
    )
    cache_positions = torch.zeros(1, dtype=torch.long, device=device)
    output = torch.empty(1, inferencer._xt_channels, dtype=torch.long, device=device)
    started = time.perf_counter()
    inferencer._xt_runner(
        inferencer.model,
        inferencer._build_local_past_key_values(),
        cache_positions,
        torch.zeros(1, 1, hidden, device=device, dtype=torch.float32),
        output,
        history,
        inferencer._xt_capacity,
        0.0,
        0,
        0.8,
        0.6,
        30,
        sample_mode(),
    )
    logger.info("[moss-patch] compiled warmup done in %.1fs", time.perf_counter() - started)


def apply_patch(module: Any) -> None:
    """Patch the streaming inference class of the given upstream module."""
    inference_cls = getattr(module, "MossTTSRealtimeInference", None)
    session_cls = getattr(module, "MossTTSRealtimeStreamingSession", None)
    if inference_cls is None or not hasattr(inference_cls, "generate_local_transformer"):
        logger.warning("[moss-patch] streaming inference class not found")
        return
    if getattr(inference_cls, "_xt_patched", False):
        return

    original_init = inference_cls.__init__
    original_generate = inference_cls.generate_local_transformer
    original_prefill = inference_cls.prefill
    original_step = inference_cls.step
    original_finish = inference_cls.finish
    original_reset = getattr(inference_cls, "reset_generation_state", None)

    def patched_init(self, *args, **kwargs):
        """Add the patch state after the upstream constructor ran."""
        original_init(self, *args, **kwargs)
        _attach(self)

    def patched_generate_local_transformer(
        self,
        hidden_states,
        temperature,
        top_p,
        top_k,
        do_sample,
        repetition_penalty,
        repetition_window,
        generated_tokens,
        gen_step,
    ):
        """Run the frame's codebooks with the selected backend and sampling head."""
        import torch

        _record_frame(self)
        runner = _ensure_runner(self)
        # The compiled loop only runs once the history window is saturated: that
        # keeps every compiled argument constant (one graph instead of one per
        # frame count), and the first frames of a turn run upstream-eager with
        # identical math.
        use_compiled = runner is not None and self._xt_history_filled >= self._xt_window
        if not use_compiled:
            return original_generate(
                self,
                hidden_states=hidden_states,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                do_sample=do_sample,
                repetition_penalty=repetition_penalty,
                repetition_window=repetition_window,
                generated_tokens=generated_tokens,
                gen_step=gen_step,
            )
        if (
            self._xt_cache_positions is None
            or self._xt_cache_positions.device != hidden_states.device
        ):
            self._xt_cache_positions = torch.zeros(
                1, dtype=torch.long, device=hidden_states.device
            )
        output_token = torch.empty(
            hidden_states.shape[0], self._xt_channels, dtype=torch.long, device=hidden_states.device
        )
        return runner(
            self.model,
            self._build_local_past_key_values(),
            self._xt_cache_positions,
            hidden_states,
            output_token,
            self._xt_history,
            self._xt_capacity,
            float(repetition_penalty or 0.0),
            int(repetition_window or 0),
            float(temperature),
            float(top_p),
            int(top_k),
            sample_mode(),
        )

    def patched_prefill(self, *args, **kwargs):
        """Run upstream prefill and start a fresh metrics turn."""
        result = original_prefill(self, *args, **kwargs)
        self._xt_history = None
        self._xt_history_filled = 0
        _reset_metrics(self)
        _push_history(self, result)
        return result

    def patched_step(self, *args, **kwargs):
        """Run upstream step and extend the sliding window with the new frame."""
        result = original_step(self, *args, **kwargs)
        _push_history(self, result)
        return result

    def patched_finish(self, *args, **kwargs):
        """Run upstream finish and report this turn's synthesis metrics."""
        result = original_finish(self, *args, **kwargs)
        _log_metrics(self, "finish")
        return result

    def patched_reset_generation_state(self, *args, **kwargs):
        """Run upstream reset and clear the sliding window."""
        result = original_reset(self, *args, **kwargs)
        self._xt_history = None
        self._xt_history_filled = 0
        return result

    inference_cls.generate_local_transformer = patched_generate_local_transformer
    inference_cls.prefill = patched_prefill
    inference_cls.step = patched_step
    inference_cls.finish = patched_finish
    inference_cls.__init__ = patched_init
    if original_reset is not None:
        inference_cls.reset_generation_state = patched_reset_generation_state
    if sample_mode() != "upstream":
        inference_cls.sample_token = _patched_sample_token
    inference_cls._xt_patched = True
    # The session ends a turn through end_text/drain; report metrics there too so
    # a turn that generated frames without a finish() call is still accounted.
    if session_cls is not None and not getattr(session_cls, "_xt_patched", False):
        original_end_text = session_cls.end_text
        original_drain = session_cls.drain

        def patched_end_text(self, *args, **kwargs):
            """Run upstream end_text and report the turn metrics."""
            result = original_end_text(self, *args, **kwargs)
            _log_metrics(getattr(self, "inferencer", None), "end_text")
            return result

        def patched_drain(self, *args, **kwargs):
            """Run upstream drain and report metrics if it produced frames."""
            result = original_drain(self, *args, **kwargs)
            _log_metrics(getattr(self, "inferencer", None), "drain")
            return result

        session_cls.end_text = patched_end_text
        session_cls.drain = patched_drain
        session_cls._xt_patched = True
    logger.info(
        "[moss-patch] applied to %s (compile=%s sample=%s)",
        inference_cls.__name__,
        local_compile_mode(),
        sample_mode(),
    )
