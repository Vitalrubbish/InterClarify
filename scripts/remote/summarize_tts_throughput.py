"""Summarize the MOSS-TTS throughput A/B run into a markdown + JSON report.

Inputs are the per-arm artifacts written by
``scripts/remote/run_tts_throughput_ab_node_job.sh``: the client-side smoke report
(``<arm>-<phase>/tts_report.json``, with audio seconds, wall seconds and
first-audio latency) and the service-side ``[tts-metric]`` / ``[moss-patch]`` log
lines per arm.  The steady-state real-time factor is

    RTF = audio_seconds / (wall_seconds - first_audio_seconds)

which excludes the one-off session start and prefill, i.e. it answers "how many
seconds of audio does this arm synthesize per second of GPU time once it is
running".
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any, Optional

METRIC_RE = re.compile(
    r"\[tts-metric\].*?reason=(\S+)\s+line=(\d+)\s+frames=(\d+)\s+audio_s=([0-9.]+)\s+"
    r"wall_s=([0-9.]+)\s+rtf=([0-9.]+)"
    r"(?:\s+local_s=([0-9.]+)\s+backbone_s=([0-9.]+))?"
)
PATCH_RE = re.compile(r"\[moss-patch\]\s+(.*)")
PROFILE_RE = re.compile(
    r"\[moss-patch\] profile frames=(\d+) device_s=([0-9.]+) cpu_s=([0-9.]+) top=(.*)$"
)


def load_json(path: Path) -> dict:
    """Return the parsed JSON file, or an empty mapping when unreadable."""
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def read_lines(path: Path) -> list[str]:
    """Return the file's lines, or an empty list when unreadable."""
    try:
        return path.read_text(errors="replace").splitlines()
    except Exception:
        return []


def summarize_arm(run_dir: Path, arm: str) -> dict[str, Any]:
    """Collect the client and service numbers of one arm."""
    result: dict[str, Any] = {"arm": arm}
    patches = [match.group(1) for match in (PATCH_RE.search(line) for line in read_lines(run_dir / 'metrics' / f'{arm}.patch.log')) if match]
    result['patch_lines'] = patches
    result['fallback'] = any('falling back' in line or 'failed' in line for line in patches)
    result['compiled'] = any('torch.compile(_local_loop) ready' in line for line in patches)
    result['warmup_seconds'] = None
    for line in patches:
        match = re.search(r"warmup done in ([0-9.]+)s", line)
        if match:
            result['warmup_seconds'] = float(match.group(1))

    result['engaged'] = any('compiled path engaged' in line for line in patches)
    result['profile'] = None
    for line in patches:
        match = PROFILE_RE.search(line)
        if match:
            result['profile'] = {
                'frames': int(match.group(1)),
                'device_seconds': float(match.group(2)),
                'cpu_seconds': float(match.group(3)),
                'top': match.group(4).strip(),
            }

    metrics = []
    for line in read_lines(run_dir / 'metrics' / f'{arm}.metric.log'):
        match = METRIC_RE.search(line)
        if match:
            metrics.append({
                'reason': match.group(1),
                'line': int(match.group(2)),
                'frames': int(match.group(3)),
                'audio_seconds': float(match.group(4)),
                'wall_seconds': float(match.group(5)),
                'rtf': float(match.group(6)),
                'local_seconds': float(match.group(7) or 0.0),
                'backbone_seconds': float(match.group(8) or 0.0),
            })
    result['turns'] = metrics
    frames_total = sum(item['frames'] for item in metrics)
    audio_total = sum(item['audio_seconds'] for item in metrics)
    wall_total = sum(item['wall_seconds'] for item in metrics)
    local_total = sum(item['local_seconds'] for item in metrics)
    backbone_total = sum(item['backbone_seconds'] for item in metrics)
    result['service_frames'] = frames_total
    result['service_audio_seconds'] = audio_total
    result['service_wall_seconds'] = wall_total
    result['service_rtf'] = (audio_total / wall_total) if wall_total else None
    result['service_rtf_median'] = statistics.median([item['rtf'] for item in metrics]) if metrics else None
    result['local_share'] = (local_total / wall_total) if wall_total else None
    result['backbone_share'] = (backbone_total / wall_total) if wall_total else None
    profile = run_dir / 'metrics' / f'{arm}.profile.txt'
    result['profile_file'] = profile.name if profile.is_file() else None

    for phase in ('cold', 'warm'):
        report = load_json(run_dir / f'{arm}-{phase}' / 'tts_report.json')
        first_audio = report.get('first_audio_seconds')
        wall = report.get('wall_seconds')
        audio = report.get('audio_seconds')
        steady_wall = None
        if wall is not None and first_audio is not None:
            steady_wall = max(1e-9, float(wall) - float(first_audio))
        result[phase] = {
            'status': report.get('status'),
            'audio_seconds': audio,
            'wall_seconds': wall,
            'first_audio_seconds': first_audio,
            'flush_seconds': report.get('flush_seconds'),
            'audio_chunks': report.get('audio_chunks'),
            'text_chunk_count': report.get('text_chunk_count'),
            'steady_rtf': (float(audio) / steady_wall) if (audio is not None and steady_wall) else None,
            'end_to_end_rtf': (float(audio) / float(wall)) if (audio is not None and wall) else None,
        }
    return result


