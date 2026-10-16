# X2Streaming ASR 替换复测任务单

## 1. 目标与范围

本轮在**相同底座**上做 ASR 单变量对照：把 Qwen3-ASR-1.7B 换成 X2Streaming-ASR-4B，其余全部保持上一轮 `20261015T114708Z-r1` 的配置——官方 DuplexCascade 权重、MOSS-TTS 播放链、0.6s micro-turn、后端 Silero VAD、FDB v1.0 五轴各 5 例。

要回答的问题：

1. 换用只追加硬提交的在线 ASR 后，可见文本还会不会出现回写、冲突冻结或 `final` 后分段重建带来的**接话空档**；
2. 同一批 pause / interruption / FDB 场景下，用户打断、停顿接话、顺畅接话等轴的行为是否变化；
3. ASR 侧音频输入、在线交付与端到端延迟的量级，以及 4B 模型在 4090 上的显存与长会话表现。

本轮**不做**离线重识别对照（X2 的离线 final 会覆盖在线文字，与本项目"已交付内容不可撤销"的边界冲突，只作独立质量分析，不在本任务单范围）。

## 2. 固定来源与对照口径

| 项 | 值 |
| --- | --- |
| InterClarify 快照 | `a352751d2e656f6a850df8e338111a78d7c8b75c` |
| X-Talk | `48c5952`（`X2StreamingClient` + `continuous_audio` 生命周期） |
| X2 源码 | `0aca80597bb1399c0be4002de5bc62c0a779c542` |
| X2 权重 | `x-square-robot/X2Streaming-ASR-4B-1009` @ `4c8df16b8d7f8b50c95590c4d7907436ebe4aa08` |
| X2 环境 | 独立 prefix `.../envs/xtalk-x2-asr`，见 [环境准备](scripts/remote/setup_x2_asr_env.md) |
| 镜像 | `docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4` |
| 资源 | `pdgpu-4090`，3 GPU / 24 CPU / 96 GB |
| 分卡 | 官方模型 GPU0、X2 ASR GPU1、MOSS GPU2 |
| ASR 语言 | 显式 `en`（FDB 为英语；不依赖模型默认语言） |
| ASR 输入 | 80 ms 连续音频；声学暂停只发 `is_final` 提示，不结束在线流 |
| 对照轮 | `20261015T114708Z-r1`（Qwen3-ASR，同镜像、同 DuplexCascade 权重、同 FDB） |

**口径警告**：替换 ASR 会改变用户文本进入 LLM 的时机与内容，因此 FDB 绝对分数与上一轮不能当作"模型好坏"的直接比较；本轮结论以**机制证据**（是否仍有回写/冻结/空档）+ 同轮内 ASR 侧延迟与显存为主，FDB 分数作为现象记录。

## 3. 环境与权重前置

在登录节点执行（首次约需下载数 GB，建议后台运行）：

```bash
bash scripts/remote/setup_x2_asr_env.sh
```

完成后 `<root>/ready.txt` 记录源码提交、权重 revision 与环境 prefix；作业所需变量：

```bash
export DUPLEX_ASR_BACKEND=x2
export DUPLEX_ASR_ENV=/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/xtalk-x2-asr
export DUPLEX_X2_SOURCE=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-x2/source-code
export DUPLEX_X2_MODEL=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-x2/model
export DUPLEX_X2_LANGUAGE=en
```

节点作业的 `environment` 步骤会用 `conda run -p "$DUPLEX_ASR_ENV"` 校验 `torch`/`transformers`，`assets` 步骤校验 X2 源码与权重目录存在；`asr_service` 步骤等待 `services/asr.log` 对应的 `/health`（进程在权重加载完成后才监听，健康即模型就绪）。

## 4. 运行范围

- 回放场景：`pause`、`normal`、`interruption`（沿用上一轮口径，`DUPLEX_A4_BARGE_AFTER_SECONDS=0.6`）。
- FDB v1.0：`pause_handling`（candor + synthetic）、`smooth_turn_taking`、`user_interruption`、`backchannel`，每子集 5 例；作业内跳过评分（GPU 空转会被 LowGpuUsage 杀），评分在作业外单跑。
- 长会话：30 轮，采集 GPU 与各服务 RSS。
- 保留 `runtime_build` 前置步骤、TTS 预热与 A1/A2/A3 回归。

