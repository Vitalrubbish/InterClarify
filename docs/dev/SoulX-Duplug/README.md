# SoulX-Duplug 路线

更新：2026-10-29。用户确认以 **SoulX-Duplug＋SenseVoiceSmall 作为语音前端**，位于 Layer 0–Layer 2 输入侧。为先打通链路，首版沿用官方配套 ASR，后续再评估 Nemotron，见[选型说明](asr_adapter_assessment.md)。独立前端写入已实现并完成少量音频检查，尚未切换现役Agent。

## 已确认合同

- 前端包含 ASR 调用与文本整理、SoulX 音频编码及状态预测；同一活动话轮只用一个权威 ASR 来源。中间转写持续写入 Shared Context，不等待完成判断，前端内部与下游使用同一来源。2026-10-30 用户确认每个 160ms 音频处理步骤联合覆盖最新全文和本块状态，不保留历史正文版本，取消 320ms 周期建议；新合同尚未实现，读取与关闭规则见[接口设计](shared_context_interface.md)。
- 前端持续接收音频，可与下游表达、思考并发执行。Layer 0 仍负责系统附和时机；未来 CoT 从 Context 反馈至前端，当前不实现条件化扩展。
- SoulX 保留音频路径和原生五类用户状态，全部送入 Layer 1；普通正式回答在当前 turn 读取对应 `user_complete` 后生成，不额外发起独立回答调用。
- 活动输出期间有效 `user_nonidle` 额外直接触发停止，涵盖 preparing 和 playing；其他状态不进入输出运行时，不映射为 start 或 keep。完整路径见[架构第 2.2 节](../../research_design/architecture.md#22-前端状态与系统附和)。
- 后续联合音频 token、转写文本 token 与已发布 CoT token 的目标已确认，当前不实现。输入序列、缓存、触发、输出是否扩展及训练方式见[架构第 2.5 节](../../research_design/architecture.md#25-soulx-的-cot-条件化控制)。
- 保持单一仲裁执行点、单一 TTS 播放所有权和已听内容不可撤销；Layer 3 定位待统一。

## 验证设计与实施状态

2026-10-30按用户授权另完成[Nemotron＋SoulX独立适配](nemotron_integration.md)，复用单一Nemotron前缀来源、SoulX音频与五状态；四视图真实时钟探针通过结构和消费一致性检查，105次正文更新、124条状态，回调至正文可见P95约6.06ms，不额外等1秒。尚未切换首版或现役Agent，完成状态时机、完整词提交和EOF尾部仍有边界，见[实际报告](../../../reports/soulx/20261030-nemotron-integration/README.md)。

已按[ASR 前端设计](asr_frontend_design.md)实现原始文本与标签保全、滑窗修订、五状态及其文本依据、SharedContext事务与独立消费者。六视图实时回放中145次ASR与299条状态写入一致，两个消费者各读取912事件；2个非静音视图关闭时仍有gap，低音量原幅度识别明显较差，backchannel实际音频预测未覆盖。结果、失败修复及延迟见[实现与检查报告](../../../reports/soulx/20261029-shared-context/README.md)，不能据此宣称识别或五状态语义质量全面通过。

已登录贵州 HPC 确认并复用 TurnControlComparison 的两组模型、冻结源码和共用 conda；最初单卡组件加载检查见[部署说明](deployment.md)和[部署报告](../../../reports/soulx/20261029-frontend-deployment/README.md)。随后已提供独立Context实现及状态事件；Layer 1状态token编码、下游模型和真实播放仍待接入，不继承其他项目的 `speak` 动作映射。

此前[质量测试方案](quality_test.md)保留为 Nemotron 历史设计：全量回放英文 Easy Turn 集共 617 条，仅评价 Listen 影子观察与 Context 接口，不包含下游 LLM 或实际播放。首版 ASR 已调整，该方案不能直接执行；若后续复用数据集，须先冻结 SenseVoiceSmall 配置与窗口转写合同，执行另行确认。

首版已用实际只读消费者核对话轮快照、修订、重置历史和中间文字可读，仍需区分正文覆盖与接口搬运。Nemotron 的音频观察配对、词内增量和缓存适配留待后续。此前自建场景、额外开发集和200条抽样方案已撤回；TextTurn／XTurnix仅保留历史协议与证据，不继承其专属输入、动作token或训练门槛。

实施顺序及资源见[工程计划](../../engineering_implementation.md)，本轮输入与执行范围见[检查任务说明](frontend_audio_check.md)。实现及少量契约测试均有同路径中文说明；工作单仅按明确建单指令建立，本次没有新建issue或训练。
