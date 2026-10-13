# 阶段 A 全双工运行时验收任务单

## 1. 目标与范围

本任务单把阶段 A 的验收从"入口已准备"推进到"在服务器上跑出可复核的真实证据"。范围包括：源码与依赖校验、官方 DuplexCascade 权重接入、真实 ASR/MOSS 音频回放、用户打断、长会话压力、FDB v1.0 对齐与评分、零旁路验证，以及人工试听与资源趋势。

本轮**只做 Duplex 模式**，不做原生 X-Talk 对照；backchannel 语义场景留给后续 FDB v1.5。

## 2. 本轮已确定的决定

| 主题 | 决定 |
| --- | --- |
| 开发与同步 | 直接在服务器共享盘工作树原地开发；无本地/远端同步。提交前原地生成 manifest，作业内校验 |
| 集群镜像与资源 | `sjtu_yukai-xuanzhang-xtalk-round1:v0.3`，`pdgpu-4090`，3 GPU / 24 CPU / 96G |
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
6. **FDB 场景增加"输入结束后静音续播窗口"**（`--post-input-seconds`，默认对齐官方 ≥5s）：送完 `input.wav` 后继续喂静音并保持会话，使模型在用户说完之后产生的回答能被录进 `output.wav`；报告记录 `post_input_seconds` 与实测 tail，作为"回答是否被录到"的判据。本轮 `_run_fdb` 只 `sleep(0.5)`，是 §9.4 口径问题的直接原因。

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

关键环境变量（脚本已内置下列默认值，可按需覆盖）：

```bash
export DUPLEX_A4_REQUIRE_INTERRUPTION=1
export DUPLEX_A4_REQUIRE_COMPLETE=1
export DUPLEX_A4_ROUNDS=30
export DUPLEX_A4_BARGE_AFTER_SECONDS=0.6
export DUPLEX_A4_SCENARIOS="normal interruption pause multi_question long_session"
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

### 9.1 本轮结果（2026-10-13，tag `20261013T070801Z`）

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

**上游参照**：上游仓库自带 Full-Duplex-Bench 结果表，已归档为 `reports/duplex_acceptance/20261013T070801Z/reference/upstream_full_duplex_bench_table.png`（原图在 `/hpc_stor03/sjtu_home/xuan.zhang/DuplexCascade/assets/full-duplex-bench.png`）。DuplexCascade 在同一 `synthetic` 子集上的 User Interruption：TOR 0.955、GPT-4o 4.016、latency 1.225；其余三轴为 Pause Handling 0.058/0.222、Backchannel 0.218/0.009/0.949、Smooth Turn Taking 0.832/1.724。

用 §7.1 的入口对本轮 5 个 `user_interruption` 样本跑官方对齐 + 官方默认 `gpt-4-turbo` judge：

```
conda run --no-capture-output -n paratalker-dev python scripts/remote/run_fdb_llm_judge.py \
  --root-dir data/runs/20261013T070801Z/fdb/user_interruption/synthetic_user_interruption \
  --out data/runs/20261013T070801Z/fdb_llm_judge --task user_interruption --gpus 0
