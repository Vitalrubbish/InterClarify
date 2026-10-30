"""Check complete weighted trajectories before the authorized remote training."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'training'))
from freeze_textturn_full_trajectories import file_hash
from train_textturn import register_dataset_tokens
from textturn_loss import stage_loss_weights
from transformers import AutoTokenizer


def audit(data, base, training_config):
    m = json.loads((data / 'manifest.json').read_text())
    b = json.loads((base / 'manifest.json').read_text())
    assert m['complete_trajectories'] and m['training_allowed']
    assert file_hash(base / 'manifest.json') == m['base_manifest_sha256']
    for root, manifest in ((data, m), (base, b)):
        for name, expected in manifest['files'].items():
            assert file_hash(root / name) == expected, (root, name)
    assert file_hash(ROOT / 'scripts/training/freeze_textturn_full_trajectories.py') == m['freezer_sha256']
    assert file_hash(ROOT / 'scripts/training/build_textturn_duplex_dataset.py') == m['builder_sha256']
    config = json.loads(training_config.read_text())
    assert config['loss_policy'] == m['loss_policy']
    tokenizer = AutoTokenizer.from_pretrained(data, local_files_only=True)
    assert register_dataset_tokens(tokenizer, m) == list(m['new_token_ids'].values())
    finish = m['new_token_ids']['<finish>']
    base_signatures = {}
    for line in (base / 'timelines.jsonl').open():
        trace = json.loads(line)
        base_signatures[trace['scenario_id']] = hashlib.sha256(line.encode()).hexdigest()
    expected_counts = {}
    for line in (data / 'timelines.jsonl').open():
        trace = json.loads(line)
        sid = trace['scenario_id']
        assert hashlib.sha256(line.encode()).hexdigest() == base_signatures[sid]
        expected_counts[sid] = sum(e['kind'] == 'control_request' for e in trace['events'])
    index = json.loads((data / 'split_index.json').read_text())
    original_index = json.loads((base / 'split_index.json').read_text())
    assert all(item in original_index for item in index)
    train_groups = {i['duplicate_group'] for i in index if i['split'] == 'train'}
    dev_groups = {i['duplicate_group'] for i in index if i['split'] == 'dev'}
    assert not train_groups & dev_groups
    assert {i['source_id'] for i in index if i['split'] == 'dev'} == {
        i['source_id'] for i in original_index if i['split'] == 'dev'}
    counts, ids, finish_counts, stage_weights = {}, {}, Counter(), {}
    for split, filename in m['split_files'].items():
        windows = Counter()
        categories, weight_mass = Counter(), defaultdict(float)
        keep_counts, keep_masses = Counter(), defaultdict(float)
        keep_ranges, weight_rows = {}, []
        row_ids, source_forms = {}, defaultdict(set)
        clocks = {}
        with gzip.open(data / filename, 'rt', encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                sid = row['scenario_id']
                assert row['snapshot_id'] == f'{sid}:{windows[sid]}'
                windows[sid] += 1
                assert row['visible_ms'] > clocks.get(sid, -1)
                clocks[sid] = row['visible_ms']
                assert row['excluded_reason'] is None
                weight = row['loss_weight']
                assert math.isfinite(weight) and weight > 0
                action = row['target_action']
                expected = m['action_token_ids'][action]
                assert [v for v in row['labels'] if v != -100] == [expected]
                assert len(row['input_ids']) == len(row['labels']) <= 2048
                assert tokenizer.encode(row['prompt'], add_special_tokens=False) == row['input_ids'][:-1]
                assert 'loss_weight' not in row['visible'] and 'annotation' not in row['visible']
                positions = [i for i,v in enumerate(row['input_ids']) if v == finish]
                assert all(row['labels'][i] == -100 for i in positions)
                finish_counts[split] += bool(positions)
                categories[action] += 1
                weight_mass[action] += weight
                if split in ('train', 'pilot'):
                    weight_rows.append({'target_action': action, 'loss_weight': weight})
                if action == 'keep':
                    key = sid, row['visible']['state'], row['category']
                    keep_counts[key] += 1
                    keep_masses[key] += weight
                    lo, hi = keep_ranges.get(key, (weight, weight))
                    keep_ranges[key] = min(lo, weight), max(hi, weight)
                else:
                    assert weight == m['loss_policy']['action_weights'][action]
                source_forms[row['source_id']].add((row['utterance_form'],row['scenario_variant']))
                assert row['snapshot_id'] not in row_ids
                row_ids[row['snapshot_id']] = hashlib.sha256(line.encode()).hexdigest()
        assert all(windows[sid] == expected_counts[sid] for sid in windows)
        assert all(len(forms) == 4 for forms in source_forms.values())
        for key, n in keep_counts.items():
            assert math.isclose(keep_masses[key], min(n,m['loss_policy']['keep_group_budget']), abs_tol=1e-9)
            expected_weight = min(1., m['loss_policy']['keep_group_budget'] / n)
            assert all(math.isclose(w, expected_weight, abs_tol=1e-12) for w in keep_ranges[key])
        assert dict(categories) == m['statistics'][split]['actions']
        assert len(row_ids) == m['statistics'][split]['snapshots']
        assert math.isclose(sum(weight_mass.values()) / len(row_ids),
                            m['statistics'][split]['mean_weight'], rel_tol=1e-9)
        counts[split] = {'windows':len(row_ids), 'trajectories':len(windows), 'sources':len(source_forms)}
        ids[split] = row_ids
        if split in ('train', 'pilot'):
            _, summary = stage_loss_weights(weight_rows, config.get('loss_balance'))
            if config.get('loss_balance') is not None:
                for action, share in config['loss_balance']['action_shares'].items():
                    assert math.isclose(summary['action_weight_mass'][action], len(weight_rows) * share, rel_tol=1e-9)
            stage_weights[split] = summary
    assert counts['train']['windows'] <= 10000 and counts['pilot']['windows'] <= 2000
    assert all(ids['train'][sid] == digest for sid,digest in ids['pilot'].items())
    prefix = 'tt-010-duplex160-r2:91459:question:normal:'
    assert sum(sid.startswith(prefix) for sid in ids['train']) == 70
    assert len(ids['train']) + len(ids['dev']) == sum(expected_counts.values())
    result = {'status':'passed','manifest_sha256':file_hash(data/'manifest.json'),
              'complete_trajectories':True,'statistics':counts,'all_weights_positive':True,
              'keep_group_weight_budget_verified':True,'reviewed_example_windows':70,
              'finish_input_snapshots':dict(finish_counts),'base_events_unchanged':True,
              'pilot_contains_only_whole_train_sources':True,'training_config_sha256':file_hash(training_config)}
    result.update(frozen_loss_helper_sha256=m['loss_helper_sha256'],
                  active_loss_helper_sha256=file_hash(ROOT / 'scripts/training/textturn_loss.py'),
                  stage_loss_weights=stage_weights)
    (data/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--training-config',type=Path,default=Path('configs/textturn_full_trajectory_training.json'))
    args = parser.parse_args()
    print(json.dumps(audit(args.data,args.base,args.training_config),ensure_ascii=False,indent=2))
