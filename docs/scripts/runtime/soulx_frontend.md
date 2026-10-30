# SoulX＋SenseVoice 当前值前端

对应 `scripts/runtime/soulx_frontend.py`。`SoulXFrontend` 管理一个稳定逻辑话轮，复用官方SenseVoice、音频编码、门控、KV修正与五状态预测；每处理一个160ms音频块，将最新话轮全文与本块状态原子覆盖到SharedContext，不再发布版本化正文事件。Nemotron组合适配已撤下。

`instrument_methods()` 校验冻结`service/model.py`摘要后，用AST插入原始预测与状态回调，以及音频拼接／裁剪采样账本。模型、权重和共享上游目录不修改。附加状态仍逐项校验tokenizer与配置ID，FunASR1.2.6后处理字典与摘要保持冻结。

`_recognize()`将同次音频转为float32，在后处理之前采集原始SenseVoice文字和标签，再向官方推断路径返回原有控制文字。`observe_asr()`将窗口结果保留为诊断；complete或等待兜底的整段结果则覆盖所属controller片段的草稿，失败或空返回不清空正文。它不单独更新SharedContext。

`observe_control()`在原生`_asr()`返回后读取当前增量历史列表，由整理器重建草稿，同步上一周期替换和删除；不只追加对外delta，不重新对齐原始窗口。草稿采用规范化控制文字，整段结果恢复分离标签后的原文。控制诊断记录本次整理结果，原始窗口、控制文字与最终正文分别可核查。

`observe_state()` 暂存本块原始／规则修正状态，执行远场与排空过滤。有效nonidle仍在此即时向匹配活动输出提交一次停止，不等待整段识别、下游LLM或正文写入；对同一output_id去重。

`_state_predict()` 在官方外层状态处理返回后组装并发布一帧。因此complete分支后续的整段识别及内部reset已执行，最新正文与触发本块的状态一同可读。状态携带预测时的controller generation，reset不会使complete被改成下一generation的空状态。未调用ASR的块沿用正文，仍更新状态。drain阶段仅诊断，不覆盖在线记录。

`_reset_controller()`重置模型内部状态，保留未处理PCM和逻辑话轮正文，并将当前片段保留为前文；下一generation的整段结果只覆盖新草稿。drain阶段不推进在线正文整理器。`feed_audio()`使用单模型计算锁、16kHz单声道float32输入、800ms单包与4MiB PCM上限；采样账本检查真实音频无跳过、重复或倒退。`close_turn()`拒绝与计算并发，保留最后联合观察并关闭；`detach()`恢复官方方法。

`on_commit(context)` 在开轮、每次在线帧覆盖和关闭后通知读者。调用方通过`context.get_user_turn(session_id, turn_id)`取得同组副本，不依赖事件游标。audit可记录原始识别、控制文字、状态、reset和发布前整帧；这些是外部检查信息，不进入在线历史正文。

限制：160ms是音频步长，不是墙钟延迟承诺；原生增量仍可能误识别，controller累计缓冲不一定覆盖全部用户发声；状态语义需单独评测，没有接入Layer1／2、CoT或真实播放。本次未新增ASR调用或有界补识别；旧窗口拼合的远端结果不作为新策略的GPU验证。直接停止回调不代表物理停播已完成。
