# Nemotron 160ms teacher forcing 方案讨论

2026-10-30，用户提出：用Nemotron按160ms持续解码，取消3.2秒ASR窗口；0.6B自身预测的正文丢弃，Nemotron新文字注入上下文，模型生成的状态special token进入上下文。本页讨论可行性及必要的时序定义，尚未实现、提交模型作业或恢复旧Nemotron适配，不新建issue。

当前回滚已完成：`a1c30af`撤回SenseVoice delta草稿＋controller片段覆盖及固定起点重识别候选。160ms Context接口保留，运行代码与前端测试恢复到`484ca32`基线；历史报告保留。现行基线仍有旧窗口拼合质量限制，不能视为新方案已生效。

## 1. 可行性结论

方案在结构上可行，符合“外部ASR给文字，SoulX给状态”的teacher forcing思路。关键是文字位置直接使用Nemotron输入，避免让0.6B自生成正文先进入缓存、事后只隐藏输出。不是修改`recognize()`返回值就能完成，需要调整原生ASR门控、文本输入位置、解码步配对和与无delta相关的状态规则。

官方[论文第3.4／3.6节](https://arxiv.org/html/2603.14877v1)使用音频、文字、状态交错序列，推理采用外部ASR的teacher forcing。官方[service/model.py](https://github.com/Soul-AILab/SoulX-Duplug/blob/a0b9063843df69619b087b95b74597b2176910b8/service/model.py)已有音频后注入外部文字、补ASR结束分隔符再预测状态的前向路径，但使用SenseVoice滑窗差分和自身门控；用户提出的新方案可复用输入结构，不能原样复用窗口差分。

## 2. 160ms是持续解码步，不是独立短录音

Nemotron每次处理约160ms新增音频，保留跨块声学／RNNT解码缓存；不能每160ms重新创建会话、清空缓存再识别。取消的是SoulX的3.2秒滑动ASR重识别和文字LCS拼接，不是取消Nemotron的历史缓存、必要特征重叠或前瞻。

沿用现有EN0.6B固定revision `ebe59e5a817142986528bbbee5dba8db7b38ed50`、FP32和lookahead1，不在本轮讨论中升级模型。[固定revision模型说明](https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b/blob/ebe59e5a817142986528bbbee5dba8db7b38ed50/README.md)介绍其cache-aware FastConformer-RNNT结构；实际现役解码由[独立服务](../../scripts/remote/nemotron_asr_service.md)维持单次generate和特征迭代器。

160ms步可能没有新增文字，也可能返回跨越此前多个块的词或词内字符。名义160ms不是每词延迟承诺，更不能将某步新返回的字全部视为只来自这160ms。SoulX音频编码原有960ms回看／40ms前瞻与ASR的3.2秒窗口是不同机制，本方案不默认删除它们。

## 3. 先区分两种上下文

| 位置 | 应放入什么 | 不能混入什么 |
| --- | --- | --- |
| 0.6B内部输入序列／KV | 原生音频embedding、Nemotron派生文字token、结构分隔符、五类状态token | 0.6B自行生成的普通正文；重复注入已消费前缀 |
| 下游SharedContext | Nemotron原文累积的用户正文，以及单独字段中的当前有效状态 | 音频token、内部结束符、0.6B自行生成的正文 |

用户的“文字注入上下文”必须至少作用于0.6B内部输入，才是teacher forcing。仅把Nemotron文字写入SharedContext，0.6B不会自动读到它。状态special token既作为后续状态模型输入，也以状态字段交给下游；不把它拼成用户自然语言。

只有五类用户状态可以作为下游状态：`user_idle`、`user_nonidle`、`user_incomplete`、`user_complete`、`user_backchannel`。`asr_eos`、padding、音频边界等special token仅为内部结构，不能全部发布。[官方token定义](https://github.com/Soul-AILab/SoulX-Duplug/blob/a0b9063843df69619b087b95b74597b2176910b8/config/config.py)区分了ASR结束符、音频符号、用户状态及其他动作，不能只按“是否special”作一个通用开关。

## 4. 推荐的逐步输入顺序

每步内部逻辑序列为：

```text
... → 上一步状态 → 当前音频 A_t → Nemotron新增文字 ΔT_t
    → ASR结束分隔符 E → 预测当前状态 S_t → 下一步音频 ...
```

执行上，先将上一步状态及当前音频送入0.6B并更新KV；此时产生的普通文字候选不用作输入。再用SoulX自己的tokenizer编码本步实际可用且尚未消费的Nemotron原文字增量，注入这些token与ASR结束分隔符；其后才预测状态。生成的有效状态在进入下一步音频前送回内部上下文。预测出的token本身不会因读取logits就自动进入KV，必须在下一次前向中明确输入一次。

因此不需要“持续自由生成，删掉普通字，一直等special token”的循环。如果普通字已被自回归反馈，再从外部输出删除，缓存中仍含这些字；如果丢弃后不改变输入就反复采样，则可能始终预测同一个字。按文字槽teacher forcing、按状态槽解码可以避免这两个问题。

ASR正文不能受原生0.6B的文字门控阻塞：Nemotron实际有新字就应消费，不能因0.6B先预测了`asr_eos`而漏掉它。结束分隔符在teacher forcing文字之后输入，不因模型提前给结束符而跳过已就绪文字。状态位置若出现普通正文或不支持的special token，应记录无效输出，不能继续自由生成凑出一个状态。是否使用五状态词表约束解码属于具体实现选择，需保留原始logits以评价行为。

ΔT_t使用Nemotron实际字符串增量，不将Nemotron词表ID直接输入Qwen词表。不自行给词内增量补空格：`inter`后到`net`不能变为`inter net`。SharedContext正文从原始累计字符串形成，始终只有Nemotron这一份权威文字。

按不同teacher forcing槽分别编码文字可能与整体字符串一次分词不同；不必为了追求全前缀分词一致而默认重放整段KV，但须验证词内交付在模型中的实际语义和状态影响。这一点不能靠原文只追加就认定已经解决。新增消费的字节范围、token输入和时间都需可追溯。

## 5. 解码同步和无新增文字

实际ASR完成步、已到达音频和SoulX处理块必须配对，不能仅按`step_seq × 160ms`宣称精确对齐。特征提取可能包含前瞻或预取；每次注入只使用截至本次在线状态计算时已返回、音频观察范围符合当前输入的结果，记录真实观察上界，不能把后来的词回填为早先已读。

首版建议先等待相应的真实Nemotron解码完成，再执行对应SoulX状态步骤；没有新字时ΔT_t为空，仍输入结束分隔符并预测状态。ASR尚未完成不能伪装成“完成但无字”。这会增加ASR计算等待，需在实时时钟回放中实测，不能先承诺固定160ms墙钟返回。保留800ms音频积压等现有保护边界。

原生`_state_predict()`在连续nonidle且delta为空时累计`mistake_len`，达到阈值后强制在complete／incomplete间选择。Nemotron没有出字可能是词未解码完或处理尚未就绪，不能把该规则原样继承为本方案的完成依据。建议首个对照取消“仅因Nemotron空delta累计就强制完成”的分支，并分开保留模型原始状态与其他规则调整，独立评价状态时机；不能将其改名为空增量后继续使用。

## 6. reset、发布和收尾

SoulX内部reset不重启Nemotron流、不清空共享正文，也不能把已消费ASR前缀重新当新字注入。新0.6B上下文是否需要补充此前语义属于明确的缓存策略，不能假定单纯去重就能保留被reset丢掉的语义。首个实验至少记录每次reset发生的位置及其后实际上下文；不能用此前已有正文掩盖模型未读到它。

取消SenseVoice完成分支的整段重识别：完成时使用Nemotron真实已交付的当前正文。complete既不清空ASR缓存，也不证明尾词全部到达。若有未交付末尾，按实际到达时间处理；不伪造音频或倒填较早状态。

当前接口仍规定每160ms处理步骤将最新全文及状态联合覆盖一份SharedContext记录，不保留历史正文版本。在这个接口下，Nemotron增量先进入前端当前正文，随相应处理步发布。如果用户还要求每次ASR回调立即独立写SharedContext、而不等状态步骤，则属于发布时机的另一个修订，不能混同于内部KV注入；后续实施前需在合同中写清。

EOF排空按现有规则仅作诊断；若需“关闭前等待ASR全部交付”，需明确关闭顺序和真实返回时间，不把complete与EOF当相同事件。

## 7. 与旧Nemotron组合的区别及验证

此前旧适配保留0.6B原生ASR门控，只在门控允许且有因果前缀时消费；还对累计前缀分词修订做KV重放。本方案的关键变化是：持续Nemotron解码、不再使用3.2秒窗口差分、每步文字槽直接teacher forcing、普通自生成文本不进入缓存，重新审视空delta兜底。不是恢复旧适配文件就等价完成。

[旧30条结果](../../../reports/soulx/20261030-nemotron-fdb30/README.md)中有提前complete、停顿误完成和打断检测延迟，因此现有权重对本方案的文本到达节奏仍需验证。不能将旧失败单独归因于空delta规则，也不能因结构可行就认为无需适配或训练。

实施后重点核对：逐步输入序列符合音频／教师文字／结束符／状态顺序；普通生成文本从未反馈缓存；ASR新字恰好消费一次；空结果与pending分开；词内增量不补空格；reset不重复或丢失ASR流；正文质量与原始ASR一致；状态时机、实际延迟、积压及显存符合既定资源范围。先用独立受限探针，不切换现役Agent、不自动恢复旧FDB任务。

本轮只完成回滚与方案讨论。Nemotron接入、门控替换、空delta规则调整、内部reset策略及发布时机尚未修改，研究主文档也没有据候选讨论自动切换为已实施的新路线。
