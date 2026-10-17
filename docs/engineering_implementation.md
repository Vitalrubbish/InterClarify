# InterClarify 分阶段工程落地方案

## 1. 文档目的与路线决策

本文把 [research_design.md](research_design.md) 中的研究构想转换为可执行、可验收和可停止的工程计划。

## 当前状态（2026-10-16 清理后）

ASR 比较实验已经结束，保留 `reports/` 的全部结果与 [选型决定](asr_selection_decision.md)，移除一次性下载、评测、对齐、日志诊断、接话重放工具及其测试和镜像说明。Qwen3-ASR 的修订窗口与已提交前缀冲突会导致不可接受的交付停滞，按用户要求退役其服务、配置、旧联调作业与镜像依赖，不再作为失败回退。历史验收记录只用于解释结果，不再代表可执行任务。

Nemotron EN 160ms 是后续英文主线，尚未完成运行时接入与 Layer 1 验收；现有 X2 链路仅保留作回归诊断，运行 A4 时必须显式选择 `DUPLEX_ASR_BACKEND=x2` 并提供其独立 conda prefix、源码和权重。通用 MOSS、官方控制服务、FDB 驱动和播放链路保留。清理范围及历史源码恢复位置见 [清理记录](asr_cleanup.md)。以下分阶段与历史执行记录中的 Qwen 保留要求被本段取代，Layer 边界和研究范围不变。

当前处于**阶段 A 验收**：驱动/运行时/服务与 FDB 四轴推理都已跑通；四轴指标与读法见 [A4 任务单](xtalk_a4_remote_acceptance.md) §9.7–§9.9，其中 §9.9 是 2026-10-16 的 X2Streaming-ASR 单变量替换复测（ASR 替换尚未达标，遗留项见 [X2 复测任务单](x2streaming_asr_retest.md) §10）。本仓库仍不实现第二套语音运行时或 Layer 2；原生链路的历史门禁与来源固定见 [xtalk_baseline_stack.md](xtalk_baseline_stack.md)。

阶段 A 的实现分布在 X-Talk fork 与 `scripts/remote/`：fork 提交与基线见 [xtalk_baseline_stack.md](xtalk_baseline_stack.md)，改动清单、逐轮验收数字与仍挂着的待办见 [A4 任务单](xtalk_a4_remote_acceptance.md)。本地门禁：X-Talk 全量 142 项（139 PASS、3 skipped）、InterClarify root 80 项。

2026-10-17 TTS 优化规划：在 `feature/tts-latency-optimization` 分支按 [TTS 优化 issues](issues/tts_001_latency_instrumentation.md) 依次补齐计时、降低批量生成的帧数、覆盖每轮开头的编译路径，再按实测占比优化 prefill、codec 或 backbone。保留批量交付，以供音连续和自然度约束批次大小，不默认逐帧发送；不更换 ASR/LLM、不改变话轮策略，不新增播放所有者。已实现测量工具及默认关闭的批次/开头编译实验路径，本地逻辑验证通过；远端基线、音质和集成验收未执行，见 [远端任务单](tts_latency_remote_tasks.md)。

自 2026-10-09 起，项目不再直接复现、内嵌或改造 DuplexCascade 官方源码。新的工程路线是：

