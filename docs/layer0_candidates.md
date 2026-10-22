# 状态 ASR 候选与标点依赖调研

更新：2026-10-22。依据用户提出的标点出现时序与转写回写问题补充调研。本次仅核查公开论文、模型卡、作者推理代码和本地客户端，未执行真实推理。

当前计划接入 X2-Turn 作为独立 ASR/用户状态前端，暂不实现 Layer 0。Layer 0 的系统 backchannel 时机预测和训练保留在后续总计划；本文候选不承担系统附和预测器职责。

## 1. 需要验证的问题

文本预测器可能利用句读判断完成状态；ASR 在何时补出句号、如何改写前缀，会改变控制器当时的判断。模型大小本身不能证明存在这种依赖，“影响非常大”仍需实验确定。

XTurnix 作者在[论文第 4.1 节](https://arxiv.org/html/2610.04400#S4.SS1)明确去掉训练前缀的末尾 Unicode 标点，模型卡也说明末尾标点预处理，因此不能断言其成绩只来自句末标点。但是，论文第 5.2 节的固定输入准确率不能证明其对不同 ASR 的增量时序、内部标点、回写及已经执行的错误动作稳健。

音频输入也不等于没有文本依赖。以下区分并行 ASR/状态头、音频与外部文本共同输入、先生成转写再生成状态、纯音频结束分类。原生状态、动作、类 ID 或概率均可由唯一仲裁器解释，不要求候选先生成 DuplexCascade 的 token。

## 2. 音频输入候选

| 候选 | 规模口径 | 输入与原生输出 | 流式与部署边界 |
| --- | --- | --- | --- |
| X2-Turn-4B-0812 | 约 4B 总模型 | 音频输入，ASR 与状态头共享隐藏表示；五个受监督状态为 idle、noidle、incomplete、complete、backchannel | 每 80ms 输出一帧；发布版本另提供未受训练监督的 uncertain 回退。论文评测的流式 delay 与帧间隔分别记录 |
| SoulX-Duplug-0.6B | 0.6B 语言主干，另计 GLM 语音 tokenizer、外部 ASR | 音频 token 与 ASR 文本交错输入，生成 user_idle、user_nonidle、user_backchannel、user_complete、user_incomplete | 160ms 目标块，40ms 右侧上下文须等实际到达；推理需要外部 ASR 文本，服务还会合并状态并执行规则 |
| Easy Turn | 约 0.85B；Whisper-Medium 编码器、adaptor、Qwen2.5-0.5B | 音频输入，先生成转写，再生成 COMPLETE、INCOMPLETE、BACKCHANNEL、WAIT 标签 | 原方案以分段语音推理；不能把整段结果当成逐块在线成绩。WAIT 指明确要求暂停/停止交互，不直接等同思考停顿 |
| Smart Turn v3.2 | 约 8M | 原始波形判断是否结束，不需要外部转写 | VAD 后运行，最多最近 8 秒；只提供结束对照，缺少完整附和/插话语义 |

### 2.1 X2-Turn：优先验证的联合流式方案

[作者论文](https://arxiv.org/html/2608.10878#S2.SS1)说明 ASR 头与状态头在同一次 forward 上并行预测，状态预测不回灌到 ASR 解码。因此无需等待外部 ASR 将一句文本和标点完整生成，适合作为本项目音频路线候选。

但共享隐藏表示仍读取此前 ASR token，不能宣称彻底消除文本、标点或 ASR 错误影响。[发布权重](https://huggingface.co/x-square-robot/X2-Turn-4B-0812)将论文的 incomplete/complete 显示为 speaking/turn_end，并另列 uncertain，需固定权重与运行代码版本。80ms 是帧间隔，模型卡的评测设置为 delay=480ms，不代表端到端动作只延迟 80ms。

[作者部署说明](https://github.com/X-Square-Robot/X2-Turn)要求本地演示 GPU 至少 24GB 显存；只加载 ASR/状态模块，不引入其 LLM/TTS 演示链路。首次预检单独占用一张现有预算内 GPU。若与本项目其余模型不能在原两卡预算内共存，报告资源限制，不自动加卡。

### 2.2 SoulX-Duplug：音频结合其他 ASR，且显式处理标点

[论文第 3.6 节](https://arxiv.org/html/2603.14877#S3.SS6)采用 SenseVoice Small 提供推理时的文本指导。[作者 README](https://github.com/Soul-AILab/SoulX-Duplug)当前建议中文 Paraformer、英文或双语 SenseVoice，不能把不同版本的默认配置混作同一次实验。

[service/model.py](https://github.com/Soul-AILab/SoulX-Duplug/blob/main/service/model.py)设置 `<|punctuation_off|>`，对当前及历史 ASR 文本调用 `zh_remove_punc` 后再规范化、求增量。它也有附和词处理、状态合并及等待回退，需分别记录原始模型 token 与服务最终状态，不能将规则收益全部归给模型。

[model/asr.py](https://github.com/Soul-AILab/SoulX-Duplug/blob/main/model/asr.py)中的 Paraformer 使用包含 vad/punc 的 ModelScope 模型包，SenseVoice 包装器对传入窗口调用识别。这里是滚动音频窗口辅助流式状态模型，不等于外部 ASR 本身使用严格追加的流式接口。去标点有明确代码证据，但其字符覆盖、标点尚未到达时的文本修订及稳定前缀仍须检查。

本地 X-Talk 已有 `models/turn_detector/soulx_duplug.py` 客户端，但客户端包含等待确认和回退策略；接入双工路径仍需保持唯一仲裁，不直接启用第二个控制管理器。

### 2.3 Easy Turn 与轻量声学对照

[Easy Turn 论文](https://arxiv.org/html/2509.23938#S3)和[作者实现](https://github.com/ASLP-lab/Easy-Turn)公开音频到转写与四类状态的模型及权重。它无需外部 ASR，但状态生成发生在自身转写之后，仍需核对训练句读和按前缀推理表现。优先用于分段模态对照，暂不承担首个连续流式控制实现。

[Smart Turn](https://github.com/pipecat-ai/smart-turn)可作为不接收外部文本的结束检测对照。此对照能帮助分析文本标点因素，但二分类模型不承担全部控制任务，不能直接与多类模型总准确率相比较。

## 3. 使用其他 ASR 的文本预测器

| 候选 | 已核实的 ASR 来源 | 输出和能力范围 | 证据边界 |
| --- | --- | --- | --- |
| Paraformer + TEN Turn Detection | Easy Turn 作者明确以 Paraformer 转写后测试 TEN | Qwen2.5-7B；finished、unfinished、wait | 是非 Qwen3-ASR 的明确评测组合；不是已证实的逐块回写鲁棒方案，也不原生检测用户附和 |
| FireRedASR + FireRedChat EoT | FireRedChat 论文的串联系统采用 FireRedASR，结束检测器读取累计转写 | mBERT 分类器，公开中英/中文 ONNX，输出语义结束概率 | 是独立文本结束检测器，未提供 XTurnix 式原生 start/stop 双状态控制；不能直接承担附和/插话判断 |
| 现有 Nemotron + XTurnix | 本项目拟用的流式 ASR 组合 | 原生 keep/start/stop | 属于待验证工程对照，不能写成作者已用该 ASR 评测 |

TEN 的非 Qwen3-ASR 组合依据 [Easy Turn 第 4.2 节](https://arxiv.org/html/2509.23938#S4.SS2)，规模与输出依据 [TEN 作者仓库](https://github.com/ten-framework/ten-turn-detection)。TEN 仍是文本模型，换用 Paraformer 不足以证明标点不敏感，也不是首选轻量部署方案。

FireRedChat 的模型与输入依据 [论文第 2.2.2、2.3.1 节](https://arxiv.org/html/2509.06502#S2.SS2.SSS2)及[公开模型卡](https://huggingface.co/FireRedTeam/FireRedChat-turn-detector)。模型卡的用例包含无标点文本，可在 CPU 用 ONNX 计算概率；这一例子不等于标点消融实验。其[ASR 服务](https://github.com/FireRedTeam/FireRedChat)包含标点恢复，仍需核查实际送入 EoT 的文本版本。原系统以 pVAD 暂停播放，不据此认定文本模型已经区分用户附和与真实打断。

## 4. 选用顺序与验证方法

当前先接入和验证 X2-Turn；SoulX-Duplug + SenseVoice、Smart Turn、XTurnix + Nemotron、FireRedChat EoT 和 TEN + Paraformer 保留为调研及必要对照，不再以全部候选比较作为当前前置条件。

X2-Turn 已作为计划采用的独立前端，当前尚未替换现役 ASR。转写与原生用户状态持续交给 Layer 1/统一仲裁器，单独记录其质量与时序，不能再称为 Layer 0 音频后端；Layer 0 留给后续系统附和预测。对照注明前端/控制的共同变化，不错误归因于附和模块。

### 4.1 标点影响与跨 ASR 影响分别测量

1. 固定当时已到达的同一词序列、历史和系统状态，对比原标点、仅去末尾标点、去全部标点、延后释放已到达标点。按冻结规则操作，只做文本敏感性诊断，不向正式模型补入未来标点或未来词。
2. 对同一音频前缀运行各自原生 ASR，保留真实返回时间、累计文本、修订范围和标点首次出现时间；分别比较识别错误、回写和文本到达时间。跨 ASR 结果不能全部归因于标点。
3. 同一已去标点词序列相同时，另比时间与暂停信号；文字相同不代表在线可用条件相同。记录没有新文字但出现标点修订的调用。
4. 音频模型只访问当时真实已到达的块；SoulX 的右侧上下文及 X2 的固定延迟均计入输入可用时刻。禁止先编码完整音频再切帧报告实时表现。

### 4.2 记录与评分

保留原生 token/类 ID/分数、模型原始输出、预处理后实际输入、观察与 ASR 版本、结果到达时间、状态首次变化、动作和已播前缀。报告标点干预导致的动作翻转率、结束检出时间变化、误接话、附和误停、真实打断漏停，以及超时/无输出覆盖。

每次对照重置会话或从相同快照重放，防止模型缓存污染。ASR 回写只影响后续判断；此前已执行的错误动作不能从统计或播放历史删除。模型状态原始结果和服务确认、等待回退、仲裁决策、实际停声分别记录，避免用最终文本的分类正确率代替在线控制正确率。

首轮使用与 FDB 隔离的独立开发事件检查输入、用户状态和阈值；冻结后按 [工程计划](engineering_implementation.md#6-fdb-对话音频测试计划)做 FDB 对话音频测试。原生状态直接解释，不因 token 名称或类别数不同启动训练。后续系统附和训练属于独立职责，不以 X2-Turn 是否通过用户状态验收为条件。
