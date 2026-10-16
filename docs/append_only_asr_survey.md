# 无回写流式 ASR 候选普查（含标点判据）

## 2026-10-16 本轮复核：以下结论取代旧排序

本轮用户明确要求“没有回写机制”，因此进一步区分原生连续发射与内部可修订、仅对外冻结前缀。**建议首轮测试 Nemotron 英语版、Nemotron 3.5 多语言版和 Kyutai 1B。** 后文原始普查保留作为调研记录，排序和排除理由以本节为准；后续服务器执行按 [选型测试任务单](asr_selection_benchmark.md)。本轮未下载权重或运行新推理。

| 优先级 | 模型 | 原生标点证据 | 延迟配置，非端到端实测 | 结论 |
| --- | --- | --- | --- | --- |
| 1 | `nvidia/nemotron-speech-streaming-en-0.6b` | 官方明确标点及大小写 | 80/160/560/1120ms chunk | 英文主场景第一候选 |
| 2 | `nvidia/nemotron-3.5-asr-streaming-0.6b` | 官方明确标点及大小写 | 80/160/320/560/1120ms chunk | 多语言对照候选 |
| 3 | `kyutai/stt-1b-en_fr` | 官方明确标点及大小写 | 约 500ms 文本流偏移 | DSM 结构参照候选 |
| 有条件 | Confucius4-R2T2 | 在线句末标点待验证 | 自报平均 200–600ms，口径不同 | 默认含未固定 token 回滚窗口，不直接满足严格条件 |

### 英语版 Nemotron 的补充证据

[官方模型卡](https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b) 明确：600M、Cache-aware FastConformer-RNNT、原生标点及大小写。需固定更新后的 checkpoint，避免混用 2026 年 1 月旧版本。官方去标点／大小写后的 WER 如下：

| chunk | 多数据集平均 WER | LibriSpeech test-clean | AMI |
| --- | --- | --- | --- |
| 80ms | 8.43% | 2.80% | 18.29% |
| 160ms | 7.67% | 2.56% | 14.71% |
| 560ms | 7.07% | 2.46% | 11.88% |
| 1120ms | 6.93% | 2.32% | 11.73% |

先测试 160ms 与 560ms，观察额外等待能否换取本项目准确率提升。英语版不支持中文，许可按 NVIDIA Open Model License 登记。RNNT 必须采用携带状态的连续贪心解码；beam search 的临时最优假设不天然保证稳定。原生结构可单调生成，也不等于服务实现已经通过零回写检查。

多语言版 [官方模型卡](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) 的 FLEURS 英文 LangID WER 在 160/560/1120ms 下分别为 8.88%/7.99%/7.91%。该表与英语版的多数据集平均不是同口径，不能直接横比。首轮固定英文语言条件；中文需要时单独测 CER。

### 对旧文的纠正

