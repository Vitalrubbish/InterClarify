# InterClarify 分阶段工程落地方案

## 1. 文档目的与路线决策

本文把 [research_design.md](research_design.md) 中的研究构想转换为可执行、可验收和可停止的工程计划。

自 2026-10-09 起，项目不再直接复现、内嵌或改造 DuplexCascade 官方源码。新的工程路线是：

1. 以 [X-Talk](https://github.com/xcc-zach/xtalk) 的模块化全双工级联系统为唯一运行底座；
2. 在 X-Talk 的事件总线、轮次检测、生成、TTS 协调和播放链路上做最小扩展；
3. 以 DuplexCascade 展示的能力作为功能目标和相关工作参照，不依赖其官方权重、控制 token、Kyutai 服务或源码实现；
4. 先让改造后的 X-Talk 具备可观察、可回归的 micro-turn、backchannel、提前回答、用户打断停播和持续监听能力，再接入 InterClarify 的 Layer 2；
5. 快速验证话轮内主动澄清是否值得继续，只有通过门禁后才扩大数据、训练和真人实验。

因此，旧路线中的 `3rd-party/DuplexCascade`、官方权重准备脚本、Kyutai `moshi-server` 编排、官方控制模型适配器及其测试和实验产物均不再属于当前实现。

## 2. MVP 范围与不可破坏的边界

### 2.1 当前研究范围

MVP 只选择一个可程序核验结果的任务域，默认采用**日程安排中的日期和时间选择**。系统研究对象仍是 Layer 2 的澄清判断与交互闭环：

- 当前前缀是否存在会改变任务结果的解释分歧；
- 分歧是否仍未解决，用户是否可能马上自行说明；
- 当前是否适合接话；
- 能否生成一个具体、简短、可回答的问题；
- 收到回答后能否恢复同一个任务。

X-Talk 提供 ASR、LLM agent、TTS、VAD、轮次检测、异步事件和 WebSocket 服务基础。项目不建设第二套并行语音运行时，也不把复现 DuplexCascade 的模型或训练流程作为前置条件。

### 2.2 Layer 与动作边界

- Layer 0 只产生 `SILENCE` 或低强度 `BACKCHANNEL`。
- Layer 1 负责常规 `SILENCE` / `ANSWER`，并可请求 Layer 2。
- Layer 2 只产生 `NO_OVERRIDE` 或澄清问题；识别到歧义也可以选择等待。
- 当前不启用 Layer 3；只预留版本化修订接口。若后续启用，Layer 3 只能修订尚未提交播放的片段。
- 所有候选输出必须经过一个 `OutputArbiter`。有效优先级为 Layer 2、Layer 1、Layer 0。
- 只允许一个 TTS 播放所有者。X-Talk 的播放管理链路是唯一提交点，其他模块只能提交播放意图。
- 已经播放给用户的内容不可撤销。高优先级结果只能取消或替换尚未提交的片段。
- 在线策略只能读取决策时刻以前到达的音频、ASR 前缀、修订和运行状态；隐藏目标、完整转写和未来输入只用于数据构建与评价。

### 2.3 对 X-Talk 的改造原则

- 固定上游提交后再开发；镜像标签不能代替源码提交记录。
- 优先通过 InterClarify 适配器、自定义 manager、event 和 model slot 扩展 X-Talk。
- 必须修改上游文件时，以最小补丁维护，并记录文件、原因、上游提交和回归测试。
- 不复制 X-Talk 已有的 EventBus、会话管理、ASR/TTS manager 或播放队列。
- 不允许 Layer 0、Layer 1、Layer 2 分别创建播放通道。
- 不允许慢速 Layer 2 阻塞音频接收、轮次检测或正在进行的正常回答。

### 2.4 统一完成定义

一个阶段只有同时具备以下四项才算完成：

1. 可运行产物：脚本、配置或服务入口可在新的 conda 环境中执行；
2. 可追溯产物：X-Talk 提交、依赖、模型、数据、提示词和配置都有版本记录；
3. 可检查证据：日志、结果表或试听样本支持验收结论；
4. 对应文档：实现文件在 `docs/` 下有同路径说明，记录功能、主要类和核心方法。

## 3. 目标能力与总体阶段

### 3.1 DuplexCascade 功能目标的操作化定义

本项目所称“达到 DuplexCascade 的功能”只指以下可测试行为，不指复现其模型结构、参数或论文数值：

| 能力 | 可测试定义 |
| --- | --- |
| 持续监听 | 系统播放期间仍持续接收用户音频并更新会话状态 |
| micro-turn | 按固定或事件驱动的短窗口检查是否保持静默、backchannel、回答或请求澄清 |
| backchannel | 能产生与正式回答可区分的低强度反馈，且不错误结束用户话轮 |
| 提前回答 | 在用户话轮未正式结束但语义和时机允许时，可以启动常规回答 |
| 用户打断停播 | 用户有效插话后停止未完成播放并恢复监听 |
| 单一输出仲裁 | 同一时刻只有一个模块决定哪个候选输出进入 TTS |
| 单一播放所有权 | 只有一个组件提交、开始、停止和完成播放 |
| 可观测性 | 音频、ASR、决策、生成、TTS、播放和打断事件能串成一条时间线 |

### 3.2 阶段与门禁

| 阶段 | 核心目标 | 主要产物 | 继续条件 |
| --- | --- | --- | --- |
| P0 路线重置 | 固定 X-Talk 来源、环境和记录格式 | conda 环境、配置、来源登记 | 基础环境与日志脚手架可重复运行 |
| P1 X-Talk 功能对齐 | 建立原生基线并补齐目标双工行为 | X-Talk 基线、差距表、改造运行时、FDB smoke | 目标行为稳定且关键事件可观察 |
| P2 快速可行性验证 | 验证话轮内澄清现象和闭环 | 小样本、规则/提示策略、试交互报告 | 存在足够可问窗口且任务可恢复 |
| P3 数据与评测基础设施 | 形成可训练、可审计的数据资产 | 回放器、标注格式、切分和检查工具 | 无未来泄漏，正负轨迹覆盖充分 |
| P4 决策方法与可选训练 | 固定 Layer 2 方法并完成对照 | 各策略、可选 LoRA、消融结果 | 主方法在固定底座上有稳定收益 |
| P5 系统测试与正式评价 | 验证通用能力和论文主张 | FDB 对照、真人实验、最终报告 | 结果支持或清楚限定研究主张 |

P1 和 P2 是最早的两个强制门禁。P2 未通过前，不开展大规模数据生产、训练或正式真人实验。

## 4. P0：路线重置与工程准备

### 4.1 目标

保留已有的通用配置、运行清单、事件日志和集群脚手架，移除 DuplexCascade 专属资产，并为 X-Talk 改造建立唯一来源记录。

### 4.2 工作项

1. 在 `configs/base.yaml` 固定 X-Talk 仓库地址与源码提交；当前起点记录在 [p0/xtalk_registry.md](p0/xtalk_registry.md)。
2. 明确集群镜像 `xtalk:v0.17` 与源码提交的对应关系；对应关系未证明前，不把镜像标签当作可复现版本。
3. 用 conda 创建本地和远端环境；P1 选择具体 ASR、TTS、LLM agent 和 turn detector 后，再锁定相应 X-Talk extras。
4. 保留 local / replay / cluster 三类配置、唯一运行目录和结构化事件日志。
5. 重新检查音频采样率、客户端 VAD、服务端 turn detector、AEC 和播放设备条件。
6. 集群测试前在 `docs/jobs/` 新建 X-Talk 专用任务单和对应脚本。

### 4.3 P0 验收门槛

- 全新 conda 环境能运行当前 P0 测试和离线冒烟；
- X-Talk 来源提交、许可证状态和镜像对应关系有明确记录；
- 配置和 manifest 不再引用 DuplexCascade 或 Kyutai；
- 同一离线输入在相同配置下产生结构一致的日志。

## 5. P1：基于 X-Talk 的功能对齐

具体扩展点、事件协议、响应生命周期、文件布局和测试矩阵见 [xtalk_modification_plan.md](xtalk_modification_plan.md)。本节定义阶段门禁；该方案文档定义实现细节。

### 5.1 P1.0 固定并导入 X-Talk

- 使用固定提交的独立 checkout、fork 或可编辑安装；不得追踪浮动的 `main`。
- 记录 X-Talk 核心依赖和实际启用的 optional extras。
- 选择一套最小可本地部署的 ASR、LLM agent、TTS、VAD/turn detector 组合；所有后续策略共享该组合。
- 跑通 X-Talk 原生示例，保存启动配置、首包延迟、实时因子、显存和事件日志。
- 在未完成来源与许可证核验前，不把 X-Talk 源码直接复制进本仓库。

### 5.2 P1.1 原生基线与差距审计

先不接入 InterClarify，逐项验证第 3.1 节能力。形成机器可读的差距表，每项标为：

- `SUPPORTED`：X-Talk 固定版本原生满足；
- `ADAPT`：已有扩展点，需 InterClarify 适配器；
- `PATCH`：必须修改固定版本的上游实现；
- `BLOCKED`：受模型、设备或环境阻塞。

重点检查 X-Talk 的 `EventBus`、`TurnDetectorManager`、`TurnTakingManager`、LLM generation manager、TTS response coordinator 和 TTS playback manager。类名和事件名以固定提交为准，升级后必须重新审计。

### 5.3 P1.2 最小功能改造

#### micro-turn 调度

新增短窗口调度器，默认以 0.6 秒作为实验起点，同时允许由 ASR partial、停顿和轮次检测事件提前触发。调度器只发布 tick，不直接生成或播放。

#### Layer 0/1 映射

- Layer 0 根据说话状态、停顿和上下文提交 `SILENCE` 或 `BACKCHANNEL` 候选。
- Layer 1 根据当前可见前缀提交 `SILENCE`、`ANSWER` 或 `REQUEST_LAYER2`。
- 两层可以复用同一 LLM/turn detector 的不同结构化输出，不要求先训练独立模型。
- X-Talk 原有句末生成仍作为安全回退。

#### 单一仲裁器

所有层输出统一转换为带有 `session_id`、`turn_id`、`prefix_version`、`priority`、`kind` 和 `payload` 的候选。`OutputArbiter` 是唯一选择器，不能直接操作音频设备。

#### 单一播放所有者

选中的候选进入 X-Talk 的 TTS 协调与播放链路。播放 manager 是唯一所有者，并显式区分：

```text
generated -> tts_requested -> tts_ready -> playback_committed
          -> playback_started -> playback_stopped | playback_finished
```

`playback_committed` 之前允许高优先级候选取消；提交后只能通过用户打断停止剩余音频，不能声称撤销已播内容。

#### 持续监听与用户打断

系统播放期间 ASR/VAD/turn detector 继续工作。有效用户插话触发停止生成和播放、关闭旧候选，并让会话回到监听状态。环境噪声、回声和短 backchannel 不应自动视为正式打断。

### 5.4 P1.3 统一事件日志

至少记录：

```text
audio_chunk_received
asr_partial / asr_revision / asr_final
vad_speech_start / vad_speech_end
micro_turn_tick
layer0_decision / layer1_decision
arbiter_selected / arbiter_rejected
tts_requested / tts_ready
playback_committed / playback_started / playback_stopped / playback_finished
user_barge_in
```

每条事件包含单调时钟时间、会话 ID、话轮 ID、片段 ID、输入前缀版本、来源模块和必要载荷。文本必须区分“模型生成”“已提交 TTS”“已经播放”。

### 5.5 P1.4 FDB 与验收门槛

- 先对固定的原生 X-Talk 基线运行 Full-Duplex-Bench smoke，再运行功能对齐版本；
- 两者使用同一 ASR、TTS、音频后端、数据版本和判分脚本；
- 优先检查停顿、backchannel、顺畅接话、用户打断和重叠语音；
- 不以复现 DuplexCascade 论文数值作为成功标准。

进入 P2 前必须确认：

- 系统发声时仍能接收用户输入；
- backchannel、正式回答和澄清候选在日志中可区分；
- 用户打断能停止未完成播放并继续同一会话；
- 同一输入可从音频、ASR、决策、仲裁追踪到播放；
- 原生 X-Talk 与功能对齐版本都有 FDB smoke 或明确阻塞记录；
- 没有第二套仲裁器或第二个 TTS 播放所有者。

## 6. P2：快速可行性验证

### 6.1 本阶段只回答三个问题

1. 真实流式语音前缀中是否存在足够多“有后果、尚未解决、可问可接、可恢复”的窗口？
2. 最小 Layer 2 是否比单纯 ASR 不确定性更准确地选择这些窗口？
3. 用户回答后，系统能否把答案并回原任务并完成正确动作？

本阶段不追求模型最优，也不生产正式训练集。

### 6.2 最小数据与 Layer 2

围绕日程时间选择准备约 30–50 条探索轨迹，覆盖持续歧义、自行消歧、ASR 修订和无后果不确定性。音频按原速进入固定的 X-Talk ASR 链路，保存当时可见的 partial、revision 和 final。

Layer 2 输入固定为：

```text
session_id
turn_id
prefix_version
visible_asr_prefix
asr_revision_summary
task_state_visible_to_system
speech_state: SPEAKING | PAUSING | ENDED
request_time
```

输出固定为：

```text
decision: NO_OVERRIDE | CLARIFY
question: string | null
candidate_interpretations: list
consequence_difference: string | null
self_resolution_risk: low | medium | high
prefix_version
```

只有结果版本有效、问题非空、歧义仍存在且目标音频尚未提交播放时，仲裁器才接受澄清覆盖。

### 6.3 状态机与门禁

单写者状态机为：

```text
LISTENING -> CANDIDATE_PENDING -> CLARIFYING -> WAITING_FOR_REPLY
          -> ANSWERING -> LISTENING
```

Layer 2 请求绑定 `prefix_version`；关键 ASR 修订、用户自行消歧或任务改变会使旧请求失效。用户回复被解析为原任务状态补丁，而不是新建无关任务。

采用盲前缀审计、脚本化闭环和小规模真人试交互。Go 门槛至少包括 15 个经审计的可澄清窗口、大多数澄清能被理解并恢复任务、错误插话没有压倒潜在收益。若两轮验证仍主要观察到自然自我消歧或任务无法恢复，则停止大规模训练并收缩主张。

## 7. P3：数据与评测基础设施

P2 通过后再建立正式数据流程。每个会话记录原始音频、隐藏任务目标、ASR 时间线、决策窗口前缀、候选解释、分歧出现与消失时间、允许动作、系统干预后的用户响应和最终结果。

标注者先看前缀视图，完整轨迹只用于记录用户后来是否自行消歧。程序检查时间戳单调、前缀无未来文本、候选结果确实不同、版本引用存在。按说话人和场景划分 train/dev/test。

回放器提供实时时钟和虚拟时钟；所有策略读取同一事件流，原录音后半段不能当作系统插话后的真实反应。

## 8. P4：决策方法、对照与可选训练

固定底座上至少实现：

1. 原生 X-Talk：不主动澄清；
2. 功能对齐 X-Talk：具备 Layer 0/1，但不启用 Layer 2；
3. Wait-until-end；
4. Uncertainty-trigger；
5. Direct-LLM；
6. InterClarify；
7. 若采用按需调用，再比较逐窗口强模型与同等调用预算的触发策略。

开发顺序固定为规则、结构化提示、误差分析、必要时训练。训练只覆盖关键分歧识别、接话时机、`NO_OVERRIDE` 和短问题生成；默认冻结 ASR、TTS、X-Talk 轮次控制和通用 LLM agent。

至少消融语义分歧、自行消歧线索、说话/停顿状态和前缀版本检查。训练方案若未超过提示基线，就保留提示方案。

## 9. P5：系统测试与正式评价

### 9.1 测试层次

- 单元：前缀版本、仲裁优先级、播放提交边界、用户插话停播、任务状态合并和未来泄漏；
- 确定性集成：Layer 2 提前/延迟/超时、ASR 修订、澄清中途插话、连续候选窗口和不同播放状态；
- 实时回归：延迟抖动、长会话积压、回声、噪声、重叠语音、进程超时与安全降级；
- 系统能力：原生 X-Talk、功能对齐 X-Talk 和最终 InterClarify 使用同一 FDB 适配器。

### 9.2 正式指标

分别报告时机得体性、问题相关性、可回答性、真人接话顺畅度、最终任务正确率、澄清后恢复率、插话次数、用户重复次数、完成时间、模型调用次数、端到端延迟和峰值显存。不得压成未经验证的单一“真人感”分数。

## 10. 核心模块与接口边界

| 模块 | 职责 | 禁止行为 |
| --- | --- | --- |
| `XTalkRuntimeAdapter` | 连接固定版本 X-Talk 的事件和会话接口 | 不复制第二套服务运行时 |
| `StreamingPrefixTracker` | 产生 partial、revision、final 和版本 | 不读取任务真值 |
| `MicroTurnScheduler` | 发布固定/事件驱动 tick | 不直接决定输出 |
| `Layer01Policy` | 产生 L0/L1 候选 | 不阻塞等待 Layer 2 |
| `ClarificationTrigger` | 决定是否发起 Layer 2 请求 | 不直接播放 |
| `Layer2Policy` | 判断等待/澄清并生成短问题 | 不使用未来输入 |
| `ResultValidator` | 检查版本、任务和自行消歧状态 | 不改写已播内容 |
| `OutputArbiter` | 单点选择 L2/L1/L0 输出 | 不拥有播放设备 |
| `XTalkPlaybackBridge` | 把唯一选中结果交给 X-Talk 播放链路 | 不创建第二个 TTS 队列 |
| `TaskStateReducer` | 把澄清回答合并回同一任务 | 不另开无关任务 |
| `EventRecorder` | 保存时间线、配置和结果 | 不把离线真值注入在线模块 |

Layer 2 结果必须同时满足会话、话轮、前缀版本、任务状态、歧义状态、问题非空和目标片段未提交等条件；否则记录过时或拒绝原因并回退到 Layer 1/0。

## 11. 建议仓库结构与文档映射

按实现进度逐步建立，不创建空目录：

```text
InterClarify/
├── configs/
├── scripts/
│   ├── run_xtalk_baseline.py
│   ├── replay_session.py
│   └── run_evaluation.py
├── src/interclarify/
│   ├── xtalk/
│   ├── layers/
│   ├── arbitration/
│   ├── playback/
│   ├── task/
│   ├── data/
│   └── evaluation/
├── tests/
├── experiments/
└── docs/
```

新实现必须同步增加对应文档；例如 `src/interclarify/xtalk/runtime.py` 对应 `docs/src/interclarify/xtalk/runtime.md`。第三方代码不逐文件复制文档，但必须记录来源、提交、许可证和补丁。

## 12. 实验记录与产物管理

每次运行使用唯一 `run_id`，至少包含：

```text
manifest.json
resolved_config.yaml
events.jsonl
metrics.json
environment.txt
artifacts/
```

数据、权重和大体积音频不进入 Git。manifest 必须记录 InterClarify 提交、X-Talk 提交、启用的组件配置和模型修订。

## 13. 风险与收缩策略

| 风险 | 最早阶段 | 应对方式 |
| --- | --- | --- |
| X-Talk 接口快速变化 | P0/P1 | 固定提交，升级前做差距审计和回归 |
| 镜像与源码版本不一致 | P0 | 记录镜像 digest，验证安装包与提交；未验证不作为基线 |
| 组件依赖或许可证冲突 | P0/P1 | 按实际启用 extras 锁定并完成许可证审计 |
| 原生轮次控制缺少 micro-turn/backchannel | P1 | 通过事件和 manager 扩展，必要时维护最小上游补丁 |
| 多模块争抢 TTS | P1 | 单一仲裁器和单一播放所有者测试作为硬门槛 |
| ASR 修订能力不足 | P1/P3 | 更换统一 ASR，所有方法共享相同底座 |
| Layer 2 延迟导致过时覆盖 | P2/P4 | 版本失效、超时和轻量触发 |
| 真实可澄清窗口太少 | P2 | 调整单一任务域或收缩为句末澄清 |
| 澄清后任务无法恢复 | P2 | 优先修复状态合并，暂停扩大数据与训练 |

## 14. 近期执行清单

1. 固定并核验 X-Talk 提交、镜像 digest、许可证与可选依赖；
2. 在 conda 环境中跑通原生 X-Talk 最小本地链路；
3. 建立第 3.1 节能力差距表和原生 FDB smoke；
4. 依次实现 micro-turn、Layer 0/1 候选、单一仲裁、单一播放与统一日志；
5. 保存功能对齐版本的 FDB smoke；
6. 构造 30–50 条日程时间域探索轨迹；
7. 实现规则/提示版 Layer 2、版本检查和任务恢复；
8. 完成盲前缀审计、脚本化闭环和小规模真人试交互；
9. 形成 go / revise / stop 报告；
10. 只有得到 go 结论后，才扩展正式数据、训练和完整测试。

这条路线把工程重点从“复现另一个完整系统”转为“在可维护的 X-Talk 模块化底座上实现并验证所需行为”，同时保持研究问题、动作边界和评测严谨性不变。
