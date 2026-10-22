# 历史 FLEURS 子集核查

更新：2026-10-22。状态：已核对历史 Git 记录并登录远端只读检查；没有下载数据、部署 X2-Turn 或运行模型。用户已取消本轮 FDB 质量测试，当前仅确认历史 FLEURS 子集，不自动开始新的测试计划。

## 1. 当时使用的数据

| 项目 | 历史记录 |
| --- | --- |
| 数据集 | `google/fleurs`，名称为 FLEURS |
| 固定 revision | `70bb2e84b976b7e960aa89f1c648e09c59f894dd` |
| 正式子集 | `en_us/test` 的 100 条独立录音 |
| 选择规则 | 对原始音频文件名计算 SHA256，按哈希升序取前 100 条 |
| 总时长 | 969.26 秒，约 16.15 分钟 |
| 标准化参考词数 | 2,162 词 |
| 预热输入 | `en_us/dev` 按同样规则另取 1 条，不计入 100 条正式样本 |
| 当时的正式比较 | Nemotron EN 160/560 ms、Nemotron 3.5 320/560 ms、Kyutai 500 ms |

三轮重复使用同样 100 条音频，不是 300 条独立样本。旧报告的 Nemotron EN160 WER 为 7.68%；比较时必须沿用同一参考和标准化口径，不能用本轮可能重写的归一化方式直接宣称提升。

## 2. 远端当前情况

通过已有 Windows OpenSSH `guizhou` 入口登录，实际主机为 `d6-hpc-debuggpu-001`，用户根目录 `/hpc_stor03/sjtu_home/xuan.zhang`。

| 路径 | 本次检查结果 |
| --- | --- |
| `interclarify-asr-selection` | 存在 |
| `interclarify-asr-selection/dataset` | 不存在；原音频与 manifest 无法从此路径复用 |
| `interclarify-asr-selection/runs` | 不存在；旧运行目录不可直接复用 |
| `interclarify-asr-selection/models` | 存在；本次未重新校验权重 |
| `.cache/huggingface/hub/datasets--google--fleurs` | 不存在；默认 `.cache` 目录本身也不存在 |

登录 shell 未设置 `HF_HOME`、`HUGGINGFACE_HUB_CACHE`、`HF_HUB_CACHE` 或 `XDG_CACHE_HOME`。另在用户根目录做最多四层、15 秒超时的名称检查，跳过 models、envs、.git、node_modules 和 pkgs，未找到名称含 FLEURS 的路径或 `dataset.lock.json`。这不等于扫描了所有共享磁盘或任意深度缓存。

现有 `scripts/remote/cleanup_remote_assets.sh` 将旧 `dataset`、`runs` 列为清理目标，与本次现状一致。本次未找到文档所列的两份远端执行日志，因此只确认当前路径不存在，不以缺失日志证明具体删除时间。

## 3. 可以怎样恢复

历史准备脚本仍可从提交 `6c75f38d659998d6f149923085d82c0d7db267c5` 读取：

```bash
git show 6c75f38:scripts/remote/prepare_asr_selection.py
git show 6c75f38:docs/asr_selection_benchmark.md
```

该脚本读取固定版本的 `data/en_us/test.tsv` / `dev.tsv`，按文件名哈希选样，从对应音频归档提取，保存原始参考、数据集标准化参考、音频摘要与时长。因此具备按原规则重建同一批样本的依据。恢复时必须显式指定上表 revision；旧脚本在缺少 lock 时会解析当前远端 revision，不能不改版本固定逻辑就直接重跑。

若后续采用此集，应在远端 conda 环境中分阶段取得小型 TSV、生成选样清单，再估算音频归档下载/解包空间，受限下载并重建 manifest。旧 manifest 和音频哈希当前缺失，重建后须记录新哈希、核对 100/1 条及总时长，不能宣称已与原 manifest 逐文件验同。本次没有执行恢复。

## 4. 后续测试的适用边界

FLEURS 是朗读语音，适合固定同集比较转写 WER 与末端文本交付延迟。末端应通过独立对齐并核查真实发声结束，不能直接使用文件末尾静音。旧 WER 采用 `whisper-normalizer==0.1.12` 的 `EnglishTextNormalizer`；旧逐词延迟采用独立 CTC 对齐，不能与用户这次要求的平均末端延迟混称同一指标。

该集不自带 X2-Turn 的逐帧状态金标，也不足以直接验收自然对话中的用户附和/打断等类别。是否保留状态 Judger、补充哪些状态材料，应在新的实现计划中明确；本次只完成数据核查，不把旧 FDB 方案直接改名套用。

## 5. 证据位置

- 历史选样脚本及数据 revision：`git show 6c75f38:scripts/remote/prepare_asr_selection.py`、`git show 6c75f38:docs/asr_selection_benchmark.md`。
- 汇总口径与 100 条/969.26 秒/2,162 词：`git show f6ad9d9:docs/asr_selection_report.md` 第 3.2 节，以及同提交的 `reports/asr_selection/20261016-results/summary.md`。
- 远端检查为本次 SSH 只读会话，未在服务器写入资产或提交作业。
- 本次工作单：[X2Q-007](../../issue/archive/x2q/x2q_007_fleurs_verification.md)。旧 FDB 计划及工作单已取消，历史内容可从 Git 追溯。
