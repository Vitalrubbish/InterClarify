# 无回写流式 ASR 候选普查（含标点判据）

调研日期：2026-10-16。本次只阅读官方模型卡、论文、README 与许可证原文，未下载权重、未执行推理、未改现有配置与代码。结论是候选排序与待验证清单，不是已通过本项目验收的结果。本文不改变 [engineering_implementation.md](engineering_implementation.md) 的任何实现边界。

## 1. 判据与项目语境

五条硬性判据，缺一不可：

1. **流式**：音频边到边识别，不等待整段文件；
2. **低延迟**：提交延迟与本项目 ASR 事件节奏可比；
3. **无回写**：已释放文本永不修订。这不是显示偏好，而是项目输出边界（已被用户听到的内容不可撤销），并与 X-Talk 适配器 `advance_committed` 的前缀单调检查兼容；
4. **准确率尚可**：中文与英文均需达标（中文日期/时间、英文 FDB 答案都是现有验收内容）；
5. **输出标点**：本轮新增硬性条件。本地实验已证明标点不只是排版问题：`x2streaming_asr_retest.md` §12.1 中样本 101 末段 ` steam on` 在补上句号后，控制模型下一拍即输出 finish-talking 并开始回答；§12.2 确认 X2 权重在线提交 1,022 条中含句读标点者为 0。

部署约束沿用现状：远端 4090（24GB）、独立 conda 环境、单一 ASR 服务、FDB 为英文、中文含日期时间语句。

## 2. 结论摘要

| 排序 | 候选 | 流式 | 低延迟 | 无回写 | 准确率(zh/en) | 标点 | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Confucius4-R2T2（网易有道） | ✓ | 200–600ms 均值 | ✓（尾部 1 token 回滚窗口需适配层扣留） | 接近离线 Qwen3-ASR | 待实测（基座输出标点，权重未声明） | 唯一结构上五条全中的候选，优先验证 |
| 2 | Nemotron 3.5 ASR streaming 0.6B | ✓ | chunk 80–1120ms | ✓（RNNT 单调发射） | 英文合格，**中文仅 broad-coverage（FLEURS CER≈19–20%）** | ✓ 原生 | 中文判据不满足；作英文对照/备选 |
| 3 | Kyutai stt-1b-en_fr（DSM，官方 DuplexCascade 的 ASR，见 §6） | ✓ | 固定 0.5s delay | ✓（逐词 `Word` 事件只追加） | **仅 en/fr，无中文**；en 平庸（Voxtral 报告：En-Short 12.26 / En-Long 13.83 WER@500ms） | ✓ 声明带大小写与标点 | 中文判据不满足；但证明"无回写+标点"组合已存在于官方参照系 |
| 4 | Voxtral-Mini-4B-Realtime-2602 | ✓ | 240ms–2.4s 可配 | ✓（DSM 逐帧生成，服务端只发增量 delta） | zh FLEURS 15.74% WER@480ms，平庸 | 未声明；其微调 X2 实测无标点，先验为负 | 标点判据大概率不满足；作架构参考 |
| 备选 | X2Streaming-ASR-4B | ✓ | 32–109ms 均值 | ✓ | 中英强 | **实测 0/1022 含标点** | 若标点判据可放宽仍是第一优先 |
| 现役 | Qwen3-ASR-1.7B | ✓ | — | **✗ 修订窗口→前缀冲突→可见文本冻结** | 强 | ✓ | 回写判据不满足 |

云 API（Deepgram、AssemblyAI、Soniox、Speechmatics、ElevenLabs、讯飞/腾讯/阿里/火山）作为类别整体排除：partial 结果在 final 前持续修订（R2T2 对照表中凡标 ※ 者即此类），只消费 final 可保单调但延迟上升，且引入外部网络、隐私与费用依赖，与远端集群自部署形态不匹配。

## 3. 候选一：Confucius4-R2T2

