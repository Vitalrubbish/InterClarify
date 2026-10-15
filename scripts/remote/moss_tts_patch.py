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

Two independent levers, both measured by a single-card throughput A/B job that
was retired on 2026-10-15 (its numbers are recorded in the A4 task document).
They are independent variables: an arm must change exactly one of them,
otherwise the report cannot attribute the difference.

**T1 - local transformer execution backend.**  Upstream compiles the codebook loop
only on the non-flash-attention path (``_should_compile_local_transformer =
not _use_dynamic_local_cache``), so our ``attn_impl=flash_attention_2`` deployment
runs all 17 forwards eagerly.  ``XTALK_TTS_LOCAL_COMPILE`` replaces the loop with
:func:`_local_loop`, a faithful re-implementation that keeps the local cache outside
the compiled region (so nothing has to construct a Python cache object inside the
graph), and compiles the loop itself - ``inductor`` or ``cudagraph``.

Compiling that loop on the flash-attention path is impossible: the local
transformer decodes one query token against a 17-key cache without an attention
mask, and flash-attn's helper then branches on the *values* of ``position_ids``,
which ``fullgraph=True`` cannot trace (``Data-dependent branching``).  The
``XTALK_TTS_LOCAL_ATTN=sdpa`` switch moves the local transformer to sdpa and to
the static local cache upstream's compiled path already uses, leaving the
backbone on flash-attention - sdpa is a single traceable kernel and is cheaper at
this size.

**T2 - per-codebook sampling.**  Upstream ``sample_token`` divides by the
temperature, runs a full-vocabulary ``topk``, then a full-vocabulary ``sort`` for
nucleus sampling, a ``softmax`` and a ``multinomial``: seven-plus tensor ops per
codebook, over a hundred per frame.  ``XTALK_TTS_SAMPLE`` selects a cheaper head:
``greedy`` (one ``argmax``) or ``topk`` (top-k, then nucleus over the k candidates
only).

``XTALK_TTS_METRICS=1`` adds rate-limited ``[tts-metric]`` lines.  The service
drives synthesis one frame at a time (``drain(max_steps=1)`` calls ``finish``
once per frame), so a per-call log would emit thousands of useless lines; each
line therefore reports the frames and wall clock *since the previous line*, plus
how many CUDA-event seconds of that slice went to the local transformer and to
the backbone forward.  Summaries sum the lines instead of trusting one of them.
The event numbers measure the wall clock *between* two events, i.e. they also
contain the gaps in which the CPU cannot keep the GPU fed; the executed kernel
time is what the profiler reports (see below).

``XTALK_TTS_PROFILE=<path>`` profiles the first ``XTALK_TTS_PROFILE_FRAMES``
frames (60 by default) of every turn with ``torch.profiler`` (CUDA activities)
and appends the per-kernel table to that path, next to one ``[moss-patch] profile
… device_s=… cpu_s=… top=…`` line that the report parser reads.  The profiler
runs inside the TTS service process, so one turn covers the model *and* the codec
decode; it also slows those frames down, so its own throughput numbers are not
readings - only its device/cpu split is.