## 5. 检查与证据边界

**ASR 侧**：

- `services/asr.log` 的 `live_emit` / `live_done` 事件：`delivered_monotonic` 与模型自带音频时间，用于区分算法等待与计算/交付延迟；
- `event=x2_online` 请求记录：累计音频秒数、在线累计文本、`pause_hint`、`end_stream`；
- 可见文本必须**单调追加**：本轮应不出现 Qwen 轮次里的"提交停滞/冻结"与 `final` 后分段重建；出现提前提交错误、漏字或重复时按识别错误记录，不能等同回写。

**X2 的暂停/结束语义与 Qwen 不同，读日志时必须区分**：`continuous_audio` 的 `pause()` 直接返回、不停止也不发布 partial，因此暂停不再产生 `speech_pause=True` 的边界事件，`x2_online` 的 `pause_hint` 正常情况恒为 `false`——停顿释放完全由 X2 自己的 Wait/Emit 逻辑决定。`end()` 才会调用 `finish_stream`（`end_stream=true`），而 duplex 模式下 `TurnASREndRequested` 目前没有发布者，所以要在时序上确认输入结束前的最后若干词是否已经在 `live_text` 里；若观察到句尾缺词，属于需要单独处理的问题，不在本轮自动判 PASS 范围内。

**运行时侧**：时间线里 `TurnASRPauseRequested` 后的新文本更新时间、播放期间的 `update_asr`、打断 `reset` 与已播文本单调性；与 [A4 任务单](xtalk_a4_remote_acceptance.md) 第 10 节同一套核验口径。

**FDB**：官方 `get_transcript/asr.py`（NeMo parakeet）对齐 + `evaluation/evaluate.py` 评分；`user_interruption` 的 judge 模型在端点可用性允许时优先用官方默认，若不可用则记录平替模型，分数不与历史 judge 口径混用。

**产物**：完整产物写 `data/runs/<tag>/`，关键报告复制到 `reports/duplex_acceptance/<tag>/`，独立源码快照位于 `interclarify-retests/<tag>/`。

## 6. 提交记录

- 运行标识：`20261015T172109Z`。
- 快照：InterClarify `a352751d2e656f6a850df8e338111a78d7c8b75c`、X-Talk `48c595243207bacf25667449bf784b7fa73d9dd3`，位于 `/mnt/cloudstorfs/sjtu_home/xuan.zhang/interclarify-retests/20261015T172109Z`。
- Manifest：183 个文件，snapshot `91a58587b9525e2c58bc1ee26896ce7afd6b842ded577e993292fbb21ad114d2`；来源清单已覆盖 `x2_asr_service.py`、`setup_x2_asr_env.sh`、`configs/xtalk_duplex_x2_runtime.json`、`tests/test_x2_asr_service.py` 与 X-Talk 的 `x2_streaming_client.py`。
- 环境与权重：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-x2`（`ready.txt` 记录源码、权重与环境 prefix）；提交前在登录节点用同一服务脚本对 `regular_answer_01_question.wav` 做过一次 80 ms 增量端到端冒烟，`/health` 正常、`end_stream` 后得到 `could you tell me a short joke please`。
- 作业：`job-179208494223390610578-xuan-zhang`（`pdgpu-4090`，3 GPU / 24 CPU / 96 GB），提交日志 `data/runs/submit_logs/submit.20261015T172221Z.sh`。
- 提交成功不等于测试通过；结果与读法在取得产物后回填。

## 7. 结果边界

- 只替换 ASR，不改 micro-turn、模型协议与播放链，因此不得据此宣称 TTS 或轮次策略改善。
- X2 在线硬提交不回写，但仍可能提前提交错误、漏字、重复或因不确定而等待；不回写不等于识别正确。
- 未取得实际输出前，不宣称"停滞消除"或"延迟改善"。
- 本轮不与 Qwen 轮次的 FDB 分数做无条件对比；单变量对照的读法见 §2。

## 8. 首轮结果与冷启动修复（`20261015T172109Z`）

**作业现状**：`job-179208494223390610578-xuan-zhang`，除 `real_audio_replay` 外全部 PASS——`source_manifest`、`gpu_allocation`、`assets`、`environment`、`runtime_config`、A1/A2/A3 回归、三个服务、`tts_warmup`、`official_model_smoke`、`runtime_build`、`fdb_inference`（五轴各 5 例）全部通过；`a4_summary.json` 为 `FAIL`（`failures=1`）。

**`pause` 场景 FAIL 的根因（已定位）**：`pause` 是本轮第一个场景，其 ASR 会话在整个服务里也是第一个会话。`services/asr.log` 显示该会话只收到 **2 个请求**：第一个 0.096 s，第二个一次带走 **5.76 s**（≈两段之和），且整场没有任何 `live_emit`；其余所有会话均为 ~0.096 s 的稳定增量。原因是 X-Talk 的 ASR 消费者在首个 `recognize` 里阻塞于 X2 进程内第一个 `AdaptiveSession` 的一次性成本（CUDA 模块加载 / kernel autotune / 流式左填充 prefill），期间整段语音堆在消费者队列里，等解阻塞后一次取走；由于此后不再有新音频，累计文本再没有被客户端取回，driver 也没有看到 `update_asr`，于是判 FAIL（`response: ""`、`tts_audio_bytes: 0`）。`normal` 与 `interruption` 两个场景通过：转写准确（`could you tell me a short joke please`、`how often should i take my dog to the vet hold on can we discuss something else what's a good recipe for a quick dinner`），打断由模型自身的 `<|user interruption|>` 触发并冻结音频。

