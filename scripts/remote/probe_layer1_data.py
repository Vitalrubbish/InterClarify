"""Check real published-tokenizer plans on a bounded, verified source shard."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
from layer1_data import (
    DialogueIndex, MicroTurnPlanner, ReleasedTokenizer, SequenceEncoder,
    canonical, digest, file_digest, validate_config, write_json,
)


def probe(args):
    """Report a diagnostic prefix without claiming a full-source training split."""
    config = yaml.safe_load(args.config.read_text())
    validate_config(config)
    source = json.loads(args.source_manifest.read_text())
    if any(source.get(k) != v for k, v in config['source'].items()):
        raise ValueError('Unexpected diagnostic source')
    row = source['files'][0]
    if Path(row['path']).name != row['path']:
        raise ValueError('Invalid shard name')
    path = args.source_dir / row['path']
    if path.stat().st_size != row['size'] or file_digest(path) != row['lfs']['oid']:
        raise ValueError('Diagnostic shard failed verification')
    tokenizer = ReleasedTokenizer(args.tokenizer, config['token_ids'])
    args.output.mkdir(parents=True, exist_ok=False)
    planner = MicroTurnPlanner(tokenizer, config)
    encoder = SequenceEncoder(tokenizer, config, args.max_length)
    index = DialogueIndex(args.output / 'filter.sqlite3', config)
    counts, ids, failures, observed = Counter(), [], [], Counter()
    sequence_count = 0
    try:
        with path.open(encoding='utf-8') as stream:
            for number, line in enumerate(stream, 1):
                item = json.loads(line)
                if index.rejection(item):
                    continue
                identity = str(item['id'])
                dialogue = {'dialogue_id': identity, 'texts': item['data'], 'split': 'diagnostic'}
                plan = planner.plan(dialogue, 0)
                if planner.plan(dialogue, 0) != plan:
                    raise ValueError('Non-deterministic diagnostic plan')
                expected_targets = None
                for view in ('original', 'unpunctuated'):
                    sequences = list(encoder.encode(plan, 'diagnostic', 'diagnostic', view))
                    targets = [x for seq in sequences for x in seq['labels'] if x != -100]
                    if expected_targets is not None and targets != expected_targets:
                        raise ValueError('Punctuation view changed supervision')
                    expected_targets = targets
                    sequence_count += len(sequences)
                    observed[view + '_effective_tokens'] += len(targets)
                counts.update(e['control'] or 'content_only' for e in plan['events'])
                write_json(args.output / (digest(identity) + '.json'), plan)
                ids.append({'dialogue_id': identity, 'source_line': number, 'plan_sha256': digest(plan)})
                if len(ids) >= args.samples:
                    break
        if len(ids) != args.samples:
            raise ValueError('Insufficient valid diagnostic prefix')
        report = {'diagnostic_only': True, 'training_allowed': False, 'full_source_verified': False,
                  'source_shard': row['path'], 'source_sha256': row['lfs']['oid'],
                  'samples': ids, 'dialogues': len(ids), 'sequences': sequence_count,
                  'controls': dict(counts), 'effective_tokens': dict(observed),
                  'tokenizer': tokenizer.fingerprint, 'max_length': args.max_length,
                  'config_sha256': file_digest(args.config), 'failures': failures,
                  'machine_passed': True, 'human_reviewed': False}
        write_json(args.output / 'report.json', report)
        return report
    finally:
        index.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/layer1_data.yaml'))
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=32)
    parser.add_argument('--max-length', type=int, default=4096)
    args = parser.parse_args()
    if not 1 <= args.samples <= 100:
        parser.error('Diagnostic samples must be between 1 and 100')
    report = probe(args)
    print(canonical({k: v for k, v in report.items() if k != 'samples'}))
