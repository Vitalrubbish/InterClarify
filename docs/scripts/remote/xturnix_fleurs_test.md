# XTurnix FLEURS 数据与回放入口

`scripts/remote/xturnix_fleurs_test.py` 是 XTX 系列共用的远端入口。`prepare-data` 与 `verify-data` 属于 XTX-001，负责固定 100 条英文 test 输入、1 条 dev 预热输入和历史 Nemotron ASR 基线来源；`replay` 属于 XTX-003，按真实时钟把音频流经 Nemotron 与 XTurnix，并保存可离线评分的因果 trace。回放本身不计算 start 延迟或 WER，指标由 XTX-004 独立完成。

## 固定范围

- 数据集 `google/fleurs`，revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`，不接受缺省最新版本。
- `en_us/test` 按 `SHA256(filename)` 升序取前 100 条；`en_us/dev` 同规则取 1 条，仅用于协议预热，不计入正式分母。
- 核对历史总量：test 总时长 969.26 秒，参考文本经 `whisper-normalizer==0.1.12` 标准化后 2,162 词。
- 核对边界文件：test 首末为 `2074231104398719826.wav`、`1277588711703410007.wav`，dev 为 `786465049904960526.wav`。
- 音频按归档原始字节提取或从已有核验数据复制，不重采样、不转换声道、不裁剪头尾静音。PCM16 传输转换属于回放阶段，单独记账。

## 两种数据输入来源

| 模式 | 用法 | 行为 |
| --- | --- | --- |
| 恢复下载 | 默认 | 从固定 revision 串行下载 2 个 TSV 和 2 个音频归档，只解出选中的 101 个 WAV |
| 只读复用 | `--reuse-dir PATH` | 从既有 FLEURS 数据目录（或其工作区根）读取 TSV 与选中 WAV；不复用旧 manifest，不信任旧哈希 |

只读复用时，脚本重新按固定 TSV 选择样本，要求复用目录中的 WAV 集合与选择结果完全一致，然后复制到新的冻结目录并重新计算全部哈希。这样既避免重复下载，也不会把“目录仍存在”误当成“与历史 manifest 逐文件验同”。

目标目录已有冻结结果时默认失败；只有显式 `--overwrite` 才替换，避免误删上一轮证据。

## 数据准备类与核心方法

`DatasetPreparer` 管理一次冻结：

- `check_capacity`：启动前要求工作盘至少 30 GiB 空闲，写入前后记录容量。
- `download_sources` / `stage_reused_sources`：下载固定源文件，或从既有数据只读复制 TSV；两种模式都记录来源与摘要。
- `select_sources`：校验 7 列 TSV、文件名和参考文本，按固定规则选样，并检查 test/dev 无交集。
- `extract` / `copy_reused_audio`：只写入选中的 WAV；下载模式从归档解出，复用模式逐文件复制，均采用 `.part` 原子替换。
- `build_sample`：计算音频 SHA256，记录声道、采样率、帧数、时长、原始参考、数据集标准化参考和固定 normalizer 的标准化参考。
- `check_expectations`：核对条数、总时长、标准化词数及首末/dev 文件名；任一不符立即失败，不替换样本凑数。
- `prepare`：串联容量预检、取源、选样、写音频、写 manifest/lock/baseline/report，最后调用独立复核。

`verify_manifest` 不重新下载，逐项复核文件存在、音频哈希、元数据、时长、标准化词数、选择键顺序、test/dev 路径边界、实际文件集合、汇总数、源文件副本和历史基线记录。`verify_data` 在复核后写 `verification.json`。

`historical_baseline` 固定记录历史来源提交 `f6ad9d9ba04e4e046dcfcdd480b5343165466046`、指标定义、可测词覆盖和限制：P50 413.582852 ms、P95 1,032.668798 ms、可测词 3,068/4,324、WER 7.68%。该 P50 只作为逐词典型开销常数，不是均值、末词实测或端到端成绩。

## 真实时钟回放

`replay` 先从冻结 manifest 读出计划样本，逐条串行执行：

1. 校验音频 SHA256 与格式，把原文件转成 16 kHz 单声道 PCM16；源文件不改写。每条录音新建 ASR 会话，控制历史为空。
2. `ResultObserver` 独立按 50ms 轮询 ASR 前缀版本，不等待整个文件结束。版本变化即记录 `asr_observation`，包括原始/累计文本、增量、词汇 token、词汇变化、接收单调时钟和当前阶段。
3. 每个非空 ASR 版本进入 `ControlScheduler`。调度器只保留最新未开始前缀，最多一个在途控制请求；排队、合并、丢弃和迟到返回都写入 trace。冻结服务只交付累计文本，因此 trace 记录文本增量与词形 token，并明确标 `token_ids_available=false`，不伪造模型 token ID。
4. XTurnix 始终以 Listen 状态和当时可见的累计前缀推理，只记录 `<|start|>` / `<|keep|>`。start 是影子决策：不关闭 ASR、不切换 Speak、不播放，也不抑制后续 start。
5. 文件音频按 80ms 包真实发送。发完后继续 63 个静音包（5.04 秒），在尾窗结束时设置在线采集截止 `online_cutoff`，随后发送真实 EOF 并等待排空。
6. ASR 在 EOF 排空阶段的新版本继续保留，但阶段标为 `eof_drain`；截止后返回的控制结果记为 `post_cutoff`，不进入在线主指标。

阶段顺序固定为 `file_audio → tail_silence → post_cutoff → eof_drain → closed`，并在 trace 中写入 `file_audio_complete`、`online_cutoff`、`eof_request_started`、`eof_completed` 等标记。暂停注入保持关闭：不从 EOF、文件时长、参考文本、离线最后 token 或事后对齐补点。

### 回放类与核心方法

- `ReplaySettings`：从冻结配置派生 80ms 包、16 kHz、63 个尾窗包、5 秒主窗口、50ms 轮询、30 秒 ASR 超时和 10 秒控制超时。任何放宽都会在 `load_replay_config` 阶段被拒绝。
- `AsrClient`：单会话 HTTP 客户端，分别读取 `/health`、创建、送音、结果与删除；非 200 一律作为证据失败，不静默重试。
- `ResultObserver`：后台线程独立轮询前缀。仅在新 `prefix_version` 时写事件；用词形 token 判断 `lexical_change`，因此只新增标点或空白不会被误记为新词。
- `ControlScheduler`：单工作者线程。`submit` 只保留最新前缀；被替换的未开始请求记 `control_superseded`，截止时仍未开始的记 `control_dropped`。请求 ID、输入版本、观察事件序号、发送/返回时间和是否在截止前返回都写入 trace。
- `XTurnixController`：只加载一次冻结的 `turn_pipeline.py` 与权重，按官方 Listen 提示词串行推理，并记录归一化后的输入、动作和分数。
- `ReplayRunner`：串行运行计划样本，写输入快照、逐例 trace、`status.json` 和 `replay_report.json`。失败样本保留，后续样本继续；若会话清理失败或控制线程无法停止，则停止后续样本并标记 `skipped`，避免污染下一条记录。
- `TraceRecorder` / `PhaseTracker`：为每例维护全局递增事件序号和同一客户端单调时钟，供 XTX-004 重建因果顺序。

### 输入快照与 trace 边界

`input_snapshot.json` 只记录配置摘要、manifest 摘要、计划样本的音频路径/哈希/格式和时序参数，不把参考答案送入在线回放。控制请求只接收 ASR 当时可见的文本；trace 中保留原始输入摘要和请求关联。参考答案由 XTX-004 在离线评分时从 manifest 读取。

## 输出

`--root` 下冻结数据写入：

```text
dataset/fleurs_en_us/
├── audio/test/*.wav          # 100 条正式输入
├── audio/dev/*.wav           # 1 条预热输入
├── source/en_us/*.tsv        # 固定 revision 的小型文本副本
├── dataset.lock.json         # revision、来源模式、选样规则与源摘要
├── manifest.json             # 逐例参考、音频元数据、摘要与汇总
├── historical_asr_baseline.json  # 历史 ASR 常数来源、定义与限制
├── prepare_events.jsonl      # 下载/复用、选样、容量事件
├── prepare_report.json       # 成功状态、容量、资产与产物摘要
└── verification.json         # verify-data 的独立复核记录
```

每次回放写到新目录（默认 `<root>/runs/<run_id>/replay`）：

```text
replay/
├── config.json               # 本次实际使用的配置副本
├── input_snapshot.json       # 计划样本、音频摘要、时序参数；不含参考文本
├── traces/test/*.jsonl       # 逐例因果事件
├── traces/dev/*.jsonl
├── status.json               # 全部计划样本的 completed/failed/skipped 与原因
└── replay_report.json        # 运行状态、计数、控制器信息与 trace 大小
```

`replay_report.json` 只报告回放执行事实；不计算、也不暗示 start 命中率、末词延迟、WER 或模型质量。`status.json` 覆盖全部计划分母，失败与跳过都不从清单消失。

## 远端执行

数据环境沿用已存在的 `~/miniconda3/envs/interclarify-x2-turn-data`（Python 3.11.17；`whisper-normalizer==0.1.12`、`soundfile==0.14.0`、`huggingface_hub==0.36.2`）。该环境只用于数据哈希与文本标准化，不执行已退役的 X2-Turn 代码。运行前设置 `PYTHONNOUSERSITE=1`。

```bash
PYTHONNOUSERSITE=1 ~/miniconda3/envs/interclarify-x2-turn-data/bin/python \
  scripts/remote/xturnix_fleurs_test.py prepare-data \
  --root ~/interclarify-xturnix-fleurs \
  --reuse-dir ~/interclarify-x2-turn-complete
```

无既有数据时去掉 `--reuse-dir`，脚本使用 `https://hf-mirror.com` 并串行下载。实际 endpoint 写入数据锁；可用 `--endpoint` 或 `HF_ENDPOINT` 覆盖，revision 始终固定。

```bash
PYTHONNOUSERSITE=1 ~/miniconda3/envs/interclarify-x2-turn-data/bin/python \
  scripts/remote/xturnix_fleurs_test.py verify-data \
  --root ~/interclarify-xturnix-fleurs
```

回放必须在远端 GPU 调度作业内启动冻结的 Nemotron 服务后运行，使用 XTurnix 隔离环境的 Python：

```bash
PYTHONNOUSERSITE=1 ~/interclarify-xturnix-fleurs/envs/xturnix/bin/python \
  scripts/remote/xturnix_fleurs_test.py replay \
  --root ~/interclarify-xturnix-fleurs \
  --run-id xtx-003-dev-smoke-20261023 \
  --split dev --limit 1 \
  --asr-url http://127.0.0.1:18805
```

`--split` 可选 `test`、`dev`、`all`，`--limit` 只用于冒烟；正式 100 条由 XTX-006 按计划清单执行。输出目录已存在且非空时脚本直接失败，避免覆盖旧证据。完整的单作业启动、限额和退出清理属于 XTX-005 的 `run_xturnix_fleurs_job.sh`。

## 资源与边界

数据准备最多 4 CPU、8 GiB RAM、下载并发 1，单作业 1 小时，新增资产累计不超过 10 GiB，启动空闲盘至少 30 GiB。回放沿用 XTX-002 冻结的两组件配置，串行处理单条录音，不训练、不调阈值、不接入 Layer 1/TTS/播放器。trace 累计超过 2 GiB 时停止并保留失败，不自动扩容。单元测试中的模拟服务只验证协议与时序，不代表真实 Nemotron 或 XTurnix 成绩。
