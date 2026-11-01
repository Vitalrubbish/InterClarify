# SoulX＋SenseVoice 当前值前端

对应 `scripts/runtime/soulx_frontend.py`。`SoulXFrontend` 管理一个稳定逻辑话轮，复用官方SenseVoice、音频编码、门控、KV修正与五状态预测。默认每160ms联合发布SenseVoice正文和状态；NTF-005增加可选的`frame_sink`和独立`publication_source`，由双ASR组合器接收冻结状态，配对Nemotron正文后发布，SenseVoice控制输入保持原生。

`instrument_methods()` 校验冻结`service/model.py`摘要后，用AST插入原始预测与状态回调，以及音频拼接／裁剪采样账本。模型、权重和共享上游目录不修改。附加状态仍逐项校验tokenizer与配置ID，FunASR1.2.6后处理字典与摘要保持冻结。

`_recognize()` 将同次音频转为float32，在后处理之前取得原始SenseVoice文字和标签，更新话轮正文整理器，再向官方推断路径返回其原有控制文字。`observe_asr()` 只推进前端当前草稿，不单独更新SharedContext；诊断通过可选`audit`回调输出到Context之外。

`observe_state()` 暂存本块原始／规则修正状态，执行远场与排空过滤。原生`user_complete`若官方`speech_detected`仍为假，则以`no_speech`拒绝，不产生完成信号；该快照随帧保存。有效nonidle仍在此即时向匹配活动输出提交一次停止，不等待整段识别、下游LLM或正文写入；对同一output_id去重。

`_state_predict()` 在官方外层状态处理返回后组装并发布一帧。外层返回的服务状态与整段识别文字写入`service_state`、`service_text`；`service_completion_source`区分`model_complete`与`wait_fallback`，原生`state_token`与`state_accepted`保持模型语义，不把`speak`反写成`user_complete`。因此complete分支后续的整段识别及内部reset已执行，最新正文与触发本块的状态一同可读。状态携带预测时的controller generation，reset不会使complete被改成下一generation的空状态。未调用ASR的块沿用正文，仍更新状态。drain阶段仅诊断，不覆盖在线记录。服务结果另以`service_source`审计事件写出，诊断文字不覆盖正文。

`_reset_controller()` 重置模型内部状态但保留未处理PCM及逻辑话轮正文。`feed_audio()` 使用单模型计算锁、16kHz单声道float32输入、800ms单包与4MiB PCM上限；采样账本检查真实音频无跳过、重复或倒退。`close_turn()` 拒绝与计算并发，保留最后联合观察并关闭；`detach()` 恢复官方方法，不留下旧采集钩子。

2026-11-01差异核查：`_reset_controller()`实际保留的是整个`model.buffer`，包含回看与未处理采样，覆盖了官方reset刚建立的初始padding；这是此前单路适配器已有的音频连续性选择，不应描述为完整原生reset等价。该差异可能改变reset后的音频编码输入，因果贡献尚未经单项对照；本次仅修订说明，未修改模型或buffer实现。

`on_commit(context)` 在开轮、每次在线帧覆盖和关闭后通知读者。调用方通过`context.get_user_turn(session_id, turn_id)`取得同组副本，不依赖事件游标。audit可记录原始识别、控制文字、状态、reset和发布前整帧；这些是外部检查信息，不进入在线历史正文。

配对模式在官方整步返回后记录`controller_completed_at`、本步控制文字、实际主块/回看/前瞻采样账本及本步ASR调用。`state_resolved_at`仍为原始状态产生时刻，complete后的整段SenseVoice识别和官方reset耗时不会被隐去。`frame_sink`只入队，不等待Nemotron或Context；`observe_state()`中的有效nonidle停止回调仍即时执行。`pcm_metrics()`分别返回保留PCM字节与尚未成为主块的真实采样，不将历史回看当作未读积压。

`control_text`和`delta_text`在原始状态钩子中冻结，因此关门步骤也能显示当时已有控制正文，complete后的reset不会清空审计；`gate_open`由本步是否实际调用SenseVoice滑窗识别确定（官方每步调用`_asr()`，关门时不识别）。

限制：160ms是音频步长，不是墙钟延迟承诺；窗口拼合可能gap，状态语义仍需单独评测；没有接入Layer1／2、CoT或真实播放。直接停止回调故障应交由调用方处理，不代表物理停播已完成。
