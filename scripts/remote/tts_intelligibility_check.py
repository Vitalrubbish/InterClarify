"""Transcribe saved TTS WAVs with a fixed, offline ASR for intelligibility checks."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import re
from collections import defaultdict
from pathlib import Path


def words(text):
    """Normalize punctuation and case without changing the expected wording."""
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())


def edit_counts(reference, hypothesis):
    """Return minimum word edits with separate substitution/deletion/insertion."""
    expected, actual = words(reference), words(hypothesis)
    previous = [(i, 0, 0, i) for i in range(len(actual) + 1)]
    for i, ref in enumerate(expected, 1):
        current = [(i, 0, i, 0)]
        for j, hyp in enumerate(actual, 1):
            if ref == hyp:
                current.append(previous[j - 1])
                continue
            candidates = []
            for value, offset in ((previous[j - 1], 1), (previous[j], 2), (current[j - 1], 3)):
                changed = list(value)
                changed[0] += 1
                changed[offset] += 1
                candidates.append(tuple(changed))
            current.append(min(candidates))
        previous = current
    edits, substitutions, deletions, insertions = previous[-1]
    return {'reference_words': len(expected), 'errors': edits,
            'substitutions': substitutions, 'deletions': deletions, 'insertions': insertions}


def summarize(rows):
    """Keep failures separate and use total reference words as the WER denominator."""
    result = {}
    for name in sorted({row['arm'] for row in rows}):
        group = [row for row in rows if row['arm'] == name]
        valid = [row for row in group if row['error'] is None]
        count = sum(row['edits']['reference_words'] for row in valid)
        errors = sum(row['edits']['errors'] for row in valid)
        result[name] = {'attempts': len(group), 'failures': len(group) - len(valid),
                        'reference_words': count, 'word_errors': errors,
                        'wer': errors / count if count else None,
                        'exact_sentences': sum(row['edits']['errors'] == 0 for row in valid)}
    return result


def digest(path):
    """Hash a model or audio file without reading it all into Python memory."""
    sha = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def run(args):
    """Use only pre-existing model files and preserve every transcription result."""
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from transformers import pipeline

    lock = json.loads(args.lock.read_text())['nemotron_en']
    if args.model.resolve() != Path(lock['path']).resolve():
        raise ValueError('ASR model differs from the fixed lock path')
    for name in ('config.json', 'model.safetensors'):
        if digest(args.model / name) != lock['files'][name]:
            raise ValueError(f'ASR file digest differs: {name}')
    args.output.mkdir(parents=True, exist_ok=False)
    metadata = {'model': lock, 'dependencies': {name: importlib.metadata.version(name)
        for name in ('torch', 'transformers', 'soundfile', 'scipy')},
        'note': 'ASR diagnostic only; not human naturalness or runtime integration acceptance.'}
    (args.output / 'manifest.json').write_text(json.dumps(metadata, indent=2))
    recognizer = pipeline('automatic-speech-recognition', model=str(args.model), device=0)
    corpus = {row['id']: row['text'] for row in
              (json.loads(line) for line in (args.screen / 'screen_corpus.jsonl').read_text().splitlines())}
    cache, rows = {}, []
    paths = [(path, '') for path in sorted(args.screen.glob('*/measured/responses.jsonl'))]
    if args.extra_screen:
        paths += [(path, '_retest') for path in sorted(args.extra_screen.glob('*/measured/responses.jsonl'))]
    for path, suffix in paths:
        arm = path.parent.parent.name + suffix
        for source in (json.loads(line) for line in path.read_text().splitlines()):
            row = {'arm': arm, 'id': source['id'], 'mode': source['mode'], 'repeat': source['repeat'],
                   'response_id': source['response_id'], 'expected': corpus[source['id']],
                   'transcript': None, 'edits': None, 'error': None}
            wav = path.parent / f"{source['id']}_{source['mode']}_{source['repeat']}.wav"
            try:
                if source['error'] or not source['samples']:
                    raise ValueError('TTS response failed or had no audio')
                checksum = digest(wav)
                if checksum not in cache:
                    data, rate = sf.read(wav, dtype='float32', always_2d=True)
                    data = data.mean(axis=1)
                    if rate != 16000:
                        divisor = math.gcd(rate, 16000)
                        data = resample_poly(data, 16000 // divisor, rate // divisor).astype(np.float32)
                    cache[checksum] = recognizer({'array': data, 'sampling_rate': 16000})['text']
                row['transcript'] = cache[checksum]
                row['edits'] = edit_counts(row['expected'], row['transcript'])
            except Exception as error:
                row['error'] = f'{type(error).__name__}: {error}'
            rows.append(row)
            with (args.output / 'transcripts.jsonl').open('a') as handle:
                handle.write(json.dumps(row) + '\n')
            print(json.dumps({'completed': len(rows), 'arm': arm, 'id': source['id'], 'error': row['error']}), flush=True)
    summary = {'arms': summarize(rows), 'responses': len(rows), 'unique_audio': len(cache),
               'note': metadata['note'], 'by_mode': {mode: summarize([row for row in rows if row['mode'] == mode])
                   for mode in sorted({row['mode'] for row in rows})}}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2))
    return int(not rows or any(row['error'] for row in rows))


def main():
    """Run in the existing ASR conda environment on an allocated GPU."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('screen', 'model', 'lock', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--extra-screen', type=Path, help='Additional isolated paired retest; label arms with _retest')
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
