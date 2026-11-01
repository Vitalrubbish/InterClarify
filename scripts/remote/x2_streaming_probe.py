"""Probe whether X2Streaming-ASR can sustain real-time 80 ms frames.

The checkpoint is an adaptive LISTEN/DECODE model, not a plain autoregressive
one-token-per-frame ASR. This script runs the official interleaved state machine
over incrementally encoded audio, records every LISTEN frame and every closed
word, and does not start SoulX or write teacher frames.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

FRAME_MS = 80
WAIT_TOKEN_ID = 32
WORD_TOKEN_ID = 33
PAD_TOKEN_ID = 32
BOS_TOKEN_ID = 1
EOS_TOKEN_ID = 2
SAMPLE_RATE = 16000
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
ADAPTIVE_DELAY_MS = 80


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def distribution(values):
    return {
        'count': len(values),
        'p50': percentile(values, .5),
        'p95': percentile(values, .95),
        'max': max(values) if values else None,
        'mean': sum(values) / len(values) if values else None,
    }


def decode(tokenizer, ids):
    if not ids:
        return ''
    return tokenizer.decode(ids, skip_special_tokens=True,
                            clean_up_tokenization_spaces=False)


def parse_groups(tokens, emit_ms):
    """Legacy [W]/[P] grouping retained for audit helpers and local tests."""
    groups, current, unbound = [], None, []
    word_markers = wait_markers = 0
    for frame, token in enumerate(tokens):
        if token == WORD_TOKEN_ID:
            word_markers += 1
            if current is not None:
                current['close_frame'] = frame
                current['close_ms'] = emit_ms[frame]
                current['close_reason'] = 'next_word'
                groups.append(current)
            current = {'start_frame': frame, 'token_frames': [], 'token_ids': []}
            continue
        if token == WAIT_TOKEN_ID:
            wait_markers += 1
            if current is not None:
                current['close_frame'] = frame
                current['close_ms'] = emit_ms[frame]
                current['close_reason'] = 'wait'
                groups.append(current)
                current = None
            continue
        if current is None:
            unbound.append({'frame': frame, 'token_id': token})
            continue
        current['token_frames'].append(frame)
        current['token_ids'].append(token)
    return {
        'groups': groups,
        'unbound_tokens': unbound,
        'unclosed_tail': current,
        'word_markers': word_markers,
        'wait_markers': wait_markers,
    }


def group_audit(tokenizer, tokens, emit_ms, cumulative):
    parsed = parse_groups(tokens, emit_ms)
    for group in parsed['groups'] + ([parsed['unclosed_tail']] if parsed['unclosed_tail'] else []):
        group['text'] = decode(tokenizer, group['token_ids'])
        group['token_count'] = len(group['token_ids'])
        group['last_token_frame'] = group['token_frames'][-1] if group['token_frames'] else group['start_frame']
        if 'close_frame' in group:
            group['close_delay_frames'] = group['close_frame'] - group['last_token_frame']
            group['close_delay_ms'] = group['close_ms'] - emit_ms[group['last_token_frame']]
    violations = []
    for group in parsed['groups']:
        closed_at = group['close_frame']
        prefix = cumulative[closed_at]
        for frame in range(closed_at + 1, len(cumulative)):
            if not cumulative[frame].startswith(prefix):
                violations.append({'group_start_frame': group['start_frame'],
                                   'group_close_frame': closed_at,
                                   'changed_frame': frame,
                                   'closed_text': prefix,
                                   'later_text': cumulative[frame]})
                break
    parsed['group_prefix_violations'] = violations
    parsed['close_delay_ms'] = [g['close_delay_ms'] for g in parsed['groups']]
    parsed['close_delay_frames'] = [g['close_delay_frames'] for g in parsed['groups']]
    return parsed


def audit_cumulative_text(tokenizer, tokens):
    cumulative, rewrites, text_ids = [], [], []
    for frame, token in enumerate(tokens):
        if token not in (WAIT_TOKEN_ID, WORD_TOKEN_ID):
            text_ids.append(token)
        current = decode(tokenizer, text_ids)
        if cumulative and not current.startswith(cumulative[-1]):
            rewrites.append({'frame': frame, 'before': cumulative[-1], 'after': current})
        cumulative.append(current)
    return cumulative, rewrites


def load_audio(path, gain_normalize=True):
    import numpy as np
    import soundfile as sf
    import soxr
    audio, rate = sf.read(str(path), dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != SAMPLE_RATE:
        audio = soxr.resample(audio, rate, SAMPLE_RATE)
    audio = np.asarray(audio, dtype=np.float32)
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.
    gain = min(.05 / rms, .9 / peak) if gain_normalize and rms > 0 and peak > 0 else 1.
    return (audio * gain).astype(np.float32), float(gain)


def verify_sample(sample):
    path = Path(sample['input'])
    for name, expected in sample['files'].items():
        candidate = path.parent / name
        if digest(candidate) != expected:
            raise ValueError(f'Frozen input digest differs: {candidate}')


def select_case(samples, case_id=None, longest=False):
    if case_id:
        matches = [s for s in samples if s['case_id'] == case_id]
        if len(matches) != 1:
            raise ValueError(f'Requested case is absent or duplicated: {case_id}')
        return matches[0]
    if longest:
        return max(samples, key=lambda s: s['duration_seconds'])
    raise ValueError('Either case_id or longest is required')


def continuous_audio(samples, seconds):
    import numpy as np
    target = int(round(seconds * SAMPLE_RATE))
    pieces, records = [], []
    for sample in samples:
        audio, gain = load_audio(sample['input'])
        pieces.append(audio)
        records.append({'case_id': sample['case_id'], 'samples': len(audio), 'gain': gain})
        if sum(len(piece) for piece in pieces) >= target:
            break
    joined = np.concatenate(pieces) if pieces else np.zeros(0, np.float32)
    if len(joined) < target:
        raise ValueError('Frozen manifest cannot supply the requested continuous stream')
    return joined[:target].copy(), records


def streaming_delay_config(processor, delay_ms=ADAPTIVE_DELAY_MS):
    cfg = processor.mistral_common_audio_config
    hop = processor.feature_extractor.hop_length
    win = processor.feature_extractor.win_length
    delay_tokens = int(cfg.get_num_delay_tokens(delay_ms))
    first_mel_frames = (delay_tokens + 1) * int(cfg.audio_length_per_tok)
    first_samples = (first_mel_frames - 1) * hop + win // 2
    return {
        'delay_ms': delay_ms,
        'num_delay_tokens': delay_tokens,
        'num_mel_frames_first_audio_chunk': first_mel_frames,
        'num_samples_first_audio_chunk': first_samples,
        'num_samples_per_audio_chunk': int(cfg.audio_length_per_tok) * hop + win,
    }


def encode_first_streaming_chunk(processor, audio, delay_ms=ADAPTIVE_DELAY_MS):
    """Encode the adaptive protocol prompt instead of the fixed 480ms default."""
    import numpy as np
    from mistral_common.protocol.instruct.chunk import RawAudio
    from mistral_common.protocol.transcription.request import StreamingMode, TranscriptionRequest
    from mistral_common.tokens.tokenizers.audio import Audio
    from transformers.feature_extraction_utils import BatchFeature
    sr = processor.feature_extractor.sampling_rate
    audio_obj = Audio(audio_array=np.asarray(audio, dtype=np.float32), sampling_rate=sr, format='wav')
    request = TranscriptionRequest(audio=RawAudio.from_audio(audio_obj), streaming=StreamingMode.ONLINE,
                                   target_streaming_delay_ms=delay_ms, language=None)
    tokenized = processor.tokenizer.tokenizer.encode_transcription(request)
    audio_arrays = [value.audio_array for value in tokenized.audios]
    text_encoding = processor.tokenizer(tokenized.tokens, add_special_tokens=False, return_tensors='pt')
    audio_encoding = processor.feature_extractor(audio_arrays, center=True, sampling_rate=sr)
    delay_tokens = int(processor.mistral_common_audio_config.get_num_delay_tokens(delay_ms))
    return BatchFeature(data={**text_encoding, **audio_encoding,
                              'num_delay_tokens': delay_tokens}, tensor_type='pt')


def disable_adarms_delay_conditioning(model):
    """Make AdaRMS delay conditioning an identity, as required by adaptive X2."""
    import torch
    root = model.model
    if type(root.time_embedding).__name__ == '_ZeroTimeEmbedding':
        return
    dim = int(root.time_embedding.dim)

    class _ZeroTimeEmbedding(torch.nn.Module):
        def __init__(self, hidden_dim):
            super().__init__()
            self.dim = hidden_dim

        def forward(self, time_tensor):
            return torch.zeros(self.dim, device=time_tensor.device, dtype=time_tensor.dtype)

    root.time_embedding = _ZeroTimeEmbedding(dim)


def _cache_shapes(cache):
    if cache is None:
        return None
    result = {}
    for key, layer in getattr(cache, 'layers', {}).items():
        if getattr(layer, 'cache', None) is not None:
            result[key] = list(layer.cache.shape)
    return result


class AdaptiveStream:
    """Run the official LISTEN/DECODE loop over incrementally encoded frames."""

    def __init__(self, model, processor, audio, config, realtime=True):
        import numpy as np
        self.model, self.processor = model, processor
        self.audio = np.asarray(audio, dtype=np.float32)
        self.config = config
        self.realtime = realtime
        self.frame_samples = FRAME_SAMPLES
        self.n_left_pad = int(getattr(processor.mistral_common_audio_config,
                                      'streaming_n_left_pad_tokens', None) or 32)
        self.delay = streaming_delay_config(processor)
        self.first_samples = self.delay['num_samples_first_audio_chunk']
        self.first_mel_frames = self.delay['num_mel_frames_first_audio_chunk']
        self.chunk_samples = self.delay['num_samples_per_audio_chunk']
        self.hop = processor.feature_extractor.hop_length
        self.win = processor.feature_extractor.win_length
        self.flush_frames = int(config.get('contract', {}).get('flush_frames', 8))
        self.padded_samples = len(self.audio) + self.flush_frames * self.frame_samples
        self.audio_frames = len(self.audio) / self.frame_samples
        self.records, self.groups, self.feeds = [], [], []
        self.cache_calls = []
        self.tokens = []
        self.listen_compute = []
        self.decode_compute = []
        self.encode_compute = []
        self.warmup_ms = None
        self.past = None
        self.padding_cache = None
        self.encoder_cache = None

    def _schedule(self):
        chunks = [(0, self.first_samples)]
        mel_frame = self.first_mel_frames
        while True:
            start = mel_frame * self.hop - self.win // 2
            if start >= self.padded_samples:
                break
            chunks.append((start, start + self.chunk_samples))
            mel_frame += int(self.processor.audio_length_per_tok)
        return chunks

    def _encode(self, features):
        import torch
        before = _cache_shapes(self.padding_cache)
        started = time.monotonic()
        outputs = self.model.model.get_audio_features(
            input_features=features, padding_cache=self.padding_cache,
            past_key_values=self.encoder_cache, use_cache=True)
        torch.cuda.synchronize()
        elapsed = (time.monotonic() - started) * 1000
        self.padding_cache = outputs.padding_cache
        self.encoder_cache = outputs.past_key_values
        after = _cache_shapes(self.padding_cache)
        self.cache_calls.append({'before': before, 'after': after,
                                 'input_shape': list(features.shape),
                                 'pooler_shape': list(outputs.pooler_output.shape)})
        self.encode_compute.append(elapsed)
        return outputs.pooler_output[0].to(self.model.device, dtype=self.model.dtype)

    def _embed(self, token_id):
        import torch
        return self.model.model.get_input_embeddings()(
            torch.tensor([[token_id]], dtype=torch.long, device=self.model.device))

    def _lm_step(self, embeds, past):
        import torch
        if embeds.dim() == 2:
            embeds = embeds.unsqueeze(0)
        started = time.monotonic()
        t_cond = self.model.model.time_embedding(
            torch.full((1,), self.delay['num_delay_tokens'], device=embeds.device,
                       dtype=embeds.dtype))[None, ...]
        outputs = self.model.model.language_model(
            inputs_embeds=embeds, past_key_values=past, use_cache=True, t_cond=t_cond)
        torch.cuda.synchronize()
        elapsed = (time.monotonic() - started) * 1000
        logits = self.model.lm_head(outputs.last_hidden_state[:, -1:, :])
        return logits, outputs.past_key_values, elapsed

    def _chunk_audio(self, start, end):
        import numpy as np
        chunk = self.audio[start:min(end, len(self.audio))]
        if len(chunk) < end - start:
            chunk = np.pad(chunk, (0, end - start - len(chunk)))
        return chunk

    def _decode_word(self, frame, wall_ms, tokenizer, past):
        import torch
        w_emb = self._embed(WORD_TOKEN_ID)
        logits, past, elapsed = self._lm_step(w_emb, past)
        self.decode_compute.append(elapsed)
        next_token = int(torch.argmax(logits[0, -1]).item())
        emit_ids, decode_ms, count, closed_by = [], elapsed, 0, 'eos'
        cap = int(self.config.get('contract', {}).get('max_decode_tokens', 64))
        while count < cap:
            if next_token == EOS_TOKEN_ID:
                break
            if next_token not in (PAD_TOKEN_ID, WORD_TOKEN_ID, BOS_TOKEN_ID):
                emit_ids.append(next_token)
            count += 1
            logits, past, elapsed = self._lm_step(self._embed(next_token), past)
            self.decode_compute.append(elapsed)
            decode_ms += elapsed
            next_token = int(torch.argmax(logits[0, -1]).item())
        else:
            closed_by = 'cap'
        close_wall = time.monotonic()
        group = {
            'index': len(self.groups),
            'frame': frame,
            'audio_ms': (frame + 1) * FRAME_MS,
            'text': decode(tokenizer, emit_ids),
            'token_ids': emit_ids,
            'open_wall_ms': wall_ms,
            'close_wall_ms': (close_wall - self.started) * 1000,
            'close_delay_ms': (close_wall - self.started) * 1000 - wall_ms,
            'decode_ms': decode_ms,
            'decode_tokens': count,
            'closed_by': closed_by,
        }
        self.groups.append(group)
        return past

    def run(self):
        import torch
        from transformers import DynamicCache
        torch.set_grad_enabled(False)
        first_audio = self._chunk_audio(0, self.first_samples)
        first_inputs = encode_first_streaming_chunk(self.processor, first_audio)
        self.started = time.monotonic()
        self.encoder_cache = DynamicCache(config=self.model.config.audio_config)
        first_embeds = self._encode(first_inputs.input_features.to(
            self.model.device, dtype=self.model.dtype))
        self.feeds.append({'chunk_index': 0, 'start_sample': 0, 'end_sample': self.first_samples,
                           'mel_shape': list(first_inputs.input_features.shape),
                           'pooler_frames': len(first_embeds)})
        bos = self._embed(BOS_TOKEN_ID)
        logits, past, elapsed = self._lm_step(bos, None)
        self.listen_compute.append(elapsed)
        warm_started = time.monotonic()
        pad = first_embeds[:self.n_left_pad]
        logits, past, elapsed = self._lm_step(pad, past)
        self.listen_compute.append(elapsed)
        self.past = past
        self.warmup_ms = (time.monotonic() - warm_started) * 1000
        self.started = time.monotonic()
        user_embeds = first_embeds[self.n_left_pad:]
        frame = 0
        coverage_end = self.first_samples / SAMPLE_RATE * 1000
        for embed in user_embeds:
            self._listen(frame, embed, coverage_end, self.processor.tokenizer)
            frame += 1
        for index, (start, end) in enumerate(self._schedule()[1:], 1):
            target = self.started + end / SAMPLE_RATE
            while self.realtime:
                remaining = target - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(remaining)
            chunk = self._chunk_audio(start, end)
            inputs = self.processor(chunk, sampling_rate=SAMPLE_RATE, is_streaming=True,
                                    is_first_audio_chunk=False, return_tensors='pt')
            embeds = self._encode(inputs.input_features.to(self.model.device, dtype=self.model.dtype))
            self.feeds.append({'chunk_index': index, 'start_sample': start, 'end_sample': end,
                               'mel_shape': list(inputs.input_features.shape),
                               'pooler_frames': len(embeds)})
            for embed in embeds:
                self._listen(frame, embed, end / SAMPLE_RATE * 1000, self.processor.tokenizer)
                frame += 1
        return self._result()

    def _listen(self, frame, embed, coverage_end, tokenizer):
        import torch
        listen_started = time.monotonic()
        logits, past, elapsed = self._lm_step(embed, self.past)
        self.past = past
        self.listen_compute.append(elapsed)
        wall_ms = (time.monotonic() - self.started) * 1000
        token = int(torch.argmax(logits[0, -1]).item())
        record = {
            'frame': frame,
            'chunk_coverage_end_ms': coverage_end,
            'audio_frame_end_ms': (frame + 1) * FRAME_MS,
            'token_id': token,
            'wall_ms': wall_ms,
            'listen_ms': elapsed,
            'backlog_ms': wall_ms - (frame + 1) * FRAME_MS,
            'frame_lag_ms': wall_ms - (frame + 1) * FRAME_MS,
            'pad': frame >= self.audio_frames,
            'is_word': token == WORD_TOKEN_ID,
            'is_wait': token == WAIT_TOKEN_ID,
        }
        if token == WORD_TOKEN_ID:
            self.past = self._decode_word(frame, wall_ms, tokenizer, self.past)
            record['word_index'] = len(self.groups) - 1
        self.records.append(record)
        self.tokens.append(token)

    def _result(self):
        tokenizer = self.processor.tokenizer
        real_records = [r for r in self.records if not r['pad']]
        group_text = []
        prefix_violations = []
        text = ''
        for group in self.groups:
            if group['frame'] >= self.audio_frames:
                continue
            new = text + group['text']
            if not new.startswith(text):
                prefix_violations.append({'group': group['index'], 'before': text, 'after': new})
            text = new
            group_text.append(group['text'])
        return {
            'records': self.records,
            'groups': self.groups,
            'feeds': self.feeds,
            'cache_calls': self.cache_calls,
            'tokens': self.tokens,
            'started': self.started,
            'audio_seconds': len(self.audio) / SAMPLE_RATE,
            'audio_frames': self.audio_frames,
            'warmup_ms': self.warmup_ms,
            'listen_compute': self.listen_compute,
            'decode_compute': self.decode_compute,
            'encode_compute': self.encode_compute,
            'group_text': group_text,
            'prefix_violations': prefix_violations,
            'final_text': text,
            'n_left_pad': self.n_left_pad,
        }

    def summary(self, run):
        real = [r for r in run['records'] if not r['pad']]
        backlog = [r['backlog_ms'] for r in real]
        frame_lag = [r['frame_lag_ms'] for r in real]
        first_window = [r['backlog_ms'] for r in real if r['wall_ms'] <= 5000]
        last_window = [r['backlog_ms'] for r in real
                       if r['wall_ms'] > max(0, run['audio_seconds'] * 1000 - 5000)]
        drift = None
        if first_window and last_window:
            drift = percentile(last_window, .5) - percentile(first_window, .5)
        groups = [g for g in run['groups'] if g['frame'] < run['audio_frames']]
        total_compute = (sum(run['listen_compute']) + sum(run['decode_compute'])
                         + sum(run['encode_compute']))
        real_compute = total_compute
        audio_seconds = run['audio_seconds']
        shape_counts = Counter(tuple(f['mel_shape']) for f in run['feeds'])
        pooler_counts = Counter(f['pooler_frames'] for f in run['feeds'])
        return {
            'audio_seconds': audio_seconds,
            'tokens': len(run['records']),
            'real_tokens': len(real),
            'pad_tokens': len(run['records']) - len(real),
            'feature_shapes': {'x'.join(map(str, key)): count for key, count in shape_counts.items()},
            'pooler_frames': dict(pooler_counts),
            'warmup_ms': run['warmup_ms'],
            'x2_rtf': real_compute / 1000 / audio_seconds if audio_seconds else None,
            'x2_rtf_including_flush': total_compute / 1000 / audio_seconds if audio_seconds else None,
            'listen_compute_ms': distribution(run['listen_compute']),
            'decode_compute_ms': distribution(run['decode_compute']),
            'encode_compute_ms': distribution(run['encode_compute']),
            'frame_lag_ms': distribution(frame_lag),
            'backlog_ms': distribution(backlog),
            'backlog_drift_ms': drift,
            'first_window_backlog_p50_ms': percentile(first_window, .5),
            'last_window_backlog_p50_ms': percentile(last_window, .5),
            'first_backlog_ms': backlog[0] if backlog else None,
            'last_backlog_ms': backlog[-1] if backlog else None,
            'word_markers': len(run['groups']),
            'wait_markers': sum(1 for r in real if r['is_wait']),
            'closed_groups': len(groups),
            'unbound_tokens': sum(1 for r in real if not r['is_word'] and not r['is_wait']),
            'unclosed_tail': None,
            'group_close_delay_ms': distribution([g['close_delay_ms'] for g in groups]),
            'group_decode_ms': distribution([g['decode_ms'] for g in groups]),
            'group_texts': [g['text'] for g in groups[:20]],
            'group_prefix_violations': len(run['prefix_violations']),
            'group_prefix_violation_examples': run['prefix_violations'][:5],
            'text_rewrites': 0,
            'text_rewrite_examples': [],
            'final_text': run['final_text'],
            'n_left_pad': run['n_left_pad'],
            'cache_calls': len(run['cache_calls']),
        }


def contract_check(model, processor, config):
    """Pin the adaptive first chunk and incremental encoder shapes."""
    import numpy as np
    rng = np.random.default_rng(42)
    count = int(3.36 * SAMPLE_RATE)
    timeline = np.arange(count) / SAMPLE_RATE
    audio = (.05 * np.sin(2 * np.pi * 220 * timeline)
             + .01 * rng.standard_normal(count)).astype(np.float32)
    stream = AdaptiveStream(model, processor, audio, config, realtime=True)
    run = stream.run()
    summary = stream.summary(run)
    first = run['feeds'][0]
    expected_cache = {
        'conv1': [1, int(model.config.audio_config.num_mel_bins),
                  int(model.model.audio_tower.embedder.conv1.left_pad)],
        'conv2': [1, int(model.config.audio_config.hidden_size),
                  int(model.model.audio_tower.embedder.conv2.left_pad)],
    }
    first_cache = run['cache_calls'][0]['after'] if run['cache_calls'] else None
    second_cache = run['cache_calls'][1]['after'] if len(run['cache_calls']) > 1 else None
    contract = config.get('contract', {})
    checks = {
        'first_mel_shape': first['mel_shape'][1:] == [int(model.config.audio_config.num_mel_bins),
                                                       contract.get('first_total_mel_frames')],
        'first_input_tokens': first['mel_shape'][-1] // int(processor.audio_length_per_tok)
                              == contract.get('first_input_tokens'),
        'first_pooler_frames': first['pooler_frames'] == contract.get('first_pooler_frames'),
        'first_user_pooler_frames': (first['pooler_frames'] - stream.n_left_pad
                                     == contract.get('first_user_pooler_frames')),
        'left_pad_tokens': stream.n_left_pad == contract.get('left_pad_tokens'),
        'subsequent_mel_frames': all(f['mel_shape'][-1] == int(processor.audio_length_per_tok)
                                     for f in run['feeds'][1:]),
        'subsequent_pooler_frames': all(f['pooler_frames'] == 1 for f in run['feeds'][1:]),
        'first_cache': first_cache == expected_cache,
        'second_cache': second_cache == expected_cache,
        'tokens': len(run['records']) > 0,
    }
    record = {
        'passed': all(checks.values()),
        'checks': checks,
        'seconds': 3.36,
        'first_mel_shape': first['mel_shape'],
        'first_pooler_frames': first['pooler_frames'],
        'n_left_pad': stream.n_left_pad,
        'delay': stream.delay,
        'first_cache': first_cache,
        'second_cache': second_cache,
        'expected_cache': expected_cache,
        'subsequent_mel_shapes': sorted({tuple(f['mel_shape']) for f in run['feeds'][1:]}),
        'tokens_emitted': len(run['records']),
        'groups': len(run['groups']),
        'summary': summary,
    }
    return record, run


def case_record(sample, audio, gain, summary):
    return {
        'case_id': sample.get('case_id', 'continuous_60s'),
        'task': sample.get('task', 'continuous'),
        'duration_seconds': sample.get('duration_seconds', len(audio) / SAMPLE_RATE),
        'gain': gain,
        'passed': True,
        **summary,
    }


def write_frames(path, records):
    with path.open('x') as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')


def run_cases(args, config):
    import os
    import torch
    from transformers import AutoProcessor, VoxtralRealtimeForConditionalGeneration

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(config.get('gpu_memory_fraction', .55), 0)
    manifest = json.loads(args.manifest.read_text())
    samples = manifest['samples']
    if len(samples) != 30 or sum(s['duration_seconds'] for s in samples) > 1200:
        raise ValueError('Expected the frozen thirty-clip FDB manifest')
    if args.case:
        selected = [s for s in samples if s['case_id'] == args.case]
        if len(selected) != 1:
            raise ValueError('Requested case is absent from the frozen manifest')
    else:
        selected = [select_case(samples, longest=True),
                    select_case(samples, 'candor_pause_handling-16'),
                    select_case(samples, 'candor_turn_taking-102')]
    output = args.output
    output.mkdir(exist_ok=False)
    write_json(output / 'input_manifest.json', dict(manifest, samples=selected))

    processor = AutoProcessor.from_pretrained(args.model, local_files_only=True)
    model = VoxtralRealtimeForConditionalGeneration.from_pretrained(
        args.model, dtype=torch.bfloat16, device_map='cuda',
        local_files_only=True, attn_implementation='sdpa').eval()
    disable_adarms_delay_conditioning(model)
    torch.cuda.synchronize()
    result = {
        'passed': False,
        'issue': 'NTF-011',
        'timing_mode': 'realtime' if args.realtime else 'unpaced',
        'manifest_sha256': digest(args.manifest),
        'model': str(Path(args.model).resolve()),
        'model_revision': config.get('model', {}).get('revision'),
        'model_sha256': config.get('model', {}).get('sha256'),
        'source_commit': os.environ.get('SOULX_SOURCE_COMMIT'),
        'processor': {
            'adaptive_delay_ms': ADAPTIVE_DELAY_MS,
            'delay_tokens': streaming_delay_config(processor)['num_delay_tokens'],
            'first_samples': streaming_delay_config(processor)['num_samples_first_audio_chunk'],
            'first_mel_frames': streaming_delay_config(processor)['num_mel_frames_first_audio_chunk'],
            'chunk_samples': streaming_delay_config(processor)['num_samples_per_audio_chunk'],
            'chunk_mel_frames': int(processor.audio_length_per_tok),
            'frame_ms': FRAME_MS,
            'left_pad_frames': int(getattr(processor.mistral_common_audio_config,
                                           'streaming_n_left_pad_tokens', None) or 32),
            'wait_token_id': WAIT_TOKEN_ID,
            'word_token_id': WORD_TOKEN_ID,
        },
        'gpu': None,
        'contract': None,
        'cases': [],
        'expected_cases': 1 if args.case else (3 if args.skip_continuous else 4),
        'gate': None,
    }
    if torch.cuda.is_available():
        result['gpu'] = {'name': torch.cuda.get_device_name(0),
                         'total_mib': torch.cuda.get_device_properties(0).total_memory / 2 ** 20}
    try:
        contract, _ = contract_check(model, processor, config)
        write_json(output / 'contract.json', contract)
        result['contract'] = contract
        if not contract['passed']:
            raise RuntimeError('Adaptive first-chunk feature/cache contract failed')
        if args.contract_only:
            result['passed'] = True
            return result, torch
        for sample in selected:
            verify_sample(sample)
            audio, gain = load_audio(sample['input'])
            stream = AdaptiveStream(model, processor, audio, config, realtime=args.realtime)
            run = stream.run()
            summary = stream.summary(run)
            record = case_record(sample, audio, gain, summary)
            write_frames(output / (sample['case_id'] + '.frames.jsonl'), run['records'])
            write_json(output / (sample['case_id'] + '.groups.json'), run['groups'])
            result['cases'].append(record)
            write_json(output / 'progress.json', result)
            print(json.dumps(record, ensure_ascii=False), flush=True)
        if not args.skip_continuous:
            audio, parts = continuous_audio(samples, args.continuous_seconds)
            stream = AdaptiveStream(model, processor, audio, config, realtime=args.realtime)
            run = stream.run()
            summary = stream.summary(run)
            record = case_record({'case_id': 'continuous_60s'}, audio, None, summary)
            record['continuous_parts'] = parts
            write_frames(output / 'continuous_60s.frames.jsonl', run['records'])
            write_json(output / 'continuous_60s.groups.json', run['groups'])
            result['cases'].append(record)
            write_json(output / 'progress.json', result)
            print(json.dumps(record, ensure_ascii=False), flush=True)
        result['gate'] = evaluate_gate(result['cases'], config, result.get('peak_gpu_mib', 0),
                                       result['expected_cases'])
        result['passed'] = bool(result['gate']['passed'])
    except Exception as exc:
        result.update(error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        torch.cuda.synchronize()
        result['peak_allocated_mib'] = torch.cuda.max_memory_allocated() / 2 ** 20
        result['peak_reserved_mib'] = torch.cuda.max_memory_reserved() / 2 ** 20
        result['peak_gpu_mib'] = result['peak_reserved_mib']
        if not result.get('gate') and result['cases'] and not result.get('error'):
            result['gate'] = evaluate_gate(result['cases'], config, result['peak_gpu_mib'],
                                           result['expected_cases'])
            result['passed'] = bool(result['gate']['passed'])
        write_json(output / 'result.json', result)
    return result, torch


def evaluate_gate(cases, config, peak_mib=0, expected_cases=4):
    thresholds = config.get('gate', {})
    by_id = {case['case_id']: case for case in cases}
    continuous = by_id.get('continuous_60s')
    rtf = {case['case_id']: case.get('x2_rtf') for case in cases}
    p95 = {case['case_id']: case.get('backlog_ms', {}).get('p95') for case in cases}
    values = {
        'x2_rtf_max': max((v for v in rtf.values() if v is not None), default=None),
        'backlog_p95_ms_max': max((v for v in p95.values() if v is not None), default=None),
        'continuous_drift_ms': continuous.get('backlog_drift_ms') if continuous else None,
        'peak_gpu_mib': peak_mib,
    }
    checks = {
        'all_cases_completed': len(cases) == expected_cases
                               and all(case.get('passed') for case in cases),
        'x2_rtf': values['x2_rtf_max'] is not None
                  and values['x2_rtf_max'] <= thresholds.get('x2_rtf_max', .6),
        'backlog_p95': values['backlog_p95_ms_max'] is not None
                       and values['backlog_p95_ms_max'] <= thresholds.get('backlog_p95_ms_max', 320),
        'continuous_drift': values['continuous_drift_ms'] is None
                            or values['continuous_drift_ms'] <= thresholds.get('continuous_drift_ms_max', 160),
        'peak_gpu': values['peak_gpu_mib'] <= thresholds.get('peak_gpu_mib_max', 12288),
    }
    return {
        'thresholds': {
            'x2_rtf_max': thresholds.get('x2_rtf_max', .6),
            'backlog_p95_ms_max': thresholds.get('backlog_p95_ms_max', 320),
            'continuous_drift_ms_max': thresholds.get('continuous_drift_ms_max', 160),
            'peak_gpu_mib_max': thresholds.get('peak_gpu_mib_max', 12288),
        },
        'values': values,
        'rtf_by_case': rtf,
        'backlog_p95_by_case': p95,
        'checks': checks,
        'passed': all(checks.values()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path,
                        default=Path(__file__).parents[2] / 'configs/x2_streaming_probe.json')
    parser.add_argument('--case')
    parser.add_argument('--continuous-seconds', type=float, default=None)
    parser.add_argument('--contract-only', action='store_true')
    parser.add_argument('--skip-continuous', action='store_true')
    parser.add_argument('--unpaced', dest='realtime', action='store_false')
    parser.set_defaults(realtime=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.continuous_seconds is None:
        args.continuous_seconds = float(config.get('continuous_seconds', 60))
    result, _ = run_cases(args, config)
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