**修复**：`scripts/remote/x2_asr_service.py` 在加载权重后、`uvicorn` 监听前执行一次 `warmup()`（创建会话 → 追加 1 s 静音 → 关闭），把首个会话成本挪到作业本来就在等待的 `/health` 之前。本地验证：预热耗时 0.435 s；预热后按真实时间喂 80 ms 增量，文本在 0.64 s / 0.72 s / … / 2.08 s 逐词在线增长（修复前同一 clip 只在 `end_stream` 才出整句）。对应回归见 `tests/test_x2_asr_service.py::test_warmup_uses_one_session_and_releases_it`，服务文档见 [x2_asr_service.md](scripts/remote/x2_asr_service.md)。

**同时记录的两项事实（本轮不修）**：

1. `x2_online` 记录显示本轮 4866 个请求里 `pause_hint` 与 `end_stream` 均为 0：`continuous_audio` 使 `pause()` 直接返回（不产生暂停边界事件），而 duplex 模式下 `TurnASREndRequested` 没有发布者，所以在线流从未被 flush。结论只在"在线持续发射能覆盖句尾"这一点上成立；若后续发现句尾缺词，需要 X-Talk 侧补一个真实的流结束发布者。
2. FDB 五轴推理的转写为 X2 风格（小写、无标点），且都产出了回答；语义分数仍以作业外的官方对齐与评分为准。

修复后以新快照重跑，见 §9。

## 9. 修复复跑（`20261015T180154Z`）

- 快照：InterClarify `04536cf`（相对 `a352751` 只增加服务预热与其文档/回归）、X-Talk `48c5952`，位于 `/mnt/cloudstorfs/sjtu_home/xuan.zhang/interclarify-retests/20261015T180154Z`。
- Manifest：183 个文件，snapshot `988ad7a00078ceaf736feddf9891a7942b725fa86bd9e29b339c6c584241d262`。
- 作业：`job-179208736349843642489-xuan-zhang`（`pdgpu-4090`，3 GPU / 24 CPU / 96 GB），场景与 FDB 范围同 §2；提交日志 `data/runs/submit_logs/submit.20261015T180242Z.sh`。

**自动门禁全部 PASS**：17 个步骤中除 `fdb_scoring`（按配置 SKIPPED）外全部 PASS，`real_audio_replay` 的 `pause`/`normal`/`interruption` 三场景均 PASS，`fdb_inference` 五轴各 5 例 PASS，`a4_summary.json` 为 `INCOMPLETE`（仅因评分按设计延后）。

`pause` 场景本轮的关键差别：ASR 文本在 5.99–7.04 s 逐词增长（`hi i have two quick things to ask you`），系统随后正常作答；修复前同一场景整段没有任何 ASR 文本。

**FDB 官方对齐与评分**（debug GPU 节点单跑，`full-duplex-bench`，FDB `3e799c45`）：

