"""Measure causal X2 LISTEN/DECODE inference against the frozen NTF-011 gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import traceback


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def distribution(values):
    if not values:
        return {'count': 0, 'p50': None, 'p95': None, 'max': None}
    ordered = sorted(values)
    def percentile(q):
        index = (len(ordered) - 1) * q
        low, high = math.floor(index), math.ceil(index)
        return ordered[low] + (ordered[high] - ordered[low]) * (index - low)
    return {'count': len(values), 'p50': percentile(.5), 'p95': percentile(.95), 'max': max(values)}


def evaluate_gate(cases, peak_gpu_mib, limits):
    failures = []
    if len(cases) != 4 or len({c['case_id'] for c in cases}) != 4:
        failures.append('four_distinct_cases_required')
    if not any(c['case_id'] == 'continuous_60s' for c in cases):
        failures.append('continuous_60s_required')
    for case in cases:
        name = case['case_id']
        if not case.get('completed'):
            failures.append(name + ':incomplete')
            continue
        if case['x2_rtf'] > limits['x2_rtf']:
            failures.append(name + ':x2_rtf')
        if case['backlog_ms']['p95'] > limits['backlog_p95_ms']:
            failures.append(name + ':backlog_p95_ms')
        if case['rewrite_count'] or case['unclosed_groups']:
            failures.append(name + ':text_integrity')
        if name == 'continuous_60s' and abs(case['backlog_drift_ms']) > limits['drift_ms']:
            failures.append(name + ':backlog_drift_ms')
    if peak_gpu_mib > limits['peak_gpu_mib']:
        failures.append('peak_gpu_mib')
    return failures


class ClosedGroups:
    """Only accept EOS-terminated emits; independently recheck historic prefixes."""

    def __init__(self, decode, join):
        self.decode, self.join = decode, join
        self.groups, self.ids, self.snapshots = [], [], []
        self.text, self.rewrites = '', []

    def append(self, ids):
        if not ids or ids[-1] != 2 or any(v in (1, 2, 32, 33) for v in ids[:-1]):
            raise ValueError('Emit must contain text tokens followed by EOS')
        chunk = self.decode(ids[:-1]).strip()
        old = self.text
        candidate = self.join(self.groups + [chunk])
        all_ids = self.ids + ids[:-1]
        for end, previous in self.snapshots:
            current = self.decode(all_ids[:end])
            if current != previous:
                self.rewrites.append({'end': end, 'before': previous, 'after': current})
        if not candidate.startswith(old):
            self.rewrites.append({'before': old, 'after': candidate})
        self.ids = all_ids
        self.snapshots.append((len(self.ids), self.decode(self.ids)))
        self.groups.append(chunk)
        self.text = candidate
        return self.text[len(old):]


def decode_emit(next_token, token_forward, on_token, max_tokens):
    """Decode one emit without consuming another audio frame or inventing EOS."""
    ids, last_text_at = [], None
    for _ in range(max_tokens + 1):
        at = time.monotonic()
        on_token(next_token, 'decode')
        ids.append(next_token)
        if next_token == 2:
            return ids, (at - last_text_at) * 1000 if last_text_at else 0.
        if next_token in (1, 32, 33):
            raise ValueError(f'Unexpected control token within DECODE: {next_token}')
        if len(ids) > max_tokens:
            raise RuntimeError('Emit exceeded bounded decode length without EOS')
        last_text_at = at
        next_token = token_forward(next_token)
    raise AssertionError('Unreachable decode state')


def frame_window(index, total_samples):
    end = min((index + 1) * 1280, total_samples)
    observed = min((index + 1) * 1280 + 200, total_samples)
    padding = max(0, (index + 1) * 1280 + 200 - total_samples)
    return end, observed, padding


class X2Engine:
    """Use frozen upstream adaptive helpers with separate audio and text KV caches."""

    def __init__(self, model_path, upstream, config):
        import torch
        from transformers import AutoProcessor, VoxtralRealtimeForConditionalGeneration
        sys.path.insert(0, str(upstream))
        sys.path.insert(0, str(upstream / 'demo'))
        from engine import encode_first_streaming_chunk
        from models.voxtral_asr.data import disable_adarms_delay_conditioning
        from models.voxtral_asr.interleaved import _lm_step_embeds
        from models.voxtral_asr.language_tag import attach_language_tag_embed, set_infer_language_id
        from data_pipeline.join_emit import join_emit_texts
        self.torch, self.config = torch, config
        self.processor = AutoProcessor.from_pretrained(str(model_path), local_files_only=True)
        self.model = VoxtralRealtimeForConditionalGeneration.from_pretrained(
            str(model_path), dtype=torch.bfloat16, device_map='cuda:0',
            attn_implementation='sdpa', local_files_only=True).eval()
        attach_language_tag_embed(self.model, model_path=str(model_path), require_checkpoint_weights=True)
        set_infer_language_id(self.model, 'en')
        disable_adarms_delay_conditioning(self.model)
        self.lm_forward, self.join = _lm_step_embeds, join_emit_texts
        self.first_encode = encode_first_streaming_chunk
        self.last_shape, self.memory_samples = {}, []

    def memory(self):
        free, total = self.torch.cuda.mem_get_info()
        current = (total - free) / 2**20
        self.memory_samples.append(current)
        if current > self.config['stop_gpu_mib']:
            raise MemoryError(f'GPU usage {current:.1f} MiB exceeds stop line')
        return current

    def encode(self, audio, first=False):
        if first:
            inputs = self.first_encode(self.processor, audio, self.config['adaptive_protocol_ms'])
        else:
            inputs = self.processor(audio, sampling_rate=16000, is_streaming=True,
                                    is_first_audio_chunk=False, return_tensors='pt')
        features = inputs.input_features
        expected = self.config['first_mel_frames'] if first else self.config['next_mel_frames']
        self.last_shape = {'first': first, 'pcm_samples': len(audio),
                           'input_features': list(features.shape), 'expected_mel_frames': expected}
        if tuple(features.shape) != (1, 128, expected):
            raise AssertionError(f'Unexpected mel contract: {self.last_shape}')
        output = self.model.model.get_audio_features(
            input_features=features.to('cuda', dtype=self.model.dtype),
            padding_cache=self.padding, past_key_values=self.audio_past, use_cache=True,
            use_padding_cache=True)
        self.padding, self.audio_past = output.padding_cache, output.past_key_values
        shapes = {str(key): list(layer.cache.shape) for key, layer in self.padding.layers.items()}
        self.last_shape['padding_cache'] = shapes
        embedder = self.model.model.audio_tower.embedder
        expected_shapes = {name: [1, getattr(embedder, name).in_channels,
                                 getattr(embedder, name).left_pad]
                           for name in ('conv1', 'conv2')}
        if shapes != expected_shapes:
            raise AssertionError(f'Invalid convolution cache: {self.last_shape}')
        frames = output.pooler_output
        if frames.shape[1] != expected // 8:
            raise AssertionError(f'Unexpected pooled features: {tuple(frames.shape)}')
        return frames

    def lm(self, embeds):
        logits, self.past = self.lm_forward(self.model, embeds, self.past)
        return int(logits[0, -1].argmax().item())

    def token_embed(self, token):
        return self.model.model.get_input_embeddings()(
            self.torch.tensor([[token]], device='cuda', dtype=self.torch.long))

    def token_forward(self, token):
        return self.lm(self.token_embed(token))

    def reset(self):
        import numpy as np
        from transformers.models.voxtral_realtime.modeling_voxtral_realtime import VoxtralRealtimeConv1dPaddingCache
        self.padding, self.audio_past, self.past = VoxtralRealtimeConv1dPaddingCache(), None, None
        self.groups = ClosedGroups(
            lambda ids: self.processor.tokenizer.decode(ids, skip_special_tokens=True), self.join)
        self.token_forward(1)
        # Match upstream's synthetic online left-pad warmup; surplus pad frames are discarded.
        frames = self.encode(np.zeros(self.config['first_pcm_samples'], np.float32), first=True)
        shape = dict(self.last_shape)
        self.lm(frames[:, :self.config['left_pad_frames']])
        self.torch.cuda.synchronize()
        return {'left_pad_frames': self.config['left_pad_frames'], 'shape': shape,
                'discarded_synthetic_frames': frames.shape[1] - self.config['left_pad_frames'],
                'left_pad_in_timed_audio': False, 'actual_observation_offset_samples': 200}

    def step(self, audio, on_token):
        began = time.monotonic()
        frames = self.encode(audio)
        decision = self.lm(frames)
        on_token(decision, 'listen')
        tokens, closed, delay = [decision], 0, None
        if decision == 33:
            ids, delay = decode_emit(self.token_forward(33), self.token_forward,
                                     on_token, self.config['max_decode_tokens'])
            self.groups.append(ids)
            tokens.extend(ids)
            closed = 1
        elif decision != 32:
            raise ValueError(f'LISTEN must produce PAD or WORD, got {decision}')
        self.torch.cuda.synchronize()
        return {'token_ids': tokens, 'decision': decision, 'closed_groups': closed,
                'group_close_delay_ms': delay, 'compute_ms': (time.monotonic() - began) * 1000,
                'text': self.groups.text, 'unclosed_groups': 0, 'gpu_mib': self.memory()}


def run_stream(engine, audio, case_id, output, realtime=True):
    import numpy as np
    torch = engine.torch
    count = math.ceil(len(audio) / 1280)
    extended = np.pad(audio, (200, count * 1280 + 200 - len(audio)))
    with torch.inference_mode():
        warm = engine.reset()
        started = time.monotonic()
        rows, close_delays, compute_ms = [], [], 0.
        with (output / f'{case_id}.tokens.jsonl').open('x') as tokens_file, \
                (output / f'{case_id}.frames.jsonl').open('x') as frames_file:
            for index in range(count):
                end, observed, eof_padding = frame_window(index, len(audio))
                due = started + observed / 16000
                if realtime:
                    time.sleep(max(0, due - time.monotonic()))
                def on_token(token, phase):
                    tokens_file.write(json.dumps({'frame_index': index, 'token_id': token,
                        'phase': phase, 'at': time.monotonic(), 'audio_end_sample': end,
                        'observed_end_sample': observed}) + '\n')
                frame = engine.step(extended[index * 1280:index * 1280 + 1680], on_token)
                at = time.monotonic()
                frame.update(frame_index=index, audio_end_sample=end, observed_end_sample=observed,
                    token_at=at, frame_lag_ms=(at - started - end / 16000) * 1000,
                    backlog_ms=(at - due) * 1000, eof_padding_samples=eof_padding)
                frames_file.write(json.dumps(frame, ensure_ascii=False) + '\n')
                frames_file.flush()
                tokens_file.flush()
                rows.append(frame)
                compute_ms += frame['compute_ms']
                if frame['group_close_delay_ms'] is not None:
                    close_delays.append(frame['group_close_delay_ms'])
    lag = [r['backlog_ms'] for r in rows]
    return {'case_id': case_id, 'completed': True, 'duration_seconds': len(audio) / 16000,
            'frames': len(rows), 'elapsed_seconds': time.monotonic() - started,
            'x2_rtf': compute_ms / 1000 / (len(audio) / 16000), 'prefill': warm,
            'frame_lag_ms': distribution([r['frame_lag_ms'] for r in rows]),
            'backlog_ms': distribution(lag), 'backlog_first_ms': lag[0], 'backlog_last_ms': lag[-1],
            'backlog_drift_ms': lag[-1] - lag[0],
            'group_close_delay_ms': distribution(close_delays),
            'word_signals': sum(r['decision'] == 33 for r in rows),
            'closed_groups': sum(r['closed_groups'] for r in rows), 'unclosed_groups': 0,
            'rewrite_count': len(engine.groups.rewrites), 'rewrites': engine.groups.rewrites,
            'online_text': engine.groups.text}


def load_audio(sample):
    import numpy as np
    import soundfile as sf
    import soxr
    path = Path(sample['input'])
    for name, expected in sample['files'].items():
        if digest(path.parent / name) != expected:
            raise ValueError(f'Frozen input digest differs: {path.parent / name}')
    audio, rate = sf.read(path, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        audio = soxr.resample(audio, rate, 16000)
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(audio)))
    gain = min(.05 / rms, .9 / peak) if rms and peak else 1.
    if abs(len(audio) / 16000 - sample['duration_seconds']) > 1 / 16000:
        raise ValueError('Frozen duration differs')
    return (audio * gain).astype(np.float32), gain


def main():
    parser = argparse.ArgumentParser()
    for name in ('model', 'upstream', 'manifest', 'config', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    result = {'passed': False, 'cases': [], 'issue': 'NTF-011',
              'source_commit': __import__('os').environ.get('SOULX_SOURCE_COMMIT'),
              'manifest_sha256': digest(args.manifest), 'config_sha256': digest(args.config)}
    engine = None
    try:
        import numpy as np
        import torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        config = json.loads(args.config.read_text())
        result['config'] = config
        for name, expected in config['upstream_files'].items():
            if digest(args.upstream / name) != expected:
                raise ValueError(f'Official upstream source digest differs: {name}')
        if digest(args.model / 'model.safetensors') != config['model_sha256']:
            raise ValueError('X2 model digest differs')
        manifest = json.loads(args.manifest.read_text())
        if len(manifest['samples']) != 30:
            raise ValueError('Expected frozen FDB30')
        result['gpu_name'] = torch.cuda.get_device_name()
        if '4090' not in result['gpu_name']:
            raise ValueError('NTF-011 requires a 4090')
        torch.cuda.set_per_process_memory_fraction(config['stop_gpu_mib'] * 2**20 / torch.cuda.get_device_properties(0).total_memory)
        engine = X2Engine(args.model, args.upstream, config)
        p = engine.processor
        default = p(np.zeros(p.num_samples_first_audio_chunk, np.float32), sampling_rate=16000,
                    is_streaming=True, return_tensors='pt')
        result['default_processor_contract'] = {'pcm_samples': p.num_samples_first_audio_chunk,
            'nominal_mel_frames': p.num_mel_frames_first_audio_chunk,
            'actual_features': list(default.input_features.shape), 'prompt_tokens': default.input_ids.shape[-1]}
        tone = (.05 * np.sin(2 * np.pi * 220 * np.arange(53760) / 16000)).astype(np.float32)
        result['synthetic'] = run_stream(engine, tone, 'synthetic_3360ms', args.output, realtime=False)
        result['synthetic']['sha256'] = hashlib.sha256(tone.tobytes()).hexdigest()
        result['incremental_shape'] = dict(engine.last_shape)
        write_json(args.output / 'progress.json', result)
        samples = manifest['samples']
        selected = [max(samples, key=lambda s: s['duration_seconds'])]
        selected += [next(s for s in samples if s['case_id'] == name)
                     for name in ('candor_pause_handling-16', 'candor_turn_taking-102')]
        if len({s['case_id'] for s in selected}) != 3:
            raise ValueError('The three selected cases must be distinct')
        write_json(args.output / 'input_manifest.json', dict(manifest, selected=selected))
        def measure(audio, name):
            try:
                return run_stream(engine, audio, name, args.output)
            except MemoryError:
                raise
            except Exception as exc:
                traceback.print_exc()
                return {'case_id': name, 'completed': False, 'error': str(exc),
                        'traceback': traceback.format_exc(), 'shape': engine.last_shape}
        for sample in selected:
            audio, gain = load_audio(sample)
            case = measure(audio, sample['case_id'])
            case['gain'] = gain
            result['cases'].append(case)
            write_json(args.output / 'progress.json', result)
            print(json.dumps(case, ensure_ascii=False), flush=True)
        parts, recipe, remaining = [], [], 960000
        for sample in samples:
            audio, gain = load_audio(sample)
            take = min(remaining, len(audio))
            parts.append(audio[:take])
            recipe.append({'case_id': sample['case_id'], 'samples': take, 'gain': gain})
            remaining -= take
            if not remaining:
                break
        if remaining:
            raise ValueError('Frozen manifest cannot supply 60 seconds')
        result['continuous_recipe'] = recipe
        result['cases'].append(measure(np.concatenate(parts), 'continuous_60s'))
        result['peak_gpu_mib'] = max(engine.memory_samples)
        result['gate_failures'] = evaluate_gate(result['cases'], result['peak_gpu_mib'], config['limits'])
        result['passed'] = not result['gate_failures']
    except Exception as exc:
        result.update(error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc(),
                      shape=engine.last_shape if engine else None)
        traceback.print_exc()
    finally:
        if 'torch' in locals() and torch.cuda.is_initialized():
            result['peak_allocated_mib'] = torch.cuda.max_memory_allocated() / 2**20
            result['peak_reserved_mib'] = torch.cuda.max_memory_reserved() / 2**20
        result['exit_code'] = 0 if result['passed'] else 1
        write_json(args.output / 'result.json', result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(result['exit_code'])


if __name__ == '__main__':
    main()
