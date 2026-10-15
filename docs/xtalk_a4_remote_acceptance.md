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

### 9.1 上一轮结果（2026-10-13，旧 tag）

作业 `job-179187528229476527799-xuan-zhang`（节点 `d6-hpc-gpu-052`），`failures=0`：

| 步骤 | 状态 |
| --- | --- |
| source_manifest / gpu_allocation / assets / environment / runtime_config | PASS |
| a1_regression / a2_a3_regression / a4_driver_regression | PASS |
| duplex_model_service / asr_service / tts_service | PASS |
| official_model_smoke | PASS |
| real_audio_replay（normal / interruption / pause / multi_question / long_session） | 5/5 PASS |
| fdb_inference（四轴 / 5 样本） | PASS |
| fdb_scoring | 作业内 SKIPPED（`DUPLEX_A4_FDB_SCORING=0`），故 `a4_summary.json` 为 `INCOMPLETE`；实际评分由独立入口补跑，见 §9.2 |

关键证据：

- interruption 场景：`interruption_stop_response_ids` 含被打断 response，`teardown_stop_response_ids` 仅含会话收尾的第二个 response，`interrupted_audio_frozen=true`（reset 后 1s 内音频字节增量为 0），`stop_request→tts.stopped` 约 0.4ms，协议错误与旁路均为空。
- 长会话 30 轮：11 个 response、84 micro-turn、7 次由 `<|user is talking|>`/打断触发的 reset、1 次收尾停止、0 协议错误。
- 模型服务共 883 次请求：prompt_tokens 最大 1403（p95 989），generated_tokens 最大 23，单次最长 5.63s，峰值显存 16.5 GiB，`out of memory` 与 `model_service_error` 计数为 0。与此前 633 micro-turn / 约 1 万 token prompt 的 OOM 场景相比，prompt 与显存都不再失控。
- FDB `user_interruption` 5 样本诊断：只有样本 102 出现 `<|user interruption|>` 并触发 reset（2 个 response）；样本 1/10/100/101 在打断轮到模型时只吐 `<|user backchannel|>`（既无新的 `<|user is talking|>` 也无 `interruption`），按官方语义不会 reset，只有收尾停止。语义分数与低分归因见 §9.2。

因此本轮结论：驱动、运行时、服务与 FDB 推理全线 PASS；`a4_summary.json` 因作业内未评分保持 `INCOMPLETE`，但 FDB 语义评分已由独立入口补跑（§9.2）。

### 9.2 独立评分结果：`user_interruption`（2026-10-13）

**上游参照**：上游仓库自带 Full-Duplex-Bench 结果表，已归档为 `reports/duplex_acceptance/reference/upstream_full_duplex_bench_table.png`（原图在 `/hpc_stor03/sjtu_home/xuan.zhang/DuplexCascade/assets/full-duplex-bench.png`）。DuplexCascade 在同一 `synthetic` 子集上的 User Interruption：TOR 0.955、GPT-4o 4.016、latency 1.225；其余三轴为 Pause Handling 0.058/0.222、Backchannel 0.218/0.009/0.949、Smooth Turn Taking 0.832/1.724。

用 §7.1 的入口对本轮 5 个 `user_interruption` 样本跑官方对齐 + 官方默认 `gpt-4-turbo` judge：

```
conda run --no-capture-output -n paratalker-dev python scripts/remote/run_fdb_llm_judge.py \
  --root-dir <run>/fdb/user_interruption/synthetic_user_interruption \
  --out <run>/fdb_llm_judge --task user_interruption --gpus 0
```

`align_rc=0`、`judge_rc=0`，`llm_judge_summary.json`：`average_rating=0.6`、`average_take_turn=1.0`、`average_latency=1.536`。该轮评分日志与逐样本 rating 随旧 tag 证据目录一并移除；同一口径在 §9.6.1 的复检里重跑，数字记录在该小节（按 `reports/duplex_acceptance` 的约定，原始目录只保留最新一轮，见该目录 README）。

| 样本 | rating | 打断结束 | 首词延迟 | 被判分的文本（打断后裁剪段） | 运行时事实 |
| --- | --- | --- | --- | --- | --- |
| 1 | 0 | 12.568 | 0.24s | `Start by creating a budget ... cut back to cut unnecessary expenses` | 无 interruption，旧答案继续 |
| 10 | 1 | 11.971 | 0.48s | `maintaining both your mental and physical health health. Here are several strategies ... alleviate stress` | 无 interruption，旧答案继续 |
| 100 | 2 | 13.251 | 0.64s | `Here it would be helpful if if you could spec specify.` | 无 interruption，旧"请补充信息"继续 |
| 101 | 0 | 13.272 | 3.12s | `The best time to play play can very greatly depending on the material.` | 无 interruption，旧答案继续 |
| 102 | 0 | 13.421 | 3.20s | `Absolutely. Here are some additional additional trap dapple tips.` | 有 interruption 并 reset，但只留 9 个词且转写崩坏 |

**口径**：官方 `asr.py --task user_interruption` 按 `interrupt.json` 的 `timestamp[1]` 硬裁 `output.wav` 只转写裁剪段（词级时间戳 + offset）；`eval_user_interruption.py` 用裁剪段算 TOR 与 latency，**只有 TOR=1 才**把裁剪段文本喂 judge 评"与打断轮的相关性"。因此 TOR 恒为 1.0 并不表示系统让出了话轮——旧答案的音频还在播，裁剪段必然有语音。

**主因（协议层，已核实）**：被评测文本就是"打断前那句话的尾巴"，因为运行时没有 reset。原因是模型在这 5 个样本里只吐了 4 次 `<|user interruption|>`（全轮次 25 个会话合计也只有 4 次），4/5 样本改吐 `<|user backchannel|>`（`timeline.raw_outputs`，`protocol_errors` 为空；`interruption_events` 为空、唯一一次停止记在 `teardown_stop_response_ids`）。按官方语义，`<|user backchannel|>` 只 flush 不 reset，所以旧答案继续，评分段自然与新问题无关。样本 102 证明"收到 interruption → reset"链路是通的。

**归因（含实测）**：标记由上游权重自己生成，我们的 runtime 不注入也不压制；`build_prompt_ids` 的扁平 ChatML、`<|no voice|>` 静音标记、assistant 存 token id、0.6s tick（= 官方 `--overlap-window-s` 默认值）与 `do_sample=False` 贪心都与官方同构，所以不是结构性偏离。而"打断句被切成碎片、首片被判附和、模型沿用自己上一拍的标记"**是官方设计的固有性质**：官方 `server.py` 同样每 0.6s 一拍、把新增词作为一条 user 拍喂给模型、由模型 in-band 贪心生成标记，`<|user backchannel|>` 同样只 flush 不 reset（只有 `talking`/`interruption` 会 reset）。全轮次的标记分布也支持这点：`talking` 324 次、`finish talking` 24 次、`backchannel` 17 次、`interruption` 仅 4 次；样本 102 在用户沉默的 12 个空拍里仍连吐 18 次 `talking`。

文本形态这条线已用一次性标记探针（纯文本重放；脚本与产物已在 2026-10-14 清理中移除）实测判定：`raw` 变体复现了生产录制（10/100/102 逐标记一致，**含 10/100 的失败与 102 的成功**），说明探针可信；`strip` / `strip_lower` / `burst` 确实能确定性地翻转打断判定（重复实验证明同输入下解码稳定，非噪声），但**没有任何变体构成修复**——三种变体各只救一个样本且互相抵消（`burst` 弄丢 102 本可用的 interruption，`strip_lower` 让 100 退化成 19 连 `<|user is thinking|>`）；打断前的 `talking → finish talking` 在所有变体里都稳定，唯一致命的就是打断分类本身。

**结论（2026-10-13 修正）**：本轴状态机对齐正确、文本归一化不构成修复，但**不能把低分归因于上游能力**。上游仓库自带的 Full-Duplex-Bench 结果表（`DuplexCascade/assets/full-duplex-bench.png`）显示同一 `synthetic` 子集上 DuplexCascade 的 User Interruption 为 **TOR 0.955 / GPT-4o 4.016 / latency 1.225**，而我们实测 1.0 / 0.6 / 1.536——模型在原版链路上能做出"让出话轮并回答新问题"的行为。因此差异来自我们这条输入链路，而按排除法**唯一未验证与原版一致的环节就是模型唯一的输入：ASR 文本流**（我们用 Qwen3-ASR-1.7B 的 0.6s 累积前缀＋标点，上游用 Kyutai `delayed-streams-modeling` 的逐词流）。探针只测了"对我们自己的 ASR 文本做变换"，结构上无法发现这一点，属已知方法盲区。

待验证路径（按成本排序）：① `truth` 变体——用 FDB `interrupt.json` 的 `context`/`interrupt` 原句按时间戳逐词注入替代我们的 ASR 流；② `kyutai` 变体——用官方 STT 对同一段音频取词流再重放；③ 全量 FDB v1.0 跑完后与上游表逐轴对齐（Pause Handling 0.058/0.222、Backchannel 0.218/0.009/0.949、Smooth Turn Taking 0.832/1.724），若仅此轴显著偏低则病灶锁定在该路径。比较时须同时记录三处口径差异：judge 模型（上游 GPT-4o，我们官方默认 `gpt-4-turbo`）、上游图未标注 FDB 版本（我们为 `fdb/v1_0`）、上游 TOR 为 0.955 而非 1.0。

