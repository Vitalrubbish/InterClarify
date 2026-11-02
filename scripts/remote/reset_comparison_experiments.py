"""Remove explicitly retired comparison experiments while preserving shared assets."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


PROTECTED = {'models', 'envs', 'scoring-models', 'environment', 'wheelhouse', 'upstream', 'cache'}
RETIRED = {'campaigns', 'inspection', 'managers', 'repository', 'runs', 'scripts',
           'source', 'submit_logs', 'tmp'}


def inspect(root):
    expected = Path.home() / 'turncontrol-comparison'
    if root.is_symlink() or root.resolve() != expected.resolve() or root.name != expected.name:
        raise ValueError('Cleanup is restricted to the existing comparison root')
    items = []
    for path in sorted(root.iterdir()):
        if path.name in PROTECTED:
            continue
        if path.name not in RETIRED and path.suffix not in ('.bundle', '.tar'):
            raise ValueError(f'Unknown root entry needs classification: {path.name}')
        items.append(path)
    for directory in (root / 'repository', *sorted((root / 'source').glob('*'))):
        if (directory / '.git').exists():
            result = subprocess.run(['git', '-C', str(directory), 'status', '--porcelain',
                                     '--untracked-files=all'],
                                    text=True, capture_output=True, timeout=20, check=True)
            changes = [line for line in result.stdout.splitlines()
                       if not (line.startswith('?? ') and '__pycache__' in Path(line[3:]).parts
                               and line.endswith(('.pyc', '.pyo')))]
            if changes:
                raise ValueError(f'Uncommitted experiment source: {directory}: {changes[:10]}')
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.home() / 'turncontrol-comparison')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    started = time.monotonic()
    paths = inspect(args.root)
    if args.output.resolve().is_relative_to(args.root.resolve()):
        raise ValueError('Maintenance evidence must be outside the cleanup root')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError('Do not overwrite a previous cleanup record')
    record = {'created_at': datetime.now(timezone.utc).isoformat(), 'root': str(args.root),
              'execute': args.execute, 'preserved': sorted(PROTECTED),
              'planned': [p.name for p in paths], 'removed': [], 'bytes_in_removed_files': 0,
              'free_bytes_before': shutil.disk_usage(args.root).free}
    def save():
        args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    save()
    try:
        if args.execute:
            for path in paths:
                count, size = 0, 0
                if path.is_dir() and not path.is_symlink():
                    for base, directories, files in os.walk(path, followlinks=False):
                        for name in files:
                            size += (Path(base) / name).lstat().st_size
                            count += 1
                        if time.monotonic() - started > 600:
                            raise TimeoutError('Comparison cleanup exceeded ten minutes')
                    shutil.rmtree(path)
                else:
                    size, count = path.lstat().st_size, 1
                    path.unlink()
                record['removed'].append({'name': path.name, 'files': count, 'bytes': size})
                record['bytes_in_removed_files'] += size
                save()
        record['remaining'] = sorted(p.name for p in args.root.iterdir())
        record['free_bytes_after'] = shutil.disk_usage(args.root).free
        record['elapsed_seconds'] = time.monotonic() - started
        record['passed'] = not args.execute or set(record['remaining']) <= PROTECTED
    except Exception as exc:
        record.update(passed=False, error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        save()
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
