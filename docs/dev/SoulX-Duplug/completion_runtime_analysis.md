# SoulX-Duplug 提前 complete、官方运行时恢复

**SoulX 会在局部语义似乎结束时给出 complete，官方规则也能把持续 nonidle 改成 complete。官方系统随后启动回答，持续听音，并在用户续说时取消生成和未播音频，从而抵消部分可听后果**

## 1. 需要区别的概念

### 1.1 两种状态

1. Qwen3-0.6B 生成的**原始预测状态**；
2. 原始预测状态经过官方规则处理后生成的**规则后状态**；

每周期**原始预测状态**到**规则后状态**的处理规则：
1. 如果上一周期的规则后状态是 nonidle，本步的原始预测是idle，则会直接在 complete 和 incomplete 之间二选一；
2. 如果连续 3 拍的原始预测都是 nonidle，但是这 3 拍都没有产生出增量的文本，则会直接在 complete 和 incomplete 之间二选一；

### 1.2 两种上下文

1. Qwen3-0.6B 的 context
2. 交给半双工 LLM 的 context

## 2. 提前 complete 的具体例子

本节是 TurnControlComparison 自写运行时的实际日志，用于展示状态与续说现象。它调用官方 SoulX 控制器，但回复调度、播放、历史管理并非官方 dialogue-system，不能据此认定官方会生成相同的下一次 context。日志的 controller_raw 记录规则后返回值，未保存原始 argmax，不能确证第三步是否由规则改写。第三、四节仅按官方固定提交 `66a9f74ca39d30984eb87fc4c029fadc797b6e34` 解释。

### 2.1 无新字之后分别出现 complete 和 incomplete

| 日志墙钟 | 行号 | 记录状态 | delta_text |
| --- | ---: | --- | --- |
| 1.255s | 44 | nonidle | `a lot` |
| 1.356s | 49 | nonidle | 空 |
| 1.574s | 56 | nonidle | 空 |
| 1.678s | 61 | complete | 空 |
| 1.953s | 73 | nonidle | `I` |
| 2.135s | 83 | nonidle | 空 |
| 2.212s | 87 | nonidle | 空 |
| 2.318s | 92 | incomplete | 空 |


### 2.2 首音前取消和 context 合并

| 墙钟 | 直接记录 |
| --- | --- |
| 1.7396s | 生成回答，用户文本 `I see that a lot.` |
| 1.9544s | 取消回答，原因 `soulx_nonidle`（即用户又在说话） |
| 1.9545s | `playback_cancelled`（取消播放） |
| 1.9718s | LLM 返回 `It sounds like you're`，`cancelled=true` |
| 3.6583s | 下次 `llm_request` 只有合并用户消息 `I see that a lot. And.`，没有插入这次未播助手回答 |

从回复启动到取消请求约 214.8ms。

## 3. 官方怎样抵消一部分可听后果

官方下游消费服务层 speak：规则后 complete 在此前已检测到有效语音时，可触发整段识别并交接；另一条兜底必须先出现 incomplete、开启等待监控，之后连续 idle 达到 max_wait_num（默认 8），且已检测到语音，才能返回 speak。任意八拍 idle 本身不触发回答。FDB 离线入口还过滤空文本与附和文本，再启动 LLM／TTS。

下一次 nonidle 就直接取消当前的播放链路；如果取消之前 TTS 还没有播放音频，那么从听感上就没有抢话；

## 4. 取消后怎样处理 context

### 4.1 首音前取消：有条件地合并用户片段

以“帮我订周五的车票，……不对，是周六”为说明性输入。第一次交接后助手还未发声，随后续说取消了响应：

| 项目 | 官方 FDB 离线路径的理想顺序 |
| --- | --- |
| 用户内容 | 先保留周五片段，之后收到周六片段；若其间没有非空助手历史，两段 user 消息自动合并 |
| 助手未播回答 | 播放前取消的已排定音频删除；在历史截断得到空文本时，不追加助手消息 |
| 恢复 | 后续交接以合并后的输入重新生成 |

### 4.2 已播后取消：保留可听前缀与续说