附带观察：`icc_backchannel/11` 的 ASR 整段偏成西班牙语、模型回了 `¡`，说明这条 ASR 文本流本身可以严重偏轨。

**机制定位（同日补）**：把探针 15 个"样本×变体"按"打断到达前模型**是否已经开口**"分组后，规律很干净——**打断前已生成答案文本（72–103 词）→ `backchannel`（10/11）**；**尚未开口（0 词）→ `talking`/`interruption`（3/3，其中 `102 raw` 走到 `interruption` ✓）**。即主导线索是**模型自身的说话状态**（"我在讲话时对方出声 = 附和"），而非用户文本的内容。样本 1/10/100/101 都在约 3s 就答完了上下文问题（`first_audio_seconds` 2.6–3.3s），而 FDB 的合成打断固定在 9.2–9.8s，必然落进"我正在说话"的窗口 → 该轴几乎结构性必挂；唯一成功的 102 是唯一"还没开口"的样本。详见 探针记录 §6（已移除）。这也让"待验证路径"收敛为一条：**当模型已经开口时，什么条件能让它改判为夺轮**（官方链路能拿 4.016，说明存在我们尚未复刻的条件；官方 STT 的逐词流形态仍是最可疑者）。**补充**："ASR 比用户输入慢"已被量测排除——更新间隔中位数 0.61s（每拍一条）、末条文本距语音实际结束 −0.53~+0.95s、逐词延迟 0~0.6s 且不累积，即延迟就是"0.6s 分块+推理"的地板（详见 探针记录 §6（已移除））。

### 9.3 全量 FDB v1.0 运行的前置要求

全量跑（四轴 + 全部子集）时至少满足：

1. **保留逐拍证据**：`fdb_driver/*/timelines/` 或等价记录必须落盘，并在其中记录每拍的 micro-turn 文本（`delta_text`/`revision_kind`）与模型 raw output。上一轮为省空间删除 timelines，导致无法把协议 token 精确对齐到拍，只能靠 `services/duplex_model.log` 的 `prompt_tokens` 增量反推。
2. **统计协议 token**：汇总各轴 `<|no voice|>`/`talking`/`finish talking`/`interruption`/`backchannel` 的出现次数与位置，作为"模型标记是否可信"的量化证据。
3. **记录节奏指标**：复位后到首音频的延迟、已播文本的最大停顿（本轮 101 在裁剪边界处停了 3.18s，直接污染 latency）。
4. **消融实验（已完成）**：见 §9.2 的探针结论（探针脚本与产物已在 2026-10-14 清理中移除）。`raw`/`strip`/`strip_lower`/`burst` 都能确定性翻转打断判定，但没有一个变体是修复（各救一个样本且互相抵消），故不做文本归一化改动；标点/大小写这条线作废。
5. 复听让出话轮样本的 `output.wav`（本轮 102 的 `travel tips` 被官方 parakeet 转成 `trap dapple tips`）。
6. ~~补足输入结束后的录制/续播窗口~~：**2026-10-15 撤销**，理由见 §9.3 第 6 条（官方 `SynchronizedRecorder` 同样把 `output.wav` 写成输入时长，延长录制没有意义）。三个非打断轴的正确修法是在输入内尽早释放用户文本（§9.5.4.2）。

### 9.4 其它三轴的作答统计与输入侧缺陷（2026-10-13，旧 tag）

复核本轮 25 个样本的 `a4_report.json`（`events` 的 `update_asr` 文本、`timeline.protocol_tokens`、`response`、`tts_audio_bytes`）后发现两条与"标记判定"无关、且纯文本探针结构上测不到的输入侧事实。

