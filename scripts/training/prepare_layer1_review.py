"""Export pending human review cards from frozen, machine-audited Layer 1 data."""

from __future__ import annotations

import argparse
import copy
from collections import defaultdict
import html
import json
from pathlib import Path

from layer1_data import ReleasedTokenizer, canonical, digest, file_digest, write_json


BEHAVIORS = ('user_continuation', 'natural_pause', 'response_start', 'interruption',
             'user_backchannel', 'post_response_thinking')


def choose_events(candidates, seed, per_behavior, double_per_behavior):
    """Select different dialogues within each behavior using registered split quotas."""
    if per_behavior < 1 or not 0 <= double_per_behavior <= per_behavior:
        raise ValueError('Invalid human-review sampling budget')
    train, dev = per_behavior * 3 // 5, per_behavior // 5
    quotas = {'train': train, 'dev': dev, 'test': per_behavior - train - dev}
    pools = defaultdict(dict)
    for row in candidates:
        if row['behavior'] not in BEHAVIORS or row['split'] not in quotas:
            raise ValueError('Unknown review behavior or split')
        rank = digest([seed, row['behavior'], row['split'], row['dialogue_id'], row['event_id']])
        ranked = {**row, 'selection_rank': rank}
        key = row['behavior'], row['split']
        old = pools[key].get(row['dialogue_id'])
        if old is None or rank < old['selection_rank']:
            pools[key][row['dialogue_id']] = ranked
    selected, coverage = [], []
    for behavior in BEHAVIORS:
        group = []
        for split, requested in quotas.items():
            available = sorted(pools[behavior, split].values(), key=lambda r: r['selection_rank'])
            chosen = available[:requested]
            coverage.append({'behavior': behavior, 'split': split, 'requested': requested,
                             'available_dialogues': len(available), 'selected': len(chosen)})
            group.extend(chosen)
        group.sort(key=lambda r: r['selection_rank'])
        for index, row in enumerate(group):
            row['required_reviewers'] = 2 if index < double_per_behavior else 1
            row['reviews'] = [{'reviewer': None, 'accepted': None, 'reason': None}
                              for _ in range(row['required_reviewers'])]
        selected.extend(group)
    return selected, coverage


def cell(value):
    text = html.escape(str(value))
    for marker in ('\\', '|', '`', '[', ']', '*', '!'):
        text = text.replace(marker, '\\' + marker)
    return text.replace('\r', '').replace('\n', '<br>')


def render_card(dialogue, artifact, tokenizer, event_ids=None):
    """Show source context and both user views; no approval is produced automatically."""
    lines = [f"### {cell(dialogue['dialogue_id'])} ({dialogue['split']})", '',
             '原始对话（仅用于离线核查，不代表模型每拍可见全部文本）：', '']
    for turn, text in enumerate(dialogue['texts']):
        lines.append(f"- {turn} {'user' if turn % 2 == 0 else 'assistant'}：{cell(text)}")
    lines += ['', '| event | 行为 | 用户原样 | 用户去句读 | 控制 | assistant正文 |',
              '| --- | --- | --- | --- | --- | --- |']
    for event in artifact['plan']['events']:
        if event_ids is not None and event['event_id'] not in event_ids:
            continue
        lines.append('| ' + ' | '.join(cell(x) for x in (
            event['event_id'], event['kind'], event['user_text'], event['user_unpunctuated'],
            event['control'], tokenizer.decode(event['assistant_ids']))) + ' |')
    return '\n'.join(lines) + '\n'


