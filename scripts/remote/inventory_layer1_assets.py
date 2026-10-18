"""Inventory local Layer 1 assets without importing or loading a model."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import struct
import subprocess
import sys


def file_record(path: Path) -> dict:
    """Hash a file in bounded memory and reject concurrent modifications."""
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if identity(before) != identity(after):
        raise ValueError(f'File changed during inventory: {path}')
    record = {'bytes': after.st_size, 'sha256': digest.hexdigest()}
    if path.is_symlink():
        record['symlink_target'] = str(path.resolve())
    if path.suffix == '.safetensors':
        with path.open('rb') as stream:
            size_bytes = stream.read(8)
            if len(size_bytes) != 8:
                raise ValueError(f'Truncated safetensors file: {path}')
            size = struct.unpack('<Q', size_bytes)[0]
            if size > 100 * 1024 * 1024 or size > after.st_size - 8:
                raise ValueError(f'Invalid safetensors header length: {path}')
            header = json.loads(stream.read(size))
        record['tensors'] = {key: value for key, value in header.items() if key != '__metadata__'}
    return record


def git_record(root: Path) -> dict:
    """Record a checkout identity and the actual tracked/untracked source bytes."""
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args])
    revision = git('rev-parse', 'HEAD').decode().strip()
    status = git('status', '--short', '--untracked-files=all').decode()
    names = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')
    files = {}
    for name in sorted(set(names) - {''}):
        path = root / name
        if path.is_file():
            files[name] = file_record(path)
        elif not path.exists():
            files[name] = {'deleted': True}
    return {'path': str(root.resolve()), 'revision': revision, 'status': status, 'files': files}


def asset_record(root: Path) -> dict:
    """Scan all regular asset files and retain failures without declaring readiness."""
    if not root.exists():
        raise FileNotFoundError(root)
    paths = [root] if root.is_file() else sorted(
        path for path in root.rglob('*') if '.git' not in path.relative_to(root).parts
        and (path.is_file() or path.is_symlink()))
    files, errors = {}, []
    for path in paths:
        name = path.name if root.is_file() else str(path.relative_to(root))
        try:
            files[name] = file_record(path)
        except (OSError, ValueError) as exc:
            errors.append({'path': name, 'error': str(exc)})
    if not files:
        errors.append({'path': str(root), 'error': 'No readable files'})
    return {'path': str(root.resolve()), 'files': files, 'errors': errors}


def main() -> int:
    """Write an exclusive inventory directory and return nonzero on missing evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--xtalk', type=Path, required=True)
    parser.add_argument('--asset', action='append', default=[], metavar='NAME=PATH')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assets = {}
    for item in args.asset:
        name, separator, value = item.partition('=')
        if not separator or not name or not value or name in assets:
            parser.error('Each asset must have a unique nonempty NAME=PATH')
        assets[name] = Path(value)
    if not assets:
        parser.error('At least one --asset is required')
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'created_utc': datetime.now(timezone.utc).isoformat(),
              'python': sys.version, 'executable': sys.executable,
              'platform': platform.platform(), 'packages': {},
              'repositories': {}, 'assets': {}, 'errors': [],
              'training_released': False,
              'note': 'File inventory only; revisions, licenses, token IDs and runtime gates require review.'}
    result['packages'] = dict(sorted((dist.metadata['Name'], dist.version)
                                    for dist in importlib.metadata.distributions() if dist.metadata['Name']))
    for name, root in [('interclarify', args.repo), ('xtalk', args.xtalk)]:
        try:
            result['repositories'][name] = git_record(root)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            result['errors'].append({'repository': name, 'error': str(exc)})
    for name, root in assets.items():
        try:
            record = asset_record(root)
            result['assets'][name] = record
            result['errors'].extend({'asset': name, **error} for error in record['errors'])
        except (OSError, ValueError) as exc:
            result['errors'].append({'asset': name, 'error': str(exc)})
    code = int(bool(result['errors']))
    result['exit_code'] = code
    (args.output / 'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (args.output / 'exit_code.txt').write_text(f'{code}\n')
    print(json.dumps({'output': str(args.output), 'exit_code': code, 'errors': result['errors']}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
