"""Summarize the ASR streaming-contract comparison into markdown + JSON.

Inputs are the per-arm event streams written by
``scripts/remote/run_asr_contract_ab_node_job.sh`` (one ``<subset>/<sample>/``
directory per input, containing ``asr_events.jsonl`` and ``asr_report.json``).
Every event carries both the raw transcript ``text`` and the committed-prefix
transcript ``visible_text``, so one arm per decoder window answers both exposure
questions:

* **raw exposure** - what the official demo shows; a rewrite means the model
  replaced text it had already produced.
* **committed prefix** - what our runtime needs; a rewrite there would break the
  append-only contract the released DuplexCascade server relies on.

The cost of a wider decoder window shows up as a later commit: the audio-time
delay between the raw stream and the committed stream carrying the final word.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Optional

AUDIO_STEP_SECONDS = 0.08
# A committed prefix that lags the raw decode by more words than this for a
# stretch of ticks is the failure mode the token-level commit fixed: the old
# string comparison froze the visible transcript for the rest of the utterance.
BACKLOG_WORDS = 8


def read_events(path: Path) -> list[dict[str, Any]]:
    """Return the JSON events of one sample, skipping unreadable lines."""
    events = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return events
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def word_distance(left: str, right: str) -> int:
    """Return the word-level Levenshtein distance between two transcripts."""
    a, b = left.split(), right.split()
    previous = list(range(len(b) + 1))
    for i, word_a in enumerate(a, start=1):
        current = [i]
        for j, word_b in enumerate(b, start=1):
            cost = 0 if word_a == word_b else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


def event_time(event: dict[str, Any]) -> float:
    """Return the arrival time of one event, falling back to its audio position.

    ``arrival_seconds`` is wall clock; because the smoke replays the input at real
    time it tracks the audio position closely, and unlike ``audio_seconds`` it is
    also present on the terminal event.
    """
    for key in ('arrival_seconds', 'audio_seconds'):
        value = event.get(key)
        if value is not None:
            return float(value)
    return 0.0


def commit_lag(events: list[dict[str, Any]], word: str) -> Optional[float]:
    """Return how much later the committed stream first carries ``word``.

    The difference is the delay the committed-prefix contract adds for that word:
    the runtime receives it this much later than the raw decoder output would have.
    """
    if not word:
        return None
    raw_at = None
    visible_at = None
    for event in events:
        if raw_at is None and word in (event.get('text') or '').split():
            raw_at = event_time(event)
        if visible_at is None and word in (event.get('visible_text') or '').split():
            visible_at = event_time(event)
    if raw_at is None or visible_at is None:
        return None
    return visible_at - raw_at


def sample_stream(sample: Path) -> Optional[dict[str, Any]]:
    """Collect the observable contract of one sample."""
    events = read_events(sample / 'asr_events.jsonl')
    if not events:
        return None
    partials = [event for event in events if not event.get('final')]
    final = next((event for event in events if event.get('final')), None)
    if not partials:
        return None
    duration = float(partials[-1].get('audio_seconds') or 0.0)
    raw_changes = [event for event in partials if event.get('rewritten')]
    visible_changes = [event for event in partials if event.get('visible_rewritten')]
    settled = final or partials[-1]
    words = (settled.get('visible_text') or settled.get('text') or '').split()
    last_partial = partials[-1]
    # Words the committed prefix is behind the raw decode by. The decoder emits
    # bursts of text that it revises later, so a single tick is noisy; the
    # per-sample value is the median over its ticks.
    held_back = statistics.median([
        max(0, len((event.get('text') or '').split())
            - len((event.get('visible_text') or '').split()))
        for event in partials
    ]) if partials else 0
    # Longest stretch where the committed prefix fell that far behind: the
    # user-visible symptom of a frozen commit.
    freeze_seconds = 0.0
    run_start = None
    for event in partials:
        backlog = (len((event.get('text') or '').split())
                   - len((event.get('visible_text') or '').split()))
        if backlog >= BACKLOG_WORDS:
            if run_start is None:
                run_start = event_time(event)
        elif run_start is not None:
            freeze_seconds = max(freeze_seconds, event_time(event) - run_start)
            run_start = None
    if run_start is not None:
        freeze_seconds = max(freeze_seconds, event_time(partials[-1]) - run_start)
    subset, _, name = sample.name.partition('__')
    return {
        'sample': name or sample.name,
        'subset': subset,
        'audio_seconds': duration,
        'partials': len(partials),
        'raw_rewrites': len(raw_changes),
        'visible_rewrites': len(visible_changes),
        'commit_lag_seconds': commit_lag(events, words[-1] if words else ''),
        'held_back_words': held_back,
        'commit_stalls': int(last_partial.get('commit_stalls') or 0),
        'freeze_seconds': freeze_seconds,
        'raw_final_text': settled.get('text', ''),
        'visible_final_text': settled.get('visible_text', ''),
        'visible_partial_text': last_partial.get('visible_text', ''),
    }


def collect_arm(run_dir: Path, arm: str) -> list[dict[str, Any]]:
    """Collect every staged sample of one arm, in a deterministic order."""
    rows = []
    root = run_dir / arm
    if not root.is_dir():
        return rows
    for path in sorted(root.rglob("asr_events.jsonl")):
        row = sample_stream(path.parent)
        if row is not None:
            rows.append(row)
    return rows


def format_seconds(value: Optional[float]) -> str:
    """Render an optional number of seconds."""
    return '-' if value is None else f'{value:.2f}'


def summarize_arm(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one arm's per-sample observations."""
    if not rows:
        return {'samples': 0}
    lags = [row['commit_lag_seconds'] for row in rows
            if row['commit_lag_seconds'] is not None]
    held_back = [row['held_back_words'] for row in rows]
    return {
        'samples': len(rows),
        'audio_seconds': sum(row['audio_seconds'] for row in rows),
        'raw_rewrites': sum(row['raw_rewrites'] for row in rows),
        'visible_rewrites': sum(row['visible_rewrites'] for row in rows),
        'samples_with_raw_rewrites': sum(1 for row in rows if row['raw_rewrites']),
        'commit_lag_samples': len(lags),
        'commit_lag_median_seconds': statistics.median(lags) if lags else None,
        'commit_lag_max_seconds': max(lags) if lags else None,
        'held_back_words_median': statistics.median(held_back) if held_back else None,
        'held_back_words_max': max(held_back) if held_back else None,
        'commit_stalls': sum(row['commit_stalls'] for row in rows),
        'samples_with_stalls': sum(1 for row in rows if row['commit_stalls']),
        'freeze_seconds_median': statistics.median(
            [row['freeze_seconds'] for row in rows]) if rows else None,
        'freeze_seconds_max': max(row['freeze_seconds'] for row in rows) if rows else None,
        'visible_partial_tail_missing': sum(
            1 for row in rows
            if row['visible_final_text'].strip()
            and not row['visible_final_text'].startswith(row['visible_partial_text'])
        ),
    }


