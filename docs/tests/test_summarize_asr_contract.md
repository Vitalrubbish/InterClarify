# `tests/test_summarize_asr_contract.py`

## 功能与边界

验证 `scripts/remote/summarize_asr_contract.py`：它决定一个运行时契约（`unfixed_chunk_num` 是否与官方对齐），所以计数口径必须精确。测试用合成的 `asr_events.jsonl` 造样本，不加载模型、不需要 GPU。

## 用例

| 用例 | 断言 |
| --- | --- |
| `WordDistanceTests`（2 个） | 相同转写距离为 0；距离按**词**计（替换/插入各计 1） |
| `SampleStreamTests`（5 个） | `commit_stalls` 与 `freeze_seconds`（定稿前缀落后 raw 超过 8 个词的连续时长）可从事件流读出；健康样本两者都为 0 |
| `SampleStreamTests`（3 个） | raw 与可见改写分别计数；提交延迟按 `arrival_seconds` 计算、挂起的词数按最后一个 partial 的 raw/可见词数差计算；被替换的可见文本会被记为可见改写；缺事件流的样本返回 `None` 而不是假行 |
| `ReportTests` | 两臂报告：样本数、raw 改写、baseline 距离为 0、较宽窗口的可见最终距离（词级中位数）、提交延迟与挂起的词数都正确；Markdown 与 JSON 同时产出 |

## 运行

```bash
conda run -n xtalk-round1-client python -m unittest tests.test_summarize_asr_contract
```
