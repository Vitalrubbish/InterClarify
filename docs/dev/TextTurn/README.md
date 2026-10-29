# TextTurn：历史文本话轮控制器路线

更新：2026-10-29。当前研究前端已选用[SoulX-Duplug](../SoulX-Duplug/README.md)。TextTurn保留Nemotron EN160＋Qwen3-0.6B文本控制器的数据、训练与评测证据，不作为SoulX的输入或动作合同。

## 已交付与未完成

[工作单](../../issue/TextTurn/README.md)共11项：7项完成、TT-009终止归档、TT-004／010／011未完成。初始数据、模型及Context接口已交付；四类验收v2因接话语义覆盖不足仍证据不足。480ms／160ms FDB动作监控及UltraChat重测已交付归档，不能据行为统计宣称完整语义能力通过。

TT-010的r5修复已实现并冻结：train160／pilot54／dev200来源、52656／9526／75767窗。最新报告记录于2026-10-27 12:47：旧pilot两轮及重载完成，新版两轮评估完成、当时正在第3／5轮，整体质量仍未通过；当前作业与最终重载状态未重新核查。见[修复与训练记录](../../../reports/textturn/20261027-dataset-repair/README.md)，不自动full或恢复TT-011。

## 历史合同

控制器读取在线转写、历史与Listen/Speak模式，预测keep/start/stop；无新增ASR文本使用`no-voice`，该文本路线不额外增加VAD或补偿。stop只用于用户打断，正常输出结束由运行时finish输入闭合。TT-001—003采用480ms观察窗，TT-010改为160ms、独立生成／播放时钟及完整轨迹逻辑组内平衡损失，最终预算与规则见修复配置。

FDB仅监控真实ASR与动作驱动的状态，不模拟助手正文、finish或计时复位；start切Speak、stop回Listen、keep维持。两周期各100条、退出码0且未知0，见[联合结果](../../../reports/textturn/20261025-fdb-action-only/README.md)。它与UltraChat模拟回答生命周期分别报告。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [VoxTurn重新调研](../VoxTurn/research_assessment.md) | 已核对现成权重、真实停顿训练、官方测试及音频接入边界；历史候选，尚未部署 |
| [数据修复配置讨论](dataset_repair_configuration.md) | 保留逐项讨论历史；最终合同以完整修复配置为准 |
| [数据修复完整配置（已确认）](dataset_repair_recommendation.md) | 六组配置及规模预算已确认；新版r5已实现并冻结，训练状态见运行记录 |
| [既有trace发布节奏](publication_trace_review.md) | 原生160ms解码中的连续更新、词内续写与空串，含本地交互查看器 |
| [小控制器可行性](controller_feasibility.md) | 短周期与长上下文、异步CoT、单一执行点、训练顺序及后备路线 |
| [当前数据管线审计](dataset_pipeline_review.md) | 当前完整轨迹版本的逐窗事实、构造问题、覆盖缺口及复现证据 |
| [训练与验收方案](training_plan.md) | 基模、旧 UltraChat 数据复用、训练方法、四类能力与延迟门槛 |


历史版本及失败保留原始证据，代码与中文实现说明同路径维护；现役播放器未替换，Layer 0/1/2和CoT未因文本控制训练完成接入。
