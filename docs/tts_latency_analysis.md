# TTS 首音延迟分析与优化顺序

日期：2026-10-17。依据 `prompt.md`，目标为整体平均响应约 1 秒、避免超过 1.5 秒，简单问题达到亚秒级。本文最初用于分析方案；当前实验工具和默认关闭的批次/开头编译路径已准备，进展见 [远端任务单](tts_latency_remote_tasks.md)。尚未启动集群实验或更换模型。研究范围和动作边界沿用 [研究设计](research_design.md) 与 [工程方案](engineering_implementation.md)。

## 1. 结论

优先优化当前 MOSS 服务的首帧交付和每轮开头的推理路径，同时把 CosyVoice 作为替换对照。现有证据不能证明 MOSS 模型本身存在约 0.7 秒的最低延迟，也不能保证换模型后整体低于 1 秒。

两个直接来自固定源码的线索值得优先验证：

1. 服务先调用 `push_text_tokens()` 生成整批帧，再解码并发送；已生成的首帧可能被同批后续帧阻塞。
2. 本地编译补丁每轮清空历史，在重复惩罚窗口填满前使用 eager；长句稳态加速不等于短句和首音加速。

## 2. 已有测量能说明什么

历史 20261015T060611Z 小子集的分解见 [FDB 延迟诊断](fdb_latency_diagnosis.md)：

| 阶段 | 顺畅接话平均 | 用户插话后新回答平均 |
| --- | ---: | ---: |
| TTSStarted → 首 PCM | 0.732s | 0.738s |
| 首 PCM → 对齐首词 | 0.455s | 0.477s |
| 全链路 → 对齐首词 | 2.558s | 2.848s |

这是旧 ASR 链路、4 条有效接话和 5 条插话回答的历史结果，不代表当前主线总体分布。后续 `reports/duplex_acceptance/20261016T044445Z/latency_review.json` 中唯一明确启动插话后新回答的样本 101，TTS 启动到首包仍为约 1.012s，说明实际首包会随运行条件变化，不能只使用 0.73s。

首 PCM 可以包含静音，首词对齐又受对齐器影响。不能把后一段约 0.46s 全部判定为音频前导静音，也不能在没有试听和能量检查时直接裁掉。

现有吞吐优化已经完成：4090 每帧 75.0ms → 35.0ms，默认 local SDPA + inductor，采样保持官方设置，见 [A4 任务单 §9.6.7](xtalk_a4_remote_acceptance.md)。项目旧指标 `rtf=2.25` 表示音频秒数/计算秒数，约 2.25 倍实时；常见论文的 RTF 则取其倒数，约 0.44，比较时必须统一。

## 3. 固定源码审计

审计配置锁定的 MOSS 源码 `58b20a0d5fcc6766658d50967a90a9d890009a46`、服务适配器 `b3306b97f8a64c1a2f25b9803c070ff32ecff6b1`，以及本仓库当前补丁。未核验远端实际加载文件是否与这些版本完全一致，因此以下属于可复核的代码路径分析，尚非新实验的因果结论。

### 3.1 先整批生成、后交付可能拖住首帧

固定版 `fast_api.py` 的 `SessionManager._handle_push_text()` 先将传入文本编码成 token，再调用 `tts_session.push_text_tokens(tokens)`，最后才调用 `frame_decoder.decode_frames(audio_frames)`。

`MossTTSRealtimeStreamingSession._drain_pending_tokens()` 返回的是列表：先执行 prefill，再逐个消费当前全部待处理文本 token，调用 `inferencer.step()`，最后一起返回音频帧。即使 prefill 已经生成首帧，也必须等该次调用剩余步骤结束后才进入 codec 和输出队列。开始时自带文本的路径也使用这种调用顺序。

由此推断：**单次推入的文本块越大，首帧在服务内部等待的风险越高。** 用现有稳态每帧约 35ms 举例，若首帧后还有 10 个 step，就可能额外等待约 350ms；这只是数量级示意，开头的真实耗时需单独测量。

2026-10-17 根据用户反馈修正方案：保留批量生成和交付，优先适当降低每批帧数，不以逐帧发送为默认目标。将一次文本推送对应的无界生成列表改为按音频帧数限制的小批次，在批次间解码和入队；模型条件、采样顺序和每轮 codec 流状态保持连续。小批次可能增加解码、传输和调度开销，也可能引起供音不足，因此选择须同时依据首音、断流和自然度。改造覆盖 start、push、finish 三条路径，避免重复帧、漏帧和取消后旧音频入队。具体实验和验收见 [TTS 优化 issues](issues/tts_001_latency_instrumentation.md)。

