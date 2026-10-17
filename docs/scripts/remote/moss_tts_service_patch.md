# MOSS 服务实验入口

`moss_tts_service_patch.py` 显式加载固定服务适配器，包装其 `_load_upstream_module` 后调用原 `main`；不修改上游 checkout。固定来源为 MOSS `58b20a0`、服务 `b3306b9`，由现有 launcher 核验完整提交。

`apply_service_patch` 包装 command queue 的 put/get、start/push/finish、音色编码缓存、生成和 codec；以服务 session ID 作为组件实验的 request/response ID，记录实际门槛与 prefix 信息。`ObservedQueue` 记录排队，`trace_scope` 在 worker 处理命令时恢复关联。原始队列时序和 codec 生命周期保持不变。没有真实声卡消费数据，不能声称已测扬声器延迟。

实验开关 `XTALK_TTS_GENERATION_BATCH_FRAMES` 默认 0，保持原列表路径；候选 2/4/6。开启时仅在该服务加载的 Session 子类中使用惰性帧迭代器：每次先生成至多上限帧，再由原 decoder 消费，随后原 worker 自动继续余量。start、push、end_text 都沿原方法调用；finish 的原单帧 drain 保持不变。没有额外 worker 或播放队列。close 时标记取消，在批次生成前、交付前及 PCM 入队前丢弃未提交数据。尚待远端验证，不能作为默认配置。

`main` 记录文件摘要和实际环境开关；所有优化关闭时仍可独立开启 trace。当前尚未观测到 socket 发送与真实播放，需在报告中明确缺项。

worker 包装器在退出时清理仍打开的 codec streaming context；正常 finish 已关闭时不重复关闭，close/异常退出也不会遗留共享 codec 状态。取消与 PCM 入队由同一提交锁串行化；等待供音后重新检查取消。已经进入客户端播放缓冲的数据仍须由原播放所有者丢弃，服务补丁不能撤回已交付音频。

节点诊断可用 `XTALK_TTS_STACK_DIAGNOSTIC=1` 每 60 秒将 Python 栈写入服务日志，用于定位启动或推理停滞；它不属于正式性能测量，排障后关闭再跑基线。不打印请求内容或环境秘密。

`load_codec` 提供独立的启动排障开关 `XTALK_TTS_CODEC_LOAD_THREADS=1`（默认 0，沿用原线程数）。仅在 `_load_codec` 调用期间将 torch CPU 线程设为 1，成功或异常后都恢复原线程数；不改模型、采样、推理线程、codec streaming 状态或现役 conda。记录切换前后线程数和加载 span。原因是远端原 8 线程 codec 初始化在 `weight_norm` 的 OpenMP 并行区长期停滞，而同节点单线程加载约 2.1 秒完成；该处理只解决启动，不能计作首音优化收益。

## 稀疏文本启动候选

`prefill_options` 校验门槛（0/4/8/12）与最大等待（0 或正毫秒）。`update_prefill_deadline` 在原 worker 接受不足门槛的首批真实 token 后设置截止时间，后续 push 不延长；prefill/结束/取消时清除。`ObservedQueue.get` 在原 worker 空闲等待命令时以此截止时间作 timeout，超时产生内部 push 命令；已经排队的真实命令优先处理。

`partial_prefill` 在同一 worker 中以当前已有真实 token 做局部启动，临时降低 session 门槛后恢复，不设置 text-ended、不结束 codec 或清空 KV。内部命令复用原解码和音频入队路径，取消仍在提交边界检查。门槛和等待上限是独立变量，默认分别为沿用 processor 和关闭；现役行为不变。原 session 初始化处记录实际配置，push/timeout 记录待处理 token 和是否已结束。

服务子类在 `push_text_tokens` 记录实际独立 tokenize 的 token 数与 ID，便于核对稀疏片段没有丢失或提前使用未来文本。此 trace 为固定非 FDB 实验文本证据，仍不能替代对生成语音的转写和人工试听。

模型 prefill/step 成功后记录实际消费的文本 token，真实 finish 后记录 pending 余量。若小门槛导致提前音频 EOS，后续文本即使已接收也可能未消费；报告必须比对接收/消费顺序和剩余 token，不能只凭 WAV 非空判定通过。token 消费完整仍不能证明发音无漏词。

`service_patch_requested` 汇总 trace、批次、prefill、codec 加载和栈诊断开关供 launcher 判断，保证单独启用稀疏文本修复也能进入包装器；不依赖另一个实验开关作为隐式前置。

复用同一服务 session 开始新 turn 时，先清除前一轮 deadline；close 取消时同时清除，避免计时状态串到新一轮。取消标记与 PCM 提交锁的原检查仍保留。