| 轴 | 指标 | 本轮 X2 `20261015T180154Z` | 上一轮 Qwen `20261015T114708Z-r1` |
| --- | --- | --- | --- |
| `pause_handling`（candor） | TOR ↓ | **0.00**（0/5 有音频） | 0.40 |
| `pause_handling`（synthetic） | TOR ↓ | **0.00**（1/5 有音频） | 0.00 |
| `smooth_turn_taking`（candor） | TOR ↑ / Latency ↓ | **0.40 / 2.990s** | 0.80 / 2.838s |
| `backchannel`（icc） | TOR ↓ / Freq ↑ / JSD ↓ | **0.00 / 0.0000 / 1.0000** | 0.00 / 0.0048 / 0.9545 |
| `user_interruption` | GPT / TOR / Latency | **2.75 / 0.80 / 3.26s**（`gpt-6-sol` 平替） | 3.60 / 1.00 / 2.384s（`gpt-4o` 平替） |

**读法（含三处必须标注的口径）**：

1. **Candor Pause Handling 预期系统保持沉默**。本轮 candor 0/5 有音频、TOR 从 0.40 降到 0.00，符合预期，是该子集的正向结果，不能据此判定漏答。逐样本时间线复核：candor/1 在约 2.707s 启动 TTS，约 3.274s 被取消，未产生播放音频；此前“音频落在等长输出窗口之外”的归因不成立。synthetic TOR=0.00、1/5 有音频；是否误接话仍以标注窗口和官方评分为准。
2. `smooth_turn_taking` 与 `user_interruption` 相对 Qwen 轮次**退化**：STT 的 TOR 0.80→0.40、latency 2.838→2.990s；UI 的 TOR 1.00→0.80、latency 2.384→3.26s。UI 的 rating 换了 judge 模型（`gpt-4o`→`gpt-6-sol`），**不可与历史 rating 比较**；TOR 与 latency 与 judge 无关，属本轮实际结果。本轮 UI 逐样本 rating 为 10→4、100→3、101→4、102→0，样本 1 未接话所以无 rating；102 仍是"延续打断前话题"的老问题。
3. `backchannel` 的 Freq=0.0000 / JSD=1.0000 是阶段 A 关闭系统附和的必然现象侧值，不作达标项。

**judge 通道变更**：端点先下架 `gpt-4-turbo`（上一轮记录），本轮连 `gpt-4o` 也返回 503「无可用通道」；该 key 的分组里 `gpt-5.4*`/`gpt-6-luna`/`gpt-5.6-*` 均报无可用通道或上游饱和，**只有 `gpt-6-sol` 可用**，故本轮 UI rating 用 `gpt-6-sol` 并在证据里标注。

**ASR 侧证据（`services/asr.log`）**：

- 在线文本**单调追加**：28 个有 emit 的会话中回写违规 0；
- 交付相对音频时间的**滞后增长量**：中位 **-0.02 s**、P95 0.11 s、最大 2.39 s（首尾 emit 之间的 `delivered_monotonic` 跨度减模型 `time_s` 跨度）。该差值只反映会话内滞后是否持续增加，会抵消固定启动偏移，不能当作 ASR 绝对延迟；事件时间也是服务读取事件队列的时刻，而非模型实际 emit 的时刻；
- 首个真实会话仍有 **4.06 s 的一次性堆积**（预热把上一轮"整段吞掉"收敛到 4 s 级），其余会话均为 0.09–0.10 s/请求稳定增量；
- 原始日志复核共 4897 条 `x2_online` 请求，`pause_hint`、`end_stream` 均为 0（见 §8 第 1 条）。`synthetic_pause_handling` 5/5 样本都缺参考转写末词：`hobby`、`Thursday`、`information`、`cost`、`cybersecurity`（按参考文本记录，不代表人工确认语音内容）；candor 输入带尾部静音。无 EOF 收尾与异步结果未取回同时存在，需要修复后对照才能区分各自贡献。

**产物**：完整产物 `data/runs/20261015T180154Z/`；关键证据已复制到 `reports/duplex_acceptance/20261015T180154Z/`（`a4_summary.json`、`steps.jsonl`、逐场景 `report.json`、五轴 `*_fdb_summary.json`、`fdb_axes_summary.json`、`scoring/*_align_summary.json` 与 `tests/fdb_scoring_*.log`）。