不能仅把客户端文本拆成单个字符：服务对每个 push 独立 tokenize，随意拆分会改变 token 序列，英语词片段尤其需要检查。优先修服务内部交付粒度，再优化有明确边界的文本输入。

### 3.2 每个回答开头仍然缺少编译加速

`scripts/remote/moss_tts_patch.py` 的 `patched_prefill()` 在调用原 prefill 前把 `_xt_history` 清空。`patched_generate_local_transformer()` 要求历史非空；若重复惩罚生效，还要求 `_xt_history_filled >= min(capacity, repetition_window)`。

默认重复惩罚窗口为 50，MOSS 帧率为 12.5Hz。因此历史填满约对应 4 秒已生成音频，**不是固定 4 秒墙钟等待**。首帧以及后续窗口未满的帧仍走上游 eager，短回答可能在结束前始终没有进入编译路径。启动预热可以提前完成编译，却不会让新回答的历史自动填满。

建议研究固定形状历史缓冲区加有效位置掩码，让未满窗口也可编译；首帧无惩罚和后续有惩罚可用不同的稳定图。必须验证只对有效历史施加原有惩罚，不能用伪造历史填充窗口，也不应默认关闭重复惩罚来换速度。增加每轮前 1/5/10/50 帧的耗时与 eager/compiled 计数，直接评价短句收益。

### 3.3 首包已经按一帧解码，不能误判为等待六帧

固定版服务创建 `AudioStreamDecoder(chunk_frames=6, initial_chunk_frames=1)`。解码块按 1、2、3……逐步增加，最大到 6 帧。因此默认 `decode_chunk_frames=6` 不意味着首包必等 6 帧，也不能据此声称改成 1 就能省下 400ms。

codec 是否在内部累计、单帧调用多久、返回多少有效样本，仍需记录。继续减小后续块会增加调用开销，必须检查持续供音和断流。

### 3.4 文本等待要看实际接口，不能照搬通用 session 默认值

通用 session 的 `push_text()` 有字符缓冲与标点分段，但固定版服务实际使用 `push_text_tokens()`，绕过了这一层字符缓冲。因此不能把 `text_buffer_size=32` 当成当前首包慢的已知原因。

仍然存在 prefill 门槛：服务使用 `processor.delay_tokens_len`，通用 session 默认值为 12。文本不足且尚未结束时不会启动 prefill；结束后则允许短文本开始生成。须记录实际门槛与达标时刻，及时发送真实文本结束事件，尤其检查只有几个词的回答。

12 token 与模型的文本—音频延迟设计有关。降低到 8 或 4 可以作为独立质量实验，不能视作无损配置修改；需要检查漏词、重复、发音、韵律和后续接续。首轮优先保持该门槛，先解除交付阻塞。

### 3.5 参考音色缓存与 backbone

固定服务已经缓存参考音频的 codec token，不能假定每轮都重新编码参考 WAV。不过每轮创建 inferencer 并重置 KV，参考提示仍可能反复参与模型 prefill。

先测参考提示长度与 prefill 占比，再考虑缓存完全一致的固定前缀 KV。可变 KV 必须按会话隔离，不能把前一条已取消回答的缓存当成新回答前缀；完整多轮语音上下文复用会改变条件，不宜作为本轮首选。

backbone 已成为稳态最大单项，可继续研究 decode step 的编译、静态 cache 或图捕获。但首轮要区分 prefill 与 decode：只优化单 token step 不一定显著降低首包。量化与更换推理引擎留到上述路径测量之后，避免同时引入多个变量。

## 4. 替换 TTS 的候选

公开延迟只用于筛选，硬件、输入交付与计时起点并不一致，不能直接排列为本项目实测榜单。

| 方案 | 官方信息 | 对本项目的判断 |
| --- | --- | --- |
| 保留 MOSS-Realtime | 官方 Realtime README 报告 L20 预热后 TTFB 180ms，开启 SDPA 与 compile；另将 LLM 生成首批文本计时 | 优先排查当前服务与该路径的差距；不能据此承诺 4090 达到同值 |
| CosyVoice | 官方仓库描述支持文本输入与音频输出双流，宣称低至 150ms | 首选替换对照，核验实际所选 checkpoint、推理后端及双流接口；仓库级宣传不等于任意模型的首包保证 |
| Pocket TTS | 官方描述 100M、CPU 音频流式、首包约 200ms | 可作为轻量对照；额外核验目标语言、文本增量接口与服务器 CPU 性能，不能从音频流式推断支持任意文本增量 |