假设助手已说“我查一下周五的……”，用户改口“是周六”。官方保留打断点前的音频，对助手正文按下式估计截断：

`保留字符数 = floor(助手文本长度 × min(已播放时长 / 已生成音频总时长, 1))`

在这个正常顺序下，下一轮是 user（先前片段）→assistant（估计已说前缀）→user（后续改口），用户片段因此不再直接合并。我们的设计也以首段实际播放作为分组边界，但要求按真实输出账本保存已播事实，不能将按字符估计的文本当成精确可听转写。

### 4.3 下一次交接怎样重新喂给 LLM

官方 FDB 离线入口 `_start_generation()` 按顺序执行：先 `_flush_assistant_history()` 整理前一次助手暂存消息，再追加本次用户文本，最后调用 `generate_with_history()`。后者把 system 提示词与当前角色消息列表组成请求。客户端把相邻同角色内容用换行合并，仅保留最后五个合并消息条目。

以“帮我订周五的车票……不对，是周六”为例，下列为官方正常历史整理顺序的说明性输入，不是第二节日志的官方重放结果：

| 取消阶段 | 下一次 LLM 请求中的角色消息 |
| --- | --- |
| 首音前，整理后助手文本为空 | system；user：帮我订周五的车票\n不对，是周六。FDB 离线入口不追加空助手消息，前后 user 因而合并 |
| 首音后，整理后助手文本非空 | system；user：帮我订周五的车票；assistant：按时长比例截出的已说前缀；user：不对，是周六 |

官方没有将所有已生成但未播的文本作为隐藏草稿再次输入，也没有对已播尾部做 ASR 回填。FDB 默认的 IndexTTS 组合客户端先缓冲文字，得到关联音频组后再交给运行时；被运行时接纳的正文暂存为 pending_message，之后按打断时间与音频时长裁切成助手历史。生成过的 token、暂存正文与下一次 messages 并非同一份内容。

LLM 服务对每次请求重新 apply_chat_template、分词，组合生成函数把 past_key_values 初始化为 None，然后在本次生成内部使用 KV 缓存。下一次交接会从整理后的 messages 重新计算，不沿着被取消回答的 KV 续写。因此不能把它描述成“未播 token 保留在旧 KV，再输入续说继续生成”。

源码见[历史整理与交接](https://github.com/Soul-AILab/SoulX-Duplug/blob/66a9f74ca39d30984eb87fc4c029fadc797b6e34/dialogue_system/offline_infer.py#L320-L336)、[角色消息与请求](https://github.com/Soul-AILab/SoulX-Duplug/blob/66a9f74ca39d30984eb87fc4c029fadc797b6e34/dialogue_system/clients/llm_client.py#L125-L143)和[每次请求的 KV 初始化](https://github.com/Soul-AILab/SoulX-Duplug/blob/66a9f74ca39d30984eb87fc4c029fadc797b6e34/dialogue_system/modules/qwen_llm/llm_server.py#L112-L165)。

### 4.4 设计意图与实际代码的边界

上述首音前合并、首音后保留前缀，是打断时间等元数据有效时的 FDB 离线处理路径，不是所有执行顺序的保证。工作线程尚未收尾时被取消，随后可能把 interruption_sample 清空，使助手暂存全文进入下一次历史；这在固定官方原方法的 CPU 探针中已复现。因此官方实际行为不能简化为“永远只保留已播文字”。

官方在线 app.py 还与 FDB 离线入口不同：中断分支即使未发出音频，也会追加空 assistant 消息，这会隔开前后 user 消息；首音时间记录的是服务端第一次发送音频，并非浏览器实际开播确认。不能把 FDB 离线的角色合并效果当作在线演示的统一保证。见[在线历史处理](https://github.com/Soul-AILab/SoulX-Duplug/blob/66a9f74ca39d30984eb87fc4c029fadc797b6e34/dialogue_system/app.py#L303-L333)与[离线历史处理](https://github.com/Soul-AILab/SoulX-Duplug/blob/66a9f74ca39d30984eb87fc4c029fadc797b6e34/dialogue_system/offline_infer.py#L574-L605)。
