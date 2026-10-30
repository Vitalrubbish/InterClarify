# 英文来源首轮审核证据

2026-10-23，XTX-009 首轮审核。DailyTalk 和 SwDA 各 24 个不同原始会话，共 48 个观察点。Codex 单次辅助审核，非双人人工试标；完整方法、来源和限制见[审核报告](../../../docs/archive/dev/XTurnix/source_audit.md)。

结果为 Listen/start 条件候选 23、Listen/keep 条件候选 4、Speak/keep 条件候选 3、歧义 18；Speak/stop 明确候选 0，当前可直接冻结的训练记录 0。48 个会话全部排除出后续独立测试。

| 文件 | 内容 |
| --- | --- |
| reviews.csv（原始文件`reviews.csv`已归档） | 48 条候选或歧义判断、中文依据和证据缺口 |
| manifest.json（原始文件`manifest.json`已归档） | 逐例来源、版本、会话/说话人、观察记录序号与 SHA256；无对话正文 |
| source_requests.json（原始文件`source_requests.json`已归档） | 正式采集 r2 的 URL、真实 HTTP Range、字节数与片段摘要 |
| summary.json（原始文件`summary.json`已归档） | 分母、候选分布、审核方式、资源与结果摘要 |

本地完整审查包：`artifacts/xturnix_source_audit/20261023-first-review-r2/packets.json`。可以通过[采集脚本](../../../archive/scripts/analysis/collect_xturnix_source_audit.py)在新输出目录复现，原始正文与音频不进入 Git。重采集不能覆盖旧 run；人工/辅助审核意见不由脚本自动生成。

## 原始产物保存

本页为Git保留的结果汇总；逐例JSON／CSV、trace、样本正文及资源采样不再入库。本地归档位于`artifacts/report_archive/reports/xturnix_training/20261023-source-audit/`，具体文件与SHA256见本地`artifacts/report_archive/archive_index.json`；已有远端run路径保持原样。复现时读取归档，不从报告链接下载原始产物。Git历史未重写。
