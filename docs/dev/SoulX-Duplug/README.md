# SoulX-Duplug 路线

更新：2026-10-29。当前话轮控制器选用 **SoulX-Duplug**；[适配调研](asr_adapter_assessment.md)支持优先使用 Nemotron EN160，适配失败或组合实测不满足后续确认要求时回退 SenseVoiceSmall。新组合尚未实现或切换运行时，延迟收益仍需实测。

## 已确认合同

- 同一活动话轮使用一个权威 ASR 来源，持续转写先写 Shared Context；控制器和后续 Layer 1/2 读取同一来源。快照、游标和关闭规则见[接口设计](shared_context_interface.md)。
- SoulX 保留音频路径和原生五类用户状态，全部送入 Layer 1；普通正式回答在当前 turn 读取对应 `user_complete` 后生成，不额外发起独立回答调用。
- 活动输出期间有效 `user_nonidle` 额外直接触发停止，涵盖 preparing 和 playing；其他状态不进入输出运行时，不映射为 start 或 keep。完整路径见[架构第 2.2 节](../../research_design/architecture.md#22-前端状态与系统附和)。
- 后续联合音频 token、转写文本 token 与已发布 CoT token 的目标已确认，当前不实现。输入序列、缓存、触发、输出是否扩展及训练方式见[架构第 2.5 节](../../research_design/architecture.md#25-soulx-的-cot-条件化控制)。
- 保持单一仲裁执行点、单一 TTS 播放所有权和已听内容不可撤销；Layer 3 定位待统一。

## 验证设计与实施状态

此前[质量测试方案](quality_test.md)计划全量回放英文 Easy Turn 集：Complete 318 条、Incomplete 299 条，共 617 条。仅在 Listen 影子模式评价完整性判断、原生／兜底分支及实测延迟，同次核查 Context 写入与只读消费者读取；不加载下游 LLM，不评价用户附和、打断或实际播放。执行仍待重新确认。

音频观察边界、文本版本、词内增量、单次消费和缓存修订是适配的关键缺口，不能只替换模型名称。此前自建场景、额外开发集和 200 条抽样方案已撤回；TextTurn／XTurnix 仅保留历史协议与证据，不继承其专属输入、动作 token 或训练门槛。

实施顺序及资源见[工程计划](../../engineering_implementation.md)。后续按明确指令建立工作单，代码、配置及少量契约测试同步维护同路径中文说明；本次文档整理不启动远端作业或训练。
