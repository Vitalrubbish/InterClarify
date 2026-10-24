# SoulX-Duplug＋Nemotron 路线

2026-10-24 最新状态：用户已选择启动 [TextTurn 文本控制器路线](../TextTurn/README.md)，本路线转为保留候选，不继续启动适配、617 条回放或训练。以下是此前方案；Shared Context 的按 turn 转写与读取原则由新路线继承，音频同步约定不作为新路线前置。

更新：2026-10-24。状态：用户已确认组合与简化测试范围；当前只更新方案，尚未实现适配、运行模型或训练。

Nemotron EN160 是唯一 ASR 来源，持续产生原始转写、增量和版本；SoulX-Duplug 读取同一用户音频及 Nemotron 的在线文本，保留原生五类用户状态。后续 Layer 1/2 读取同一份 Nemotron 转写，不另外运行 SenseVoice。选择这一组合的原因是保留现有英文识别能力，并避免两套转写在内容和修订上的分歧。

按用户补充要求，必须向下游 LLM 暴露每个用户 turn 的转写：同一 `turn_id` 下的在线文本更新先写入 Shared Context，提供最新快照与按游标读取更新的接口，不等控制器判 complete。字段、版本及关闭规则见[Shared Context 接口合同](shared_context_interface.md)。

## 当前测试

仅使用官方公开的英文 `Easy-Turn-Testset-en.zip`，计划全量回放 Complete 318 条、Incomplete 299 条，共 617 条。报告完成／未完成判断、原生判断与兜底接话差异，以及组合的实测延迟；同次回放验证 Shared Context 的转写写入、读取与可见耗时，不加载下游 LLM。具体协议见[质量测试计划](quality_test.md)。

此前自建 100 个交互场景、额外开发集和公开集 200 条抽样方案撤回。本轮不测试 Speak、用户附和、用户打断或真实播放，不以这个二分类数据集证明完整话轮控制能力。

## 实施边界

- Nemotron 替换官方外部 ASR 的适配尚未实现，不能声称已保持 SoulX-Duplug 原配套成绩；音频截止点、文本实际到达、空增量及缓存修订必须可追溯。
- 第一阶段保留 `user_idle`、`user_nonidle`、`user_backchannel`、`user_complete`、`user_incomplete`，不强制改成 start/keep/stop。
- 本次更新不启动远端作业、训练或现役切换，不新建未经明确指令的 issue；旧 XTurnix 实现和已取消作业不因选型变化而恢复。
- 后续 CoT 仍保持文本形式，待 Layer 2 与相应输入、训练合同建立后验证；不将基础测试通过等同于 CoT 能力成立。
- 继续保持[研究方案](../../research_design.md)中的层级职责、单一仲裁执行点、单一 TTS 播放所有权和已听内容不可撤销的边界。

后续按明确指令建立工作单，完成适配协议、资产预检、少量冒烟、公开集回放与中文报告。实施代码、配置和少量契约测试分别维护 `docs` 下同路径说明，本次不创建实现空壳。
