# XTurnix FLEURS 数据冻结入口

`scripts/remote/xturnix_fleurs_test.py` 是 XTX 系列共用的远端入口。当前阶段只实现 `prepare-data` 与 `verify-data`：固定 100 条英文 test 输入、1 条 dev 预热输入，并保存历史 Nemotron ASR 基线来源。脚本不加载模型、不回放音频，也不计算任何质量指标。

## 固定范围

- 数据集 `google/fleurs`，revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`，不接受缺省最新版本。
- `en_us/test` 按 `SHA256(filename)` 升序取前 100 条；`en_us/dev` 同规则取 1 条，仅用于协议预热，不计入正式分母。
- 核对历史总量：test 总时长 969.26 秒，参考文本经 `whisper-normalizer==0.1.12` 标准化后 2,162 词。
- 核对边界文件：test 首末为 `2074231104398719826.wav`、`1277588711703410007.wav`，dev 为 `786465049904960526.wav`。
- 音频按归档原始字节提取或从已有核验数据复制，不重采样、不转换声道、不裁剪头尾静音。PCM16 传输转换属于后续回放阶段，单独记账。

## 两种输入来源

| 模式 | 用法 | 行为 |
| --- | --- | --- |
| 恢复下载 | 默认 | 从固定 revision 串行下载 2 个 TSV 和 2 个音频归档，只解出选中的 101 个 WAV |
| 只读复用 | `--reuse-dir PATH` | 从既有 FLEURS 数据目录（或其工作区根）读取 TSV 与选中 WAV；不复用旧 manifest，不信任旧哈希 |

只读复用时，脚本重新按固定 TSV 选择样本，要求复用目录中的 WAV 集合与选择结果完全一致，然后复制到新的冻结目录并重新计算全部哈希。这样既避免重复下载，也不会把“目录仍存在”误当成“与历史 manifest 逐文件验同”。

目标目录已有冻结结果时默认失败；只有显式 `--overwrite` 才替换，避免误删上一轮证据。

## 类与核心方法

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

## 输出

`--root` 下写入：

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

Git 只保存脚本、测试、说明和简明结果摘要，不保存音频、归档或远端 manifest。

## 远端执行

远端数据环境沿用已存在的 `~/miniconda3/envs/interclarify-x2-turn-data`（Python 3.11.17；`whisper-normalizer==0.1.12`、`soundfile==0.14.0`、`huggingface_hub==0.36.2`）。该环境只用于数据哈希与文本标准化，不执行已退役的 X2-Turn 代码。运行前设置 `PYTHONNOUSERSITE=1`。

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

## 资源与边界

数据准备最多 4 CPU、8 GiB RAM、下载并发 1，单作业 1 小时，新增资产累计不超过 10 GiB，启动空闲盘至少 30 GiB。该阶段不加载 GPU 模型、不启动回放、不恢复旧专用测试脚本，也不改写源音频。