**结论边界**：本轮证明换成 X2 后自动门禁与 FDB 推理可跑通、在线文本单调、多数会话未持续增加积压，但**不能据此宣称替换成功**：STT/UI 两轴相对 Qwen 轮次退化，首个会话仍有秒级冷启动堆积，且异步交付与真实 EOF 收尾尚不完整。Candor Pause Handling 的沉默符合预期。下一步见 §10。

## 10. 修复与诊断清单（2026-10-16 复核）

本节是后续工作的统一清单，**均尚未实施**。前四项是明确的工程缺口或测量修正，后三项需要先定位再确定实现方案。Candor Pause Handling 的沉默符合预期，不列为待修问题。继续保留 X2 原生追加输出与在线缓存，不对 X2 加入 Qwen 的反回写、冲突冻结或分段重建逻辑。

### 10.1 优先修复的工程项目

| 编号 / 优先级 | 证据与问题 | 涉及实现及处理方向 | 验收条件 |
| --- | --- | --- | --- |
| F1 / 高：异步结果交付 | `X2Service.recognize()` 追加 PCM 后立即读取 `live_text`，模型后台稍后产生的结果需下一次请求才能取回；`AudioConsumer` 没有新音频便不再请求。因此输入暂时停止也可能漏交付已生成的文字。 | `scripts/remote/x2_asr_service.py`、X-Talk 的 `models/asr/x2_streaming_client.py`、`serving/modules/asr_manager.py`：建立独立于新音频到达的结果接收机制。轮询、长轮询或推送的选择留到实现时确定；关闭与取消时释放接收任务。 | 异步假引擎在最后一次音频请求返回后才 emit，且没有后续音频，运行时仍能收到该文本；无重复音频提交；关闭后无过期发布与遗留任务。 |
| F2 / 高：真实 EOF 收尾 | 本轮 4897 条请求 `end_stream=0`，synthetic pause 五例均缺参考末词。驱动发完输入只等待，duplex 链路没有实际触发 `finish_stream`。 | X-Talk 的输入网关、ASR 生命周期及 `scripts/remote/duplex_a4_replay.py`：对有限音频输入提供显式 EOF，排空队列并取得最终在线输出。**声学暂停继续保留流与缓存**，不得用 VAD 停顿推断真实 EOF，也不得借参考转写或隐藏让轮标记触发收尾。麦克风持续输入不按每个话轮重建 X2。 | EOF 前已接收音频全部处理；在线尾部交付后再释放会话；重复 EOF 幂等；暂停恢复仍使用原流；远端逐例检查五条尾词，仍缺失时另记识别错误。官方 WAV 保持输入等长，EOF 后诊断输出单独记录。 |
| F3 / 高：完整预热 | `warmup()` 追加 1s 静音后直接 `abort()`，未等待实际 decode/emit 完成；本轮首个真实会话请求音频量为 0.096s、4.064s、随后约 0.096s，仍有一次性堆积。 | `scripts/remote/x2_asr_service.py` 或节点作业预热入口：使用固定真实语音，等待非空在线输出、在线 EOF 排空和资源释放，再进入就绪状态。不得仅以请求成功或静音已入队作为完成条件。 | 在新服务进程上验证，首个测量会话能逐步出字且不再出现本轮 4s 级首批积压；记录预热与会话创建耗时、实际请求块大小、首文本时间；预热内容不进入测量会话。 |
| F4 / 高：指标与验收口径 | 官方 UI TOR=0.8，但只有 10/100/101 启动新回答；1 停旧回答后未接话，102 持续旧回答。ASR 的 -0.02s 是滞后增长量。candor/1 的无音频来自播放前取消，原文窗口外归因错误。 | `scripts/remote/duplex_a4_replay.py`、X-Talk 的 `duplex_control/timeline.py` 与汇总报告：保留官方评分，补充旧回答停止、新回答启动、首 PCM、对齐语音起点、ASR 输入/计算/交付时刻。按 request_id/response_id 关联；缺失就留空。后续 judge 固定同一模型；需要比较 rating 时用相同 judge 重评旧轮次。 | 官方分数与诊断指标分开；102 不计为新回答成功；Candor Pause Handling 无回答不计漏答；绝对延迟与滞后增长不混用；不把播放确认后的文本更新当作声音起点。 |

