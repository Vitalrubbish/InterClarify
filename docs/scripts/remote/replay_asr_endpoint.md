# replay_asr_endpoint.py

将五配置真实 ASR 到达轨迹按墙钟重放到现有 X-Talk `MicroTurnAssembler` 和 `DuplexRuntimeAdapter`，加载固定官方 DuplexCascade 权重。没有 TTS 或播放设备，不引入新的产品运行时。`OfficialBridge` 复用现有 `OfficialDuplexModel.stream` 并保留原始 assistant token IDs，绕过 HTTP 的影响单独说明。

`replay_one` 让 ASR 到达和单一 600ms 控制时钟独立运行，首非空文本之后启动第一拍；推理忙时不积压旧快照。ASR 全部作为 partial 发布，不把真实 EOF、人工边界或静音尾长告诉模型。通过实际运行时的 `LLMAgentResponseUpdate` 记录每个新 response_id 的首正文，通过停播事件标记被取消。边界前已生成、边界后继续的旧正文单列；finish token 而无正文不算回复。

原样与去句读标点条件分别建立自己的模型历史，保持时间及其他文本不变。观察截止为标注区间结束后 12s，2/5/12s 覆盖率是描述指标，不是预设淘汰阈值。未回复保持 null 和分母。该实验测文本回复行为，不证明声音、回答相关性或完整 FDB 通过。

`run` 保存权重信息、服务源码和 X-Talk 关键模块摘要，并在结束时复查，以识别运行期间的源码漂移。每条轨迹保存原始控制和正文事件、微轮 prompt 轨迹及历史；汇总保留错误与取消。

`replay_one` 的观察长度可在本地契约测试中缩短；真实任务入口固定 12s。集成测试复用真实 X-Talk 类和假模型输出，检查首拍输入只能包含该拍之前到达的文本。
