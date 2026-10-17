"""Generate an evidence-based Chinese TTS latency report from completed runs."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import tts_latency_benchmark as bench
from tts_latency_experiments import arms


def read_json(path, default=None):
    """Keep missing artifacts explicit rather than treating them as success."""
    return json.loads(path.read_text()) if path.is_file() else default


def read_rows(path):
    """Read complete JSONL records, rejecting truncated artifacts."""
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def trace_checks(events, rows):
    """Check token conservation and timing only within a process clock domain."""
    grouped = defaultdict(list)
    identities = {row['response_id']: row for row in rows}
    for event in events:
        rid = event.get('response_id')
        if rid in identities:
            grouped[(rid, event['clock_domain'])].append(event)
    response_checks = {}
    for (rid, clock), timeline in grouped.items():
        received, consumed, remaining = [], [], None
        accepted_at, prefill_at = None, None
        before, last_graphs = None, None
        frames = {}
        for event in timeline:
            kind = event['event']
            if kind == 'text.tokens':
                received.extend(event['token_ids'])
                if event['token_ids'] and accepted_at is None:
                    accepted_at = event['monotonic_ns']
            elif kind == 'text.consumed':
                consumed.extend(event['token_ids'])
            elif kind == 'text.remaining':
                remaining = event['count']
            elif kind == 'model.prefill.start' and prefill_at is None:
                prefill_at = event['monotonic_ns']
            elif kind == 'compile.state' and event.get('phase') == 'prefill.before':
                before = event.get('unique_graphs')
            elif kind == 'model.frame_summary':
                last_graphs = event.get('unique_graphs')
                if event['frame'] in (1, 5, 10, 50):
                    frames[str(event['frame'])] = {key: event[key] for key in ('wall_seconds', 'eager', 'compiled')}
        observed = remaining is not None and any(e['event'] == 'text.tokens' for e in timeline)
        response_checks[rid] = {
            'clock_domain': clock, 'token_observation_complete': observed,
            'received_tokens': len(received), 'consumed_tokens': len(consumed),
            'token_order_equal': received == consumed if observed else None,
            'remaining_tokens': remaining,
            'worker_text_to_prefill_seconds': (prefill_at - accepted_at) / 1e9
                if prefill_at is not None and accepted_at is not None else None,
            'new_graphs': last_graphs - before if before is not None and last_graphs is not None else None,
            'early_frames': frames,
        }
    by_mode = {}
    for mode in sorted({row['mode'] for row in rows}):
        selected = [response_checks[row['response_id']] for row in rows
                    if row['mode'] == mode and row['response_id'] in response_checks]
        by_mode[mode] = {
            'observed_responses': len(selected),
            'token_checks_complete': sum(row['token_observation_complete'] for row in selected),
            'token_mismatches': sum(row['token_order_equal'] is False for row in selected),
            'remaining_token_responses': sum(bool(row['remaining_tokens']) for row in selected),
            'worker_text_to_prefill_seconds': bench.distribution([row['worker_text_to_prefill_seconds']
                for row in selected if row['worker_text_to_prefill_seconds'] is not None]),
            'responses_with_new_graphs': sum((row['new_graphs'] or 0) > 0 for row in selected),
            'graph_observation_complete': sum(row['new_graphs'] is not None for row in selected),
            'early_frame_seconds': {str(frame): bench.distribution([row['early_frames'][str(frame)]['wall_seconds']
                for row in selected if str(frame) in row['early_frames']]) for frame in (1, 5, 10, 50)},
        }
    return {'by_mode': by_mode, 'responses': response_checks}


def summarize_run(directory, trace_path):
    """Summarize all attempts, preserving slow compiler-contaminated responses."""
    rows = read_rows(directory / 'responses.jsonl')
    if not rows:
        return {'status': 'pending', 'rows': [], 'modes': {}}
    summary_file = read_json(directory / 'summary.json')
    events = read_rows(trace_path)
    selected = {row['response_id'] for row in rows}
    selected_events = [event for event in events if event.get('response_id') in selected]
    checks = trace_checks(selected_events, rows)
    modes = bench.summarize(rows)
    for mode, values in modes.items():
        group = [row for row in rows if row['mode'] == mode]
        values['simulated_underrun_seconds'] = bench.distribution([row['simulated_underrun_seconds'] for row in group])
        values['waveform_onset_seconds'] = bench.distribution([row['onset_seconds'] for row in group if row['onset_seconds'] is not None])
        values['slow_first_pcm_over_5s'] = sum((row['first_pcm_seconds'] or 0) > 5 for row in group)
        values['wall_seconds'] = bench.distribution([row['wall_seconds'] for row in group])
    rounds = {str(i): bench.summarize([row for row in rows if row['repeat'] == i])
              for i in sorted({row['repeat'] for row in rows})}
    stages = bench.analyze_server_trace(selected_events)
    stage_modes = {}
    for mode in modes:
        ids = {row['response_id'] for row in rows if row['mode'] == mode}
        stage_rows = [stage for stage in stages['first_pcm_stages'] if stage['response_id'] in ids]
        phases = sorted({name for stage in stage_rows for name in stage['seconds']})
        stage_modes[mode] = {name: bench.distribution([stage['seconds'].get(name, 0) for stage in stage_rows])
                             for name in phases}
    return {'status': 'complete' if summary_file is not None else 'running',
            'attempts': len(rows), 'rows': rows, 'modes': modes, 'rounds': rounds,
            'checks': checks, 'stage_seconds_by_mode': stage_modes,
            'missing_events': stages['missing_events'], 'unclosed_spans': stages['unclosed_spans']}


def diagnostics(directory):
    """Report compiled fallback evidence, not merely a compile-ready log line."""
    path = directory / 'service.log'
    text = path.read_text(errors='replace') if path.is_file() else ''
    configuration = read_json(directory / 'arm.json', {})
    requested = configuration.get('service_environment', {}).get('TORCH_LOGS', '')
    recompile_logging = 'recompiles' in requested or '__recompiles' in text
    return {'fallbacks': text.count('falling back to eager'),
            'recompile_logging_enabled': recompile_logging,
            'compiled_engaged': text.count('compiled path engaged'),
            'recompile_log_entries': text.count('Recompiling function') if recompile_logging else None,
            'warmup_seconds': [float(value) for value in re.findall(r'compiled warmup done in ([0-9.]+)s', text)],
            'recompile_limit_fallbacks': len(re.findall(r'falling back to eager: recompile_limit', text)),
            'worker_errors': len(re.findall(r'\[session_worker_error\]', text))}


def compare_runs(control, candidate, require_pcm=False):
    """Compare matching texts, modes and repetitions; do not match unrelated trials."""
    base = {(row['id'], row['mode'], row['repeat']): row for row in control.get('rows', [])}
    pairs = [(base[(row['id'], row['mode'], row['repeat'])], row)
             for row in candidate.get('rows', []) if (row['id'], row['mode'], row['repeat']) in base]
    result = {}
    for mode in sorted({row['mode'] for _, row in pairs}):
        group = [(a, b) for a, b in pairs if b['mode'] == mode]
        valid = [(a, b) for a, b in group if not a['error'] and not b['error']]
        result[mode] = {'matched_attempts': len(group), 'valid_pairs': len(valid),
            'first_pcm_saved_seconds': bench.distribution([a['first_pcm_seconds'] - b['first_pcm_seconds']
                for a, b in valid if a['first_pcm_seconds'] is not None and b['first_pcm_seconds'] is not None]),
            'audible_estimate_saved_seconds': bench.distribution([a['audible_estimate_seconds'] - b['audible_estimate_seconds']
                for a, b in valid if a['audible_estimate_seconds'] is not None and b['audible_estimate_seconds'] is not None]),
            'pcm_equal': sum(a.get('audio_sha256') == b.get('audio_sha256') for a, b in valid)
                if require_pcm else None}
    return result


def gpu_summary(path):
    """Read sampled memory as observed nvidia-smi usage, not allocator peak."""
    if not path.is_file():
        return None
    memory, identities = [], set()
    with path.open() as handle:
        for row in csv.DictReader(handle):
            values = {key.strip(): value.strip() for key, value in row.items()}
            if 'uuid' in values:
                identities.add(values['uuid'])
            value = values.get('memory.used [MiB]', '').split(' ')[0]
            try:
                memory.append(float(value))
            except ValueError:
                continue
    return {'sampled_peak_mib': max(memory) if memory else None,
            'samples': len(memory), 'gpu_uuids': sorted(identities)}


def build_report(baseline, screen, intelligibility=None):
    """Keep acceptance limitations explicit even when a candidate is faster."""
    report = {'baseline_root': str(baseline), 'screen_root': str(screen),
              'baseline_exit': (baseline / 'exit_code.txt').read_text().strip() if (baseline / 'exit_code.txt').exists() else None,
              'screen_exit': (screen / 'exit_code.txt').read_text().strip() if (screen / 'exit_code.txt').exists() else None,
              'baseline': summarize_run(baseline / 'baseline', baseline / 'server.jsonl'),
              'baseline_diagnostics': diagnostics(baseline),
              'baseline_gpu': gpu_summary(baseline / 'gpu.csv'),
              'screen_gpu': gpu_summary(screen / 'gpu.csv'),
              'screen_progress': read_json(screen / 'progress.json'),
              'models': read_json(baseline / 'models.lock.json'),
              'arms': {}, 'comparisons': {},
              'intelligibility': read_json(intelligibility or screen / 'intelligibility/summary.json'),
              'quality_listening': 'not_performed', 'physical_playback': 'not_measured',
              'fdb_integration': 'not_run', 'product_defaults_changed': False}
    for arm in arms():
        root = screen / arm['name']
        result = summarize_run(root / 'measured', root / 'server.jsonl')
        failures = (report.get('screen_progress') or {}).get('failed', [])
        failure = next((item for item in failures if item['arm'] == arm['name']), None)
        if failure is not None:
            result['status'] = 'failed'
            result['error'] = failure['error']
        result['configuration'] = read_json(root / 'arm.json', {'configuration': arm})
        result['diagnostics'] = diagnostics(root)
        report['arms'][arm['name']] = result
    for arm in arms():
        if arm['control']:
            report['comparisons'][arm['name']] = compare_runs(report['arms'][arm['control']],
                report['arms'][arm['name']], require_pcm=arm['name'] == 'batch4')
    report['complete'] = (report['baseline_exit'] is not None and report['screen_exit'] is not None
                          and (report.get('screen_progress') or {}).get('phase') == 'finished'
                          and all(value['status'] in ('complete', 'failed') for value in report['arms'].values()))
    report['all_runs_successful'] = (report['baseline_exit'] == '0' and report['screen_exit'] == '0'
                                   and all(value['status'] == 'complete' for value in report['arms'].values()))
    return report


def seconds(value):
    """Format absent measurements without inventing a zero."""
    return '缺测' if value is None else f'{value:.3f}'


def latency_table(modes):
    """Render comparable client-clock latency distributions."""
    lines = ['| 输入 | n | 失败/无音频 | 首 PCM 均值/p50/p95（秒） | 模拟有声均值/p50/p95（秒） | 音频秒/墙钟秒均值 |',
             '| --- | ---: | --- | --- | --- | ---: |']
    for mode, data in modes.items():
        first, voice = data['first_pcm_seconds'], data['audible_estimate_seconds']
        lines.append(f"| {mode} | {data['attempts']} | {data['failures']}/{data['no_audio']} | "
                     + '/'.join(seconds(first[key]) for key in ('mean', 'p50', 'p95')) + ' | '
                     + '/'.join(seconds(voice[key]) for key in ('mean', 'p50', 'p95'))
                     + f" | {seconds(data['audio_per_wall']['mean'])} |")
    return '\n'.join(lines)


def render_markdown(report):
    """Write a self-contained report distinguishing measured gains from acceptance."""
    lines = ['# TTS 端延迟优化报告', '', '日期：2026-10-17。'
             + ('本轮作业均已结束，候选通过与否见结果。' if report['complete'] else '部分作业尚未完成或缺少终态证据，见下文。'), '',
             '## 结论与使用边界', '',
             '本轮固定 MOSS 权重、音色与官方采样，保留唯一 TTS/播放所有权。'
             '实现了批次上限、开头编译和稀疏文本局部 prefill 的可关闭候选路径。'
             '产品默认配置未切换：模型输出与音质尚未通过人工试听、真实播放器和 FDB 集成验收。', '',
             '首 PCM、波形 RMS 语音起点和模拟播放有声时刻是三个不同指标。'
             '模拟欠载使用立即消费、零启动缓冲的 headless 模型，不能解释为真实播放器已经断流。'
             'RMS 起点为 10ms 窗口、阈值 0.01，未人工核查；不能据此声称已完成扬声器首音测量。', '',
             '## 实验来源与规模', '',
             f"原基线：`{report['baseline_root']}`，退出码 `{report['baseline_exit']}`。",
             f"同卡筛选：`{report['screen_root']}`，退出码 `{report['screen_exit']}`。", '',
             '基线为 35 条非 FDB 文本 × whole/incremental × 3 轮，共 210 条。'
             '筛选只含原集合中的短答、澄清与长句三条，每模式三轮；不同候选共 117 条，属于小集合初筛，不能外推可靠的 p95。'
             'whole 一次推送，incremental 每三个词间隔 100ms，sparse 每两个词间隔 600ms、末块后 600ms 才真实结束。'
             '实际 TTS token 数由服务记录，与单词数或 LLM token 数不同。'
             'sparse 是构造的压力输入，并非真实 LLM 流的发生频率估计。', '',
             '固定来源：MOSS `58b20a0d5fcc6766658d50967a90a9d890009a46`，adapter '
             '`b3306b97f8a64c1a2f25b9803c070ff32ecff6b1`；依赖 torch 2.9.1+cu128、transformers 5.0.0、flash-attn 2.8.3。'
             '模型 revision 与路径详见 JSON 摘要中的 models，独立运行源码和开关见各 measured/config.json、arm.json。', '',
             f"原基线 GPU：`{report['baseline_gpu']}`。",
             f"筛选 GPU：`{report['screen_gpu']}`。", '',
             '原基线与筛选可能分配到不同 4090，不直接将二者差值归因于优化。所有候选与首尾 control 在筛选作业内同卡比较。', '',
             '## 原始基线', '', latency_table(report['baseline']['modes']), '',
             '所有尝试均保留。均值中的长尾可能含新形状编译，不剔除这些响应以美化结果。分轮结果如下：', '']
    for repeat, values in report['baseline'].get('rounds', {}).items():
        lines += [f'### 第 {int(repeat) + 1} 轮', '', latency_table(values), '']
    lines += ['基线编译/回退诊断：`' + json.dumps(report['baseline_diagnostics'], ensure_ascii=False) + '`。', '',
              '原基线未启用 TORCH_LOGS=recompiles，重编译条目为缺测，不能解释为没有重编译。'
              '现有日志若出现 recompile_limit 回退，则该部分是 eager 性能，不能当作持续编译后的成绩。', '',
              '## 同卡候选结果', '']
    for name, value in report['arms'].items():
        config = value['configuration']['configuration']
        lines += [f'### {name}', '',
                  f"状态：{value['status']}；batch={config['batch']}、early={config['early']}、prefill={config['tokens']}、max_wait_ms={config['wait_ms']}。", '']
        if value.get('error'):
            lines += ['失败原因：`' + value['error'].replace('`', '') + '`。', '']
        if value['modes']:
            lines += [latency_table(value['modes']), '']
        for mode, check in value.get('checks', {}).get('by_mode', {}).items():
            lines += [f"- {mode}：token 观测 {check['token_checks_complete']}/{check['observed_responses']}；"
                      f"消费顺序不一致 {check['token_mismatches']}，结束有余量 {check['remaining_token_responses']}；"
                      f"worker 文本至 prefill p50/p95={seconds(check['worker_text_to_prefill_seconds']['p50'])}/"
                      f"{seconds(check['worker_text_to_prefill_seconds']['p95'])} 秒；"
                      f"正式响应新图 {check['responses_with_new_graphs']}（图计数观测 {check['graph_observation_complete']}）。"]
        lines += ['', '编译与服务诊断：`' + json.dumps(value['diagnostics'], ensure_ascii=False) + '`。', '']
        for mode, compare in report['comparisons'].get(name, {}).items():
            first, voice = compare['first_pcm_saved_seconds'], compare['audible_estimate_saved_seconds']
            lines += [f"- 对照 {config['control']} / {mode}：{compare['valid_pairs']}/{compare['matched_attempts']} 个有效配对；"
                      f"首 PCM 节省均值/p50={seconds(first['mean'])}/{seconds(first['p50'])} 秒；"
                      f"模拟有声节省均值/p50={seconds(voice['mean'])}/{seconds(voice['p50'])} 秒；正值表示改善。"
                      + (f" PCM 完全相同 {compare['pcm_equal']}/{compare['valid_pairs']}。" if compare['pcm_equal'] is not None else '')]
        lines += ['']
    lines += ['## 语音内容诊断', '']
    diagnostic = report.get('intelligibility')
    if diagnostic is None:
        lines += ['尚无独立 ASR 转写结果；token 消费完整不等于语音内容完整。', '']
    else:
        lines += ['使用既有固定 Nemotron EN 权重对保存 WAV 离线转写，辅助发现漏词/重复。'
                  'ASR 本身有误差，以下不是人工自然度评价；只在同一模式的相同文本上比较。', '']
        for mode, values in diagnostic['by_mode'].items():
            lines += [f'### {mode} 内容检查', '',
                      '| 配置 | 尝试/失败 | 总参考词 | ASR 词错误 | WER | 整句匹配 |',
                      '| --- | ---: | ---: | ---: | ---: | ---: |']
            for name, data in values.items():
                lines.append(f"| {name} | {data['attempts']}/{data['failures']} | {data['reference_words']} | "
                             f"{data['word_errors']} | {seconds(data['wer'])} | {data['exact_sentences']} |")
            lines += ['']
    lines += ['## 阶段分解与剩余问题', '',
              '服务端阶段使用单一进程单调时钟，客户端端到端时间使用客户端单调时钟，两者不直接相减。'
              'prefill/step/codec/音色准备按区间分割，重叠单列，未归因等待不擅自称为排队。'
              '每响应的文本等待、前 1/5/10/50 帧及阶段数据在 JSON 摘要中；不存在的帧数为缺测。', '',
              '同卡 control_start 的首 PCM 阶段均值（秒）：', '',
              '| 模式 | 阶段 | 均值 |', '| --- | --- | ---: |']
    for mode, phases in report['arms']['control_start'].get('stage_seconds_by_mode', {}).items():
        for phase, data in phases.items():
            lines.append(f"| {mode} | {phase} | {seconds(data['mean'])} |")
    lines += ['', '启动兼容处理仅在 codec CPU 加载期间设为单线程，之后恢复 8 线程；'
              '它避免初始化停滞，不能归为热态首音收益。'
              '冷启动与首次新形状编译曾达数十秒，不能凭长句预热一次就认定所有短句均为热态。', '',
              '小门槛与超时路径不伪造 final，文本流保持开启；但它们改变模型 prefix 条件。'
              'token 全部消费只证明输入没有在服务中丢失，不能证明生成语音没有漏词、重复或韵律退化。'
              '批次路径在相同采样条件下另核对 PCM 摘要，数值不一致必须保留并调查。', '',
              '## Issue 状态与后续', '',
              '- TTS-001：组件基线已采集；真实播放器、socket 发送、首词对齐与人工核查仍缺测。',
              '- TTS-002：批次 4 初筛与 token/PCM 对照见上；未自动选为产品默认值。',
              '- TTS-003：开头编译初筛与新图/回退计数见上；若发生回退或持续重编译，不认定编译优化验收通过。',
              '- TTS-004：已有阶段分解，未擅自引入 KV 复用、codec/backbone 编译或更换模型。',
              '- TTS-005：新增小门槛与空闲等待上限路径并进行 sparse 对照；质量未验收前保留默认门槛。', '',
              '稀疏输入下，原 session 主要随真实文本 token 推进一步音频；提前 prefill 不会自动补齐未来文本。'
              '若输入速度过低，首 PCM 提前也可能仍有明显供音间隙，不能靠伪造 final 或填充未来文本解决。', '',
              '所有候选仍需在至少 30 条稀疏文本上扩大验证、隐藏配置名成对试听，并验证真实插话取消和连续播放。'
              '当前 Nemotron 主线未完成接入，未运行 FDB；不能将组件结果视为整体接话延迟或质量通过。', '',
              '完整证据包括各目录的 WAV、逐响应 JSON、server.jsonl、service.log、measured/responses.jsonl、'
              'GPU 采样与源码/环境清单；本报告的 JSON 摘要保留失败、缺测及配对依据。', '']
    return '\n'.join(lines)


def main():
    """Regenerate only this report's artifacts from immutable run directories."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--screen', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--intelligibility', type=Path, help='Optional alternate ASR summary JSON')
    args = parser.parse_args()
    report = build_report(args.baseline.resolve(), args.screen.resolve(), args.intelligibility)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'tts_latency_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (args.output / 'tts_latency_optimization_report.md').write_text(render_markdown(report))
    print(json.dumps({'complete': report['complete'], 'output': str(args.output),
                      'baseline_attempts': report['baseline'].get('attempts', 0),
                      'arm_states': {k: v['status'] for k, v in report['arms'].items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
