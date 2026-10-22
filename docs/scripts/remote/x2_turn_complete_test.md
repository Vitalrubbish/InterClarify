# X2-Turn FLEURS 数据、实时回放与独立评分

`scripts/remote/x2_turn_complete_test.py` 的当前阶段负责恢复历史 ASR 选型使用的 FLEURS 英文子集，供后续 X2-Turn 实时回放、WER 与 complete 指标共用。冻结数据入口保持原有行为；新增 `replay`、`score-asr` 与 `score-complete` 入口，共用一批客户端原始 trace。脚本不加载权重，通过固定版本服务的 WebSocket 接口输入音频。

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
- 数据准备与离线评分不使用 GPU；回放只能连接远端受限推理作业，不在登录节点启动模型。
- 数据核验和 WER 共用固定 normalizer，不能用其他版本补足词数差异。


## 回放入口与合同

X2Q-011—013 已实现；X2Q-014 已于 2026-10-22 完成真实模型测试。回放与评分客户端仍由本脚本提供，单作业编排与提交分别由 `run_x2_turn_complete_job.sh` 和 `submit_x2_turn_complete_jobs.sh` 负责，说明见同目录同名文档。回放 Python 环境需要 `soundfile`、`websockets` 和 `whisper-normalizer==0.1.12`，推荐在冻结数据的独立 conda 环境补装 `websockets`，并保存 `pip freeze`；不要为回放重新恢复数据。模型所在环境与回放客户端可以独立。

在远端已由调度作业启动并核验有效 delay=480 ms 的服务后执行：

```bash
python scripts/remote/x2_turn_complete_test.py replay \
  --root /hpc_stor03/sjtu_home/xuan.zhang/interclarify-x2-turn-complete \
  --run-id formal-r1 --mode formal --url ws://127.0.0.1:18011/v1/realtime
python scripts/remote/x2_turn_complete_test.py score-asr \
  --run /hpc_stor03/sjtu_home/xuan.zhang/interclarify-x2-turn-complete/runs/formal-r1
python scripts/remote/x2_turn_complete_test.py score-complete \
  --run /hpc_stor03/sjtu_home/xuan.zhang/interclarify-x2-turn-complete/runs/formal-r1
```

以上 `python` 应为独立 conda 环境的解释器。`--mode dev` 固定 1 条 dev，`smoke` 固定前 5 条 test，`formal` 固定全部 100 条 test；每次使用新的 `run_id`。预热与冒烟报告的正式样本数为 0。连接/样本失败后继续后续计划样本，整轮有失败则 CLI 退出码为 1。启动先只读复核冻结 manifest 和全部音频，不改写 X2Q-009 资产。

`StreamingReplay` 每条录音独立会话、batch=1，`run` 并行运行 `send_audio` 与 `receive`：

- `read_replay_audio` 接受冻结的单声道 16 kHz WAV，PCM16、PCM24 与 IEEE float 编码均可读；不重采样、不裁剪。浮点样本按 ×32768 四舍五入并裁剪到 int16，与部署阶段协议诊断的转换一致。块在所含采样按源时钟到齐后发送，完整块为 80 ms，文件末块保留原长度。因此计划文件末端为起点加原始采样时长。
- 每块发送 append 与非 final commit，最后一个原始块的发送完成时刻为 `t_end`。随后按同样时钟发送恰好 80,000 个静音采样，最后一个块为 40 ms，不通过快速上传提前完成尾窗。
- `receive` 在解析 JSON、写日志前打客户端 monotonic 接收时戳，保存原始 payload（含全部状态、ID、概率）、累计文本与 UTC。发送等待期间接收持续运行，文本不受状态门控。
- `window_end=t_end+5`；所有静音发完才记完整观察。`t_eof` 是 final commit 请求前的时刻，`t_eof_sent` 是发送完成时刻，`t_done` 是 `transcription.done` 接收时刻。按请求时刻切开 EOF 阶段，避免发送过程中收到的响应被当成在线输出。
- final commit 后独立排空最多 60 秒。收到 done 后采用其完整 text；正常空文本仍为成功会话。提前 done、断连、服务错误、非法 JSON、超时分别记失败；已观察的事件不丢弃。整条还受音频时长加 120 秒的外层超时约束。

