# `scripts/remote/run_asr_contract_ab_node_job.sh`

## 功能与边界

在**单张 4090** 上对比 ASR 的流式契约，回答"`unfixed_chunk_num` 要不要与官方默认 2 对齐"。每臂只改解码窗口（`0` = 我们的配置、`2` = 官方默认），`unfixed_token_num` 固定 5；**不启服务、不占端口、不跑 LLM/duplex 运行时**。

关键事实：`asr-smoke --audio-dir` 在**本进程内**驱动官方流式 API，并且每条事件同时写下 raw 转写与"只暴露已定稿前缀"的转写。于是**每臂一次运行就能同时测两种暴露口径**：

| 口径 | 含义 |
| --- | --- |
| raw 转写 | 官方 demo 直接显示文本的做法，改写即模型替换已产出文本 |
| 已定稿前缀 | 我们交给运行时的那一份，改写必须为 0（append-only 契约） |

输入按**子集均衡**取样：`asr-smoke --audio-dir` 只取它遍历到的前 N 个 `input.wav`，那会全部落在字母序最前的子集，因此脚本先把每个子集的前 `ASR_AB_PER_SUBSET` 个样本以软链接形式汇集到 `data/runs/asr_contract_<tag>/inputs/<subset>__<sample>/input.wav`。**标签里必须带子集名**：smoke 把结果写在输入目录的 basename 下，而 FDB 的样本号在 5 个子集里重复，只用样本号会让各子集的样本互相覆盖（第一轮 40 个输入被覆盖成 14 个目录）。

## 输入（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INTERCLARIFY_ROOT` | 必填 | 同步后的源码根（提交脚本传入） |
| `XTALK_ROUND1_ROOT` / `XTALK_ROUND1_MODEL_ROOT` | 必填 | 参考资产目录 与 模型 snapshot 根 |
| `RUN_TAG` | UTC 时间戳 | 产物目录名 |
| `ASR_ENV` / `CLIENT_ENV` | `xtalk-round1-asr` / `xtalk-round1-client` | smoke 运行环境（smoke 会 import `qwen3_asr_service` 与模型，必须在 ASR 环境） |
| `ASR_AB_AUDIO_ROOT` | `/hpc_stor03/.../STS/data/fdb/v1_0` | FDB v1.0 语料根（按子集遍历 `input.wav`） |
| `ASR_AB_PER_SUBSET` | `8` | 每个子集取前多少个样本（共 5 个子集） |
| `ASR_AB_WINDOWS` | `0 2` | 要对比的 `unfixed_chunk_num` 列表 |
| `ASR_AB_TOKEN_NUM` | `5` | 固定的 `unfixed_token_num` |

## 产物

- `data/runs/asr_contract_<tag>/inputs/…`：均衡取样后的软链接树。
- `data/runs/asr_contract_<tag>/window-<n>/<subset>/<sample>/{asr_events.jsonl,asr_report.json}`：逐样本事件流（含 raw/可见文本、`rewritten`/`visible_rewritten`、到达时间）与报告。
- `data/runs/asr_contract_<tag>/logs/window-<n>.smoke.log`、`run.log`、`gpu.csv`、`source_check.txt`。
- `reports/asr_contract/<tag>/asr_contract.{md,json}`：由 `summarize_asr_contract.py` 生成的对照表与判据。

## 判定

- **可见改写必须为 0**：任一臂出现非 0 就说明该窗口不能直接给运行时用。
- 与 baseline（`window-0`）比**可见最终转写的词级距离中位数**：若 `window-2` 明显大于 0，说明官方窗口会改变最终交给模型的文本，此时再比较「提交延迟」（运行时晚多久拿到最终词）与「挂起的词」（音频结束时还扣着多少词）的代价来决定。
- 若两者最终距离都为 0、而 `window-2` 的提交延迟更大，则保持 `unfixed_chunk_num: 0`（当前配置）。
- 单臂可以单独跑（`ASR_AB_WINDOWS="0"` / `"2"`），两臂也可以各提交一个作业并行跑：产物目录按 `<tag>` 合并，最后在本地跑一次汇总器即可（首轮曾整容器被杀，分作业可降低风险）。

## 用法

```bash
INTERCLARIFY_DUPLEX_ROOT=$PWD XTALK_ROUND1_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1 \
XTALK_ROUND1_MODEL_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/models \
RUN_TAG=20261015T000000Z bash scripts/remote/submit_asr_contract_ab_job.sh
```

单臂可复用：`ASR_AB_WINDOWS="2" ASR_AB_PER_SUBSET=4 …`。
