# X-Talk 改造方案

## 1. 结论

InterClarify 采用“**X-Talk 独立 fork + InterClarify 研究仓库固定其提交**”的双仓库结构。

- `xtalk/` 保留独立 Git 历史，作为实际运行时和主要代码改造仓库；
- InterClarify 根仓库保存研究设计、实验配置、数据工具、评测、任务单和 X-Talk 提交锁定；
- 待 X-Talk fork 远端建立后，InterClarify 通过根目录 `xtalk/` 子模块固定可复现提交；
- X-Talk 官方仓库设为 `upstream`，项目 fork 设为 `origin`；
- 不把 X-Talk 放入 `3rd-party/`，也不把其源码平铺复制进 InterClarify Git 历史。

当前本地 `xtalk/` 已固定在 `5f0d9959edf1026588246efbed827b078cbb114c`。在 fork 远端确定前，暂不把该目录加入 InterClarify 索引。

## 2. X-Talk 可直接复用的能力

| X-Talk 能力 | 复用方式 | 结论 |
| --- | --- | --- |
| 每会话 `EventBus` | manager 通过事件解耦 | 保留 |
| `Service` / `DefaultService` | 注册新 manager、禁用或替换事件订阅 | 保留 |
| 流式 ASR partial/final | `ASRResultPartial`、`ASRResultFinal` 已携带 turn/segment | 保留并补版本 |
| turn detector | 音频、partial、停顿和已播文本均可输入 | 保留，作为时机信号 |
| 用户打断 | `TurnDetectorStopSpeaking` 到 LLM/TTS stop | 保留并补日志 |
| TTS 响应串行化 | `TTSResponseCoordinator` 管理 delivering/preparing response | 保留 |
| 单一 TTS 队列 | `TTSManager` 统一合成、暂停、恢复和停止 | 保留 |
| 播放确认 | `TTSChunkPlayed`、`TTSPlaybackStopped/Finished` | 保留 |
| 已播文本事实 | `ResponseUpdate` / `ResponseFinish` 只记录播放确认文本 | 作为不可撤销边界 |
| 会话历史 | assistant 历史按 `response_id` 合并播放确认内容 | 保留 |

X-Talk 已经具备单会话单 TTS 协调器、单 TTS manager 和播放确认文本，因此不再新建第二套播放系统。

## 3. 当前缺口

### 3.1 控制缺口

1. ASR partial 是完整前缀文本，但事件没有显式 `prefix_version`。
2. 默认 Agent 在 partial 上只做 backchannel；普通回答只在 final 后生成，不支持统一的句中 `ANSWER` 决策。
3. 默认 backchannel 在 Agent 内部直接形成 `direct_audio`，没有经过 Layer 2 > Layer 1 > Layer 0 的语义仲裁。
4. `TTSResponseCoordinator` 负责机械串行化和抢占，不判断候选是否过时，也不表达 Layer 优先级。
5. `TurnDetectorStartGeneration` / `StopSpeaking` 不携带 turn、segment 和前缀版本，异步结果难以审计。
6. Layer 2、任务状态和澄清回复恢复尚不存在。

### 3.2 提交与播放边界缺口

当前链路可区分：

- `LLMAgentResponseUpdate`：模型已经生成；
- `TTSStarted`：响应已打开客户端交付门，可视为 `playback_committed`；
- `ResponseUpdate`：对应文本已被前端播放确认；
- `ResponseFinish`：正常完成或中断后最终确认的已播前缀。

`TurnDetectorManager` 当前在 `TTSChunkReady` 时切换为“系统正在说话”，该时刻是音频生成/发送阶段，早于真实播放。第一阶段先改为监听 `TTSStarted`，将其定义为交付提交边界。若真人实验需要精确的声卡起播时间，再增加前端 `tts_playback_started` 回执；该扩展不作为首轮 MVP 前置条件。

### 3.3 并发缺口

`EventBus` 默认发布方式会并发创建 handler task。InterClarify 不能依赖 handler priority 获得完整的顺序一致性。所有会改变候选、任务状态或播放所有权的路径必须：

