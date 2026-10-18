# 历史全双工验收证据

本目录保存历史阶段 A 的紧凑报告，原始音频和完整时间线留在远端运行目录。当前英文开发目标为 Nemotron EN 160ms + Kokoro，执行任务见 [issue 索引](../../docs/issue/README.md)，历史解释见 [证据索引](../../docs/baseline_evidence.md)。历史 PASS 不代表新组合已验收。

| 目录 | 用途 |
| --- | --- |
| [20261015T060611Z](20261015T060611Z/) | Qwen/MOSS，后端 VAD 生效后的对照 |
| [20261015T114708Z-r1](20261015T114708Z-r1/) | Qwen 分段重建修复复测及官方评分 |
| [20261015T172109Z](20261015T172109Z/) | X2 首轮预热失败证据 |
| [20261015T180154Z](20261015T180154Z/) | X2/MOSS 预热修复及 FDB 回归 |
| [20261016T044445Z](20261016T044445Z/) | 后续控制回放与延迟复核 |
| [reference](reference/) | 上游参考结果图 |

单次报告可能包括来源、环境、模型 health、逐步骤状态、回放摘要、官方分数、对齐记录和资源摘要；实际文件以各目录为准。`PASS` 只表示相应执行门禁通过，`SKIPPED` 或待评分不是语义质量合格。不同 judge 的内容分数不可直接跨轮比较，TOR 与新回答覆盖分开解释。

文档清理不改写本目录原始数值。报告精简规则见 [compact_a4_report](../../docs/scripts/remote/compact_a4_report.md)，大音频、权重与完整日志不进入 Git。旧任务步骤可从 [清理前固定提交](https://github.com/Vitalrubbish/InterClarify/tree/c614d55/docs) 恢复。