def main() -> int:
    """Write the JSON and markdown summaries of one contract comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True,
                        help='data/runs/asr_contract_<tag>')
    parser.add_argument('--report-dir', type=Path, required=True,
                        help='reports/asr_contract/<tag>')
    parser.add_argument('--tag', default='')
    parser.add_argument('--baseline', default='window-0',
                        help='arm whose final transcripts are the reference')
    args = parser.parse_args()

    arms = [path.name for path in sorted(args.run_dir.glob('window-*')) if path.is_dir()]
    if not arms:
        arms = [f'window-{window}' for window in (0, 2)]
    per_arm = {arm: collect_arm(args.run_dir, arm) for arm in arms}
    summaries = {arm: summarize_arm(rows) for arm, rows in per_arm.items()}
    baseline_rows = per_arm.get(args.baseline, [])

    def baseline_for(row: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Return the baseline row of the same sample, if any."""
        for candidate in baseline_rows:
            if candidate['subset'] == row['subset'] and candidate['sample'] == row['sample']:
                return candidate
        return None

    for arm, rows in per_arm.items():
        visible_distances = []
        raw_distances = []
        for row in rows:
            reference = baseline_for(row)
            if reference is None:
                continue
            visible_distances.append(
                word_distance(reference['visible_final_text'], row['visible_final_text']))
            raw_distances.append(
                word_distance(reference['raw_final_text'], row['raw_final_text']))
        summary = summaries[arm]
        summary['visible_final_distance_median'] = (
            statistics.median(visible_distances) if visible_distances else None)
        summary['raw_final_distance_median'] = (
            statistics.median(raw_distances) if raw_distances else None)
        summary['samples_compared'] = len(visible_distances)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        'tag': args.tag,
        'run_dir': str(args.run_dir),
        'baseline': args.baseline,
        'arms': {arm: {'summary': summaries[arm], 'samples': per_arm[arm]} for arm in arms},
    }
    (args.report_dir / 'asr_contract.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')

    lines = [
        '# ASR 流式契约对比（解码窗口 × 暴露口径）',
        '',
        f"- tag: `{args.tag}`",
        f'- run dir: `{args.run_dir}`',
        '- 每个 arm 只改 `unfixed_chunk_num`（`0` = 我们的配置，`2` = 官方默认）；`unfixed_token_num` 固定为 5。'
        ' 各 arm 都在一条事件里同时记录 raw 转写与"只暴露已定稿前缀"的转写，所以两种暴露口径在同一轮里同时被测。',
        '- `raw 改写` = 官方示例口径下模型替换已产出文本的次数；`可见改写` = 我们口径下运行时看到的改写次数，**必须为 0**；',
        '- `提交延迟` = 最终词在"已定稿前缀"里首次出现的时间减去它在 raw 转写里首次出现的时间（即运行时比官方口径晚多久拿到这个词）；'
        '`挂起的词` = 每一拍 raw 转写比已定稿前缀多出的词数在**该样本内取中位数**（刻意扣住的可改写尾巴有多长）；'
        f'`冻结` = 定稿前缀落后 raw 超过 {BACKLOG_WORDS} 个词的最长连续时长（token 级提交修复前的症状）；'
        '`提交停滞` = 解码器回改到"已交给调用方"的 token 的次数（正常应为 0）；'
        '`最终转写距离` = 与 baseline arm 的**词级**编辑距离中位数。',
        '',
        '| arm | 样本 | 音频 s | raw 改写 | 可见改写 | 有改写的样本 | 提交延迟 中位/最大 s | 挂起的词 中位/最大 | 冻结 中位/最大 s | 提交停滞 | 可见最终距离 | raw 最终距离 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |',
    ]
    for arm in arms:
        summary = summaries[arm]
        if not summary.get('samples'):
            lines.append(f'| {arm} | 0 | - | - | - | - | - | - | - | - | - | - |')
            continue
        lines.append(
            '| {arm} | {samples} | {audio} | {raw} | {visible} | {with_raw} | {lag} / {lag_max} | {held} / {held_max} | {freeze} / {freeze_max} | {stalls} | {vdist} | {rdist} |'.format(
                arm=arm,
                samples=summary['samples'],
                audio=summary['audio_seconds'],
                raw=summary['raw_rewrites'],
                visible=summary['visible_rewrites'],
                with_raw=summary['samples_with_raw_rewrites'],
                lag=format_seconds(summary['commit_lag_median_seconds']),
                lag_max=format_seconds(summary['commit_lag_max_seconds']),
                held=summary['held_back_words_median'],
                held_max=summary['held_back_words_max'],
                freeze=format_seconds(summary['freeze_seconds_median']),
                freeze_max=format_seconds(summary['freeze_seconds_max']),
                stalls=summary['commit_stalls'],
                vdist='-' if summary.get('visible_final_distance_median') is None
                else f"{summary['visible_final_distance_median']:.1f}",
                rdist='-' if summary.get('raw_final_distance_median') is None
                else f"{summary['raw_final_distance_median']:.1f}",
            ))

    lines += ['', '## 判据', '']
    lines.append(
        '- **可见改写必须为 0**（任一 arm 出现非 0 就说明该配置不能给运行时用）；')
    lines.append(
        f'- 若 `window-2` 相对 `{args.baseline}` 的**可见最终距离中位数明显大于 0**，说明官方窗口会改变我们最终交给模型的文本，'
        '此时要看它多花的提交延迟（运行时晚多久拿到词）再决定是否对齐官方；')
    lines.append(
        '- 若两者最终距离都为 0 且 `window-2` 的提交延迟更大，则保持 `unfixed_chunk_num: 0`（当前配置）。')
    (args.report_dir / 'asr_contract.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
