"""Diagnose complete-ASR omission with bounded, isolated native comparisons."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
from unittest.mock import patch


SOURCE_COMMIT = '65d15e60730a3e01c580ee68a73d75c4439741db'


def tensor_digest(value):
    import torch
    return hashlib.sha256(value.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes()).hexdigest()


def write_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def run_comparison(probe, model, audio, output, *, align_complete_rng):
    import torch
    from funasr.utils.load_utils import extract_fbank

    frontend = model.cascade_asr.sensevoice_model.kwargs['frontend']
    original_forward = frontend.forward
    original_recognize = model.cascade_asr.recognize
    original_complete = probe.NativeSoulX.complete_text
    calls, features, supplements = [], [], []
    context = {'recognition': None, 'supplement': False}

    def forward(*args, **kwargs):
        before = tensor_digest(torch.random.get_rng_state())
        started = time.monotonic()
        result = original_forward(*args, **kwargs)
        features.append({'recognition': context['recognition'], 'supplement': context['supplement'],
                         'input_dtype': str(args[0].dtype), 'input_shape': list(args[0].shape),
                         'rng_before': before, 'rng_after': tensor_digest(torch.random.get_rng_state()),
                         'feature_sha256': tensor_digest(result[0]), 'feature_shape': list(result[0].shape),
                         'seconds': time.monotonic() - started})
        return result

    def recognize(values, *args, **kwargs):
        index = len(calls)
        context['recognition'] = index
        row = {'index': index, 'pcm_sha256': probe.pcm_digest(values),
               'samples': len(values), 'dtype': str(values.dtype),
               'rng_before': tensor_digest(torch.random.get_rng_state())}
        result = original_recognize(values, *args, **kwargs)
        row.update(text=result, rng_after=tensor_digest(torch.random.get_rng_state()))
        calls.append(row)
        context['recognition'] = None
        return result

    def complete(wrapper, values, *args, **kwargs):
        if align_complete_rng and wrapper.skip_complete_recognition:
            context['supplement'] = True
            before = tensor_digest(torch.random.get_rng_state())
            try:
                extract_fbank([values], frontend=frontend)
            finally:
                context['supplement'] = False
            supplements.append({'step_id': wrapper._step_id, 'samples': len(values),
                                'pcm_sha256': probe.pcm_digest(values), 'rng_before': before,
                                'rng_after': tensor_digest(torch.random.get_rng_state())})
        return original_complete(wrapper, values, *args, **kwargs)

    with patch.object(frontend, 'forward', forward), \
            patch.object(model.cascade_asr, 'recognize', recognize), \
            patch.object(probe.NativeSoulX, 'complete_text', complete):
        comparison = probe.compare_native(model, audio)
    trace_a, trace_b = comparison['reference']['trace'], comparison['observed']['trace']
    differences = [{'index': i, 'reference': left, 'observed': right}
                   for i, (left, right) in enumerate(zip(trace_a, trace_b)) if left != right]
    write_json(output / 'comparison.json', comparison)
    write_json(output / 'recognitions.json', calls)
    write_json(output / 'features.json', features)
    summary = {'passed': comparison['passed'], 'align_complete_rng': align_complete_rng,
               'dither': frontend.dither, 'trace_lengths': [len(trace_a), len(trace_b)],
               'trace_differences': differences, 'supplements': supplements,
               'recognitions': len(calls), 'feature_calls': len(features)}
    write_json(output / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--warmup-audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 2**20, 64 * 2**20))
    observed = subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(args.source), 'status', '--porcelain'], text=True).strip()
    if observed != SOURCE_COMMIT or dirty:
        raise ValueError('Expected clean NTF-054 source')
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    sys.path.insert(0, str(args.source / 'scripts/remote'))
    import native_frontend_probe as probe
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(22 * 2**30 / torch.cuda.get_device_properties(0).total_memory)
    controller = probe.load_native_controller(args.root / 'upstream/soulx-duplug',
                                              args.assets / 'models/soulx-duplug',
                                              args.assets / 'models/sensevoice-small',
                                              args.output / 'assets')
    model = controller.model
    controller.detach()
    audio, preparation = probe.warmup_audio(args.warmup_audio)
    summaries = {}
    for name, align in [('baseline', False), ('aligned', True)]:
        folder = args.output / name
        folder.mkdir()
        summaries[name] = run_comparison(probe, model, audio, folder, align_complete_rng=align)
    result = {'source_commit': observed, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'versions': {name: importlib.metadata.version(name) for name in ('torch', 'torchaudio', 'funasr')},
              'audio_sha256': probe.pcm_digest(audio), 'preparation': preparation, 'comparisons': summaries,
              'execution': controller.execution_manifest, 'seconds': time.monotonic() - started,
              'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              'peak_gpu_allocated_mib': torch.cuda.max_memory_allocated() / 2**20,
              'peak_gpu_reserved_mib': torch.cuda.max_memory_reserved() / 2**20}
    output_bytes = sum(path.stat().st_size for path in args.output.rglob('*') if path.is_file())
    result['output_bytes_before_summary'] = output_bytes
    if output_bytes > 128 * 2**20:
        raise RuntimeError('Diagnostic output exceeds 128 MiB')
    write_json(args.output / 'summary.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
