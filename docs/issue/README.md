# 开发与测试工作单

更新：2026-10-22。这里只列当前工作与采用决定；研究范围以 [正式研究方案](../research_design.md) 为准，第一步安排见 [工程实施计划](../engineering_implementation.md)。

## 当前工作

当前先接入 X2-Turn 的 ASR 与用户状态，再用 FDB 对话音频验证。Layer 0 暂不实现或训练；系统 backchannel 保留在后续总计划。阶段修订见 [091](archive/091_x2_turn_and_system_backchannel_scope.md)，初始计划历史见 [083](archive/083_layer0_implementation_plan.md)。

| 工作单 | 状态 | 依赖与交付 |
| --- | --- | --- |
| [084：X2-Turn 前端协议与资产](084_layer0_candidates_and_contract.md) | 待执行 | 固定前端、独立开发验证及输入/状态时序；不依赖 Layer 0 |
| [085：X2-Turn 与仲裁接入](085_layer0_runtime_integration.md) | 待执行 | 依赖 084；转写/用户状态、LLM 调度与唯一执行路径 |
| [086：Layer 0 系统附和](086_layer0_training_fallback.md) | 后续保留，当前不执行 | 未来实现/训练附和时机并专项评测；不阻塞当前步骤 |
| [087：FDB 数据与评测入口](087_layer0_fdb_protocol.md) | 待执行 | 冻结 v1.0/v1.5，准备因果回放、正确分母及远端脚本 |
| [088：远端 FDB 验证](088_layer0_remote_fdb_validation.md) | 待执行 | 依赖 084、085、087；X2-Turn 基础话轮/实际播放测试，不依赖 086 |
| [089：远端旧路线资产清理](089_remote_asset_cleanup.md) | 已完成，2026-10-22 | 清理 xtalk 模型库、旧训练/选型环境、旧运行结果、缓存与旧 conda 环境；dry-run 与执行均完成，释放约 301G |

已完成单元直接归入 [归档索引](archive/README.md)。Layer 1/2 后续实现待本步骤结果后另行拆单。

[090：音频与其他 ASR 候选调研](archive/090_layer0_audio_and_asr_candidates.md)已完成，见 [调研记录](../layer0_candidates.md)。原生输出可直接驱动唯一仲裁器，候选尚未实测。

## 当前采用决定

| 内容 | 采用范围与依据 |
| --- | --- |
| 研究范围 | 模型自主发现任务信息缺口并判断继续倾听或主动澄清；system backchannel 保留在总计划，Layer 0 后续专项训练，当前不实现，见[研究方案](../research_design.md) |
| 首版 benchmark | 只评价决策合理性与澄清内容；不要求用户回答，不评价任务结果或实际交互成本，见[第5.6节](../research_design.md#56-首版-benchmark-的评测范围) |
| 专项数据与标注 | 试标 200 条逐条人工标注；训练 2k—5k、测试 300 条采用模型标注加人工抽检；标注思考启动位置与必须/可选/不得介入事件窗口，不设置参考问句，内容采用 LLM judge 并人工抽检，见[第5.7节](../research_design.md#57-数据规模时序标注与内容审核) |
| Layer 2 初期路线 | 冻结现成模型权重，以 system prompt 驱动持续判断和结构化输出，暂不专项训练；运行时记录真实观察、完成、返回与注入事件，见[第7节](../research_design.md#7-系统工程架构) |
| 异步训练参考 | 外部结果块屏蔽损失，后续动作与正文监督方案待定，见[第5.8节](../research_design.md#58-异步调用与结果利用的训练参考) |
| 思考调用方向 | Layer 1 在倾听或表达时均可通过独立 special token 请求异步思考；每会话最多一个请求在途，重复触发合并；结果写回 Layer 1 后经统一仲裁与单一播放路径表达，见[第7.2—7.4节](../research_design.md#72-思考请求与任务调度) |
| 组件与运行时 | Nemotron EN160 + Kokoro `af_heart`；300/1200ms 分段、600ms micro-turn、会话 KV 复用、`duplex_greedy_v1`；X-Talk `ca9b23c`，见[运行时配置](../runtime_baseline.md) |
| 工程第一步 | X2-Turn 提供 ASR/用户状态，经唯一仲裁器接入 LLM/TTS 并做 FDB；当前不实现 Layer 0。后续 Layer 0 只预测系统附和时机，见[工程计划](../engineering_implementation.md) |
| FDB 评测 | 保留冻结子集与完整两轴回放、官方词级对齐和 TOR/Latency 评分脚本；FDB 作为辅助工程与能力评测，不替代主动澄清 benchmark，结果见[reports/fdb](../../reports/README.md) |

## 共用约束

- 中文开发文档；英文文件名、实现注释与提交消息。实现修改同步同路径说明，先记录设计变更再改代码。
- 当前架构采用 Layer 0/1/2 职责分工，不设独立修订层；保持单一仲裁器与单一 TTS 播放所有权，已听内容不可撤销。
- 本地和远端使用 conda；真实模型与集群测试在远端调度执行，冻结源码、资产、输入及资源上限，独立 run_id，保留失败与退出码。
- 完整模型历史与生成 ID 保留；缓存改写、取消或淘汰时安全失效并重建。
- 未执行的官方评分、完整评测与人工复核继续如实标注；统计延迟时同时报告漏答与样本覆盖率。
- 大模型、音频与逐请求日志留本地或远端；Git 保留当前源码、简明报告、关键摘要与追溯哈希。
