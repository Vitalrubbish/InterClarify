"""Freeze a bounded, source-disjoint TextTurn corpus with explicit synthetic timing."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import unicodedata

from build_textturn_dataset import (
    ACTIONS, MODEL_REVISION, SOURCE_REVISION, ControlTokenizer, compile_scenario,
    digest, seeded_rng, write_json,
)

SOURCE_SIZE = 963569677
SOURCE_SHA256 = '83e8bf5ad58dad37317e20daf8dd8fcdf483a8ff29ba73351a47cad3c2cad368'
HISTORY_REVISION = '38315aa^'
QUESTION_PREFIX = re.compile(
    r'^(?:How (?:can|do|does|is|are)|What (?:is|are|can|do|does)|Can you|Could you|'
    r'Why (?:is|are|do|does)|Are there|Is there|Do you)\b')
DECLARATION_PREFIX = re.compile(
    r'^(?:I (?:would like|want|need|think|believe|have|am)|My |That |This |It |The |We |Wow[,!] |Yeah[,!] )')


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def fetch_source(path, endpoint='https://huggingface.co'):
    """Resume a full pinned shard and accept only its published LFS digest."""
    import requests
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(path.suffix + '.part')
        start = temporary.stat().st_size if temporary.exists() else 0
        if start > SOURCE_SIZE:
            raise ValueError('Partial source exceeds frozen size')
        url = f'{endpoint}/datasets/openbmb/UltraChat/resolve/{SOURCE_REVISION}/train_0.jsonl?download=true'
        with requests.get(url, headers={'Range': f'bytes={start}-'} if start else {},
                          stream=True, timeout=(30, 90)) as response:
            response.raise_for_status()
            if response.status_code == 206:
                if response.headers.get('Content-Range') != f'bytes {start}-{SOURCE_SIZE - 1}/{SOURCE_SIZE}':
                    raise ValueError('Unexpected partial source response')
            elif response.status_code == 200:
                start = 0
            else:
                raise ValueError('Unexpected source status')
            with temporary.open('ab' if start else 'wb') as output:
                for block in response.iter_content(1024 * 1024):
                    if output.tell() + len(block) > SOURCE_SIZE:
                        raise ValueError('Source size budget exceeded')
                    output.write(block)
        if temporary.stat().st_size != SOURCE_SIZE or file_hash(temporary) != SOURCE_SHA256:
            raise ValueError('Complete source verification failed')
        temporary.rename(path)
    if path.stat().st_size != SOURCE_SIZE or file_hash(path) != SOURCE_SHA256:
        raise ValueError('Pinned source changed')


def collect_exclusions():
    """Recover identifiers and hashed dialogue filenames from retained Git evidence."""
    paths = subprocess.check_output(
        ['git', 'ls-tree', '-r', '--name-only', HISTORY_REVISION], text=True).splitlines()
    paths = [p for p in paths if p.endswith('.json') and (
        p.startswith('reports/layer1_training/') or p.startswith('tests/fixtures/layer1'))]
    ids, hashed_ids, evidence = set(), set(), []

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                match = re.fullmatch(r'dialogues/([a-f0-9]{64})\.json', key)
                if match:
                    hashed_ids.add(match[1])
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.isdecimal():
            ids.add(value)

    for path in paths:
        raw = subprocess.check_output(['git', 'show', f'{HISTORY_REVISION}:{path}'])
        visit(json.loads(raw))
        evidence.append({'path': path, 'sha256': digest(raw)})
    if len(hashed_ids) < 1500:
        raise ValueError('Historical split inventory is incomplete')
    return {'revision': subprocess.check_output(['git', 'rev-parse', HISTORY_REVISION], text=True).strip(),
            'ids': sorted(ids), 'canonical_id_hashes': sorted(hashed_ids), 'evidence': evidence,
            'conservative_id_range': [10000, 95000],
            'scope_zh': '恢复保留报告中的历史训练及开发／测试来源；整体排除范围外来源和review前缀。历史正文未全部恢复，不声称全历史语义近重复排除。'}


def normalized(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def select_sources(path, exclusions, tokenizer):
    ids, hashed_ids = set(exclusions['ids']), set(exclusions['canonical_id_hashes'])
    sources, skipped, offset = [], Counter(), 0
    with Path(path).open('rb') as stream:
        for line in stream:
            position, offset = offset, offset + len(line)
            row = json.loads(line)
            key, texts = str(row['id']), row['data']
            canonical_id = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            if not 10000 <= int(key) < 95000 or key in ids or digest(canonical_id.encode()) in hashed_ids:
                skipped['historical_or_conservative_exclusion'] += 1
                continue
            if len(texts) < 4 or any(not isinstance(t, str) or '<|' in t or '|>' in t for t in texts):
                skipped['invalid_or_reserved'] += 1
                continue
            q = QUESTION_PREFIX.match(texts[0])
            if (not q or not texts[0].rstrip().endswith('?') or '?' in texts[2]
                    or not texts[2].rstrip().endswith(('.', '!')) or not DECLARATION_PREFIX.match(texts[2])):
                skipped['no_conservative_semantic_pair'] += 1
                continue
            if len(texts[0]) > 230 or len(texts[2]) > 260 or any(len(texts[i]) > 1300 for i in (1, 3)):
                skipped['length_filter'] += 1
                continue
            if any(not 40 <= len(tokenizer.encode(texts[i])) <= 400 for i in (1, 3)):
                skipped['assistant_length_filter'] += 1
                continue
            if any(sum(c.isascii() and c.isalpha() for c in t) / max(1, sum(c.isalpha() for c in t)) < .95
                   for t in texts[:4]):
                skipped['language_filter'] += 1
                continue
            sources.append({'source_id': key, 'texts': texts, 'byte_offset': position,
                            'raw_line_sha256': digest(line), 'source_shard': 'train_0.jsonl',
                            'source_revision': SOURCE_REVISION, 'pause_boundary': q.end()})
    return sources, skipped


def deduplicate(sources):
    """Reject exact turns and high-overlap source pairs before assigning any split."""
    accepted, exact, index, features, pairs = [], set(), defaultdict(set), {}, []
    for source in sorted(sources, key=lambda s: s['source_id']):
        turns = {normalized(t) for t in source['texts'][:4]}
        if turns & exact:
            pairs.append({'source_id': source['source_id'], 'reason': 'exact_turn'})
            continue
        words = normalized(' '.join(source['texts'][:4])).split()
        grams = {' '.join(words[i:i + 5]) for i in range(max(1, len(words) - 4))}
        possible = set().union(*(index[g] for g in grams))
        duplicate = next((other for other in sorted(possible)
                          if len(grams & features[other]) / len(grams | features[other]) >= .85), None)
        if duplicate is not None:
            pairs.append({'source_id': source['source_id'], 'matched_source_id': duplicate, 'reason': 'near_duplicate'})
            continue
        key = source['source_id']
        features[key] = grams
        for gram in grams:
            index[gram].add(key)
        exact.update(turns)
        accepted.append(source | {'duplicate_group': key})
    return accepted, pairs


def make_plan(source, split, seed):
    key, boundary = source['source_id'], source['pause_boundary']
    rng = seeded_rng(seed, key, 'semantic_schedule')
    backchannel = rng.choice(['Hmm.', 'I see.', 'Right.', 'Mm-hm.', 'Okay.'])
    interruption = rng.choice(['Please stop.', 'Stop for a moment.', 'Please pause.', 'Wait, stop.'])
    trigger = 'wait' if interruption.startswith('Wait') else ('pause' if 'pause' in interruption else 'stop')

    def user(category, **kwargs):
        return {'channel': 'user', 'category': category, 'action': 'keep',
                'reason_zh': '当前新增输入仍在到达，尚未出现完整表达后的让轮空观察。', **kwargs}

    def start(turn, form):
        return {'channel': 'silence', 'category': 'smooth', 'windows': [1, 1], 'action': 'start',
                'utterance_form': form, 'assistant_stream': {'source_turn': turn},
                'reason_zh': '完整请求或陈述已可见，随后出现首个让轮空观察；正文按来源完整保留。'}

    def generation(**kwargs):
        return {'channel': 'generation', 'category': 'natural_completion', 'action': 'keep',
                'reason_zh': '助手生成及播放继续，没有用户接管依据。', **kwargs}

    return {'scenario_id': f'mixed_{key}', 'source_id': key, 'category': 'mixed',
            'state': 'Listen', 'history_before_turn': 0, 'split': split,
            'annotation_method': 'conservative_rules_with_agent_spot_check',
            'phases': [
                user('pause', source_turn=0, end=boundary),
                {'channel': 'silence', 'category': 'pause', 'windows': [1, 3], 'action': 'keep',
                 'reason_zh': '只看到问句开头，缺少谓语或必要补语；当前语义不完整，不依据未来文字。'},
                user('smooth', source_turn=0, start=boundary), start(1, 'question'),
                generation(windows=[1, 1]),
                user('backchannel', text=backchannel, origin='synthetic_annotation', close_backchannel=True,
                     reason_zh='助手表达中的短促附和，没有要求停止或接管。'),
                generation(),
                {'channel': 'playback_tail', 'category': 'natural_completion', 'windows': [1, 3],
                 'action': 'keep', 'reason_zh': '生成已结束但仍在播放，没有打断依据。'},
                {'channel': 'playback_complete'},
                {'channel': 'post_playback_wait', 'category': 'natural_completion', 'windows': [1, 5],
                 'action': 'keep', 'reason_zh': '上一轮已结束，用户尚未开始下一轮。'},
                user('smooth', source_turn=2), start(3, 'declarative'),
                generation(windows=[1, 1]),
                {'channel': 'user', 'category': 'interruption', 'text': interruption,
                 'origin': 'synthetic_annotation', 'action': 'stop', 'trigger_text': trigger,
                 'prefix_action': 'keep', 'prefix_reason_zh': '当前前缀没有明确停止依据。',
                 'reason_zh': '当前前缀已明确要求停止或暂停；stop仅用于用户打断。'}]}


def stratified_rows(rows, limit, seed):
    """Retain action anchors and distinct negative classes without duplicating rows."""
    buckets = defaultdict(list)
    for row in rows:
        buckets[(row['category'], row['target_action'])].append(row)
    for key, bucket in buckets.items():
        seeded_rng(seed, *key).shuffle(bucket)
    selected = []
    while len(selected) < limit and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(selected) < limit:
                selected.append(buckets[key].pop())
    return sorted(selected, key=lambda r: (r['scenario_id'], r['visible_ms']))


def freeze(args):
    fetch_source(args.source)
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('Output must be fresh')
    tokenizer = ControlTokenizer(args.cache)
    exclusions = collect_exclusions()
    sources, skipped = select_sources(args.source, exclusions, tokenizer)
    sources, duplicates = deduplicate(sources)
    seeded_rng(args.seed, 'split_assignment').shuffle(sources)
    counts = {'train': args.train_dialogues, 'dev': 200, 'test': 300}
    if not 1 <= args.train_dialogues <= 1000 or len(sources) < sum(counts.values()):
        raise ValueError(f'Insufficient independent source groups: {len(sources)}, requested {counts}')
    args.output.mkdir(parents=True)
    write_json(args.output / 'exclusions.json', exclusions)
    rows_by_split, plans, index, all_sources = defaultdict(list), [], [], {}
    all_counts, excluded_counts = Counter(), Counter()
    offset = 0
    with (args.output / 'timelines.jsonl').open('w') as traces:
        for split, count in counts.items():
            for source in sources[offset:offset + count]:
                plan = make_plan(source, split, args.seed)
                events, rows = compile_scenario(plan, source, tokenizer, 2048, seed=args.seed)
                plans.append(plan)
                all_sources[source['source_id']] = source
                index.append({'source_id': source['source_id'], 'duplicate_group': source['duplicate_group'],
                              'split': split, 'raw_line_sha256': source['raw_line_sha256']})
                traces.write(json.dumps({'scenario_id': plan['scenario_id'], 'split': split,
                                         'source_id': source['source_id'], 'events': events}, ensure_ascii=False) + '\n')
                for row in rows:
                    row.update(split=split, review_status='conservative_rule_annotated')
                    phase = int(row['snapshot_id'].split(':')[1])
                    opportunity = ('first' if phase < 10 else 'second') if row['category'] == 'smooth' else row['category']
                    row['opportunity_id'] = f"{row['scenario_id']}:{row['category']}:{opportunity}"
                    row['allowed_visible_ms'] = row['visible_ms'] - 480 if row['target_action'] == 'start' else row['visible_ms']
                    expected = [tokenizer.special[ACTIONS[row['target_action']]]]
                    if [v for v in row['labels'] if v != -100] != expected:
                        raise ValueError('Invalid action-only mask')
                    all_counts[(split, row['category'], row['target_action'])] += 1
                    if row['excluded_reason']:
                        excluded_counts[split] += 1
                    rows_by_split[split].append(row)
            offset += count
    usable = {split: [r for r in rows if not r['excluded_reason']] for split, rows in rows_by_split.items()}
    usable['train'] = stratified_rows(usable['train'], 10000, args.seed)
    usable['pilot'] = stratified_rows(usable['train'], 2000, args.seed)
    for split in ('train', 'dev', 'test', 'pilot'):
        with (args.output / f'{split}.jsonl').open('w') as stream:
            for row in usable[split]:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
    write_json(args.output / 'split_index.json', index)
    write_json(args.output / 'source_records.json', all_sources)
    write_json(args.output / 'event_plans.json', plans)
    tokenizer.backend.save(str(args.output / 'tokenizer.json'))
    shutil.copyfile(args.cache / 'tokenizer_config.json', args.output / 'tokenizer_config.json')
    stats = {}
    for split, rows in usable.items():
        starts = [r for r in rows if r['target_action'] == 'start']
        stats[split] = {'snapshots': len(rows), 'source_dialogues': len({r['source_id'] for r in rows}),
                        'actions': dict(Counter(r['target_action'] for r in rows)),
                        'start_declarative': sum(r['utterance_form'] == 'declarative' for r in starts),
                        'start_total': len(starts),
                        'category_groups': {c: len({r['scenario_group'] for r in rows if r['category'] == c})
                                            for c in ('smooth', 'pause', 'backchannel', 'interruption')}}
    if stats['train']['start_declarative'] * 3 < stats['train']['start_total']:
        raise ValueError('Declarative start coverage is insufficient')
    if any(stats['test']['category_groups'][c] < 100 for c in stats['test']['category_groups']):
        raise ValueError('Insufficient test opportunities')
    manifest = {'schema_version': 1, 'status': 'frozen_rule_annotated_text_corpus', 'training_allowed': True,
                'independent_text_split_ready': True, 'online_evaluation_ready': False,
                'source_revision': SOURCE_REVISION, 'model_revision': MODEL_REVISION,
                'source_sha256': SOURCE_SHA256, 'source_bytes': SOURCE_SIZE, 'seed': args.seed,
                'window_ms': 480, 'user_tokens_per_step': [1, 2], 'assistant_tokens_per_step': 8,
                'max_length': 2048, 'new_token_ids': tokenizer.special, 'split_dialogues': counts,
                'statistics': stats, 'skipped_sources': dict(skipped), 'dedup_rejected': duplicates,
                'overlength_snapshots': dict(excluded_counts), 'eligible_source_groups': len(sources),
                'annotation_zh': '保守语义规则标注全部窗口，代理抽检另存；没有逐例人工审核。',
                'limitations_zh': ['时序和播放均为合成，尚无Nemotron语音或在线结果。',
                                   '短附和及停止指令来自固定小型模板集合；不宣称未见模板泛化。',
                                   '历史来源ID及已恢复的分组排除；未恢复的历史正文不能做全面语义近重复校验。',
                                   '训练对话实际数低于1000上限，不用重复窗口补足对话。'],
                'builder_sha256': file_hash(__file__),
                'compiler_sha256': file_hash(Path(__file__).with_name('build_textturn_dataset.py')),
                'files': {p.name: file_hash(p) for p in args.output.iterdir() if p.is_file()}}
    write_json(args.output / 'manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--train-dialogues', type=int, default=160)
    parser.add_argument('--seed', type=int, default=20261025)
    print(json.dumps(freeze(parser.parse_args()), ensure_ascii=False, indent=2))