```

`align_rc=0`、`judge_rc=0`，`llm_judge_summary.json`：`average_rating=0.6`、`average_take_turn=1.0`、`average_latency=1.536`。证据归档在 `reports/duplex_acceptance/20261013T070801Z/tests/fdb_scoring_user_interruption.{align,judge}.log`、`fdb_scoring_user_interruption.ratings.json`、`fdb_scoring_summary.json`。

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

文本形态这条线已用 [DuplexCascade 标记探针任务单](xtalk_duplex_marker_probe.md) 实测判定：`raw` 变体复现了生产录制（10/100/102 逐标记一致，**含 10/100 的失败与 102 的成功**），说明探针可信；`strip` / `strip_lower` / `burst` 确实能确定性地翻转打断判定（重复实验证明同输入下解码稳定，非噪声），但**没有任何变体构成修复**——三种变体各只救一个样本且互相抵消（`burst` 弄丢 102 本可用的 interruption，`strip_lower` 让 100 退化成 19 连 `<|user is thinking|>`）；打断前的 `talking → finish talking` 在所有变体里都稳定，唯一致命的就是打断分类本身。

**结论（2026-10-13 修正）**：本轴状态机对齐正确、文本归一化不构成修复，但**不能把低分归因于上游能力**。上游仓库自带的 Full-Duplex-Bench 结果表（`DuplexCascade/assets/full-duplex-bench.png`）显示同一 `synthetic` 子集上 DuplexCascade 的 User Interruption 为 **TOR 0.955 / GPT-4o 4.016 / latency 1.225**，而我们实测 1.0 / 0.6 / 1.536——模型在原版链路上能做出"让出话轮并回答新问题"的行为。因此差异来自我们这条输入链路，而按排除法**唯一未验证与原版一致的环节就是模型唯一的输入：ASR 文本流**（我们用 Qwen3-ASR-1.7B 的 0.6s 累积前缀＋标点，上游用 Kyutai `delayed-streams-modeling` 的逐词流）。探针只测了"对我们自己的 ASR 文本做变换"，结构上无法发现这一点，属已知方法盲区。

待验证路径（按成本排序）：① `truth` 变体——用 FDB `interrupt.json` 的 `context`/`interrupt` 原句按时间戳逐词注入替代我们的 ASR 流；② `kyutai` 变体——用官方 STT 对同一段音频取词流再重放；③ 全量 FDB v1.0 跑完后与上游表逐轴对齐（Pause Handling 0.058/0.222、Backchannel 0.218/0.009/0.949、Smooth Turn Taking 0.832/1.724），若仅此轴显著偏低则病灶锁定在该路径。比较时须同时记录三处口径差异：judge 模型（上游 GPT-4o，我们官方默认 `gpt-4-turbo`）、上游图未标注 FDB 版本（我们为 `fdb/v1_0`）、上游 TOR 为 0.955 而非 1.0。

附带观察：`icc_backchannel/11` 的 ASR 整段偏成西班牙语、模型回了 `¡`，说明这条 ASR 文本流本身可以严重偏轨。

**机制定位（同日补）**：把探针 15 个"样本×变体"按"打断到达前模型**是否已经开口**"分组后，规律很干净——**打断前已生成答案文本（72–103 词）→ `backchannel`（10/11）**；**尚未开口（0 词）→ `talking`/`interruption`（3/3，其中 `102 raw` 走到 `interruption` ✓）**。即主导线索是**模型自身的说话状态**（"我在讲话时对方出声 = 附和"），而非用户文本的内容。样本 1/10/100/101 都在约 3s 就答完了上下文问题（`first_audio_seconds` 2.6–3.3s），而 FDB 的合成打断固定在 9.2–9.8s，必然落进"我正在说话"的窗口 → 该轴几乎结构性必挂；唯一成功的 102 是唯一"还没开口"的样本。详见 [探针任务单 §6](xtalk_duplex_marker_probe.md)。这也让"待验证路径"收敛为一条：**当模型已经开口时，什么条件能让它改判为夺轮**（官方链路能拿 4.016，说明存在我们尚未复刻的条件；官方 STT 的逐词流形态仍是最可疑者）。**补充**："ASR 比用户输入慢"已被量测排除——更新间隔中位数 0.61s（每拍一条）、末条文本距语音实际结束 −0.53~+0.95s、逐词延迟 0~0.6s 且不累积，即延迟就是"0.6s 分块+推理"的地板（详见 [探针任务单 §6](xtalk_duplex_marker_probe.md)）。

### 9.3 全量 FDB v1.0 运行的前置要求

全量跑（四轴 + 全部子集）时至少满足：

1. **保留逐拍证据**：`fdb_driver/*/timelines/` 或等价记录必须落盘，并在其中记录每拍的 micro-turn 文本（`delta_text`/`revision_kind`）与模型 raw output。上一轮为省空间删除 timelines，导致无法把协议 token 精确对齐到拍，只能靠 `services/duplex_model.log` 的 `prompt_tokens` 增量反推。
2. **统计协议 token**：汇总各轴 `<|no voice|>`/`talking`/`finish talking`/`interruption`/`backchannel` 的出现次数与位置，作为"模型标记是否可信"的量化证据。
3. **记录节奏指标**：复位后到首音频的延迟、已播文本的最大停顿（本轮 101 在裁剪边界处停了 3.18s，直接污染 latency）。
4. **消融实验（已完成）**：见 [DuplexCascade 标记探针任务单](xtalk_duplex_marker_probe.md) §6。`raw`/`strip`/`strip_lower`/`burst` 都能确定性翻转打断判定，但没有一个变体是修复（各救一个样本且互相抵消），故不做文本归一化改动；标点/大小写这条线作废。
5. 复听让出话轮样本的 `output.wav`（本轮 102 的 `travel tips` 被官方 parakeet 转成 `trap dapple tips`）。
6. **补足输入结束后的录制/续播窗口**：本轮 `_run_fdb` 在送完音频后只等 0.5s，导致 `output.wav` 与 `input.wav` 等长（tail = 0），三个非打断轴的回答落在窗口之外。全量跑前必须把窗口设为可配置且 ≥ 官方量级（≥5s），并在报告里记录 `post_input_seconds` 与实测 tail。

### 9.4 其它三轴的作答统计与输入侧缺陷（2026-10-13，tag `20261013T070801Z`）

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

**不受该口径缺陷影响的两条**：

1. **`candor_turn_taking` 的 3/5 沉默是真失败**：`turn_taking.json` 的 `[TURN-TAKING]` 标记在文件中部（5.63 / 4.23 / 4.83 / 5.79 / 6.52s，而文件长 10.90 / 9.60 / 9.91 / 10.79 / 11.80s），让轮之后仍有余量——1 / 101 / 102 在各自约 5s 余量内零输出，10 / 100 则分别在让轮后 **0.80s / 1.39s** 作答。该轴官方要求 TOR↑（上游 0.832），故这 3 个样本是与 `user_interruption` 同向的真实失败，是目前唯一可确认的"第二处异常"。
2. **"用户说话期间的行为"证据依然有效**：Pause Handling 的 TOR（是否在停顿处抢话）与 Backchannel 的 TOR/Freq 都只看文件内音频，例如 `candor_pause_handling/1` 在 3.22s 就抢答——是该轴要惩罚的提前接管。这三轴可以用本轮产物直接跑官方评分，只需在文档里注明录制窗口。而 Pause Handling / Backchannel 的 TOR 越低越好，其"少言"在方向上不构成异常。

**输入侧缺陷**：

1. **ASR 语言会跑飞**：`icc_backchannel/1` 的 `update_asr` 全程是德语（`ja also es ist wie ich war sitzend ...`），`/11` 全程是西班牙语（`yo no te dije que ...`）；而这两份 `input.wav` 按 FDB `transcription.json` 都是英语。原因在 `scripts/remote/qwen3_asr_service.py`：会话初始化只传了流式切块参数（`chunk_size_sec`/`unfixed_chunk_num`/`unfixed_token_num`），**没有传 `language`/`context`**；而 `qwen_asr` 的 `init_streaming_state(context="", language=None, ...)` 支持强制语言。属可直接修复项。
2. **ASR 更新以"改写末尾"为主**：25 个样本的相邻 `update_asr` 中，真正"严格延长上一版"的比例只有 0–27%，其余 62–100% 会重写末尾若干个词（例：`checked before.` → `checked beforehand,`；`icc_backchannel/0` 为 1 次追加 / 26 次改写）。这来自流式配置 `unfixed_token_num: 5` / `unfixed_chunk_num: 2`（末尾 5 个 token / 2 个 chunk 视为未定），于是运行时几乎每拍都会走 `REWRITE` 修复路径，而官方 Kyutai 词流是单调追加的。是否收紧这两个参数属待评估项。

**待办**：①先给 `_run_fdb` 加可配置的"输入结束后静音续播窗口"（对齐官方 ≥5s，并保留 tail 字段作为证据），再重跑三个非打断轴，用官方评分器（`pause_handling` / `smooth_turn_taking` 不需要 LLM judge，只需 `get_transcript/asr.py` + `evaluate.py`）与上游表逐轴对齐；②`user_interruption` 自带 15s 尾静音、不受该缺陷影响，可沿用 §9.2 结论无需重跑。③另见输入侧缺陷两条（ASR 语言、末尾改写为主）待评估。

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
| `scripts/remote/duplex_a4_replay.py` | per-scenario 请求音频；新增 pause / multi_question 场景；播放自动证据字段（`played_text_monotonic`、`unplayed_tail_excluded`、`asr_updates_during_playback`、`playback_window`） | ✅ 已实现（`a59a542`） |
| `scripts/remote/duplex_a4_replay.py` | 打断判定改为"打断原因 reset + reset 后音频冻结 1s"；新增 `interruption_stop_response_ids` / `teardown_stop_response_ids` 区分 reset 与收尾停止 | ✅ 已实现 |
| `scripts/remote/duplex_model_service.py` | 请求体改为结构化 `history`（user 文本 + assistant token id），服务端按官方 header 展平为 raw ChatML；`use_fast=True`；`num_logits_to_keep=1` | ✅ 已实现 |
| `xtalk/src/xtalk/duplex_control/runtime_adapter.py` | 历史存 token id；不截断模型流；`<\|user finish talking\|>` 打开播报窗口后才允许 reset；送 TTS 去句点 | ✅ 已实现 |
| `xtalk/src/xtalk/duplex_control/model_client.py` | 发送结构化历史，`GenerationEnd` 携带生成 token id | ✅ 已实现 |
| `xtalk/tests/test_duplex_runtime.py` | 新增并强化零旁路断言（剔除 `DirectAudioManager` 与原生语义 manager，保留 ASR/TTS/播放组件） | ✅ 已实现（X-Talk `8c11d6b`） |
| `scripts/remote/run_xtalk_duplex_a4_node_job.sh` | 按场景传音频；interruption 默认用 FDB 样本 106；barge 延迟 0.6；pause gap；RSS 采样；FDB 四轴循环与评分；judge 凭据与默认 `gpt-4-turbo`；产物落 `data/runs` 与 `reports/duplex_acceptance` | ✅ 已实现 |
| `scripts/remote/setup_fdb_scoring_env.sh` | 固定评分环境：cu126 torch + NeMo 2.x；卸载 `cuda-bindings` 让 NeMo 走 `NO_WHILE_LOOPS` 回退，并设 `NUMBA_CUDA_USE_NVIDIA_BINDING=0` | ✅ 已实现 |
| `scripts/remote/duplex_a4_replay.py` | FDB 场景的"输入结束后静音续播窗口"（`--post-input-seconds`，默认 ≥5s）与 `post_input_seconds`/tail 证据字段 | ⏳ 待实现（见 §5.6、§9.3.6、§9.4） |
| `scripts/remote/run_fdb_llm_judge.py` | 对已有 FDB 输出树跑官方对齐 + judge；凭据从项目根 `openai_api.txt` 读，只经子进程环境传递 | ✅ 已实现 |
| `scripts/remote/probe_duplex_markers.py`、`run_duplex_probe_node_job.sh`、`submit_duplex_probe_job.sh` | 纯文本重放探针：把已录制的 ASR 微轮重新喂给官方权重，隔离文本形态（标点/大小写/碎片粒度）对 interleave 标记的影响 | ✅ 已实现 |
| `scripts/remote/submit_xtalk_duplex_a4_job.sh` | 传递场景音频/FDB 四轴/judge 环境变量；提交日志改落 `data/runs/submit_logs` | ✅ 已实现 |
| `.gitignore` | 允许 `reports/duplex_acceptance/` 下的 `*.jsonl`、`*.log` 跟踪 | ⬜ 待做 |
| `README.md`、`docs/tests/`、`docs/scripts/remote/` | 与新行为同步 | ⬜ 部分待做 |

实现行为与本任务单不一致时，先更新本任务单并说明原因，再改代码。