**作答统计**（官方方向与上游数值见 [§9.2](#92-独立评分结果user_interruption2026-10-13)）：25 个样本里 **6 个整段没有产出任何 TTS 音频**、**13 个作答不足 5 词**；除 `user_interruption` 外，`<|user is talking|>` 占各轴微拍的 83–97%。

| 子集 | 官方期望 | 无音频 | 作答 <5 词 | 平均作答 | `talking` 占比 |
| --- | --- | --- | --- | --- | --- |
| `icc_backchannel` | TOR↓ / Freq↑ | 1/5 | 5/5 | 0.8 词 | 91% |
| `candor_pause_handling` | TOR↓ | 1/5 | 2/5 | 16.2 词 | 89% |
| `synthetic_pause_handling` | TOR↓ | 1/5 | 3/5 | 4.4 词 | 83% |
| `candor_turn_taking` | **TOR↑（上游 0.832）** | 3/5 | 3/5 | 3.8 词 | 97% |
| `synthetic_user_interruption` | **TOR↑（上游 0.955）** | 0/5 | 0/5 | 23.2 词 | 59% |

**口径修正（同日）**：`output.wav` 与 `input.wav` 时长在 **25/25** 个样本上完全相等（tail = 0）。原因是 `scripts/remote/duplex_a4_replay.py` 的 `_run_fdb` 在送完音频后只 `sleep(0.5)` 就收尾，而官方 `model_inference` 脚本送完音频会再等一段（`gemini/inference_gemini25_native.py` 的 `timeout=5.0`，`sonic/inference.py` 亦有 `listener_task` 超时）。同时，三个非打断轴的**用户最后一个词都落在文件结尾前 0.02–0.15s**（由 `transcription.json` 的末词时间戳算出）：用户话一说完录音就断，输入之后产生的回答必然录不到。因此上表"无音频/作答很短"在这些子集上**不能当作模型没作答的证据**；`synthetic_user_interruption` 是唯一在数据里自带 15.00s 尾静音、因而能完整录到回答的轴——这正是它可被 judge 打分的前提。

**2026-10-15 复核官方代码后的修正**：官方推理脚本 `SynchronizedRecorder(out_sr, target_sec=输入时长, outfile)` 也是按输入时长写 `output.wav`，所以"输出 == 输入时长"是**官方口径**而非我们独有的取舍（此前把等长归因于"只 `sleep(0.5)`"只对了一半：等长来自裁剪，而裁剪本身与官方一致）。由此"补录制窗口"的方向应当放弃：非打断三轴要拿分，模型必须在输入文件自身的时间轴内说话（在其内部停顿处接话），这也正是该三轴的设计意图。

**不受该口径缺陷影响的两条**：

1. **`candor_turn_taking` 的 3/5 沉默是真失败**：`turn_taking.json` 的 `[TURN-TAKING]` 标记在文件中部（5.63 / 4.23 / 4.83 / 5.79 / 6.52s，而文件长 10.90 / 9.60 / 9.91 / 10.79 / 11.80s），让轮之后仍有余量——1 / 101 / 102 在各自约 5s 余量内零输出，10 / 100 则分别在让轮后 **0.80s / 1.39s** 作答。该轴官方要求 TOR↑（上游 0.832），故这 3 个样本是与 `user_interruption` 同向的真实失败，是目前唯一可确认的"第二处异常"。
2. **"用户说话期间的行为"证据依然有效**：Pause Handling 的 TOR（是否在停顿处抢话）与 Backchannel 的 TOR/Freq 都只看文件内音频，例如 `candor_pause_handling/1` 在 3.22s 就抢答——是该轴要惩罚的提前接管。这三轴可以用本轮产物直接跑官方评分，只需在文档里注明录制窗口。而 Pause Handling / Backchannel 的 TOR 越低越好，其"少言"在方向上不构成异常。

**输入侧缺陷**：

1. **ASR 语言会跑飞**：`icc_backchannel/1` 的 `update_asr` 全程是德语（`ja also es ist wie ich war sitzend ...`），`/11` 全程是西班牙语（`yo no te dije que ...`）；而这两份 `input.wav` 按 FDB `transcription.json` 都是英语。原因在 `scripts/remote/qwen3_asr_service.py`：会话初始化只传了流式切块参数（`chunk_size_sec`/`unfixed_chunk_num`/`unfixed_token_num`），**没有传 `language`/`context`**；而 `qwen_asr` 的 `init_streaming_state(context="", language=None, ...)` 支持强制语言。属可直接修复项。
2. **ASR 更新以"改写末尾"为主**：25 个样本的相邻 `update_asr` 中，真正"严格延长上一版"的比例只有 0–27%，其余 62–100% 会重写末尾若干个词（例：`checked before.` → `checked beforehand,`；`icc_backchannel/0` 为 1 次追加 / 26 次改写）。这来自流式配置 `unfixed_token_num: 5` / `unfixed_chunk_num: 2`（末尾 5 个 token / 2 个 chunk 视为未定），于是运行时几乎每拍都会走 `REWRITE` 修复路径，而官方 Kyutai 词流是单调追加的。**2026-10-14 复核已把这条从"待评估"升级为已定位的根因**：25 个样本共 **333 次改写**，且改写会真的让模型"答一个用户没说完的版本"，见 §9.5。

**待办**：①先让声学边界真的可达（§9.5.4.2 的后端 VAD + `vad_redemption_ms`；原先设想的"输入结束后续播窗口"已按 §9.3 第 6 条撤销），再重跑四轴，用官方评分器（`pause_handling` / `smooth_turn_taking` 不需要 LLM judge，只需 `get_transcript/asr.py` + `evaluate.py`）与上游表逐轴对齐；②`user_interruption` 自带 15s 尾静音、不受该缺陷影响，可沿用 §9.2 结论无需重跑。③输入侧缺陷第 2 条（末尾改写）已按 §9.5.4 方案 B 实现，待远端复检；第 1 条（ASR 语言跑飞）仍未改，留待独立复检以避免多变量混跑。

### 9.5 prompt 与输入流的保真核查（2026-10-14）

对照 `/hpc_stor03/sjtu_home/xuan.zhang/DuplexCascade/server.py` 逐项核对我们送进官方权重的输入，结论是：**prompt 本身没有漏 BOS，真正的偏离在输入端——官方只把"已定稿的词"交给模型，而我们把 ASR 的易变尾巴也交给了模型。**

#### 9.5.1 BOS 与 prompt 展平（结论：一致，无需修改）

官方 `prepare_llm_tokens()` 取 `self.bos_id = self.tokenizer.bos_token_id`，会话开始时 `if self.bos_id is not None: history_ids.append(int(self.bos_id))`。逐项核对后**我方没有漏 BOS**：

| 项目 | 官方 `server.py` | 我方 `duplex_model_service.build_prompt_ids` | 判定 |
| --- | --- | --- | --- |
| BOS | `bos_token_id` 非空时前插 | 不插 | **一致**：checkpoint 自带 tokenizer 与 `Qwen/Qwen2-7B-Instruct` 的 `tokenizer_config.json` 均为 `"bos_token": null`，实测 `bos_token_id = None`，官方那一行是死代码 |
| user 头 / 尾巴 | `<\|im_start\|>user\n` + 文本或 `<\|no voice\|>` + `<\|im_end\|>\n` | 同 | 一致 |
| assistant 微轮 | `header_assist` + 逐个生成的 token id（含 `<\|im_end\|>` 与特殊标记） | 同 | 一致 |
| 收尾 | 追加一次 `header_assist` | 同 | 一致 |
| 生成预算 | `--max-new-tokens` 默认 **64** | `duplex_max_new_tokens: 64` | 一致 |
| 微轮时钟 | `--overlap-window-s` 默认 **0.6** | `duplex_micro_turn_seconds: 0.6` | 一致 |

实测记录：`python … transformers.AutoTokenizer.from_pretrained(<tokenizer>, use_fast=True)` → `bos_token = None`、`bos_token_id = None`、`eos_token_id = 151645`、`convert_tokens_to_ids('<|endoftext|>') = 151643`（两者相同）。核对方式：当时把重建的 prompt 逐拍与探针记录的 `prompt_tokens` 对账（该 trace 工具已在 2026-10-14 清理中移除），`user_interruption` 五样本 **223/223** 拍全部一致。

#### 9.5.2 官方输入契约：只喂"已定稿的词"

官方 `stt_receiver_task()` 只处理 `type == "Word"` 的消息并 append 进 `asr_buffer_words`，源码注释明确 `# ignore Step / EndWord / Marker for now`；`llm_tick_task` 每拍把该缓冲 `" ".join` 成 `delta_text` 后 `clear()`，只把增量拼进 `history_ids`。因此官方的输入流是：

- **单调追加**：每个词只进历史一次，历史永不被回写；
- **只见定稿**：Kyutai 的中间假设（Step 等）被直接丢弃，模型看不到任何"可能变"的尾巴。

我方 `qwen_asr` 的流式解码每 0.6s 重喂全量音频，并把上一轮解码结果的**末尾 `unfixed_token_num=5` 个 token 回滚后重解**（`chunk_id < unfixed_chunk_num=2` 时甚至不带前缀独立解码），返回的 `state.text` 就包含了这段易变尾巴。

#### 9.5.3 后果：答案会"答一个用户没说完的版本"（已复现到拍）

当时的探针产物给出五样本逐拍 trace（每拍：ASR 累积文本、是否改写、是否回写历史、当时的完整 prompt、该拍模型输出；产物已随 2026-10-14 清理移除）。`synthetic_user_interruption/1` 的决定性两拍：

| 拍 | 时钟 | ASR 可见文本 | 送给模型的 user 历史 | 模型输出 |
| --- | --- | --- | --- | --- |
| 0 | 1.227s | `How.` | `How.` | `<\|user is talking\|>` |
| 1 | 1.827s | `How can I save my life?` | `How can I save my life?`（prompt 26 tokens，与录制一致） | `<\|user finish talking\|>Saving your life involves taking care of both your physical` |
| 2 | 2.427s | `How can I save money?` | **`How can I save money?`**（同一槽位被回写）+ assistant `Saving your life …` | ` and mental health. Here are some tips to help` |

即：1.25s 的 ASR 版本（`save my life`）已经让模型开口；1.84s 的改写（`save money`）落地时，`_append_user` 把**已经发出的** user 微轮原地改成新版本，但那条基于旧版本生成的 assistant 文本既留在历史里、也已经送进 TTS，于是最终播报的答案是缝合体：`Saving your life involves taking care of both your physical and mental health Here are some tips to help you save money effectively`。

护栏式统计（当时对该轮 25 个样本的 `a4_report.json` 做词级审计，与时间戳无关、只看词；审计文件随旧 tag 移除）：

| 轴 | 改写次数 | 答案里保留了"ASR 已撤回的词"的样本 |
| --- | --- | --- |
| `icc_backchannel` | 127/5 样本 | 0/5 |
| `candor_pause_handling` + `synthetic_pause_handling` | 150/10 样本 | 1/10（`I have a check.` → `I have a checkup appointment.`，答案留下 check） |
| `candor_turn_taking` | 31/5 样本 | 0/5 |
| `synthetic_user_interruption` | 25/5 样本 | 2/5（`save my life`→`save money` 留下 life；`best time to play`→`best time to plant tomatoes` 留下 play） |

`synthetic_user_interruption` 五样本各有 4–6 次改写，每次改写都同时触发一次"回写已发出的 user 微轮"。改写本身在"答案尚未开口"时无害（模型只会在当前文本上作答），但只要落在模型已经开口之后，就会同时污染语义与后续上下文。

#### 9.5.4 修法选项与选定方案（2026-10-14 选定 B 并已实现）

| 方案 | 做法 | 代价 |
| --- | --- | --- |
| A. 收紧流式参数 | `unfixed_token_num: 0`、`unfixed_chunk_num: 0`（纯配置） | 尾巴立刻定稿、不再回滚，ASR 失去边界纠正能力，尾部 WER 上升 |
| **B. 只暴露定稿前缀（已实施）** | 关掉"前 N 个 chunk 独立解码"（`unfixed_chunk_num: 0`），并在 ASR 服务里让 `is_final=false` 只返回已定稿前缀（`state.text` 去掉末尾 K 个 token），`is_final=true` 释放完整文本 | 可见文本比 ASR 内部晚约 K 个 token（实测词级 1–6 词）；尾部由调用方的显式边界 `is_final` 释放（**不是**"停顿即释放"，见 §9.5.4.1） |
| C. 运行时兜底 | `REWRITE` 时连 assistant 一起回滚重生成 | 与"已被听到的内容不可撤销"冲突，且官方无此语义 |

单调性证明（B 为什么必须同时关掉 `unfixed_chunk_num`）：记第 n 拍的原始解码串为 `R_n`，其前缀 `P_n = truncate_K(R_{n-1})`（`unfixed_chunk_num > 0` 时前几个 chunk 的 `P_n` 为空、由音频独立解码，`R_n` 与 `R_{n-1}` 之间没有任何前缀约束）。因 `R_n = P_n + G_n` 且 `P_n` 是整 token 边界，故 `T_n := truncate_K(R_n)` 满足 `T_{n-1} = P_n ⊑ T_n`，即**逐拍单调追加**；这正是官方 `Word` 词流的性质。若保留 `unfixed_chunk_num=2`，前两拍的"定稿前缀"仍可能整体换掉，模型照样会看到改写。

#### 9.5.4.1 对比的副产物：契约实现里有两个真 bug（2026-10-15 实测，待修）

`run_asr_contract_ab_node_job.sh` 的第一轮结果（40 样本 / 729s 音频，两臂各 40）本身支持"保持 `unfixed_chunk_num: 0`"：两臂最终转写**逐词相同**（词级距离中位数 0.0）、提交延迟相同（中位 0.96s）、可见改写都是 0，raw 改写 532（window-0）vs 539（window-2）。但它同时暴露了两个更严重的问题：

1. **可见文本会被永久冻结**（`scripts/remote/qwen3_asr_service.py` 的 `advance_committed`）。它用**字符串** `proposed.startswith(visible_text)` 保证单调，而模型再解码时常把句末标点/空格改掉（例如 `'I never like.'` → `'I never like I know…'`），一旦已释放的可见文本里含这种字符，此后**任何**延长都会被 `startswith` 拒绝，可见文本就停在原地。实测：`candor_pause_handling/1` 在 t=0.72s 释放 `'I never like.'`（当时 raw 也只有这 3 个词），之后 raw 长到 127 词，可见文本**冻住 26.3s（330 拍）**；另一个样本冻在 `'Yeah.'` 9.7s。40 样本上"raw 比可见多出的词数（每样本取中位）"的中位数是 **15 词**、最大 62 词。
2. **duplex 运行时从不释放被扣住的尾巴**。`AudioConsumer.pause()/end()` 才带 `is_final_chunk=True`，而它们在 `ASRManager` 里只由 `TurnASRPauseRequested`/`TurnASREndRequested` 触发；duplex 模式下只有 `MicroTurnAssembler` 发 `TurnASRStartRequested`（`duplex_control/micro_turn.py:58`），暂停/结束请求**没有发布者**（原发布者 `turn_taking_manager`/`TurnDetectorManager` 已被 `duplex_manager_classes` 移出）。于是服务在整个会话里拿不到 `is_final=true`，扣住的尾巴永远不释放。

**含义**：之前 A4/FDB 各轮的运行时看到的是"用户在整段话里只有开头几个词、且被冻结"的文本，这也解释了实测里出现的抢话/答案缝合/低分现象；**这些 FDB 数字需要在修好之后重跑**（与 §9.6.7 的 TTS 默认配置一起重跑最经济）。

**修法**：

- ① **已实施（2026-10-15，服务侧）**：`advance_committed` 改为 **token 级**单调推进——交付单位是 token 前缀（`committed_token_ids` / `decode_token_prefix`），只扣住末尾 `unfixed_token_num` 个 token，只在候选延长已交付前缀时推进；解码器回改到已交付 token 时保持已交付文本、累计 `stalls` 并打一条 warning；**删除了"本次解码无新增文本就释放尾巴"这条规则**（句内停顿不是片段结束，正是它把 `'I never like.'` 交了出去，见上）。`SessionState` 用 `committed_ids` 取代 `last_parsed`，`asr-smoke` 同步记录 `commit_stalls`，汇总器新增「冻结」（前缀落后 raw 超过 8 个词的最长连续时长）与「提交停滞」两列。单测：`tests/test_qwen3_asr_service.py` 9 个（含 `'I never like.'` 回归用例）、`tests/test_summarize_asr_contract.py` 8 个。
- ② **已实施（2026-10-15，运行时侧）**：`duplex_control/micro_turn.py` 现在订阅声学 `VADSpeechEnd`/`VADSpeechStart`——前者发 `TurnASRPauseRequested`（保留 ASR 状态、只触发一次识别，正是官方 `TurnTakingManager` 在配置了端点检测时的做法），后者发 `TurnASRStartRequested` 恢复采集（否则音频只进 1s 预缓冲、会丢话）。触发点选 VAD 而非 micro-turn 收口：改动最小、不干扰 in-band 轮次判定，也不把一句长话切碎。单元测试：`tests/test_duplex_runtime.py` 新增 3 例（声学结束只发一次 pause、合成文本输入不发 pause、消费者未启动不发 pause），`tests/test_asr_finalization.py` 新增链路测试（`VADSpeechEnd` → `TurnASRPauseRequested` → `AudioConsumer.pause()` → ASR 客户端真的收到 `is_final=True`，并发布一个 `speech_pause=True` 的 partial）。**已知未做**：硬回合结束（`TurnASREndRequested`，会重置 ASR 状态）仍无发布者，因此 ASR 文本跨回合累积；官方 duplex 是否就该如此（其在线 STT 是一路连续流）需要专门验证，故本轮不动。

① 的效果需要用同一套对比工具复测（预期"挂起的词"降到 1–4 词、`commit_stalls`/「冻结」为 0）。

**`unfixed_chunk_num` 是否与官方对齐（2026-10-15 起测）**：官方默认是 `unfixed_chunk_num: 2`，我们配的是 `0`。由于 `advance_committed` 守卫只让可见文本单调增长，对齐官方**不会**破坏 append-only；真正的差别是解码器是否用最近 2 个 chunk 重解码（边界纠正能力）以及由此带来的提交点后移。用 [run_asr_contract_ab_node_job.sh](scripts/remote/run_asr_contract_ab_node_job.sh)（单卡、进程内驱动官方流式 API、FDB 语料按子集均衡取样）量 `window-0` 与 `window-2` 的 raw/可见改写次数、尾部释放延迟与最终转写词级距离后再定。

**已实现的改动**：

| 文件 | 改动 |
| --- | --- |
| `scripts/remote/qwen3_asr_service.py` | `--emit-committed-prefix` 的 append-only 契约：**token 级**单调推进（`committed_token_ids`/`decode_token_prefix`/`advance_committed`），只扣住末尾 `unfixed_token_num` 个 token，`is_final=true` 释放全量且不重置推进基点；回改到已交付 token 时保持已交付文本并计数（`stalls`）。2026-10-15 修掉"字符串比较导致可见文本永久冻结"与"停顿即释放"两个缺陷（§9.5.4.1） |
| `configs/xtalk_round1.yaml` | `asr_streaming.unfixed_chunk_num: 2 → 0`；新增 `emit_committed_prefix: true` |
| `scripts/remote/run_xtalk_round1.py` | `serve asr` 透传 `--emit-committed-prefix`；`asr-smoke` 支持 `--audio-dir` 与流式契约覆盖，并额外报告 `visible_text`/`visible_revisions`；输入按运行时同一路径重采样 |
| `tests/test_qwen3_asr_service.py` | 新增：改写不得缩短/替换已给出文本、隐藏窗口正好是 `unfixed_token_num`、静音必须释放尾巴、可见文本不得含语言标签、HTTP 生命周期、默认档位不变 |

**第一次实现的缺陷与修正（2026-10-14）**：首版按**原始解码串** `_raw_decoded` 末尾截断，且只在"有新增文本"时更新可见文本，导致两个问题，并在 `20261014T025649Z` 的复检里暴露（该轮产物已作废，目录随清理移除）：

| 缺陷 | 观测证据 | 修正 |
| --- | --- | --- |
| 截断点落在 `language English<asr_text>` 内部，把语言标签当用户文本交给模型 | `replay/normal` 场景全程 397 拍只有 `<|user is talking|>`、`response_ids` 为空（`normal` FAIL、`interruption` INCONCLUSIVE）；FDB 样本 `10`/`102` 的 `update_asr` 文本为 `language English` / `language` | 改为对**已解析转写** `state.text` 截断，标签不可能再进入结果 |
| 句尾 K 个 token 永久扣住（只有继续出现新词才会释放） | `synthetic_user_interruption/1` 最后一拍停在 `… what are some financial`，`goals I should set?` 再未出现；问题语音结束后 15s 静音期间可见文本停在 `How can I`（8s） | 当时新增了"本次解码没有新增文本即释放尾巴"；**该规则已于 2026-10-15 撤销**（句内停顿不是片段结束，它正是可见文本被永久冻结的根因），尾巴改由显式边界 `is_final` 释放，详见 §9.5.4.1 |

该轮 `fdb_inference` 虽为 PASS，但其 ASR 文本已被上述缺陷污染，故**不作为方案 B 的证据**，已作废重跑。

**为什么这不违背"已被听到的内容不可撤销"**：修法只改变**模型能看到的文本**，不撤回任何已经生成/播报的音频；相反，它消除的正是"先按旧文本作答、再被回写"的那类语义污染。

**远端验证**（两个一次性作业，脚本与产物已在 2026-10-14 清理中移除；判据与结论保留在 §9.6.1）：

1. 单卡 before/after ASR 对比：同一批 FDB 输入跑前后两版契约，`after` 的 `visible_revisions` 必须为 0，并比对最终转写与参考转写的词级距离。
2. 3 卡 `user_interruption` 复检：只重跑该轴 + 官方 judge，核对运行时 `update_asr` 流改写次数是否归零、rating 相对 §9.2 的 0.6 的变化。

修法**不**包含另外两处已知输入侧问题：ASR 语言跑飞（§9.4 第 1 条）与 `_run_fdb` 的录制窗口（§9.3 第 6 条），它们各自独立验证，避免把多个变量混进同一次复检。

#### 9.5.4.2 后端 VAD：让声学边界真的到达 ASR（2026-10-15）

**问题（第二轮 A4，tag `20261015T032348Z`）**：运行时进程**没有加载后端 VAD**——`VADManager` 首行即 `if self.vad is None: return`，整条声学状态机不工作。于是唯一的 `vad_speech_end` 是 input gateway 在**音频流边界**代发的那个，§9.5.4.1 ② 接好的释放链路被推迟到文件结束：`synthetic_user_interruption/101`（28.27s，语音 13.0s 结束，其后 15.27s 数字静音、RMS=0）里 `speech_pause=True` 直到 27.13s 才出现，模型 27.09s 才开口，所以该轮多数样本 `response: ''`、`tts_audio_bytes: 0`，数字不可用。

**修法（配置一处；依赖只在配方里显式声明）**：

| 位置 | 改动 | 说明 |
| --- | --- | --- |
| `configs/xtalk_duplex_runtime.json` | 新增 `vad` 槽位 `{"type": "SileroVAD", "params": {"threshold": 0.5}}` | 这是 `VADManager` 唯一的开关；模型取 `~/.cache/xtalk/models/silero_vad.onnx`（共享盘已缓存，不联网下载） |
| 同文件 `service_config` | `vad_redemption_ms: 600` | 最后一个语音帧之后积累 600ms 静音才发 `VADSpeechEnd` |
| `Dockerfile.round1` + 镜像 **v0.4** | client 环境显式装 `xtalk[example,dev,silero-vad]` 并钉 `onnxruntime==1.31.0`（离线取自 wheelhouse） | 把"运行时需要 onnxruntime"写进配方、避免它随依赖变动悄悄消失。**就本故障而言 v0.4 与 v0.3 内容等价**（见下），v0.4 只是以增量层发布（`Dockerfile.round1.overlay` + `OVERLAY=1`：几分钟/几百 MB，而从零重建要 1 小时/十几 GB） |

**为什么是 600ms 而不是 500ms**：ASR 客户端的节奏是 `chunk_ms: 600`，停顿判定不能早于"句尾那一段已经交给 ASR"的那一刻；否则 pause 的 flush 会漏掉最后一段，那段音频只能躺在 1s 预缓冲里等下一次 `VADSpeechStart`——用户不再说话就永远不被识别。600ms 与 chunk 对齐使 flush 带上句尾（代价是释放点晚 100ms）。若复测仍见句尾丢词，可上调到 700–800ms，结构不变。

**依赖核查（2026-10-15 更正：先前的归因是错的）**：最初把 tag `20261015T040437Z` 的失败归因于"client 环境没有 `onnxruntime`"。**该结论不成立**：

- 直接在 v0.3 镜像里查 `/opt/conda/envs/xtalk-round1-client` 可见 `onnxruntime 1.31.0` 早已存在，v0.4 增量层构建也打印 `Requirement already satisfied: onnxruntime==1.31.0`；
- 用**同一镜像 + 同一运行配置**在本机容器内跑，`Xtalk.from_config` 加 uvicorn 绑定端口只需 **1.9s**（onnxruntime import 0.10s、构造模型 1.89s，而 `--server-timeout` 默认 60s）；带 GPU、带作业同款线程环境变量复测同样是 1.8s。

因此后端 VAD 配置本身与这次失败无关，v0.4 也不是修复。

**这次真正暴露的是可观测性缺陷**：作业里回放与 5 个 FDB 批次都只留下父进程的超时 traceback，子进程是崩了还是卡住无从判断。修法：

- `_serve` 把启动进度写入 `$XTALK_SERVE_LOG`（`start` → `imports ok` → `app mounted` → `uvicorn returned`），失败时写完整 traceback；
- `_wait_for_server` 在端口不开时报告子进程状态（`exited with code N` 或 `still alive (stalled before binding its port)`）并附该日志尾部；回放器把日志指到 `<--out>/xtalk_serve.log`，随产物留存；
- 节点脚本新增 **`runtime_build`** 前置步骤：启动服务前用 client 环境按运行时配置真正构造一遍模型集合并要求 `models.get(VAD)` 非空，把这类问题从"超时后翻日志"变成一条明确失败。

`20261015T040437Z` 的**成因仍未确定**（本机无法复现，作业现场日志不足）；重跑时上述埋点会直接给出结论。

**测试**：`tests/test_xtalk_link_check.py` 新增两条（子进程退出码 + 子进程日志尾部进入报错；存活子进程被判定为"卡住"而非崩溃）；`xtalk/tests/test_asr_finalization.py` 新增全链用例——8 个语音帧开启片段、15 个静音帧（480ms）**不发** end（窗口被遵守），再过 5 帧越过 600ms 后 `VADSpeechEnd` → `TurnASRPauseRequested` → `AudioConsumer.pause()` → ASR 客户端真的收到 `is_final=True`。

**顺带修掉的评分阻塞**：`fdb_scoring BLOCKED` 是环境导入问题而非缺 NeMo——该镜像上 `nemo.collections.asr` 需要 `NUMBA_CUDA_USE_NVIDIA_BINDING=0` 才能导入，该变量已在节点脚本打分段 export。三卡作业内仍默认跳过评分（对齐阶段 GPU 空转会被集群按 LowGpuUsage 杀掉），评分继续用 [run_fdb_llm_judge.py](scripts/remote/run_fdb_llm_judge.md) 对已有产物树单跑。

### 9.6 复检结果与 TTS 交付瓶颈（2026-10-14）

#### 9.6.1 方案 B 复检（tag `20261014T033949Z`）

`data/runs/20261014T033949Z/`：单卡 ASR 契约 A/B + 3 卡 `user_interruption` 复跑，官方对齐与 judge 由 `run_fdb_llm_judge.py` 独立运行（作业内评分因节点 conda 看不到带 NeMo 的 `full-duplex-bench` 而 BLOCKED，改为独立脚本执行）。

| 项 | 复检前（§9.2，旧 tag） | 复检后（`20261014T033949Z`） | 上游 DuplexCascade（仓库自带表） |
| --- | --- | --- | --- |
| `average_rating` | 0.6 | **2.25** | GPT-4o 4.016 |
| `average_take_turn` | 1.0（含"旧答案音频仍在播"的假阳性） | 0.875（样本 `10` 无音频→TOR 0） | 0.955 |
| `average_latency` | 1.536（同样被旧答案音频抬高） | **4.10** | 1.225 |

- ASR 侧结论：`after` 的运行时可见改写 **0/0/0/0/0**，两模式最终转写逐词相同（当轮对比报告 `asr_stream_compare.md` 随清理移除）——append-only 契约成立且不损准确率；`user_interruption` 的作答质量因此明显回升（101 从 0→5，1 从 0→2）。
- 遗留：latency 4.10s（4 个 TOR=1 样本：4.16 / 6.24 / 5.52 / 0.48）。样本 `102` 的 0.48s 是假数据——该样本没有发生 reset，被记为"首音频"的其实是旧答案尾音。

#### 9.6.2 4–6s 延迟的四段分解（实测）

按 FDB wav 时钟（`interrupt.json timestamp[1]` → 官方对齐的 `output.json chunks[0]`），四个环节：

| 环节 | 实测 | 性质 |
| --- | --- | --- |
| 用户说完 → ASR 给出全量文本 | 0.13–0.84s | 方案 B 的设计代价：duplex runtime 无人发 `TurnASRPauseRequested`/`TurnASREndRequested`（唯一发布者 `turn_taking_manager` 被 `duplex_manager_classes` 替换），ASR 服务只能靠"下一拍解码无新增文本"释放尾巴 |
| → runtime 起新 TTS（`tts.started`） | 1.13–1.17s（四样本几乎恒定） | 0.6s 节拍 + 模型多要一拍才输出 `<|user finish talking|>` |
| → 首个 `tts.chunk_ready` | 0.96–1.12s | MOSS prefill（冷启动会话） |
| → 对齐器认出的首个词 | **1.21 / 3.23 / 3.12s** | 主因，见下 |

第四段的直接证据：样本 1 从首块到首个可识别词是 1.21s，其间只落了 1–2 个 100ms 块；对齐出的词表本身就是"一次突发一个词"（`Set [16.73]`、`playing [17.61]`、`financial [18.81]`、`goals [20.25]`…），样本 100/101 同形（首词 19.49 / 18.79）。不是对齐器或 prefill 的问题。

同期实测交付率（`tts.chunk_ready` × 100ms，1s 滑窗）：4/5 样本中位数 **200–500 ms/s**，即整条链路只有约 **0.2–0.5 倍实时**；同一时间窗内 LLM 已推入 **169 词 ≈ 67.6s 语音（4.8 倍实时）**，故瓶颈在 LLM 之后。`output.wav` 里助手说话段的 speech/span 只有 0.10–0.32（旧 run 同样 0.12–0.33，属既有问题），答案也被 27.5s 录制窗口截断，judge 转写出现 `pet get food for for your animal` 这类碎片化误识。

#### 9.6.3 机制：MOSS-TTS-Realtime 的每帧成本

- 编解码帧率 24000/1920 = **12.5 Hz**，每帧 80ms 音频；每帧 = 1 次 backbone 前向 + **16 次 local transformer 前向**（`rvq=16` 逐码本串行）+ 每码本一次采样。
- 上游只在非 flash-attention 路径编译该循环（`_should_compile_local_transformer = not _use_dynamic_local_cache`），我们的 `attn_impl=flash_attention_2` 部署是全 eager；采样默认 `do_sample=True` + top-k + **全词表 sort** 的 nucleus，每帧上百次张量算子。
- 结论：链路交付约 0.2–0.5 倍实时（§9.6.2），瓶颈在"每帧 17 次前向 + 16 次采样"的**每调用开销**而非算力；但精确到"哪一段占多少"仍需 §9.6.5 的 profile 臂给出，先前的"单帧约 205ms"是把客户端墙钟除以帧数得到的粗估。

#### 9.6.4 已实现：运行时补丁 T1/T2 与 A/B 任务

- `scripts/remote/moss_tts_patch.py`（T1 编译后端 / T2 采样头 / 限速 `[tts-metric]` 切片 / `XTALK_TTS_PROFILE` kernel 剖析），经 `run_xtalk_round1.py serve tts` 的 `sitecustomize` 注入，上游 checkout 保持 `git diff` 干净。
- `scripts/remote/run_tts_throughput_ab_node_job.sh` + `submit_tts_throughput_ab_job.sh` + `summarize_tts_throughput.py`：单卡多臂、固定 75 词负载、每臂 cold+warm（`warm-only` 跳过 cold），产出 `reports/tts_throughput/<tag>/tts_throughput.{md,json}`。第二轮用的是 6 臂（`baseline`/`t2-greedy`/`t2-topk`/`t1-inductor`/`t1-cudagraph`/`profile`，§9.6.6）；默认臂表已按瓶颈改为 5 臂（`baseline`/`t1-sdpa`/`t1-sdpa-cudagraph`/`t1-sdpa-inductor`/`t1-sdpa-profile`）。
- 正确性：`tests/test_moss_tts_patch.py` 把重写后的 `_local_loop` 与**真实上游**循环逐 token 对拍（含经 `sample_token` 派发一例），另覆盖 `_attach` 字段完整性、注意力/cache 切换、饱和门、event 记账、限速指标与 profiler 摘要（TTS 环境 24/24 通过，其它环境 skip）。

**判据**：`steady_rtf = audio_s / (wall_s - first_audio_s) > 1` 才算追上实时；`t1-*` 需服务日志**同时**出现 `torch.compile(_local_loop) ready`（图建好）、`compiled path engaged`（推理真的走了编译路径）、无 `falling back to eager`，且 warm rtf 明显高于 baseline；`t2-*` 改变音频内容，须试听后再决定。此后若吞吐达标，再用 `20261014T033949Z` 的同一流程重跑 `user_interruption` 轴，比较 latency 4.10 → ? 与 rating 2.25 → ?。

**测量节点**：A/B 可以在 `pdgpu-a10` 上跑（4090 队列常满，提交脚本用 `TTS_AB_PARTITION` 切换）。A10 比 4090 慢，**绝对值不可与 4090 直接比较**，该节点只用来判断 T1/T2 在*同一节点*上的相对倍率是否成立；全链路的全量测试仍等 4090 空出后进行。

#### 9.6.5 首轮吞吐测量作废与修正（2026-10-14）

首轮 A/B（tag `20261014T100302Z`，A10）**不作为 T1/T2 证据**，四条原因与修正：

| 现象 | 证据 | 根因 | 修正 |
| --- | --- | --- | --- |
| 两个 arm 白跑（`t2-greedy`/`t1-inductor`） | 控制台里其 `service healthy` 用时 **0s**（正常 arm 35s），随后 smoke 报 `Cannot connect to host 127.0.0.1:8004` | `stop_service` 后立刻起下一个 arm，上一 arm 的服务仍在监听；新进程 bind 失败退出，健康探针打到了旧服务 | 每个 arm 独立端口（`serve tts --port`）+ 健康判定要求"进程存活 + 日志 `[warmup] Backend loaded` + 端口连续两次应答" |
| `t1-cudagraph` 的编译从未生效 | 日志有 `torch.compile(_local_loop) ready`，紧接 `compiled warmup failed, falling back to eager: Logger not supported for non-export cases`，traceback 指向 `transformers/modeling_flash_attention_utils.py:465` 的 `logger.warning_once` | warmup 用 `torch.float32` 造 hidden state，触发 flash-attn 的 fp32 回铸告警；`fullgraph=True` 遇到 logger 调用直接失败；此外饱和门读的 `_xt_window` **从未定义** | warmup 改用该帧真实 hidden state 与采样标量；`relax_dynamo_logging()` 把 `Logger.warning_once` 等加入 `ignore_logger_methods`；饱和门改为 `min(capacity, repetition_window)`，并新增 `compiled path engaged` 作为"真的生效"的证据 |
| 服务端数字不可读 | 报告"服务端 rtf(最大)"列出现 `151231.24` | 服务每帧调用一次 `finish`，而指标按"每次调用一行"打印，被逐帧刷屏 | 指标改为限速切片（≥6 帧或 ≥1s 墙钟一行），汇总改为 `Σaudio/Σwall` 与中位数 |
| T1/T2 变量混淆 | `t1-*` 臂当时用 greedy 采样 | 一个臂同时改了"编译"和"采样头"，差值无法归因 | 每臂只改一个变量：`t1-*` 采样保持 `upstream`；新增 `profile` 臂（`torch.profiler` 逐 kernel，同时覆盖模型与 codec 解码） |

首轮唯一可用结论：A10 上上游 eager 路径稳定态合成速率 ≈ **0.62× 实时**（客户端与服务端 `[tts-metric]` 相互印证），采样换头（top-k nucleus）在同一节点无可测收益。

#### 9.6.6 第二轮（4090，tag `20261014T141920Z`）：瓶颈定位到"launch 次数"

修复后 6 个 arm 全部跑通（`baseline / t2-greedy / t2-topk / t1-inductor / t1-cudagraph / profile`），结论：

| 观测 | 数值 | 含义 |
| --- | --- | --- |
| `baseline` warm steady rtf | **1.06**（`t2-greedy` 1.13、`t2-topk` 1.07） | 4090 上上游 eager 路径**刚好实时**；A10 的 0.62 是节点差异，A4 链路 0.2–0.5 倍是**链路侧**而非模型原始上限 |
| 每帧墙钟（baseline） | ≈82.6ms（89 帧 7.12s 音频 / 7.35s 墙钟） | 12.5Hz 下每帧只该 80ms |
| 每帧 **device** 时间（`profile` 臂 kernel 表） | **≈24ms**（60 帧合计 1.437s） | GPU 只忙了 ~30%，**~58ms/帧在等 CPU 派发** |
| 最大单块 kernel | `gemvx`（1-token 矩阵-向量乘）**45.8%**、**37996 次 / 60 帧 ≈ 633 次/帧** | 逐算子 launch 主导；其中 ~450 次来自 16 个码本的本地前向 |
| CUDA event 归因（`local_s`/`backbone_s`） | 本地码本循环 **66–69%**、backbone **12–14%** | 与 kernel 计数一致：本地循环是 launch 数量的大头，T1 打的位置正确 |
| T1 两个编译 arm | 均 `compile 回退`：`torch._dynamo.exc.Unsupported: Data-dependent branching`，落在 `transformers/modeling_flash_attention_utils.py:670`（`elif is_fa_with_varlen_kwargs or is_fa_with_position_ids:`） | flash-attn 用 `position_ids` 的**张量值**选 varlen 分支；local transformer 是"1 query × 17 key、无 mask"，该分支既被走到又数据相关 → `fullgraph=True` 无法 trace |

**据此的下一步（已实现）**：新增 `XTALK_TTS_LOCAL_ATTN=sdpa` —— 只把 local transformer 换成 sdpa 并启用静态本地 cache（backbone 保持 flash-attn），使码本循环可编译；臂表改为 `baseline / t1-sdpa / t1-sdpa-cudagraph / t1-sdpa-inductor / t1-sdpa-profile`，其中 `t1-sdpa` 单独隔离"换注意力+静态 cache"这一步。判据仍是 `ready` + `engaged` + warm rtf 明显高于 baseline。若编译收益兑现（预期把 ~58ms 的 CPU 派发开销压到个位数毫秒），再考虑把同一手段用于 backbone 前向（每帧 ~200 次 launch，但其 attention mask 非空、走的是可 trace 的分支）。

#### 9.6.7 sdpa 与编译后端实测、默认配置定稿（tag `20261014T151046Z`，2026-10-15）

第三轮的两个编译臂都拿到了干净读数（`compiled path engaged` 成立，编译在冷跑内完成）：

| arm | 每帧墙钟（中位） | local / backbone | 稳态 rtf（服务端切片中位） | 首次编译 |
| --- | --- | --- | --- | --- |
| `baseline`（flash-attn + eager） | 75.0ms | 53.3 / 16.7ms | 1.06 | — |
| `t1-sdpa`（sdpa + eager） | 68.3ms | 45.0ms | 1.18 | — |
| `t1-sdpa-cudagraph` | 36.7ms | 13.3 / 18.3ms | 2.19 | 53.4s |
| `t1-sdpa-inductor` | **35.0ms** | 13.3ms | **2.25** | 43.6s |
| `t1-sdpa-profile`（带 profiler，仅看构成） | 45.0ms | 16.7 / 21.7ms | 1.76 | 7.7s（命中 pod 内编译缓存） |

**默认配置（已固化）**：`services.tts.local_attn: sdpa` + `services.tts.local_compile: inductor`，由 `serve tts` 转成 `XTALK_TTS_LOCAL_ATTN` / `XTALK_TTS_LOCAL_COMPILE` 传给服务（环境里显式设置则优先，供 A/B 扫臂）。理由：

- **收益**：每帧 75.0ms → 35.0ms（**2.14×**），稳态 rtf 1.06 → **2.25**，即 TTS 从"勉强实时"变为"约 2.2 倍实时"，为链路留出缓冲；本地码本循环从 53.3ms/帧降到 13.3ms/帧（−75%）。
- **选 `inductor` 而非 `cudagraph`**：两者稳态相当（35.0 vs 36.7ms，中位 rtf 2.25 vs 2.19），但 `mode="default"` 首次编译更便宜（43.6s vs 53.4s）、没有图捕获的内存池与静态形状约束，且**与下一个杠杆兼容**——backbone 前向带自增 KV cache，要编译它必须允许动态形状，cudagraph 做不到。
- **保留官方采样**（`XTALK_TTS_SAMPLE=upstream`）：采样换头实测只值 ~5%（1.13 / 1.07）却会改变音频内容，风险收益不划算。
- **首次编译成本**：每个服务进程 43.6s（同 pod 内第二次编译只要 7.7s，说明产物按代码/守卫缓存）。A4 作业已在 TTS 健康检查后加一步 `tts_warmup` 预热合成，把这次编译从"首个被测话轮"挪到启动阶段。

**修复的两个测量缺陷**：① backbone 计时原先挂在 inference 对象上，而服务**每回合新建 inference 对象、model 是共享的**，导致第一个回合之后 `backbone_s` 恒为 0（本轮已改为把 event 列表挂在 model 上，`t1-sdpa` 臂的 45.0ms 就是修正后的口径）；② A/B 续跑时残留的 `-cold` 目录会让 `tts-smoke` 的 `mkdir(exist_ok=False)` 失败，已在每个 phase 前清目录。

**剩余瓶颈**（同一轮的 profile 臂，device 侧 60 帧合计 1.422s ⇒ 23.7ms/帧，其中 1-token GEMV 47%）：编译码本循环后，每帧 35.0ms ≈ 本地 13.3ms + backbone 18.3ms + codec/其他 ≈3ms，**backbone 前向成为最大单项**；下一杠杆是编译 backbone 的 `step`（每帧约 200 次 launch，且它的 attention mask 非空、走的是可 trace 的分支），预期还能再压掉一部分 CPU 派发开销，但 device 侧 GEMV 的 ~11ms/帧是硬底。


**运行过程中的定位与加固**：

- **sdpa 确实让编译路径可 trace**：`t1-sdpa-cudagraph` 的服务日志出现 `inference ready … attention=sdpa` → `torch.compile(_local_loop) ready mode=reduce-overhead` → 进入 inductor 代码生成（`torch/_inductor/compile_fx.py` 警告），**不再有 `Data-dependent branching`**；随后 pod 被整容器终止（bash 与服务同时消失、submit 日志戛然而止、`vc list` 里作业直接不见），即死在**编译/图捕获的峰值内存**上（前端证据见 `run.log` 与 `metrics/*.resources.txt`）。
- **sdpa 单独的收益（已完成的两个 arm，同 tag，warm）**：每帧稳态墙钟 **75.8ms → 70.6ms**（−7%），服务端首个切片 7.20s → 6.53s、`local_s` 4.77s → 4.09s（本地占比 66% → 63%）；两轮 `baseline` 的每帧墙钟完全一致（75.8ms），说明该口径可复现。采样内容长度会变（27.36s vs 31.20s，未设种子），故只比较每帧墙钟。
- **加固（已实现）**：A/B 作业默认给服务进程设 `TORCHINDUCTOR_COMPILE_THREADS=1`（默认会按 CPU 数起并行编译 worker，是峰值内存主因）与 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`；新增 `TTS_AB_RESUME=1` 续跑（跳过已有 `-warm` 产物的 arm，端口序号不变）与每 arm 的 `metrics/<arm>.resources.txt` 资源快照（落到共享盘，pod 被杀也可读）。若在同一 32G 预算下仍被杀，则需要把单卡作业的内存预算调高或把编译粒度拆细（例如只编译单个码本步、由 Python 循环 16 次）。

**读数口径**：**客户端 `steady_rtf` 会被会话内的编译污染**（`t1-sdpa-cudagraph` 客户端报 0.44，因为它那次的冷跑失败、warm 成了该进程的首个会话），编译臂必须看服务端切片的 rtfs/中位数。本轮冷跑还因续跑残留的 `-cold` 目录 `FileExistsError` 而失败（harness 缺陷，已修：每个 phase 前清目录）。

其余待办不变：ASR 按静音即时释放（可再省 0.5–1.9s，§9.6.2 前两段；duplex 运行时目前无人发 `TurnASRPause/EndRequested`，是 §9.5.4.1 的待修项 ②）、ASR 语言跑飞（§9.4 第 1 条）、ASR `unfixed_chunk_num` 是否与官方对齐（§9.5.4 已给出对比工具，等结果）。



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
2. `pause_handling`（candor）TOR=1.0 是**该轴最差情形**：本轮把"用户在句内停顿 ≥600ms"就当成片段边界释放，模型于是真的在用户思考停顿处接话。阶段 A 的运行时**刻意不含语义端点判定**（`duplex_manager_classes` 移除了 TurnSense/TurnDetector，见 [duplex_runtime.md](../xtalk/docs/technical_reference/duplex_runtime.md)），所以这个轴当前的代价是设计边界而非实现缺陷；要改善必须引入"停顿之后用户还没说完"的语义/韵律判定，属阶段 B 范围。`synthetic` 子集的停顿更短（0.00 TOR）说明该行为与停顿长度强相关。
3. `backchannel` Freq=0.00 同样是设计边界：阶段 A 关闭了系统附和（配置要求附和链路为空），因此"不该抢话"这一半（TOR=0.20）成立，而"该附和"这一半必然为 0。该轴本轮不作为达标项。
4. `candor_turn_taking` 上一轮 3/5 完全沉默（§9.3 判断为真失败），本轮 4/5 接话且 TOR 0.80 已接近官方 0.832。

**遗留与噪声**：`services/tts.log` 有 54 处 `websockets ... connection is closing`（客户端断开后服务端仍写帧；上一轮 21 处，数量随产出音频增加），属既有噪声、不影响指标；ASR 侧有 11 条"回改到已交付 token"的警告，可见文本在抽样会话上 7 拍全部单调延长、输出完整（`... how do I fix a leaky faucet?`），冻结缺陷未复现。

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

## 12. 实现改动清单（进度）

| 文件 | 改动 | 状态 |
| --- | --- | --- |
| `scripts/remote/duplex_a4_replay.py` | per-scenario 请求音频；新增 pause / multi_question 场景；播放自动证据字段（`played_text_monotonic`、`unplayed_tail_excluded`、`asr_updates_during_playback`、`playback_window`） | ✅ 已实现（行为以当前文件与单测为准；早期独立提交 `a59a542` 已被后续重构取代，不在分支历史中） |
| `scripts/remote/duplex_a4_replay.py` | 打断判定改为"打断原因 reset + reset 后音频冻结 1s"；新增 `interruption_stop_response_ids` / `teardown_stop_response_ids` 区分 reset 与收尾停止 | ✅ 已实现 |
| `scripts/remote/duplex_model_service.py` | 请求体改为结构化 `history`（user 文本 + assistant token id），服务端按官方 header 展平为 raw ChatML；`use_fast=True`；`num_logits_to_keep=1` | ✅ 已实现 |
| `xtalk/src/xtalk/duplex_control/runtime_adapter.py` | 历史存 token id；不截断模型流；`<\|user finish talking\|>` 打开播报窗口后才允许 reset；送 TTS 去句点 | ✅ 已实现 |
| `xtalk/src/xtalk/duplex_control/model_client.py` | 发送结构化历史，`GenerationEnd` 携带生成 token id | ✅ 已实现 |
| `xtalk/tests/test_duplex_runtime.py` | 新增并强化零旁路断言（剔除 `DirectAudioManager` 与原生语义 manager，保留 ASR/TTS/播放组件） | ✅ 已实现（X-Talk dev `2f595f3` 的 `tests/test_duplex_runtime.py::test_duplex_mode_removes_every_bypass_manager`；早期独立提交 `8c11d6b` 已被该文件重写取代） |
| `scripts/remote/run_xtalk_duplex_a4_node_job.sh` | 按场景传音频；interruption 默认用 FDB 样本 106；barge 延迟 0.6；pause gap；RSS 采样；FDB 四轴循环与评分；judge 凭据与默认 `gpt-4-turbo`；产物落 `data/runs` 与 `reports/duplex_acceptance`；末尾自动运行 `compact_a4_report.py` | ✅ 已实现 |
| `scripts/remote/compact_a4_report.py`、`tests/test_compact_a4_report.py` | 提交前把 committed 证据紧凑化：逐拍数组折成计数、采样 CSV 折成摘要、长文本截断；原始流留在 `data/runs` | ✅ 已实现（`20261014T033949Z` 由 12.1k 行压到 1.3k 行） |
| `scripts/remote/setup_fdb_scoring_env.sh` | 固定评分环境：cu126 torch + NeMo 2.x；卸载 `cuda-bindings` 让 NeMo 走 `NO_WHILE_LOOPS` 回退，并设 `NUMBA_CUDA_USE_NVIDIA_BINDING=0` | ✅ 已实现 |
| `scripts/remote/duplex_a4_replay.py` | FDB 场景的"输入结束后静音续播窗口"（`--post-input-seconds`，默认 ≥5s）与 `post_input_seconds`/tail 证据字段 | ⏳ 待实现（见 §5.6、§9.3.6、§9.4） |
| `scripts/remote/run_asr_contract_ab_node_job.sh`、`submit_asr_contract_ab_job.sh`、`summarize_asr_contract.py`、`tests/test_summarize_asr_contract.py` | ASR 流式契约对比（`unfixed_chunk_num` 0 vs 官方 2 × raw/可见暴露口径）：进程内驱动官方流式 API、按子集均衡取样、汇总改写次数/尾部释放延迟/最终转写词级距离（§9.5.4） | ⏳ 测量工具（定稿后随清理移除） |
| `scripts/remote/run_fdb_llm_judge.py` | 对已有 FDB 输出树跑官方对齐 + judge；凭据从项目根 `openai_api.txt` 读，只经子进程环境传递 | ✅ 已实现 |
| （已移除）标记探针 3 件套 | 一次性诊断：把已录制的 ASR 微轮重放给官方权重，隔离文本形态（标点/大小写/碎片粒度）对 interleave 标记的影响 | 🗑 2026-10-14 清理移除（结论见 §9.2） |
| （已移除）`micro_turn_trace.py` | 逐拍证据生成器：重建每拍 wire 历史与 prompt、统计 ASR 改写率 | 🗑 2026-10-14 清理移除（结论见 §9.5、§9.6.1） |
| `scripts/remote/qwen3_asr_service.py`、`configs/xtalk_round1.yaml`、`scripts/remote/run_xtalk_round1.py`、`tests/test_qwen3_asr_service.py` | append-only 输入契约（§9.5.4 方案 B）：只暴露已定稿前缀、`unfixed_chunk_num: 0`、smoke 支持契约覆盖与 `visible_revisions`、新增单测 | ✅ 已实现，已远端复检（§9.6.1：可见改写 0、最终转写不变） |
| （已移除）ASR before/after 对比作业 3 件套 | 单卡对比作业与汇总判据：`after` 可见改写必须为 0，并比对词级编辑距离 | 🗑 2026-10-14 清理移除（结论见 §9.6.1） |
| （已移除）`submit_duplex_interruption_recheck_job.sh` | 只重跑 `user_interruption` 轴 + 官方 judge 的复检提交 | 🗑 2026-10-14 清理移除（结论见 §9.6.1） |
| `scripts/remote/moss_tts_patch.py`、`tests/test_moss_tts_patch.py` | TTS 吞吐运行时补丁：T1 local transformer 编译后端（需 `XTALK_TTS_LOCAL_ATTN=sdpa` 才能编译）、T2 采样头（greedy/top-k nucleus）、限速 `[tts-metric]` 切片（本地/backbone CUDA 计时，backbone event 列表挂 model 以跨回合累计）、`XTALK_TTS_PROFILE` kernel 剖析与 `[moss-patch] profile` 摘要行；与真实上游循环逐 token 对拍 | ✅ 已实现并定稿（§9.6.7：每帧 75.0ms → 35.0ms、稳态 rtf 1.06 → 2.25；TTS 环境 25/25 通过） |
| `scripts/remote/run_tts_throughput_ab_node_job.sh`、`submit_tts_throughput_ab_job.sh`、`summarize_tts_throughput.py` | 单卡吞吐 A/B：每臂独立端口与健康证据、失败 arm 记 `ENV-FAILED`/`smoke-failed` 后继续、`TTS_AB_RESUME` 续跑、每 arm 资源快照、编译 worker 限流、phase 目录预清理；汇总 `Σaudio/Σwall`、local/backbone 占比与 profile 摘要 | ⏳ 测量工具（数字已定稿，随清理移除） |
| `scripts/remote/run_xtalk_round1.py`（`serve tts`、`--port`、配置默认值） | 启动期 `sitecustomize` 注入 `moss_tts_patch`（上游 checkout 不变；dynamo 动态形状补丁按 `torch_compile: dynamic` 保留）；`serve` 新增 `--port` 覆盖配置端口；`serve tts` 把 `services.tts.local_attn/local_compile` 转成 `XTALK_TTS_*`（环境显式设置优先） | ✅ 已实现 |
| `configs/xtalk_round1.yaml`（`services.tts.local_attn/local_compile`） | TTS 吞吐补丁的部署默认值：`sdpa` + 编译后端 `inductor`（§9.6.7 实测依据） | ✅ 已实现 |
| `scripts/remote/run_xtalk_duplex_a4_node_job.sh`（`tts_warmup`） | TTS 就绪后先做一次预热合成，把编译本循环的首次 ~43.6s 从首个被测话轮挪到启动阶段 | ✅ 已实现 |
| `xtalk/src/xtalk/duplex_control/micro_turn.py`、`xtalk/tests/test_duplex_runtime.py`、`xtalk/tests/test_asr_finalization.py` | duplex 控制接管 ASR 片段边界：声学 `VADSpeechEnd` → `TurnASRPauseRequested`（ASR 定稿、释放解码器扣住的尾巴），`VADSpeechStart` → `TurnASRStartRequested` 恢复；官方 `TurnTakingManager` 原本是这两个边界的发布者，被 `duplex_manager_classes` 替换后无人发布（§9.5.4.1 ②） | ✅ 已实现（含 3 个单元用例 + 1 个链路用例） |
| `scripts/remote/submit_xtalk_duplex_a4_job.sh` | 传递场景音频/FDB 四轴/judge 环境变量；提交日志改落 `data/runs/submit_logs` | ✅ 已实现 |
| `.gitignore` | 允许 `reports/duplex_acceptance/` 下的 `*.jsonl`、`*.log` 跟踪 | ✅ 已实现（清理后只保留 A4 报告例外） |
| `README.md`、`docs/tests/`、`docs/scripts/remote/` | 与新行为同步（ASR 契约、TTS 补丁、清理后的入口索引） | ✅ 已实现 |

## 13. 仓库清理记录（2026-10-14）

按"只保留原始 X-Talk 复现 + 阶段 A 最终实现"的口径做过一次清理：**结论与数字全部保留在本任务单**，移除的只是一次性脚本与它们的一次性产物。

| 移除项 | 原用途 | 结论去向 |
| --- | --- | --- |
| 标记探针 3 件套、`docs/xtalk_duplex_marker_probe.md`、`reports/duplex_marker_probe/` | 纯文本重放诊断（标点 / 大小写 / 碎片粒度） | §9.2、§9.5："没有任何变体构成修复" |
| `micro_turn_trace.py` 及其文档 | 逐拍 trace 重建与 ASR 改写率审计 | §9.5.3、§9.6.1（223/223 拍一致、可见改写 0/0/0/0/0） |
| ASR before/after 对比作业 3 件套、`reports/duplex_asr_contract/` | 单卡契约 A/B | §9.6.1（可见改写 0、最终转写逐词不变） |
| `submit_duplex_interruption_recheck_job.sh` | 一次性复检提交 | §9.6.1（rating 0.6→2.25、latency 1.536→4.10） |
| `run_xtalk_duplex_node_job.sh`、`docs/xtalk_duplex_remote_task.md` | pre-A4 官方权重运行时冒烟 | 已被 A4 作业覆盖（§2、§3） |
| `reports/duplex_acceptance/{20261013T024524Z,20261013T070801Z,20261014T025649Z}/` 与 `data/runs/` 中对应旧 run | 早期轮次与作废轮次证据 | §9.1–§9.4、§9.5.4；本目录只保留最新一轮 `20261014T033949Z` |
| P0 脚手架（`src/interclarify/`、`configs/{base,local,replay,cluster}.yaml`、`docs/src/`、`scripts/run_p0_smoke.py`、`tests/test_p0_artifacts.py`） | P0 阶段的通用配置、清单与冒烟骨架 | 与当前集群链路无关；保留 `scripts/check_env.py`、`scripts/check_audio_io.py` 作环境自检 |

保留的核心入口是原生 X-Talk 复现（§1 与 [基线栈](xtalk_baseline_stack.md)）与阶段 A 全双工实现（本任务单、[改造方案](xtalk_modification_plan.md)）。TTS 吞吐补丁 `scripts/remote/moss_tts_patch.py` 与其单测属最终实现；配套的吞吐 A/B 作业只是测量工具，拿到数字后同样移除。

实现行为与本任务单不一致时，先更新本任务单并说明原因，再改代码。
