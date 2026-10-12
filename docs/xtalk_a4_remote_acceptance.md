# A1–A3 收尾审查与 A4 远端测试任务单

## 当前结论

A1 协议、关联字段与交付边界已完成本地门禁；A2 的窗口组装、增量前缀、修订和串行调度已完成；A3 的在线 token 执行、回答续写、用户附和、final 去重、错误降级和 shutdown 已完成本地实现。最新工作树进一步实现：完整 `<|user interruption|>` 到达后同时关闭模型流、停止未播放音频、结束当前 system micro-turn；不等待 `<|im_end|>`，只在内部历史补闭合符。相关回归涵盖分片 token、无 EOS、流关闭和原始日志保留。

版本边界：A3 interruption 实现已提交为 X-Talk `2f8a43343dd83153298c416d270a8843b023abc0`。历史官方权重 smoke 使用 `17fd22d55cc7` 快照（12 micro-turn、协议错误 0），覆盖真实 LLM、脚本 ASR 和模拟 PCM。该历史结果不证明最新提交或真实 ASR/MOSS/FDB 已通过。

A4 测试入口已经准备，A4 验收保持未完成。代码检查与本地测试不替代集群真实模型运行。

## 测试范围与分工

| 项目 | 执行入口 | 通过证据 |
| --- | --- | --- |
| 源码与依赖 | manifest 校验、conda 导入、A1–A3 回归 | SHA256、git 状态、测试日志 |
| 官方模型接入 | 原有 `duplex_runtime_smoke.py` | 严格权重装载、health、raw wire token |
| 真实 ASR/TTS | `duplex_a4_replay.py` | 真实 WAV→ASR partial→LLM→MOSS PCM→播放确认 |
| 用户打断 | 同一回放器 interruption 场景 | 同一 response 的 interruption raw token、reason、TTSStopped |
| 会话压力 | long_session 场景，增加 `--rounds` | 持续收音、多个 micro-turn、无协议错误、GPU 采样 |
| FDB v1/v1.5 | 同一回放器批处理 + 官方对齐/评分 | 新生成等长输出 WAV、官方转写、判分日志 |
| 原生对照、音质、长期资源稳定性 | 同设备上的额外实验 | 成对基线、试听、长时资源趋势、shutdown 日志 |

回放器模拟有节奏的 headless 播放确认；它不使用真实声卡。三轮压力 smoke 不能证明长期资源稳定性。停顿、思考、提前回答和用户附和要使用专门选定的真实音频及 FDB 子集补充；不能因为模型未输出对应 token 就宣称覆盖。

## 源码准备

根仓库忽略 `xtalk/`。必须同步两个工作树，并固定 X-Talk 提交 `2f8a43343dd83153298c416d270a8843b023abc0`；只拉取根仓库不会取得 X-Talk 源码。推荐复制到新的独立目录，再生成清单；保存开发机生成的清单，服务器只校验，不在服务器重新生成清单掩盖传输差异。

```bash
# 在完整待同步目录中，使用本地 conda 环境
conda run -n paratalker-dev python scripts/remote/create_duplex_source_manifest.py
# 将整个目录及 source_manifest.json 同步到服务器的独立目录
```

禁止复用非空运行目录。模型不下载、不训练。沿用服务器现有官方 checkpoint、Qwen2 基础模型、round1 `models.lock.json`、ASR/MOSS/codec 和参考音色。

## 集群运行

默认镜像 `sjtu_yukai-xuanzhang-xtalk-round1:v0.3`，申请 **3 GPU / 24 CPU / 96G**。官方模型用 GPU 0，Qwen3-ASR 用 GPU 1，MOSS 用 GPU 2；各服务使用现有 conda 环境。

```bash
# 在服务器的独立源码目录执行
export INTERCLARIFY_DUPLEX_ROOT="$PWD"
bash scripts/remote/submit_xtalk_duplex_a4_job.sh
```

已经进入分配到三张 GPU 的节点时：

```bash
export INTERCLARIFY_DUPLEX_ROOT="$PWD"
export CONDA_SH=/opt/conda/etc/profile.d/conda.sh
bash scripts/remote/run_xtalk_duplex_a4_node_job.sh
```

默认请求 `$XTALK_ROUND1_ROOT/audio/request.wav` 可能只产生短回答，无法保证播放期间仍有可打断尾部。请准备较长回答请求及明确的打断音频；缺少实际 token 或活动播放机会会记为 `INCONCLUSIVE`。

