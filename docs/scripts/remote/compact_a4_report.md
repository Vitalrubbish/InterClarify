# `scripts/remote/compact_a4_report.py`

## 作用与边界

把 A4 作业复制进 `reports/duplex_acceptance/<tag>/` 的证据**就地紧凑化**，控制 git 提交的行数。一次完整跑原本会把上百 KB 的逐拍数组（`events`、`timeline.played_text`、`raw_outputs`/`protocol_tokens`）与两份采样 CSV 带进版本库，单文件数千行、整体上万行，而其中的判据信息只有几个计数。

紧凑化只动"原始流"，**不动结论**：状态、错误列表、id、时延、字节数、日志与 `steps.jsonl` 原样保留；完整数组不会丢失，仍在 git-ignored 的 `data/runs/<tag>/` 里与音频放在一起。由 `run_xtalk_duplex_a4_node_job.sh` 在复制证据后自动调用，也可手工对历史 tag 重跑。

## 改写规则

| 原始内容 | 紧凑化结果 |
| --- | --- |
| `events`（逐拍事件列表，每项一个 dict） | `{"ticks": <.>, "by_event": {<事件名>: <次数>}}` |
| `timeline.played_text.<response_id>`（已播文本快照列表） | `{"<response_id>": {"snapshots": <.>, "last": "<最后一条>"}}` |
| `timeline.raw_outputs`、`timeline.protocol_tokens`（token / 标记流） | `{"count": <.>, "tokens": {<token>: <次数>}}`，即 A4 任务单需要的 `<\|user is talking\|>` / `interruption` 等计数 |
| 超过 600 字符的字符串（模型回答、ASR 终稿） | 保留前 600 字符 + `…[truncated N chars]` |
| `*_samples.csv`（显存 / RSS 采样） | 同名 `<name>_summary.json`：`rows` 与每列的 `min`/`median`/`max`，原 CSV 删除 |

`*.log`、`*.txt`、`steps.jsonl` 与其他 JSON 标量不动。

## 用法

```bash
# 作业内自动执行（复制证据之后）
python scripts/remote/compact_a4_report.py --report-dir reports/duplex_acceptance/<tag>

# 只看压缩效果，不写文件
python scripts/remote/compact_a4_report.py --report-dir reports/duplex_acceptance/<tag> --dry-run
```

退出码恒为 0；脚本会打印每个被改写文件的行数变化与总量。**对已提交过的 tag 重跑会改写 git 跟踪的文件**，需要随之提交（这正是 2026-10-14 把 `20261014T033949Z` 从约 1.2 万行压到千行以内所做的事）。
