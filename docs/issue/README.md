# 工作单管理

更新：2026-10-29。本页合并重复进度，区分当前研究路线与历史实验；不新建工作单、不改变原验收结论。当前研究前端采用 **SoulX-Duplug**，ASR 优先适配 Nemotron EN160、条件性回退 SenseVoiceSmall，见[研究方案](../research_design.md)与[工程计划](../engineering_implementation.md)。SoulX 适配尚未实施，公开英文集验证仍待重新确认执行。

## 工作单状态

| 工作单组 | 已记录进度 | 后续边界 |
| --- | --- | --- |
| [TextTurn](TextTurn/README.md) | 共 11 项：7 项完成归档、TT-009 终止归档、TT-004／010／011 未完成 | 保留旧路线证据，不自动继承为 SoulX 合同 |
| [XTurnix](XTurnix/README.md) | XTX-001—005 与 XTX-007 已完成归档；XTX-006 正式作业已取消；XTX-009 仅完成来源审核 | XTX-008—013 草案已撤下，不恢复旧训练或取消测试 |

TT-010 最新已记录核查为 **2026-10-27 12:47**：r5 数据已冻结并通过全量核查，train／pilot／dev 为 160／54／200 来源、52656／9526／75767 窗，pilot 为 train 子集。旧 pilot 两轮完成且重载通过；新版完成两轮评估，当时正在第 3／5 轮，尚未达到质量线。此为历史观察，不能据此断言现在仍 Running 或最终完成；见[修复与训练报告](../../reports/textturn/20261027-dataset-repair/README.md)。不自动进入 full 或恢复 TT-011。

TT-004 的 v2 评分已重评，接话语义覆盖不足，整体证据不足；TT-011 旧续接已停止，UltraChat 与 FDB 外部测试未提交。训练启动、工作交付和模型达标分别记录，不以启动或进程成功代替质量验收。

## 历史证据入口

| 内容 | 证据 |
| --- | --- |
| TextTurn 初始数据、模型与四类评测 | [数据冻结](../../reports/textturn/20261025-tt-001-freeze/README.md)、[训练](../../reports/textturn/20261025-tt-002-training/README.md)、[结果](../../reports/textturn/20261025-tt-004-results/README.md)、[v2 评分](../../reports/textturn/20261025-scoring-v2/README.md) |
| FDB 动作监控与 UltraChat 重测 | [480ms／160ms FDB 联合结果](../../reports/textturn/20261025-fdb-action-only/README.md)、[UltraChat 两周期结果](../../reports/textturn/20261025-ultrachat-prefix-retest/README.md) |
| TT-010 训练失败、修复与诊断 | [超时与续接停止](../../reports/textturn/20261026-tt-011-external-evaluation/README.md)、[放行／损失修复](../../reports/textturn/20261026-tt-010-loss-gate/README.md)、[动作平衡重训](../../reports/textturn/20261026-tt-010-balanced-training/README.md)、[四臂诊断](../../reports/textturn/20261026-training-diagnostics/README.md) |
| XTurnix FLEURS 与来源审核 | [工作单及冻结证据](XTurnix/README.md)、[48 会话审核](../dev/XTurnix/source_audit.md) |

## 管理约定

工作单仅按用户明确指令建立；交付满足验收后立即归档并同步索引。历史停止、回退、失败和未完成记录保留在对应报告或 Git，不在入口反复追加已失效的运行快照。真实模型训练和集群测试使用远端 conda 调度作业，资源限制按相应工作单与已确认修订执行；实现同步维护 `docs` 下同路径中文说明。
