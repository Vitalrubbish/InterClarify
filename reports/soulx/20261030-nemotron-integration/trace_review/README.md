# Nemotron＋SoulX：两条真实 trace 核查

2026-10-30，按用户要求从既有 r2 远端结果提取两条完整录音，不重新运行模型、不更改适配实现。结论：**在线文字连续、可读；完成状态与整句结束的匹配仍有明显问题，当前不宜依赖它直接触发正式回答。**

## 阅读口径

- 时间均为音频坐标：状态的 `processed_until / 16000`，不是回调墙钟时间，也不是逐词声学对齐时间。CSV 另保留音频观察上界。
- 表内“控制文本”是该 controller generation 实际使用的累计派生文本。reset 后可能从旧尾词重新开始；它与 Context 全文不同。CSV 同时保留两者和版本。
- 表格保留状态首次出现及每次切换；相同状态连续帧见两份 CSV，共 48＋44＝92 帧。事件序号直接对应原始 JSONL。
- 五类 special token 原样记录，不人工纠正预测。两例均未出现 `<|user_backchannel|>`。机械引用一致与语义时机正确分开判断。
- 没有逐时话轮金标，也未在本轮重新听音或取得两例的独立人工转写，因此不给总体文字准确率或 special token 命中率。既有报告对 FLEURS 的参考一致性判断仅作为已有证据引用。


## Trace 1：FLEURS 完整录音

音频长度 7.800 秒；48 条状态，55 次在线文字更新，0 次文本 token 缓存重放。

最终在线全文（与排空结果相同）：

> In many cases enrolling on a gap year course abroad can actually improve your chances of moving into higher education back in your home country

| 音频处理至（秒） | 事件 | generation | special token | Context／消费版本 | 控制文本 |
| ---: | ---: | ---: | --- | --- | --- |
| 0.12 | 3 | 0 | `<|user_idle|>` | 0／0 | （空） |
| 1.24 | 34 | 0 | `<|user_nonidle|>` | 5／5 | In many cases |
| 2.68 | 81 | 0 | `<|user_incomplete|>` | 15／15 | In many cases enrolling on a gap year |
| 2.84 | 90 | 0 | `<|user_idle|>` | 18／15 | In many cases enrolling on a gap year |
| 3.48 | 110 | 0 | `<|user_nonidle|>` | 22／22 | In many cases enrolling on a gap year course abroad can |
| 4.44 | 150 | 0 | `<|user_complete|>` | 33／33 | In many cases enrolling on a gap year course abroad can actually improve your chances |
| 4.60 | 154 | 1 | `<|user_idle|>` | 33／0 | （空） |
| 5.08 | 165 | 1 | `<|user_nonidle|>` | 34／34 | chances of |
| 6.52 | 214 | 1 | `<|user_incomplete|>` | 45／45 | chances of moving into higher education |
| 6.68 | 221 | 1 | `<|user_nonidle|>` | 47／47 | chances of moving into higher education back |
| 7.48 | 252 | 1 | `<|user_complete|>` | 55／55 | chances of moving into higher education back in your home country |
| 7.64 | 256 | 2 | `<|user_idle|>` | 55／0 | （空） |

