# 工作单管理

更新：2026-10-30。当前活动研究路线为 **Nemotron Teacher Forcing＋SoulX-Duplug 语音前端**，见[研究方案](../research_design.md)与[工程计划](../engineering_implementation.md)。TextTurn、VoxTurn、XTurnix 三条历史路线已按用户指令归档：路线文档移至[归档区](../archive/dev/README.md)，对应实现移至 [archive/](../../archive/README.md)，历史工作单保留在本地 `docs/issue/archive/`（不进入 Git）。

当前用户已授权 Nemotron Teacher Forcing 接入与 FDB 三轴固定小样本实验。下游 Agent 尚未切换到 SoulX，旧 Nemotron 公开英文集方案和旧文本控制器合同只作为历史设计，不恢复作业。

当前没有活动工作单。NTF-001／002 已完成并归档至本地 `archive/`：教师文字前端与屏障已实现，本地20项检查、远端309帧预检及30/30条正式回放通过，3185帧顺序复查通过。质量并未整体改善，见[报告](../../reports/soulx/20261030-nemotron-teacher-fdb30/README.md)。22:01核查服务器队列为空，未切换现役Agent或接入下游。

## 路线状态

| 路线 | 归档状态 | 入口 |
| --- | --- | --- |
| SoulX-Duplug | 当前活动：语音前端与 Shared Context 已实现，下游 LLM、思考与真实输出未接入 | [路线文档](../dev/SoulX-Duplug/README.md) |
| TextTurn | 已归档；共 11 项，7 项完成、TT-009 终止，TT-004／010／011 未完成 | [路线归档](../archive/dev/TextTurn/README.md) |
| VoxTurn | 已归档；仅完成现成权重与接入可行性调研，未部署 | [调研归档](../archive/dev/VoxTurn/research_assessment.md) |
| XTurnix | 已归档；XTX-001—005 与 XTX-007 完成，XTX-006 取消，XTX-009 仅完成来源审核 | [路线归档](../archive/dev/XTurnix/README.md) |

历史工作单不再维护进度，验收结论以归档文档和报告为准。TT-010 最后一次核查为 2026-10-27 12:47，r5 已冻结、pilot 未达质量线；该观察不表示作业仍在运行。XTX-008—013 草案已撤下，不恢复旧训练或已取消测试。

## 历史证据入口

| 内容 | 证据 |
| --- | --- |
| TextTurn 初始数据、模型与四类评测 | [数据冻结](../../reports/textturn/20261025-tt-001-freeze/README.md)、[训练](../../reports/textturn/20261025-tt-002-training/README.md)、[结果](../../reports/textturn/20261025-tt-004-results/README.md)、[v2 评分](../../reports/textturn/20261025-scoring-v2/README.md) |
| FDB 动作监控与 UltraChat 重测 | [480ms／160ms FDB 联合结果](../../reports/textturn/20261025-fdb-action-only/README.md)、[UltraChat 两周期结果](../../reports/textturn/20261025-ultrachat-prefix-retest/README.md) |
| TT-010 训练失败、修复与诊断 | [超时与续接停止](../../reports/textturn/20261026-tt-011-external-evaluation/README.md)、[放行／损失修复](../../reports/textturn/20261026-tt-010-loss-gate/README.md)、[动作平衡重训](../../reports/textturn/20261026-tt-010-balanced-training/README.md)、[四臂诊断](../../reports/textturn/20261026-training-diagnostics/README.md) |
| XTurnix FLEURS 与来源审核 | [FLEURS 报告](../../reports/xturnix_fleurs/20261023-xtx-005-smoke-a10/README.md)、[48 会话审核](../archive/dev/XTurnix/source_audit.md) |

## 管理约定

工作单仅按用户明确指令建立；交付满足验收后立即归档并同步索引。历史停止、回退、失败和未完成记录保留在对应报告、归档区或 Git，不在入口反复追加已失效的运行快照。真实模型训练和集群测试使用远端 conda 调度作业，资源限制按相应工作单与已确认修订执行；实现同步维护 `docs` 下同路径中文说明。
