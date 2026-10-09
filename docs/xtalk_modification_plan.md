# X-Talk 的 DuplexCascade 功能改造方案

## 1. 路线结论

X-Talk fork 与 InterClarify 是两个独立项目，不使用 Git 子模块。

| 仓库 | 职责 |
| --- | --- |
| `Vitalrubbish/xtalk` | 全双工运行时；先实现 DuplexCascade 风格的通用能力 |
| `Vitalrubbish/InterClarify` | 主动澄清研究；记录底座提交、数据、评测和 Layer 2 实现 |

本地 `InterClarify/xtalk/` 只是当前工作区中的独立 checkout。InterClarify Git 忽略该目录，通过配置和 manifest 记录实际使用的 X-Talk fork URL 与提交，不跟踪其源码或 gitlink。

开发顺序固定为：

1. **阶段 A：X-Talk Duplex**。先冻结第一套原生组件组合，再实现 DuplexCascade 无 System Backchannel 版的 micro-turn、Layer 1、提前回答、持续监听、用户打断、单一仲裁和单一 TTS 所有权。
2. **阶段 B：InterClarify**。阶段 A 稳定后，InterClarify 通过扩展接口增加 Layer 2、前缀有效性、任务状态和澄清恢复。

阶段 A 不包含主动澄清，不实现日程任务状态，也不引入 InterClarify 专属提示词。