The patch never raises at import time: a failure falls back to the upstream code
path and is logged with its traceback.  Only the single-session (batch size 1)
service is supported, which is how the TTS service is configured.
"""

from __future__ import annotations

import importlib.abc
import logging
import os
import sys
import time
import traceback
from typing import Any, Optional

logger = logging.getLogger("xtalk.moss_tts_patch")

#: Module that owns the streaming inference class used by the service.
_TARGET_MODULE = "mossttsrealtime.streaming_mossttsrealtime"

#: Audio frame duration produced by the codec (24000 Hz / downsample_rate 1920).
FRAME_SECONDS = 1920.0 / 24000.0

#: Rows kept per codebook for the repetition penalty; the service uses window 50.
_HISTORY_CAPACITY = 128

#: A metrics line is emitted once the slice reaches this many frames (0.48s of
#: audio) or this many wall seconds, whichever comes first.
_METRIC_MIN_FRAMES = 6
_METRIC_MIN_WALL_SECONDS = 1.0

#: Frames profiled per turn by ``XTALK_TTS_PROFILE``.
_PROFILE_DEFAULT_FRAMES = 60

#: Bound on CUDA-event pairs whose end event has not completed yet.
_PENDING_EVENT_LIMIT = 4096

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


def profile_path() -> str:
    """Return the file that receives ``torch.profiler`` tables, or ``""``."""
    return os.environ.get("XTALK_TTS_PROFILE", "").strip()


def profile_frames() -> int:
    """Return how many frames of each turn are profiled."""
    raw = os.environ.get("XTALK_TTS_PROFILE_FRAMES", "").strip()
    try:
        return max(1, int(raw)) if raw else _PROFILE_DEFAULT_FRAMES
    except ValueError:
        return _PROFILE_DEFAULT_FRAMES


def local_attention_mode() -> str:
    """Return the local-transformer attention backend: ``upstream`` or ``sdpa``."""
    value = _env_value("XTALK_TTS_LOCAL_ATTN", "upstream")
    if value in {"sdpa", "traceable"}:
        return "sdpa"
    return "upstream"


def switch_local_attention(inferencer: Any) -> None:
    """Point the local transformer at sdpa and at the static local cache.

    The flash-attention helper chooses its varlen path from ``position_ids``
    (``transformers.modeling_flash_attention_utils._flash_attention_forward``),
    and the local transformer decodes one query token against a 17-key cache
    without an attention mask, so that branch is both taken and data dependent -
    dynamo refuses it under ``fullgraph=True``.  sdpa is a single traceable
    kernel, and at this size it is also cheaper than the flash-attn wrapper,
    which checks dtypes and rebuilds varlen metadata on every call.

    Parameters
    ----------
    inferencer : Any
        Inference object whose local transformer is configured upstream.
    """
    try:
        inferencer.model.local_transformer.config._attn_implementation = "sdpa"
        # The static local cache is what upstream's own compiled path uses.
        inferencer._use_dynamic_local_cache = False
        # Our switch owns the backend decision, so upstream must not compile too.
        inferencer._should_compile_local_transformer = False
    except Exception as error:  # pragma: no cover - defensive
        logger.warning("[moss-patch] could not switch the local transformer to sdpa: %s", error)


def relax_dynamo_logging() -> None:
    """Let logger calls inside a compiled graph become no-ops instead of errors.

    ``fullgraph=True`` aborts on any call it cannot trace, and transformers calls
    ``logger.warning_once`` inside the flash-attention helper when it has to cast
    inputs back to the model dtype.  Upstream never compiles this path (it is the
    non-flash-attention branch), so it never had to declare those methods.
    """
    try:
        import logging as _logging

        import torch

        methods = {
            _logging.Logger.warning_once,
            _logging.Logger.debug,
            _logging.Logger.info,
            _logging.Logger.warning,
            _logging.Logger.error,
            _logging.Logger.exception,
            _logging.Logger.critical,
            _logging.Logger.log,
        }
        torch._dynamo.config.ignore_logger_methods.update(methods)
        logger.info(
            "[moss-patch] dynamo ignores %d logger methods for compile", len(methods)
        )
    except Exception as error:  # pragma: no cover - defensive
        logger.warning("[moss-patch] could not relax dynamo logger handling: %s", error)


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
    do_sample: bool,
    sample_token: Any,
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
    do_sample : bool
        Upstream sampling switch; ``False`` (or ``temperature == 0``) means argmax.
    sample_token : Callable
        Bound upstream ``sample_token``, used untouched by ``mode="upstream"``.
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
        if mode == "greedy" or not do_sample or temperature == 0:
            token = _sample_greedy(logits).reshape(batch_size, 1)
        elif mode == "topk":
            token = _sample_topk(logits, temperature, top_p, top_k).reshape(batch_size, 1)
        else:
            token = sample_token(
                logits=logits,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                do_sample=do_sample,
            ).reshape(batch_size, 1)
        output_token[:, codebook] = token.reshape(batch_size)
        if codebook == 0:
            local_inputs = None
    return output_token


def _compile_target(capacity: int, repetition_window: int) -> int:
    """Return the frame count after which the sliding window is saturated.

    The compiled loop passes a constant ``history_filled`` (the capacity type of
    the pass is what keeps dynamo from tracing one graph per frame count), so it
    may only take over once the repetition penalty reads exactly the same rows
    the eager path reads: the last ``repetition_window`` frames.

    Parameters
    ----------
    capacity : int
        Rows stored in the sliding window.
    repetition_window : int
        Frames the repetition penalty looks back at; 0 means "the whole history".

    Returns
    -------
    int
        Frames that must already be in the window before compiling pays off.
    """
    if repetition_window > 0:
        return min(capacity, repetition_window)
    return capacity


def _timed_call(pairs: list, function: Any, *args: Any, **kwargs: Any) -> Any:
    """Call ``function`` and append one CUDA-event pair when metrics are on.

    Parameters
    ----------
    pairs : list
        Per-inferencer list of running ``(start, end)`` event pairs.
    function : Callable
        Callable to time.
    *args, **kwargs
        Forwarded to ``function``.

    Returns
    -------
    Any
        Whatever ``function`` returns.
    """
    if not metrics_enabled():
        return function(*args, **kwargs)
    import torch

    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    try:
        return function(*args, **kwargs)
    finally:
        end.record()
        pairs.append((start, end))


def _consume_events(pairs: list) -> float:
    """Sum the completed CUDA-event pairs in seconds, keeping the pending ones."""
    if not pairs:
        return 0.0
    total = 0.0
    pending = []
    for start, end in pairs:
        try:
            if end.query():
                total += start.elapsed_time(end)
            else:
                pending.append((start, end))
        except Exception:  # pragma: no cover - defensive
            continue
    if len(pending) > _PENDING_EVENT_LIMIT:
        pending = pending[-_PENDING_EVENT_LIMIT:]
    pairs[:] = pending
    return total / 1000.0


def _wrap_backbone(inferencer: Any) -> None:
    """Time every backbone forward of the given inference object.

    The service builds a new inference object per turn while the model object
    outlives it, so the event list is stored on the model and every inference
    object points at the same list; otherwise only the first turn's backbone
    seconds would ever be reported.
    """
    try:
        import torch

        model = getattr(inferencer, "model", None)
        if model is None:
            return
        events = getattr(model, "_xt_backbone_events", None)
        if events is None:
            events = []
            model._xt_backbone_events = events
        inferencer._xt_backbone_events = events
        if getattr(model, "_xt_timed", False):
            return
        original_forward = model.forward

        def timed_forward(*args: Any, **kwargs: Any) -> Any:
            """Record one CUDA-event pair around the backbone forward."""
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            try:
                return original_forward(*args, **kwargs)
            finally:
                end.record()
                events.append((start, end))

        model.forward = timed_forward
        model._xt_timed = True
    except Exception as error:  # pragma: no cover - defensive
        logger.warning("[moss-patch] could not time the backbone forward: %s", error)


def _device_seconds(item: Any) -> float:
    """Return one profiler entry's device time in seconds, or ``0.0``."""
    for name in ("self_device_time_total", "self_cuda_time_total"):
        value = getattr(item, name, None)
        if value is not None:
            try:
                return float(value) / 1e6
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _log_profile_summary(profiled: int, events: Any) -> None:
    """Log the totals and the heaviest kernels of one profiled turn.

    The text table is for reading; this line is what the report parser consumes,
    so a throughput report can state where the device time goes without anyone
    re-reading the table by hand.
    """
    try:
        entries = list(events)
        total_device = sum(_device_seconds(item) for item in entries)
        total_cpu = sum(
            float(getattr(item, "self_cpu_time_total", 0.0) or 0.0) for item in entries
        ) / 1e6
        top = sorted(entries, key=_device_seconds, reverse=True)[:3]
        logger.info(
            "[moss-patch] profile frames=%d device_s=%.3f cpu_s=%.3f top=%s",
            profiled,
            total_device,
            total_cpu,
            " | ".join(
                "%s:%.3fs:%d" % (str(item.key)[:60], _device_seconds(item), int(item.count))
                for item in top
            ),
        )
    except Exception as error:  # pragma: no cover - defensive
        logger.warning("[moss-patch] profiler summary failed: %s", error)


