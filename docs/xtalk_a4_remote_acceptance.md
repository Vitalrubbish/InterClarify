# 阶段 A 全双工运行时验收任务单

## 1. 目标与范围

本任务单把阶段 A 的验收从"入口已准备"推进到"在服务器上跑出可复核的真实证据"。范围包括：源码与依赖校验、官方 DuplexCascade 权重接入、真实 ASR/MOSS 音频回放、用户打断、长会话压力、FDB v1.0 对齐与评分、零旁路验证，以及人工试听与资源趋势。

本轮**只做 Duplex 模式**，不做原生 X-Talk 对照；backchannel 语义场景留给后续 FDB v1.5。

## 2. 本轮已确定的决定

| 主题 | 决定 |
| --- | --- |
| 开发与同步 | 直接在服务器共享盘工作树原地开发；无本地/远端同步。提交前原地生成 manifest，作业内校验 |
| 集群镜像与资源 | `sjtu_yukai-xuanzhang-xtalk-round1:v0.4`，`pdgpu-4090`，3 GPU / 24 CPU / 96G |
| GPU 分卡 | 官方模型 GPU0、Qwen3-ASR GPU1、MOSS GPU2；FDB 对齐/评分与模型服务分阶段，避免共占显存 |
| normal 请求音频 | `regular_answer_01_question.wav` |
| interruption 请求/打断 | 请求 FDB v1.0 样本 106 的 `context.wav`（短答问题），打断同目录 `interrupt.wav`，`--barge-after-seconds` 调小（0.6s，自首个音频包起算） |
| 每场景音频 | 扩展回放器支持 per-scenario 请求音频（normal / interruption / long_session 各用各自输入） |
| 新增回放场景 | `pause`（两段间隔续说）、`multi_question`（连续两问）；backchannel 本轮不做 |
| 长会话 | 30 轮，并补 RSS 与队列深度采样 |
| 零旁路 | 以 X-Talk 单测为主（断言剔除 `DirectAudioManager` 与原生语义 manager、`backchannel_model is None`），FDB 行为指标作佐证 |
| FDB 数据 | 复用本机 FDB **v1.0**（`/hpc_stor03/sjtu_home/xuan.zhang/STS/data/fdb/v1_0`）；v1.5 本轮不做 |
| FDB 子集 | 四轴：pause_handling、smooth_turn_taking、user_interruption、backchannel |
| FDB 样本量 | 每子集 5 个样本（pause_handling 的 candor 与 synthetic 两个子集各 5 个） |
| FDB 评分环境 | 共享 miniconda 新建 `full-duplex-bench`（即节点脚本默认 `DUPLEX_A4_FDB_ENV`）；暂不预加 torchaudio 兼容处理，出错再补 |
| FDB judge | `user_interruption` 用 OpenAI `gpt-4-turbo` 官方默认模型口径；凭据从本机 key 文件读入子进程环境，脚本与日志不记录 |
| 四轴作业组织 | 一次作业内循环四个轴，各出独立子目录 |
| 严格度 | `DUPLEX_A4_REQUIRE_INTERRUPTION=1`、`DUPLEX_A4_REQUIRE_COMPLETE=1` 同时开启 |
| 播放与音质 | 自动证据（已播文本单调、未播尾部不计已播、播放期间 ASR 持续更新）+ 人工试听关键 WAV |
| ASR 输入契约 | **2026-10-14 变更**：`asr_streaming.unfixed_chunk_num: 0` + `emit_committed_prefix: true`，只把解码器**已定稿**的文本交给模型（对齐官方只喂 Kyutai 定稿词的契约）；理由、证据与单调性证明见 §9.5 |
| 产物留存 | 完整产物在 `data/runs/`；关键报告复制到 git 跟踪的 `reports/duplex_acceptance/<UTC-tag>/` |
| manifest 门禁 | 保留：原地生成 `source_manifest.json`，作业内逐文件 SHA256 校验 |
| 原生对照 | 本轮不做，后续在原生 LLM/TurnSense/ASR/MOSS 节点成对补测 |

## 3. 测试范围与通过证据

| 项目 | 执行入口 | 通过证据 |
| --- | --- | --- |
| 源码与依赖 | `create_duplex_source_manifest.py` + 节点校验 + A1–A3 回归 | `source_check.json`、`environment.txt`、测试日志 |
| 官方模型接入 | `duplex_runtime_smoke.py` | 严格权重装载、health、token ID、BF16、raw wire token |
| 真实 ASR/TTS | `duplex_a4_replay.py` normal 场景 | 真实 WAV→ASR partial→LLM→MOSS PCM→播放确认 |
| 用户打断 | 同一回放器 interruption 场景 | 同 response 的 interruption 原始 token、reason、由打断触发的 reset 记录，以及 reset 后该 response 音频冻结 1s |
| 停顿与连续提问 | 回放器 pause / multi_question 场景 | 不提前抢答、连续两问被依次处理、无协议错误 |
| 会话压力 | long_session 场景 `--rounds 30` | 持续收音、多个 micro-turn、无协议错误、GPU/RSS/队列采样 |
| FDB v1.0 | 同一回放器批处理 + 官方对齐/评分 | 新生成等长输出 WAV、官方转写、判分日志 |
| 人工项 | 关键 WAV 试听 + 资源趋势 + shutdown | 试听结论、资源趋势曲线、shutdown 日志 |

## 4. 环境与资产准备

### 4.1 源码

原地开发后，在仓库根目录生成清单：

```bash
conda run -n paratalker-dev python scripts/remote/create_duplex_source_manifest.py
```

固定 X-Talk 提交 `2f8a43343dd83153298c416d270a8843b023abc0`；作业执行前逐文件校验，禁止复用非空运行目录。模型不下载、不训练，沿用服务器现有官方 checkpoint、Qwen2 基础模型、`models.lock.json`、ASR/MOSS/codec 与参考音色。

### 4.2 音频素材

场景音频在 `/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/audio/`（16k mono PCM16，`manifest.json` 记录来源与 SHA256）。语义配对：

| 角色名（`benchmark/audio/` 副本） | 来源（`$XTALK_ROUND1_ROOT/audio/`） | 时长 |
| --- | --- | --- |
| `normal.wav` | `scenarios/regular_answer_01_question.wav` | 2.96s |
| `interruption_request.wav` | FDB v1.0 `synthetic_user_interruption/106/context.wav` | 3.38s |
| `interruption_barge.wav` | FDB v1.0 `synthetic_user_interruption/106/interrupt.wav` | 4.49s |
| `pause_first.wav` | `scenarios/pause_then_continue_01_part_one.wav` | 3.12s |
| `pause_second.wav` | `scenarios/pause_then_continue_02_part_two.wav` | 2.72s |
| `multi_question.wav` | `scenarios/continuous_two_questions_01_two_questions.wav` | 4.96s |

