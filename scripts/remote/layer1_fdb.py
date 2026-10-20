"""Stage the frozen FDB subset and run the existing real-audio full-chain driver."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace


def file_hash(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def prepare(manifest_path, output):
    manifest = json.loads(manifest_path.read_text())
    if (manifest['sessions'], len(manifest['samples'])) != (25, 25):
        raise ValueError('Expected exactly the frozen 25 FDB sessions')
    if len({s['input'] for s in manifest['samples']}) != 25:
        raise ValueError('Duplicate FDB input')
    root = Path(manifest['remote_root'])
    checked = []
    for sample in manifest['samples']:
        relative = Path(sample['input'])
        if relative.is_absolute() or '..' in relative.parts or relative.name != 'input.wav':
            raise ValueError('Unsafe FDB input path')
        for name, record in sample['files'].items():
            if Path(name).name != name or name in ('output.wav', 'output.json', 'clean_output.wav', 'clean_output.json'):
                raise ValueError('Unsafe or historical generated FDB artifact')
            path = root / relative.parent / name
            if path.stat().st_size != record['bytes'] or file_hash(path) != record['sha256']:
                raise ValueError('Frozen FDB asset changed: ' + str(path))
            checked.append((path, relative.parent / name))
    output.mkdir(parents=True, exist_ok=False)
    for source, relative in checked:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    actual = {str(p.relative_to(output)) for p in output.rglob('input.wav')}
    if actual != {s['input'] for s in manifest['samples']}:
        raise ValueError('Staged FDB inputs differ from manifest')
    return {'manifest_sha256': file_hash(manifest_path), 'sessions': len(actual), 'files': len(checked)}


async def run(args):
    from duplex_a4_replay import run_fdb_batch
    config = json.loads(args.config.read_text())
    config['asr']['params']['base_url'] = args.asr_url
    config['tts']['params']['base_url'] = args.tts_url
    config['service_config']['duplex_timeout_seconds'] = 120
    args.output.mkdir(parents=True, exist_ok=False)
    config_path = args.output / 'runtime.json'
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    summaries = []
    subsets = ('candor_pause_handling', 'synthetic_pause_handling', 'candor_turn_taking',
               'synthetic_user_interruption', 'icc_backchannel')
    for subset in subsets:
        parameters = SimpleNamespace(config=config_path, model_url=args.model_url,
            out=args.output / 'driver' / subset, fdb_input_root=args.input / subset,
            fdb_output_root=args.output / 'fdb' / subset, fdb_limit=0, fdb_tail_seconds=5.0,
            fdb_tail_audio=True, timeout=240.0, server_timeout=120.0)
        result = await run_fdb_batch(parameters)
        summaries.append({'subset': subset, 'status': result['status'], 'sessions': len(result['samples'])})
        (args.output / 'progress.json').write_text(json.dumps(summaries, indent=2) + '\n')
        print(json.dumps(summaries[-1]), flush=True)
    passed = all(s['status'] == 'PASS' and s['sessions'] == 5 for s in summaries)
    (args.output / 'summary.json').write_text(json.dumps({'transport_passed': passed,
        'subsets': summaries, 'sessions': sum(s['sessions'] for s in summaries),
        'official_scoring': 'pending', 'manual_content_review': 'pending',
        'physical_playback_measured': False}, indent=2) + '\n')
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    stage = sub.add_parser('prepare')
    stage.add_argument('--manifest', type=Path, required=True)
    stage.add_argument('--output', type=Path, required=True)
    replay = sub.add_parser('run')
    for name in ('input', 'output', 'config'):
        replay.add_argument('--' + name, type=Path, required=True)
    for name in ('asr-url', 'tts-url', 'model-url'):
        replay.add_argument('--' + name, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        print(json.dumps(prepare(args.manifest, args.output)))
    else:
        raise SystemExit(asyncio.run(run(args)))


if __name__ == '__main__':
    main()