def _dump_profile(inferencer: Any, reason: str) -> None:
    """Stop the running profiler and append its kernel table to the target file."""
    profiler = inferencer._xt_profiler
    inferencer._xt_profiler = None
    if profiler is None:
        return
    profiled = inferencer._xt_profile_frames
    try:
        profiler.stop()
        events = profiler.key_averages()
        table = events.table(sort_by="cuda_time_total", row_limit=25)
    except Exception as error:  # pragma: no cover - defensive
        logger.warning("[moss-patch] profiler stop failed: %s", error)
        return
    _log_profile_summary(profiled, events)
    path = profile_path()
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(
                f"\n===== turn={inferencer._xt_turns} reason={reason} "
                f"profiled_frames={profiled} =====\n{table}\n"
            )
        logger.info(
            "[moss-patch] profiler table written to %s (frames=%d)", path, profiled
        )
    except Exception as error:  # pragma: no cover - defensive
        logger.warning("[moss-patch] profiler dump failed: %s", error)


def _maybe_profile_frame(inferencer: Any) -> None:
    """Start or stop the CUDA profiler around the first frames of a turn."""
    if not profile_path() or inferencer._xt_profile_disabled:
        return
    limit = profile_frames()
    if inferencer._xt_profiler is None and inferencer._xt_turn_frames == 1:
        try:
            import torch

            profiler = torch.profiler.profile(
                activities=[torch.profiler.ProfilerActivity.CUDA]
            )
            profiler.start()
        except Exception as error:  # pragma: no cover - defensive
            logger.warning("[moss-patch] profiler start failed: %s", error)
            inferencer._xt_profile_disabled = True
            return
        inferencer._xt_profiler = profiler
        inferencer._xt_profile_frames = 0
    if inferencer._xt_profiler is None:
        return
    inferencer._xt_profile_frames += 1
    if inferencer._xt_profile_frames >= limit:
        _dump_profile(inferencer, "frames")


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
    if local_compile_mode() != "off":
        relax_dynamo_logging()
    logger.info(
        "[moss-patch] armed local_compile=%s sample=%s metrics=%s profile=%s",
        local_compile_mode(),
        sample_mode(),
        metrics_enabled(),
        profile_path() or "-",
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
    inferencer._xt_runner_used = False
    inferencer._xt_turn_frames = 0
    inferencer._xt_turns = 0
    inferencer._xt_local_events = []
    inferencer._xt_backbone_events = []
    inferencer._xt_profiler = None
    inferencer._xt_profile_frames = 0
    inferencer._xt_profile_disabled = False
    inferencer._xt_metrics = {"frames": 0, "started": None, "finished": None, "lines": 0}
    if local_attention_mode() == "sdpa":
        switch_local_attention(inferencer)
    if metrics_enabled():
        _wrap_backbone(inferencer)
    logger.info(
        "[moss-patch] inference ready channels=%d capacity=%d compile=%s sample=%s attention=%s",
        inferencer._xt_channels,
        inferencer._xt_capacity,
        local_compile_mode(),
        sample_mode(),
        local_attention_mode(),
    )


def _record_frame(inferencer: Any) -> None:
    """Advance the frame counters of the current metrics slice and turn."""
    metrics = getattr(inferencer, _METRICS_ATTR, None)
    if metrics is None:
        return
    if metrics["started"] is None:
        metrics["started"] = time.perf_counter()
    metrics["frames"] += 1
    metrics["finished"] = time.perf_counter()
    inferencer._xt_turn_frames += 1
    if metrics_enabled():
        _maybe_profile_frame(inferencer)


def _log_metrics(inferencer: Any, reason: str, force: bool = False) -> None:
    """Log one rate-limited metrics line for the synthesis since the last line.

    Parameters
    ----------
    inferencer : Any
        Inference object holding the counters, or ``None`` when the session was
        called without one.
    reason : str
        Caller that triggered the line (``finish``, ``drain`` or ``end_text``).
    force : bool
        Emit even for a slice below the size threshold (turn boundaries).
    """
    metrics = getattr(inferencer, _METRICS_ATTR, None)
    if metrics is None or not metrics_enabled():
        return
    frames = metrics["frames"]
    if not frames or metrics["started"] is None:
        return
    now = time.perf_counter()
    wall = max(1e-9, now - metrics["started"])
    if not force and frames < _METRIC_MIN_FRAMES and wall < _METRIC_MIN_WALL_SECONDS:
        return
    audio = frames * FRAME_SECONDS
    local_seconds = _consume_events(inferencer._xt_local_events)
    backbone_seconds = _consume_events(inferencer._xt_backbone_events)
    metrics["lines"] += 1
    metrics["frames"] = 0
    metrics["started"] = None
    metrics["finished"] = None
    logger.info(
        "[tts-metric] reason=%s line=%d frames=%d audio_s=%.2f wall_s=%.2f rtf=%.2f"
        " local_s=%.2f backbone_s=%.2f local_pct=%.0f",
        reason,
        metrics["lines"],
        frames,
        audio,
        wall,
        audio / wall,
        local_seconds,
        backbone_seconds,
        100.0 * local_seconds / wall,
    )


def _reset_metrics(inferencer: Any) -> None:
    """Start a fresh turn: reset the slice counters and close an open profiler."""
    metrics = getattr(inferencer, _METRICS_ATTR, None)
    if metrics is not None:
        metrics["frames"] = 0
        metrics["started"] = None
        metrics["finished"] = None
    if getattr(inferencer, "_xt_profiler", None) is not None:
        _dump_profile(inferencer, "turn_end")
    inferencer._xt_turn_frames = 0
    inferencer._xt_turns += 1


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
        logger.warning(
            "[moss-patch] torch.compile failed mode=%s: %s\n%s",
            mode,
            error,
            traceback.format_exc(),
        )
    _COMPILED[mode] = compiled
    return compiled


def _ensure_runner(inferencer: Any, warmup: dict) -> Optional[Any]:
    """Return this session's compiled local loop, warming it up once.

    Parameters
    ----------
    inferencer : Any
        Inference object owning the per-session runner state.
    warmup : dict
        Sampling context of the first real frame; the warmup reuses its scalars
        and its bound ``sample_token`` so the compiled graph matches the frames
        that follow.
    """
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
        _warmup_runner(inferencer, warmup)
    except Exception as error:  # pragma: no cover - defensive
        logger.warning(
            "[moss-patch] compiled warmup failed, falling back to eager: %s\n%s",
            error,
            traceback.format_exc(),
        )
        inferencer._xt_runner = None
    return inferencer._xt_runner


def _warmup_runner(inferencer: Any, warmup: dict) -> None:
    """Capture one steady-state frame so the first real frame is not delayed.

    The arguments mirror a real frame: same hidden state, same sampling scalars,
    same dtype and the same bound ``sample_token``.  Only the sliding window is a
    fresh zero tensor, which is discarded with the returned tokens.
    """
    import torch

    batch_size = warmup["hidden_states"].shape[0]
    device = warmup["hidden_states"].device
    history = torch.zeros(
        (batch_size, inferencer._xt_capacity, inferencer._xt_channels),
        dtype=torch.long,
        device=device,
    )
    cache_positions = torch.zeros(1, dtype=torch.long, device=device)
    output = torch.empty(batch_size, inferencer._xt_channels, dtype=torch.long, device=device)
    started = time.perf_counter()
    inferencer._xt_runner(
        inferencer.model,
        inferencer._build_local_past_key_values(),
        cache_positions,
        warmup["hidden_states"],
        output,
        history,
        inferencer._xt_capacity,
        warmup["penalty"],
        warmup["window"],
        warmup["temperature"],
        warmup["top_p"],
        warmup["top_k"],
        warmup["do_sample"],
        warmup["sample_token"],
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
        penalty = float(repetition_penalty or 0.0)
        window = int(repetition_window or 0)
        # The repetition penalty reads the last ``repetition_window`` frames, so
        # the compiled loop can be entered as soon as that many frames are known:
        # from there on every compiled argument is constant (one graph per
        # session), while the first frames of a turn run upstream-eager with
        # identical math.
        target = _compile_target(self._xt_capacity, window)
        penalty_active = bool(penalty) and penalty != 1.0
        runner = _ensure_runner(
            self,
            {
                "hidden_states": hidden_states,
                "penalty": penalty,
                "window": window,
                "temperature": float(temperature),
                "top_p": float(top_p),
                "top_k": int(top_k),
                "do_sample": bool(do_sample),
                "sample_token": self.sample_token,
            },
        )
        use_compiled = (
            runner is not None
            and self._xt_history is not None
            and (not penalty_active or self._xt_history_filled >= target)
        )
        if not use_compiled:
            return _timed_call(
                self._xt_local_events,
                original_generate,
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
        if not self._xt_runner_used:
            self._xt_runner_used = True
            logger.info(
                "[moss-patch] compiled path engaged frame=%d filled=%d target=%d mode=%s",
                self._xt_turn_frames,
                self._xt_history_filled,
                target,
                local_compile_mode(),
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
        return _timed_call(
            self._xt_local_events,
            runner,
            self.model,
            self._build_local_past_key_values(),
            self._xt_cache_positions,
            hidden_states,
            output_token,
            self._xt_history,
            self._xt_capacity,
            penalty,
            window,
            float(temperature),
            float(top_p),
            int(top_k),
            bool(do_sample),
            self.sample_token,
            sample_mode(),
        )

    def patched_prefill(self, *args, **kwargs):
        """Run upstream prefill, then start a fresh turn with its first frame."""
        # Clear the window *before* the upstream call: prefill generates the first
        # frame of the new turn through this same patched method, and it must not
        # see the window of the previous turn.
        self._xt_history = None
        self._xt_history_filled = 0
        _reset_metrics(self)
        result = original_prefill(self, *args, **kwargs)
        _push_history(self, result)
        return result

    def patched_step(self, *args, **kwargs):
        """Run upstream step and extend the sliding window with the new frame."""
        result = original_step(self, *args, **kwargs)
        _push_history(self, result)
        return result

    def patched_finish(self, *args, **kwargs):
        """Run upstream finish and report the metrics slice that just closed."""
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
            """Run upstream end_text, close the metrics slice and any profiler."""
            result = original_end_text(self, *args, **kwargs)
            inferencer = getattr(self, "inferencer", None)
            _log_metrics(inferencer, "end_text", force=True)
            if inferencer is not None and inferencer._xt_profiler is not None:
                _dump_profile(inferencer, "end_text")
            return result

        def patched_drain(self, *args, **kwargs):
            """Run upstream drain and report the metrics slice it closed."""
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