替换不会在结构上要求重新训练 DuplexCascade：LLM 向 TTS 交付文本，TTS 不决定话轮 token。但不同语速、韵律和首音时刻会影响 FDB 与打断行为，需要重新验证。当前研究没有要求特定声音克隆效果，选择以英文可懂度、短问句自然度、首音和可取消性为主。

## 5. 目标预算与验证顺序

建议将“首个回答文本可用 → 客户端首个可听语音”设为 TTS 链路目标：常见短回答约 250–350ms，长尾目标 p95 不高于 500ms。这是拟议预算，不是实测结论，也不代表用户提出的 1.5 秒限制已经满足。

整体 1 秒可以先按输入交付 200ms、轮次调度 250ms、LLM 首文本 100ms、TTS 至可听首音 300ms、其他交付余量 150ms 分配；各阶段定义须互斥并按同一回答计时。真实流式阶段可以重叠，最终以同一端到端时钟为准。若保留约 600ms 的额外话轮等待，即使 TTS 达到预算，也很难稳定亚秒级。

远端验证使用独立 conda 环境和固定 4090；GPU 作业尚未提交，工具准备与缺项见远端任务单。顺序为：

1. **补齐阶段计时并复现基线。** 同一 request/response 记录首文本、排队、会话准备、prefill 门槛达标、prefill 起止、首帧、首 codec PCM、发送、客户端接收、实际消费及非静音起点。跨进程比较注明时钟和传输误差。
2. **单变量降低生成批次帧数。** 保留批量交付，以同一文本 token 序列比较原路径与有界小批次，检查首音、连续供音和自然度；改造后要求帧序列和文本内容保持一致。不默认采用逐帧发送。
3. **单变量覆盖开头编译路径。** 每轮前段计时，比较短回答和长回答；保持采样与重复惩罚语义，分别报告冷启动和已预热结果。
4. **按占比优化 prefill、codec 或 backbone。** 只有证据显示文本积累主导时，再做 prefill 门槛实验。
5. **仍超预算时测 CosyVoice 对照。** 保持同样文本、同样推入节奏和播放链路；通过短句质量和延迟门槛后再做集成替换。

组件测试建议使用非评测文本：短答、短澄清问句、完整长句，覆盖数字、专名、标点、真实 LLM 分块与文本中途取消。固定至少 30 条短句并重复测试，报告 p50/p95、均值、首包有效音频长度、断流次数、显存和短句错误；逐条保存 WAV 与时间线，不能只测试一次整句输入。30 条适合初筛，不能用于宣称可靠的极端尾延迟。

通过组件筛选后回放原 FDB 小子集，检查顺畅接话、停顿、用户附和和插话后的新回答；同时统计无回答比例。优化可能让原本因延迟而没被录到的错误抢答变得可听，因此低延迟与话轮正确性必须共同验收。小子集通过后才扩大 FDB 评价。

取消验证必须覆盖队列中尚未播放的旧音频，以及取消后后台仍在生成的帧；只有当前有效 response 可以进入唯一播放链路。已被听到的内容不回滚，不引入 Layer 2/3 或额外仲裁器，不使用预录的泛化附和音冒充回答来改善首音指标。

## 6. 来源

- 本地：[MOSS 补丁说明](scripts/remote/moss_tts_patch.md)、[历史 FDB 分解](fdb_latency_diagnosis.md)、[A4 吞吐结果](xtalk_a4_remote_acceptance.md)。
- 固定代码：[MOSS 服务与会话处理](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/moss_tts_realtime/fast_api.py)、[流式 session 与 decoder](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/moss_tts_realtime/mossttsrealtime/streaming_mossttsrealtime.py)、[WebSocket 适配器](https://github.com/xcc-zach/xtalk-moss-tts-realtime/blob/b3306b97f8a64c1a2f25b9803c070ff32ecff6b1/serving/fast_api_entrypoint.py)。
- 候选与公开指标：[MOSS-Realtime README](https://github.com/OpenMOSS/MOSS-TTS/tree/main/moss_tts_realtime)、[CosyVoice 官方仓库](https://github.com/QwenAudio/CosyVoice)、[Pocket TTS 官方仓库](https://github.com/kyutai-labs/pocket-tts)。公开信息查阅日期为 2026-10-17，实验前应再次固定候选源码与权重 revision。