def format_seconds(value: Optional[float], digits: int = 2) -> str:
    """Render an optional number with a fixed precision."""
    return '-' if value is None else f'{value:.{digits}f}'


def format_ratio(value: Optional[float], digits: int = 1) -> str:
    """Render an optional speedup ratio."""
    return '-' if value is None else f'{value:.{digits}f}x'


def format_percent(value: Optional[float]) -> str:
    """Render an optional share of the wall clock as an integer percentage."""
    return '-' if value is None else f'{100.0 * value:.0f}%'


def main() -> int:
    """Write the JSON and markdown summaries for one A/B run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True, help='data/runs/tts_throughput_<tag>')
    parser.add_argument('--report-dir', type=Path, required=True, help='reports/tts_throughput/<tag>')
    parser.add_argument('--tag', default='')
    parser.add_argument('--baseline', default='baseline', help='arm used as the speedup reference')
    args = parser.parse_args()

    arms = sorted(
        {path.name[: -len('-warm')] for path in args.run_dir.glob('*-warm') if path.is_dir()},
        key=lambda name: (name != args.baseline, name),
    ) if args.run_dir.is_dir() else []
    if not arms:
        arms = ['baseline', 't2-greedy', 't2-topk', 't1-inductor', 't1-cudagraph']
    summaries = [summarize_arm(args.run_dir, arm) for arm in arms]
    baseline = next((item for item in summaries if item['arm'] == args.baseline), None)
    baseline_rtf = (baseline or {}).get('warm', {}).get('steady_rtf')
    for item in summaries:
        steady = item.get('warm', {}).get('steady_rtf')
        item['speedup_vs_baseline'] = (
            steady / baseline_rtf if (steady and baseline_rtf) else None
        )

    args.report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        'tag': args.tag,
        'run_dir': str(args.run_dir),
        'baseline': args.baseline,
        'baseline_steady_rtf': baseline_rtf,
        'arms': summaries,
    }
    (args.report_dir / 'tts_throughput.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8'
    )

    lines = [
        '# MOSS-TTS-Realtime 吞吐 A/B',
        '',
        f"- tag: `{args.tag}`",
        f'- run dir: `{args.run_dir}`',
        '- 固定文本、`--stream-chunk-words 6 --gap-seconds 0.02`、同一张卡的同一份权重；每个 arm 重启服务（各自独立端口），先跑 `cold` 再跑 `warm`。',
        '- 每个 arm 只改一个变量：`t1-*` 只改本地码本循环的执行后端（采样保持 upstream），`t2-*` 只改采样头（编译保持 off）。',
        '- `steady rtf = audio_s / (wall_s - first_audio_s)`：剔除一次性的会话启动与 prefill；`服务端 rtf` = `Σaudio_s/Σwall_s`（对所有 `[tts-metric]` 行求和，中位数另列），`local/backbone 占比` = 该 arm 的 CUDA event 累计秒数 ÷ 墙钟。',
        '',
        '| arm | 编译 | 生效 | cold 首包 s | warm 首包 s | warm 音频 s | warm 墙钟 s | steady rtf | 服务端 rtf | 服务端中位 | local 占比 | backbone 占比 | 相对 baseline | 状态 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |',
    ]
    for item in summaries:
        cold, warm = item.get('cold', {}), item.get('warm', {})
        if not warm.get('audio_seconds'):
            status = 'FAILED'
        elif item['fallback']:
            status = 'compile 回退'
        elif item['compiled'] and not item['engaged']:
            status = '编译未生效'
        elif item['compiled']:
            status = 'compiled'
        else:
            status = '上游路径'
        lines.append(
            '| {arm} | {compile} | {engaged} | {cold} | {warm} | {audio} | {wall} | {rtf} | {srtf} | {smed} | {local} | {backbone} | {speedup} | {status} |'.format(
                arm=item['arm'],
                compile='是' if item['compiled'] else '否',
                engaged='是' if item['engaged'] else '否',
                cold=format_seconds(cold.get('first_audio_seconds')),
                warm=format_seconds(warm.get('first_audio_seconds')),
                audio=format_seconds(warm.get('audio_seconds')),
                wall=format_seconds(warm.get('wall_seconds')),
                rtf=format_seconds(warm.get('steady_rtf'), 2),
                srtf=format_seconds(item.get('service_rtf'), 2),
                smed=format_seconds(item.get('service_rtf_median'), 2),
                local=format_percent(item.get('local_share')),
                backbone=format_percent(item.get('backbone_share')),
                speedup=format_ratio(item.get('speedup_vs_baseline')),
                status=status,
            )
        )
    profiled = [item for item in summaries if item.get('profile')]
    if profiled:
        lines += [
            '',
            '## profile（`torch.profiler`，每回合最初的若干帧）',
            '',
            '| arm | 剖析帧数 | device 合计 s | cpu 合计 s | device/帧 ms | top kernel（按 device 时间） |',
            '| --- | --- | --- | --- | --- | --- |',
        ]
        for item in profiled:
            profile = item['profile']
            frames = max(1, profile['frames'])
            lines.append(
                '| {arm} | {frames} | {device} | {cpu} | {per} | {top} |'.format(
                    arm=item['arm'],
                    frames=profile['frames'],
                    device=format_seconds(profile['device_seconds'], 3),
                    cpu=format_seconds(profile['cpu_seconds'], 3),
                    per=format_seconds(1000.0 * profile['device_seconds'] / frames, 1),
                    top=profile['top'].replace('|', '/') or '-',
                )
            )
        lines.append(
            '- `device/帧` 是**实际执行的 kernel 时间**；拿它与同一 arm 的墙钟/帧对比，差值就是 GPU 等 CPU 发活的时间（eager 逐算子派发时通常占大头）。'
        )
        lines.append('- 剖析期间的墙钟被 profiler 拖慢，所以 profile 臂的 rtf 不可当读数，只看本表。')

    lines += ['', '## 说明', '']
    if baseline_rtf:
        lines.append(
            f"- baseline 稳定态 rtf = **{baseline_rtf:.2f}**（>1 才追得上实时；本轮 A4 实测交付率约 0.2–0.5）。"
        )
    if any(item['fallback'] for item in summaries):
        lines.append('- `compile 回退` = 本地编译或图捕获失败并退回 eager，原因与 traceback 见 `metrics/<arm>.patch.log`。')
    if any(item['compiled'] and not item['engaged'] for item in summaries):
        lines.append('- `编译未生效` = 编译产物建好了，但推理没走到编译路径（窗口未饱和或 warmup 失败），该 arm 的读数不是编译后的成绩。')
    profiled = [item['arm'] for item in summaries if item.get('profile_file')]
    if profiled:
        lines.append(
            '- profile 臂（%s）的逐 kernel 表在 `metrics/<arm>.profile.txt`，用来判断时间花在 codec 解码、backbone 前向还是本地码本循环上。'
            % '、'.join(profiled)
        )
    lines += [
        '- 判据：`t1-*` 只有在 `编译=是` 且 `生效=是` 且 `warm` rtf 明显高于 baseline 时才算成立；',
        '- 采样档位（`t2-greedy`/`t2-topk`）会改变音频内容，质量需试听 `warm/tts.wav`，本报告只给吞吐。',
    ]
    (args.report_dir / 'tts_throughput.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
