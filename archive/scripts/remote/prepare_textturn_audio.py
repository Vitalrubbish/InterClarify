"""Synthesize traceable speech for the frozen TextTurn test source groups."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kokoro_tts_service import KokoroEngine


def prepare(args):
    import soundfile as sf
    from scipy.signal import resample_poly
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('Audio output must be fresh')
    args.output.mkdir(parents=True)
    (args.output / 'audio').mkdir()
    sources = json.loads((args.data / 'source_records.json').read_text())
    plans = [p for p in json.loads((args.data / 'event_plans.json').read_text()) if p['split'] == 'test']
    if args.limit:
        plans = plans[:args.limit]
    engine = KokoroEngine(args.snapshot)
    cache = {}

    def speech(text):
        if text not in cache:
            pcm48 = np.frombuffer(engine.synthesize(text), dtype='<i2').astype(np.float32) / 32768
            cache[text] = resample_poly(pcm48, 1, 3).astype(np.float32)
        return cache[text]

    records = []
    manifest = {'source_type': 'offline_kokoro_synthetic_test_only', 'voice': 'af_heart',
                'dataset_manifest_sha256': hashlib.sha256((args.data / 'manifest.json').read_bytes()).hexdigest(),
                'planned_source_groups': len(plans), 'records': records, 'complete': False}
    for position, plan in enumerate(plans):
        key = plan['source_id']
        source = sources[key]
        texts = source['texts']
        cut = source['pause_boundary']
        prefix = speech(texts[0][:cut])
        suffix = speech(texts[0][cut:].strip())
        silence_seconds = (.48, .96, 1.44)[position % 3]
        pause_samples = int(silence_seconds * 16000)
        question = np.concatenate([prefix, np.zeros(pause_samples, dtype=np.float32), suffix])
        backchannel = plan['phases'][5]['text']
        interruption = plan['phases'][13]['text']
        for category, audio, reference in [
            ('smooth_question_pause', question, texts[0]),
            ('smooth_declarative', speech(texts[2]), texts[2]),
            ('backchannel', speech(backchannel), backchannel),
            ('interruption', speech(interruption), interruption)]:
            relative = f'audio/{key}-{category}.wav'
            path = args.output / relative
            sf.write(path, audio, 16000, subtype='PCM_16')
            records.append({'case_id': f'{key}-{category}', 'source_id': key, 'category': category,
                            'path': relative, 'reference_text': reference,
                            'audio_seconds': len(audio) / 16000,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'pause_start_seconds': len(prefix) / 16000 if category == 'smooth_question_pause' else None,
                            'pause_end_seconds': (len(prefix) + pause_samples) / 16000 if category == 'smooth_question_pause' else None,
                            'pause_prefix_text': texts[0][:cut] if category == 'smooth_question_pause' else None,
                            'utterance_form': 'declarative' if category == 'smooth_declarative' else 'question',
                            'history': [] if category == 'smooth_question_pause' else
                                       [{'role': 'user', 'text': texts[0]}, {'role': 'assistant', 'text': texts[1]}]
                                       if category == 'smooth_declarative' else [{'role': 'user', 'text': texts[0]}],
                            'assistant_text': texts[3] if category == 'smooth_declarative' else texts[1]})
        (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        if sum(p.stat().st_size for p in (args.output / 'audio').iterdir()) > 1024**3:
            raise RuntimeError('Audio asset budget exceeded 1GiB')
        print(json.dumps({'event': 'audio_preparation', 'completed': position + 1, 'planned': len(plans)}), flush=True)
    manifest['complete'] = True
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=0)
    prepare(parser.parse_args())
