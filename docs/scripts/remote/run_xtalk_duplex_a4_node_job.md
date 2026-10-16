# `scripts/remote/run_xtalk_duplex_a4_node_job.sh`

阶段 A 节点执行入口：校验清单、资产和三张 GPU，检查 conda 依赖，执行 X-Talk A1–A3 回归和根仓库驱动测试，启动官方 DuplexCascade、ASR（默认 Qwen3-ASR，`DUPLEX_ASR_BACKEND=x2` 时改 X2Streaming-ASR）与 MOSS，运行官方模型 smoke、真实音频回放和 FDB v1.0 四轴推理与评分。

`assets` 步骤在 `DUPLEX_ASR_BACKEND=x2` 时额外校验 `DUPLEX_X2_SOURCE` / `DUPLEX_X2_MODEL` 存在，把缺权重从服务日志里的启动崩溃变成一条明确失败。启动前脚本把共享盘上的 Silero VAD 权重（`DUPLEX_VAD_CACHE_FILE`，默认 `/hpc_stor03/sjtu_home/xuan.zhang/.cache/xtalk/models/silero_vad.onnx`）复制进 `$XDG_CACHE_HOME/xtalk/models/`：容器内 `/tmp` 缓存为空且无法访问 GitHub raw，缺这一步会由 VAD 下载失败而非明确报错终止。`runtime_build` 步骤在启动服务前用 client 环境按运行时配置真正构造一遍模型集合（含后端 VAD），把"缺可选依赖导致回放服务进程起不来"这类问题从 30s 超时变成一条明确失败；ASR 服务健康检查超时与模型/TTS 一致取 1800s：X2 权重约 9 GB，需与另外两个服务并发从共享盘读入，20 分钟窗口偏紧。`record_step` 追加逐步 JSONL，并通过命令替换去掉多余换行，保证每条记录只占一行；`wait_http` 检查服务 health、日志及启动进程；`stop_services` 仅清理本作业进程组。失败、阻塞和未覆盖状态进入 `a4_summary.json`；自动 PASS 只表示本次自动检查通过，完整验收仍需任务单列出的额外证据。TTS 服务健康后再做一次 `tts_warmup` 预热合成：运行时补丁的码本编译发生在服务进程看到的第一帧上（首次约 43.6s），这一步把它挪到启动阶段，避免由首个被测话轮支付。

`a4_summary.json` 汇总三部分：`steps`（逐步状态，读取 `steps.jsonl` 时跳过空行，避免个别环境的多余换行中断生成）、`fdb_axes`（各 FDB 轴汇总状态）与 `replay`（回放总体与逐场景状态的紧凑概览，不嵌入完整事件）。整体状态取 `FAIL`（有任一步骤 FAIL）、`PASS`（全部步骤 PASS）或 `INCOMPLETE`（其余）；生成失败时兜底写入 `INCOMPLETE` 摘要，确保汇总文件始终存在。

## 调度约束（LowGpuUsage）

集群会在**任一被分配 GPU 连续约 6 分钟接近 0% 利用率**时中断作业。因此模型、Qwen3-ASR、MOSS 三个服务改为**并发启动**，A1–A3 与驱动回归测试放在服务加载期间执行，保证三张卡尽早持续工作；顺序启动会让后启动的 GPU 空转超时被杀。

FDB 对齐与评分阶段会使 GPU 空转，故默认不在三卡作业内执行：`DUPLEX_A4_FDB_SCORING` 默认 `0`，记 `fdb_scoring SKIPPED`，评分应另起**单 GPU** 作业完成。

## 音频与场景

默认按语义配对各自的请求音频，不再共用一个输入：

| 场景 | 默认音频（相对 `$XTALK_ROUND1_ROOT/audio/`） |
| --- | --- |
| normal | `scenarios/regular_answer_01_question.wav` |
| interruption | 请求 FDB v1.0 样本 106 的 `context.wav`（"How often should I take my dog to the vet?"），打断同目录 `interrupt.wav`（"Hold on, can we discuss something else? ..."） |
| pause | `scenarios/pause_then_continue_01_part_one.wav`,`scenarios/pause_then_continue_02_part_two.wav` |
| multi_question | `scenarios/continuous_two_questions_01_two_questions.wav` |
| long_session | 默认同 normal |

`DUPLEX_A4_SCENARIOS` 控制场景列表，`DUPLEX_A4_NORMAL_AUDIO`、`DUPLEX_A4_INTERRUPTION_REQUEST_AUDIO`、`DUPLEX_A4_PAUSE_FIRST_AUDIO`、`DUPLEX_A4_PAUSE_SECOND_AUDIO`、`DUPLEX_A4_MULTI_QUESTION_AUDIO`、`DUPLEX_A4_LONG_SESSION_AUDIO` 可覆盖各请求音频；`DUPLEX_A4_INPUT` 作为 normal 的向后兼容别名。interruption 默认取 `DUPLEX_A4_FDB_V1_ROOT`（默认 `/hpc_stor03/sjtu_home/xuan.zhang/STS/data/fdb/v1_0`）下 `synthetic_user_interruption/106/` 的 `context.wav` 与 `interrupt.wav`，可用 `DUPLEX_A4_INTERRUPTION_SAMPLE_DIR` 换样本、用 `DUPLEX_A4_INTERRUPTION_AUDIO` 单独换打断音频。`DUPLEX_A4_BARGE_AFTER_SECONDS` 默认 `0.6`，即播放开始后 0.6s 放出打断内容；`DUPLEX_A4_PAUSE_GAP_SECONDS` 默认 `1.5`。