- 由单写者 manager 持有状态；
- 使用 `asyncio.Lock` 串行更新；
- 对关键事件使用等待式 dispatch；
- 对慢速模型调用使用 request id 和版本校验，不在锁内等待模型。

## 4. 总体控制链路

```text
Audio / VAD
    │
    ▼
X-Talk ASR ──► PrefixTracker ──► versioned PrefixSnapshot
                                   │
                 ┌─────────────────┼──────────────────┐
                 ▼                 ▼                  ▼
             Layer 0           Layer 1        Layer 2 async request
          SILENCE/BACKCHANNEL  SILENCE/ANSWER/   NO_OVERRIDE/CLARIFY
                              REQUEST_LAYER2
                 └─────────────────┼──────────────────┘
                                   ▼
                            OutputArbiter
                       L2 > L1 > L0 + freshness
                                   │
                                   ▼
                         ResponseExecutor
                                   │
                                   ▼
        X-Talk LLMAgentConsumption / TTSResponseCoordinator
                                   │
                                   ▼
                    TTSManager / TTSPlaybackManager
                                   │
                                   ▼
                ResponseUpdate / ResponseFinish
```

语义仲裁发生在生成/播放链路之前。X-Talk 的 TTS coordinator 继续承担机械交付串行化，两者职责不能合并：

- `OutputArbiter` 回答“哪个语义动作有效”；
- `TTSResponseCoordinator` 回答“哪个已批准响应可以进入客户端交付”。

## 5. 核心数据结构

### 5.1 `PrefixSnapshot`

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
task_revision
```

同一 turn 中，只要可见文本、停顿状态或 final 状态发生有效变化，`prefix_version` 就递增。版本由 InterClarify `PrefixTracker` 生成，不依赖 ASR 模型内部 revision 编号。

### 5.2 `OutputCandidate`

```text
candidate_id
request_id
session_id
turn_id
segment_id
prefix_version
task_revision
layer: L0 | L1 | L2 | L3
action: SILENCE | BACKCHANNEL | ANSWER | CLARIFY | REVISION
payload_type: AUDIO | TEXT | GENERATION
payload
created_monotonic
expires_monotonic
```

Layer 3 在 MVP 中不会产生候选，只保留类型位置。未来的 `REVISION` 必须额外携带 `target_response_id` 和 `target_revision`，且只能作用于未提交片段。

### 5.3 `ResponseLifecycle`

```text
IDLE
  -> SELECTED
  -> GENERATING
  -> PREPARING
  -> COMMITTED       # 收到 TTSStarted
  -> HEARD_PARTIAL   # 收到非空 ResponseUpdate
  -> SETTLED         # 收到 ResponseFinish
  -> IDLE
