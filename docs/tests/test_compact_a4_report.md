# `tests/test_compact_a4_report.py`

## 功能与边界

验证 `scripts/remote/compact_a4_report.py` 的压缩策略：只把"原始流"折算成计数、截断超长字符串、把采样 CSV 变成数值摘要，**不丢判据**。全程只用标准库与临时目录，不需要 GPU、模型或集群，任意 conda 环境可跑。

## 用例

| 用例 | 断言 |
| --- | --- |
| `test_event_stream_becomes_histogram` | `events` 变成 `{ticks, by_event}`，并给出 `span_seconds` |
| `test_token_stream_becomes_histogram` | `raw_outputs`/`protocol_tokens` 变成按 token 的直方图（任务单判读 `<\|user is talking\|>` / `interruption` 次数就靠它） |
| `test_played_text_keeps_last_snapshot` | `timeline.played_text.<id>` 变成 `{snapshots, last}` |
| `test_long_strings_are_truncated_with_a_marker` | 超 `MAX_STRING` 的字符串保留头部并标注被截断的字符数 |
| `test_scalars_and_ids_survive` | `status`/`errors`/`response_ids`/时延/字节数等判据字段原样保留 |
| `test_csv_becomes_a_numeric_summary` | `*_samples.csv` 变成 `{rows, columns: {min, median, max}}`，非数值列被跳过 |
| `test_main_rewrites_a_report_directory` | 端到端：目录内 JSON 就地压缩、CSV 被摘要 JSON 取代 |

## 运行

```bash
conda run -n xtalk-round1-client python -m unittest tests.test_compact_a4_report
```