FDB 样本 wav 为 24k 单声道（`context.wav`/`interrupt.wav` 为 float32），回放器加载时统一转 16k PCM16，无需预处理。

## 资源采样

`gpu_samples.csv` 每 5s 记录显存与利用率；`resource_samples.csv` 每 5s 记录各服务进程组（`ps -g`）的 RSS 合计，用于长会话的资源趋势与任务异常分析。

## FDB v1.0 四轴

当 `DUPLEX_A4_FDB_INPUT_ROOT` 指向 FDB v1.0 根目录时，脚本按 `DUPLEX_A4_FDB_AXES` 循环每个 `轴:子集:ASR任务`：

```
pause_handling:candor_pause_handling:default
pause_handling:synthetic_pause_handling:default
smooth_turn_taking:candor_turn_taking:default
user_interruption:synthetic_user_interruption:user_interruption
backchannel:icc_backchannel:default
```

每个子集独占输出目录 `$FDB_OUTPUT_ROOT/<轴>/<子集>`，先跑回放器 FDB 批推理（`DUPLEX_A4_FDB_LIMIT` 限制样本数，默认 5），停服务后再做官方 `get_transcript/asr.py` 词级对齐与 `evaluation/evaluate.py` 评分。脚本只把官方仓库的 `get_transcript/` 与 `evaluation/` 复制到 `$RUN_DIR/fdb_repo`——上游 `node_modules` 里含悬空符号链接且体积很大，无需进入运行目录；仅当 `DUPLEX_A4_FDB_JUDGE_MODEL` 不是官方默认 `gpt-4-turbo` 时才在工作副本里替换 `eval_user_interruption.py` 的模型名，原始 checkout 不改动；`behavior` 轴额外调用 `get_timing.py`。judge 凭据取自 `DUPLEX_A4_FDB_API_KEY_FILE`（默认 `/hpc_stor03/sjtu_home/xuan.zhang/openai_api.txt`），只经子进程环境传递，`logs/fdb_scoring_credentials.log` 只记录来源与端点，缺凭据时记 `fdb_judge BLOCKED`。`DUPLEX_A4_FDB_SKIP_JUDGE=1` 时跳过 `user_interruption` 的 GPT judge 评分（仍做 NeMo 对齐），并记录一条 `fdb_judge BLOCKED`。缺少 FDB 资产时记 `BLOCKED`；`FDB_ENV` 无法导入 `nemo.collections.asr` 时评分记 `BLOCKED`，但 FDB 推理仍保留。FDB 推理本身不需要该环境。

## 产物留存

完整产物写入 `DUPLEX_A4_RUN_ROOT/<UTC-tag>`（默认 `data/runs`），含服务日志、逐场景 WAV/报告、`steps.jsonl`、`gpu_samples.csv`、`resource_samples.csv`、FDB 推理与评分日志。关键报告复制到 `DUPLEX_A4_REPORT_ROOT/<UTC-tag>`（默认 `reports/duplex_acceptance`）纳入 git：`source_check.json`、`environment.txt`、`git.txt`、`model_health.json`、`steps.jsonl`、`a4_summary.json`、资源/GPU 采样、`replay/summary.json` 与逐场景报告、FDB 批汇总与评分日志、单测日志。

## 用法

必填 `INTERCLARIFY_DUPLEX_ROOT`；默认共享路径、环境、服务端口见脚本开头。`DUPLEX_A4_REQUIRE_INTERRUPTION=1` 要求真实 interruption 覆盖，`DUPLEX_A4_REQUIRE_COMPLETE=1` 要求所有自动步骤 PASS；输出目录重复使用会拒绝启动。提交包装器把这些 `DUPLEX_*` 变量传入节点。完整用法见 [任务单](../../xtalk_a4_remote_acceptance.md)。
`DUPLEX_ASR_BACKEND=qwen`（默认）使用 X-Talk 原生 Qwen3-ASR 服务；`DUPLEX_ASR_BACKEND=x2` 改用 X2 在线服务，并选择 `configs/xtalk_duplex_x2_runtime.json`。

## X2 对照入口

`DUPLEX_ASR_BACKEND=x2` 时，`ASR_ENV` 是独立 conda **prefix**（不是环境名），由 `DUPLEX_ASR_ENV` 指定；必须同时给出 `DUPLEX_X2_SOURCE`（X2 源码根）与 `DUPLEX_X2_MODEL`（权重目录），可选 `DUPLEX_X2_LANGUAGE`（默认 `en`）。环境准备见 [setup_x2_asr_env.md](setup_x2_asr_env.md)，服务实现见 [x2_asr_service.md](x2_asr_service.md)。运行时选择 `X2StreamingClient`、80 ms 输入、600 ms micro-turn，模型协议与 MOSS 播放链不变。F1 后 micro-turn 从会话启动开始，每拍先读最新 ASR，再发送增量或 no-voice。A2/A3 回归同时执行 X-Talk 的 `tests.test_x2_streaming_client`，覆盖延迟结果交付与取消；根仓库驱动回归执行 `tests/test_x2_asr_service.py` 验证只读服务接口。


X2 duplex 运行配置不加载 VAD，runtime_build 校验连续 ASR 对应无 VAD；Qwen 对照仍要求 VAD。两条路径均实际加载模型，加载异常仍使预检失败。

完整 X2 预热：节点入口传入 `DUPLEX_X2_WARMUP_AUDIO`（缺省为固定场景 `NORMAL_AUDIO`，非 FDB 测量样本），在 assets 阶段检查文件。服务必须完成真实语音在线出字、EOF 排空及会话释放后才监听 HTTP。
