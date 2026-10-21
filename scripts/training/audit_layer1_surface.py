"""Read-only punctuation, pause and native ASR surface audit for Issue 073."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import resource
import shutil
import time

import yaml

from audit_layer1_dataset import audit, require
from layer1_data import digest, file_digest, write_json


MARKS = '.,!?;:'
CLOSERS = '\"\'”’)]}'
CUE = re.compile(r'\b(?:first|second|third|finally|actually|rather|instead|I mean)\b|(?:^|\n)\s*(?:[-*]|\d+[.)])', re.I)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def terminal_positions(text):
    """Locate trailing sentence marks, allowing quotes and closing brackets."""
    end = len(text.rstrip())
    while end and text[end - 1] in CLOSERS:
        end -= 1
    start = end
    while start and text[start - 1] in '.!?':
        start -= 1
    return set(range(start, end))


def text_statistics(text):
    """Count diagnostic characters without interpreting abbreviation periods."""
    terminal = terminal_positions(text)
    result = Counter(texts=1, nonempty=int(bool(text.strip())))
    for name, positions in (('internal', set(range(len(text))) - terminal), ('terminal', terminal)):
        found = Counter(text[i] for i in positions if text[i] in MARKS)
        result[f'{name}_texts'] = int(bool(found))
        for char, count in found.items():
            result[f'{name}_chars_{char}'] = count
            result[f'{name}_texts_{char}'] = 1
    return result


def strip_terminal(text, marks='.'):
    """Produce an offline candidate only; never apply this to individual chunks."""
    positions = terminal_positions(text)
    return ''.join(c for i, c in enumerate(text) if i not in positions or c not in marks)


def boundary_kind(text, offset):
    """Use surface cues only; sentence completion remains a review question."""
    left, right = text[:offset].rstrip(), text[offset:]
    while left and left[-1] in CLOSERS:
        left = left[:-1]
    if left and left[-1] in '.!?':
        return 'after_sentence_mark'
    if left and left[-1] in ',;:':
        return 'after_clause_mark'
    if 0 < offset < len(text) and text[offset - 1].isalnum() and right[0].isalnum():
        return 'inside_word'
    return 'other'


def check_disk(output):
    require(shutil.disk_usage(output).free >= 10 * 1024 ** 3, 'Less than 10 GiB free')
    require(sum(p.stat().st_size for p in output.iterdir() if p.is_file()) <= 2 * 1024 ** 3,
            'Audit output exceeds 2 GiB')


def select_cards(candidates, seed, per_group=15):
    """Select distinct source turns, retaining pending human and semantic labels."""
    chosen, used, coverage = [], set(), {}
    groups = ('sentence_mark_then_continues', 'enumeration_or_repair_cue', 'inside_word', 'turn_end')
    for group in groups:
        rows = sorted(candidates.get(group, []), key=lambda r: digest([seed, group, r['dialogue_id'], r['turn'], r['event_id']]))
        count = 0
        for row in rows:
            identity = (row['dialogue_id'], row['turn'])
            if identity in used:
                continue
            chosen.append(dict(row, group=group, semantic_review=None, human_review=None))
            used.add(identity)
            count += 1
            if count == per_group:
                break
        coverage[group] = {'candidate_events': len(rows), 'requested': per_group, 'selected': count}
    return chosen, coverage


def audit_dataset(args, inputs):
    """Reaudit all serialized supervision before reporting surface diagnostics."""
    manifest_path = args.dataset / 'manifest.json'
    manifest = load(manifest_path)
    manifest_sha = file_digest(manifest_path)
    previous = load(args.audit)
    protocol = yaml.safe_load(args.protocol.read_text())
    require(manifest_sha == protocol['data_manifest_sha256'] == previous['manifest_sha256'], 'Wrong baseline data')
    require(file_digest(args.audit) == protocol['data_audit_sha256'], 'Wrong baseline audit')
    require(file_digest(args.index) == protocol['full_train_index_sha256'], 'Wrong baseline index')
    for path in (manifest_path, args.audit, args.index, args.protocol, args.dataset / 'dialogues.json'):
        inputs[str(path)] = file_digest(path)
    print('Revalidating full dataset and all three serialized views', flush=True)
    machine = audit(args.dataset, args.tokenizer)
    write_json(args.output / 'machine_audit.json', machine)
    dialogues = load(args.dataset / 'dialogues.json')
    index = load(args.index)['T2']
    require(index['subset'] == [d['dialogue_id'] for d in dialogues if d['split'] == 'train'], 'Train subset drift')
    stats, candidates, seen_dialogues = {}, defaultdict(list), defaultdict(set)
    train_sequences = train_tokens = 0
    for position, dialogue in enumerate(dialogues):
        split, identity = dialogue['split'], dialogue['dialogue_id']
        if split not in stats:
            stats[split] = {'counts': Counter(), 'punctuation': defaultdict(Counter),
                            'pause_boundaries': Counter(), 'pause_windows_histogram': Counter()}
        report = stats[split]
        report['counts']['dialogues'] += 1
        path = args.dataset / 'dialogues' / (digest(identity) + '.json')
        checksum = file_digest(path)
        require(checksum == manifest['artifacts'][str(path.relative_to(args.dataset))], 'Changed dialogue artifact')
        artifact = load(path)
        plan, events = artifact['plan'], artifact['plan']['events']
        report['counts'].update(e['kind'] for e in events)
        for turn, surface in plan['user_turns'].items():
            sourced = [e for e in events if e['user_origin'] and e['user_origin']['turn'] == int(turn)]
            original = ''.join(e['user_text'] for e in sourced)
            t2 = ''.join(e['user_unpunctuated'] for e in sourced)
            require(original == surface['text'], 'User turn reconstruction mismatch')
            views = {'original': original, 'T2': t2,
                     'terminal_period_removed_candidate': strip_terminal(original),
                     'terminal_sentence_marks_removed_candidate': strip_terminal(original, '.!?')}
            for name, text in views.items():
                report['punctuation'][name].update(text_statistics(text))
            report['counts']['user_turns'] += 1
            report['counts']['internal_punctuation_lost_in_T2_turns'] += int(
                text_statistics(original)['internal_texts'] and not text_statistics(t2)['internal_texts'])
        for i, event in enumerate(events):
            if event['kind'] == 'natural_pause':
                if i and events[i - 1]['kind'] == 'natural_pause':
                    continue
                prev = events[i - 1]
                require(prev['user_origin'] is not None, 'Pause without preceding source')
                origin = prev['user_origin']
                turn = origin['turn']
                text = plan['user_turns'][str(turn)]['text']
                duration = 1
                while i + duration < len(events) and events[i + duration]['kind'] == 'natural_pause':
                    duration += 1
                require(events[i + duration]['user_origin']['turn'] == turn, 'Pause crosses user turn')
                kind = boundary_kind(text, origin['end'])
                report['pause_boundaries'][kind] += 1
                report['pause_windows_histogram'][str(duration)] += 1
                report['counts']['pause_triggers'] += 1
                seen_dialogues[split].add(identity)
                group = {'after_sentence_mark': 'sentence_mark_then_continues', 'inside_word': 'inside_word'}.get(kind)
                if CUE.search(text):
                    groups = [group, 'enumeration_or_repair_cue']
                else:
                    groups = [group]
                offset = origin['end']
                windows = duration
            elif event['kind'] == 'response_start':
                prev = events[i - 1]
                origin = prev['user_origin']
                turn, offset = origin['turn'], origin['end']
                text = plan['user_turns'][str(turn)]['text']
                kind, groups, windows = 'turn_end', ['turn_end'], 0
            else:
                continue
            row = {'dialogue_id': identity, 'split': split, 'turn': turn, 'event_id': i,
                   'artifact_sha256': checksum, 'offset': offset, 'boundary': kind, 'pause_windows': windows,
                   'prefix_original': text[:offset], 'prefix_T2': ''.join(
                       e['user_unpunctuated'] for e in events[:i] if e['user_origin'] and e['user_origin']['turn'] == turn),
                   'continuation': text[offset:], 'control': event['control']}
            for group in groups:
                if group:
                    candidates[group].append(row)
        if split == 'train':
            seqs = [s for s in artifact['sequences'] if s['arm'] == 'T2']
            require(all(s['view'] == 'unpunctuated' for s in seqs), 'T2 view drift')
            train_sequences += len(seqs)
            train_tokens += sum(s['effective_tokens'] for s in seqs)
        if position % 100 == 0:
            check_disk(args.output)
    require(train_sequences == index['statistics']['sequences'], 'Index sequence count mismatch')
    require(train_tokens == index['statistics']['effective_tokens'], 'Index token count mismatch')
    for split, report in stats.items():
        report['counts']['dialogues_with_pauses'] = len(seen_dialogues[split])
        report['counts']['pause_seconds_synthetic'] = report['counts']['natural_pause'] * manifest['identity']['config']['generation']['micro_turn_ms'] / 1000
    cards, coverage = select_cards(candidates, args.seed)
    require(len(cards) == 60, 'Insufficient distinct review turns; inspect coverage')
    write_json(args.output / 'review_cards.json', {'seed': args.seed, 'coverage': coverage, 'cards': cards,
                                                 'human_review_complete': False})
    print('Dataset diagnostics complete', flush=True)
    return {'manifest_sha256': manifest_sha, 'splits': stats, 'review_coverage': coverage,
            'train_index_sequences': train_sequences, 'train_index_effective_tokens': train_tokens,
            'machine_passed': machine['machine_passed'], 'human_review_complete': False}


def transcript_views(rows):
    """Keep recordings whose first text arrives after EOF in the denominator."""
    require(bool(rows), 'Empty ASR trace')
    require(all(isinstance(r.get('text'), str) and type(r.get('eof')) is bool for r in rows),
            'Unexpected trace schema')
    online_rows = [r['text'] for r in rows if not r['eof']]
    return (online_rows[-1] if online_rows else ''), rows[-1]['text']


def audit_asr(root, inputs):
    """Summarize native cumulative transcripts without rerunning ASR."""
    paths = sorted(root.glob('shard-*/repeat-*/nemotron_en-160/sample-*.jsonl'))
    require(bool(paths), 'No historical EN160 traces')
    totals = {name: Counter() for name in ('online', 'final', 'delta')}
    per_sample = defaultdict(list)
    examples, rewrites, eof_only = [], 0, 0
    for path in paths:
        inputs[str(path)] = file_digest(path)
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        online, final = transcript_views(rows)
        eof_only += int(not online.strip() and bool(final.strip()))
        totals['online'].update(text_statistics(online))
        totals['final'].update(text_statistics(final))
        old = ''
        for row in rows:
            text = row['text']
            if not text.startswith(old):
                rewrites += 1
            else:
                totals['delta'].update(text_statistics(text[len(old):]))
            old = text
        per_sample[path.name].append({'online': online, 'final': final})
        if len(examples) < 6 and text_statistics(online)['internal_texts']:
            examples.append({'path': str(path), 'online': online, 'final': final})
    require(len(paths) == 200 and len(per_sample) == 100 and all(len(v) == 2 for v in per_sample.values()),
            'Historical recording coverage differs from frozen 100 recordings / 2 runs')
    unique_first = {name: Counter() for name in ('online', 'final')}
    for repeats in per_sample.values():
        for name in unique_first:
            unique_first[name].update(text_statistics(repeats[0][name]))
    return {'trace_files': len(paths), 'distinct_sample_names': len(per_sample),
            'repeat_counts': dict(Counter(len(v) for v in per_sample.values())),
            'all_runs': totals, 'one_run_per_sample': unique_first, 'prefix_rewrites': rewrites,
            'eof_only_text_runs': eof_only,
            'examples': examples, 'scope': 'historical recordings; no new model run; deltas include EOF',
            'independence_note': 'sample filenames identify the shared fixed recording set; first sorted run retained for deduplication'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dataset', 'audit', 'protocol', 'index', 'tokenizer', 'asr-root', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261021)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, inputs = time.monotonic(), {str(Path(__file__).resolve()): file_digest(__file__)}
    try:
        check_disk(args.output)
        data = audit_dataset(args, inputs)
        asr = audit_asr(args.asr_root, inputs)
        write_json(args.output / 'input_files.json', inputs)
        result = {'schema_version': 1, 'dataset': data, 'asr': asr, 'training_allowed': False,
                  'elapsed_seconds': time.monotonic() - started,
                  'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  'input_files_sha256': file_digest(args.output / 'input_files.json')}
        write_json(args.output / 'summary.json', result)
        check_disk(args.output)
        print(json.dumps({'machine_passed': data['machine_passed'], 'review_cards': 60,
                          'asr_traces': asr['trace_files'], 'elapsed_seconds': result['elapsed_seconds']}), flush=True)
    except Exception as error:
        write_json(args.output / 'failure.json', {'error': str(error), 'training_allowed': False})
        raise


if __name__ == '__main__':
    main()
