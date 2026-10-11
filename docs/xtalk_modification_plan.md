# X-Talk DuplexCascade 阶段 A 改造方案

> 本计划只覆盖阶段 A：在固定的 X-Talk fork 上实现 DuplexCascade 无 System Backchannel 版本的全双工 micro-turn 流程。LLM 是唯一的语义与轮次决策者；运行时只负责输入组装、输出协议解析、生成任务生命周期和唯一 TTS 播放链路。论文原文见 [DuplexCascade](https://arxiv.org/html/2603.09180v1)。

## 1. 范围与目标

X-Talk fork 与 InterClarify 是两个独立项目，不使用 Git 子模块。

| 仓库 | 阶段 A 职责 |
| --- | --- |
| Vitalrubbish/xtalk | 实现通用 DuplexCascade 运行时和模型输出协议 |
| Vitalrubbish/InterClarify | 记录 X-Talk 提交、配置、测试证据和阶段 A 基线 |

阶段 A 的目标是让固定版本的 X-Talk 具备以下行为：

1. 持续接收音频并由流式 ASR 产生 partial/final 文本；
2. 按固定时间窗口形成 user micro-turn，空窗口使用 `<no voice>`；
3. 让 DuplexCascade 风格的 LLM 直接决定等待、回答、用户附和和用户打断；
4. 将 LLM 生成的系统 micro-turn 流式送入现有 TTS 与播放管理；
5. 支持回答进行中的持续监听、用户打断和剩余输出取消；
6. 保持一个 TTS 播放所有者，并把已经交付给用户的内容视为不可撤销事实。

阶段 A 不建立第二套语音运行时，不加入任务领域逻辑，也不把外部规则分类器放在 LLM 决策链路中。

## 2. 版本与 Git 基线

当前本地 InterClarify/xtalk 是独立 checkout，根仓库忽略该目录。X-Talk 远端配置为：

~~~text
origin   git@github.com:Vitalrubbish/xtalk.git
upstream git@github.com:xcc-zach/xtalk.git
~~~

阶段 A 开发使用独立 feature/* 分支。当前框架连接基线为：

~~~text
base:        5f0d9959edf1026588246efbed827b078cbb114c
integration: d9303c819c96230e527ea5159e7c74f1b5841a3e
~~~

实际运行时必须记录 X-Talk 分支、提交、模型 revision、量化方式、服务提交、依赖版本、VAD/轮次检测配置和参考音色。实验 manifest 不使用浮动分支名代替提交哈希。

## 3. 设计原则

### 3.1 LLM 是唯一语义决策者

DuplexCascade 的核心是把 micro-turn 的轮次控制交给经过 special token 训练的 LLM。阶段 A 不设置规则 Layer1Policy，也不让 TurnDetectorManager、VAD 或其他外部模块重新判断用户是否说完、用户是否在思考或用户是否只是附和。

LLM 的输入是截至当前窗口已经到达的对话历史和 user micro-turn；LLM 的输出是一个系统 micro-turn，其中可以包含控制 token 和回答文本。运行时只解析协议并执行，不根据同一输入再猜测一个替代状态。

### 3.2 运行时只执行确定性协议

运行时负责以下确定性工作：

- 聚合 ASR partial/final 和空窗口；
- 插入 `<no voice>` 与 `<EOS>`；
- 识别控制 token 的边界和顺序；
- 启动、暂停、取消和结束对应的生成/TTS 任务；
- 维护 session_id、turn_id、segment_id、prefix_version 和 response_id；
- 把回答交给唯一的 X-Talk TTS/播放链路；
- 在协议损坏时执行安全降级并记录原因，不重新进行语义分类。

阶段 A 不设置独立 OutputArbiter。单层运行时不存在跨策略竞争；DuplexRuntimeAdapter 只负责协议执行和提交边界，不能成为第二个语义决策器。

### 3.3 无 System Backchannel

阶段 A 采用论文中的 DuplexCascade，而不是 DuplexCascade-beta：

- 不训练、不生成 `<system backchannel>`；
- 不加载系统附和模型、预录音频或 direct_audio 路径；
- 用户附和 `<user backchannel>` 仍属于输入交互现象，必须保留；
- 当前阶段不实现 Layer 0 或其他系统倾听反馈。

## 4. DuplexCascade 控制协议

### 4.1 输入 token

每个 user micro-turn 进入 LLM 前使用以下格式化约定：

| token | 作用 |
| --- | --- |
| `<no voice>` | 当前窗口没有识别到用户文本，表示用户静默 |
| `<EOS>` | 结束一个 micro-turn，分隔连续的用户和系统片段 |

`<no voice>` 是输入事件，不代表运行时自行判断用户正在思考；是否属于用户思考由 LLM 根据上下文输出对应系统 token。

### 4.2 输出 token

阶段 A 只使用 DuplexCascade 无 System Backchannel 版本的五个系统控制 token：

| LLM 输出 token | 协议含义 | 运行时执行 |
| --- | --- | --- |
| `<user is speaking>` | 用户仍在继续当前表达 | 结束当前系统 micro-turn，不启动新 TTS |
| `<user finish speaking>` | 当前可以接过话轮 | 允许后续回答文本进入流式 TTS |
| `<user is interrupting>` | 用户正在打断系统 | 取消当前未完成生成和剩余未播放音频 |
| `<user backchannel>` | 用户产生短附和 | 不创建新回答，保持当前回答流 |
| `<user is thinking>` | 用户在系统回答结束后继续思考 | 结束当前系统 micro-turn，继续等待 |

`<user finish speaking>` 后面可以跟系统回答文本；其他四个控制 token 按论文协议以 `<EOS>` 结束当前系统 micro-turn。阶段 A 不把这些 token 压缩为 SILENCE/ANSWER 训练标签。统计日志可以额外记录粗粒度投影，但投影不能替代原始 token。

### 4.3 协议错误

运行时只接受当前 response 的合法 token 顺序，并检查 response/session/turn 上下文。遇到未知 token、缺失 `<EOS>`、重复提交或已取消 response 时：

1. 停止当前未提交的协议片段；
2. 不根据 ASR 内容猜测替代动作；
3. 记录 protocol_error、response ID、prefix version 和原始片段；
4. 继续接收后续 micro-turn，或按配置执行安全的句末回退。

## 5. Micro-turn 组装

### 5.1 窗口策略

- 默认窗口从 0.6 秒开始，作为实验参数而不是固定研究结论；
- 定时 tick 产生窗口，即使当前没有新文本也要发送 `<no voice>`；
- ASR partial、停顿和必要的输入事件可以提前触发 flush；
- 同一窗口只发送当时已经到达的 ASR 前缀；
- ASR revision 以新的 prefix_version 表示，不能覆盖已经提交或已经播放的 response；
- 窗口调度器只负责组装和发布，不执行 LLM 语义判断，不直接调用 TTS。

### 5.2 前缀快照

每个送入 LLM 的窗口形成一个不可变 PrefixSnapshot：

~~~text
session_id
turn_id
segment_id
prefix_version
text
previous_text
revision_kind: APPEND | REWRITE | FINALIZE | SILENCE
speech_state: SPEAKING | PAUSING | ENDED
received_monotonic
~~~

同一 turn 中，只要可见文本、修订类型或 final/停顿状态发生有效变化，prefix_version 递增。快照不能包含未来音频、完整人工转写、任务真值或最终动作标签。

## 6. 运行时生命周期

阶段 A 使用 X-Talk 既有事件和播放管理，并补充协议所需的关联字段。一个回答的生命周期为：

~~~text
RECEIVED
  -> GENERATED
  -> TTS_REQUESTED
  -> TTS_READY
  -> COMMITTED        (TTSStarted，客户端交付门打开)
  -> HEARD_PARTIAL    (非空 ResponseUpdate)
  -> FINISHED | STOPPED
  -> SETTLED           (ResponseFinish)
~~~

- response_id 在允许回答的 micro-turn 开始时确定，并贯穿 LLM、TTS、播放和历史合并；
- COMMITTED 之后不再替换已经提交的片段；
- 用户打断可以取消生成任务和未播放音频，但不能撤回 HEARD_PARTIAL 或其他已播文本；
- ResponseUpdate 和 ResponseFinish 是已经交付的不可撤销事实；
- 提前回答后到达的 ASR final 不得自动产生第二个相同回答；
- 没有提前回答时，final 可以触发一次正常的句末生成。

TurnDetectorManager 的 speaking 状态在 TTSStarted 后切换为非 listening，在 TTSPlaybackFinished 或 TTSStopped 后恢复。TTSChunkReady 只表示音频已生成，不能作为客户端交付边界。

## 7. 阶段 A 控制链路

~~~text
Audio / low-level VAD signals
            │
            ▼
Streaming ASR partial/final
            │
            ▼
MicroTurnAssembler ──► PrefixSnapshot
            │                 │
            └─────────────────▼
                    DuplexCascade LLM
             special token + response text
                              │
                              ▼
                    DuplexRuntimeAdapter
               protocol parsing and lifecycle
                              │
                              ▼
             LLMAgentConsumption / TTS coordinator
                              │
                              ▼
                 TTSManager / PlaybackManager
~~~

低层 VAD 信号可以继续被 X-Talk 用于音频接收和资源管理；它们不能绕过 LLM 直接决定 Layer 1 的语义动作。阶段 A 的无 System Backchannel 能力目标也不等价于移除所有底层 VAD。

## 8. X-Talk 模块职责与最小改造

### 8.1 保留的原生模块

| 模块 | 阶段 A 用途 |
| --- | --- |
| EventBus | 发布和关联会话事件 |
| ASRManager | 产生流式 partial/final 文本 |
| LLMAgentConsumptionManager | 消费 LLM 输出流并转发文本片段 |
| TTSResponseCoordinator | 串行管理 response 交付 |
| TTSManager | 流式语音合成 |
| TTSPlaybackManager | 唯一播放所有者，确认已播文本 |
| TurnDetectorManager | 接收低层轮次线索和已播上下文，维护 listening 边界；Duplex 模式不把其 START_GENERATION/STOP_SPEAKING 作为语义决策 |

### 8.2 新增或最小补丁

通用改造放在 X-Talk fork 的 src/xtalk/duplex_control/：

~~~text
src/xtalk/duplex_control/
├── __init__.py
├── protocol.py
├── state.py
├── timeline.py
├── micro_turn.py
├── runtime_adapter.py
└── service.py
~~~

| 文件 | 职责 |
| --- | --- |
| protocol.py | 定义输入/输出 token、协议解析结果和错误类型；不包含语义规则 |
| state.py | 定义 PrefixSnapshot、response 生命周期和不可变关联字段 |
| timeline.py | A1 的会话事件记录器，保留原始关联字段、单调时间戳、协议错误码和已播文本 |
| micro_turn.py | 按 tick 和 ASR 事件组装 user micro-turn；插入 `<no voice>` |
| runtime_adapter.py | 解析 LLM token，执行取消、TTS 请求、提交边界和安全降级；不判断语义 |
| service.py | 将 assembler、adapter 和现有 X-Talk manager 注册到 session service |

首轮允许对以下现有文件做最小补丁；A1 的交付关联字段跨越多个原生 manager，因此补充相应字段传递补丁：

| 文件 | 补丁内容 |
| --- | --- |
| serving/events.py | ASR、生成和控制事件补充 prefix/turn/segment/response 关联字段 |
| llm_agent_generation_manager.py | 使用预先关联的 response ID，保留流式 token 顺序 |
| turn_detector_manager.py | speaking 状态由 TTSStarted 驱动，而不是 TTSChunkReady |
| serving/service.py | 注册阶段 A assembler 和 runtime adapter |
| llm_agent_context_manager.py | A1 传递输入关联字段，区分输入请求与已播反馈的 response ID |
| tts_response_coordinator.py | A1 在准备、切换与交付请求之间保留每个 response 的关联快照 |
| tts_manager.py | A1 在合成、交付和停止事件中保留关联快照 |
| tts_playback_manager.py | A1 为已播更新、结算和关闭事件保留关联快照 |

不复制 EventBus、会话管理、ASR、TTS 或播放队列。阶段 A 不新增语义 Arbiter、规则 Policy、第二个 executor 或第二条 TTS 通道。

启用 DuplexCascade 模式时，X-Talk 原生 turn detector 的 START_GENERATION/STOP_SPEAKING 事件不能绕过 LLM 直接启动回答或决定语义打断。运行时只保留它们提供的低层输入、停止信号和播放清理能力；回答开始、用户附和、用户思考和语义打断均以 LLM special token 为准。

## 9. DuplexCascade 风格训练协议

### 9.1 数据构造

论文从文本对话动态构造 duplex 训练序列。阶段 A 的训练适配器应支持同样的序列格式：

1. 将用户和系统长话轮切成短 micro-turn；
2. 在用户窗口后插入系统控制 micro-turn；
3. 用 `<no voice>` 模拟自然停顿和系统回答后的思考；
4. 以受控概率插入用户打断和用户附和；
5. 在系统微回合中监督五个无 System Backchannel 控制 token；
6. 仅对系统 micro-turn 计算 next-token 监督，保护基础 LLM 的语言能力。

论文使用 50k 多轮文本对话、LoRA 和控制 token 的加权损失作为示例。阶段 A 可以先以小规模数据和短跑验证协议，再根据 X-Talk 的固定 LLM、显存和延迟条件决定正式数据量。论文的 H100 训练时长不能直接当作本项目 4090 集群的预算承诺。

### 9.2 训练约束

- 不加入 `<system backchannel>` 目标；
- 控制 token 的 embedding 与输出头必须纳入适配；
- token 类别权重、窗口长度和系统 micro-turn 长度必须写入版本化配置；
- 训练输入只能使用当时可见的 micro-turn 历史；
- 训练和回放脚本必须保留原始 token 序列，不能只保存 SILENCE/ANSWER 投影；
- 在线服务使用的 LLM revision 必须与训练 manifest 对齐。

## 10. 实施顺序

### A0：固定基线与框架连接（已通过）

- 固定 X-Talk feature 分支、模型组合和服务配置；
- 在 conda 环境中跑通原生 ASR、LLM、TTS 和播放链路；
- 显式关闭系统附和模型与音频目录；
- 保存事件日志、提交哈希、依赖和资源记录。

### A1：协议与可观测性（本地门禁已通过）

- 补齐 prefix_version、request_id、response_id、turn/segment 字段；
- 定义 token 解析事件和协议错误事件；
- 记录从 ASR micro-turn 到 TTSStarted、ResponseUpdate、ResponseFinish 的统一时间线；
- 把 speaking 边界从 TTSChunkReady 修正为 TTSStarted。

2026-10-11 审查发现：已有字段定义、完整片段解析器、观测事件和记录器，但生成、交付和播放发布路径尚未完整传递关联信息；JSONL 缺少 error_code，边界测试只直接调用处理方法。因此 A1 补丁增加确定性的字段传递与事件总线回归，扩展上述四个原生 manager 的最小补丁范围。输入已经提供的 prefix_version 原样传递；版本生成与 micro-turn 调度仍属于 A2。协议观察只验证完整模型输出并记录结果，在线流解析、过期响应拒绝、取消与 final 去重属于 A3。

记录器区分事件创建时间与记录顺序，保留错误码和原始输出，不从相邻事件推测缺失 ID。验收应包含并发响应隔离、预分配 response ID、响应结束后的新 ID、准备阶段持续监听、TTSStarted 后状态切换和已播文本结算；远端模型链路与 FDB 验收属于 A4。

2026-10-12 补充结果：关联传递、协议错误码、事件总线边界测试和 shutdown 日志已补齐；定向测试 35/35 PASS。运行位置为 X-Talk fork 根目录：

~~~bash
conda run -n paratalker-dev env PYTHONPATH=src python -m unittest tests.test_duplex_protocol tests.test_duplex_observability tests.test_turn_detector_manager tests.test_llm_agent_persistent_stream tests.test_response_identity tests.test_tool_call_playback_barrier tests.test_tts_streaming_playback_alignment -q
~~~

A1 实现与双语文档提交为 9c131ed6399da66b66b001184cfa4005787b5f67，分支 dev，开发父提交为 b371bb4f8868fbb1672b055e13f631155213083c；远端已验证基线仍为 d9303c8。源码镜像说明、配置与测试索引位于独立 fork 的 docs/technical_reference/duplex_observability.zh.md。本地模拟链路结果不替代远端 conda 模型服务、FDB、长会话与音频质量验收。

### A2：Micro-turn 组装

- 实现 0.6 秒起始 tick 和事件驱动 flush；
- 无新增文本时发送 `<no voice>`；
- 正确处理 partial、pause、rewrite 和 final 的版本递增；
- 验证窗口组装不阻塞音频接收和 TTS 播放。

### A3：LLM 协议执行

- 将 user micro-turn 送入 DuplexCascade 格式的 LLM 上下文；
- 解析五个控制 token 和 `<EOS>`；
- 将回答文本流接入现有 TTS；
- 实现 `<user is interrupting>` 的生成取消、剩余音频停止和监听恢复；
- 实现用户附和保持当前回答、用户思考继续等待和提前回答后的 final 去重；
- 处理 malformed output、过期 response 和 shutdown 取消。

### A4：阶段 A 验收

- 脚本化 micro-turn、停顿、思考、用户附和、提前回答和用户打断场景；
- X-Talk 原生基线与 DuplexCascade 运行时对照；
- FDB smoke，重点检查停顿、用户附和、顺畅接话、用户打断和重叠语音；
- 检查首 token、首 TTS chunk、TTSStarted、首个已播文本和停止延迟；
- 检查长会话队列、任务取消、内存、显存和 shutdown；
- 确认系统附和 token、音频和旁路播放调用均为零。

## 11. 阶段 A 测试矩阵

### 协议测试

- 输入 `<no voice>` 和 `<EOS>` 的序列化/反序列化；
- 五个系统控制 token 的识别、边界和 `<EOS>` 处理；
- 未知 token、缺失 `<EOS>`、重复 token 和乱序 response 的安全降级；
- 不出现 `<system backchannel>` 和 direct-audio 旁路。

### Micro-turn 测试

- 固定 tick、partial 触发、停顿触发和 final 触发；
- 空窗口仍发送 `<no voice>`；
- append、rewrite、pause、final 的 prefix_version 单调递增；
- 旧版本 response 不覆盖新版本上下文；
- 调度器不阻塞 ASR、LLM 消费或 TTS 播放。

### 生命周期测试

- response_id 在生成、TTS、播放和历史合并中保持一致；
- TTSStarted 才打开 COMMITTED 边界；
- 用户打断停止未播放尾部，已播文本保持不变；
- 提前回答后 final 不重复生成；
- 没有提前回答时 final 只触发一次安全回答；
- shutdown 取消 assembler、LLM 和 TTS 相关任务。

### 回归测试

- X-Talk 原有 TTS 串行和播放对齐测试继续通过；
- TurnDetectorManager 在 TTSStarted/Stopped/PlaybackFinished 时保持正确 listening 状态；
- 原生组件、依赖和配置版本与 manifest 一致；
- 远端 conda 环境运行阶段 A 脚本和 FDB smoke。

## 12. 验收标准与限制

阶段 A 只有在以下条件同时满足时才算完成：

1. 固定 X-Talk 提交可重复启动并运行完整链路；
2. LLM special token 是唯一的 Layer 1 语义决策来源；
3. micro-turn、协议解析、取消和播放边界有事件证据；
4. 用户已听到的文本不会被撤回或伪造为未播放；
5. X-Talk 原有 TTS、播放和 turn-taking 回归不退化；
6. 阶段 A 验收场景和 FDB smoke 在远端 conda 环境可重复运行。

阶段 A 不声称复现论文的官方权重、训练规模、硬件时长或全部论文数值。它验证的是在固定 X-Talk 底座上实现 DuplexCascade 无 System Backchannel 的可运行协议和全双工行为。