## Trace 与离线重算

`runs/<run_id>/run.json` 固定模式、计划样本、80 ms、5 秒和 60 秒参数以及原 manifest 的 SHA256；`manifest.json` 是冻结输入的逐字节副本，参考文本只用于客户端离线评分，不发送给模型。每条记录为 `000.json` 等，包含输入、静音逐块的 deadline、实际发送起止、迟到，所有接收事件、关键时刻、在线/最终文本、错误与退出码。

`000.jsonl` 等是边运行边 flush 的事件日志，用于审计进程异常退出；独立评分读取最终 JSON。运行开始先为所有计划输入写失败占位，进程被终止时未完成样本仍留在分母，部分原始观测可从 journal 人工恢复审计，不将未完成占位当成完整未命中。输出目录存在即拒绝执行，评分只重写各自派生报告，不修改原 trace。

在线文本按 `received <= window_end` 且早于 EOF 的接收记录确定；即使发送迟到使实际 EOF 晚于计划窗末，也不把窗外文本纳入在线值。输出序列包含原始状态帧，不平滑、不增加连续确认、状态 Judger 或控制器。

回放串行，一次只读一条音频。每个服务帧限制 2 MiB，日志写入计入整轮 5 GiB 结果预算并预留最终 trace 副本空间，超限记失败。远端 CPU/内存、资产≤70 GiB、启动空闲盘≥100 GiB、服务资源峰值及调度限制仍由作业入口和 X2Q-014 统一执行。

## ASR 评分方法

`score_asr` 独立于 complete：原始参考和 EOF 排空后的最终文本用固定 `EnglishTextNormalizer` 标准化。`score_run` 重算全部 test 参考词数，必须为 2,162，且冻结 normalizer 元数据必须匹配版本。`word_errors` 用确定性的 Levenshtein 动态规划计算 S/D/I，等代价依次选替换、删除、插入；语料 WER 汇总错误数后除以可评分参考词数，正常空输出计删除，运行失败的错误数和 WER 为 null。

`lexical_text` 用 Unicode 标点删除、大小写和空白统一识别词汇变化，避免标点 delta 延后时间。末端延迟为窗内、EOF 前最后一次词汇变化接收时刻减 `t_end`，允许负值；空输出或失败为 null。`score_asr` 另保存 EOF 后词汇更新的实际接收时间、距 EOF/文件末端的耗时，以及最终词汇文本是否不同于在线文本。

`asr_scores.json` 保存逐例参考、最终假设、S/D/I、在线文本、文本延迟和 EOF 更新；汇总提供计划数、计划参考词数、可评分覆盖、失败、可评分语料分母、末端延迟均值/P50/P95/有效数及 EOF 补齐统计。`distribution` 使用线性插值计算分位数，空集合为 null。EOF 更新保留失败样本的已有观测，不能将这些诊断当成成功完成。

## complete 评分方法

`score_complete` 只读取原生 `turn.delta`，严格检查六类 ID 与标签对应；异常帧保留为协议异常且不命中。只有 ID38 / `turn_end` 在闭区间 `[t_end, t_end+5]` 内、EOF 前实际收到才命中，重复帧不增加样本命中数，首次接收时刻决定延迟。

`complete_scores.json` 主比例使用全部计划样本；成功回放条件比例另报。协议异常使 complete 的 `replay_ok` 为 false，`runtime_failed` 单独统计运行退出失败。部分观察中已收到的合法命中保留，但窗口未观察完整、运行失败与协议异常分别留账；未完成窗口的“完整窗无命中”字段为 null。提前、仅 EOF 后、全程未观察到 complete、窗外事件均留账；输入前后都有帧时仍可命中，不要求状态转换。

未命中延迟为 null；汇总仅对命中样本计算条件均值/P50/P95/最大值和命中数，同时展示输出率、各类失败与窗口完整数。这些是文件输入末端输出指标，不是状态准确率或系统实际接话成功率；文本延迟须与 WER 一起解释，也不称真实发声末端延迟。

验证方法见 [测试说明](../../tests/test_x2_turn_complete_test.md)。