文字判断：与[已有报告](../README.md#3-r2实测结果)所记参考的词序一致；本轮对照历史转写也只见逗号差异，但历史 ASR 输出不能代替独立金标。全句 25 词，最终在线正文完整，未观察到重复拼词或丢失中间片段。

状态判断：4.44 秒在 `…improve your chances` 发出第一次 complete，后面仍有 `of moving into higher education back in your home country`。该前缀本身可以成句，但对这条实际持续录音形成了提前分段；随后 generation 从 0 变为 1。7.48 秒的第二次 complete 已消费到 `country`，与完整文本结束相符，但没有声学结束金标，不能把距离文件末尾 0.32 秒直接当作提前量。6.52 秒在 `higher education` 给出 incomplete，随后继续接收后半句，从发布状态看定性上合理，但这帧原始预测为 nonidle，incomplete 来自上游规则。

完整逐帧数据：[fleurs.trace.csv](fleurs.trace.csv)。原始输入 `artifacts/soulx/20261030-nemotron-integration-r2/runs/nemotron-soulx-20261030-r2/probe/fleurs.events.jsonl`，SHA256 `2b2332640abc0e6bad2f19af931b3787f2fa4066bbdf38fa22f556ae68a75769`。


## Trace 2：官方英文示例

音频长度 7.176 秒；44 条状态，32 次在线文字更新，3 次文本 token 缓存重放。

最终在线全文（与排空结果相同）：

> The tribal chieftain called for the boy and presented him with fifty pieces of gold

| 音频处理至（秒） | 事件 | generation | special token | Context／消费版本 | 控制文本 |
| ---: | ---: | ---: | --- | --- | --- |
| 0.12 | 3 | 0 | `<|user_idle|>` | 0／0 | （空） |
| 1.56 | 32 | 0 | `<|user_nonidle|>` | 1／1 | The |
| 2.04 | 41 | 0 | `<|user_incomplete|>` | 1／1 | The |
| 2.20 | 48 | 0 | `<|user_nonidle|>` | 3／3 | The trib |
| 3.80 | 102 | 0 | `<|user_complete|>` | 15／15 | The tribal chieftain called for the boy |
| 3.96 | 106 | 1 | `<|user_idle|>` | 15／0 | （空） |
| 4.92 | 136 | 1 | `<|user_nonidle|>` | 21／21 | boy and presented him |
| 6.68 | 187 | 1 | `<|user_incomplete|>` | 30／30 | boy and presented him with fifty pieces of |
| 6.84 | 190 | 1 | `<|user_idle|>` | 30／30 | boy and presented him with fifty pieces of |

文字判断：最终得到完整、通顺的 15 词句子，在线与排空一致；缺少独立人工参考，不能仅凭通顺认定逐字正确。2.20 秒实际控制文本还在词内前缀 `The trib`，原始字符追加没有完整词保障。3 次缓存重放处理了分词变化，不能把“缓存重建成功”计作状态预测正确。

状态判断：3.80 秒在 `The tribal chieftain called for the boy` 给出唯一 complete，后面仍有 `and presented him with fifty pieces of gold`，同样提前切开了实际录音。6.68 秒在 `…pieces of` 给出 incomplete，与介词后待续文本吻合，但该 incomplete 由上游规则从 nonidle 转换而来；6.84 秒转为 idle。之后 Context 收到 `gold` 并达到在线版本 32，但控制器最多消费到版本 30，即 `…pieces of`，没有在完整全文后再次给出 complete。这例同时暴露提前完成和尾词未进入状态判断的问题。

完整逐帧数据：[english_example.trace.csv](english_example.trace.csv)。原始输入 `artifacts/soulx/20261030-nemotron-integration-r2/runs/nemotron-soulx-20261030-r2/probe/english_example.events.jsonl`，SHA256 `07f705d98e6f3904b517ba5433a8f9ca203fbf19fb1aa2763c0eb79533e4cfae`。


## 匹配程度的结论

两条 trace 的 92 帧全部被接纳；其中 89 帧原始预测与发布 token 一致，另 3 帧经上游 `native_complete_incomplete_rule` 从 nonidle 改为 incomplete（FLEURS 事件 214，英文示例事件 41、187）。CSV 保留 raw_token、raw_token_id 和 adjustment。每帧控制事件引用、实际消费版本、因果观察上界均通过检查。这说明事件与输入关联可追溯，**不代表 92 帧语义全对**。

实际观察到 3 次 complete：FLEURS 的第一次和英文示例的唯一一次出现在后续仍有正文的句中位置；FLEURS 的第二次出现在完整文本之后。这是案例计数，不能据此计算模型准确率。缺少停顿、话轮结束及 backchannel 金标，idle／nonidle 也不能逐帧判对错。

当前组合的主要问题已从“能否拼出连续文字”转向“控制器如何在词内增量、reset 和尾词迟到下正确判断结束”。若直接沿用 complete 触发正式回答，这两例都会有在用户后续内容到来前启动回答的风险；本次未接入 LLM／TTS，没有发生实际抢话测试。
