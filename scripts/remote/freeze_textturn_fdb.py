"""Freeze ranked FDB recordings, source hashes, annotations and protocol before inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

SUBSETS = {'candor_turn_taking': ('turn_taking.json',),
           'candor_pause_handling': ('pause.json', 'transcription.json')}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def annotations(path, duration):
    values = json.loads(path.read_text())
    if not isinstance(values, list) or not values:
        raise ValueError('Empty annotation list')
    for value in values:
        times = value['timestamp']
        if len(times) != 2 or not all(isinstance(t, (int, float)) and math.isfinite(t) for t in times):
            raise ValueError('Invalid annotation timestamps')
        if not 0 <= times[0] <= times[1] <= duration + 1 / 16000:
            raise ValueError('Annotation outside original recording')
    return values


def freeze(root, config, output):
    import numpy as np
    import soundfile as sf
    protocol = json.loads(config.read_text())
    if not re.fullmatch('[0-9a-f]{64}', protocol['candidate_sha256']):
        raise ValueError('Candidate SHA256 must contain exactly 64 lowercase hex digits')
    output.mkdir(parents=True, exist_ok=False)
    candidates, selected, smoke, seen = [], [], [], set()
    for subset, names in SUBSETS.items():
        directories = sorted((p for p in (root / subset).iterdir() if p.is_dir()),
            key=lambda p: hashlib.sha256(f"{protocol['seed']}|{subset}|{p.name}".encode()).hexdigest())
        valid = []
        for directory in directories:
            record = {'subset': subset, 'sample_id': directory.name,
                'case_id': subset + '-' + directory.name,
                'rank_sha256': hashlib.sha256(f"{protocol['seed']}|{subset}|{directory.name}".encode()).hexdigest(),
                'source_session': None, 'source_session_status': 'unavailable',
                'history': ['FDB complete Smooth evaluation 20261021-r4'] if subset == 'candor_turn_taking' else [],
                'other_historical_use': 'unknown', 'selected': False}
            try:
                files = {}
                for name in ('input.wav', *names):
                    path = directory / name
                    files[name] = {'path': str(path.relative_to(root)), 'sha256': digest(path),
                                   'bytes': path.stat().st_size}
                record['files'] = files
                audio, rate = sf.read(directory / 'input.wav', dtype='float32', always_2d=True)
                if rate != 16000 or audio.shape[1] != 1 or not len(audio) or not np.isfinite(audio).all():
                    raise ValueError('Expected finite nonempty mono16k recording; no implicit conversion')
                pcm = (np.clip(audio[:, 0], -1, 1) * 32767).astype('<i2').tobytes()
                identity = hashlib.sha256(pcm).hexdigest()
                record.update(rate=rate, channels=1, frames=len(audio), duration_seconds=len(audio)/rate,
                    normalized_pcm_sha256=identity, tail_seconds=protocol['tail_seconds'][subset],
                    sent_seconds=len(audio)/rate + protocol['tail_seconds'][subset],
                    annotations={name: annotations(directory / name, len(audio)/rate) for name in names})
                if identity in seen:
                    raise ValueError('Duplicate normalized audio in ranked candidates')
                seen.add(identity)
                valid.append(record)
            except Exception as exc:
                record['excluded_reason'] = repr(exc)
            candidates.append(record)
        for record in valid[:protocol['per_arm']]:
            record['selected'] = True
            selected.append(record)
        if len(valid) > protocol['per_arm']:
            smoke.append(valid[protocol['per_arm']])
    complete = all(sum(r['subset'] == subset for r in selected) == protocol['per_arm'] for subset in SUBSETS)
    result = {'schema_version': 1, 'complete': complete, 'root': str(root.resolve()),
        'corpus': 'existing FDB v1.0 assets; not project-level blind test',
        'protocol': protocol, 'protocol_sha256': digest(config), 'candidates': candidates,
        'records': selected, 'smoke': smoke,
        'selection': 'SHA256(seed|subset|sample_id), ascending, unique normalized PCM',
        'conversion': 'mono16k float32 read, clip [-1,1], multiply 32767, little-endian int16',
        'source_version': 'per-file SHA256; upstream dataset revision unavailable'}
    write_json(output / 'manifest.json', result)
    print(json.dumps({'complete': complete, 'selected': len(selected), 'candidates': len(candidates),
                      'manifest_sha256': digest(output / 'manifest.json')}))
    return complete


def derive_manifest(baseline, config, output):
    """Change the control protocol while retaining every frozen input and smoke record."""
    result = json.loads(baseline.read_text())
    protocol = json.loads(config.read_text())
    allowed = {'control_ms', 'assistant_generation_ms', 'playback_tail_ms', 'experiment'}
    original = result['protocol']
    if (not result['complete'] or len(result['records']) != 100 or
            original['control_ms'] != 480 or protocol['control_ms'] != 160 or
            any(protocol.get(k) != original.get(k) for k in set(protocol) | set(original) if k not in allowed)):
        raise ValueError('Expected a 160ms protocol with identical frozen inputs and candidate')
    result.update(protocol=protocol, protocol_sha256=digest(config), baseline_manifest_sha256=digest(baseline),
                  baseline_control_ms=original['control_ms'], baseline_manifest_path=str(baseline.resolve()))
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'manifest.json', result)
    print(json.dumps({'complete': True, 'selected': 100, 'baseline_manifest_sha256': digest(baseline),
                      'manifest_sha256': digest(output / 'manifest.json')}))
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--root', type=Path)
    source.add_argument('--baseline-manifest', type=Path)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    complete = (derive_manifest(args.baseline_manifest, args.config, args.output) if args.baseline_manifest
                else freeze(args.root, args.config, args.output))
    raise SystemExit(0 if complete else 1)