`benchmark/audio/` 下是按此角色名整理的副本（位于 gitignore 的 `benchmark/`，仅供试听与规划）；节点脚本默认对 normal/pause/multi_question/long_session 指向 `$XTALK_ROUND1_ROOT/audio/scenarios/` 的原始文件，对 interruption 指向 FDB 样本 106。interruption 样本的转写取自 `interrupt.json`：请求为 “How often should I take my dog to the vet?”，打断为 “Hold on, can we discuss something else? What's a good recipe for a quick dinner?”。上游 `barge_in_stop` 片段与其余自定义片段的转写仍为 `pending_manual_annotation`，判分与试听结论须注明。参考音色为 `audio/reference.wav`。

### 4.3 FDB v1.0

数据位于 `/hpc_stor03/sjtu_home/xuan.zhang/STS/data/fdb/v1_0`，五个子集：`candor_pause_handling`、`candor_turn_taking`、`icc_backchannel`、`synthetic_pause_handling`、`synthetic_user_interruption`。轴↔子集映射：

- pause_handling → `candor_pause_handling`、`synthetic_pause_handling`
- smooth_turn_taking → `candor_turn_taking`
- user_interruption → `synthetic_user_interruption`
- backchannel → `icc_backchannel`

输入根目录必须是**单个子集**，下一层为样本目录，样本含 `input.wav`。输出目录位于输入树外的新空目录。

### 4.4 FDB 评分环境

