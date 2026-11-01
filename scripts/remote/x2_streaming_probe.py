"""Probe whether X2Streaming-ASR can sustain one 80 ms token per frame in real time.

The script loads the 4B checkpoint in one process, feeds a processor-compatible
stream, and records every emitted token with its wall-clock and audio coverage.
It does not start SoulX and does not write teacher frames.
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
SAMPLE_RATE = 16000
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def percentile(values, fraction):
    """Linearly interpolated percentile with deterministic empty handling."""
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
    """Split tokens into [W]...([W] or [P]) groups and audit unbound text."""
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
    unclosed = None
    if current is not None:
        unclosed = current
    return {
        'groups': groups,
        'unbound_tokens': unbound,
        'unclosed_tail': unclosed,
        'word_markers': word_markers,
        'wait_markers': wait_markers,
    }


def group_audit(tokenizer, tokens, emit_ms, cumulative):
    """Verify that closing a group never rewrites its later decoded prefix."""
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
                violations.append({
                    'group_start_frame': group['start_frame'],
                    'group_close_frame': closed_at,
                    'changed_frame': frame,
                    'closed_text': prefix,
                    'later_text': cumulative[frame],
                })
                break
    parsed['group_prefix_violations'] = violations
    parsed['close_delay_ms'] = [g['close_delay_ms'] for g in parsed['groups']]
    parsed['close_delay_frames'] = [g['close_delay_frames'] for g in parsed['groups']]
    return parsed


def audit_cumulative_text(tokenizer, tokens):
    """Decode the raw append-only stream and list every prefix rewrite."""
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


class StreamRun:
    """One real-time generation pass with per-token timing and group audit."""

    def __init__(self, model, processor, audio, config, realtime=True,
                 flush_frames=None):
        import numpy as np
        import torch
        self.model, self.processor = model, processor
        self.torch = torch
        self.audio = np.asarray(audio, dtype=np.float32)
        self.config = config
        self.realtime = realtime
        self.frame_samples = FRAME_SAMPLES
        self.first_samples = processor.num_samples_first_audio_chunk
        self.user_prefill_mel_frames = processor.num_mel_frames_first_audio_chunk
        self.chunk_samples = processor.num_samples_per_audio_chunk
        self.hop = processor.feature_extractor.hop_length
        self.win = processor.feature_extractor.win_length
        self.delay = int(processor.num_delay_tokens)
        self.flush_frames = self.delay + 2 if flush_frames is None else int(flush_frames)
        self.audio_frames = len(self.audio) / self.frame_samples
        self.padded_samples = len(self.audio) + self.flush_frames * self.frame_samples
        self.started = None
        self.tokens = []
        self.feature_calls = []
        self.padding_cache_calls = []
        self._active_feed = None

    def _schedule(self):
        """Return (start_sample, end_sample) for each one-token feature chunk."""
        chunks = [(0, self.first_samples)]
        frame_index = self.user_prefill_mel_frames
        while True:
            start = frame_index * self.hop - self.win // 2
            if start >= self.padded_samples:
                break
            chunks.append((start, start + self.chunk_samples))
            frame_index += self.processor.audio_length_per_tok
        return chunks

    def _first_inputs(self):
        import numpy as np
        first_audio = self.audio[:self.first_samples]
        if len(first_audio) < self.first_samples:
            first_audio = np.pad(first_audio, (0, self.first_samples - len(first_audio)))
        first = self.processor(first_audio, sampling_rate=SAMPLE_RATE, is_streaming=True,
                               is_first_audio_chunk=True, return_tensors='pt')
        return first

    def _chunk_audio(self, start, end):
        import numpy as np
        chunk = self.audio[start:min(end, len(self.audio))]
        if len(chunk) < end - start:
            chunk = np.pad(chunk, (0, end - start - len(chunk)))
        return chunk

    def _wrap_audio_features(self):
        original = self.model.model.get_audio_features
        calls = self.feature_calls
        cache_calls = self.padding_cache_calls
        processor = self.processor

        def wrapped(*args, **kwargs):
            features = kwargs.get('input_features')
            if features is None and args:
                features = args[0]
            before = _cache_shapes(kwargs.get('padding_cache'))
            outputs = original(*args, **kwargs)
            after = _cache_shapes(getattr(outputs, 'padding_cache', None))
            calls.append({
                'input_features_shape': list(features.shape) if features is not None else None,
                'cache_before': before,
                'cache_after': after,
            })
            cache_calls.append(after)
            return outputs

        self.model.model.get_audio_features = wrapped
        return original

    def run(self):
        import torch
        first = self._first_inputs()
        input_ids = first.input_ids.to(self.model.device)
        first_features = first.input_features.to(self.model.device, dtype=self.model.dtype)
        self.delay = int(first.num_delay_tokens)
        self.flush_frames = int(self.config.get('contract', {}).get('flush_frames', self.delay + 2))
        self.padded_samples = len(self.audio) + self.flush_frames * self.frame_samples
        chunks = self._schedule()

        # Capture the actual first tensor without slicing its channel dimension.
        original = self._wrap_audio_features()
        started = time.monotonic()
        self.started = started
        feed_records = []

        def features():
            nonlocal first_features
            record = {'chunk_index': 0, 'start_sample': 0, 'end_sample': self.first_samples,
                      'coverage_samples': self.first_samples,
                      'fed_at': time.monotonic(), 'features_shape': list(first_features.shape)}
            feed_records.append(record)
            self._active_feed = record
            yield first_features
            for index, (start, end) in enumerate(chunks[1:], 1):
                target = started + end / SAMPLE_RATE
                while self.realtime:
                    remaining = target - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(remaining)
                chunk = self._chunk_audio(start, end)
                inputs = self.processor(chunk, sampling_rate=SAMPLE_RATE, is_streaming=True,
                                        is_first_audio_chunk=False, return_tensors='pt')
                feature = inputs.input_features.to(self.model.device, dtype=self.model.dtype)
                record = {'chunk_index': index, 'start_sample': start, 'end_sample': end,
                          'coverage_samples': end, 'fed_at': time.monotonic(),
                          'features_shape': list(feature.shape)}
                feed_records.append(record)
                self._active_feed = record
                yield feature

        class Recorder:
            def __init__(self, run):
                self.run = run

            def put(self, value):
                ids = value.detach().cpu().reshape(-1).tolist()
                now = time.monotonic()
                feed = self.run._active_feed
                for token in ids:
                    frame = len(self.run.tokens)
                    self.run.tokens.append({
                        'frame': frame,
                        'token_id': int(token),
                        'emitted_at': now,
                        'feed_at': feed['fed_at'] if feed else started,
                        'chunk_index': feed['chunk_index'] if feed else None,
                        'feature_shape': feed['features_shape'] if feed else None,
                    })

            def end(self):
                pass

        self.model._stream_exhausted = False
        original_prepare = self.model.prepare_inputs_for_generation

        def prepare(*args, **kwargs):
            # Transformers 5.15 drops multimodal inputs on non-prefill iterations.
            # The streaming processor yields one feature chunk per decode step, so
            # keep the chunk visible to the model-specific forward path.
            kwargs['is_first_iteration'] = True
            return original_prepare(*args, **kwargs)

        self.model.prepare_inputs_for_generation = prepare
        try:
            with torch.inference_mode():
                self.model.generate(input_ids=input_ids, input_features=features(),
                                    num_delay_tokens=self.delay, streamer=Recorder(self),
                                    do_sample=False, use_cache=True)
        finally:
            self.model._stream_exhausted = False
            self.model.prepare_inputs_for_generation = original_prepare
            self.model.model.get_audio_features = original
        return self._record(started, feed_records, chunks)

    def _record(self, started, feeds, chunks):
        tokenizer = self.processor.tokenizer
        tokens = [value['token_id'] for value in self.tokens]
        emit_ms = [(value['emitted_at'] - started) * 1000 for value in self.tokens]
        cumulative, rewrites = audit_cumulative_text(tokenizer, tokens)
        parsed = group_audit(tokenizer, tokens, emit_ms, cumulative)
        records = []
        for value, text in zip(self.tokens, cumulative):
            frame = value['frame']
            wall_ms = (value['emitted_at'] - started) * 1000
            feed = next((f for f in feeds if f['chunk_index'] == value['chunk_index']), feeds[-1])
            coverage_ms = feed['coverage_samples'] / SAMPLE_RATE * 1000
            frame_end_ms = (frame + 1) * FRAME_MS
            records.append({
                **value,
                'wall_ms': wall_ms,
                'audio_frame_end_ms': frame_end_ms,
                'coverage_end_ms': coverage_ms,
                'frame_lag_ms': wall_ms - frame_end_ms,
                'decode_latency_ms': (value['emitted_at'] - value['feed_at']) * 1000,
                'backlog_ms': wall_ms - coverage_ms,
                'pad': frame >= self.audio_frames,
                'cumulative_text': text,
                'delta_text': text[len(cumulative[frame - 1]):] if frame else text,
                'is_wait': value['token_id'] == WAIT_TOKEN_ID,
                'is_word': value['token_id'] == WORD_TOKEN_ID,
            })
        return {
            'records': records,
            'feeds': feeds,
            'chunks': len(chunks),
            'cumulative': cumulative,
            'rewrites': rewrites,
            'groups': parsed,
            'started': started,
            'audio_seconds': len(self.audio) / SAMPLE_RATE,
            'audio_frames': self.audio_frames,
            'tokenizer': tokenizer,
        }

    def summary(self, run):
        real = [value for value in run['records'] if not value['pad']]
        all_records = run['records']
        groups = run['groups']
        values = lambda key, rows: [r[key] for r in rows if r.get(key) is not None]
        backlog = values('backlog_ms', real)
        frame_lag = values('frame_lag_ms', real)
        decode = values('decode_latency_ms', real)
        compute = values('decode_latency_ms', real)
        audio_seconds = run['audio_seconds']
        total_compute = sum(values('decode_latency_ms', all_records))
        real_compute = sum(compute)
        first_window = [r['backlog_ms'] for r in real if r['wall_ms'] <= 5000]
        last_window = [r['backlog_ms'] for r in real if r['wall_ms'] > max(0, audio_seconds * 1000 - 5000)]
        drift = None
        if first_window and last_window:
            drift = percentile(last_window, .5) - percentile(first_window, .5)
        feature_shapes = Counter(tuple(value['features_shape']) for value in run['feeds'])
        group_text = [g['text'] for g in groups['groups']]
        return {
            'audio_seconds': audio_seconds,
            'tokens': len(all_records),
            'real_tokens': len(real),
            'pad_tokens': len(all_records) - len(real),
            'chunks': run['chunks'],
            'feature_shapes': {'x'.join(map(str, key)): count for key, count in feature_shapes.items()},
            'x2_rtf': real_compute / 1000 / audio_seconds if audio_seconds else None,
            'x2_rtf_including_flush': total_compute / 1000 / audio_seconds if audio_seconds else None,
            'compute_ms': distribution(compute),
            'frame_lag_ms': distribution(frame_lag),
            'backlog_ms': distribution(backlog),
            'decode_latency_ms': distribution(decode),
            'first_window_backlog_p50_ms': percentile(first_window, .5),
            'last_window_backlog_p50_ms': percentile(last_window, .5),
            'backlog_drift_ms': drift,
            'first_backlog_ms': backlog[0] if backlog else None,
            'last_backlog_ms': backlog[-1] if backlog else None,
            'word_markers': groups['word_markers'],
            'wait_markers': groups['wait_markers'],
            'closed_groups': len(groups['groups']),
            'unbound_tokens': len(groups['unbound_tokens']),
            'unclosed_tail': None if groups['unclosed_tail'] is None else {
                'start_frame': groups['unclosed_tail']['start_frame'],
                'token_count': groups['unclosed_tail']['token_count'],
                'text': groups['unclosed_tail']['text'],
            },
            'group_close_delay_ms': distribution(groups['close_delay_ms']),
            'group_close_delay_frames': distribution(groups['close_delay_frames']),
            'group_texts': group_text[:20],
            'group_prefix_violations': len(groups['group_prefix_violations']),
            'group_prefix_violation_examples': groups['group_prefix_violations'][:5],
            'text_rewrites': len(run['rewrites']),
            'text_rewrite_examples': run['rewrites'][:5],
            'final_text': run['cumulative'][-1] if run['cumulative'] else '',
            'padding_cache_calls': len(self.padding_cache_calls),
        }


def _cache_shapes(cache):
    if cache is None:
        return None
    result = {}
    for key, layer in getattr(cache, 'layers', {}).items():
        if getattr(layer, 'cache', None) is not None:
            result[key] = list(layer.cache.shape)
    return result


def contract_check(model, processor, config):
    """Pin the first and incremental feature/cache shapes before real audio."""
    import numpy as np
    rng = np.random.default_rng(42)
    seconds = 3.36
    count = int(seconds * SAMPLE_RATE)
    timeline = np.arange(count) / SAMPLE_RATE
    audio = (.05 * np.sin(2 * np.pi * 220 * timeline)
             + .01 * rng.standard_normal(count)).astype(np.float32)
    run = StreamRun(model, processor, audio, config, realtime=True)
    result = run.run()
    summary = run.summary(result)
    first_shape = tuple(run.feature_calls[0]['input_features_shape'])
    expected_cache = {
        'conv1': [1, int(model.config.audio_config.num_mel_bins),
                  int(model.model.audio_tower.embedder.conv1.left_pad)],
        'conv2': [1, int(model.config.audio_config.hidden_size),
                  int(model.model.audio_tower.embedder.conv2.left_pad)],
    }
    first_cache = run.padding_cache_calls[0] if run.padding_cache_calls else None
    second_cache = run.padding_cache_calls[1] if len(run.padding_cache_calls) > 1 else None
    first_user = int(processor.num_mel_frames_first_audio_chunk)
    total_frames = first_shape[-1] if len(first_shape) == 3 else None
    left_pad = total_frames - first_user if total_frames is not None else None
    expected_first = config.get('contract', {}).get('first_total_mel_frames')
    expected_left_pad = (processor.mistral_common_audio_config.n_left_pad_tokens
                         * int(processor.audio_length_per_tok))
    checks = {
        'first_feature_channels': first_shape[1] == int(model.config.audio_config.num_mel_bins),
        'first_feature_frames': total_frames == expected_first,
        'left_pad_mel_frames': left_pad == expected_left_pad,
        'first_user_mel_frames': first_user
                                 == config.get('contract', {}).get('first_user_mel_frames'),
        'first_input_tokens': result['feeds'][0]['features_shape'][-1] // int(processor.audio_length_per_tok)
                              == int(processor.num_delay_tokens) + 1 + expected_left_pad
                              // int(processor.audio_length_per_tok),
        'subsequent_feature_frames': all(
            value['features_shape'][-1] == int(processor.audio_length_per_tok)
            for value in result['feeds'][1:]),
        'first_cache': first_cache == expected_cache,
        'second_cache': second_cache == expected_cache,
        'tokens': len(result['records']) > 0,
    }
    record = {
        'passed': all(checks.values()),
        'checks': checks,
        'seconds': seconds,
        'first_shape': list(first_shape),
        'first_user_mel_frames': first_user,
        'left_pad_mel_frames': left_pad,
        'expected_first_mel_frames': total_frames,
        'first_tokens': result['feeds'][0]['features_shape'][-1] // int(processor.audio_length_per_tok),
        'subsequent_shapes': sorted({tuple(v['features_shape']) for v in result['feeds'][1:]}),
        'expected_padding_cache': expected_cache,
        'first_padding_cache': first_cache,
        'second_padding_cache': second_cache,
        'tokens_emitted': len(result['records']),
        'summary': summary,
    }
    return record, result


def case_record(sample, audio, gain, run, summary):
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
    import numpy as np
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
        selected = [
            select_case(samples, longest=True),
            select_case(samples, 'candor_pause_handling-16'),
            select_case(samples, 'candor_turn_taking-102'),
        ]
    output = args.output
    output.mkdir(exist_ok=False)
    write_json(output / 'input_manifest.json', dict(manifest, samples=selected))

    processor = AutoProcessor.from_pretrained(args.model, local_files_only=True)
    model = VoxtralRealtimeForConditionalGeneration.from_pretrained(
        args.model, dtype=torch.bfloat16, device_map='cuda',
        local_files_only=True, attn_implementation='sdpa').eval()
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
            'delay_tokens': int(processor.num_delay_tokens),
            'first_samples': int(processor.num_samples_first_audio_chunk),
            'first_user_mel_frames': int(processor.num_mel_frames_first_audio_chunk),
            'chunk_samples': int(processor.num_samples_per_audio_chunk),
            'chunk_mel_frames': int(processor.audio_length_per_tok),
            'frame_ms': FRAME_MS,
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
        result['gpu'] = {
            'name': torch.cuda.get_device_name(0),
            'total_mib': torch.cuda.get_device_properties(0).total_memory / 2 ** 20,
        }
    try:
        contract, _ = contract_check(model, processor, config)
        write_json(output / 'contract.json', contract)
        result['contract'] = contract
        if not contract['passed']:
            raise RuntimeError('First-block feature/cache contract failed')
        if args.contract_only:
            result['passed'] = True
            return result, torch

        cases = []
        for sample in selected:
            verify_sample(sample)
            audio, gain = load_audio(sample['input'])
            run = StreamRun(model, processor, audio, config, realtime=args.realtime)
            stream = run.run()
            summary = run.summary(stream)
            record = case_record(sample, audio, gain, stream, summary)
            write_frames(output / (sample['case_id'] + '.frames.jsonl'), stream['records'])
            cases.append(record)
            result['cases'].append(record)
            write_json(output / 'progress.json', result)
            print(json.dumps({k: v for k, v in record.items() if k not in ('group_texts',)}, ensure_ascii=False),
                  flush=True)

        if not args.skip_continuous:
            audio, parts = continuous_audio(samples, args.continuous_seconds)
            run = StreamRun(model, processor, audio, config, realtime=args.realtime)
            stream = run.run()
            summary = run.summary(stream)
            record = case_record({'case_id': 'continuous_60s'}, audio, None, stream, summary)
            record['continuous_parts'] = parts
            write_frames(output / 'continuous_60s.frames.jsonl', stream['records'])
            result['cases'].append(record)
            write_json(output / 'progress.json', result)
            print(json.dumps({k: v for k, v in record.items() if k not in ('group_texts',)},
                             ensure_ascii=False), flush=True)

        if not args.contract_only:
            result['gate'] = evaluate_gate(result['cases'], config, result.get('peak_gpu_mib', 0),
                                           result['expected_cases'])
            result['passed'] = bool(result['gate']['passed'])
        elif result['contract'] and result['contract']['passed']:
            result['passed'] = True
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
    peak = peak_mib
    values = {
        'x2_rtf_max': max((v for v in rtf.values() if v is not None), default=None),
        'backlog_p95_ms_max': max((v for v in p95.values() if v is not None), default=None),
        'continuous_drift_ms': continuous.get('backlog_drift_ms') if continuous else None,
        'peak_gpu_mib': peak,
    }
    checks = {
        'all_cases_completed': len(cases) == expected_cases
                               and all(case.get('passed') for case in cases),
        'x2_rtf': values['x2_rtf_max'] is not None and values['x2_rtf_max'] <= thresholds.get('x2_rtf_max', .6),
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
    parser.add_argument('--continuous-seconds', type=float,
                        default=None)
    parser.add_argument('--contract-only', action='store_true')
    parser.add_argument('--skip-continuous', action='store_true')
    parser.add_argument('--unpaced', dest='realtime', action='store_false')
    parser.set_defaults(realtime=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.continuous_seconds is None:
        args.continuous_seconds = float(config.get('continuous_seconds', 60))
    result, torch = run_cases(args, config)
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
