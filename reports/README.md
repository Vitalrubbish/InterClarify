# 实验报告

当前路线为 SoulX-Duplug 原生控制＋独立 X2Streaming-ASR，以及普通半双工 LLM／TTS 评测。Layer 1／2 接入与专项训练尚未实施。

| 报告 | 用途 |
| --- | --- |
| [半双工首轮评测](../docs/reports/soulx/20261105-fdb30-half-duplex/README.md) | 固定 30 条 TOR／延迟、原始低分与限制 |
| [控制积压归因](../docs/reports/soulx/20261105-fdb30-half-duplex/control_backlog_analysis.md) | 首轮延迟长尾与接话失败的逐例依据 |
| [修复后复测](../docs/reports/soulx/20261105-ntf054-retest/README.md) | NTF-054 活动证据；完整复测尚未完成 |

早期独立前端验收和 complete 审计已结束，其报告与退役工具可从 Git 历史追溯，不再作为当前入口。原始 run、日志和产物保留在远端及本地 `artifacts/`，本轮不修改或删除。

Git 保留审阅后的结论、分母、限制、源码／模型版本及必要审计摘要；已跟踪的 11 月 5 日评测与活动复测 JSON 继续保留。权重、音频、大日志和后续原始逐帧输出不提交，不使用 `git add -f` 绕过忽略规则，也不重写 Git 历史。
