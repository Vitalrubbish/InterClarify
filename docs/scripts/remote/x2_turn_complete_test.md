# X2-Turn FLEURS 固定子集准备与核验

`scripts/remote/x2_turn_complete_test.py` 的当前阶段负责恢复历史 ASR 选型使用的 FLEURS 英文子集，供后续 X2-Turn 实时回放、WER 与 complete 指标共用。脚本只恢复输入，不加载模型、不回放、不评分；后续工作单在同一入口增加回放与评分命令，避免重新启用旧 ASR 选型的缺省 revision 逻辑。

## 固定范围

- 数据集 `google/fleurs`，revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`，脚本不接受缺省最新版本。
- `en_us/test` 对音频文件名计算 SHA256，按哈希升序取前 100 条；`en_us/dev` 同规则取 1 条，仅用于预热，不计入正式 100 条。
- 校验历史总量：test 总时长 969.26 秒，原始参考经 `whisper-normalizer==0.1.12` 的 `EnglishTextNormalizer` 标准化后为 2,162 词。
- 音频按归档中的原始字节提取，不做重采样、声道转换或静音裁剪；头尾静音和原始采样率、声道、帧数写入 manifest。
- 旧 manifest 已缺失，因此本轮记录新哈希；报告明确不宣称与原 manifest 逐文件验同。

## 使用

远端使用独立 conda 环境 `~/miniconda3/envs/interclarify-x2-turn-data`（Python 3.11、`whisper-normalizer==0.1.12`、`soundfile`、`huggingface_hub`），运行前设置 `PYTHONNOUSERSITE=1`，避免用户级 site-packages 混入版本。

```bash
PYTHONNOUSERSITE=1 ~/miniconda3/envs/interclarify-x2-turn-data/bin/python \
  scripts/remote/x2_turn_complete_test.py prepare-data \
  --root ~/interclarify-x2-turn-complete
```

重新核验已恢复数据：

```bash
PYTHONNOUSERSITE=1 ~/miniconda3/envs/interclarify-x2-turn-data/bin/python \
  scripts/remote/x2_turn_complete_test.py verify-data \
  --root ~/interclarify-x2-turn-complete
```

`prepare-data` 默认使用 `https://hf-mirror.com`，因为远端计算节点不能直连 `huggingface.co`。实际 endpoint 写入数据锁和报告；可用 `HF_ENDPOINT` 或 `--endpoint` 覆盖。revision 始终固定，镜像只改变下载入口。

## 类与核心方法

`DatasetPreparer` 管理一次恢复过程：

- `check_capacity`：启动前要求工作盘至少有 100 GiB 空闲；写入前、后容量统计。
- `fetch_source`：按固定 revision 下载 `en_us/test.tsv`、`dev.tsv` 及两个音频归档，记录缓存路径、字节数、SHA256 和下载耗时。
- `read_tsv` / `select_rows`：校验 7 列 TSV 和音频文件名，按 `SHA256(filename)` 升序选样并保留选择键。
- `extract`：只从归档读取被选 WAV，先写 `.part` 再原子替换；删除同目录中不属于本轮选样的旧 WAV，避免 test/dev 混淆。
- `build_sample`：计算音频摘要，读取声道、采样率、帧数和时长，同时保存原始参考、数据集标准化参考与固定 normalizer 的标准化参考。
- `check_expectations`：核对 100/1 条、test 总时长和标准化词数；任何一项不一致都失败退出，不静默补样本。
- `prepare`：串联容量预检、下载、选样、提取、manifest/lock/报告写入和独立复核。

`verify_manifest` 不需要重新下载：逐条核对文件存在、音频 SHA256、声道/采样率/帧数/时长、normalized 词数、test 与 dev 路径边界、实际 WAV 集合和汇总数。`load_english_normalizer` 强制检查安装版本为 `0.1.12`。

## 输出

`--root` 下只写 `dataset/fleurs_en_us`：

```text
dataset/fleurs_en_us/
├── audio/test/*.wav          # 100 条正式输入
├── audio/dev/*.wav           # 1 条预热输入
├── source/en_us/*.tsv        # 固定 revision 的小型文本副本
├── dataset.lock.json         # revision、endpoint、源文件摘要与选样规则
├── manifest.json             # 逐例参考、音频元数据、摘要与汇总
├── prepare_events.jsonl      # 下载、选样、提取、容量事件
└── prepare_report.json       # 成功状态、容量统计与复核结果
```

`prepare_report.json` 分开记录数据目录、下载源文件与合计资产字节，三者都受整轮 70 GiB 预算约束。Git 只保存脚本、测试和说明，不保存音频、归档或远端 manifest。正式 WAV 和事件日志留在远端。

## 资源与边界

- 下载串行执行，并发 1（低于允许的 2）；设置不超过 4 CPU、16 GiB RAM。音频资产计入整轮 70 GiB 预算，启动空闲盘要求至少 100 GiB。
- 本阶段不使用 GPU，不提交 X2-Turn 推理作业，不产生 WER 或 complete 结果。
- 固定 normalizer 版本只用于核对参考词数；后续 WER 也必须复用同一版本，不能用其他版本补足差异。
