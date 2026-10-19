"""Inventory held-out sources and hash available text without requiring FDB transcripts."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import yaml

from layer1_data import digest, file_digest, normalized, write_json


def extract_text(value, keys, ignored):
    """Read only registered text fields; never hash labels or arbitrary metadata."""
    if isinstance(value, list):
        return [text for item in value for text in extract_text(item, keys, ignored)]
    if not isinstance(value, dict):
        return []
    result = []
    for key, item in value.items():
        if key in keys and isinstance(item, str) and item.strip() and item.strip() not in ignored:
            result.append(item.strip())
        elif isinstance(item, (dict, list)):
            result.extend(extract_text(item, keys, ignored))
    return result


def build(args):
    """Separate required source coverage from optional FDB text overlap checks."""
    config = yaml.safe_load(args.config.read_text())
    if config['schema_version'] != 1:
        raise ValueError('Unsupported exclusion schema')
    hashes, sources, missing, records = set(), [], [], []
    optional_text_missing = []
    counts = Counter()
    source_digests = {}

    def consume(path, scope, identity, supplied=None):
        payload = json.loads(path.read_text()) if supplied is None else supplied
        texts = extract_text(payload, set(config['text_keys']), set(config['ignored_markers']))
        if isinstance(payload, dict) and payload.get('word_events'):
            texts.append(' '.join(str(event['text']).strip() for event in payload['word_events']))
        texts = [t for t in texts if normalized(t)]
        if texts:
            hashes.update(digest(normalized(t)) for t in texts)
            hashes.add(digest(normalized(' '.join(texts))))
        if str(path) not in source_digests:
            source_digests[str(path)] = file_digest(path)
        records.append({'scope': scope, 'sample_id': identity, 'path': str(path),
                        'sha256': source_digests[str(path)], 'text_units': len(texts)})
        return texts

    fleurs = json.loads(args.fleurs_manifest.read_text())
    samples = fleurs.get('samples', [])
    counts['fleurs'] = len(samples)
    counts['fleurs_test'] = sum(row.get('split', 'test') == 'test' for row in samples)
    if counts['fleurs_test'] != config['fleurs_count']:
        missing.append({'scope': 'fleurs', 'reason': 'test_sample_count', 'actual': counts['fleurs_test']})
    identities = set()
    for row in samples:
        identity = row['sample_id']
        if identity in identities:
            raise ValueError('Duplicate FLEURS sample identity')
        identities.add(identity)
        if not consume(args.fleurs_manifest, 'fleurs', identity, row):
            missing.append({'scope': 'fleurs', 'sample_id': identity, 'reason': 'no_text'})
    sources.append(str(args.fleurs_manifest))

    history = json.loads(args.historical_manifest.read_text())
    cases = history.get('cases', history.get('samples', []))
    if isinstance(cases, dict):
        cases = [{'case_id': key, **value} for key, value in cases.items()]
    counts['historical'] = len(cases)
    if len(cases) != config['historical_count']:
        missing.append({'scope': 'historical', 'reason': 'sample_count', 'actual': len(cases)})
    for i, row in enumerate(cases):
        if not consume(args.historical_manifest, 'historical', row.get('case_id', row.get('id', str(i))), row):
            missing.append({'scope': 'historical', 'sample_id': str(i), 'reason': 'no_text'})
    sources.append(str(args.historical_manifest))

    for subset, expected in config['fdb_counts'].items():
        root = args.fdb_root / subset
        directories = sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []
        counts['fdb/' + subset] = len(directories)
        if len(directories) != expected:
            missing.append({'scope': 'fdb/' + subset, 'reason': 'sample_count', 'actual': len(directories)})
        for directory in directories:
            texts = []
            for path in sorted(directory.glob('*.json')):
                texts.extend(consume(path, 'fdb/' + subset, directory.name))
            if texts:
                hashes.add(digest(normalized(' '.join(texts))))
            else:
                optional_text_missing.append({'scope': 'fdb/' + subset, 'sample_id': directory.name, 'reason': 'no_text'})
        sources.append(str(root))
    result = {'schema_version': 1, 'ids': [], 'normalized_hashes': sorted(hashes),
              'source_refs': sources, 'reviewed': not missing, 'coverage_complete': not missing,
              'review_scope': 'source_inventory_and_available_text',
              'text_coverage_complete': not missing and not optional_text_missing,
              'optional_text_missing': optional_text_missing,
              'fdb_transcription_required': False,
              'namespace_policy': 'external_ids_are_provenance_only_not_ultrachat_ids',
              'match_scope': 'normalized_each_text_unit_and_concatenated_sample',
              'coverage': dict(counts), 'missing': missing, 'records': records,
              'config_sha256': file_digest(args.config), 'builder_sha256': file_digest(__file__),
              'fleurs_source': {k: fleurs.get(k) for k in ('repo', 'revision', 'selection')},
              'training_allowed': False}
    write_json(args.output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/layer1_exclusions.yaml'))
    parser.add_argument('--fleurs-manifest', type=Path, required=True)
    parser.add_argument('--historical-manifest', type=Path, required=True)
    parser.add_argument('--fdb-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args)
    print(json.dumps({'reviewed': result['reviewed'], 'coverage': result['coverage'],
                      'missing': len(result['missing']), 'hashes': len(result['normalized_hashes'])}))
