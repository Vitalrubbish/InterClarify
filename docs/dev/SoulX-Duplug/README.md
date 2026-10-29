# SoulX-Duplug＋Nemotron 路线

2026-10-29 当前选型：用户决定采用 SoulX-Duplug 作为话轮控制器，并指令调研 Nemotron 低延迟适配，不可行时使用 SenseVoiceSmall。[调研结论](asr_adapter_assessment.md)支持优先采用 Nemotron EN160，SenseVoiceSmall 保留为适配失败或组合实测不达要求时的回退；低延迟收益仍需实测，尚未实现或切换运行时。

用户进一步确认：后续让 SoulX 联合读取音频 token、转写文本 token 和 Layer 2 已发布的 CoT token，保留 CoT 条件下的主动澄清与话轮决策目标，当前暂不实现。当前五类状态 token 全部送入 Layer 1，由 LLM 决定自身行为；普通正式回答在当前 turn 看到 `user_complete` 后开始生成，看到之前不生成正文。仅有效用户打断额外走直接停止路径，其他状态不进入输出运行时，也不转换为 start 或 keep，详见[架构第 2.2 节](../../research_design/architecture.md#22-前端状态与系统附和)。CoT 阶段是否扩展输出另行讨论，见[架构第 2.5 节](../../research_design/architecture.md#25-soulx-的-cot-条件化控制)。

Layer 3 定位待后续讨论。下方 617 条测试是此前方案，须重新确认后实施，不因本次选型自动启动。TextTurn 与 XTurnix 保留历史证据，不继承其专属输入、动作 token 或训练参数。

更新：2026-10-24。状态：用户已确认组合与简化测试范围；当前只更新方案，尚未实现适配、运行模型或训练。

Nemotron EN160 是唯一 ASR 来源，持续产生原始转写、增量和版本；SoulX-Duplug 读取同一用户音频及 Nemotron 的在线文本，保留原生五类用户状态。后续 Layer 1/2 读取同一份 Nemotron 转写，不另外运行 SenseVoice。选择这一组合的原因是保留现有英文识别能力，并避免两套转写在内容和修订上的分歧。

按用户补充要求，必须向下游 LLM 暴露每个用户 turn 的转写：同一 `turn_id` 下的在线文本更新先写入 Shared Context，提供最新快照与按游标读取更新的接口，不等控制器判 complete。字段、版本及关闭规则见[Shared Context 接口合同](shared_context_interface.md)。

## 当前测试

仅使用官方公开的英文 `Easy-Turn-Testset-en.zip`，计划全量回放 Complete 318 条、Incomplete 299 条，共 617 条。报告完成／未完成判断、原生判断与兜底接话差异，以及组合的实测延迟；同次回放验证 Shared Context 的转写写入、读取与可见耗时，不加载下游 LLM。具体协议见[质量测试计划](quality_test.md)。

此前自建 100 个交互场景、额外开发集和公开集 200 条抽样方案撤回。本轮不测试 Speak、用户附和、用户打断或真实播放，不以这个二分类数据集证明完整话轮控制能力。

## 实施边界

- Nemotron 替换官方外部 ASR 的适配尚未实现，不能声称已保持 SoulX-Duplug 原配套成绩或已验证更低延迟；音频截止点、文本实际到达、空增量、词内增量及缓存修订必须可追溯，具体见[适配调研](asr_adapter_assessment.md)。
- 当前保留原生五类状态 token，作为 Layer 1 输入；活动输出期间有效 `user_nonidle` 额外直接触发停止，其他状态不进入输出运行时，不设五状态动作映射表。
- 本次更新不启动远端作业、训练或现役切换，不新建未经明确指令的 issue；旧 XTurnix 实现和已取消作业不因选型变化而恢复。
- 后续将已发布 CoT 正文转为控制器输入 token，与音频和转写共同决策；当前不新增专用 token、注入接口或训练，序列和边界编码后续确定，不将基础测试通过等同于 CoT 能力成立。
- 继续保持[研究方案](../../research_design.md)中的层级职责、单一仲裁执行点、单一 TTS 播放所有权和已听内容不可撤销的边界。

后续按明确指令建立工作单，完成适配协议、资产预检、少量冒烟、公开集回放与中文报告。实施代码、配置和少量契约测试分别维护 `docs` 下同路径说明，本次不创建实现空壳。
