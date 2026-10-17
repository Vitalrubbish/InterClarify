"""Report a combined MOSS configuration against matched same-GPU controls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tts_latency_experiments import arms
from tts_latency_report import (compare_runs, diagnostics, gpu_summary, latency_table,
                               read_json, render_diagnostics, seconds, summarize_run)


def build(root, intelligibility=None):
    """Retain terminal failures and require complete counts before closing a run."""
    progress = read_json(root / 'progress.json', {})
    failures = {row['arm']: row['error'] for row in progress.get('failed', [])}
    values = {}
    for arm in arms('combination'):
        name = arm['name']
        value = summarize_run(root / name / 'measured', root / name / 'server.jsonl')
        value.update(configuration=read_json(root / name / 'arm.json'), diagnostics=diagnostics(root / name))
        if name in failures:
            value.update(status='failed', error=failures[name])
        values[name] = value
    exit_code = (root / 'exit_code.txt').read_text().strip() if (root / 'exit_code.txt').exists() else None
    complete = exit_code is not None and progress.get('phase') == 'finished'
    counts_ok = all(v.get('attempts') == 27 and v['status'] == 'complete' for v in values.values())
    return {'run_root': str(root), 'exit_code': exit_code, 'progress': progress,
            'complete': complete, 'all_runs_successful': complete and counts_ok and exit_code == '0',
            'gpu': gpu_summary(root / 'gpu.csv'), 'arms': values,
            'combination_comparison': compare_runs(values['control_start'], values['combined'], require_pcm=True),
            'control_drift': compare_runs(values['control_start'], values['control_end']),
            'intelligibility': read_json(intelligibility or root / 'intelligibility/summary.json'),
            'product_defaults_changed': False, 'physical_playback': None, 'human_listening': 'pending'}


def render(report):
    """Explain remaining budget and correctness limits, not just packet speed."""
    lines = ['# MOSS-TTS 组合优化验证', '',
             '日期：2026-10-17。' + ('作业已结束。' if report['complete'] else '作业未完成或终态缺测。'), '',
             '## 配置与测量边界', '',
             '组合为 batch=4、early_compile=1、prefill_text_tokens=4、max_wait_ms=0；'
             '原配置为 batch=0、early=0、prefill=12。同一卡顺序运行原配置、组合、原配置，'
             '固定权重、音色、官方采样与 seed=17。三个筛选文本、三种输入模式、三轮，共计划81条。'
             '这是组合效果验证，不作单变量归因，不证明所有 MOSS 优化方向已经穷尽。', '',
             f"运行目录：`{report['run_root']}`；退出码 `{report['exit_code']}`；GPU `{report['gpu']}`。", '',
             '首 PCM 可能含静音。有声是10ms RMS阈值0.01与立即消费缓冲模型估计，不是扬声器实测。'
             '输入从首个真实文本可用计时，包含后续文本等待；whole、incremental、sparse 分别汇总。'
             '小集合每模式9条的p95只用于描述，不作为可靠的产品尾延迟估计。', '',
             '## 三组结果', '']
    for name, value in report['arms'].items():
        lines += [f'### {name}', '', f"状态：{value['status']}；正式记录 {value.get('attempts', 0)}/27。", '']
        if value['modes']:
            lines += [latency_table(value['modes']), '']
        lines += [render_diagnostics(value['diagnostics']), '']
        if value.get('error'):
            lines += ['失败上下文：`' + value['error'].replace('`', '') + '`。', '']
        for mode, check in value.get('checks', {}).get('by_mode', {}).items():
            lines.append(f"- {mode}：token观测 {check['token_checks_complete']}/{check['observed_responses']}；"
                         f"消费不一致 {check['token_mismatches']}、有剩余 {check['remaining_token_responses']}；"
                         f"正式新图响应 {check['responses_with_new_graphs']}；worker文本至prefill均值 "
                         f"{seconds(check['worker_text_to_prefill_seconds']['mean'])} 秒。")
        lines += ['']
    lines += ['## 同卡配对收益', '',
              '| 输入 | 配对数 | 首PCM平均提前（秒） | 模拟有声平均提前（秒） | PCM相同 |',
              '| --- | ---: | ---: | ---: | ---: |']
    for mode, value in report['combination_comparison'].items():
        lines.append(f"| {mode} | {value['valid_pairs']} | {seconds(value['first_pcm_saved_seconds']['mean'])} | "
                     f"{seconds(value['audible_estimate_saved_seconds']['mean'])} | {value['pcm_equal']}/{value['valid_pairs']} |")
    lines += ['', '正值表示组合更快。PCM变化意味着生成内容/韵律/静音长度可能变化；有声时刻的差值不能全部解释为计算加速。', '',
              '## 首包前阶段均值（秒）', '',
              '| 配置/输入 | prefill含首帧 | 首包前后续生成 | codec | 等待及其他准备 |',
              '| --- | ---: | ---: | ---: | ---: |']
    for name in ('control_start', 'combined'):
        value = report['arms'][name]
        for mode, phases in value.get('stage_seconds_by_mode', {}).items():
            average = lambda key: phases.get(key, {}).get('mean', 0.)
            other = sum(v['mean'] or 0 for k, v in phases.items() if k not in ('model.prefill','model.step','codec.decode'))
            lines.append(f"| {name}/{mode} | {seconds(average('model.prefill'))} | {seconds(average('model.step'))} | "
                         f"{seconds(average('codec.decode'))} | {seconds(other)} |")
    lines += ['', '这些是同一服务进程内的区间分割；客户端时间不直接与服务端时间戳相减。', '',
              '## 控制组漂移与内容诊断', '']
    for mode, drift in report['control_drift'].items():
        lines.append(f"- {mode}：末尾control相对开头的首PCM平均提前 {seconds(drift['first_pcm_saved_seconds']['mean'])} 秒，"
                     f"模拟有声平均提前 {seconds(drift['audible_estimate_saved_seconds']['mean'])} 秒。")
    diagnostic = report['intelligibility']
    if diagnostic:
        lines += ['', f"离线ASR共检查 {diagnostic['responses']} 条、{diagnostic['unique_audio']} 个不同WAV；"
                  '只辅助检验漏读/重复，不代替真人自然度试听。', '',
                  '| 输入/配置 | 尝试/失败 | ASR词错误/参考词 | 整句匹配 |', '| --- | ---: | ---: | ---: |']
        for mode, groups in diagnostic['by_mode'].items():
            for name, value in groups.items():
                lines.append(f"| {mode}/{name} | {value['attempts']}/{value['failures']} | "
                             f"{value['word_errors']}/{value['reference_words']} | {value['exact_sentences']} |")
    else:
        lines += ['', '离线ASR诊断尚未完成。']
    lines += ['', '## 判断', '']
    combined = report['arms']['combined']
    if combined['status'] == 'complete':
        for mode, value in combined['modes'].items():
            voice = value['audible_estimate_seconds']
            lines.append(f"- {mode}：模拟有声均值 {seconds(voice['mean'])} 秒、p50 {seconds(voice['p50'])} 秒、"
                         f"p95 {seconds(voice['p95'])} 秒；"
                         + ('本小集合达到300ms描述性上界。' if voice['p95'] is not None and voice['p95'] <= .3
                            else '尚不能支持可听首音稳定200–300ms。'))
    lines += ['', '若组合仍明显超出可听预算，应优先开展替代TTS的同输入对照，而不是把结果解释为必须更换ASR。'
              '更换组件的实际操作须依据用户对ASR/TTS指向的确认；本轮不替换模型。'
              '没有改动产品默认值，也未测试真实播放、人工自然度、FDB和端到端1秒目标。', '']
    return '\n'.join(lines)


def main():
    """Generate the same artifacts locally or remotely from saved run data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--intelligibility', type=Path)
    args = parser.parse_args()
    report = build(args.run.resolve(), args.intelligibility)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'tts_combination_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (args.output / 'tts_combination_validation.md').write_text(render(report))
    print(json.dumps({'complete': report['complete'], 'exit': report['exit_code'],
                      'attempts': {k:v.get('attempts',0) for k,v in report['arms'].items()}}), flush=True)


if __name__ == '__main__':
    main()