1. 以独立维护的 [Vitalrubbish/xtalk](https://github.com/Vitalrubbish/xtalk) fork 为唯一运行底座；
2. 先在 X-Talk fork 中实现通用的 DuplexCascade 功能层，再由独立的 InterClarify 项目接入 Layer 2；
3. 2026-10-12 用户指定阶段 A 先使用远端官方 DuplexCascade 权重，输入触发与实际 special token 遵循固定官方推理实现；ASR/TTS 与播放继续使用 X-Talk，训练另行决策；
4. 先冻结第一套原生 X-Talk 组件组合，再在阶段 A 实现 DuplexCascade 无 System Backchannel 版本的功能：micro-turn、Layer 1、提前回答、用户打断停播和持续监听；阶段 B 才接入 InterClarify 的 Layer 2；
5. 快速验证话轮内主动澄清是否值得继续，只有通过门禁后才扩大数据、训练和真人实验。

因此，旧路线中的 `3rd-party/DuplexCascade`、官方权重准备脚本、Kyutai `moshi-server` 编排、官方控制模型适配器及其测试和实验产物均不再属于当前实现。

本次收缩依据用户决定：从当前改造范围移除 Layer 0 和系统附和输出，先建立更简单的无 System Backchannel 底座。论文第 4.1 节将无系统附和版称为 DuplexCascade，有系统附和版称为 DuplexCascade-β，见[原文](https://arxiv.org/html/2603.09180v1#S4.SS1)。用户附和识别仍属于保留能力。第一套组件候选及冻结门禁见 [xtalk_baseline_stack.md](xtalk_baseline_stack.md)。

**2026-10-14 仓库清理**：按"只保留原生 X-Talk 复现 + 阶段 A 最终实现"的口径，移除了 P0 阶段建立的通用配置/清单骨架（`src/interclarify/`、`configs/{base,local,replay,cluster}.yaml`、`docs/src/`、`scripts/run_p0_smoke.py`、`tests/test_p0_artifacts.py`）与全部一次性诊断作业及其产物；环境自检脚本 `scripts/check_env.py`、`scripts/check_audio_io.py` 保留。第 4 节记录的 P0 工作项因此不再有对应实现，后续 P2 的数据/评测骨架从第 11 节的结构重新建立。清理明细与结论去向见 [A4 任务单](xtalk_a4_remote_acceptance.md) §13。

**2026-10-15 补充清理**：TTS 吞吐 A/B 三件套与 FDB 录制窗口方案按 §13.1 移除（数字保留在任务单）；ASR 流式契约对比工具**保留**为后续 ASR 改动的回归工具（§9.4 的语言跑飞仍待修）；任务单中 2026-10-13～10-14 的调试过程叙事已压缩为结论，`data/runs/` 只保留每轮原始产物与提交记录。

## 2. MVP 范围与不可破坏的边界

2026-10-16 ASR 选型实验：用户授权在远端下载并比较 Nemotron 英语版、Nemotron 3.5 和 Kyutai 1B。新增离线评测入口仅用于按真实时间送入音频及记录输出，不建设第二套产品运行时。统一使用 FLEURS `en_us/test` 的确定性子集，独立 conda 环境；用户随后允许多个独占 GPU 作业并行，并澄清标点是为官方 DuplexCascade 及时回复服务的诊断因素，而非硬性门禁。因此扩展测试按五个分片并行、轮次间轮换配置，并补充官方权重对真实 ASR 文本轨迹的接话验证；测试协议、指标限制及版本见 [任务单](https://github.com/Vitalrubbish/InterClarify/blob/6c75f38d659998d6f149923085d82c0d7db267c5/docs/asr_selection_benchmark.md)。现役 ASR 和双工策略保持冻结，实验后再决定替换。

2026-10-16 后续路线：根据实测及用户提出的去标点训练方向，后续英文主线选择 Nemotron EN 0.6B/160ms，Kyutai 留作官方控制权重对照。EN 与未适配官方权重的接话尚未达标，不能直接宣布替换完成。允许规划以现有 Layer 1 q/v LoRA 为对象的小规模标点鲁棒性对照，先做数据盘点和资源短跑，不提前开展大规模训练；细节和回归条件见 [选型决策](asr_selection_decision.md)。这项底座适配不改变 Layer 2 的研究范围，也不新增运行时、仲裁器或播放路径。

### 2.1 当前研究范围

MVP 只选择一个可程序核验结果的任务域，默认采用**日程安排中的日期和时间选择**。系统研究对象仍是 Layer 2 的澄清判断与交互闭环：

- 当前前缀是否存在会改变任务结果的解释分歧；
- 分歧是否仍未解决，用户是否可能马上自行说明；
- 当前是否适合接话；
- 能否生成一个具体、简短、可回答的问题；
- 收到回答后能否恢复同一个任务。

X-Talk fork 提供 ASR、LLM agent、TTS、VAD、轮次检测、异步事件和 WebSocket 服务基础。InterClarify 不建设第二套并行语音运行时，也不把复现 DuplexCascade 的模型或训练流程作为前置条件。

### 2.2 Layer 与动作边界

- 当前移除 Layer 0：不注册该策略，不产生系统 `BACKCHANNEL` 候选，不加载系统附和模型或预录音频。未来若恢复，须先更新范围和评测方案，其动作边界仍为 `SILENCE` / `BACKCHANNEL`。
- Layer 1 采用 DuplexCascade 无 System Backchannel 的五种状态 token，由 LLM 直接生成；阶段 A 的运行时适配器只解析并执行 token，不重新判断语义。它可请求 Layer 2，但阶段 A 不设置独立跨层仲裁器。
- Layer 2 只产生 `NO_OVERRIDE` 或澄清问题；识别到歧义也可以选择等待。
- 当前不启用 Layer 3；只预留版本化修订接口。若后续启用，Layer 3 只能修订尚未提交播放的片段。
- 阶段 A 只有一个 DuplexRuntimeAdapter，执行 DuplexCascade LLM 产生的细粒度状态 token；阶段 B 同时启用 Layer 2 后，才引入跨层 `OutputArbiter`，优先级为 Layer 2 > Layer 1。
- 只允许一个 TTS 播放所有者。X-Talk 的播放管理链路是唯一提交点，其他模块只能提交播放意图。
- 已经播放给用户的内容不可撤销。高优先级结果只能取消或替换尚未提交的片段。
- 在线策略只能读取决策时刻以前到达的音频、ASR 前缀、修订和运行状态；隐藏目标、完整转写和未来输入只用于数据构建与评价。

### 2.3 对 X-Talk 的改造原则

- 固定上游提交后再开发；镜像标签不能代替源码提交记录。
- 通用双工能力直接在 X-Talk fork 中实现；InterClarify 专属代码留在本仓库，等底座稳定后通过公开扩展接口接入。
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
| micro-turn | 按固定或事件驱动的短窗口检查是否保持静默或回答；无新增文本的窗口也需处理等待状态 |
| 无 System Backchannel | 用户说话时不输出系统附和；包括 Agent 的预录音频路径和正式回答路径中的伪附和 |
| User Backchannel | 系统说话时识别用户短附和，避免无条件停播；有效插话仍可打断 |
| 提前回答 | 在用户话轮未正式结束但语义和时机允许时，可以启动常规回答 |
| 用户打断停播 | 用户有效插话后停止未完成播放并恢复监听 |
| 单层协议执行 | 阶段 A 由 DuplexRuntimeAdapter 执行 LLM 状态 token 与 TTS 请求；跨层场景再增加仲裁 |
| 单一播放所有权 | 只有一个组件提交、开始、停止和完成播放 |
| 可观测性 | 音频、ASR、决策、生成、TTS、播放和打断事件能串成一条时间线 |

### 3.2 阶段与门禁

| 阶段 | 核心目标 | 主要产物 | 继续条件 |
| --- | --- | --- | --- |
| P0 路线重置 | 固定 X-Talk 来源、环境和记录格式 | conda 环境、配置、来源登记 | 已完成；后续只修复发现的记录问题 |
| P1 X-Talk Duplex | 在已接通底座上实现无 System Backchannel 的 Layer 1 行为 | 组件锁定记录、差距表、改造运行时、FDB smoke | 目标行为稳定且关键事件可观察 |
| P2 快速可行性验证 | 验证话轮内澄清现象和闭环 | 小样本、规则/提示策略、试交互报告 | 存在足够可问窗口且任务可恢复 |
| P3 数据与评测基础设施 | 形成可训练、可审计的数据资产 | 回放器、标注格式、切分和检查工具 | 无未来泄漏，正负轨迹覆盖充分 |
| P4 决策方法与可选训练 | 固定 Layer 2 方法并完成对照 | 各策略、可选 LoRA、消融结果 | 主方法在固定底座上有稳定收益 |
| P5 系统测试与正式评价 | 验证通用能力和论文主张 | FDB 对照、真人实验、最终报告 | 结果支持或清楚限定研究主张 |

P1 和 P2 是最早的两个强制门禁。A1–A3 已通过本地实现门禁；A4 远端任务、真实音频与 FDB 证据仍是 P1 控制层的完成条件。P2 未通过前，不开展大规模数据生产、训练或正式真人实验。

## 4. P0：路线重置与工程准备

### 4.1 目标

保留已有的通用配置、运行清单、事件日志和集群脚手架，移除 DuplexCascade 专属资产，并为 X-Talk 改造建立唯一来源记录。

### 4.2 工作项

1. 固定 X-Talk fork、官方 upstream、适配器提交和基座提交；当前来源和验收证据登记在 [xtalk_baseline_stack.md](xtalk_baseline_stack.md)（原先用于固定的 `configs/base.yaml` 已随 2026-10-14 清理移除，来源改由该登记表与 [configs/xtalk_round1.yaml](../configs/xtalk_round1.yaml) 承担）。
2. 明确集群镜像 `xtalk:v0.17` 与源码提交的对应关系；对应关系未证明前，不把镜像标签当作可复现版本。
3. 用 conda 创建本地和远端环境；P1 选择具体 ASR、TTS、LLM agent 和 turn detector 后，再锁定相应 X-Talk extras。
4. 保留 local / replay / cluster 三类配置、唯一运行目录和结构化事件日志。
5. 重新检查音频采样率、客户端 VAD、服务端 turn detector、AEC 和播放设备条件。
6. 集群测试使用当前联调入口，并把来源、配置和结果摘要回填到 [xtalk_baseline_stack.md](xtalk_baseline_stack.md)。

### 4.3 P0 验收门槛

- 全新 conda 环境能运行当前 P0 测试和离线冒烟；
- X-Talk 来源提交、许可证状态和镜像对应关系有明确记录；
- P0 原生基线配置保留；P1 duplex 配置单独固定官方 DuplexCascade 权重，不新增 Kyutai 运行时；
- 同一离线输入在相同配置下产生结构一致的日志。

## 5. P1：在 X-Talk fork 中实现 DuplexCascade 功能层

具体扩展点、事件协议、响应生命周期、文件布局和测试矩阵见 [xtalk_modification_plan.md](xtalk_modification_plan.md)。P1 交付无 System Backchannel 的 Layer 1 全双工底座。当前组件与连接配置已固定，A1 已通过本地门禁，当前实现 A2 micro-turn 组装和 A3 在线协议执行；正式质量、性能与 FDB 冻结不再作为 A1 的前置任务。这延续用户先接通框架、再逐步改造的安排，P2 的准入门槛仍按第 5.5 节执行。

### 5.1 P1.0 固定并导入 X-Talk

- 在独立 X-Talk fork 中开发；`origin` 指向 `Vitalrubbish/xtalk`，`upstream` 指向官方仓库，不使用子模块。
- 记录 X-Talk 核心依赖和实际启用的 optional extras。
- 按 [xtalk_baseline_stack.md](xtalk_baseline_stack.md) 选择一套自部署的 ASR、LLM agent、TTS、VAD/turn detector 组合；实际权重 revision、服务提交和推理参数核验后才视为冻结。所有后续策略共享该组合。
- 当前连接配置固定到 X-Talk fork `feature/qwen3-asr-adapter@d9303c819c96230e527ea5159e7c74f1b5841a3e`，组件为 Qwen3-ASR 1.7B + MOSS-TTS-Realtime（含 codec）、Qwen3-8B-AWQ 和 TurnSense，见 `configs/xtalk_round1.yaml` 与 [xtalk_baseline_stack.md](xtalk_baseline_stack.md)。该提交已经通过最小联调，后续控制层开发不得漂移来源。
- 框架接通门禁已经完成，证据摘要见 [xtalk_baseline_stack.md](xtalk_baseline_stack.md)。中文质量评测、延迟预算、长会话和 FDB 留到 P1 控制层稳定后；人为分块的 TTS 首包仍只是独立服务指标，不能单独宣称端到端或全双工复现完成。
- 跑通 X-Talk 原生示例，保存启动配置、首包延迟、实时因子、显存和事件日志。
- 在未完成来源与许可证核验前，不把 X-Talk 源码直接复制进本仓库。

### 5.2 P1.1 原生基线与差距审计

先不接入 InterClarify，逐项验证第 3.1 节能力。形成机器可读的差距表，每项标为：

- `SUPPORTED`：X-Talk 固定版本原生满足；
- `ADAPT`：已有扩展点，可在 X-Talk Duplex 控制层中适配；
- `PATCH`：必须修改固定版本的上游实现；
- `BLOCKED`：受模型、设备或环境阻塞。

重点检查 X-Talk 的 `EventBus`、`TurnDetectorManager`、`TurnTakingManager`、LLM generation manager、TTS response coordinator 和 TTS playback manager。类名和事件名以固定提交为准，升级后必须重新审计。

### 5.3 P1.2 最小功能改造

#### micro-turn 调度

2026-10-15 用户授权接入 X2Streaming-ASR：增加独立在线服务和 X-Talk 客户端，80 ms 音频输入，默认英语。X2 在线追加输出直接交付，不经过 Qwen 的保留 token、冲突冻结或 final 后分段重建。显式关闭离线覆盖。ASR 接口增加连续音频能力标志；此类实现声学暂停期间继续接收静音，实际结束才关闭在线流。原 600 ms micro-turn、模型与 MOSS 播放链路保持不变。

客户端实现固定为 X-Talk `48c5952`；X2 源码 `0aca80597bb1399c0be4002de5bc62c0a779c542`、权重 `4c8df16b8d7f8b50c95590c4d7907436ebe4aa08`。本地 X-Talk 150 项测试通过（3 skipped），主仓库 35 项相关测试通过；真实模型质量与性能仍须远端复测。

2026-10-15 远端准备：`scripts/remote/setup_x2_asr_env.sh` 在共享盘新建独立 conda prefix `xtalk-x2-asr`（官方 `torch==2.11.0+cu128` / `transformers==5.15.1`，与 Qwen/MOSS 环境隔离），稀疏检出固定源码提交并下载固定 revision 权重到 `interclarify-x2/`；A4 节点入口新增 `DUPLEX_ASR_BACKEND=x2` 分支、X2 资产前置校验与 X2 服务单测。对照复测的范围、口径与证据边界见 [X2 复测任务单](x2streaming_asr_retest.md)。

2026-10-16 复测结果：首轮 `20261015T172109Z` 因首个会话冷启动吞掉整段 `pause` 语音而 FAIL；服务增加启动预热后用 `04536cf` 重跑 `20261015T180154Z`，自动门禁与 FDB 五轴推理全 PASS。FDB 官方评分显示 `pause_handling` 两子集 TOR=0.00；**Candor Pause Handling 的沉默符合预期，TOR 0.40→0.00 是正向结果**。`smooth_turn_taking` TOR 0.80→0.40、`user_interruption` TOR 1.00→0.80、latency 2.384→3.26s；UI 真正启动新回答为 3/5，不能用官方 TOR 代替该指标。本轮 judge 改用 `gpt-6-sol`，rating 不跨轮比较。在线文本单调；滞后增长量中位 -0.02s 不是绝对识别延迟。首会话仍有秒级堆积，异步末次输出缺少独立接收，真实输入结束没有 flush，synthetic pause 五例均缺参考末词。**ASR 替换尚未达到可宣称成功的程度**。后续以 [X2 复测任务单](x2streaming_asr_retest.md) §10 为统一清单：先修结果交付、真实 EOF、完整预热和测量，再定位 micro-turn 等待、轮次误判与 TTS 首音延迟；保持阶段 A 范围及单一播放所有权。

新增短窗口调度器，默认 0.6 秒；partial、停顿和 final 只更新缓冲，串行生成完成后才 flush 下一窗口。累计前缀以增量发送；修订、空窗口和 final 去重见改造计划第 13 节。

2026-10-16 用户确认的 F1 方案：会话启动即运行唯一 micro-turn 时钟，每一拍在组装输入前请求 ASR 最新在线累计文本。X2 对空音频、非 final 的读取调用只读 HTTP 接口；不新增轮询时钟，不追加静音、不结束流、不等待未来 emit。取到的新增后缀按原官方 ChatML 协议送 LLM，没有新增则由原模型服务编码为 `<|no voice|>`，首条识别前也如此。ASR 音频提交保持独立连续，客户端创建/读取/删除串行化；结果必须先更新前缀再生成本拍快照。暂停与真实 EOF 继续分开，F2/F3 及 TTS、窗口优化不纳入本次实现。

2026-10-16 用户要求移除 X2 duplex 的声学 VAD：服务根据 continuous_audio 能力派生 acoustic_vad_enabled=false，移除 VAD manager；X2 配置不再加载 Silero。会话握手将能力告知浏览器及回放客户端，二者仅发送连续 PCM，不发送声学 speech start/end；网关忽略旧客户端的这两类信号，micro-turn 不再发布 pause/resume。唯一 ASR 启动来自会话启动事件；每拍读取机制保持不变。文本提交所需的内部合成边界保留，不代表声学检测。Qwen 对照保留原声学暂停机制。此项不实现 EOF 收尾，也不宣称真实模型延迟已经改善。

2026-10-16 完整预热与复测：X2 启动使用固定的非评测真实语音 WAV（16 kHz、单声道、PCM16），按 80 ms 追加到独立预热会话；等待非空在线转写，显式 EOF 并等待收尾完成，再释放会话，随后才启动 HTTP 服务。启动错误、空输出和超时均直接失败，不以静音入队代替 decode 完成。记录音频 SHA256、长度、首文本及 EOF 耗时，预热文字不进入测量会话。复测固定模型、MOSS、600 ms 和原五轴各 5 例；本轮包含 F1、移除 VAD 与 F3，不作单变量归因。ASR 改善与质量回归结果出来前保留 Qwen 路线。

2026-10-16 证据范围修正：独立 ASR/TTS smoke 的配置和锁定清单只记录实际参与该 probe 的模型；TTS 仅包含 MOSS 与 codec，不复制 Qwen ASR/LLM 清单。对已完成轮次的错误清单先归档原文件及摘要，再修正元数据；不改 WAV、时间线或评测结果。

#### Layer 1 映射

2026-10-15 修复契约：声学暂停只释放 ASR 尾部，不代表语义让轮。Qwen final 后新建片段解码状态，由服务拼接已释放前缀；重复空 final 幂等，final 同样不能覆盖已交付前缀。每请求记录 session、片段、raw/committed token 与冲突位置。分段失去跨段声学上下文，真实词尾质量必须远端复核。延迟按发生时刻和 request_id/response_id 关联，缺失关联留空。FDB 官方 WAV 保持输入等长，诊断长尾录音独立保存，不参与官方评分；传输成功与语义得分分开报告。

- DuplexCascade LLM 根据当前可见 micro-turn 输出 `<user is speaking>`、`<user finish speaking>`、`<user is interrupting>`、`<user backchannel>` 或 `<user is thinking>`；输入侧使用 `<no voice>` 和 `<EOS>`。
- `DuplexRuntimeAdapter` 只解析状态 token，执行等待、回答、停止剩余输出或保持当前回答，并记录原始 token；收到完整 `<|user interruption|>` 时，它立即结束当前 system micro-turn、关闭当前模型流并停止未播放音频，不等待 `<|im_end|>`。它不输出规则状态，也不把 `SILENCE`/`ANSWER` 当作训练协议。
- 不实现 Layer 0；显式关闭原生 Agent 的系统 backchannel 配置。
- Layer 1 使用官方 DuplexCascade 模型；实际 wire token 与论文语义映射见改造计划第 13 节。duplex 模式关闭原生 turn detector 的语义旁路。
- duplex 模式协议错误记录并停止未播放输出，不从句末旁路另行触发回答。
- 可以预留 higher-layer policy 接口，但 P1 不加载 Layer 2。

#### 单层控制与播放边界

阶段 A 不设置独立 `OutputArbiter`。`DuplexRuntimeAdapter` 是唯一的协议执行者，所有结果都带有 `session_id`、`turn_id`、`segment_id`、`prefix_version`、`state_token` 和 `reason`，并在进入 TTS 协调链路前完成上下文、去重、过期和提交边界检查。适配器不直接操作音频设备。

阶段 B 接入 Layer 2 后，再增加跨层 `OutputArbiter`，统一比较 Layer 2 与 Layer 1 的有效结果。

#### 单一播放所有者

通过检查的回答进入 X-Talk 的 TTS 协调与播放链路。播放 manager 是唯一所有者，并显式区分：

```text
generated -> tts_requested -> tts_ready -> playback_committed
          -> playback_started -> playback_stopped | playback_finished
```

`playback_committed` 之前允许高优先级候选取消；提交后只能通过用户打断停止剩余音频，不能声称撤销已播内容。

#### 持续监听与用户打断

系统播放期间 ASR/VAD/turn detector 继续工作。有效用户插话由模型输出 `<|user interruption|>` 确认；该完整 special token 触发停止生成和播放、立即结束当前 system micro-turn、关闭旧候选，并让会话回到监听状态。环境噪声、回声和用户短附和不应自动视为正式打断。原生组合保留其 VAD 条件作为基线；去掉 Layer 0 不等于完成 VAD-free 改造，当前只声明功能对齐。

### 5.4 P1.3 统一事件日志

A1 使用 X-Talk fork 的 `duplex_control/timeline.py` 记录原生事件，先补齐 request/response/turn/segment/prefix 字段的确定性传递、协议错误码和交付边界测试。补丁范围和审查原因见 [xtalk_modification_plan.md](xtalk_modification_plan.md) 第 8、10 节。A1 的完整输出解析器只产生协议观测；A2 建立 micro-turn 与前缀版本，A3 才接入在线协议执行。下方列表是 P1 最终日志目标，阶段 A 不产生跨层 arbiter 事件。

至少记录：

```text
audio_chunk_received
asr_partial / asr_revision / asr_final
vad_speech_start / vad_speech_end
micro_turn_tick
layer1_decision
arbiter_selected / arbiter_rejected
tts_requested / tts_ready
playback_committed / playback_started / playback_stopped / playback_finished
user_backchannel / user_barge_in
```

每条事件包含单调时钟时间、会话 ID、话轮 ID、片段 ID、输入前缀版本、来源模块和必要载荷。文本必须区分“模型生成”“已提交 TTS”“已经播放”。

### 5.5 P1.4 FDB 与验收门槛

- 先对固定的原生 X-Talk 基线运行 Full-Duplex-Bench smoke，再运行功能对齐版本；
- 两者使用同一 ASR、TTS、音频后端、数据版本和判分脚本；
- 优先检查停顿、用户附和、顺畅接话、用户打断和重叠语音；系统附和输出指标单列为范围外，不与有 System Backchannel 系统混为同一目标；
- 不以复现 DuplexCascade 论文数值作为成功标准。

进入 P2 前必须确认：

- 系统发声时仍能接收用户输入；
- 用户附和和有效打断在日志中可区分，系统附和候选和音频输出均为零；
- 用户打断能停止未完成播放并继续同一会话；
- 同一输入可从音频、ASR、决策、仲裁追踪到播放；
- 原生 X-Talk 与功能对齐版本都有 FDB smoke 或明确阻塞记录；
- 没有第二套仲裁器或第二个 TTS 播放所有者；
- higher-layer policy 扩展点存在，但未启用主动澄清。

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
2. 功能对齐 X-Talk：具备 Layer 1，关闭 System Backchannel，尚未启用 Layer 2；
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
| `DuplexCascade LLM` | 产生 DuplexCascade 状态 token | 不产生系统附和，不读取未来输入 |
| `DuplexRuntimeAdapter` | 解析并执行状态 token | 不重新判断语义，不直接拥有播放设备 |
| `ClarificationTrigger` | 决定是否发起 Layer 2 请求 | 不直接播放 |
| `Layer2Policy` | 判断等待/澄清并生成短问题 | 不使用未来输入 |
| `ResultValidator` | 检查版本、任务和自行消歧状态 | 不改写已播内容 |
| `OutputArbiter` | 阶段 B 选择 L2/L1 输出 | 阶段 A 不加载，不拥有播放设备 |
| `XTalkPlaybackBridge` | 把唯一选中结果交给 X-Talk 播放链路 | 不创建第二个 TTS 队列 |
| `TaskStateReducer` | 把澄清回答合并回同一任务 | 不另开无关任务 |
| `EventRecorder` | 保存时间线、配置和结果 | 不把离线真值注入在线模块 |

Layer 2 结果必须同时满足会话、话轮、前缀版本、任务状态、歧义状态、问题非空和目标片段未提交等条件；否则记录过时或拒绝原因并回退到 Layer 1。

## 11. 建议仓库结构与文档映射

P1 的 X-Talk Duplex 源码位于独立 fork，不出现在本仓库文件树中。以下结构从 P2 的 InterClarify 接入开始逐步建立，不创建空目录；P0 阶段曾建立的同类骨架已在 2026-10-14 清理中移除，当时只保留 X-Talk 复现与阶段 A 实现所需的 `configs/`、`scripts/remote/`、`tests/`、`docs/` 四类目录：

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

InterClarify 新实现必须同步增加对应文档；例如 `src/interclarify/xtalk/runtime.py` 对应 `docs/src/interclarify/xtalk/runtime.md`。X-Talk fork 遵循其自身文档约定，并在本仓库登记使用的提交、许可证和实验配置。

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
| 原生轮次控制缺少 micro-turn 或误判用户附和 | P1 | 通过事件和 manager 扩展，必要时维护最小上游补丁 |
| 多模块争抢 TTS | P1/P2 | 阶段 A 保持单协议执行者；跨层启用后以仲裁器和单一播放所有者测试作为硬门槛 |
| ASR 修订能力不足 | P1/P3 | 更换统一 ASR，所有方法共享相同底座 |
| Layer 2 延迟导致过时覆盖 | P2/P4 | 版本失效、超时和轻量触发 |
| 真实可澄清窗口太少 | P2 | 调整单一任务域或收缩为句末澄清 |
| 澄清后任务无法恢复 | P2 | 优先修复状态合并，暂停扩大数据与训练 |

## 14. 近期执行清单

1. 固定并核验 X-Talk 提交、镜像 digest、许可证与可选依赖；
2. 在 conda 环境中跑通第一套原生 X-Talk 自部署组合并冻结实际模型与参数；
3. 建立第 3.1 节能力差距表和原生 FDB smoke；
4. 依次实现 micro-turn、Layer 1 状态 token、单层控制、单一播放与统一日志；保持 System Backchannel 关闭；
5. 保存功能对齐版本的 FDB smoke；
6. 构造 30–50 条日程时间域探索轨迹；
7. 实现规则/提示版 Layer 2、版本检查和任务恢复；
8. 完成盲前缀审计、脚本化闭环和小规模真人试交互；
9. 形成 go / revise / stop 报告；
10. 只有得到 go 结论后，才扩展正式数据、训练和完整测试。

这条路线把工程重点从“复现另一个完整系统”转为“在可维护的 X-Talk 模块化底座上实现并验证所需行为”，同时保持研究问题、动作边界和评测严谨性不变。

## 2026-10-17 TTS 实验实现边界

为推进四项 issue，先准备默认关闭的批次/开头编译路径及确定性测试，原因是远端基线尚未建立，不能把本地逻辑验证当作性能门禁。实验执行仍严格依次为基线、批次、开头编译、剩余瓶颈；未通过前一步不选用下一步产品配置。新增显式服务包装器和固定文本组件回放，源码与镜像文档同步。不更换 ASR/LLM、音色、采样、codec 配置或播放所有权。TTS-004 只分析实测完整性与候选瓶颈，没有证据时不实施 KV/codec/backbone 优化。

## 2026-10-17 稀疏文本启动修复

按用户新增要求，将跨 micro-turn 不足 12 个 TTS token 的等待单列为 [TTS-005](issues/tts_005_sparse_text_prefill_wait.md)，优先在当前基线完成后进行独立组件对照。候选为启动门槛 8/4，或原门槛加 200ms 空闲等待上限；不伪造 final，不把每个 micro-turn 当作回答结束。新增默认关闭的服务参数与原 worker 队列超时路径，音质与文本完整性未通过前不改变产品默认值。现有基线不修改，后续同卡筛选单变量推进；完整结果与局限写入 TTS 优化报告。

## 2026-10-17 TTS 本轮结果

基线 210 条、原同卡筛选 99 条、修复配对复测 36 条均已归档；另保留一次旧 early 预热失败。离线 ASR 对 135 条筛选/复测记录完成内容诊断，实际不同 WAV 为 20 个，不把重复轮次视作独立语音样本。4 帧批次与 early 的收益、门槛 4/8 和 200ms 等待的正负结果见 [优化报告](tts_latency_optimization_report.md)。当前产品默认配置不变，前 10 帧执行改善与单一队列的有界启动路径已验证，但可听预算、自然度、真实播放与 FDB 仍未验收；不以首 PCM 提前替代这些结论。

## MOSS 组合验证

用户要求在决定替换组件前补跑一次组合。沿用既有三条筛选文本、三种输入模式和三轮，新增独立组合 suite：原配置 control_start、batch4 + early + prefill4、原配置 control_end，共 81 条测量；首尾 control 与组合在同一调度器 GPU 上顺序运行。此轮用于验证交互收益，不作单变量归因，也不声称已穷尽全部 MOSS 优化空间。固定权重、音色、采样与现有 codec；不改在线 ASR，不启用 200ms 超时，不改变产品默认参数。首 PCM、模拟有声和 ASR 内容诊断仍分开验收。用户提及“换 ASR”与此前 TTS 讨论存在歧义，组合先执行，组件替换等待明确指向。

组合验证已完成：81条同卡测量、81条离线内容诊断，所有运行无失败；组合正式区间无新图、token消费完整，报告见 [组合验证](tts_combination_validation.md)。延迟有改善，但模拟有声均值仍为1.08–1.82秒，不支持稳定200–300ms目标。后续优先考虑替代TTS的固定输入对照，而不是从TTS组件延迟推断ASR必须替换；不在本次直接更换组件或修改默认配置。