### 10.2 随后定位的优化项目

| 编号 / 优先级 | 已观察到的现象 | 下一步与验收方向 |
| --- | --- | --- |
| D1 / 中：micro-turn 等待 | 成功启动回答的六个样本，最后一次 ASR 更新到对应模型请求为 0.745–1.151s，超过单个 600ms 窗口；尚不能把整段归因于调度器。 | 在 F1–F4 修复后，逐窗口分离时钟等待、前次串行生成占用、模型主动等待及 ASR 更新阶段。保留串行生成与无过期输入积压的约束；消融窗口时同时检查误接话和打断行为。 |
| D2 / 中：轮次模型误判 | STT/101、102 在末次 ASR 更新后仍约 11.5s、10.3s 输出“用户在说话”；UI/102 已识别换话题及 travel tips，却连续六次判为用户附和，未停播。UI/1 完整问题已到达，但停播后约 20s 未启动新回答。 | 固定文本内容与到达时间做对照，分别检查大小写/标点、增量切分、历史与控制 token。先比较补齐交付的 X2 与 Qwen，再做单因素消融；不能未经验证归因于无标点，也不能用规则直接覆盖模型语义决策。验收需同时报告 STT 接话、UI 停旧回答及新话题回答。 |
| D3 / 中：TTS 首音延迟 | STT 首 PCM 为 TTS 启动后 0.838–0.862s，UI 新回答为 0.993–1.001s；部分样本官方对齐语音起点进一步晚于首 PCM，STT/1 虽有 PCM 但官方转写为空。 | 分离文本积累、服务排队、模型/codec 计算、传输、首包前导静音和音频可识别性。对齐为空不能直接判无声音或全部归因于静音；需结合试听与波形核查。优化后同时检查语音质量与延迟，保持唯一 TTS 播放所有者。 |

**暂停状态的归因边界**：`continuous_audio` 的 `pause()` 直接返回，确实不再发布 `speech_pause=True`。但当前 `runtime_adapter._append_user()` 只向模型传文本增量，`duplex_model_service.build_prompt_ids()` 仍把空增量编码为 `<|no voice|>`，不读取 `speech_state`。因此不能把漏发暂停字段直接认定为持续“用户在说话”的根因；如果恢复该观测状态，应保持它与声学事实一致，并单独验证实际消费路径。

### 10.3 当前延迟分解基线

来源为远端 `data/runs/20261015T180154Z/fdb_driver/*/timelines/*.jsonl`，按产生该回答的 request_id 及 response_id 关联，使用事件自身的 `monotonic_timestamp`。样本为 STT/1、10、100 和 UI/10、100、101。无新回答的样本保留失败状态，不填补延迟。

| 环节 | STT 三例范围 | UI 新回答三例范围 |
| --- | --- | --- |
| 末次 ASR 更新 → 触发回答的模型请求 | 0.793–1.151s | 0.745–1.128s |
| 模型请求 → 首 token | 38–39ms | 54–69ms |
| 首 token → TTS 启动 | 33–34ms | 33–34ms |
| TTS 启动 → 首 PCM | 0.838–0.862s | 0.993–1.001s |
| 标注让轮/插话结束 → 首 PCM | 1.348–2.122s | 1.737–2.578s |

末次 ASR 更新可能早于标注边界，因此最后一行不等于前四行相加；它们起点不同。官方语音对齐延迟另见 §9，统计样本也可能不同。以上只用于定位当前剩余开销，不是 ASR 绝对识别延迟的测量。

### 10.4 执行顺序与复测约束

先完成 F1/F2 的输出与流生命周期，再完成 F3/F4，随后对 D1/D2/D3 分别定位与优化。先做覆盖异步末次输出、EOF 幂等和取消的本地契约验证；真实模型、首会话预热及 FDB 复测均在远端 conda 环境执行。

下一轮继续冻结控制模型、MOSS-TTS、600ms 窗口和相同 FDB 样本，先验证工程修复，再单独消融调度与组件参数。有限输入 EOF、输出等长裁剪及额外诊断窗口均须记录；如果对照轮缺少同样输入生命周期，补跑对照后再归因。继续维持阶段 A 范围、唯一运行底座与唯一 TTS 播放所有权。