```

`COMMITTED` 前允许高优先级候选替换低优先级候选；`COMMITTED` 后只允许用户打断停止剩余输出，禁止用新候选声称撤销已播内容。

## 6. 模块设计

InterClarify 专属实现放在 X-Talk fork 的新包 `src/xtalk_interclarify/`，降低与上游核心文件的冲突。

### 6.1 `events.py`

定义版本化前缀、micro-turn、策略请求/结果、候选、仲裁、任务补丁和响应状态事件。事件只传递不可变快照，不共享可变任务对象。

### 6.2 `state.py`

包含：

- `PrefixSnapshot`；
- `OutputCandidate`；
- `ResponseLifecycle`；
- `ClarificationState`；
- `SessionControlState`。

### 6.3 `policies.py`

- `Layer0Policy`：根据 turn semantic、停顿、冷却时间和当前播放状态产生 `SILENCE/BACKCHANNEL`；
- `Layer1Policy`：产生 `SILENCE/ANSWER/REQUEST_LAYER2`；
- `Layer2Policy`：按需分析结果分歧、自行消歧风险、接话时机和问题内容；
- 所有策略只返回候选，不直接调用 TTS。

首版策略采用规则和结构化提示。Layer 0 优先使用规则；Layer 1 使用轻量结构化判定；Layer 2 使用较强模型异步调用。

### 6.4 `controller.py`

`InterClarifyControllerManager` 是会话控制状态的单写者：

- 监听 ASR partial/final、VAD、turn detector、TTS 和播放确认事件；
- 维护 `prefix_version`、`task_revision`、响应状态和澄清状态；
- 产生固定 0.6 秒起点的 micro-turn，并允许 partial/停顿事件提前触发；
- 启动策略任务，但不在状态锁内等待模型；
- 接收策略结果并提交给仲裁器；
- 失效旧 request 和 candidate。

### 6.5 `arbiter.py`

`OutputArbiter` 是唯一语义选择器，规则为：

1. 候选的 session、turn、prefix 和 task revision 必须仍有效；
2. `CLARIFY` 必须问题非空且歧义仍存在；
3. 优先级固定为 `L2 > L1 > L0`；
4. L0 不得取消 L1/L2；
5. 响应进入 `COMMITTED` 后拒绝替换；
6. 同一 turn 同一歧义只允许一个有效澄清；
7. 被拒绝候选必须记录具体原因。

### 6.6 `agent.py`

`InterClarifyAgent` 继承 X-Talk `DefaultAgent`：

- partial 只更新用户前缀历史，不使用默认内置 backchannel；
- 提供显式的流式 `generate_answer(snapshot)`；
- final 到达时，如果该 turn 已由提前回答或澄清接管，只完成用户文本，不重复生成；
- assistant 历史仍只通过 `ResponseUpdate/Finish` 写入；
- 不把未播放的生成文本写入历史。

### 6.7 `executor.py`

`ResponseExecutorManager` 只执行仲裁器批准的候选：

- `BACKCHANNEL`：使用预录音频，仍经 X-Talk `TTSManager` 的 response lifecycle；
- `ANSWER`：调用 `InterClarifyAgent.generate_answer`，经 `LLMAgentConsumptionManager` 流式进入 TTS；
- `CLARIFY`：把单句问题包装为短流，走同一 TTS 链路；
- 为每个批准响应预先分配 `response_id`，供取消、提交和播放确认映射。

### 6.8 `task_state.py`

`TaskStateReducer` 只实现日程时间域：

- 保存用户当前目标、候选日期/时间和待澄清字段；
- 澄清后进入 `WAITING_FOR_REPLY`；
- 下一用户 turn 被解析为版本化任务补丁；
- 补丁成功后恢复原任务并进入 `ANSWERING`；
- 不建设通用工作流引擎。

### 6.9 `service.py`

创建 `InterClarifyService`：

- 从 `DefaultService` 继承；
- 注册 Controller 和 Executor；
- 禁用 `LLMAgentContextManager` 对 ASR partial/final 的默认生成订阅；
- 保留其 `ResponseUpdate/Finish` 历史更新；
- 保留 X-Talk 原有 ASR、turn taking、TTS、播放和 gateway manager。

## 7. X-Talk 核心最小补丁

专属逻辑放在 `xtalk_interclarify`，核心只接受以下通用补丁：

| 文件 | 补丁 |
| --- | --- |
| `serving/events.py` | `ConsumeLLMAgentGenerationRequested` 增加可选预分配 `response_id` 和来源 metadata |
| `llm_agent_generation_manager.py` | 使用预分配 `response_id`，不再只能在首文本 chunk 时随机创建 |
| `tts_manager.py` | `direct_audio` 接受可选 `response_id`，确保 backchannel 可被仲裁器追踪 |
| `turn_detector_manager.py` | 用 `TTSStarted` 替代 `TTSChunkReady` 切换 speaking/listening 状态 |
| `events.py` / turn detector events | 补充 turn、segment、prefix context，便于日志和过时结果检查 |

首轮不修改 `TTSResponseCoordinator`、`TTSPlaybackManager` 和前端播放实现。只有测试证明现有提交边界不足，才增加精确 `tts_playback_started` 回执。

## 8. 关键时序

### 8.1 L1 先到、L2 后到且尚未提交

```text
L1 ANSWER selected -> generation starts
L2 CLARIFY arrives -> version valid -> cancel L1 stream
                    -> select L2 -> synthesize clarification