1. **R2T2 不能标为只有标点待验证。** [README](https://github.com/netease-youdao/Confucius4-R2T2) 在宣称稳定前缀只追加的同时，将 `UNFIXED_TOKEN_NUM=1` 定义为尾部 token 回滚窗口。对外不可回写与内部完全没有回滚是两种条件。严格按本轮需求暂不进入首轮；若后续接受未提交尾部可变，再核查实际提交接口和等待成本，不能直接用外层扣留 token 宣布满足条件。
2. **Kyutai 并非只能 Rust 集成。** [模型卡](https://huggingface.co/kyutai/stt-1b-en_fr) 还链接官方 [Transformers checkpoint](https://huggingface.co/kyutai/stt-1b-en_fr-trfs)。后续优先验证 Python 的真实流式输入路径，框架变体须分别固定版本；官方组合也不保证本项目接话效果。
3. **撤回通过 X2 推断 Voxtral 无标点的理由。** 微调后代无标点不能证明基座无标点。[Voxtral 模型卡](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602) 的标点契约尚待独立确认，因此状态是待验证，而非已证不满足。
4. **不再对整个 Zipformer/Paraformer 或云 API 家族作无标点／必回写断言。** 应按具体 checkpoint 和协议判断；本轮优先自部署、原生带标点候选。额外标点恢复器暂不进入首轮比较。
5. [Parakeet Realtime EOU 120M](https://huggingface.co/nvidia/parakeet_realtime_eou_120m-v1) 官方明确输出不含标点及大小写；其 EOU token 不能代替自然标点，也不能越过 Layer 1 强制让轮。
6. **标点出现率不代表正确率。** 需测误加／漏加句末标点和到达时间；整文件输入后 TextIteratorStreamer 只证明文本增量输出，不能直接用作真实流式延迟证据。

后续选择依据同数据、同硬件的 WER、实体错误、正确词及句末标点的 P50/P95 交付延迟。当前没有任何新候选已通过本项目服务器验收。

---

## 原始普查记录（旧排序已被上节取代）

调研日期：2026-10-16。本次只阅读官方模型卡、论文、README 与许可证原文，未下载权重、未执行推理、未改现有配置与代码。结论是候选排序与待验证清单，不是已通过本项目验收的结果。本文不改变 [engineering_implementation.md](engineering_implementation.md) 的任何实现边界。

**判据修订（2026-10-16）**：用户澄清从未要求 ASR 必须支持中文。中文由排除条件降级为加分项；准确率主口径改为英文（FDB 为现有验收主场景）。

## 1. 判据与项目语境

五条硬性判据，缺一不可：

1. **流式**：音频边到边识别，不等待整段文件；
2. **低延迟**：提交延迟与本项目 ASR 事件节奏可比；
3. **无回写**：已释放文本永不修订。这不是显示偏好，而是项目输出边界（已被用户听到的内容不可撤销），并与 X-Talk 适配器 `advance_committed` 的前缀单调检查兼容；
4. **准确率尚可**：以英文为主口径（FDB 答案是现有验收内容）；**中文不是硬性判据**（2026-10-16 用户澄清），现有中文日期/时间用例仅作加分验证；
5. **输出标点**：本轮新增硬性条件。本地实验已证明标点不只是排版问题：`x2streaming_asr_retest.md` §12.1 中样本 101 末段 ` steam on` 在补上句号后，控制模型下一拍即输出 finish-talking 并开始回答；§12.2 确认 X2 权重在线提交 1,022 条中含句读标点者为 0。

部署约束沿用现状：远端 4090（24GB）、独立 conda 环境、单一 ASR 服务、FDB 为英文主场景。

## 2. 结论摘要

| 排序 | 候选 | 流式 | 低延迟 | 无回写 | 准确率(en) | 标点 | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Confucius4-R2T2（网易有道） | ✓ | 200–600ms 均值 | ✓（尾部 1 token 回滚窗口需适配层扣留） | 接近离线 Qwen3-ASR（最优） | 待实测（基座输出标点，权重未声明） | 准确率最优、zh 加分；唯一缺口是标点待实测 |
| 2 | Nemotron 3.5 ASR streaming 0.6B | ✓ | chunk 80–1120ms 运行时可调 | ✓（RNNT 单调发射） | 中等（FLEURS en 7.91@1.12s；En-Long 偏弱 13.02） | ✓ 原生声明 | 五判据结构全中；极轻（600M）、集成最容易 |
| 3 | Kyutai stt-1b-en_fr（DSM，官方 DuplexCascade 同款） | ✓ | 固定 0.5s delay | ✓（逐词 `Word` 事件只追加） | 平庸（En-Short 12.26 / En-Long 13.83 WER）但为官方端到端验证过的组合 | ✓ 声明带大小写与标点 | 与控制模型训练分布天然对齐；集成成本最高（Rust/24kHz/msgpack） |
| 4 | Voxtral-Mini-4B-Realtime-2602 | ✓ | 240ms–2.4s 可配 | ✓（DSM 逐帧生成，服务端只发增量 delta） | FLEURS AVG 8.72%@480ms | 未声明；其微调 X2 实测无标点，先验为负 | 标点判据大概率不满足；作架构参考 |
| 备选 | X2Streaming-ASR-4B | ✓ | 32–109ms 均值 | ✓ | 强（en+zh） | **实测 0/1022 含标点** | 若标点判据可放宽仍是第一优先 |
| 现役 | Qwen3-ASR-1.7B | ✓ | — | **✗ 修订窗口→前缀冲突→可见文本冻结** | 强 | ✓ | 回写判据不满足 |

云 API（Deepgram、AssemblyAI、Soniox、Speechmatics、ElevenLabs、讯飞/腾讯/阿里/火山）作为类别整体排除：partial 结果在 final 前持续修订（R2T2 对照表中凡标 ※ 者即此类），只消费 final 可保单调但延迟上升，且引入外部网络、隐私与费用依赖，与远端集群自部署形态不匹配。

前三个候选在结构上都满足五判据（R2T2 的标点、全部三家的实测行为待验证）；差异在准确率、延迟可调性、集成成本与许可。

## 3. 候选一：Confucius4-R2T2

- 代码：[GitHub master README](https://github.com/netease-youdao/Confucius4-R2T2)（本文引用其评测表）；权重：[HF](https://huggingface.co/netease-youdao/Confucius4-R2T2) / [ModelScope](https://modelscope.cn/models/netease-youdao/Confucius4-R2T2)。基座为 `Qwen/Qwen3-ASR-1.7B`——**与当前栈同一基座**。
- 机制：在 Qwen3-ASR 上以稳定前缀数据、强制时间对齐数据、token 级音频分段训练"最长稳定前缀（LSP）"提交策略；只暴露稳定前缀，已提交文本不再变更。chunk 80ms–2s 可配，默认 160ms。
- 无回写的唯一偏差：`UNFIXED_TOKEN_NUM`（默认 1）是尾部未固定 token 的回滚窗口。适配层只对外发布"已固定前缀"、扣留最后 N 个未固定 token 即可对外保持严格单调；需核实其 `ws_server.py` 实际发送的增量是否已只含固定文本（见 §9 第 2 项）。
- 服务形态现成：WebSocket 端点 `/asr_stream_api_v1` 接收 16kHz int16 PCM，返回 JSON 增量 `text`（"newly recognized segment"，客户端拼接即全文），天然映射现有 ASR 事件与 micro-turn 组装；vLLM 后端；官方建议直接跑在 `qwenllm/qwen3-asr` Docker 镜像里（conda python 3.12 或 Docker，均符合本项目环境规则）；可选 FireRedVAD。
- 官方评测（160ms，en 为 WER%，zh 为 CER% 仅作加分参考）：LS-clean 2.13、AMI 11.37、Giga-clean 9.60、TED-LIUM 3.34、Earnings22 9.36；zh：Wenet-net 5.87、CN-RealSI 3.48。对照离线 Qwen3-ASR（en 1.67–9.25），流式退化约 0.5–2.7 点，为三候选中准确率最优。同表中"Qwen3-ASR base 160ms"列 CER/WER 高达 13–39%——即朴素分块流式 Qwen 的崩坏，独立佐证了当前栈冻结问题的根因。
- 标点：基座 Qwen3-ASR 输出句末标点（当前栈实测 `'I never like.'` 等），R2T2 在其上训练且 API 保留 `state.text` 全文；但 README 与演示均未显式声明标点恢复，**五判据中唯一未直接证实的一条，必须实测**（方法复用 X2 §12.2 的提交标点统计）。
- 许可：代码 Apache-2.0；权重为 [NetEase Model Use License](https://raw.githubusercontent.com/netease-youdao/Confucius4-R2T2/master/MODEL_LICENSE)：月活超 1 亿或年收入超 10 亿元需另行授权；不得用于改进其他商业 AI 模型；排除医疗诊断、自动驾驶、军事等高风险场景。本项目研究用途在其免费范围内，但该协议为非 OSI 许可证，须在来源登记中如实记录。
- 风险：tech report 尚未发布（"will be released soon"），方法细节暂不可复核；延迟口径为 chunk 级"retrospective fuzzy latency"均值 200–600ms，与 X2 的逐字符对齐提交等待（32–109ms）口径不同，不能直接横比。

## 4. 候选二：Nemotron 3.5 ASR streaming 0.6B

- [HF 模型卡](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)（2026-06-04 发布）：Cache-Aware FastConformer-RNNT 600M + 语言 ID prompt，40 个 locale。RNNT 贪心解码逐 token 单调发射，结构上无回写；**原生标点与大小写**（训练标签的标点由 Qwen3-32B 生成），模型卡 Output 一节明确"transcribe punctuation and capitalization"。
- 流式配置：`att_context_size=[56, r]`，r∈{0,1,3,6,13} 对应 chunk 80/160/320/560/1120ms，运行时可换、无需重训。Transformers ≥5.13 原生流式（`TextIteratorStreamer`，可直接嵌入现有 Python ASR 服务），另有 NeMo 脚本与 GGUF（NeMo-Speech.cpp，可 CPU）。600M 显存占用极小，可与其他服务共存单卡。
- 准确率（FLEURS，LangID）：en 7.91% WER@1.12s、9.43%@80ms；En-Long 偏弱（Voxtral 报告基线：560ms 14.29 / 1120ms 13.02）。纯英文场景另有 `nemotron-speech-streaming-en-0.6b`（LibriSpeech clean 2.32% WER，准确率更高）。zh-CN 属 broad-coverage（CER≈19–20%）——中文降级为加分项后不再构成排除，但若未来要中文仍不达标。
- 其他注意：第三方实测（Sam Witteveen）称流式模式下标点质量不稳定，须实测；`auto` 语言检测会在句末标点后附加 `<xx-XX>` 语言 tag，须在适配层用 `strip_lang_tags` 剥除，避免把 tag 当成文本流的一部分。许可 OpenMDW-1.1（可商用、需署名）。
- 定位：结构上五判据全中且集成成本最低（Transformers 原生流式 + 600M）；缺口是准确率中等、长音频偏弱、流式标点质量未经本项目实测。

## 5. 候选三：Kyutai stt-1b-en_fr（DSM，官方 DuplexCascade 同款 ASR）

官方仓库 `sbintuitions/DuplexCascade`（固定提交 `4289302`，本项目 Layer 1 权重的同源实现）的 ASR 不是 Qwen 系，而是 **Kyutai 的 delayed-streams-modeling 流式 STT**：

- 启动方式（README）：`moshi-server worker -p 31607 --config config-stt-en_fr-hf.toml`；
- 具体模型（该 toml）：`hf://kyutai/stt-1b-en_fr-candle`，约 1B 参数，Mimi 音频 tokenizer，12.5Hz 帧率，`asr_delay_in_tokens = 6`（约 0.5s 固定延迟），temperature 0；输入音频为 24kHz（官方 `server.py` 按 1920 样本/80ms 发送）；
- 协议（`server.py::stt_receiver_task`）：STT 经 WebSocket（msgpack）逐词推送 `{"type": "Word"}` 事件，服务端把词**只追加**进缓冲，每个 `overlap_window_s`（默认 0.6s）拼一次增量文本作为 user micro-turn，无词时发 `<|no voice|>`——与本项目 A2/A3 对齐的官方推理实现一致；
- 无回写：DSM 流同步架构逐帧生成文本 token，词一经发出即成为后续条件；协议层 `Word` 事件只追加、从不修订。Voxtral Realtime（候选四）即该架构的商业后继（同一第一作者）；
- **标点：[模型卡](https://huggingface.co/kyutai/stt-1b-en_fr)明确声明 "The model produces transcripts with capitalization and punctuation"**——预训练用 whisper-timestamped 合成带标点转写（250 万小时公开音频），微调用 Fisher 2000 小时英语 + 1000 小时英语/600 小时法语专有真实转写；权重 CC-BY-4.0；另有 `stt-2.6b-en`（仅英语，2.5s delay，准确率更高但无标点声明、延迟翻五倍）；
- 准确率：平庸（Voxtral Realtime 技术报告实测 DSM 1B En-Fr@500ms：En-Short 12.26% / En-Long 13.83% WER）。

对本项目的三个直接推论：

1. **与 Layer 1 控制模型分布天然对齐**：DuplexCascade 官方就是用这款 ASR 训练/评测的——user micro-turn 带标点与大小写正是控制模型见过的分布，换用它是三候选中唯一不需要论证文本分布兼容性的选项（官方 FDB 结果即该组合的端到端证据）。
2. **"流式 + 无回写 + 输出标点"的组合并非新需求**——官方参照系从 2025 年起就是这种配置。任何替换 ASR 都应保持该文本分布；X2 的无标点小写输出相对官方管线属于分布外输入，这与 [x2streaming_asr_retest.md](x2streaming_asr_retest.md) §12.1 中"句号对固定文本轨迹有效"的观察方向一致（该实验同时声明不能未经验证归因于无标点，结论仍以 §9 实测为准）。
3. 官方 `server.py::filter_period_for_tts` 把 assistant 文本中的句号删去再送 TTS、仅保留给前端显示——官方管线自身就存在"文本带标点、TTS 不要标点"的不对称处理；后续替换 ASR/TTS 时不应把这类过滤误当成回写机制，它是单向的、不修改已释放文本。

- 集成成本：Rust `moshi-server`（msgpack WebSocket、24kHz PCM），与现有 Python HTTP ASR 服务形态差异最大；需重采样与协议适配。

## 6. 候选四：Voxtral-Mini-4B-Realtime-2602

- [HF 模型卡](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602)、[技术报告 arXiv:2602.11298](https://arxiv.org/abs/2602.11298)。Apache-2.0，4.4B（0.97B 因果音频编码器 + 3.4B Ministral 解码器）。DSM 流同步架构：每 80ms 帧解码一步，`[P]` 等待、`[W]` 起词；已生成文本 token 立即成为后续解码条件，模型内无修订机制；vLLM Realtime API 只回 `response.audio_transcript.delta` 增量，服务层同样追加式。
- 延迟由 AdaRMS-Norm 条件化，240ms–2.4s 可配（推荐 480ms）。FLEURS AVG 8.72%@480ms（13 语含 zh 15.74%）。
- 标点：模型卡未声明；HF 讨论区存在 "punctuation marks" 提问；其微调 X2 在线实测 0/1022 条含标点——**先验为负**。若无本地直接实测推翻，按不满足判据处理。
- 定位：Kyutai DSM 的商业后继与 X2 的基座；若未来自训标点版流式模型，它是合理的起点，当前不作为部署候选。

## 7. 已排除项与证据

- **X2Streaming-ASR-4B**：无回写、低延迟、中英准确率强（AISHELL-1 1.53/32ms 等），但 [x2streaming_asr_retest.md](x2streaming_asr_retest.md) §12.2 已证当前权重在线输出无标点（1,022 条提交含标点 0 条，词表允许但权重未学会）。不满足第 5 条判据；若该判据放宽，它仍是延迟最优解。无标点对控制模型等待行为的影响（§12.1）因果尚未完全定案，记录在案。
- **Qwen3-ASR-1.7B（现役）**：输出标点、流式可用（官方表：流式 WER 均值 3.33 vs 离线 2.69），但流式采用修订窗口（R2T2 表中标 ※ 的伪流式类），本地已观测前缀冲突导致可见文本冻结 26.3s/330 拍（[xtalk_a4_remote_acceptance.md](xtalk_a4_remote_acceptance.md) §7.6、[fdb_latency_diagnosis.md](fdb_latency_diagnosis.md)）。
- **Zipformer / X-ASR / Paraformer 流式（sherpa-onnx 路线）**：transducer/BPE 输出不含标点，判据 5 不满足；补 CT-Transformer 后处理器则引入额外组件与延迟，超出当前 MVP 边界。X2 表中该类 zh CER 7.9–11.3、延迟 400–600ms，无速度优势。
- **云 API 类**：见 §2。仅消费 final 可换取单调，但延迟与部署形态不匹配，列为类别性排除，不再逐家展开。

## 8. 口径声明

- 延迟口径互不可比：X2 为强制对齐字符/词声学终点→提交的等待（32–109ms）；R2T2 为 chunk 级"retrospective fuzzy latency"（200–600ms）；Nemotron/Voxtral 为 chunk/delay 设置加托管 TTFS（Together 宣称 sub-100ms，Soniox 实测中位 236ms）；Kyutai 为固定 0.5s 文本流偏移。不得拼成一张无条件性能表。
- 准确率数据集不同：AISHELL/WenetSpeech/LibriSpeech（X2、R2T2）与 FLEURS/Meanwhile/Earnings（Nemotron、Voxtral、Kyutai）不可直接横比。
- 所有厂商自报数字均未经本项目远端复测；R2T2 的方法细节（tech report）未发布前，其机制描述只能按 README 采信。

## 9. 建议的下一步（最小决策实验）

优先级从高到低，全部使用独立 conda 环境（Nemotron/Kyutai 无需新镜像；R2T2 可用 `qwenllm/qwen3-asr` 镜像），远端执行按 AGENTS 规则另出任务单：

1. **R2T2 标点实测**（门禁项）：英文不少于 25 条（含句末陈述/疑问句），流式 160ms 与 560ms 两档，统计在线增量提交中标点出现率、位置、大小写保留与句末标点到达延迟，对照 §5 官方管线的文本分布；方法复用 X2 §12.2。中文用例作加分验证。若标点缺失，R2T2 降级与 X2 同级，Nemotron 升为第一优先。
2. **Nemotron 流式标点/准确率冒烟**（低成本，可与第 1 项并行）：Transformers 原生流式跑 FDB 英文样本，同样统计标点、大小写与 WER；含长音频样本（其已知弱点）。
3. **unfixed token 语义核实**（仅 R2T2）：读 `ws_server.py` 与 `R2T2ASRModel.streaming_transcribe` 源码，确认对外增量是否只含已固定文本；若含未固定尾部，适配层扣留最后 `UNFIXED_TOKEN_NUM` 个 token，并保证对外零回退。
4. **延迟实测**：音频输入时刻→客户端增量到达的 P50/P95，不能只记录 `asr_cost_ms`；统一在 FDB 英文样本上测三家，同口径横比。
5. **A/B 对照**：A=现役 Qwen 栈（保留已知冻结缺陷为基线），B=通过门禁的候选替换 ASR 单组件（沿用 [x2streaming_replacement_assessment.md](x2streaming_replacement_assessment.md) §4 的单组件替换纪律）；跑既有 link 顺序/插话检查与 FDB 四轴，记录可见文本回退次数（必须为 0）、冻结时长、WER、日期时间实体错误、显存与长会话表现。
6. 通过后再测组合（如替换 ASR + 现役 MOSS），不提前扩大范围。Kyutai DSM 若前两名均未过门禁，再作为分布对齐兜底启动（集成成本最高，含 24kHz 重采样与 msgpack 适配）。

## 10. 来源清单

- Confucius4-R2T2：GitHub master README、HF/ModelScope 模型卡、MODEL_LICENSE（NetEase Model Use License Agreement 原文）。
- Nemotron 3.5 ASR：HF 模型卡（含 FLEURS 全表、标点声明与 att_context_size 说明）、[Baseten 发布文](https://www.baseten.co/blog/introducing-nvidia-nemotron-35-asr-streaming)、Together AI 模型页、HF 官方微调博客、`nemotron-speech-streaming-en-0.6b` 模型页。
- Kyutai DSM STT：[kyutai/stt-1b-en_fr 模型卡](https://huggingface.co/kyutai/stt-1b-en_fr)（标点/大小写声明与训练数据）、[delayed-streams-modeling config-stt-en_fr-hf.toml](https://github.com/kyutai-labs/delayed-streams-modeling/blob/main/configs/config-stt-en_fr-hf.toml)、[sbintuitions/DuplexCascade server.py 与 README](https://github.com/sbintuitions/DuplexCascade)（Word 事件消费、0.6s micro-turn、`filter_period_for_tts`）。
- Voxtral Realtime：HF 模型卡、arXiv:2602.11298（架构/训练/服务与基准表，含 DSM 1B En-Fr 基线数字）、vLLM recipes 页。
- X2Streaming-ASR：GitHub README、arXiv:2609.08672、本项目 [x2streaming_replacement_assessment.md](x2streaming_replacement_assessment.md) 与 [x2streaming_asr_retest.md](x2streaming_asr_retest.md) §12。
- Qwen3-ASR：GitHub README（流式/离线统一评测表）、本项目现役栈记录。
