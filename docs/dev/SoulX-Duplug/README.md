# SoulX-Duplug 路线

更新：2026-10-29。用户确认以 **SoulX-Duplug＋SenseVoiceSmall 作为语音前端**，位于 Layer 0–Layer 2 输入侧。为先打通链路，首版沿用官方配套 ASR，后续再评估 Nemotron，见[选型说明](asr_adapter_assessment.md)。新组合尚未实现或切换运行时，延迟收益仍需实测。

## 已确认合同

- 前端包含 ASR 调用与文本整理、SoulX 音频编码及状态预测；同一活动话轮只用一个权威 ASR 来源。中间转写持续写入 Shared Context，不等待完成判断，前端内部与下游使用同一来源。快照、游标和关闭规则见[接口设计](shared_context_interface.md)。
- 前端持续接收音频，可与下游表达、思考并发执行。Layer 0 仍负责系统附和时机；未来 CoT 从 Context 反馈至前端，当前不实现条件化扩展。
- SoulX 保留音频路径和原生五类用户状态，全部送入 Layer 1；普通正式回答在当前 turn 读取对应 `user_complete` 后生成，不额外发起独立回答调用。
- 活动输出期间有效 `user_nonidle` 额外直接触发停止，涵盖 preparing 和 playing；其他状态不进入输出运行时，不映射为 start 或 keep。完整路径见[架构第 2.2 节](../../research_design/architecture.md#22-前端状态与系统附和)。
- 后续联合音频 token、转写文本 token 与已发布 CoT token 的目标已确认，当前不实现。输入序列、缓存、触发、输出是否扩展及训练方式见[架构第 2.5 节](../../research_design/architecture.md#25-soulx-的-cot-条件化控制)。
- 保持单一仲裁执行点、单一 TTS 播放所有权和已听内容不可撤销；Layer 3 定位待统一。

## 验证设计与实施状态

已登录贵州 HPC 确认并复用 TurnControlComparison 的两组模型、冻结源码和共用 conda；ParaThink 独立单卡检查已完成，SoulX 加载／静音前向与 SenseVoice 英文识别通过，退出码 0，见[部署说明](deployment.md)和[实际报告](../../../reports/soulx/20261029-frontend-deployment/README.md)。Context、状态输入和播放仍待接入，不继承其他项目的 `speak` 动作映射。

此前[质量测试方案](quality_test.md)保留为 Nemotron 历史设计：全量回放英文 Easy Turn 集共 617 条，仅评价 Listen 影子观察与 Context 接口，不包含下游 LLM 或实际播放。首版 ASR 已调整，该方案不能直接执行；若后续复用数据集，须先冻结 SenseVoiceSmall 配置与窗口转写合同，执行另行确认。

首版需验证窗口转写到话轮快照的映射、文本修订、控制器重置后的历史保留，以及中间文字能否及时送达 Layer 1/2。Nemotron 的音频观察配对、词内增量和缓存适配留待后续。此前自建场景、额外开发集和 200 条抽样方案已撤回；TextTurn／XTurnix 仅保留历史协议与证据，不继承其专属输入、动作 token 或训练门槛。

实施顺序及资源见[工程计划](../../engineering_implementation.md)。后续按明确指令建立工作单，代码、配置及少量契约测试同步维护同路径中文说明；本次文档整理不启动远端作业或训练。
