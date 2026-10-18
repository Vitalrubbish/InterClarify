# 英文低延迟流式 TTS 调研

调研日期：2026-10-18。以下延迟均为**官方声明或架构说明，不是本项目实测**；不同硬件、原生块大小、参考音色、启动条件不统一，不能按标称数字直接排名。自然度交由用户试听评价。

## 候选与筛选

| 系统 | 英文与流式能力 | 本轮处理 | 官方依据 |
| --- | --- | --- | --- |
| MOSS-TTS-Realtime | 现役文本/音频流底座；已有本地码本编译优化 | 保留同硬件对照，复用现役来源与参考音色；不拿历史诊断数冒充新测试 | [官方](https://github.com/OpenMOSS/MOSS-TTS)；[现役来源](xtalk_baseline_stack.md) |
| Kyutai TTS 1.6B EN/FR | 官方提供整文本生成及增量文本示例，音频 codec 帧回调；服务器用途明确 | 首轮正式比较，已有远端缓存，固定来源后使用 PyTorch 原生回调 | [官方仓库](https://github.com/kyutai-labs/delayed-streams-modeling#kyutai-text-to-speech) |
| Pocket TTS 100M | CPU 原生音频流，官方称约 200ms 首块、M4 CPU 约 6 倍实时；Python 接口接收字符串，不把该接口称作增量文本输入 | 首轮比较；首选官方 CPU 配置，记录 CPU，不能将 M4 数字移植到集群 | [官方仓库](https://github.com/kyutai-labs/pocket-tts) |
| Kokoro 82M | 美英/英英音色；`KPipeline` 先做文本/音素分段，每次返回该段完整波形 | 轻量对照，明确标为分段合成；不归为帧级双向流式 | [官方代码](https://github.com/hexgrad/kokoro/blob/main/kokoro/pipeline.py) |
| Fun-CosyVoice3 0.5B 2512 | 支持英文，官方称双向流式可低至 150ms；英文内容一致性与自然度有官方评测 | 强候选，下一优先级；需准备独立依赖与参考音色，核验官方流式入口再测试 | [官方仓库](https://github.com/QwenAudio/CosyVoice) |
| NVIDIA Magpie TTS 357M | 英文在内的多语音色，模型卡列出 NeMo 推理及长文本限制；NIM 流式是部署栈能力，不能等同所有 Python 入口均流式 | 调研候选，先核验 NeMo 原生流式接口及权重/服务栈，暂不引入另一整套产品运行时 | [官方模型卡](https://huggingface.co/nvidia/magpie_tts_multilingual_357m)、[NIM](https://docs.nvidia.com/nim/speech/26.02.0/tts/index.html) |
| Qwen3-TTS 0.6B/1.7B | 官方称双轨架构最低 97ms；README 同时将在线服务及 vLLM-Omni 优化单列，需验证实际安装版本是否暴露音频迭代输出 | 不依据 97ms 将默认整段生成接口列入原生流式实测 | [官方仓库](https://github.com/QwenLM/Qwen3-TTS)、[官方仓库流式接口讨论](https://github.com/QwenLM/Qwen3-TTS/issues/10) |

另一个值得补测的自部署候选是 [VibeVoice-Realtime 0.5B](https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-realtime-0.5b.md)：英文、单说话人，文档介绍流式文本和约 200ms 首可听，同时列出约 300ms 首块说明，并仍在 TODO 中列出边生成边补文本接口。短文本也是其已列出的局限。因此须固定代码版本验证实际接口，不能把模型设计描述直接等同完整可用的双向流式服务。

云服务可作为后续对照：[Cartesia Sonic](https://www.cartesia.ai/sonic) 当前页面宣传 Sonic-3.6 和低于 90ms 首音频；[ElevenLabs 模型文档](https://elevenlabs.io/docs/overview/models) 列出 Flash v2.5 约 75ms、v4 Turbo 约 100ms 推理延迟；[Deepgram](https://developers.deepgram.com/docs/tts-models) 提供英文音色与服务接口。它们的厂商延迟不含本项目贵州服务器的网络条件，且未提供对应 TTS 服务凭据，本轮不冒用现有其他服务密钥或将云端声明填作实测。首轮优先比较与现役链路一致的自部署方案。

首轮以可核验的原生音频输出、英文适配和现有资源为准，选择 MOSS、Kyutai、Pocket 与 Kokoro 对照。它们不是穷尽列表；首轮结果不代表已证明优于尚未测试的 CosyVoice/Magpie/Qwen。语音质量与实际首可听内容优先于标称参数量或单次首包。

## 与项目需求的关系

对澄清问句，用户需要尽快听到**有意义的语音**，首块里只有静音仍会造成等待。持续供音不足实时同样会破坏短句节奏。真正增量文本输入还须验证文本尚未结束时能否出声、断句和取消语义；本轮的完整文本输入结果只回答 TTS 服务自身的延迟，不能推出 LLM→TTS 全链路结论。

默认英文音色之间的差异会影响主观选择。所有模型先按各自官方推荐或现役音色生成同文本，保持未裁剪原始开头；人工盲听后再决定是否补充统一参考音色的克隆实验。
