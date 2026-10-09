# X-Talk 的 DuplexCascade 功能改造方案

## 1. 路线结论

X-Talk fork 与 InterClarify 是两个独立项目，不使用 Git 子模块。

| 仓库 | 职责 |
| --- | --- |
| `Vitalrubbish/xtalk` | 全双工运行时；先实现 DuplexCascade 风格的通用能力 |
| `Vitalrubbish/InterClarify` | 主动澄清研究；记录底座提交、数据、评测和 Layer 2 实现 |

本地 `InterClarify/xtalk/` 只是当前工作区中的独立 checkout。InterClarify Git 忽略该目录，通过配置和 manifest 记录实际使用的 X-Talk fork URL 与提交，不跟踪其源码或 gitlink。

开发顺序固定为：

1. **阶段 A：X-Talk Duplex**。在 X-Talk fork 中实现 micro-turn、Layer 0/1、backchannel、提前回答、持续监听、用户打断、单一仲裁和单一 TTS 所有权。
2. **阶段 B：InterClarify**。阶段 A 稳定后，InterClarify 通过扩展接口增加 Layer 2、前缀有效性、任务状态和澄清恢复。

阶段 A 不包含主动澄清，不实现日程任务状态，也不引入 InterClarify 专属提示词。

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
3. 默认 backchannel 由 Agent 直接产生 `direct_audio`，没有经过统一的 Layer 1 > Layer 0 仲裁。
4. `TTSResponseCoordinator` 只处理机械串行化，不负责语义优先级和前缀有效性。
5. turn detector 的开始回答/停止说话事件缺少 turn、segment 和 prefix 上下文。
6. `TurnDetectorManager` 在 `TTSChunkReady` 时切换 speaking 状态，早于真正打开客户端交付门。
7. 默认事件发布可并发执行 handler，状态更新不能只依赖 priority 顺序。

## 4. 阶段 A 的能力边界

### 4.1 Layer 0

只产生：

```text
SILENCE
BACKCHANNEL
```

backchannel 可以使用预录音频，但必须经统一仲裁和 X-Talk 的唯一 TTS response lifecycle，不能直接向前端写音频。

### 4.2 Layer 1

只产生：

```text
SILENCE
ANSWER
```

`ANSWER` 可以在用户话轮未正式结束时启动。若此前没有提前回答，ASR final 触发相同 Agent 的句末回答安全回退。

阶段 A 可以预留 `REQUEST_HIGHER_LAYER` 扩展动作，但不会调用 Layer 2。

### 4.3 仲裁规则

- 优先级为 `Layer 1 > Layer 0`；
- 同一时刻只能有一个获批候选；
- 候选必须绑定当前 session、turn、segment 和 prefix version；
- 旧前缀结果直接拒绝；
- Layer 0 不能取消 Layer 1；
- 响应提交后不能被新候选替换；
- 用户打断可以停止剩余输出，但不能撤销已播内容。

阶段 B 接入 InterClarify 后，只把优先级扩展为 `Layer 2 > Layer 1 > Layer 0`，不更换仲裁器和播放链路。

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
    │                         ├────► Layer0Policy
    │                         └────► Layer1Policy
    │                                      │
    └──── fixed/event micro-turn ──────────┘
                                           ▼
                                    OutputArbiter
                                      L1 > L0
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
layer: L0 | L1
action: SILENCE | BACKCHANNEL | ANSWER
payload_type: AUDIO | GENERATION
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

- `Layer0Policy`：规则优先，决定静默或 backchannel；
- `Layer1Policy`：结构化模型判断静默或回答；
- 策略只返回候选，不直接调用 TTS。

### `controller.py`

`DuplexControllerManager`：

- 维护前缀版本、说话状态、响应状态和冷却时间；
- 每 0.6 秒产生 micro-turn，ASR partial 或停顿可提前触发；
- 启动策略任务，不在状态锁内等待模型；
- 失效旧 request 和 candidate；
- final 到达时决定是否需要句末回退回答。

### `arbiter.py`

`OutputArbiter` 是唯一语义选择器，实现版本校验、L1 > L0 和提交边界。

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
- backchannel 走同一 TTS response lifecycle；
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
| `tts_manager.py` | `direct_audio` 接受外部 response id |
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

### A0：fork 基线

- 创建 feature branch；
- 用 conda 建立 X-Talk 环境；
- 跑上游测试；
- 选择最小 ASR、LLM、TTS、turn detector 组合；
- 保存原生行为和资源占用。

### A1：可观测性

- prefix version；
- request/candidate/response id；
- response lifecycle；
- 统一事件日志；
- 修正 turn detector speaking 边界。

### A2：micro-turn 与 Layer 0

- 固定/事件驱动 tick；
- SILENCE/BACKCHANNEL；
- 冷却、去重和提交边界；
- backchannel 不结束用户 turn。

### A3：Layer 1 与仲裁

- SILENCE/ANSWER；
- L1 > L0；
- 提前回答；
- final 安全回退；
- 用户打断和恢复监听。

### A4：DuplexCascade 功能验收

- 脚本化场景；
- FDB smoke；
- 原生 X-Talk 与 X-Talk Duplex 对照；
- 延迟、显存、队列和长会话检查。

阶段 A 通过后，InterClarify 才开始 Layer 2。

## 12. 阶段 A 测试矩阵

- prefix append、rewrite、pause、final 的版本递增；
- 旧策略结果失效；
- L1 在提交前覆盖 L0；
- 提交后新候选被拒绝；
- backchannel 不结束用户 turn；
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
- `L2 > L1 > L0` 仲裁扩展；
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
- 多任务域；
- 完整语音模型训练；
- 通用工作流引擎；
- 第二套 EventBus、TTS 或播放队列。
