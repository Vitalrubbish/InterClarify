# SoulX＋SenseVoice 当前值前端

对应 `scripts/runtime/soulx_frontend.py`。`SoulXFrontend` 管理一个稳定逻辑话轮，复用官方SenseVoice、音频编码、门控、KV修正与五状态预测；每处理一个160ms音频块，将最新话轮全文与本块状态原子覆盖到SharedContext，不再发布版本化正文事件。Nemotron组合适配已撤下。

`instrument_methods()` 校验冻结`service/model.py`摘要后，用AST插入原始预测与状态回调，以及音频拼接／裁剪采样账本。模型、权重和共享上游目录不修改。附加状态仍逐项校验tokenizer与配置ID，FunASR1.2.6后处理字典与摘要保持冻结。

`_recognize()` 将同次音频转为float32，在后处理之前取得原始SenseVoice文字和标签，更新话轮正文整理器，再向官方推断路径返回其原有控制文字。`observe_asr()` 只推进前端当前草稿，不单独更新SharedContext；诊断通过可选`audit`回调输出到Context之外。

`observe_state()` 暂存本块原始／规则修正状态，执行远场与排空过滤。有效nonidle仍在此即时向匹配活动输出提交一次停止，不等待整段识别、下游LLM或正文写入；对同一output_id去重。

`_state_predict()` 在官方外层状态处理返回后组装并发布一帧。因此complete分支后续的整段识别及内部reset已执行，最新正文与触发本块的状态一同可读。状态携带预测时的controller generation，reset不会使complete被改成下一generation的空状态。未调用ASR的块沿用正文，仍更新状态。drain阶段仅诊断，不覆盖在线记录。

`_reset_controller()` 重置模型内部状态但保留未处理PCM及逻辑话轮正文。`feed_audio()` 使用单模型计算锁、16kHz单声道float32输入、800ms单包与4MiB PCM上限；采样账本检查真实音频无跳过、重复或倒退。`close_turn()` 拒绝与计算并发，保留最后联合观察并关闭；`detach()` 恢复官方方法，不留下旧采集钩子。

`on_commit(context)` 在开轮、每次在线帧覆盖和关闭后通知读者。调用方通过`context.get_user_turn(session_id, turn_id)`取得同组副本，不依赖事件游标。audit可记录原始识别、控制文字、状态、reset和发布前整帧；这些是外部检查信息，不进入在线历史正文。

限制：160ms是音频步长，不是墙钟延迟承诺；窗口拼合可能gap，状态语义仍需单独评测；没有接入Layer1／2、CoT或真实播放。直接停止回调故障应交由调用方处理，不代表物理停播已完成。