```

取消只允许发生在 L1 收到 `TTSStarted` 前。

### 8.2 L2 在提交后到达

```text
L1 -> TTSStarted -> COMMITTED
L2 result arrives -> reject(reason=output_committed)
```

### 8.3 ASR 修订

```text
prefix v7 -> Layer2 request r7
ASR rewrite -> prefix v8
r7 returns -> reject(reason=stale_prefix)
```

### 8.4 澄清恢复

```text
CLARIFY committed -> WAITING_FOR_REPLY
reply final -> TaskStatePatch vN+1
            -> ambiguity resolved
            -> ANSWERING original task
```

## 9. 分阶段实现

### M0：仓库与基线

- 建立 X-Talk fork；
- 配置 `origin=fork`、`upstream=official`；
- 把 `xtalk/` 作为根目录子模块加入 InterClarify；
- 建立 X-Talk 专用 conda 环境；
- 跑通上游测试和最小示例。

门槛：固定提交可运行，InterClarify 能通过子模块提交复现。

### M1：可观测性和提交边界

- 增加 prefix version、request id、candidate id 和 response id 日志；
- 修正 turn detector 的 speaking 切换点；
- 建立 response lifecycle 测试。

门槛：从 ASR partial 能追踪到最终已播文本，已生成/已提交/已播状态可区分。

### M2：Layer 0/1 与单一仲裁

- 实现 Controller、Agent、Arbiter、Executor；
- 关闭默认 partial/final 的自动输出入口，由 Controller 统一接管；
- 实现 SILENCE/BACKCHANNEL/ANSWER；
- Controller 在未发生提前输出时调用同一 Agent 完成句末回答，作为安全回退。

门槛：无 Layer 2 时具备持续监听、backchannel、提前回答和用户打断，且只有一个语义仲裁器和一个 TTS owner。

### M3：Layer 2 与任务恢复

- 实现按需异步 Layer 2；
- 加入版本失效和提交边界；
- 实现日程时间任务状态与澄清回复补丁。

门槛：澄清问题可回答、旧结果不能覆盖、回复能恢复原任务。

### M4：评测与回归

- 上游 X-Talk 测试全量回归；
- InterClarify 并发/状态测试；
- FDB smoke；
- 30–50 条探索轨迹和小规模真人试交互。

门槛：满足工程方案 P1/P2 的 go / revise / stop 条件。

## 10. 测试矩阵

至少覆盖：

- prefix append、rewrite、pause、final 的版本递增；
- 旧 Layer 2 结果失效；
- L2 在 L1 提交前覆盖；
- L2 在提交后被拒绝；
- L0 不能覆盖 L1/L2；
- final 不重复生成已提前回答的 turn；
- backchannel 不结束用户 turn；
- 用户打断停止剩余音频并提交真实已播前缀；
- clarification confirm / deny / replace / task change；
- 连续两个候选窗口只接受一个澄清；
- manager shutdown 取消所有策略任务；
- X-Talk 原有 TTS 串行、播放对齐和 turn-taking race 测试不退化。

## 11. 暂不实施的内容

- 不实现 Layer 3；
- 不训练完整语音模型；
- 不建设通用任务编排平台；
- 不在首轮更换前端音频平台抽象；
- 不同时支持多个任务域；
- 不让每个 Layer 拥有独立 TTS 或播放队列。

## 12. 开始编码前的唯一仓库决策

需要先建立可写的 X-Talk fork。推荐 fork 地址为 `Vitalrubbish/xtalk`，并采用：

```text
origin   -> git@github.com:Vitalrubbish/xtalk.git
upstream -> git@github.com:xcc-zach/xtalk.git
```

完成该步骤后再创建开发分支和提交 X-Talk 改造，避免把提交留在只有上游写权限的本地仓库中。