def prepare(args):
    """Bind review samples to exact data artifacts and leave all human labels pending."""
    root = args.dataset
    manifest = json.loads((root / 'manifest.json').read_text())
    audit = json.loads(args.audit.read_text())
    if not manifest.get('complete') or not audit.get('machine_passed'):
        raise ValueError('A complete build and successful machine audit are required')
    if audit['manifest_sha256'] != file_digest(root / 'manifest.json'):
        raise ValueError('Audit refers to a different dataset manifest')
    selected_path = root / 'dialogues.json'
    if file_digest(selected_path) != manifest['selected_sha256']:
        raise ValueError('Selected source dialogues changed')
    dialogues = json.loads(selected_path.read_text())
    config = manifest['identity']['config']
    tokenizer = ReleasedTokenizer(args.tokenizer, config['token_ids'])
    if tokenizer.fingerprint != manifest['identity']['tokenizer']:
        raise ValueError('Review tokenizer differs from the dataset')
    args.output.mkdir(parents=True, exist_ok=False)
    candidates, minimum_cards, minimum = [], [], []
    for dialogue in dialogues:
        relative = 'dialogues/' + digest(dialogue['dialogue_id']) + '.json'
        path = root / relative
        checksum = file_digest(path)
        if checksum != manifest['artifacts'].get(relative):
            raise ValueError('Review artifact checksum mismatch')
        artifact = json.loads(path.read_text())
        if dialogue['split'] == 'train' and len(minimum) < 32:
            minimum.append({'dialogue_id': dialogue['dialogue_id'], 'artifact': relative,
                            'sha256': checksum, 'reviewer': None, 'accepted': None, 'reason': None})
            minimum_cards.append(render_card(dialogue, artifact, tokenizer))
        best = {}
        for event in artifact['plan']['events']:
            if event['kind'] in BEHAVIORS:
                row = {'dialogue_id': dialogue['dialogue_id'], 'split': dialogue['split'],
                       'behavior': event['kind'], 'event_id': event['event_id'],
                       'artifact': relative, 'sha256': checksum}
                rank = digest([args.seed, row['behavior'], row['split'], row['dialogue_id'], row['event_id']])
                if event['kind'] not in best or rank < best[event['kind']][0]:
                    best[event['kind']] = (rank, row)
        candidates.extend(row for rank, row in best.values())
    events, coverage = choose_events(candidates, args.seed, args.per_behavior, args.double_per_behavior)
    template = {'schema_version': 1, 'minimum_set': minimum, 'expanded_behavior_reviews': events,
                'complete': False}
    write_json(args.output / 'human_review_template.json', template)
    write_json(args.output / 'selection.json', {'seed': args.seed, 'coverage': coverage,
        'events': events, 'manifest_sha256': file_digest(root / 'manifest.json'),
        'auditor_report_sha256': file_digest(args.audit), 'human_review_complete': False})
    (args.output / 'minimum_32.md').write_text('# 最小训练集完整人工审查\n\n'
        '逐条检查原文跨度、等待/接话、插话丢弃旧回答、附和继续、句读保护和目标一致性。以下全部待人工签署。\n\n'
        + '\n'.join(minimum_cards), encoding='utf-8')
    lookup = {d['dialogue_id']: d for d in dialogues}
    cards = []
    for event in events:
        artifact = json.loads((root / event['artifact']).read_text())
        ids = set(range(max(0, event['event_id'] - 2), event['event_id'] + 3))
        cards.append(f"抽查行为：{event['behavior']}；目标event：{event['event_id']}；需{event['required_reviewers']}名人工审查者。\n\n"
                     + render_card(lookup[event['dialogue_id']], artifact, tokenizer, ids))
    (args.output / 'expanded_samples.md').write_text('# 正式数据分层抽查\n\n'
        '这些事件来自已生成数据，不新增训练数据或曝光；与前32条完整审查分别记录。\n\n'
        + '\n'.join(cards), encoding='utf-8')
    summary = {'minimum_dialogues': len(minimum), 'expanded_events': len(events),
        'double_review_events': sum(row['required_reviewers'] == 2 for row in events),
        'coverage': coverage, 'sampling_budget_met': all(c['requested'] == c['selected'] for c in coverage),
        'human_review_complete': False, 'training_allowed': False,
        'code_sha256': file_digest(__file__)}
    write_json(args.output / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261018)
    parser.add_argument('--per-behavior', type=int, default=20)
    parser.add_argument('--double-per-behavior', type=int, default=4)
    print(canonical(prepare(parser.parse_args())))
