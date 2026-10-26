# TextTurn：文本话轮控制器路线

2026-10-27：[数据修复完整配置](dataset_repair_recommendation.md)已获用户整体确认，含train／pilot窗口上限100000／10000。按用户最新指令，本轮仅更新文档到已确认，生成器、正式JSON、冻结数据及训练均未改动或启动。TT-010仍保持打开，不能将配置确认写成实现完成。

2026-10-26：按用户要求整理[小控制器可行性与低延迟接入](controller_feasibility.md)，并完成[当前训练数据管线审计](dataset_pipeline_review.md)。新确认预设分支ID进入模型输入、8个打断模板仅5个可达，以及句式与历史位置绑定；数据修复和CoT适配仍未实施。本次沿用TT-010，仅交付文档及本地只读证据，不新增issue或启动训练。当前默认控制窗为160ms，以下480ms为旧合同记录。

更新：2026-10-25。状态：用户已指令启动 TT-001，已构建来源可追溯的首批数据检查样例；TT-001正式文本数据已冻结归档，训练与远端测试均已运行结束，语音原始未通过且v2评分已修复、接话语义标注覆盖不足。TextTurn 是本项目路线名称，不是已有模型或研究成果。

用户已明确要求按训练方案提出工作单，现建立 [TT-001—004](../../issue/TextTurn/README.md)：数据 → 模型 → 在线接入 → 四类验收。TT-001已归档，正式冻结160/200/300来源，见[数据冻结报告](../../../reports/textturn/20261025-tt-001-freeze/README.md)；TT-002训练及TT-003接口已归档；TT-004评估及v2离线重评已运行，整体证据不足，缺接话语义标注，见[结果核查](../../../reports/textturn/20261025-tt-004-results/README.md)。必要检查直接随工作交付，不单独设置确认项目。

采用 **Nemotron EN160＋Qwen3-0.6B 专项微调控制器**：Nemotron 是唯一 ASR 来源，转写按用户 turn 持续写入 Shared Context；控制器读取文本、历史和 Listen/Speak 状态，输出 keep/start/stop。第一阶段训练普通接话、用户打断、用户附和和停顿处理；第二阶段待 Layer 2 可用后加入 CoT。

stop只用于用户打断，正常说完由播放完成事件处理。按用户2026-10-25修订，控制观察窗为480ms，聚合三个Nemotron EN160解码步骤；转写仍每次及时写入Context。User非空窗随机1—2 token，Assistant每窗8 token模拟生成；生成完成后的Speak尾窗与播放完成后的Listen等待分开。质量门槛不变，聚合等待单列并纳入及时性判断。

**按用户确认，无新增 ASR 文本直接作为带延迟的静音信号，保留 `no-voice`，不增加 VAD、不做静音延迟补偿。**

| 文档 | 内容 |
| --- | --- |
| [数据修复配置讨论](dataset_repair_configuration.md) | 逐项记录用户选择、继承合同及待定配置，全部对齐后实施 |
| [数据修复完整配置（已确认）](dataset_repair_recommendation.md) | 六组配置及规模预算已整体确认，尚未实施 |
| [既有trace发布节奏](publication_trace_review.md) | 原生160ms解码中的连续更新、词内续写与空串，含本地交互查看器 |
| [小控制器可行性](controller_feasibility.md) | 短周期与长上下文、异步CoT、单一执行点、训练顺序及后备路线 |
| [当前数据管线审计](dataset_pipeline_review.md) | 当前完整轨迹版本的逐窗事实、构造问题、覆盖缺口及复现证据 |
| [训练与验收方案](training_plan.md) | 基模、旧 UltraChat 数据复用、训练方法、四类能力与延迟门槛 |

本路线替代 SoulX-Duplug 作为当前开发主线；旧 [SoulX 方案](../SoulX-Duplug/README.md)保留作候选记录，不继续启动其适配或测试。选型原因是文本输入更贴近后续 ASR＋CoT 合同，减少音频／文本交错适配工作；不预先宣称训练效果优于现成控制器。

首批数据检查复用已有 conda，仅使用 CPU；未启动 GPU。后续实现仍保持 Layer 0/1/2 的既有分工、唯一输出仲裁执行点和单一 TTS 播放所有权；已听内容不可撤销。实现文件同步维护 `docs` 下对应路径中文说明。

本轮已完成[训练数据构造与配比审核](data_review.md)，需先修语义对照及覆盖再改采样；现有冻结集和模型未改动。

按用户要求新增[FDB两臂各50条跨数据集测试计划](fdb_cross_dataset_plan.md)，并按最新指令拆为[TT-005接话覆盖与延迟](../../issue/archive/TextTurn/tt_005_fdb_turn_taking.md)及[TT-006停顿介入率与归因](../../issue/archive/TextTurn/tt_006_fdb_pause_handling.md)。两项直接交付能力结果，必要工程工作并入测试，共用一次远端串行作业和原有预算；已实现共用入口并冻结50＋50，已完成480ms与160ms远端执行及核查；运行记录见[联合报告](../../../reports/textturn/20261025-fdb-action-only/README.md)。使用现有候选补充接话／停顿外部诊断，历史使用、标注规则和语义策略差异分别披露，不替代完整四类验收。

用户进一步明确FDB只监控TextTurn。当前480ms与新增TT-007的160ms均采用仅由start／stop／keep驱动的状态，不模拟助手正文或生成／播放；旧运行撤回，修正后的480ms与160ms均已100/100、退出码0、未知0，TT-005／006／007已归档，原累计预算未超限。