- 代码：[GitHub master README](https://github.com/netease-youdao/Confucius4-R2T2)（本文引用其评测表）；权重：[HF](https://huggingface.co/netease-youdao/Confucius4-R2T2) / [ModelScope](https://modelscope.cn/models/netease-youdao/Confucius4-R2T2)。基座为 `Qwen/Qwen3-ASR-1.7B`——**与当前栈同一基座**。
- 机制：在 Qwen3-ASR 上以稳定前缀数据、强制时间对齐数据、token 级音频分段训练"最长稳定前缀（LSP）"提交策略；只暴露稳定前缀，已提交文本不再变更。chunk 80ms–2s 可配，默认 160ms。
- 无回写的唯一偏差：`UNFIXED_TOKEN_NUM`（默认 1）是尾部未固定 token 的回滚窗口。适配层只对外发布"已固定前缀"、扣留最后 N 个未固定 token 即可对外保持严格单调；需核实其 `ws_server.py` 实际发送的增量是否已只含固定文本（见 §9 第 2 项）。
- 服务形态现成：WebSocket 端点 `/asr_stream_api_v1` 接收 16kHz int16 PCM，返回 JSON 增量 `text`（"newly recognized segment"，客户端拼接即全文），天然映射现有 ASR 事件与 micro-turn 组装；vLLM 后端；官方建议直接跑在 `qwenllm/qwen3-asr` Docker 镜像里（conda python 3.12 或 Docker，均符合本项目环境规则）；可选 FireRedVAD。
- 官方评测（160ms，zh 为 CER%、en 为 WER%）：Wenet-net 5.87、Wenet-meeting 7.27、SPEECHIO-06 7.30、SPEECHIO-07 8.20、CN-RealSI 3.48；LS-clean 2.13、AMI 11.37、Giga-clean 9.60、TED-LIUM 3.34、Earnings22 9.36。对照离线 Qwen3-ASR（3.34–6.19 / 1.67–9.25），流式退化约 0.5–2.7 点。同表中"Qwen3-ASR base 160ms"列 CER/WER 高达 13–39%——即朴素分块流式 Qwen 的崩坏，独立佐证了当前栈冻结问题的根因。
- 标点：基座 Qwen3-ASR 输出句末标点（当前栈实测 `'I never like.'` 等），R2T2 在其上训练且 API 保留 `state.text` 全文；但 README 与演示均未显式声明标点恢复，**五判据中唯一未直接证实的一条，必须实测**（方法复用 X2 §12.2 的提交标点统计）。
- 许可：代码 Apache-2.0；权重为 [NetEase Model Use License](https://raw.githubusercontent.com/netease-youdao/Confucius4-R2T2/master/MODEL_LICENSE)：月活超 1 亿或年收入超 10 亿元需另行授权；不得用于改进其他商业 AI 模型；排除医疗诊断、自动驾驶、军事等高风险场景。本项目研究用途在其免费范围内，但该协议为非 OSI 许可证，须在来源登记中如实记录。
- 风险：tech report 尚未发布（"will be released soon"），方法细节暂不可复核；延迟口径为 chunk 级"retrospective fuzzy latency"均值 200–600ms，与 X2 的逐字符对齐提交等待（32–109ms）口径不同，不能直接横比。

## 4. 候选二：Nemotron 3.5 ASR streaming 0.6B

- [HF 模型卡](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)（2026-06-04 发布）：Cache-Aware FastConformer-RNNT 600M + 语言 ID prompt，40 个 locale。RNNT 贪心解码逐 token 单调发射，结构上无回写；原生标点与大小写（训练标签的标点由 Qwen3-32B 生成）。
- 流式配置：`att_context_size=[56, r]`，r∈{0,1,3,6,13} 对应 chunk 80/160/320/560/1120ms，运行时可换、无需重训。Transformers ≥5.13 原生流式（`TextIteratorStreamer`），另有 NeMo 脚本与 GGUF（NeMo-Speech.cpp，可 CPU）。600M 显存占用极小，可与其他服务共存单卡。
- 准确率（FLEURS，LangID）：en 7.91% WER@1.12s、9.43%@80ms；**zh-CN 属 broad-coverage 层级，CER 19.28–20.56%**，R2T2 表中其 160ms 中文 Wenet-net 24.70 / Wenet-meeting 20.18。中文判据明确不满足。
- 其他注意：第三方实测（Sam Witteveen）称流式模式下标点质量不稳定；`auto` 语言检测会在句末标点后附加 `<xx-XX>` 语言 tag，须在适配层用 `strip_lang_tags` 剥除，避免把 tag 当成文本流的一部分。Voxtral Realtime 技术报告将其列为基线，En-Long 14.29/13.02%（560/1120ms），长音频偏弱。许可 OpenMDW-1.1（可商用、需署名）。
- 定位：纯英文场景的合格第二候选（严格单调 + 原生标点 + 极轻）；因中文不合格，本项目只作对照与备选。

## 5. 候选三：Voxtral-Mini-4B-Realtime-2602

- [HF 模型卡](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602)、[技术报告 arXiv:2602.11298](https://arxiv.org/abs/2602.11298)。Apache-2.0，4.4B（0.97B 因果音频编码器 + 3.4B Ministral 解码器）。DSM 流同步架构：每 80ms 帧解码一步，`[P]` 等待、`[W]` 起词；已生成文本 token 立即成为后续解码条件，模型内无修订机制；vLLM Realtime API 只回 `response.audio_transcript.delta` 增量，服务层同样追加式。
- 延迟由 AdaRMS-Norm 条件化，240ms–2.4s 可配（推荐 480ms）。zh FLEURS：480ms 15.74%、2.4s 14.30%（WER 口径），中文平庸；其微调 X2 的中文强势说明可经微调改善，但那是训练投入，不是开箱能力。
- 标点：模型卡未声明；HF 讨论区存在 "punctuation marks" 提问；其微调 X2 在线实测 0/1022 条含标点——**先验为负**。若无本地直接实测推翻，按不满足判据处理。
- 定位：R2T2 之外唯一"架构级追加式 + 开源权重服务"成熟路线，也是 X2 的基座；若未来自训标点版流式模型，它是合理的起点。

## 6. 参照系：官方 DuplexCascade 使用的 ASR

官方仓库 `sbintuitions/DuplexCascade`（固定提交 `4289302`，本项目 Layer 1 权重的同源实现）的 ASR 不是 Qwen 系，而是 **Kyutai 的 delayed-streams-modeling 流式 STT**：

- 启动方式（README）：`moshi-server worker -p 31607 --config config-stt-en_fr-hf.toml`；
- 具体模型（该 toml）：`hf://kyutai/stt-1b-en_fr-candle`，约 1B 参数，Mimi 音频 tokenizer，12.5Hz 帧率，`asr_delay_in_tokens = 6`（约 0.5s 固定延迟），temperature 0；
- 协议（`server.py::stt_receiver_task`）：STT 经 WebSocket 逐词推送 `{"type": "Word"}` 事件，服务端把词**只追加**进缓冲，每个 `overlap_window_s`（默认 0.6s）拼一次增量文本作为 user micro-turn，无词时发 `<|no voice|>`——与本项目 A2/A3 对齐的官方推理实现一致；
- 无回写：DSM 流同步架构逐帧生成文本 token，词一经发出即成为后续条件；协议层 `Word` 事件只追加、从不修订。Voxtral Realtime 即该架构的商业后继（同一第一作者），见 §5；
- **标点：模型卡明确声明 "The model produces transcripts with capitalization and punctuation"**——预训练用 whisper-timestamped 合成带标点转写（250 万小时公开音频），微调用 Fisher 2000 小时英语 + 1000 小时英语/600 小时法语专有真实转写；
- 局限：仅 en/fr 两语（无中文）；准确率平庸（Voxtral Realtime 技术报告实测 DSM 1B En-Fr@500ms：En-Short 12.26% / En-Long 13.83% WER）；权重 CC-BY-4.0；另有 `stt-2.6b-en`（仅英语，2.5s delay，无标点声明）。

对本项目的两个直接推论：

1. **"流式 + 无回写 + 输出标点"的组合并非新需求**——官方参照系从 2025 年起就是这种配置。替换 ASR 时保持该文本分布（含大小写与句末标点）比引入无标点小写文本更贴近 DuplexCascade 控制模型的训练分布；X2 的无标点小写输出相对官方管线属于分布外输入，这与 [x2streaming_asr_retest.md](x2streaming_asr_retest.md) §12.1 中"句号对固定文本轨迹有效"的观察方向一致（该实验同时声明不能未经验证归因于无标点，结论仍以 §9 实测为准）。
2. 官方 `server.py::filter_period_for_tts` 把 assistant 文本中的句号删去再送 TTS、仅保留给前端显示——官方管线自身就存在"文本带标点、TTS 不要标点"的不对称处理；后续替换 ASR/TTS 时不应把这类过滤误当成回写机制，它是单向的、不修改已释放文本。

## 7. 已排除项与证据

- **X2Streaming-ASR-4B**：无回写、低延迟、中英准确率强（AISHELL-1 1.53/32ms 等），但 [x2streaming_asr_retest.md](x2streaming_asr_retest.md) §12.2 已证当前权重在线输出无标点（1,022 条提交含标点 0 条，词表允许但权重未学会）。不满足第 5 条判据；若该判据放宽，它仍是延迟最优解。无标点对控制模型等待行为的影响（§12.1）因果尚未完全定案，记录在案。
- **Qwen3-ASR-1.7B（现役）**：输出标点、流式可用（官方表：流式 WER 均值 3.33 vs 离线 2.69），但流式采用修订窗口（R2T2 表中标 ※ 的伪流式类），本地已观测前缀冲突导致可见文本冻结 26.3s/330 拍（[xtalk_a4_remote_acceptance.md](xtalk_a4_remote_acceptance.md) §7.6、[fdb_latency_diagnosis.md](fdb_latency_diagnosis.md)）。
- **Zipformer / X-ASR / Paraformer 流式（sherpa-onnx 路线）**：transducer/BPE 输出不含标点，判据 5 不满足；补 CT-Transformer 后处理器则引入额外组件与延迟，超出当前 MVP 边界。X2 表中该类 zh CER 7.9–11.3、延迟 400–600ms，无速度优势。
- **云 API 类**：见 §2。仅消费 final 可换取单调，但延迟与部署形态不匹配，列为类别性排除，不再逐家展开。

## 8. 口径声明

- 延迟口径互不可比：X2 为强制对齐字符/词声学终点→提交的等待（32–109ms）；R2T2 为 chunk 级"retrospective fuzzy latency"（200–600ms）；Nemotron/Voxtral 为 chunk/delay 设置加托管 TTFS（Together 宣称 sub-100ms，Soniox 实测中位 236ms）。不得拼成一张无条件性能表。
- 准确率数据集不同：AISHELL/WenetSpeech（X2、R2T2）与 FLEURS（Nemotron、Voxtral）不可直接横比；FLEURS 的 zh 数字按 WER 口径时本身偏高。
- 所有厂商自报数字均未经本项目远端复测；R2T2 的方法细节（tech report）未发布前，其机制描述只能按 README 采信。

## 9. 建议的下一步（最小决策实验）

优先级从高到低，全部使用独立 conda 环境或 `qwenllm/qwen3-asr` 镜像，远端执行按 AGENTS 规则另出任务单：

1. **R2T2 标点实测**（门禁项）：中英文各不少于 25 条（含句末陈述/疑问/日期时间语句），流式 160ms 与 560ms 两档，统计在线增量提交中标点出现率、位置、大小写保留与句末标点到达延迟，对照 §6 官方管线的文本分布；方法复用 X2 §12.2。若标点缺失，R2T2 降级与 X2 同级。
2. **unfixed token 语义核实**：读 `ws_server.py` 与 `R2T2ASRModel.streaming_transcribe` 源码，确认对外增量是否只含已固定文本；若含未固定尾部，适配层扣留最后 `UNFIXED_TOKEN_NUM` 个 token，并保证对外零回退。
3. **延迟实测**：音频输入时刻→客户端增量到达的 P50/P95，不能只记录 `asr_cost_ms`；含 FDB 英文与中文日期时间语句。
4. **A/B 对照**：A=现役 Qwen 栈（保留已知冻结缺陷为基线），B=R2T2 替换 ASR 单组件（沿用 [x2streaming_replacement_assessment.md](x2streaming_replacement_assessment.md) §4 的单组件替换纪律）；跑既有 link 顺序/插话检查与 FDB 四轴，记录可见文本回退次数（必须为 0）、冻结时长、CER/WER、日期时间实体错误、显存与长会话表现。
5. 通过后再测组合（如 R2T2 + 现役 MOSS），不提前扩大范围。

## 10. 来源清单

- Confucius4-R2T2：GitHub master README、HF/ModelScope 模型卡、MODEL_LICENSE（NetEase Model Use License Agreement 原文）。
- Nemotron 3.5 ASR：HF 模型卡（含 FLEURS 全表与 att_context_size 说明）、[Baseten 发布文](https://www.baseten.co/blog/introducing-nvidia-nemotron-35-asr-streaming)、Together AI 模型页、HF 官方微调博客。
- Kyutai DSM STT：[kyutai/stt-1b-en_fr 模型卡](https://huggingface.co/kyutai/stt-1b-en_fr)（标点/大小写声明与训练数据）、[delayed-streams-modeling config-stt-en_fr-hf.toml](https://github.com/kyutai-labs/delayed-streams-modeling/blob/main/configs/config-stt-en_fr-hf.toml)、[sbintuitions/DuplexCascade server.py 与 README](https://github.com/sbintuitions/DuplexCascade)（Word 事件消费、0.6s micro-turn、`filter_period_for_tts`）。
- Voxtral Realtime：HF 模型卡、arXiv:2602.11298（架构/训练/服务与基准表，含 DSM 1B En-Fr 基线数字）、vLLM recipes 页。
- X2Streaming-ASR：GitHub README、arXiv:2609.08672、本项目 [x2streaming_replacement_assessment.md](x2streaming_replacement_assessment.md) 与 [x2streaming_asr_retest.md](x2streaming_asr_retest.md) §12。
- Qwen3-ASR：GitHub README（流式/离线统一评测表）、本项目现役栈记录。