```bash
export DUPLEX_A4_INPUT=/absolute/path/long_request.wav
export DUPLEX_A4_INTERRUPPTION_AUDIO=/absolute/path/stop_request.wav
export DUPLEX_A4_REQUIRE_INTERRUPTION=1
```

默认输出 `artifacts/a4/<UTC-tag>/`。主要文件：`source_check.json`、`environment.txt`、`models.lock.json`、`gpu_samples.csv`、三份服务日志、`tests/`、`model_health.json`、`replay/summary.json`、逐场景 WAV/报告/时间线、`steps.jsonl`、`a4_summary.json`。

`PASS` 表示该步骤门禁通过，`FAIL` 表示执行或协议失败，`INCONCLUSIVE` 表示语义场景未覆盖，`BLOCKED` 表示所需资产或评分环境缺失。汇总 `INCOMPLETE` 保留未完成状态。默认退出码反映硬失败；设置 `DUPLEX_A4_REQUIRE_COMPLETE=1` 时，未完成也返回非零。任务单中剩余人工项单独记录，即使自动步骤全部通过也不能直接将整个 A4 标为完成。

## FDB smoke

已核对官方 FDB 提交 `3e799c45a045256f47d5f1c9cda90157e2d2ec9e` 的 [v1/v1.5 推理与评分说明](https://github.com/DanielLin94144/Full-Duplex-Bench/tree/3e799c45a045256f47d5f1c9cda90157e2d2ec9e/v1_v1.5)。输入根目录应是**单个任务子集**，下一层为样本目录。回放器限制样本目录数，保持 `input.wav` 与可选 `clean_input.wav` 成对处理；输出目录必须位于输入树外，使用新的空目录。

```bash
export DUPLEX_A4_FDB_INPUT_ROOT=/shared/fdb/v1.0/pause_handling
export DUPLEX_A4_FDB_OUTPUT_ROOT=/shared/a4-runs/unique-tag/pause_handling
export DUPLEX_A4_FDB_LIMIT=5
export DUPLEX_A4_FDB_REPO=/shared/Full-Duplex-Bench
export DUPLEX_A4_FDB_ENV=full-duplex-bench
export DUPLEX_A4_FDB_TASK=pause_handling
export DUPLEX_A4_FDB_COMMIT=3e799c45a045256f47d5f1c9cda90157e2d2ec9e
bash scripts/remote/submit_xtalk_duplex_a4_job.sh
```

先使用 conda 建立独立 FDB 环境，按该固定仓库的 requirements 准备 NeMo 对齐和评分依赖。默认生成推理 WAV；提供仓库、环境和任务后调用官方 `get_transcript/asr.py` 与 `evaluation/evaluate.py`。需要付费 judge 的 `user_interruption`、`behavior` 使用用户已配置的凭据，脚本不记录凭据。对齐 GPU 与模型服务分阶段使用，避免共占官方模型显存。

v1.0 优先跑 pause_handling、smooth_turn_taking、user_interruption；v1.5 user_interruption、user_backchannel 等 overlap 子集使用 `behavior` 评分，并按官方方法补 timing。系统输出 backchannel 指标保持范围外，**用户附和抗误打断仍必测**。原生 X-Talk 对照使用相同回放器的 `--native` FDB 模式与 `configs/xtalk_round1_runtime.json`，在已启动原生 LLM/TurnSense/ASR/MOSS 的节点执行；基线与 Duplex 模式采用相同输入、参考音色、播放确认、对齐器和评分版本。

## A4 最终审查

1. 核验 manifest 对应当前补丁，health 中 token ID、checkpoint、base model、BF16 均正确。
2. interruption 必须是模型实际 token；停止事件关联同一 response。运行时事后发布 protocol_parsed，因此该时间不能冒充 token 到达时刻；报告只给 stop request→TTSStopped 执行延迟和用户输入→客户端停止延迟。
3. 听取 WAV 并检查已播文本保持单调，未播放尾部不记为已播；确认 ASR 在系统播放期间继续更新。
4. 完成用户附和、停顿、思考、提前回答、重叠语音和原生成对 FDB smoke；判分日志中的绝对分数与差值另行汇总。
5. 扩大长会话轮数/时长，查看队列、RSS、显存趋势、任务异常和会话 shutdown；记录任何 context_length 限制。
6. 配置与实际 manager 集合禁用 System Backchannel 和 DirectAudioManager；当前 timeline 不记录所有工具事件，日志中未出现旁路不等于已证明所有旁路调用为零。
