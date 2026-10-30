"""Summarize native delta drafts and whole-segment Context publications."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def summarize_case(root, case):
    """Match source updates to published frames without treating drafts as reads."""
    case_id = case['case_id']
    rows = [json.loads(line) for line in (root / f'{case_id}.source.jsonl').read_text().splitlines()]
    snapshots = [json.loads(line) for line in (root / f'{case_id}.snapshots.jsonl').read_text().splitlines()]
    frames = [v for v in snapshots if v['status'] == 'open' and v['state_token'] is not None]
    draft, published, generation, cutoff = '', '', 0, 0
    deltas, refinements, timeline, pending = [], [], [], []
    for row in rows:
        kind = row['audit_kind']
        update = row.get('assembly_result', {})
        if kind == 'control_source' and update.get('stage') == 'delta':
            draft = update['text']
            generation = update['controller_generation']
            if update['text_changed']:
                deltas.append({'generation': generation, 'text': draft})
        elif kind == 'asr_source' and row['call_kind'] == 'turn':
            item = {'phase': row['delivery_phase'], 'generation': update.get('controller_generation'),
                    'latest_delta_draft': draft, 'previous_context': published,
                    'recognized_segment': row['text'], 'update': update,
                    'audio_observed_until': row['audio_observed_until'], 'published': False}
            refinements.append(item)
            if update.get('stage') == 'turn':
                pending.append(item)
        elif kind == 'frame_source':
            for item in pending:
                if item['update']['text'] != row['text']:
                    raise AssertionError('Whole-segment update differs from its publication')
                item.update(published=True, context_text=row['text'], processed_until=row['processed_until'])
            if row['text'] != published:
                timeline.append({'processed_until': row['processed_until'],
                                 'generation': row['controller_generation'],
                                 'source': 'turn' if pending else 'delta', 'text': row['text']})
            pending.clear()
            published, cutoff = row['text'], row['processed_until']
    if pending or published != case['closed_text']:
        raise AssertionError('Missing publication or closed text mismatch')
    source_frames = [v for v in rows if v['audit_kind'] == 'frame_source']
    if [v['text'] for v in frames] != [v['text'] for v in source_frames]:
        raise AssertionError('Source frame texts differ from actual Context reads')
    return {'case_id': case_id, 'closed_text': published, 'processed_until': cutoff,
            'last_delta_draft': draft, 'delta_changes': deltas,
            'refinements': refinements, 'context_changes': timeline}


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', '<br>') or '（空）'


def render(cases):
    lines = ['# 逐样本输入与全部正文变化', '',
             '由原始 source 与实际 snapshots 交叉核对。时间为已处理真实音频截止；generation 为内部 controller 片段编号。', '',
             '“最新草稿”可能在同一步被整段结果替换，尚未单独写入 Context；“此前 Context”才是覆盖前实际可读输入。', '',
             '整段识别按原生 controller 片段触发，内部 reset 不结束逻辑话轮；无在线整段识别时不补造结果。', '']
    for case in cases:
        lines += [f'## {case["case_id"]}', '',
                  f'最后一次 asr_delta 草稿：{case["last_delta_draft"] or "（空）"}', '',
                  f'关闭时实际 Context：{case["closed_text"] or "（空）"}', '']
        if not case['refinements']:
            lines += ['未发生整段重识别。', '']
        for i, item in enumerate(case['refinements'], 1):
            lines += [f'### 整段识别 {i}（{item["phase"]}，片段 {item["generation"]}）', '',
                      '| 项目 | 输入文字 |', '| --- | --- |',
                      f'| 最新 asr_delta 草稿 | {cell(item["latest_delta_draft"])} |',
                      f'| 此前实际 Context | {cell(item["previous_context"])} |',
                      f'| 本片段整段识别 | {cell(item["recognized_segment"])} |',
                      f'| 覆盖后实际 Context | {cell(item.get("context_text", "未写入在线 Context"))} |', '']
        lines += ['### 全部在线 Context 正文变化', '',
                  '| 音频截止（秒） | 片段 | 来源 | 当前完整输入 |', '| ---: | ---: | --- | --- |']
        for item in case['context_changes']:
            lines.append(f'| {item["processed_until"] / 16000:.3f} | {item["generation"]} | {item["source"]} | {cell(item["text"])} |')
        lines.append('')
    return '\n'.join(lines).rstrip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = json.loads((args.replay / 'result.json').read_text())
    if not result['passed']:
        raise ValueError('Replay did not pass')
    cases = [summarize_case(args.replay, case) for case in result['cases']]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'inputs.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (args.output / 'sample_inputs.md').write_text(render(cases) + '\n')
    print(json.dumps({'cases': len(cases), 'published_refinements': sum(
        r['published'] for c in cases for r in c['refinements']),
        'context_text_changes': sum(len(c['context_changes']) for c in cases)}))


if __name__ == '__main__':
    main()
