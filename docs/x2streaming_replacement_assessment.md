# X2Streaming ASR/TTS 替换可行性调研

调研日期：2026-10-15。本次阅读官方论文、权重说明和实际源码，未下载模型、未执行 GPU 推理、未改现有配置。结论是替换候选排序，不是已通过本项目验收。

## 1. 来源与固定版本

- [ASR 论文 v1](https://arxiv.org/html/2609.08672v1)：早期中文实验。
- [ASR 源码](https://github.com/X-Square-Robot/X2Streaming-ASR)，本次 checkout `0aca80597bb1399c0be4002de5bc62c0a779c542`；[当前权重](https://huggingface.co/x-square-robot/X2Streaming-ASR-4B-1009)。README 的新版中英文结果与论文 v1 不同，不能混为同一实验。
- [TTS 论文](https://arxiv.org/html/2608.18661v1)、[TTS 方法源码](https://github.com/X-Square-Robot/X2Streaming-TTS)，本次 checkout `e96f066150c2b2353854e56a790262a80a2fff3d`；[TTS 权重说明](https://huggingface.co/x-square-robot/X2Streaming-TTS-1.7B)。
- [TTS 推理引擎](https://github.com/X-Square-Robot/Qwen3TTS-Streaming)，当前源码 `87eeeb3a582bd13ee7662e1a522b47c65b4c2a26`。方法仓库的 `UPSTREAM_LOCK.json` 实际固定的是旧提交 `0745e4a8613f0780cc57475452ee775a9abac2dd` 并要求两份 hook 补丁。因此当前引擎的测试数字不能视为方法固定版本的复测结果。

## 2. ASR：能解决哪一种尾部不稳定

X2Streaming-ASR 采用因果音频编码器、适配器和自回归解码器，每个约 80ms 音频 token 决定 Wait 或 Emit，Emit 后只生成新增文字，再返回监听。在线提交采用只追加的硬提交，不靠反复重识别旧尾部纠正假设。因此从设计上消除了我们当前“Qwen 重写已释放尾部 → 提交前缀冲突 → 可见文本冻结”的机制。它仍可能提前提交错误、漏字、重复，或因不确定而等待；不回写不等于没有识别错误，也不能撤回一次错误提交。

当前公开权重约 4B、BF16、16kHz 单声道，支持 `zh/en/cs`；基于 Voxtral Mini Realtime，而非 Qwen3-ASR 的修订窗口包装。显式设置语言，FDB 应为 `en`，不能依赖默认中文。

### 源码接入陷阱

`demo/engine_adaptive.py::AdaptiveSession` 默认 `enable_offline=True`；`finish_async` 先关闭在线路径，再可选对完整音频跑离线识别。`demo/app.py` 能把离线结果作为 final 返回。模型在线硬提交不回退，但直接使用 Demo final 仍可能覆盖在线文字。必须关闭离线覆盖，只使用 `live_emit/live_done`，离线结果仅可作独立质量分析。

`finish_async` 还会关闭线程和释放状态，属于整个会话结束操作；不能把当前每次声学 pause 都映射成它。短暂停顿应继续保持同一会话并接收静音，流尾才 flush；真正 reset 时才关闭。当前 `ASR.recognize_stream(is_final=True)` 是暂时边界提示，必须由新适配器明确实现这一区别。

### 准确率和延迟

最新 README 的部分结果如下，错误率单位为百分比，时间为毫秒：

| 数据集 | CER/WER | 平均提交等待 | P95 |
| --- | ---: | ---: | ---: |
| AISHELL-1 | 1.53 | 32 | 320 |
| AISHELL-3 | 2.08 | 57 | 400 |
| WenetSpeech Meeting | 8.67 | 74 | 320 |
| WenetSpeech Net | 7.88 | 109 | 400 |
| LibriSpeech clean | 2.20 | 29 | 240 |
| LibriSpeech other | 5.50 | 85 | 480 |
| GigaSpeech clean | 10.01 | 43 | 320 |
| VoxPopuli | 7.07 | 12 | 320 |
| TED-LIUM | 3.42 | 15 | 240 |

数据支持“低等待且准确率有竞争力”，不是所有数据集都最好，也没有本项目 Qwen3-ASR-1.7B 配置的同条件直接对比。不能用这些 CER/WER 推断其在 Candor 自发口语上一定更准。

论文定义的延迟是提交时刻相对强制对齐字/词声学终点的等待；源码 `interleaved.py` 的 `time_s` 由消费的音频帧数计算，Demo 另有 wall 时间。因此这些数字主要反映算法读到多少音频才提交，不足以证明 4090 的真实客户端交付为 12–109ms。须另外测音频输入时刻、计算积压、解码完成和消息收到时刻，P95 可达 240–480ms 也不能忽略。

### 适配成本与判断

推荐优先验证其替换 Qwen3-ASR。按提交片段累积为单调文本，复用 X-Talk ASR 事件和现有单一播放链；优先长连接服务，80ms 左右送音频，保留每会话模型缓存。若继续 600ms 批量送入，低算法等待收益会被输入聚合吞掉。约 4B BF16 权重裸大小约 8GB 是估算，不含缓存/运行时，24GB 4090 单独部署有可行性但需实测，不能视为显存保证。依赖要求与现环境差异大，应远端独立 conda 环境或镜像，不能原地升级共享环境。ASR 换得更快也不会自动去掉 600ms micro-turn 或改变模型让轮策略。

## 3. TTS：不回写已播音频，但仍有语义和分段风险

X2Streaming-TTS 是基于 Qwen3-TTS 的方法扩展，推理依赖 Qwen3TTS-Streaming 的 TensorRT 引擎。两个核心机制：未确定发音的文本尾部先缓冲，确定后单调提交；相邻声学片段继承 Code2Wav 状态与少量 Talker 历史，减轻断裂。比如数字 3 后面可能接单位或 rd，等待消歧比把错误发音播出后修正合理。可变的是尚未承诺的文字，已播放音频不回写，符合项目输出边界。

这种设计没有消除全部不稳定。[官方限制](https://github.com/X-Square-Robot/Qwen3TTS-Streaming/blob/main/docs/user/known_limitations.md) 明确保留重复、漏读、插入词、异常静音和某些长文本退化；输出 VAD 也可能增加起音确认等待或削掉辅音。当前引擎报告的 0/100 runaway 是固定探针、指定 BF16 产物上的结果，不是 0% 所有错误。论文方法仓库也说明更广的并发、故障和长流验证仍在进行。

### 质量与延迟口径

论文表 1：SEED-TTS-Eval 中文 CER 0.78%、英文 WER 1.93%；MiniMax 中文 CER 0.78%、英文 WER 1.86%。这些是“生成语音被另一个 ASR 转写后”的错误率，不能与输入 ASR 的错误率直接比较，也不是 MOSS 同条件对照。英文 SEED 低于 CosyVoice3 的表现，故非所有项最好。论文 10 倍长文本错误率为 4.36%，仍说明存在残余错误。

论文单 RTX 5090、BF16、预热后客户端首音频 token 中位数 15.8ms，128 并发 260.8ms；不是用户话轮结束到首个可听词，也不是我们 4090 上 TTSStarted→首 PCM 的同口径结果。应包括首个可用文字提交的等待、codec 输出、输出 VAD、网络及播放器，不能用 740/15.8 直接声称快 47 倍。

当前推理引擎另报单请求 WebSocket 23.290ms、gRPC 24.593ms 平均首包，128 并发约 1114/1274ms；硬件、缓存、版本和统计量与论文不同。该引擎明确承认当前高并发慢于历史版本。我们关注单会话，可将其视为强候选信号，不能拼成同一张无条件性能表。

### 当前权重是否适合替换 MOSS

公开 `X2Streaming-TTS-1.7B` 为单音色 `robot_service_v1`、中文主训练、英文次要能力，24kHz 单声道；模型卡明确英文自然度低于中文，数字、日期和单位应先做文本规范化。项目最终日程任务恰好对日期时间敏感，这一项必须定向测。当前引擎验证最充分的是 custom_voice；声音克隆仍为实验能力，不能假定直接保留当前 MOSS reference.wav 的音色。

引擎提供增量文字、二进制 PCM 和 cancel 接口，原则上可映射到 `StreamingTextTTS.start/append_text/flush/stop/audio_stream`。注意其协议 `stop` 表示结束输入并排空音频，真正中断应发 `cancel`；不能把 X-Talk 的打断 stop 误接成服务端 drain。保留当前唯一 TTS 播放所有者，取消后丢弃旧 response 音频，重采样或正确协商 24kHz。它需要 TensorRT 导出和匹配构建，官方建议至少 16GB 显存，不能只换 Hugging Face 路径。

结论：适合作为第二优先级候选，中文固定音色场景更值得尝试；当前英语 FDB 与保留参考音色的需求下，证据不足以直接替换 MOSS。对方法锁定的旧引擎与当前上游需选定一个固定组合，先验证兼容性，不能默认两份补丁可直接套在最新版本。

## 4. 建议的远端最小决策实验

保持本轮数据和官方权重模型，逐个组件替换，使用独立 conda 环境：A 为当前栈，B 只换 ASR，C 只换 TTS；只有 B/C 单独通过再测组合。原始 Qwen 栈的已知冻结问题须作为已知故障记录，同时与修复后的 Qwen 比较，避免把包装缺陷误报成模型准确率优势。

ASR：优先 Candor/1、100、102 的 pause→resume，再覆盖原 25 条及中文日期时间。记录可见文本回退次数、恢复发声后提交空档、WER/CER、日期时间实体错误、音频末词至客户端提交 P50/P95、实时因子/积压、显存与长会话表现；离线 final 不得覆盖在线提交，不能由全量文件离线喂入伪造实时延迟。

TTS：用相同答案及真实 LLM token 到达节奏，记录首文字到可提交文字、首 PCM、实际有声起点、首词及取消到最后一帧的 P50/P95；覆盖英文 FDB 答案、中文日期/时间/数字、短句、长句、断续输入和被打断后重开。核查漏读/重复/添词、尾音完整性、音色与自然度，继续用现有播放确认保证已经听到的文本不被撤回。

最后复跑同样 FDB 四轴：不能以降低 ASR/TTS 首包为由接受 pause 抢话、用户附和误打断或无回答增加。当前调研支持先做 ASR 替换验证；尚不能得出两组件应同时切成默认栈的结论。
