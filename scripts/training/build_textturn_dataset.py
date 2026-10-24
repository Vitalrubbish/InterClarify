"""Compile source-linked semantic annotations into causal TextTurn snapshots."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import random
import unicodedata
import urllib.request


ACTIONS = {name: f'<|tt_{name}|>' for name in ('keep', 'start', 'stop')}
SILENCE = '<|no-voice|>'
MODEL_REVISION = 'c1899de289a04d12100db370d81485cdf75e47ca'
SOURCE_REVISION = 'f220fe796ce3ed62fbe1681b45ce6cbc9c6cabe0'
LEGAL = {'Listen': {'keep', 'start'}, 'Speak': {'keep', 'stop'}}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def seeded_rng(seed, *parts):
    """Keep scenario timing reproducible without depending on processing order."""
    return random.Random(int(digest(json.dumps([seed, *parts]).encode()), 16))


def strip_terminal(text):
    """Remove terminal sentence punctuation, preserving decimals and abbreviations."""
    text = text.rstrip()
    while text and text[-1] in '.!?。！？…':
        if text[-1] == '.' and re.search(r'(?:\b[A-Za-z]\.){2,}$|\b(?:Mr|Mrs|Ms|Dr|Prof|etc)\.$', text):
            break
        text = text[:-1].rstrip()
    return text


def fetch_preview(cache):
    """Download a bounded pinned source prefix and tokenizer, never model weights."""
    cache = Path(cache)
    if cache.exists() and any(cache.iterdir()):
        raise ValueError('Fetch requires an empty cache directory')
    cache.mkdir(parents=True, exist_ok=True)
    base = 'https://huggingface.co'
    urls = {
        'dataset_api.json': f'{base}/api/datasets/openbmb/UltraChat/revision/{SOURCE_REVISION}',
        'tokenizer.json': f'{base}/Qwen/Qwen3-0.6B/resolve/{MODEL_REVISION}/tokenizer.json',
        'tokenizer_config.json': f'{base}/Qwen/Qwen3-0.6B/resolve/{MODEL_REVISION}/tokenizer_config.json',
        'source.bin': f'{base}/datasets/stingning/ultrachat/resolve/{SOURCE_REVISION}/train_0.jsonl',
    }
    evidence = {}
    for name, url in urls.items():
        headers = {'Range': 'bytes=0-1048575'} if name == 'source.bin' else {}
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            if name == 'source.bin' and (
                response.status != 206 or response.headers.get('Content-Range') != 'bytes 0-1048575/963569677'
            ):
                raise ValueError('Source response must match the requested pinned byte range')
            limit = 12 * 1024 * 1024 if name == 'tokenizer.json' else 2 * 1024 * 1024
            content = response.read(limit + 1)
            if len(content) > limit:
                raise ValueError('Download exceeds the size budget')
            (cache / name).write_bytes(content)
            evidence[name] = {'url': url, 'sha256': digest(content), 'bytes': len(content),
                              'http_status': response.status,
                              'content_range': response.headers.get('Content-Range')}
    if json.loads((cache / 'dataset_api.json').read_text())['sha'] != SOURCE_REVISION:
        raise ValueError('Source revision differs from the frozen source')
    write_json(cache / 'download_manifest.json', evidence)


class ControlTokenizer:
    """Register fresh action tokens on the pinned Qwen tokenizer without a model."""

    def __init__(self, cache):
        from tokenizers import AddedToken, Tokenizer
        self.backend = Tokenizer.from_file(str(Path(cache) / 'tokenizer.json'))
        self.base_size = self.backend.get_vocab_size()
        markers = list(ACTIONS.values()) + [SILENCE]
        if any(self.backend.token_to_id(marker) is not None for marker in markers):
            raise ValueError('Expected an unmodified base tokenizer')
        self.backend.add_special_tokens([AddedToken(marker, special=True) for marker in markers])
        self.special = {marker: self.backend.token_to_id(marker) for marker in markers}
        for marker, token_id in self.special.items():
            if self.encode(marker) != [token_id] or token_id < self.base_size:
                raise ValueError('New marker must be an independent newly allocated token')

    def encode(self, text):
        return self.backend.encode(text, add_special_tokens=False).ids

    def chunks(self, text, tokens_per_step=2, merge_terminal=True, rng=None):
        """Preserve Unicode spans and attach terminal punctuation to the preceding fragment."""
        bounds = (tokens_per_step, tokens_per_step) if type(tokens_per_step) is int else tuple(tokens_per_step)
        if len(bounds) != 2 or any(type(n) is not int for n in bounds) or not 1 <= bounds[0] <= bounds[1]:
            raise ValueError('Token step size must be a positive integer or ordered bounds')
        if bounds[0] != bounds[1] and rng is None:
            raise ValueError('Random token widths require an explicit seeded generator')
        offsets = self.backend.encode(text, add_special_tokens=False).offsets
        cursor = start = 0
        chunks = []
        while cursor < len(offsets):
            width = bounds[0] if bounds[0] == bounds[1] else rng.randint(*bounds)
            end = min(cursor + width, len(offsets))
            stop = offsets[end - 1][1]
            while end < len(offsets) and offsets[end][0] < stop:
                stop = max(stop, offsets[end][1])
                end += 1
            if end == len(offsets):
                stop = len(text)
            chunks.append(text[start:stop])
            cursor, start = end, stop
        if merge_terminal and len(chunks) > 1 and not strip_terminal(chunks[-1]).strip():
            chunks[-2:] = [chunks[-2] + chunks[-1]]
        yield from chunks


def read_sources(cache):
    """Read only complete source lines, retaining byte offsets and original line hashes."""
    raw = (Path(cache) / 'source.bin').read_bytes()
    sources, offset = {}, 0
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b'\n'):
            break
        row = json.loads(line)
        sources[str(row['id'])] = {
            'texts': row['data'], 'byte_offset': offset, 'raw_line_sha256': digest(line),
            'source_shard': 'train_0.jsonl', 'source_revision': SOURCE_REVISION,
        }
        offset += len(line)
    return sources


def group_sources(sources):
    """Group exact and word-shingle near duplicates within the inspected sources."""
    parents = {key: key for key in sources}
    features = {}
    for key, source in sources.items():
        words = re.findall(r'\w+', unicodedata.normalize('NFKC', ' '.join(source['texts'])).casefold())
        features[key] = {' '.join(words[i:i + 5]) for i in range(max(1, len(words) - 4))}

    def root(key):
        while parents[key] != key:
            key = parents[key]
        return key

    pairs = []
    keys = sorted(sources)
    for i, left in enumerate(keys):
        for right in keys[i + 1:]:
            a, b = features[left], features[right]
            score = len(a & b) / len(a | b) if a | b else 1.0
            if score >= 0.85:
                small, large = sorted((root(left), root(right)))
                parents[large] = small
                pairs.append({'left': left, 'right': right, 'jaccard': score})
    for key, source in sources.items():
        source['duplicate_group'] = root(key)
    return {'scope': 'selected_review_sources_only', 'word_ngram': 5, 'jaccard_threshold': 0.85,
            'dialogues_checked': len(keys), 'groups': len({root(k) for k in keys}), 'matched_pairs': pairs}


def source_text(spec, texts):
    if 'text' in spec:
        if spec.get('origin') != 'synthetic_annotation':
            raise ValueError('Inserted content requires explicit synthetic provenance')
        text = spec['text']
    else:
        original = texts[spec['source_turn']]
        text = original[spec.get('start', 0):spec.get('end', len(original))]
    if any(marker in text for marker in ['<|', '|>']):
        raise ValueError('Source text contains reserved token syntax')
    return text


def prompt_for(visible):
    payload = json.dumps(visible, ensure_ascii=False, separators=(',', ':'))
    return ('<|im_start|>system\nChoose one legal TextTurn action. '
            'Listen: keep/start. Speak: keep/stop. Stop only for user interruption.'
            '<|im_end|>\n<|im_start|>user\n' + payload +
            '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n')


def compile_scenario(plan, source, tokenizer, max_length, assistant_tokens_per_step=8,
                     window_ms=480, user_tokens_per_step=(1, 2), seed=20261025):
    """Compile observed windows with distinct generation and playback lifecycles."""
    if type(window_ms) is not int or window_ms <= 0 or window_ms % 160:
        raise ValueError('Control windows must cover whole 160ms ASR steps')
    texts = source['texts']
    history = [{'role': 'user' if i % 2 == 0 else 'assistant', 'text': text}
               for i, text in enumerate(texts[:plan['history_before_turn']])]
    state = plan['state']
    if state not in LEGAL or 'assistant_visible' in plan:
        raise ValueError('Expected a legal state and an incremental assistant stream')
    stream_spec = plan.get('assistant_stream')
    if (state == 'Speak') != (stream_spec is not None):
        raise ValueError('Only Speak scenarios require an assistant stream')
    assistant_chunks = list(tokenizer.chunks(
        source_text(stream_spec, texts), assistant_tokens_per_step, merge_terminal=False
    )) if stream_spec is not None else []
    lead_in = plan.get('assistant_lead_in_steps', 0)
    if type(lead_in) is not int or lead_in < 0 or (lead_in and lead_in >= len(assistant_chunks)):
        raise ValueError('Assistant lead-in must leave at least one unpublished fragment')
    if state == 'Speak' and not assistant_chunks:
        raise ValueError('Assistant stream must not be empty')
    assistant, assistant_cursor, user, elapsed, empty_streak = '', 0, '', 0, 0
    events, snapshots = [], []
    sampling_group = plan.get('sampling_group', plan['scenario_id'])

    def emit_step(kind, piece='', phase_index=None):
        nonlocal assistant, assistant_cursor, user, elapsed, empty_streak
        assistant_delta = ''
        if state == 'Speak' and assistant_cursor < len(assistant_chunks):
            assistant_delta = assistant_chunks[assistant_cursor]
            assistant_cursor += 1
            assistant += assistant_delta
        user += piece
        elapsed += window_ms
        observation = strip_terminal(piece) or SILENCE
        empty_streak = empty_streak + 1 if observation == SILENCE else 0
        event = {'step': len(events), 'visible_ms': elapsed, 'kind': kind,
                 'window_ms': window_ms, 'user_delta_raw': piece, 'observation': observation,
                 'state': state, 'phase_index': phase_index,
                 'consecutive_no_voice_windows': empty_streak,
                 'assistant_delta': assistant_delta, 'assistant_visible': assistant,
                 'assistant_generation_complete': assistant_cursor == len(assistant_chunks) if state == 'Speak' else None,
                 'assistant_delta_tokens': len(tokenizer.encode(assistant_delta))}
        events.append(event)
        return event

    def snapshot(event, phase_index, index, action, reason):
        if action is not None and (action not in LEGAL[state] or not reason):
            raise ValueError('A labeled window requires a legal action and rationale')
        visible = {'history': history.copy(), 'user_text': strip_terminal(user),
                   'assistant_visible': assistant, 'state': state, 'observation': event['observation'],
                   'window_ms': window_ms, 'consecutive_no_voice_windows': empty_streak,
                   'assistant_generation_complete': event['assistant_generation_complete'], 'cot': ''}
        prompt = prompt_for(visible)
        input_ids = tokenizer.encode(prompt)
        labels = [-100] * len(input_ids)
        if action is not None:
            token_id = tokenizer.special[ACTIONS[action]]
            input_ids.append(token_id)
            labels.append(token_id)
        snapshots.append({'snapshot_id': f"{plan['scenario_id']}:{phase_index}:{index}",
                          'scenario_id': plan['scenario_id'], 'scenario_group': source.get('duplicate_group', plan['source_id']),
                          'category': plan['category'], 'split': 'review', 'source_id': plan['source_id'],
                          'source': source | {'texts': None}, 'clock_type': f'synthetic_{window_ms}ms',
                          'playback_simulated': True, 'visible_ms': elapsed, 'step': event['step'],
                          'visible': visible, 'target_action': action,
                          'reason_zh': reason or '本快照未提供动作标注，不计动作损失。',
                          'utterance_form': plan.get('utterance_form'),
                          'review_status': 'agent_checked_user_review_pending', 'prompt': prompt,
                          'input_ids': input_ids, 'labels': labels,
                          'excluded_reason': 'overlength' if len(input_ids) > max_length else None})

    for index in range(lead_in):
        snapshot(emit_step('assistant_lead_in'), -1, index, 'keep',
                 '助手正在生成并播放，当前没有用户打断，维持Speak。')
    for phase_index, phase in enumerate(plan['phases']):
        channel = phase['channel']
        if channel == 'playback_complete':
            if state != 'Speak' or assistant_cursor != len(assistant_chunks):
                raise ValueError('Playback completion requires Speak and fully published text')
            state = 'Listen'
            history.append({'role': 'assistant', 'text': assistant})
            assistant, user, empty_streak = '', '', 0
            events.append({'step': len(events), 'visible_ms': elapsed, 'kind': channel,
                           'state_after': state, 'target_action': None})
            continue
        rng = seeded_rng(seed, sampling_group, phase_index, channel)
        if channel == 'user':
            pieces = list(tokenizer.chunks(source_text(phase, texts), user_tokens_per_step, rng=rng))
            if not pieces or not ''.join(pieces).strip():
                raise ValueError('A user phase must contain text')
        elif channel == 'generation':
            if state != 'Speak' or assistant_cursor == len(assistant_chunks):
                raise ValueError('Generation phase requires unpublished assistant text')
            pieces = [''] * (len(assistant_chunks) - assistant_cursor)
        elif channel in ('silence', 'playback_tail', 'post_playback_wait'):
            if channel == 'playback_tail' and (state != 'Speak' or assistant_cursor != len(assistant_chunks)):
                raise ValueError('Playback tail requires completed generation and active playback')
            if channel == 'post_playback_wait' and (state != 'Listen' or not history or history[-1]['role'] != 'assistant'):
                raise ValueError('Next-turn wait requires a completed assistant turn')
            if 'windows' in phase:
                bounds = phase['windows']
                if len(bounds) != 2 or any(type(n) is not int for n in bounds) or not 1 <= bounds[0] <= bounds[1]:
                    raise ValueError('Wait windows require positive ordered bounds')
                count = rng.randint(*bounds)
            else:
                duration = phase['duration_ms']
                if type(duration) is not int or duration <= 0:
                    raise ValueError('Silence duration must be positive milliseconds')
                count = math.ceil(duration / window_ms)
            pieces = [''] * count
        else:
            raise ValueError('Unknown event channel')
        action = phase.get('action')
        if action == 'start' and len(pieces) != 1:
            raise ValueError('A start anchor must identify one allowed observation window')
        for index, piece in enumerate(pieces):
            event = emit_step(channel, piece, phase_index)
            if channel == 'silence' and 'duration_ms' in phase:
                event.update(original_duration_ms=phase['duration_ms'], rebuilt_duration_ms=len(pieces) * window_ms)
            trigger = phase.get('trigger_text')
            triggered = trigger is not None and trigger.casefold() in user.casefold()
            last = index == len(pieces) - 1
            if trigger is not None and (action != 'stop' or (last and not triggered)):
                raise ValueError('A stop trigger must become visible before labeling stop')
            current_action = action if action in (None, 'keep') or last or triggered else phase.get('prefix_action')
            reason = phase.get('reason_zh') if current_action == action else phase.get('prefix_reason_zh')
            snapshot(event, phase_index, index, current_action, reason)
            if current_action in ('start', 'stop'):
                if phase_index != len(plan['phases']) - 1:
                    raise ValueError('End a scenario at an executed turn-changing action')
                return events, snapshots
    return events, snapshots


def build(config_path, cache, output):
    config = json.loads(Path(config_path).read_text())
    assistant_tokens_per_step = config['assistant_tokens_per_step']
    if type(assistant_tokens_per_step) is not int or assistant_tokens_per_step < 1:
        raise ValueError('Assistant token step size must be a positive integer')
    cache, output = Path(cache), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a fresh output directory')
    evidence = json.loads((cache / 'download_manifest.json').read_text())
    for name in ('source.bin', 'dataset_api.json', 'tokenizer.json', 'tokenizer_config.json'):
        if digest((cache / name).read_bytes()) != evidence[name]['sha256']:
            raise ValueError(f'Cached asset changed: {name}')
    if json.loads((cache / 'dataset_api.json').read_text())['sha'] != SOURCE_REVISION:
        raise ValueError('Wrong source revision')
    if not evidence['tokenizer.json']['url'].endswith(f'/{MODEL_REVISION}/tokenizer.json'):
        raise ValueError('Wrong tokenizer revision')
    tokenizer, sources = ControlTokenizer(cache), read_sources(cache)
    plans = config['scenarios']
    if len({p['scenario_id'] for p in plans}) != len(plans):
        raise ValueError('Duplicate scenario identity')
    if len(plans) > 2000 or len({p['source_id'] for p in plans}) > 1000:
        raise ValueError('Preview exceeds the dialogue/scenario budget')
    selected_sources = {key: sources[key] for key in {p['source_id'] for p in plans}}
    dedup = group_sources(selected_sources)
    output.mkdir(parents=True, exist_ok=True)
    snapshots, timelines = [], []
    for plan in plans:
        source = sources[plan['source_id']]
        events, rows = compile_scenario(plan, source, tokenizer, config['max_length'], assistant_tokens_per_step,
                                        config['window_ms'], config['user_tokens_per_step'], config['seed'])
        snapshots.extend(rows)
        timelines.append({'scenario_id': plan['scenario_id'], 'source_id': plan['source_id'],
                          'events': events})
    if len(snapshots) > 2000:
        raise ValueError('Preview exceeds the snapshot budget')
    write_json(output / 'timelines.json', timelines)
    (output / 'review_samples.json').write_text('[\n' + ',\n'.join(
        json.dumps(row, ensure_ascii=False) for row in snapshots) + '\n]\n')
    write_json(output / 'source_records.json', {key: sources[key] for key in sorted({p['source_id'] for p in plans})})
    tokenizer.backend.save(str(output / 'tokenizer.json'))
    (output / 'tokenizer_config.json').write_bytes((cache / 'tokenizer_config.json').read_bytes())
    candidates = [r for r in snapshots if r['target_action'] and not r['excluded_reason']]
    with (output / 'review_candidates.jsonl').open('w') as stream:
        for row in candidates:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    starts = [r for r in candidates if r['target_action'] == 'start']
    declarations = sum(r['utterance_form'] == 'declarative' for r in starts)
    counts = Counter(r['target_action'] or 'unknown' for r in snapshots)
    for row in snapshots:
        expected = [] if row['target_action'] is None else [tokenizer.special[ACTIONS[row['target_action']]]]
        if [label for label in row['labels'] if label != -100] != expected:
            raise ValueError('Action-only loss mask is invalid')
        if len(row['labels']) != len(row['input_ids']):
            raise ValueError('Loss mask length differs from input length')
    assistant_sizes = Counter(event['assistant_delta_tokens'] for trace in timelines for event in trace['events']
                              if event.get('assistant_delta'))
    audit = {'action_only_mask_checked': len(snapshots), 'max_input_tokens': max(
        (len(r['input_ids']) for r in snapshots), default=0), 'dedup': dedup,
        'category_snapshot_counts': dict(Counter(r['category'] for r in snapshots)),
        'assistant_token_counts_per_step': dict(assistant_sizes),
        'assistant_streaming_steps': sum(assistant_sizes.values()),
        'window_counts_by_kind': dict(Counter(event['kind'] for trace in timelines for event in trace['events']
                                              if event['kind'] != 'playback_complete')),
        'no_voice_windows': sum(event.get('observation') == SILENCE for trace in timelines for event in trace['events'])}
    write_json(output / 'audit.json', audit)
    report = {'status': 'preview_for_review', 'training_allowed': False,
              'independent_test_ready': False, 'source_revision': SOURCE_REVISION,
              'source_verification': 'pinned_HTTP_byte_range; full_shard_LFS_hash_not_verified',
              'model_revision': MODEL_REVISION, 'new_token_ids': tokenizer.special,
              'assistant_tokens_per_step': assistant_tokens_per_step,
              'window_ms': config['window_ms'], 'asr_decode_step_ms': 160,
              'user_tokens_per_step': config['user_tokens_per_step'], 'seed': config['seed'],
              'source_dialogues': len({p['source_id'] for p in plans}), 'scenarios': len(plans),
              'snapshots': len(snapshots), 'readable_candidates': len(candidates),
              'action_counts': dict(counts), 'start_declarative': declarations,
              'start_total': len(starts), 'start_declarative_fraction': declarations / len(starts) if starts else None,
              'category_scenario_groups': {c: len({sources[p['source_id']]['duplicate_group'] for p in plans if p['category'] == c})
                                           for c in sorted({p['category'] for p in plans})},
              'overlength': sum(r['excluded_reason'] == 'overlength' for r in snapshots),
              'formal_split_actual': {'train': 0, 'dev': 0, 'test': 0},
              'formal_split_targets': {'train_dialogues_max': 1000, 'train_snapshots_max': 10000,
                                       'pilot_snapshots_max': 2000, 'dev_dialogues': 200,
                                       'test_dialogues': 300, 'test_groups_per_category_min': 100},
              'gaps_zh': config['gaps_zh'], 'config_sha256': digest(Path(config_path).read_bytes()),
              'builder_sha256': digest(Path(__file__).read_bytes()), 'audit': audit, 'downloads': evidence}
    write_json(output / 'manifest.json', report)
    lines = ['# TT-001 数据检查样例', '', '这是固定 UltraChat 来源上的合成事件样例；split=review，不进入正式训练或测试。',
             f"控制窗{config['window_ms']}ms；User非空窗随机1—2 token，Assistant每窗{assistant_tokens_per_step} token模拟生成。表中动作是监督目标，不是模型实测输出。", '',
             '生成完但仍在播放时保持Speak；playback_complete后才转Listen。连续空窗数只记录已经观察的窗口。', '']
    by_step = {(row['scenario_id'], row['step']): row for row in snapshots}

    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', '<br>')

    for trace in timelines:
        lines.extend([f"## {trace['scenario_id']}", '',
                      '| 时刻ms | 状态 | User新增／空观察 | Assistant新增 | 已生成完 | 连续空窗 | 动作token |',
                      '| --- | --- | --- | --- | --- | --- | --- |'])
        for event in trace['events']:
            if event['kind'] == 'playback_complete':
                lines.append(f"| {event['visible_ms']} | Speak→Listen | playback_complete | — | — | 0 | 无动作 |")
                continue
            row = by_step[(trace['scenario_id'], event['step'])]
            action = ACTIONS[row['target_action']] if row['target_action'] else '未标注'
            completed = event['assistant_generation_complete']
            values = [event['visible_ms'], event['state'], event['observation'], event['assistant_delta'] or '（无新增）',
                      '—' if completed is None else ('是' if completed else '否'), event['consecutive_no_voice_windows'], action]
            lines.append('| ' + ' | '.join(cell(value) for value in values) + ' |')
        lines.append('')
    lines.extend(['<details>', '<summary>完整快照：累计文本、历史及标注理由</summary>', ''])
    for row in snapshots:
        v = row['visible']
        lines.extend([f"## {row['snapshot_id']}", '',
                      f"来源：UltraChat {row['source_id']}；类别：{row['category']}；可见时间：{row['visible_ms']}ms。", '',
                      f"状态：{v['state']}；本步：`{v['observation']}`；动作：**{row['target_action'] or 'unknown'}**。", '',
                      '当前累计用户文本：', '', '> ' + v['user_text'].replace('\n', '\n> '), '',
                      '已完成对话历史：', '', json.dumps(v['history'], ensure_ascii=False), '',
                      '当前助手已生成文本（不代表全部已播放）：', '', '> ' + (v['assistant_visible'] or '（空）').replace('\n', '\n> '), '',
                      row['reason_zh'], ''])
    lines.append('</details>')
    content = '\n'.join(line.rstrip() for line in '\n'.join(lines).splitlines()).rstrip() + '\n'
    (output / 'samples.md').write_text(content)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/textturn_dataset_preview.json'))
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--fetch-preview', action='store_true')
    args = parser.parse_args()
    if args.fetch_preview:
        fetch_preview(args.cache)
    if args.output:
        print(json.dumps(build(args.config, args.cache, args.output), ensure_ascii=False, indent=2))
    elif not args.fetch_preview:
        parser.error('--output or --fetch-preview is required')