根据 2026-10-09 的范围调整，当前移除 Layer 0 和系统附和生成路径。论文第 4.1 节的 DuplexCascade 为无 System Backchannel 版，DuplexCascade-β 为有系统附和版，见[原文](https://arxiv.org/html/2603.09180v1#S4.SS1)。User Backchannel 识别仍保留；后续阶段 B 默认继承该配置。第一套组件候选与冻结条件见 [xtalk_baseline_stack.md](xtalk_baseline_stack.md)。

## 2. Git 与版本管理

X-Talk 本地仓库配置为：

```text
origin   git@github.com:Vitalrubbish/xtalk.git
upstream git@github.com:xcc-zach/xtalk.git
```

- `main` 跟踪 `origin/main`；
- `upstream` 只用于 fetch，禁用 push；
- 起始提交为 `5f0d9959edf1026588246efbed827b078cbb114c`；
- 功能开发使用独立 feature branch；
- 同步上游时先 fetch/rebase，再运行上游全量测试和项目回归测试；
- InterClarify 的实验 manifest 记录 X-Talk fork 提交，不依赖浮动分支名。

## 3. X-Talk 现有能力审计

### 3.1 可直接复用

| 能力 | X-Talk 实现 | 处理方式 |
| --- | --- | --- |
| 会话事件总线 | 每会话独立 `EventBus` | 保留 |
| manager 扩展 | `DefaultService.register_manager` 与事件 override | 保留 |
| 流式 ASR | partial/final 携带 turn/segment | 保留，补前缀版本 |
| turn detector | 同时接收音频、partial、停顿和已播文本 | 保留 |
| 打断 | turn detector 到 LLM/TTS stop | 保留并增强审计 |
| TTS 串行 | `TTSResponseCoordinator` | 保留 |
| TTS 所有权 | 单一 `TTSManager` | 保留 |
| 播放确认 | chunk played、stopped、finished | 保留 |
| 已播文本 | `ResponseUpdate` / `ResponseFinish` | 作为不可撤销事实 |
| 历史合并 | assistant 文本按 `response_id` 更新 | 保留 |

### 3.2 需要补齐

1. ASR partial 没有显式 `prefix_version`，异步决策无法可靠失效。
2. 默认 Agent 在 partial 上只尝试 backchannel，普通回答只在 final 后生成。
3. 原生 Agent 配置附和模型与音频目录后可产生 `direct_audio`；本路线显式关闭两个配置，避免系统附和绕过控制层。
4. `TTSResponseCoordinator` 只处理机械串行化，不负责语义优先级和前缀有效性。
5. turn detector 的开始回答/停止说话事件缺少 turn、segment 和 prefix 上下文。
6. `TurnDetectorManager` 在 `TTSChunkReady` 时切换 speaking 状态，早于真正打开客户端交付门。
7. 默认事件发布可并发执行 handler，状态更新不能只依赖 priority 顺序。

## 4. 阶段 A 的能力边界

### 4.1 移除 Layer 0 与 System Backchannel

当前不实现或注册 `Layer0Policy`，不产生 `BACKCHANNEL` 候选，不加载系统附和音频资产。原生基线和改造版本均将 `backchannel_model` 与 `backchannel_source_dir` 固定为 `null`。Layer 1 也不能用单独的“嗯、我在听”等反馈冒充正式回答。

系统说话时仍区分用户附和与有效插话。移除系统附和不改变用户打断停播职责，也不删去 User Backchannel 的评测。

### 4.2 Layer 1

只产生：

```text
SILENCE
ANSWER
```

`ANSWER` 可以在用户话轮未正式结束时启动。若此前没有提前回答，ASR final 触发相同 Agent 的句末回答安全回退。

阶段 A 可以预留 `REQUEST_HIGHER_LAYER` 扩展动作，但不会调用 Layer 2。

### 4.3 仲裁规则

- 阶段 A 只接受 Layer 1 候选，检查版本、去重、过期与提交边界；
- 同一时刻只能有一个获批候选；
- 候选必须绑定当前 session、turn、segment 和 prefix version；
- 旧前缀结果直接拒绝；
- `SILENCE` 表示继续等待，不启动 TTS，也不取消已获批回答；
- 响应提交后不能被新候选替换；
- 用户打断可以停止剩余输出，但不能撤销已播内容。

阶段 B 接入 InterClarify 后，把优先级扩展为 `Layer 2 > Layer 1`，复用同一仲裁器和播放链路。Layer 0 恢复属于后续独立范围调整。

## 5. 提交与播放边界

阶段 A 使用 X-Talk 现有事件定义以下状态：

```text
GENERATED       LLMAgentResponseUpdate
PREPARING       TurnTTSStartRequested 已受理
COMMITTED       TTSStarted，客户端交付门已打开
HEARD_PARTIAL   非空 ResponseUpdate
SETTLED         ResponseFinish
```

`COMMITTED` 是保守边界。即使第一段音频尚未真正从声卡输出，也不再允许语义候选覆盖；用户仍可以通过 barge-in 停止剩余播放。

`TurnDetectorManager` 改为在 `TTSStarted` 后进入非 listening 状态，在 `TTSPlaybackFinished` 或 `TTSStopped` 后恢复 listening。精确声卡起播回执留到真人实验确有需要时再实现。

## 6. 阶段 A 控制链路

```text
Audio / VAD
    │
    ▼
ASR partial/final
    │
    ▼
PrefixTracker ──► PrefixSnapshot(versioned)
    │                         │
    │                         └────► Layer1Policy
    │                                      │
    └──── fixed/event micro-turn ──────────┘
                                           ▼
                                    OutputArbiter
                                     校验 L1
                                           │
                                           ▼
                                   ResponseExecutor
                                           │
                                           ▼
                     LLMAgentConsumption / TTSResponseCoordinator
                                           │
                                           ▼
                              TTSManager / PlaybackManager
```

`OutputArbiter` 选择语义动作；`TTSResponseCoordinator` 串行交付已经批准的响应。两者职责独立。

## 7. 阶段 A 核心数据结构

### 7.1 `PrefixSnapshot`

```text
session_id
turn_id
segment_id
prefix_version
text
previous_text
revision_kind: APPEND | REWRITE | FINALIZE
speech_state: SPEAKING | PAUSING | ENDED
received_monotonic
```

同一 turn 中，只要可见文本或停顿/final 状态有效变化，版本就递增。

### 7.2 `OutputCandidate`

```text
candidate_id
request_id
session_id
turn_id
segment_id
prefix_version
layer: L1
action: SILENCE | ANSWER
payload_type: NONE | GENERATION
payload
created_monotonic
expires_monotonic
```

结构预留更高层编号和 `TEXT` payload，阶段 A 不产生 `CLARIFY`。

### 7.3 `ResponseLifecycle`

```text
IDLE -> SELECTED -> GENERATING -> PREPARING
     -> COMMITTED -> HEARD_PARTIAL -> SETTLED -> IDLE
```

## 8. X-Talk fork 的模块布局

通用双工增强放在 `src/xtalk/duplex_control/`：

```text
src/xtalk/duplex_control/
├── __init__.py
├── events.py
├── state.py
├── policies.py
├── controller.py
├── arbiter.py
├── agent.py
├── executor.py
└── service.py
```

### `events.py`

定义版本化前缀、micro-turn、策略结果、候选、仲裁和响应生命周期事件。

### `state.py`

定义不可变快照和会话控制状态。单写者 manager 持有可变状态。

### `policies.py`

- `Layer1Policy`：结构化模型判断静默或回答；
- 用户附和与有效打断由冻结的 turn detector 提供线索，controller 验证并执行；
- 策略只返回候选，不直接调用 TTS。

### `controller.py`

`DuplexControllerManager`：

- 维护前缀版本、说话状态、响应状态和冷却时间；
- 每 0.6 秒产生 micro-turn，ASR partial 或停顿可提前触发；
- 启动策略任务，不在状态锁内等待模型；
- 失效旧 request 和 candidate；
- final 到达时决定是否需要句末回退回答。

### `arbiter.py`

`OutputArbiter` 是唯一语义选择器，实现版本校验、去重、过期和提交边界；阶段 A 只选择 L1。

### `agent.py`

`DuplexAgent` 继承 `DefaultAgent`：

- partial 只更新用户历史；
- 默认 partial backchannel 关闭；
- 提供显式流式 `generate_answer(snapshot)`；
- 已提前回答的 turn 在 final 时不重复生成；
- assistant 历史仍只写入播放确认文本。

### `executor.py`

`ResponseExecutorManager`：

- 为获批响应预分配 `response_id`；
- answer 经 `LLMAgentConsumptionManager` 流式进入 TTS；
- 负责取消尚未提交的旧响应；
- 不直接操作 WebSocket 或音频设备。

### `service.py`

`DuplexService` 继承 `DefaultService`：

- 注册 Controller 和 Executor；
- 接管 ASR partial/final 的输出决策；
- 保留 X-Talk 原有 ASR、turn taking、TTS、播放和 gateway manager；
- 提供稳定的 higher-layer policy 注册接口，供未来 InterClarify 使用。

## 9. X-Talk 核心最小补丁

| 文件 | 通用补丁 |
| --- | --- |
| `serving/events.py` | generation request 支持预分配 `response_id` 和来源 metadata |
| `llm_agent_generation_manager.py` | 使用预分配 response id |
| `turn_detector_manager.py` | speaking 状态从 `TTSChunkReady` 改由 `TTSStarted` 驱动 |
| turn detector action events | 增加 turn、segment、prefix context |

首轮不改 `TTSResponseCoordinator`、`TTSPlaybackManager` 和前端平台抽象。

## 10. 并发模型

`EventBus` 默认 dispatch 会并发 handler。阶段 A 采用：

- `DuplexControllerManager` 作为控制状态单写者；
- `asyncio.Lock` 保护短状态转换；
- 慢模型在锁外运行；
- 每次模型调用携带 request id 和 prefix version；
- 结果回到 controller 后重新校验；
- 关键执行事件使用等待式 dispatch；
- shutdown 取消全部策略和生成任务。

## 11. 阶段 A 实现顺序

### A0：冻结第一套原生组合（控制层改造前的门禁）

- 创建 feature branch；
- 用 conda 建立 X-Talk 环境；
- 跑上游测试；
- 按 [xtalk_baseline_stack.md](xtalk_baseline_stack.md) 核验候选组合，记录模型 revision、量化、服务提交、依赖、VAD 配置和参考音色；
- 用原生 DefaultService / DefaultAgent 跑通链路，显式关闭 System Backchannel；
- 保存原生行为和资源占用。

模型来源和配置完整、原生链路 smoke 通过、延迟与资源记录齐全后，才允许进入 A1。当前组合处于候选状态，尚未完成运行冻结。

### A1：可观测性

- prefix version；
- request/candidate/response id；
- response lifecycle；
- 统一事件日志；
- 修正 turn detector speaking 边界。

### A2：micro-turn 与等待状态

- 固定/事件驱动 tick；
- 无新增 ASR 文本和用户思考期间仍产生窗口；
- SILENCE 不生成音频；
- 冷却、去重和提交边界；
- 短暂停顿不自动等于话轮结束。

### A3：Layer 1 与仲裁

- SILENCE/ANSWER；
- 单一仲裁器验证 L1 候选；
- 提前回答；
- final 安全回退；
- 用户打断和恢复监听；
- 用户附和时保持回答，并验证无 System Backchannel 输出。

### A4：DuplexCascade 功能验收

- 脚本化场景；
- FDB smoke；
- 原生 X-Talk 与 X-Talk Duplex 对照；
- 延迟、显存、队列和长会话检查；
- 用户附和保留为验收项；系统附和输出指标单列为范围外。

阶段 A 通过后，InterClarify 才开始 Layer 2。

## 12. 阶段 A 测试矩阵

- prefix append、rewrite、pause、final 的版本递增；
- 旧策略结果失效；
- 同一前缀的 L1 候选去重与过期检查；
- 提交后新候选被拒绝；
- 系统附和候选、音频及策略调用均为零；
- 用户附和不误触发停播，有效用户插话仍停播；
- 短暂停顿及用户思考期间保持等待；
- 提前回答后 final 不重复生成；
- 没有提前回答时 final 正常回退；
- 用户打断停止剩余音频并提交实际已播前缀；
- 连续 micro-turn 不重复生成相同候选；
- manager shutdown 清理任务；
- X-Talk 原有 TTS 串行、播放对齐和 turn-taking race 测试不退化。

## 13. 阶段 B：InterClarify 接入点

InterClarify 在自己的仓库中实现：

- Layer 2 澄清策略；
- 有后果的候选解释；
- 自行消歧风险；
- 任务状态与澄清回复补丁；
- `L2 > L1` 仲裁扩展；
- 澄清专用数据、评测和实验。

X-Talk Duplex 需要对外提供：

```text
register_policy(layer, policy)
submit_candidate(candidate)
get_prefix_snapshot()
get_response_lifecycle()
invalidate_request(request_id)
```

InterClarify 不复制或 fork 第二套 X-Talk 运行时，只依赖固定的 X-Talk Duplex 提交。

## 14. 暂不实施

- 主动澄清和任务恢复；
- Layer 3；
- Layer 0 和 System Backchannel；
- 多任务域；
- 完整语音模型训练；
- 通用工作流引擎；
- 第二套 EventBus、TTS 或播放队列。
