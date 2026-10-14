# `tests/test_qwen3_asr_service.py`

## 覆盖对象与目的

在**不加载模型**的前提下验证 [qwen3_asr_service.py](../../scripts/remote/qwen3_asr_service.py) 的 HTTP 契约，以及"append-only"修法的核心不变式：调用方看到的转写只可能变长，永远不会被解码器的重解替换。

测试用 `importlib` 从脚本路径加载被测模块（不是 import 包），并用假的 `Qwen3ASRModel`（`processor.tokenizer` + `init_streaming_state` / `streaming_transcribe` / `finish_streaming_transcribe`）驱动逻辑。`qwen_asr` 只在 ASR conda 环境存在，因此本文件在缺少它时注入一个最小 stub（`parse_asr_output`：有 `<asr_text>` 就去掉语言前缀），使测试在客户端环境也能跑。

## 用例

| 用例 | 断言 |
| --- | --- |
| `TruncateTests.test_drops_the_trailing_tokens` | `truncate_tokens` 按 **token 数**（不是字符数）截断；token 数不足时返回空串 |
| `AdvanceCommittedTests.test_revision_cannot_shrink_or_replace_visible_text` | 解码器把尾巴换掉后，可见文本仍以首次给出文本为前缀 |
| `AdvanceCommittedTests.test_rewritten_tail_never_reaches_the_caller` | 被后续步骤替换掉的尾巴在任何时刻都不出现在可见文本里 |
| `OwnedServiceContractTests.test_session_lifecycle` | `POST /v1/session` → 两次 `POST /v1/recognize`（第二次必须是第一次的延长）→ `is_final=true` 释放全量且仍是延长 → 未知会话 404 → `DELETE` 返回 `{"ok": true}` |
| `OwnedServiceContractTests.test_default_mode_still_returns_the_raw_transcript` | 不开 `emit_committed_prefix` 时保持历史契约：直接返回 `state.text` |

## 为什么这些断言重要

运行时对"ASR 改写前缀"只有两个选择：回写历史（会污染已生成的回答）或拒绝改写。修法把问题前移到服务层，用"只返回已定稿前缀"让改写根本出不了服务。因此单测必须锁住：**单调性**（删掉这条断言，运行时就会重新看到 `REWRITE`）、**`is_final` 只释放不回退**（否则每次停顿都会产生一次假改写）、以及**默认档位不变**（避免影响不使用该开关的调用方）。

真实数据上的核对结论见 [阶段 A 任务单 §9.5](../../xtalk_a4_remote_acceptance.md)（逐拍核对工具已在 2026-10-14 清理中移除）。

## 运行

```bash
# 客户端环境（无 qwen_asr，走 stub）
PYTHONPATH="$PWD/xtalk/src:$PWD" python -m unittest tests.test_qwen3_asr_service
```

A4 节点作业把它并入 `tests/a4_driver_regression`（见 `run_xtalk_duplex_a4_node_job.sh`）。
