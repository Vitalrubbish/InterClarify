# 工作单管理

更新：2026-11-05。当前前端路线为 **SoulX-Duplug 官方配置＋并行 X2Streaming-ASR**。第一阶段 ASR-Frontend 已收口；Layer 1 首轮从官方 Qwen2.5-7B-Instruct 开始协议适配，Qwen3 为后续候选，接入与训练尚未实施。

## 当前工作单

当前无活动工作单。NTF-049 已完成[训练数据构造、配比与分阶段时长方案](../dev/layer1_training/README.md)并归档：提出七类数据、10 万条决策样本及四阶段训练预算，吞吐待远端校准。当前[训练设计](../research_design/layer1_training.md)首轮采用 Qwen2.5-7B-Instruct，Qwen3 保留为后续候选；依次训练协议、含噪状态与取消恢复、附和及 thinking。此前 NTF-037、040—048 的分析与设计单均已归档，未启动语料生成、下游接入或训练。NTF-039 已完成前端文档与接口收口；NTF-038 的 [SoulX 原生 complete 行为审计](../reports/soulx/20261104-completion-strategy-audit/README.md)与 NTF-019 前端验收保持。

## 当前路线交付

| 工作单 | 状态 | 交付 |
| --- | --- | --- |
| [NTF-015／016](../reports/soulx/20261102-native-independent-frontend/README.md) | 已完成并归档 | 原生控制封装、冻结加载器、同源 PCM、160ms 屏障和独立 X2 适配 |
| [NTF-017](../reports/soulx/20261102-ntf017-joint-publication/README.md) | 已完成并归档 | 文本／状态／进度联合提交，移除前端停止旁路 |
| [NTF-018](../reports/soulx/20261103-ntf018-warmup/README.md) | 已完成并归档 | 完整预热、真实权重对照和并发三轴 3/3 |
| [NTF-019](../reports/soulx/20261103-ntf019-fdb30/README.md) | 已完成并归档 | 固定 FDB30 验收，用户审核通过 |
| [NTF-026](archive/NTF-026.md) | 已完成并归档 | 采集监控的进程退出竞态修复 |
| [NTF-027](archive/NTF-027.md) | 已完成并归档 | 恢复原生控制与外接 X2 工作单 |
| [NTF-028](archive/NTF-028.md) | 已完成并归档 | 160ms 音频步推进屏障合同 |
| [NTF-029](archive/NTF-029.md) | 已完成并归档 | 160ms 双路完成后的联合发布合同 |
| [NTF-030](../reports/soulx/20261103-latency-limit-removal/README.md) | 已完成并归档 | 取消 800ms 时长停止条件，保留容量与资源保护 |
| [NTF-037](../research_design/layer1_training.md) | 研究已完成并归档 | Layer 0 并入 Layer 1 的职责同步、含噪控制与取消恢复数据、规模预算及控制方案比较；尚未实施训练 |
| [NTF-038](../reports/soulx/20261104-completion-strategy-audit/README.md) | 审计已完成并归档 | 区分当前原始预测与官方规则来源；复核 3180 批次，未改推理或追加 GPU 实验 |
| NTF-039 | 已完成并归档 | 当前前端文档、快照接口与图稿一致；135 项本地检查通过 |
| [NTF-040](../dev/SoulX-Duplug/completion_runtime_analysis.md) | 分析已完成并归档 | 真实案例、官方取消与上下文整理、七组 CPU 行为核查及当前设计影响；未接入运行时 |
| [NTF-041](../dev/SoulX-Duplug/completion_runtime_analysis.md#2-提前-complete-的具体例子) | 复核已完成并归档 | 两组无新增文字状态序列、首音前取消与上下文合并实例；明确规则前字段缺失 |
| NTF-042 | 已完成并归档 | 第二节采用 TurnControlComparison 实际日志案例，时间线与引用同步 |
| NTF-043 | 已完成并归档 | 区分自写与官方运行时，澄清官方消息整理、请求重建和 KV 边界 |
| [NTF-044](../research_design/layer1_training.md) | 文档已完成并归档 | 明确运行时基线与 7B 微调关系、窗口建议、取消恢复和 8×4090 预算；未实施接入或训练 |
| [NTF-045](../research_design/layer1_training.md) | 文档已完成并归档 | 取消两条路线；其中未微调基线的能力假设已由 NTF-046 修正，未实施接入或训练 |
| [NTF-046](../research_design/layer1_training.md) | 文档已完成并归档 | 修正既有协议与新 token 适配的能力假设；新增词表须覆盖相关参数训练，路线范围以后续 NTF-047 为准 |
| [NTF-047](../research_design/layer1_training.md) | 文档已完成并归档 | 删除路线 A，仅保留协议适配后的 7B Layer 1 训练主线及其内部检查点比较与消融 |
| [NTF-048](../research_design/layer1_training.md) | 文档已完成并归档 | 将训练起点改为 Qwen2.5-7B-Instruct 或选定 Qwen3，取消旧 checkpoint／adapter 依赖，更新模式与资源预检要求 |
| [NTF-049](../dev/layer1_training/README.md) | 文档已完成并归档 | 训练数据构造、七类占比、四阶段样本分配与 8×4090 假设下的时长；未生成语料或启动训练 |

## 后续计划

NTF-031—035 为后续 LLM／Layer 1／输出运行时计划，尚未实施并归档；用户明确暂不推进接入，不记为完成成果。相关内容见本地 `docs/issue/archive/`。

## 管理约定

工作单仅按用户明确指令建立；交付满足验收后立即归档并同步索引。真实模型训练和集群测试使用远端 conda 调度作业，资源限制按相应工作单与已确认修订执行；实现同步维护 `docs` 下同路径中文说明。

`docs/issue/archive/` 不纳入 Git，保留当前路线已完成工作单。
