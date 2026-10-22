# 工作单管理

更新：2026-10-22。

用户已取消 FDB 测试，现要求在历史 FLEURS 100 条上保留基本转写 WER 与末端文本延迟，只把控制测试简化为输入结束后的 complete 输出率和首次延迟。X2Q-009 已完成固定输入恢复；尚未实现回放、评分或模型测试。[当前协议](../dev/X2-Turn/complete_test_on_fleurs.md)。

按确认后的范围重新拆分为六个工作单元，沿用尚未实施的编号 X2Q-009—011 并细化职责，新增 X2Q-012—014；不保留重复的旧入口。

| 当前工作单 | 内容 | 依赖 | 状态 |
| --- | --- | --- | --- |
| [X2Q-010](x2q_010_x2_turn_deployment.md) | 远端 conda、模型及流式服务部署 | X2Q-008；预热需 X2Q-009 | 进行中 |
| [X2Q-011](x2q_011_streaming_replay.md) | 真实时钟回放与原始 trace | X2Q-009、010 的合同 | 待实施 |
| [X2Q-012](x2q_012_asr_metrics.md) | 转写 WER 与平均末端文本延迟 | X2Q-009、011 的合同 | 待实施 |
| [X2Q-013](x2q_013_complete_metrics.md) | complete 输出率与首次延迟 | X2Q-011 的合同 | 待实施 |
| [X2Q-014](x2q_014_fleurs_evaluation.md) | 远端冒烟、100 条正式测试及报告 | X2Q-009—013 完成 | 待执行 |

默认按表中顺序推进；合同确定后可以用模拟记录先验证逻辑，正式模型结果统一在 X2Q-014 生成。各单完成后直接归档并更新索引。本次只重整工作单，不开始数据恢复或模型作业。

简化协议 [X2Q-008](archive/x2q_008_complete_protocol.md) 已完成归档。以下为历史记录。

| 工作单 | 工作单元 | 状态 | 归档说明 |
| --- | --- | --- | --- |
| [X2Q-002](archive/x2q_002_fdb_references.md) | FDB 清单与参考 | 已取消 | 用户取消 FDB 测试 |
| [X2Q-003](archive/x2q_003_streaming_replay.md) | 部署与 FDB 回放 | 已取消 | 尚未实施 |
| [X2Q-004](archive/x2q_004_state_judger.md) | FDB 状态 Judger | 已取消 | 尚未实施 |
| [X2Q-005](archive/x2q_005_quality_metrics.md) | FDB 质量评分 | 已取消 | 尚未实施 |
| [X2Q-006](archive/x2q_006_remote_quality_run.md) | FDB 正式测试 | 已取消 | 尚未执行 |
| [X2Q-007](archive/x2q_007_fleurs_verification.md) | 历史 FLEURS 与远端现状核查 | 已完成 | 未下载数据或启动模型 |

已完成并归档：[X2Q-001：实现机制调研与评测计划](archive/x2q_001_quality_plan.md)。[X2Q-009：恢复并冻结 FLEURS 英文子集](archive/x2q_009_fleurs_data.md) 已于 2026-10-22 完成远端恢复与复核；证据见 [报告](../../reports/x2_turn_complete/20261022-fleurs-subset/README.md) 与 [脚本说明](../../docs/scripts/remote/x2_turn_complete_test.md)。

历史数据依据见 [FLEURS 子集核查](../dev/X2-Turn/fleurs_subset_verification.md)。研究范围与模块职责仍以 [research_design.md](../research_design.md)、[engineering_implementation.md](../engineering_implementation.md) 为准。
