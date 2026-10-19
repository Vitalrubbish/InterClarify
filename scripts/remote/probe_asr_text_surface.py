"""Probe the deployed Nemotron text surface on a few bounded audio files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from nemotron_asr_service import AudioBuffer, NativeNemotron, load_pcm16


def probe(manifest_path: Path, model_path: Path, output_path: Path):
    cases = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(cases, list) or not 1 <= len(cases) <= 12:
        raise ValueError('Probe manifest must contain 1–12 cases')
    for case in cases:
        if not isinstance(case, dict) or not all(k in case for k in ('name', 'audio', 'spoken_script')):
            raise ValueError('Each case needs name, audio and spoken_script')
    engine = NativeNemotron(str(model_path))
    results = []
    for case in cases:
        path = Path(case['audio'])
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f'Probe audio exceeds 2 MiB: {path}')
        pcm = load_pcm16(path)
        samples = len(pcm) // 2
        if not 0 < samples <= 30 * 16000:
            raise ValueError(f'Probe audio must be 0–30 seconds: {path}')
        source = AudioBuffer()
        source.append(pcm, eof=True)
        outputs = []
        started = time.monotonic()
        engine.run(source, lambda text, ids: outputs.append({'text': text, 'ids': ids}))
        results.append({
            'name': case['name'], 'spoken_script': case['spoken_script'],
            'source_type': case.get('source_type', 'synthetic_probe'),
            'audio_path': str(path), 'audio_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'audio_seconds': samples / 16000, 'final_text': outputs[-1]['text'] if outputs else '',
            'updates': outputs, 'decode_seconds': time.monotonic() - started,
        })
    report = {'model': engine.info, 'probe_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              'cases': results, 'training_source': False}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + '.part')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(output_path)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.manifest, args.model, args.output)
    print(json.dumps({'cases': len(result['cases']), 'output': str(args.output)}, ensure_ascii=False))