按 [Full-Duplex-Bench v1/v1.5](https://github.com/DanielLin94144/Full-Duplex-Bench/tree/3e799c45a045256f47d5f1c9cda90157e2d2ec9e/v1_v1.5) 固定提交 `3e799c45a045256f47d5f1c9cda90157e2d2ec9e`，在共享 miniconda 新建 `full-duplex-bench` 环境，装 NeMo 对齐与评分依赖。暂不预加 torchaudio 兼容处理，如官方脚本因 `torchaudio.load` 后端报错再补。

## 5. 回放器改动要求（`scripts/remote/duplex_a4_replay.py`）

1. 支持 per-scenario 请求音频：normal / interruption / long_session 各自传入不同 WAV，不再共用一个 `--audio`。
2. 新增 `pause` 场景：先送第一段，停顿后再送第二段，断言系统不提前给出最终回答、并在第二段后完成回答。
3. 新增 `multi_question` 场景：一次送入连续两问，断言系统依次产生回答、音频与协议正常。
4. 播放自动证据：从 timeline 与播放回执提取"已播文本单调、未播尾部不计已播、播放期间 `update_asr` 持续"的可量化字段，供 `classify` 与报告使用。
5. 保留原有 interruption / long_session / FDB 判定，`classify` 继续严格区分 PASS/FAIL/INCONCLUSIVE。
6. ~~FDB 场景增加"输入结束后静音续播窗口"（`--post-input-seconds`）~~：**2026-10-15 撤销**。官方 `model_inference/*/inference_*.py` 用 `SynchronizedRecorder(out_sr, target_sec=输入时长, outfile)` 写 `output.wav`（"Uses wall-clock timing to ensure output matches input timeline"），即官方口径就是**输出时长 == 输入时长**，我们回放器的 `normalize_wav_duration` 正是照此裁剪/补零。所以录在输入之外的音频一定被丢弃，加窗口救不回回答：要让回答进入打分，它必须落在**输入自身的时间轴内**。真正的杠杆是在输入内尽早释放用户文本（§9.5.4.2 的后端 VAD）。

## 6. 集群运行

已进入分配到三张 GPU 的节点时：

```bash
export INTERCLARIFY_DUPLEX_ROOT="$PWD"
export CONDA_SH=/opt/conda/etc/profile.d/conda.sh
bash scripts/remote/run_xtalk_duplex_a4_node_job.sh
```

由提交包装器提交到 `pdgpu-4090`：

```bash
export INTERCLARIFY_DUPLEX_ROOT="$PWD"
bash scripts/remote/submit_xtalk_duplex_a4_job.sh
```

关键环境变量。（**FDB 四轴才是本作业的核心**：`DUPLEX_A4_FDB_INPUT_ROOT`、`DUPLEX_A4_FDB_REPO` 与 `DUPLEX_A4_FDB_SCORING=1` 必须由入口传入，否则 `fdb_inference` 记为 `BLOCKED`、`fdb_scoring` 记为 `SKIPPED`；judge 凭据默认取仓库根的 `openai_api.txt`。回放默认只跑 `normal` 与 `interruption` 两个场景。）

```bash
export DUPLEX_A4_REQUIRE_INTERRUPTION=1
export DUPLEX_A4_REQUIRE_COMPLETE=1
export DUPLEX_A4_ROUNDS=30
export DUPLEX_A4_BARGE_AFTER_SECONDS=0.6
export DUPLEX_A4_SCENARIOS="normal interruption"   # 回放只跑这两个场景（默认已改为这两个）
```

节点脚本按语义配对向回放器传 `--scenario-audio`（normal/interruption/pause/multi_question/long_session 各用各自请求音频），并每 5s 采集各服务进程组 RSS 到 `resource_samples.csv`，与 `gpu_samples.csv` 合并分析。

FDB v1.0 根目录与四轴由入口传入（每轴每子集独立输出目录）：

```bash
export DUPLEX_A4_FDB_INPUT_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/STS/data/fdb/v1_0
export DUPLEX_A4_FDB_OUTPUT_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/InterClarify/data/runs/<tag>/fdb
export DUPLEX_A4_FDB_LIMIT=5
export DUPLEX_A4_FDB_REPO=/hpc_stor03/sjtu_home/xuan.zhang/Full-Duplex-Bench
export DUPLEX_A4_FDB_ENV=full-duplex-bench
export DUPLEX_A4_FDB_JUDGE_MODEL=gpt-4-turbo
export DUPLEX_A4_FDB_BASE_URL=https://api-2.xi-ai.cn/v1
export DUPLEX_A4_FDB_API_KEY_FILE=/hpc_stor03/sjtu_home/xuan.zhang/openai_api.txt
export DUPLEX_A4_FDB_COMMIT=3e799c45a045256f47d5f1c9cda90157e2d2ec9e
```

## 7. FDB v1.0 对齐与评分

一次作业内依次处理四个轴，各轴独立子目录：

- `pause_handling`：`candor_pause_handling` 与 `synthetic_pause_handling` 各 5 个样本；
- `smooth_turn_taking`：`candor_turn_taking` 5 个样本；
- `user_interruption`：`synthetic_user_interruption` 5 个样本，先按 `interrupt.json` 截断再做 ASR；
- `backchannel`：`icc_backchannel` 5 个样本。

集群按 **LowGpuUsage** 策略中断作业：任一被分配 GPU 连续约 6 分钟接近 0% 利用率即被杀。因此节点脚本并发启动三服务并在加载期间跑回归；FDB 对齐与评分会使 GPU 空转，默认 `DUPLEX_A4_FDB_SCORING=0` 记 `SKIPPED`，评分另起单 GPU 作业。

流程：回放器生成推理 WAV（与输入等长）→ 官方 `get_transcript/asr.py` 词级对齐（NeMo）→ 官方 `evaluation/evaluate.py` 评分。节点脚本只把官方仓库的 `get_transcript/` 与 `evaluation/` 复制到 `$RUN_DIR/fdb_repo`（避免上游 `node_modules` 进入运行目录），并在 `DUPLEX_A4_FDB_JUDGE_MODEL` 非官方默认 `gpt-4-turbo` 时才替换 `eval_user_interruption.py` 的模型名，原始 checkout 始终不改动。judge 凭据从 `DUPLEX_A4_FDB_API_KEY_FILE`（默认 `/hpc_stor03/sjtu_home/xuan.zhang/openai_api.txt`，仅在容器内可读）取出并只经子进程环境传给官方脚本，日志只记录凭据来源与端点，不记录 key；缺凭据时记 `fdb_judge BLOCKED` 而非 FAIL。对齐与评分阶段先停掉模型服务，避免共占显存。缺资产或环境时记 `BLOCKED`，模型未覆盖语义时记 `INCONCLUSIVE`。

**本轮暂缓 GPT judge**：设置 `DUPLEX_A4_FDB_SKIP_JUDGE=1`，跳过 `user_interruption` 的 OpenAI judge 评分（仍做 NeMo 对齐），并记录 `fdb_judge BLOCKED`；`backchannel`、`pause_handling`、`smooth_turn_taking` 三轴不依赖 GPT，正常评分。因此本轮 `a4_summary.json` 预期为 `INCOMPLETE`，`DUPLEX_A4_REQUIRE_COMPLETE` 应相应关闭。

作业内之所以暂缓，是因为对齐与评分会让已分配的 GPU 长时间接近空转，会触发集群 LowGpuUsage 中断；本轮的 judge 改由 §7.1 的独立入口在同一台机器上补跑，结果见 §9.2。

### 7.1 独立评分入口与凭据

为把对齐与评分从 GPU 作业里拆出来，另提供两个入口：

- [setup_fdb_scoring_env.sh](../scripts/remote/setup_fdb_scoring_env.md)：把评分环境固定到 CUDA 12.x 版 torch 与 NeMo 2.x。不锁版本时会必然失败——普通安装解析到 `torch +cu130` 需要 CUDA 13，而本机与集群节点驱动均为 570.x（仅到 CUDA 12.8）；`nemo_toolkit 3.0.0` 又把 `ASRModel` 变成抽象类，官方 `ASRModel.from_pretrained` 无法加载 parakeet 归档。
- [run_fdb_llm_judge.py](../scripts/remote/run_fdb_llm_judge.md)：对已有 FDB 输出树跑官方对齐 + judge，凭据从项目根 `openai_api.txt` 读取，产物写 `align_<task>.log`、`judge_<task>.log` 与 `llm_judge_summary.json`。

judge 走 OpenAI 兼容端点 `https://api-2.xi-ai.cn/v1`。实测该端点直接支持官方默认的 `gpt-4-turbo`（`seed=0`、输出格式符合官方解析），因此**沿用官方默认 judge 模型**即可保证口径可比；端点列出的 gpt-5.x/6.x 系列当前返回 503「无可用通道」，不作为 judge。凭据只经子进程环境传递，不落入日志与报告。

## 8. 零旁路验证

以 X-Talk 单测为主：新增 `test_duplex_mode_removes_every_bypass_manager`，并强化 `test_service_disables_native_semantic_paths`，显式断言 `duplex_manager_classes()` 与服务的实际注册集合剔除 `DirectAudioManager` 与全部原生语义 manager（`LLMAgentContextManager`、`LLMAgentConsumptionManager`、`TurnTakingManager`、`TurnDetectorManager`、`MultiSpeakerTurnContextManager`），同时保留 `ASRManager`、`TTSManager`、`TTSPlaybackManager`、`VADManager` 等非语义组件。duplex 模式移除了持有 `DefaultAgent` 的 `LLMAgentContextManager`，因此本地 `backchannel_model` 语义路径结构上不存在，无需单独断言。FDB 的 `backchannel` 轴指标仅作现象侧佐证，不作为硬门禁。该单测随节点作业的 A2/A3 回归一并执行。

**VAD 在仲裁链路上的定位（2026-10-13 澄清）**，三点：

1. **不参与仲裁**：`duplex_control/service.py` 的 `duplex_manager_classes()` 换掉 `TurnDetectorManager` 等语义 manager 后，只留 `MicroTurnAssembler` + `DuplexRuntimeAdapter` 作为唯一裁判；`micro_turn.py` 明确"continuous ASR independently of VAD semantic decisions"；`duplex_control/` 内没有任何 `VADSpeechStart/End` 的消费者（消费方只有 `TurnDetectorManager`、`LatencyManager` 指标、`input/output_gateway` 转发与 `VADManager` 自身复位）。本轮作业也没有启动 TurnSense 服务。
2. **组件保留但空转**：`VADManager` 不在被替换名单里，但其实现是"仅在后端 VAD 模型被配置时生效"（`self.vad = models.get(VAD)`）。本轮 `a4_runtime.json` 只配了 `asr`/`tts`，因此它不发事件；本轮产物里也未见 `origin="server"` 的 VAD 事件。
3. **客户端侧是脚本化 VAD**：`xtalk_link_check.LinkClient` 在音频前发一次 `vad_speech_start`、音频发完发一次 `vad_speech_end`。本轮 FDB 报告里那对事件即出自它（`round: 0`，起 `0.0002s`、止 `27.55s`=输入时长），等价于"整段音频是一次不间断的说话"，文件内部的停顿/静音从不以 VAD 事件形式传入。

## 9. 产物留存

- 完整产物：`data/runs/<UTC-tag>/`（gitignore），含 `steps.jsonl`、`run.log`、`gpu.csv`、`gpu_samples.csv`、`resource_samples.csv`、服务日志、逐场景 WAV 与报告、FDB 推理与评分日志。
- 关键报告：复制到 `reports/duplex_acceptance/<UTC-tag>/` 并纳入 git：
  - `source_check.json`、`environment.txt`、`git.txt`、`model_health.json`
  - `replay/summary.json` 与逐场景 `report.json`
  - `a4_summary.json`、`steps.jsonl`、`gpu_samples.csv`、`resource_samples.csv`
  - FDB 各轴 `fdb_summary.json`、对齐日志、评分日志与汇总
  - 单测结果日志
- `reports/` 需在 `.gitignore` 中对 `*.jsonl`、`*.log` 加例外，确保这些报告被跟踪。

### 9.1 早期轮次与结论（2026-10-13 ~ 10-14）

第一次 3 卡作业（`job-179187528229476527799`，`failures=0`）与后续几轮都**没有通过验收**：驱动/运行时/服务/FDB 推理全 PASS，但语义分数低、三个非打断轴几乎不产出音频。中间过程（标记探针的四个变体、逐拍 trace 重建、作废轮次）已随清理移除，本节只保留仍然有效的结论。

| 轮次 | `user_interruption` rating / TOR / latency |
| --- | --- |
| 2026-10-13 首轮（§9.2） | 0.6 / 1.0 / 1.536 |
| 2026-10-14 方案 B 复检（§9.6.1） | 2.25 / 0.875 / 4.10 |
| 2026-10-15 后端 VAD 生效（§9.7） | **4.60 / 1.00 / 2.848** |

FDB 样本自带 `input.wav` 与 `output.wav` 等长、非打断三轴用户末词几乎贴着文件结尾，所以"输入之后"产生的回答必然录不到；`synthetic_user_interruption` 是唯一自带 15s 尾静音的轴，也因此是唯一早先就能被 judge 打分的轴。

### 9.2 首轮 `user_interruption` 与两条机制结论（2026-10-13）

官方 `asr.py --task user_interruption` 按 `interrupt.json` 的 `timestamp[1]` 硬裁 `output.wav`，`eval_user_interruption.py` 只在 `TOR=1` 时把裁剪段喂 judge 评相关性——**该轮 `TOR=1.0` 不代表让出话轮**，旧答案的音频还在播，裁剪段必然有语音（rating 0.6 由此而来）。

仍然有效的两条机制结论：

1. **打断标记由模型自身的说话状态主导**：打断到达前模型**已经开口** → 吐 `<|user backchannel|>`（只 flush 不 reset，旧答案继续）；**尚未开口** → 吐 `talking`/`interruption`（会 reset）。4/5 样本都在约 3s 就答完上下文问题，而合成打断固定在 9.2–9.8s，必然落进"我正在说话"的窗口。
2. **"ASR 比用户输入慢"已被排除**：更新间隔中位数 0.61s（每拍一条）、逐词延迟 0~0.6s 且不累积，即延迟就是"0.6s 分块 + 推理"的地板。

上游参照（仓库自带 FDB 结果表，归档在 `reports/duplex_acceptance/reference/`）：DuplexCascade 在同一 `synthetic` 子集上 User Interruption 为 TOR 0.955 / GPT-4o 4.016 / latency 1.225，其余三轴 Pause Handling 0.058/0.222、Backchannel 0.218/0.009/0.949、Smooth Turn Taking 0.832/1.724。

### 9.3 全量 FDB v1.0 运行的前置要求

1. **保留逐拍证据**：`fdb_driver/*/timelines/` 必须落盘，并记录每拍的 micro-turn 文本与模型 raw output（早先为省空间删过 timelines，导致只能从服务日志反推）。
2. **统计协议 token**：汇总各轴 `<|no voice|>` / `talking` / `finish talking` / `interruption` / `backchannel` 的次数与位置。
3. **记录节奏指标**：复位后到首音频的延迟、已播文本的最大停顿。
4. **消融实验已完成**：文本归一化（`raw`/`strip`/`strip_lower`/`burst`）能确定性翻转打断判定，但没有一个变体构成修复（各救一个样本且互相抵消），标点/大小写这条线作废。
5. 复听让出话轮样本的 `output.wav`（parakeet 会把 `travel tips` 转成 `trap dapple tips`）。
6. ~~输入结束后的录制/续播窗口~~：**已撤销**——官方 `SynchronizedRecorder(out_sr, target_sec=输入时长, outfile)` 同样按输入时长写 `output.wav`，延长录制不改变可评分内容；正确做法是在输入自身时间轴内尽早释放用户文本（§9.5.4.2）。

### 9.4 其它三轴的作答统计与输入侧缺陷（2026-10-13，旧 tag）

25 个样本里 6 个整段无 TTS 音频、13 个不足 5 词；除 `user_interruption` 外 `<|user is talking|>` 占 83–97% 微拍。

| 子集 | 官方期望 | 无音频 | 作答 <5 词 | 平均作答 | `talking` 占比 |
| --- | --- | --- | --- | --- | --- |
| `icc_backchannel` | TOR↓ / Freq↑ | 1/5 | 5/5 | 0.8 词 | 91% |
| `candor_pause_handling` | TOR↓ | 1/5 | 2/5 | 16.2 词 | 89% |
| `synthetic_pause_handling` | TOR↓ | 1/5 | 3/5 | 4.4 词 | 83% |
| `candor_turn_taking` | TOR↑ | 3/5 | 3/5 | 3.8 词 | 97% |
| `synthetic_user_interruption` | TOR↑ | 0/5 | 0/5 | 23.2 词 | 59% |

其中 `candor_turn_taking` 的 3/5 沉默是**真失败**（`turn_taking.json` 的 `[TURN-TAKING]` 标记在文件中段，让轮后仍有余量）；Pause Handling / Backchannel 的 TOR 方向是"越低越好"，其少言本身不构成异常。输入侧的两个缺陷：

1. **ASR 语言跑飞（未修）**：`icc_backchannel/1` 全程德语、`/11` 全程西班牙语，而两份输入按 `transcription.json` 都是英语。原因：`scripts/remote/qwen3_asr_service.py` 初始化流式状态时只传了切块参数，**没有传 `language`/`context`**，而 `qwen_asr` 的 `init_streaming_state` 支持强制语言。
2. **ASR 更新以"改写末尾"为主（已修）**：25 样本共 333 次改写，会让模型"答一个用户没说完的版本"，见 §9.5。

### 9.5 prompt 与输入流的保真核查（2026-10-14）

核对官方 `server.py` 后：**prompt 侧没有偏离**，真正的偏离在输入端——官方只把"已定稿的词"交给模型，而我们把 ASR 的易变尾巴也交了出去。

#### 9.5.1 BOS 与 prompt 展平（结论：一致，无需修改）

逐项核对（BOS、user 头/尾、assistant 微轮、收尾、`max_new_tokens=64`、0.6s 微轮时钟）全部一致：官方那行 BOS 前插是**死代码**（checkpoint 自带 tokenizer 与 `Qwen/Qwen2-7B-Instruct` 的 `bos_token` 均为 null，实测 `bos_token_id = None`），而当时重建的 prompt 逐拍与探针记录的 `prompt_tokens` 对账 **223/223** 一致。

#### 9.5.2 官方输入契约：只喂"已定稿的词"

官方 `stt_receiver_task()` 只处理 `type == "Word"`（源码注释 `# ignore Step / EndWord / Marker for now`），每拍 `" ".join` 后 append 进历史 → **单调追加、只见定稿**。我们 `qwen_asr` 每 0.6s 重喂全量音频并回滚末尾 `unfixed_token_num=5` 个 token，返回的 `state.text` 带着这段易变尾巴。

#### 9.5.3 后果：答案会"答一个用户没说完的版本"（已复现到拍）

`synthetic_user_interruption/1` 的决定性三拍：

| 拍 | 时钟 | ASR 可见文本 | 送给模型的 user 历史 | 模型输出 |
| --- | --- | --- | --- | --- |
| 0 | 1.227s | `How.` | `How.` | `<\|user is talking\|>` |
| 1 | 1.827s | `How can I save my life?` | 同（与录制一致） | `<\|user finish talking\|>Saving your life involves …` |
| 2 | 2.427s | `How can I save money?` | **同一槽位被回写** + 上拍 assistant 文本 | `… and mental health. Here are some tips …` |

即 1.25s 的版本已让模型开口，1.84s 的改写回写了**已经发出的** user 微轮，而基于旧版本生成的 assistant 文本已在历史与 TTS 里，最终播出缝合体（`…your physical and mental health…to help you save money effectively`）。四个轴合计 333 次改写，其中 3 个样本的答案里真留下了被撤回的词（`save my life`→`save money` 留下 life 等）。

#### 9.5.4 修法选项与选定方案（2026-10-14 选定 B 并已实现）

| 方案 | 做法 | 代价 |
| --- | --- | --- |
| A. 收紧流式参数 | `unfixed_token_num: 0` + `unfixed_chunk_num: 0` | ASR 失去边界纠正能力，尾部 WER 上升 |
| **B. 只暴露定稿前缀（已实施）** | 关掉"前 N 个 chunk 独立解码"（`unfixed_chunk_num: 0`），`is_final=false` 只返回去掉末尾 K 个 token 的前缀，`is_final=true` 释放全量 | 可见文本比内部晚 K 个 token（词级 1–6 词）；尾巴只由调用方的显式边界释放 |
| C. 运行时兜底 | `REWRITE` 时连 assistant 一起回滚重生成 | 与"已被听到的内容不可撤销"冲突，官方无此语义 |

**为什么必须同时关掉 `unfixed_chunk_num`**：只有它为 0 时，第 n 拍的前缀才等于 `truncate_K(R_{n-1})`，从而 `truncate_K(R_n)` 逐拍单调追加；保留 2 会让前几拍的"定稿前缀"整体换掉，模型照样看到改写。

#### 9.5.4.1 契约实现的两个真 bug 与修法（2026-10-15 实测）

一次性对比作业（`20261015T023552Z`，40 样本 / 729s 音频）本身支持"保持 `unfixed_chunk_num: 0`"，同时暴露两个真 bug：

1. **可见文本会被永久冻结**：`advance_committed` 用**字符串** `proposed.startswith(visible_text)` 保单调，而再解码常改句末标点/空格（`'I never like.'` → `'I never like I know…'`），一旦已释放文本含这类字符，此后任何延长都被拒绝。实测 `candor_pause_handling/1` 冻住 26.3s（330 拍）；40 样本"raw 比可见多出的词数"中位 15 词、最大 62 词。
2. **运行时从不释放扣住的尾巴**：`is_final_chunk=True` 只由 `TurnASRPauseRequested`/`TurnASREndRequested` 触发，而 duplex 模式把 `turn_taking_manager`/`TurnDetectorManager` 移出后二者**没有发布者**，服务整场拿不到 `is_final=true`。

修法（均已实现）：

- **服务侧**：`advance_committed` 改为 **token 级**单调推进（`committed_token_ids`/`decode_token_prefix`），只扣住末尾 `unfixed_token_num` 个 token；回改到已交付 token 时保持已交付文本、累计 `stalls` 并打 warning；**删除"本次解码无新增文本就释放尾巴"这条规则**（句内停顿不是片段结束，正是它把 `'I never like.'` 交了出去）。`asr-smoke` 记录 `commit_stalls`，汇总器新增「冻结」「提交停滞」列；单测 `tests/test_qwen3_asr_service.py` 9 个（含 `'I never like.'` 回归用例）。
- **运行时侧**：`duplex_control/micro_turn.py` 订阅声学 `VADSpeechEnd` → 发 `TurnASRPauseRequested`（保留 ASR 状态、只触发一次识别，与官方 `TurnTakingManager` 在配置了端点检测时的做法一致），`VADSpeechStart` → 发 `TurnASRStartRequested` 恢复采集（否则音频只进 1s 预缓冲会丢话）。选 VAD 而非 micro-turn 收口：改动最小、不干扰 in-band 轮次判定、不把长句切碎。测试：`tests/test_duplex_runtime.py` 3 例 + `tests/test_asr_finalization.py` 全链用例（`VADSpeechEnd` → `TurnASRPauseRequested` → `AudioConsumer.pause()` → 客户端真的收到 `is_final=True`）。
- **已知未做**：硬回合结束（`TurnASREndRequested`，会重置 ASR 状态）仍无发布者，ASR 文本跨回合累积；官方在线 STT 本是一路连续流，是否该重置需专门验证。

**复测与定稿**（`20261015T023552Z`）：window-0 的「挂起的词」中位/最大 **4.0/4.0**、「冻结」**0.00s**、`提交停滞` **0**、可见改写 **0**，与 window-2 完全一致。**`unfixed_chunk_num` 保持 `0`**：两臂最终转写逐词相同（词级距离中位数 0.0）、提交延迟相同（中位 0.86s）、raw 改写 532 vs 539，对齐官方只多花开销而无收益。该修法只改变"模型能看到的文本"，不撤回任何已生成/播报的音频。

#### 9.5.4.2 后端 VAD：让声学边界真的到达 ASR（2026-10-15）

**问题（tag `20261015T032348Z`）**：运行时**没有加载后端 VAD**（`VADManager` 首行 `if self.vad is None: return`），唯一的 `vad_speech_end` 来自 input gateway 在音频流边界的代发，上面接好的释放链路因此被推迟到文件结束：`synthetic_user_interruption/101`（28.27s，语音 13.0s 结束、其后 15.27s 数字静音）里 `speech_pause=True` 直到 27.13s 才出现，多数样本 `response: ''`、`tts_audio_bytes: 0`。

| 位置 | 改动 | 说明 |
| --- | --- | --- |
| `configs/xtalk_duplex_runtime.json` | `vad` 槽位 `SileroVAD`（threshold 0.5） | `VADManager` 的唯一开关；模型取 `~/.cache/xtalk/models/silero_vad.onnx`（共享盘已缓存） |
| 同文件 `service_config` | `vad_redemption_ms: 600` | 最后一个语音帧后累计 600ms 静音才发 `VADSpeechEnd` |
| 镜像 **v0.4** | client 环境显式装 `xtalk[silero-vad]` 并钉 `onnxruntime==1.31.0`（离线取自 wheelhouse） | 把"运行时需要 onnxruntime"写进配方。v0.3 实际已含同版本，**v0.4 就本故障而言与 v0.3 内容等价**，只是改用增量层发布（`OVERLAY=1`：几分钟/几百 MB；从零重建要 1 小时/十几 GB） |

**为什么是 600ms**：ASR 客户端的节奏是 `chunk_ms: 600`，停顿判定不能早于"句尾那段已经交给 ASR"，否则 pause 的 flush 会漏掉最后一段，而那段只躺在 1s 预缓冲里等下一次 `VADSpeechStart`（用户不再说话就永远不被识别）。600ms 与 chunk 对齐使 flush 带上句尾，代价是释放点晚 100ms；若复测仍见句尾丢词可上调到 700–800ms，结构不变。

**更正一处归因**：最初把 tag `20261015T040437Z` 的失败归因于"client 环境缺 `onnxruntime`"，**该结论不成立**——v0.3 镜像里 `onnxruntime 1.31.0` 早已存在，且同镜像同配置在本机容器内 `Xtalk.from_config` + 绑定端口只要 **1.9s**（`--server-timeout` 默认 60s）。该轮的真实成因**仍未确定**（本机无法复现、作业现场日志不足）；真正暴露的是**可观测性缺陷**：日志里只有父进程的超时 traceback，看不出子进程是崩了还是卡住。已修：

- `_serve` 把启动进度写入 `$XTALK_SERVE_LOG`（`start` → `imports ok` → `app mounted` → `uvicorn returned`），失败写完整 traceback；`_wait_for_server` 在端口不开时报子进程状态（`exited with code N` / `still alive (stalled before binding its port)`）并附日志尾部；回放器把日志指到 `<--out>/xtalk_serve.log`，随产物留存。
- 节点脚本新增 **`runtime_build`** 前置步骤：启动服务前用 client 环境按运行时配置真正构造一遍模型集合并要求 `models.get(VAD)` 非空，把这类问题从"超时后翻日志"变成一条明确失败。

**顺带修掉的评分阻塞**：`fdb_scoring BLOCKED` 是环境导入问题而非缺 NeMo——该镜像上 `nemo.collections.asr` 需要 `NUMBA_CUDA_USE_NVIDIA_BINDING=0`，已在节点脚本打分段 export。三卡作业内仍默认跳过评分（对齐阶段 GPU 空转会被按 LowGpuUsage 杀掉），评分用 [run_fdb_llm_judge.py](scripts/remote/run_fdb_llm_judge.md) 对已有产物树单跑。

### 9.6 复检结果与 TTS 交付瓶颈（2026-10-14）

#### 9.6.1 方案 B 复检（tag `20261014T033949Z`）

单卡 ASR 契约 A/B + 3 卡 `user_interruption` 复跑，官方对齐与 judge 由 `run_fdb_llm_judge.py` 独立运行。ASR 侧可见改写 **0/0/0/0/0**、两模式最终转写逐词相同（append-only 契约成立且不损准确率），作答质量明显回升（101 从 0→5、1 从 0→2）：

| 项 | 复检前（§9.2） | 复检后 | 上游 DuplexCascade |
| --- | --- | --- | --- |
| `average_rating` | 0.6 | **2.25** | 4.016 |
| `average_take_turn` | 1.0（旧答案音频仍在播的假阳性） | 0.875（样本 `10` 无音频） | 0.955 |
| `average_latency` | 1.536 | **4.10** | 1.225 |

#### 9.6.2 4–6s 延迟的四段分解（实测）

按 FDB wav 时钟（`interrupt.json timestamp[1]` → 官方对齐的 `output.json chunks[0]`）：用户说完 → ASR 全量文本 0.13–0.84s（方案 B 的设计代价）→ runtime 起新 TTS 1.13–1.17s（0.6s 节拍 + 模型多要一拍才输出 `<|user finish talking|>`）→ 首个 `tts.chunk_ready` 0.96–1.12s（MOSS prefill）→ **对齐器认出的首个词 1.21 / 3.23 / 3.12s（主因）**。同期交付率只有 0.2–0.5 倍实时，而 LLM 已推入 169 词 ≈ 67.6s 语音（4.8 倍实时）→ 瓶颈在 LLM 之后。

#### 9.6.3 机制：MOSS-TTS-Realtime 的每帧成本

codec 帧率 24000/1920 = **12.5Hz**，每帧 80ms 音频；**每帧 = 1 次 backbone 前向 + 16 次 local transformer 前向（`rvq=16` 逐码本串行）+ 每码本一次采样**。上游只在非 flash-attention 路径编译该循环，而我们的 `attn_impl=flash_attention_2` 部署是全 eager，采样默认 `do_sample=True` + 全词表 sort 的 nucleus → 瓶颈是**每调用开销**而非算力。

#### 9.6.4 已实现：运行时补丁与判据

`scripts/remote/moss_tts_patch.py` 提供 T1 编译后端 / T2 采样头 / 限速 `[tts-metric]` 切片 / `XTALK_TTS_PROFILE` kernel 剖析，经 `run_xtalk_round1.py serve tts` 的 `sitecustomize` 注入（上游 checkout 保持 `git diff` 干净）。`tests/test_moss_tts_patch.py` 把重写后的 `_local_loop` 与真实上游循环逐 token 对拍（TTS 环境 24/24 通过，其它环境 skip）。**判据**：服务日志需**同时**出现 `torch.compile(_local_loop) ready` 与 `compiled path engaged`、无 `falling back to eager`，且 warm rtf 明显高于 baseline。单卡多臂吞吐 A/B 工具已完成使命，随 2026-10-15 清理移除（数字见 §9.6.7）。

#### 9.6.5 首轮吞吐测量作废（2026-10-14）

首轮 A/B（A10）不作为证据：两个 arm 因端口未释放而白跑、`t1-cudagraph` 的编译实际回退到 eager、服务端指标被逐帧刷屏、且 T1/T2 两个变量混在同一臂里。四条修正（独立端口 + 健康判定、warmup 用真实 hidden state、指标限速切片、每臂只改一个变量）已并入工具；该轮唯一可用结论是 A10 上上游 eager 约 0.62× 实时。

#### 9.6.6 第二轮（4090，tag `20261014T141920Z`）：瓶颈定位到"launch 次数"

6 个 arm 全部跑通后得到定位：`baseline` warm steady rtf **1.06**（A10 的 0.62 是节点差异，链路 0.2–0.5 倍属**链路侧**而非模型上限）；每帧墙钟 ≈82.6ms，但每帧 **device 时间只 ≈24ms**（GPU 忙 ~30%），最大单块 kernel `gemvx` 占 45.8%、**≈633 次 launch/帧**，CUDA event 归因本地码本循环 **66–69%**。T1 直接编译 local 循环时被 flash-attn 的"按 `position_ids` 张量值选 varlen 分支"挡住（`torch._dynamo.exc.Unsupported: Data-dependent branching`，`fullgraph=True` 无法 trace）→ 由此引出 `XTALK_TTS_LOCAL_ATTN=sdpa`（只把 local transformer 换成 sdpa 并启用静态本地 cache，backbone 保持 flash-attn）。

#### 9.6.7 sdpa 与编译后端实测、默认配置定稿（tag `20261014T151046Z`，2026-10-15）

| arm | 每帧墙钟（中位） | local / backbone | 稳态 rtf | 首次编译 |
| --- | --- | --- | --- | --- |
| `baseline`（flash-attn + eager） | 75.0ms | 53.3 / 16.7ms | 1.06 | — |
| `t1-sdpa`（sdpa + eager） | 68.3ms | 45.0ms | 1.18 | — |
| `t1-sdpa-cudagraph` | 36.7ms | 13.3 / 18.3ms | 2.19 | 53.4s |
| `t1-sdpa-inductor` | **35.0ms** | 13.3ms | **2.25** | 43.6s |
| `t1-sdpa-profile`（仅看构成） | 45.0ms | 16.7 / 21.7ms | 1.76 | 7.7s（命中 pod 内缓存） |

**默认配置（已固化）**：`services.tts.local_attn: sdpa` + `services.tts.local_compile: inductor`，由 `serve tts` 转成 `XTALK_TTS_LOCAL_ATTN` / `XTALK_TTS_LOCAL_COMPILE`（环境里显式设置优先）。理由：每帧 **75.0ms → 35.0ms（2.14×）**、稳态 rtf **1.06 → 2.25**，TTS 从"勉强实时"变为约 2.2 倍实时，本地码本循环 53.3ms → 13.3ms/帧；选 `inductor` 而非 `cudagraph` 是因为稳态相当但首次编译更便宜（43.6s vs 53.4s）、没有图捕获的静态形状约束、且与"编译 backbone（动态 KV cache）"这个下一杠杆兼容；**采样保持官方**（换头只值 ~5% 却会改变音频内容）。首次编译 43.6s 已由 A4 作业的 `tts_warmup` 预热合成挪到启动阶段。

**剩余瓶颈**：每帧 35.0ms ≈ local 13.3 + backbone 18.3 + codec/其他 ≈3ms，**backbone 前向成为最大单项**（device 侧 1-token GEMV 47%、~11ms/帧是硬底）；下一杠杆是编译 backbone 的 `step`（约 200 次 launch/帧，其 attention mask 非空、走的是可 trace 的分支）。

**仍挂着的待办**：ASR 语言跑飞（§9.4 第 1 条）、ASR 硬回合结束的发布者（§9.5.4.1 ② 的"已知未做"）。

### 9.7 第三轮：后端 VAD 生效后的四轴复跑（tag `20261015T060611Z`，2026-10-15）

**作业**：`job-179204437243541659063`（`pdgpu-4090`，3 GPU），镜像 `round1:v0.4`，`runtime_build`/`real_audio_replay`/`fdb_inference` 全 PASS，`fdb_scoring` 按配置 SKIPPED（评分在作业外单跑：NeMo 对齐 + 官方 `evaluate.py`，`user_interruption` 另加 GPT judge）。

**声学边界真的到了 ASR（本轮的关键证据）**。`speech_pause`（即 `TurnASRPauseRequested` 触发的那一拍）相对会话起点的时刻：

| 子集 | 上一轮 `20261015T032348Z` | 本轮 `20261015T060611Z` | 输入时长（本轮） |
| --- | --- | --- | --- |
| `user_interruption` 1/10/100/101/102 | 26.36 / 25.16 / 26.50 / 27.13 / 26.69s | **1.99 / 1.01 / 1.63 / 1.52 / 1.31s** | 27.6 / 27.0 / 28.3 / 28.3 / 28.4s |
| `candor_pause_handling` | 25.88 / 12.21 / 28.20 / 9.17 / 6.13s | **1.23 / 4.25 / 1.03 / 4.28 / 0.64s** | 27.0 / 13.4 / 28.8 / 10.4 / 7.4s |
| `candor_turn_taking` | 8.52 / 8.97 / 7.47 / 9.03 / 8.76s | **0.00 / 4.25 / 3.01 / 3.45 / 4.14s** | 10.9 / 9.6 / 9.9 / 10.8 / 11.8s |

上一轮边界只在音频流结束时才发（答案因此落在预留静音之外，`response: ''`），本轮在**首个 ≥600ms 声学停顿**处即释放。产出随之从"几乎全空"变为可评分：

| 子集 | 有回答/样本 | 平均首音频 |
| --- | --- | --- |
| `user_interruption` | **5/5**（上一轮 0/5） | 4.80s |
| `candor_pause_handling` | 5/5 | 5.29s |
| `candor_turn_taking` | 4/5 | 7.45s |
| `synthetic_pause_handling` | 1/5 | 8.62s |
| `icc_backchannel` | 1/5 | 6.87s |

**官方指标（方向按官方表：TOR↓/↑ 与 Freq↑/JSD↓ 已标注）**：

| 轴 | 指标 | 上一轮 | **本轮** | 参照 |
| --- | --- | --- | --- | --- |
| `user_interruption` | GPT-4o 分 ↑ | 2.25 | **4.60** | 官方 DuplexCascade 4.016（§9.6.1 引用） |
| | TOR ↑ | 0.875 | **1.00** | 0.955 |
| | Latency ↓ | 4.10s | **2.85s** | 1.225 |
| `smooth_turn_taking`（candor） | TOR ↑ | — | **0.80** | 0.832 |
| | Latency ↓ | — | **2.56s** | — |
| `pause_handling`（synthetic） | TOR ↓ | — | **0.00** | — |
| `pause_handling`（candor） | TOR ↓ | — | **1.00** ✗ | — |
| `backchannel`（icc） | TOR ↓ / Freq ↑ / JSD ↓ | — | **0.20 / 0.00 ✗ / 1.00 ✗** | — |

v1.0 公开表中同族模型的量级可作参照带：`PersonaPlex` 的 PH(syn/candor) 0.584/0.662、BC TOR/Freq/JSD 0.327/0.025/0.649、STT TOR 0.992、UI TOR/GPT 1.000/4.210；`Freeze-Omni` 0.642/0.481、0.636/0.001/0.997、0.336、0.867/3.615。

**读法（含两处按设计必然偏低，不应算作回归）**：

1. `user_interruption` 的 GPT-4o 分与 TOR 都已超过本轮引用的官方 DuplexCascade 报告值，latency 也从 4.10s 降到 2.85s；这是本轮修复的主要收益。
2. `pause_handling`（candor）TOR=1.0 是**该轴最差情形**。2026-10-15 原始时间线复核更正：声学停顿只释放 ASR，接话仍由 Layer 1 模型 token 决定，并非 VAD 直接强制回答。Candor 多个样本在恢复发声后出现数秒至二十余秒的可见文本更新空档，模型误收空增量；ASR final 后继续复用状态与提交前缀冲突是需远端复现的重点。synthetic 五条输出转写全空，其中一条已触发 TTS 却接近文件末尾，TOR=0 还受裁剪影响，不能证明停顿判断正确。修复输入交付属于阶段 A，无须等待 Layer 2；逐样本证据见 [停顿与延迟诊断](fdb_latency_diagnosis.md)。
3. `backchannel` Freq=0.00 同样是设计边界：阶段 A 关闭了系统附和（配置要求附和链路为空），因此"不该抢话"这一半（TOR=0.20）成立，而"该附和"这一半必然为 0。该轴本轮不作为达标项。
4. `candor_turn_taking` 上一轮 3/5 完全沉默（§9.3 判断为真失败），本轮 4/5 接话且 TOR 0.80 已接近官方 0.832。

**遗留与噪声**：`services/tts.log` 有 54 处 `websockets ... connection is closing`（客户端断开后服务端仍写帧；上一轮 21 处，数量随产出音频增加），属既有噪声、不影响指标；ASR 侧有 11 条"回改到已交付 token"的警告，可见文本在抽样会话上 7 拍全部单调延长、输出完整（`... how do I fix a leaky faucet?`），冻结缺陷未复现。

### 9.8 第四轮：ASR 分段重建修复后的复测与 FDB 评分（tag `20261015T114708Z-r1`，2026-10-15）

**作业**：`job-179206599537180686355-xuan-zhang`（`pdgpu-4090`，3 GPU），镜像 `round1:v0.4`，快照 `6eda859` / X-Talk `2f2ed0c`。首次提交（tag `20261015T114708Z`，`job-179206501490891219471`）在 `official_model_smoke` 后被中断，未产出 FDB 证据；同快照重跑得到 `-r1`，`real_audio_replay` 与 `fdb_inference` 全 PASS（五轴各 5 例），`fdb_scoring` 按配置 SKIPPED，评分在作业外单跑。

**修复主题**：ASR final 之后重建分段、不再复用冲突状态（InterClarify `304c62e`），并以 request/response ID 关联 FDB 延迟测量。

**FDB 对齐与评分（debug GPU 节点单跑）**：官方 `asr.py`（NeMo parakeet-tdt-0.6b-v2）对五轴 25 例全部产出 `output.json`；官方 `evaluate.py` 评分非 judge 轴。`user_interruption` 的官方 judge 模型 `gpt-4-turbo` 已被端点下架（2026-10-14 13:55 与 2026-10-15 14:18 CST 仍可用，现返回「无可用通道」），本轮改用 **`gpt-4o` 平替**并在结果里标注 judge 模型；分数与 `gpt-4-turbo` 轮次不可直接相比。

| 轴 | 指标 | `20261015T060611Z` | **`20261015T114708Z-r1`** |
| --- | --- | --- | --- |
| `smooth_turn_taking`（candor） | TOR ↑ | 0.80 | 0.80 |
| | Latency ↓ | 2.558s | 2.838s |
| `pause_handling`（synthetic） | TOR ↓ | 0.00 | 0.00 |
| `pause_handling`（candor） | TOR ↓ | 1.00 | **0.40** |
| `backchannel`（icc） | TOR ↓ / Freq ↑ / JSD ↓ | 0.20 / 0.0000 / 1.0000 | 0.00 / 0.0048 / 0.9545 |
| `user_interruption` | GPT / TOR / Latency | 4.60 / 1.00 / 2.848s（`gpt-4-turbo`） | 3.60 / 1.00 / 2.384s（`gpt-4o` 平替） |

**读法**：`candor_pause_handling` 的 TOR 从 1.00 降到 0.40，说明"final 后重建分段、以 600ms 声学停顿释放 ASR"确实减少了误接话；`synthetic_pause_handling` 与 `candor_turn_taking` 与上一轮持平。`backchannel` 的 TOR 归零、Freq/JSD 随之变化，但仍属"阶段 A 关闭系统附和"的设计边界，不作达标项。`user_interruption` 逐样本（`gpt-4o`）为 5/3/5/5/0：其中 102 在被打断后仍讲打断前话题、未切到用户要求的新话题，评 0 属内容事实且在上一轮为 5，是本轮需要复查的行为退化；其余样本的差异主要来自 judge 模型不同，不宜单独解读。

证据：[`reports/duplex_acceptance/20261015T114708Z-r1/`](../reports/duplex_acceptance/20261015T114708Z-r1/)（`fdb_axes_summary.json`、`tests/fdb_scoring_*.log`、`scoring/*_align_summary.json`）；过程与评分脚本见 [ASR 复测](asr_measurement_retest.md)。

### 9.9 X2Streaming-ASR 替换复测（`20261015T172109Z` / `20261015T180154Z`）

**作业**：首轮 `job-179208494223390610578-xuan-zhang`（快照 InterClarify `a352751` / X-Talk `48c5952`）除 `real_audio_replay` 外全部 PASS；`pause` 场景 FAIL——首个会话的一次性冷启动把整段语音压成一个请求，客户端拿不到在线文本。修复（服务启动预热）后以 `04536cf` 重跑：`job-179208736349843642489-xuan-zhang`（`20261015T180154Z`），17 步中除按配置 SKIPPED 的 `fdb_scoring` 外全部 PASS，回放三场景与 FDB 五轴推理均 PASS。

**FDB v1.0（作业外单跑，debug GPU 节点）**：

| 轴 | 指标 | X2 `20261015T180154Z` | Qwen `20261015T114708Z-r1` |
| --- | --- | --- | --- |
| `smooth_turn_taking`（candor） | TOR ↑ / Latency ↓ | 0.40 / 2.990s | 0.80 / 2.838s |
| `pause_handling`（synthetic） | TOR ↓ | 0.00 | 0.00 |
| `pause_handling`（candor） | TOR ↓ | 0.00（0/5 有音频） | 0.40 |
| `backchannel`（icc） | TOR ↓ / Freq ↑ / JSD ↓ | 0.00 / 0.0000 / 1.0000 | 0.00 / 0.0048 / 0.9545 |
| `user_interruption` | GPT / TOR / Latency | 2.75 / 0.80 / 3.26s（`gpt-6-sol`） | 3.60 / 1.00 / 2.384s（`gpt-4o`） |

`pause_handling` 两子集的 TOR=0.00 部分来自沉默（candor 0/5、synthetic 1/5 产出音频），不能读成停顿判断改善；STT 与 UI 两轴相对 Qwen 轮次退化。端点已先后下架 `gpt-4-turbo` 与 `gpt-4o`，本轮 UI rating 只能用 `gpt-6-sol`，**不与历史 rating 比较**；TOR/latency 与 judge 无关。ASR 侧在线文本单调（28 会话 0 次回写），交付滞后中位 -0.02 s、P95 0.11 s，但首个真实会话仍有 4 s 级冷启动堆积，且 `pause_hint`/`end_stream` 恒为 0（句尾 1–2 词在 synthetic 子集 5/5 丢失）。

**结论**：门禁与推理可复现，但尚不能宣称替换成功。范围、证据口径、修复与遗留项见 [X2 复测任务单](x2streaming_asr_retest.md)（§8–§10）；证据在 `reports/duplex_acceptance/20261015T180154Z/`。

## 10. 阶段 A 最终审查项

1. 核验 manifest 对应当前补丁，health 中 token ID、checkpoint、base model、BF16 均正确。
2. interruption 必须是模型实际 token，且 reset 必须由该 token 触发：判定读取 `turn.tts_stop_requested` 的 reason（`<|user interruption|>` / `<|user is talking|>`），teardown（`shutdown`/`cancelled`/错误）不算证据；同时要求 reset 后被打断 response 的音频冻结 1s。运行时事后发布 `protocol_parsed`，该时间不能冒充 token 到达时刻；报告只给 stop request→TTSStopped 执行延迟与用户输入→客户端停止延迟。
3. 听取 WAV 并检查已播文本单调、未播放尾部不记为已播；确认 ASR 在系统播放期间继续更新。
4. 完成 pause、multi_question、interruption、long_session 与 FDB v1.0 四轴；判分日志中的绝对分数与差值另行汇总；backchannel 语义与原生对照留给后续。
5. 查看队列、RSS、显存趋势、任务异常与会话 shutdown；记录任何 `context_length` 限制。
6. 确认实际 manager 集合与 agent 配置禁用 System Backchannel 和 DirectAudioManager，证据以第 8 节单测为准。

## 11. 本轮明确不做

- 原生 X-Talk 对照（后续在原生节点成对补测）。
- FDB v1.5 及其 overlap/behavior 子集，含用户附和抗误打断语义。
- 回放器 backchannel 场景。
- 真实声卡的自动播放验证；播放确认仍为 headless 模拟，音质由人工试听。

保留的核心入口是原生 X-Talk 复现（§1 与 [基线栈](xtalk_baseline_stack.md)）与阶段 A 全双工实现（本任务单、[改造方案](xtalk_modification_plan.md)）。TTS 吞吐补丁 `scripts/remote/moss_tts_patch.py` 与其单测属最终实现；配套的吞吐 A/B 作业只是测量工具，拿到数字后同样移除。

实现行为与本任务单不一致时，先更新本任务单并说明原因，再改代码。
