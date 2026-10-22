# X2-Turn 在 FDB 上的独立质量测试计划

更新：2026-10-22。状态：调研与实现计划完成，尚未部署、编写评测实现或提交远端作业。文件名沿用本次用户指定的 `qualtity_test_on_fdb.md`。

## 1. 本轮目标与范围

在远端服务器部署冻结版本的 X2-Turn，以 FDB 用户音频作实时流式输入，回答两个问题：转写是否准确、用户说完后多久得到末端文本；用户状态 token 在各位置是否符合参考标注。先独立评测前端，再决定后续接入。此顺序细化了 [工程计划](../../engineering_implementation.md)，不改变 [研究方案](../../research_design.md#7-系统工程架构) 的模块职责。

本轮不运行回答 LLM、TTS 或产品控制仲裁，不训练模型，不实现 Layer 0 系统附和，不做官方 FDB 全链路能力复现。这里的“控制 token”特指 X2-Turn 用户状态；Judger 是离线评测工具，没有播放、停止或接管用户话轮的权限。既有 FDB 内容评分仍保持暂缓，不因新增状态 Judger 自动重启。

主配置为英语、`x-square-robot/X2-Turn-4B-0812`、目标流式延迟 `tau_ms=480`、80 ms 输入块、batch=1、单会话。先完成这一轮，不默认增加 320/400 ms 消融或中文数据。正式测试前冻结阈值、归一化、参考标签和容差；FDB 不用于调参。

## 2. 已核查的实现机制

本次源码调研固定 X2-Turn 提交 `67ec3fe49f1977ee3129f7eaed603c04d8ed23c5`，论文为 arXiv v3。远端安装时优先复现此提交；必须变更时先更新本计划和锁定清单，不能悄悄跟随 main。

### 2.1 ASR 和状态头

模型共享流式声学与解码表示，ASR head 驱动自回归，turn head 并行给出状态，不将状态反馈到 ASR 解码。目标序列以 80 ms 为一格，每个词先放 `[W]`，再放该词的子词 token。`[W]` 的目标位置为 `round(word_start / 0.08) + tau_ms / 80`，相同位置赋予该词的话轮状态，其余目标位置为 idle。[论文第 2.1—2.3 节](https://arxiv.org/html/2608.10878v3#S2)

论文监督五种状态；发布源码暴露六个槽位：

| 论文标签 | 发布标签 | ID | 本轮解释 |
| --- | --- | ---: | --- |
| idle | idle | 35 | 目标流中的空白位置，不能单凭它认定话轮结束 |
| noidle | noidle | 36 | 已有语音、尚无充分语义 |
| incomplete | speaking | 37 | 有语义但表达尚未完整 |
| complete | turn_end | 38 | 当前语义完整，仍不是无条件接话命令 |
| backchannel | backchannel | 39 | 用户的附和或相关填充表达，按上下文判断 |
| 无训练监督类别 | uncertain | 40 | 发布推理可输出的额外类别，单独统计 |

发布的 `turn_preds_from_hidden` 对六个槽位计算 softmax 后取 argmax；不能把 uncertain 擅自改解释为本项目新增的置信度阈值。五类主评分保留 uncertain 预测列，预测 uncertain 在确定金标处计未命中，不删帧。[发布实现](https://github.com/X-Square-Robot/X2-Turn/blob/67ec3fe49f1977ee3129f7eaed603c04d8ed23c5/voxtral-realtime/integrations/vllm/vllm/model_executor/models/voxtral_mtp_utils.py)

### 2.2 选择真正可测时间的推理路径

采用带作者 MTP overlay 的 vLLM `/v1/realtime`。上游固定 vLLM 0.19.1、提交 `b1388b1fbf5aaef47937fabe98931211684666a6`；普通 vLLM 不输出 `turn.delta`。权重按作者工具导出，确认含 `vad_lm_head.weight`，记录源权重 revision、导出配置、各文件哈希。缺少转换所需的 `params.json` / `tekken.json` 时，只取得必要的基座配置文件，不默认另下载一套基座权重。[overlay 与导出说明](https://github.com/X-Square-Robot/X2-Turn/blob/67ec3fe49f1977ee3129f7eaed603c04d8ed23c5/voxtral-realtime/integrations/vllm/README.md)

逐条保存 `transcription.delta`、`turn.delta`、`transcription.done` 和错误事件。当前协议中状态事件含 `frame_index`、类别 ID 和六类概率，ASR 事件不直接携带原始 token ID。overlay 按生成输出先发文本再发状态，但 `frame_index` 是输出迭代计数；必须验证单次迭代是否恰好对应一个 80 ms token，不能直接假设 `frame_index * 80 ms` 就是词的源时间。[协议补丁](https://github.com/X-Square-Robot/X2-Turn/blob/67ec3fe49f1977ee3129f7eaed603c04d8ed23c5/voxtral-realtime/patches/vllm-voxtral-mtp.patch)

两种现成演示入口不能用来直接报告本轮实时延迟：

- Transformers `infer_asr_turn` 先生成转写，再用完整生成序列做第二遍状态前向计算，只用于短片段标签/转换一致性诊断。[实现](https://github.com/X-Square-Robot/X2-Turn/blob/67ec3fe49f1977ee3129f7eaed603c04d8ed23c5/voxtral-realtime/src/voxtral_realtime/transformers/inference.py)
- vLLM 文件演示 `stream_wav_to_vllm` 循环一次性上传文件，不能用接收耗时代替真实音频到达延迟。客户端的 `delay_ms` 还可能只参与结果包装，正式启动必须读取服务端有效 delay 配置，确认实际为 6 帧，不能只把报告字段写成 480。[实现](https://github.com/X-Square-Robot/X2-Turn/blob/67ec3fe49f1977ee3129f7eaed603c04d8ed23c5/turn-demo/demo_turn/engine_vllm.py)

主实验绕开演示客户端的开头能量门和 idle 文本抑制，完整送入原始音频并保存原始文本；不运行 `FrameTurnController`。否则裁剪静音、丢弃文本或控制器的 silence_end 都会改变评测对象。此选择测量原始前端，不代表上游演示默认部署效果。[客户端门控](https://github.com/X-Square-Robot/X2-Turn/blob/67ec3fe49f1977ee3129f7eaed603c04d8ed23c5/voxtral-realtime/src/voxtral_realtime/realtime.py)、[控制器](https://github.com/X-Square-Robot/X2-Turn/blob/67ec3fe49f1977ee3129f7eaed603c04d8ed23c5/voxtral-realtime/src/voxtral_realtime/turn/controller.py)

## 3. FDB 输入、参考文本与覆盖范围

首轮沿用项目现有 FDB v1.0 四项，共预期 672 例。官方仓库固定 `3e799c45a045256f47d5f1c9cda90157e2d2ec9e`，数据哈希另行冻结；仓库提交不等于音频版本。

| 子集 | 预期例数 | 主要诊断 |
| --- | ---: | --- |
| candor_pause_handling | 216 | 自然停顿、句中语义状态 |
| synthetic_pause_handling | 137 | 受控停顿、未完成表达 |
| candor_turn_taking | 119 | 语义完整、末端转写 |
| synthetic_user_interruption | 200 | 打断语音的转写与状态，不能单凭状态证明系统已停播 |

用户 backchannel 在这些子集中可能缺少足够正例。因此另列 v1.5 `user_backchannel` 的 99 个场景作为状态覆盖补充；如远端数据缺失则明确列为待补齐，不能以未测冒充正确。clean / overlap 共预期 198 次输入，但仍是 99 个场景，分别汇总并给出成对变化。不自动加入 v1.5 其余三类或 v1.0 ICC 系统附和任务。

官方文件说明中，v1.0 的 `transcription.json` 仅“若可用”；v1.5 的 `current_turn_text` 仅指焦点用户话轮，`timestamps` 是重叠窗口，都不能默认当作整段参考转写或用户发声末端。[FDB 数据说明](https://github.com/DanielLin94144/Full-Duplex-Bench/blob/3e799c45a045256f47d5f1c9cda90157e2d2ec9e/v1_v1.5/dataset/README.md)

实施时先生成只读 manifest：样本 ID、子集、输入变体、路径/哈希、采样率、声道、时长、参考文本及来源、用户语音段、最后目标用户发声末端、标注可用性。检查标注对应哪条音轨、是否覆盖整段输入，不能把旧系统的 `output.json` 用作用户金标。

参考构建规则：

1. 优先复用并核验原始转写；音频与文本不一致时按音频修订，保留原文与版本。没有可靠文本时，用独立 ASR 生成草稿，再人工听审；未经听审的草稿只能记作伪参考，不能混入正式 WER。
2. 对核验文本做强制对齐，得到词级起止与用户语音段。句尾、低音量词、填充词和重叠处必须听审；VAD 只提供边界候选。真实发声结束点不是文件末尾、静音检测确认点或 FDB 场景事件时间。
3. 声道不可直接平均；先确认每声道来源。单声道混入竞争说话人且无法可靠分离时，分别标识用户目标文本与可听混合文本，无法确定的片段不强造唯一参考。
4. 保留整段连续输入，不按隐藏语义事件裁剪、重置模型或通知结束。整段 WER 使用完整参考；仅有片段参考时只评对应可定位片段，单列覆盖，不能拿局部文本比较整段输出。
5. 句中停顿后的续说仍属于连续测试。末端延迟主指标每条输入只取最后一次目标用户发声结束，内部各段末端保留诊断，不用自然静音误切话轮。

原始文件不复制大批音频；重采样采用固定工具/参数、保持时长与静音，按需流式转换到 16 kHz、单声道 PCM16。所有参考与时间标注只供离线评分，不进入 X2-Turn 会话。

## 4. 实时回放与记录

模型加载、连接及独立开发音频预热完成后才开始计时。每条输入新建会话，缓存不跨样本；clean / overlap 独立运行。客户端与服务端在同一计算节点，通过 localhost 通信。

以客户端 monotonic 时钟设 `t0`，将源音频区间 `[a,b]` 的输入块安排在 `t0+b` 可用后发送，默认每块 80 ms。发送与接收使用独立异步循环，不等状态事件才发送下一块，也不把未来音频提前排入服务。记录计划/实际发送时刻、累计送入样本数、队列积压与接收时刻。迟到不通过批量提前发送未来块“补齐”；明显积压时保留实际延迟并标识资源跟不上实时。

原音频后继续按相同节奏发送 5 秒零音频作为固定观察尾窗。若原音频本身有长尾静音，该静音仍正常送入，计时锚点保持真实用户末端。尾窗结束后再发 `final=true`，另给最长 60 秒协议排空超时；EOF 不能在隐藏的用户结束点提前发出。自动补齐的服务端帧和客户端尾窗必须分别标识。

基础记录包含：`run_id/sample_id/event_seq`、原始事件、客户端 monotonic 到达时间、输入截止点、服务端帧号、原始/累计转写、文本版本、原生状态与概率、有效 delay、异常与退出码。`[t0, audio_end, tail_end, final_commit, done]` 分开记录。

协议预检必须确认文本 delta 与状态输出的对应关系、空 delta 是否占帧、帧号起点、启动前缀、EOF 补齐与生成批量大小。若现有事件不能可靠定位，给上游 overlay 增加最小的只读诊断字段：ASR token ID、生成步序号、消耗的源样本截止点。补丁单独保存与哈希，不修改 logits、选词或状态策略。未验证帧映射时仍可记录真实文本延迟，但不得声称完成严格逐帧状态评测。

## 5. 转写 WER

主指标为语料级 `WER = (S + D + I) / N_ref`，同步报替换、删除、插入总数及各子集结果。逐样本 WER 均值另列，不与语料级结果混称。

冻结 `TextNormalizer`：Unicode 规范化、英文大小写统一、标点与空白处理一致；不删除填充词，不擅自改写数字或实体，缩写/撇号规则固定并记录版本。特殊标记不算可读文本，同时保存原始输出以便追查。若有中文则另报 CER，不与英文 WER 混合。

正式文本取观察尾窗结束、EOF 前已收到的累计转写；EOF 后补出的转写单独给出 `wer_after_flush` 与变化，不覆盖主结果。解码成功但空转写且参考非空时计删除；传输失败、超时或不可判参考列入失败/缺标统计，不能悄悄丢出总体样本数。参考为空时 WER 为 null，另报幻觉词数。所有缺标的正式指标必须同时显示 `eligible / total`。

## 6. 用户说完到转写结束的延迟

### 6.1 主口径：末端文本最后更新时间

设 `e_user` 为离线确认的最后目标用户发声结束时刻，`T_user_end = t0 + e_user`。观察到固定尾窗结束，取 EOF 前累计转写最后一次发生词汇内容变化的接收时刻 `T_last_lexical_change`：

`tail_text_latency_ms = 1000 * (T_last_lexical_change - T_user_end)`。

这是事后观察“文本何时最后变化”，不声称模型当时已经知道用户说完了。末尾标点或纯空白变化单独记录，不延后词汇主指标；迟到的幻觉文字仍算变化，不能为了好看手工剔除。保留原始负值，不截为零。

平均值按每条有效输入一个观测取算术平均，同时报 P50/P90/P95、最大值、有效数和负值数；各子集、原始/clean/overlap 分开。主汇总只含自然流式观察内完成且有可靠用户末端的样本。

### 6.2 防止“漏了句尾所以很快”

每条延迟必须关联 WER、末词是否识别、最后最多 3 个参考词的恢复比例及输出覆盖。最后一次文本更新可能属于前半句，不能据此认定末端已正确完成。报告全部可观察延迟，并另报末词正确覆盖样本的条件均值及其分母；高删除率样本不从 WER 和失败覆盖中消失。整段空转写或完全未覆盖末端时，完成延迟记 null，原始最后更新时刻仍可保留作诊断。

参考末词和输出的匹配只在离线评分进行，不用于让服务端提前停止。停顿、重复词和并发说话造成匹配不唯一时标记不确定，不随意选一个更快时间。

### 6.3 与 final 信号分开

另报 `done_latency_ms = 1000 * (T_transcription_done - T_user_end)`、EOF 到 done 的排空时长、EOF 后文本新增量。`transcription.done` 可能依赖客户端 EOF，不能作为自然流式末端延迟的替代。

尾窗截止时仍未恢复末端文本、只在 EOF 后补出末端、尾窗边缘仍有新增文字或服务超时，分别标识 `missing_tail / eof_dependent / boundary_unresolved / timeout`；不把固定 5 秒尾窗当作其真实完成延迟。报告这些样本数与观察上界。延迟只能和正确性、覆盖率一起解读，不设置为了通过验收而删掉慢样本的规则。

## 7. Judger：构建参考状态而非评价自身输出

### 7.1 标注来源与职责

FDB 任务标签可以定位停顿、接话或用户附和场景，但没有与 X2-Turn 完全对应的逐 80 ms 五类金标。实现独立 `ReferenceStateJudger`，由核验参考文本、强制对齐、用户音频前缀与可用历史构造标签；不得把待测 X2-Turn 转写、预测状态、概率或控制器结果作为参考依据。

声学边界由对齐/VAD 候选和人工复核提供；语义判断使用独立模型辅助标注，冻结实际模型快照/端点返回模型名、prompt、采样参数、请求/响应摘要、标签版本和缓存键。Judger 调用失败独立记账。模型未选定前不捏造已冻结版本；先在非 FDB 开发材料完成试标，再冻结配置。

按新增参考词或语义边界调用 Judger，再按时间投影，不对每个重复 80 ms 帧重新发请求。相同前缀结果缓存；每次请求只含该截止点已知历史，不能为省调用把未来词一并给模型。完整录音可以用于转写核验与对齐定位，但未来续说、焦点场景名称和 FDB 隐藏标签不能用于倒推“当时必然未结束”。

### 7.2 两条时间轴，分别评分

**主评分：与模型训练一致的目标流状态。** Judger 为参考词给出语义标签，`FrameTargetProjector` 用同版本 tokenizer、词起点、`tau_ms`、`[W]` 与子词占位重建目标流，把词标签复制到这些位置，其余位置为 idle。它评估“是否匹配既定的 ASR 锚定标签”，不是物理时刻每一帧的瞬时 VAD 真值。[监督方法](https://arxiv.org/html/2608.10878v3#S2.SS3)

生成过程中必须核查词切分、80 ms 取整、启动前缀及相邻词 token 占位冲突。公开描述不足以唯一确定的碰撞处理，不擅自声称复现作者训练标签；优先核查可用实现/样例，仍不明确的区间标为不可判，报告 mask 与覆盖率。不能把后一个词覆盖前一个词后继续当金标。

**补充诊断：真实到达时刻的因果状态。** 按预测实际到达的时刻，Judger 只看当时已到达音频对应的参考前缀和已知历史，输出允许状态集合。此结果诊断决策是否及时，不与上述训练目标匹配率混成一个 accuracy，也不通过事后移动预测时间让结果更好看。

按完整参考词生成的训练式标签可能使用其尚未播完的部分，因此只属于目标流参考；在因果诊断中，如果截至当时尚不能辨认该词，就应保留 noidle 或不可判，而不是泄露整词文字。必须在报告中区分两者。

### 7.3 判定准则与不确定性

- idle：目标流中未占用的位置；在因果诊断中表示此刻无目标用户语音。静音不等于用户让出话轮。
- noidle：只有声学活动或不可辨前缀，还不足以支持语义判断。无法可靠细标的边界进入人工复核或 mask，不能用固定“每句前 160 ms”伪造。
- speaking：基于当前可见内容仍有未完成结构或信息依赖，表达尚在继续。
- turn_end：当前已有可独立理解的完整表达；不能因为未来用户又补充一句，就反向把此前全部改成 speaking。
- backchannel：结合此前对话判断是用户附和或相关填充表达；不能只凭“yes/okay/um”词表或时长判定，更不能把它当系统应发附和。

每条标注保存 `label/allowed_labels`、证据截止点、理由、来源、是否人工确认。存在多个合理判断时保留允许集合；无法判断时标记 `unjudgeable`，它不是模型的 uncertain 类。主严格准确率用确定的单标签位置，集合匹配率另报，二者都必须报告占总时长和语音时长的比例。

### 7.4 人工核验与成本

先在独立开发材料上检验规则与提示词。正式 FDB 标注先做每个子集至少 5 场景的质量抽查，再按类别分层抽检不少于 150 个非重复语义边界，包含所有可取得的稀有类别；低置信、重叠、标注冲突单独复核。冻结盲审样本，检查 Judger 与人工一致率、各类分歧和审核人信息；人工资源不足时只报告“自动参考匹配率”，不能称为人工金标准确率。

评分期间不依据 X2-Turn 哪些地方预测错了来修改参考。确需修正金标时生成新版本，对全部结果一致重算。调用预算初始上限为并发 1、20,000 次请求、输入输出合计 5M token、单请求 60 秒；按 manifest 估算后写入作业锁定清单。预算不足时保存进度，公开未标注覆盖，不自动增加费用或跳过难例后声称全量完成。

## 8. 状态匹配指标

先用协议预检确定的映射将输出定位到目标网格，保留原始接收时间；不使用动态时间规整将迟到输出挪到正确位置。Judger 目标流由参考文本构造，不跟随待测 ASR 结果变化。

| 指标 | 统计方式与用途 |
| --- | --- |
| 严格逐帧 accuracy | 确定单标签目标位置的精确匹配率，默认 80 ms 网格 |
| 类别 precision/recall/F1、macro-F1 | 五类逐项报告，避免长静音主导总体；uncertain 和缺失输出作为额外预测列 |
| 混淆矩阵 | 5 个确定参考类 × 6 类预测及 missing，附每类样本/时长 |
| 非 idle 与语义位置结果 | 单列参考非 idle、词占位和语义判断位置，保留 idle 误报 |
| 集合匹配与覆盖 | 允许标签集合中的命中率、确定/歧义/不可判的比例 |
| 事件 precision/recall/F1 | 相邻同类帧合并成事件，turn_end/backchannel 按类别、一对一匹配；每个参考事件最多匹配一次 |
| 事件提前/滞后、漏检/重复 | 相对参考事件的带符号偏移，另外使用实际到达时间报告在线可用性 |

严格帧匹配不设事后漂移；边界容差诊断和事件匹配初始采用 ±160 ms，必须在独立开发阶段确认并于正式回放前冻结。容差结果不能替代严格结果。前缀填充及诊断尾窗不混入主 accuracy，原音频内部静音照常评估。主输出缺帧、重复帧、乱序、空概率和未知 ID 分别计数；缺帧在确定金标位置计未命中，不默认为 idle。

按子集、语音/静音、确定/歧义、clean/overlap 分层汇总，不将相关帧当独立样本计算置信区间；需要区间时按原场景分组 bootstrap。长连续 speaking 段拆出的若干帧不算若干独立事件。

不报告本轮未执行的 Pause TOR、系统停声延迟或回答质量，也不将这里的逐帧指标与论文 EasyTurn“最后一个非 idle 状态”的话语级准确率直接比较。

## 9. 拟实现文件、类与核心方法

本次只交付计划；下列实现及镜像说明在对应工作单启动时创建，避免空壳文件。运行输出放远端，源码注释与文件名用英文，文档用中文。

| 实现文件 | 对应说明 | 主要职责、类与核心方法 |
| --- | --- | --- |
| `scripts/remote/x2_turn_fdb_data.py` | `docs/scripts/remote/x2_turn_fdb_data.md` | `FDBManifestBuilder.inspect/freeze`；`ReferenceBuilder.import_transcript/align/export`，核验输入、参考和边界 |
| `scripts/runtime/x2_turn_stream.py` | `docs/scripts/runtime/x2_turn_stream.md` | `X2TurnStream.connect/send_audio/receive_events/finish/close`，原始协议适配，不加控制策略 |
| `scripts/remote/x2_turn_fdb_replay.py` | `docs/scripts/remote/x2_turn_fdb_replay.md` | `RealtimeReplay.run_sample/run_manifest`、`TraceRecorder.record`，实时节奏、尾窗、逐事件时戳和失败记录 |
| `scripts/remote/x2_turn_fdb_judger.py` | `docs/scripts/remote/x2_turn_fdb_judger.md` | `ReferenceStateJudger.judge_prefix/review/export`；`FrameTargetProjector.project`，前缀标注与目标时间投影 |
| `scripts/remote/x2_turn_fdb_score.py` | `docs/scripts/remote/x2_turn_fdb_score.md` | `TextNormalizer.normalize`、`ASRScorer.score_wer/score_tail_latency`、`TurnStateScorer.score_frames/score_events`，独立可重算评分 |
| `scripts/remote/run_x2_turn_fdb_job.sh` | `docs/scripts/remote/run_x2_turn_fdb_job.md` | 预检、部署/回放/评分阶段调度、资源监控及退出清理；不包含产品控制器 |
| `configs/x2_turn_fdb_quality.json` | `docs/configs/x2_turn_fdb_quality.md` | 模型/源码版本、有效 delay、节奏、尾窗、归一化、Judger、资源与路径合同 |
| `tests/test_x2_turn_fdb_quality.py` | `docs/tests/test_x2_turn_fdb_quality.md` | 确认时钟/EOF 不混淆、无未来输入、投影冲突、缺帧、事件一对一匹配和漏末词处理 |

协议字段不足时的上游诊断补丁放 `patches/x2_turn_realtime_trace.patch`，说明为 `docs/patches/x2_turn_realtime_trace.md`；记录所基于的上游提交和行为一致性检查。不上升为运行时新架构。

远端每个 `run_id` 产生配置锁、环境锁、输入 manifest、参考版本、原始 trace、逐样本评分、总体汇总、失败列表、资源峰值和进程退出码。Git 仅收脚本、文档、必要补丁和中文简明报告 `reports/x2_turn_fdb_quality.md`，大 trace/音频/凭据不入库。报告链接具体远端产物与哈希，不以单一平均数代替全量覆盖说明。

## 10. 远端部署与资源约束

沿用 [远端目录约定](../../remote_workspace.md)：根目录 `/hpc_stor03/sjtu_home/xuan.zhang`，现有 `InterClarify/benchmark/fdb_v1_0` 与 `Full-Duplex-Bench` 只读复用。X2 旧资产已清理，当前不能假设模型、导出权重或环境存在。本次调研未登录服务器核实数据/GPU，因此表中数量与路径仍须预检。

创建独立工作根 `interclarify-x2-turn-quality`，内部区分 `src/models/envs/runs`。远端使用 conda Python 3.11 环境装配作者 vLLM overlay；本地只用现有 conda `interclarify-dev` 做格式、评分逻辑和协议模拟检查。对齐沿用可复现的独立评分环境，不能覆盖现役 ASR/TTS 依赖。先验证 CUDA/驱动/torch/vLLM 的兼容性并导出精确锁文件，不直接把环境模板视为已经可运行。

| 阶段 | 资源硬上限 | 时间与并发 |
| --- | --- | --- |
| 清单与资产预检 | 4 CPU、8 GiB RAM | 1 小时、1 作业 |
| 依赖安装与导出 | 8 CPU、32 GiB RAM、编译 worker≤2 | 4 小时；模型服务不同时运行 |
| X2 服务和回放 | 1×24 GiB GPU、8 CPU、32 GiB RAM | 每作业 8 小时、1 会话、1 推理 worker |
| 参考对齐 | 最多 1×24 GiB GPU、8 CPU、32 GiB RAM | 4 小时；先停 X2 服务，worker≤2 |
| 状态 Judger 和统计 | 4 CPU、8 GiB RAM | 8 小时、请求并发 1 |

X2 显存先以设备 90% 为服务上限做短片段预检；不足时报告 OOM/限制，不自动加卡。限制上下文长度和单请求音频缓冲，按 manifest 最大输入长度核算 KV/内存；超出可运行长度的输入明确失败，不静默滑窗截断或重置。模型导出若需超过内存预算则采用受限流式导出或停止，不能忽略峰值。

固定新资产预算≤70 GiB（环境、源码/构建缓存、源/导出权重合计），每轮输出≤30 GiB，启动可用空间≥120 GiB；额外完整权重、无界构建缓存和音频副本均不默认下载。预估超过预算时先改用已有只读资产/裁剪无用缓存或记录阻塞，不自动扩容。单个 trace 文件≤2 GiB，接近上限轮转；资源每 5 秒采样，接近 RAM/磁盘上限有序停止。只清理本作业进程与临时文件，不杀其他项目服务。

长作业写逐样本检查点，可在相同冻结配置下从完整样本边界恢复；不把不同版本 trace 拼成同一轮。报告实际音频总时长、播放倍速、实时积压及资源峰值。没有 GPU 实测前不承诺该配置能维持实时。

## 11. 实施顺序与验收

1. **数据与参考预检**：核实 672 主样本、99 补充场景和所需字段，生成 manifest，补齐可靠参考和末端边界。缺失项逐条说明，不默认下载新版本替换旧数据。
2. **远端部署与协议验证**：锁定环境、权重与代码，证明状态头已加载、有效 delay=480 ms、原始 delta 未门控，验证帧映射与尾窗/EOF 行为。
3. **Judger 开发与参考冻结**：先用非 FDB 开发材料定规则、容差、提示词与预算，再生成并抽检 FDB 状态参考；不读取待测预测进行打标。
4. **实现评分并做逻辑检查**：覆盖空文本/末词缺失、尾窗后补字、帧偏移/缺失、标签碰撞、歧义 mask、重叠输入和事件重复；使用人工可算的小 trace 验证。
5. **远端冒烟**：四个主子集各 5 例，加 user_backchannel 5 场景的 clean/overlap，共 30 次输入。仅检查传输、时间记录、格式和资源，不用冒烟分数选择模型/阈值；变更评分协议时版本化并重跑受影响结果。
6. **正式回放与报告**：预期 672 + 198 = 870 次输入，实际范围以冻结清单为准，逐样本串行运行。按总时长拆分受限作业，不能为赶时间改为整段快速上传。完成评分、覆盖/失败核账与代表性错误复核后，更新报告并归档对应工作单。

协议验收要求：输入按真实时钟到达；参考隔离；文本/状态/EOF 时间可追溯；所有样本都有成功、失败或缺标状态；WER、末端延迟和逐帧/事件匹配可由冻结产物独立重算；资源未越界且无遗留服务。能力结论根据实际分数给出，本轮不事先编造准确率门槛。

## 12. 工作单与待核实事项

本次明确请求恢复本轮 issue 拆分，历史已删除 issue 不重建。计划完成项 [X2Q-001](../../issue/archive/x2q_001_quality_plan.md) 已归档；待实施项见 [工作单入口](../../issue/README.md)：X2Q-002 数据/参考、X2Q-003 部署/回放、X2Q-004 状态 Judger、X2Q-005 指标/评分、X2Q-006 正式远端测试与报告。

实施前仍须核实：远端 v1.5 资产和参考完整性、人工听审安排、Judger 实际模型与预算估算、GPU/驱动与 vLLM 兼容性、服务端 delay 的真实配置路径、输出步与 80 ms 网格的映射、参考 token 占位冲突处理。以上各项均有对应预检/降级报告规则；未核实不写成已完成，不需要在本次计划阶段启动模型作业。
