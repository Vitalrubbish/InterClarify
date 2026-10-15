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
| X2 环境 | 独立 prefix `.../envs/xtalk-x2-asr`，见 [环境准备](../scripts/remote/setup_x2_asr_env.md) |
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

**修复**：`scripts/remote/x2_asr_service.py` 在加载权重后、`uvicorn` 监听前执行一次 `warmup()`（创建会话 → 追加 1 s 静音 → 关闭），把首个会话成本挪到作业本来就在等待的 `/health` 之前。本地验证：预热耗时 0.435 s；预热后按真实时间喂 80 ms 增量，文本在 0.64 s / 0.72 s / … / 2.08 s 逐词在线增长（修复前同一 clip 只在 `end_stream` 才出整句）。对应回归见 `tests/test_x2_asr_service.py::test_warmup_uses_one_session_and_releases_it`，服务文档见 [x2_asr_service.md](../scripts/remote/x2_asr_service.md)。

**同时记录的两项事实（本轮不修）**：

1. `x2_online` 记录显示本轮 4866 个请求里 `pause_hint` 与 `end_stream` 均为 0：`continuous_audio` 使 `pause()` 直接返回（不产生暂停边界事件），而 duplex 模式下 `TurnASREndRequested` 没有发布者，所以在线流从未被 flush。结论只在"在线持续发射能覆盖句尾"这一点上成立；若后续发现句尾缺词，需要 X-Talk 侧补一个真实的流结束发布者。
2. FDB 五轴推理的转写为 X2 风格（小写、无标点），且都产出了回答；语义分数仍以作业外的官方对齐与评分为准。

修复后以新快照重跑，见 §9。

## 9. 修复复跑（`20261015T180154Z`）

- 快照：InterClarify `04536cf`（相对 `a352751` 只增加服务预热与其文档/回归）、X-Talk `48c5952`，位于 `/mnt/cloudstorfs/sjtu_home/xuan.zhang/interclarify-retests/20261015T180154Z`。
- Manifest：183 个文件，snapshot `988ad7a00078ceaf736feddf9891a7942b725fa86bd9e29b339c6c584241d262`。
- 作业：`job-179208736349843642489-xuan-zhang`（`pdgpu-4090`，3 GPU / 24 CPU / 96 GB），场景与 FDB 范围同 §2；提交日志 `data/runs/submit_logs/submit.20261015T180242Z.sh`。
- 结果与读法待产物回填。
