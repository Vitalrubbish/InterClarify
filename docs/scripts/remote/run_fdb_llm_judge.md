# `scripts/remote/run_fdb_llm_judge.py`

## 功能与边界

对已有的 A4 FDB 输出树（`<subset>/<样本>/output.wav`）运行官方 FDB v1.0 的**对齐 + GPT judge**：

1. 对齐：`get_transcript/asr.py` 用 NeMo parakeet 产出与 `output.wav` 同名的 `output.json`（词级时间戳）。`user_interruption` 会先按 `interrupt.json` 的 `timestamp[1]` 裁掉打断结束点之前的音频。
2. 判题：`evaluation/evaluate.py --task user_interruption` 依据 `output.json` 计算 TOR、响应延迟，并用 OpenAI 兼容模型给"打断后回答"打 0–5 分。

脚本不改动上游 checkout：把 `v1_v1.5` 的 `get_transcript/` 与 `evaluation/` 复制到 `--out/fdb_repo`（官方两个入口只依赖这两个目录；上游 `node_modules` 含悬空符号链接且体积大，整树复制会失败且无必要），再按需替换 judge 模型名。它不生成音频、不评其它语义轴（那三条轴同样可用 `--task` 复用对齐步骤，判题段自动跳过）。

## 凭据处理

- 默认从项目根的 `openai_api.txt` 读取原始 key（文件内容即 key，可带换行）；未提供时可回退到环境变量 `OPENAI_API_KEY`。
- 通过子进程环境传递 `OPENAI_API_KEY` 与 `OPENAI_BASE_URL`（官方 `evaluate.py` 用 `OpenAI(api_key=...)`，SDK 自身识别 `OPENAI_BASE_URL`）。
- key 不写入日志、summary 或任何产物；日志只记录命令与官方输出。

## 类设计与核心方法

- `read_api_key`：按"文件优先、环境变量兜底"取 key，空文件视为缺失。
- `prepare_work_repo`：把 `v1_v1.5` 的 `get_transcript/` 与 `evaluation/` 复制到运行目录（保留符号链接、跳过悬空链接）；当 judge 模型不是官方默认 `gpt-4-turbo` 时，在工作副本里替换 `eval_user_interruption.py` 的 `MODEL_NAME`。
- `run_step`：执行一条官方命令，把 stdout/stderr 落到日志，返回退出码。
- `parse_scores`：从 judge 日志抓 `Average rating` / `Average take turn` / `Average latency`。
- `main`：串起对齐与判题，写 `llm_judge_summary.json`，并在对齐失败、判题失败或没有产出 `rating.json` 时返回非零。

## 用法

```bash
conda run --no-capture-output -n full-duplex-bench python scripts/remote/run_fdb_llm_judge.py \
  --root-dir data/runs/<tag>/fdb/user_interruption/synthetic_user_interruption \
  --out data/runs/<tag>/fdb_llm_judge --task user_interruption --gpus 0
```

主要参数：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--fdb-repo` | `/hpc_stor03/sjtu_home/xuan.zhang/Full-Duplex-Bench` | 上游 FDB checkout |
| `--root-dir` | 必填 | 含 `<样本>/output.wav` 的 FDB 子集输出目录 |
| `--out` | 必填 | 日志、`fdb_repo` 工作副本与 summary 的输出目录 |
| `--task` | `user_interruption` | 官方 `evaluate.py` 的任务名 |
| `--env` | `full-duplex-bench` | 提供 NeMo 的 conda 环境 |
| `--gpus` | `0` | 对齐阶段的 `CUDA_VISIBLE_DEVICES` |
| `--judge-model` | `gpt-4-turbo` | judge 模型；与官方默认一致时可保证口径可比 |
| `--base-url` | `https://api-2.xi-ai.cn/v1` | OpenAI 兼容端点 |
| `--skip-align` / `--skip-judge` | 关 | 分别复用已有 `output.json` 或只做对齐 |
| `--hf-online` | 关 | 默认 `HF_HUB_OFFLINE=1`，只用本地权重缓存 |

## 产物

- `align_<task>.log`、`judge_<task>.log`
- `llm_judge_summary.json`：任务名、FDB 上游 commit、judge 模型与端点、各阶段退出码、三条官方聚合指标、已产出 `rating.json` 与已对齐样本列表。
- 逐样本 `rating.json` 写在 FDB 输出树的对应样本目录内。

## 依赖与前置

- 环境须先用 [setup_fdb_scoring_env.sh](setup_fdb_scoring_env.md) 固定到 CUDA 12.x torch + NeMo 2.x，否则官方对齐脚本无法加载 parakeet 归档。
- 对齐需要 GPU；judge 只需网络与凭据。
- 官方 `eval_user_interruption.py` 的 `__main__` 漏传 `client` 参数，因此必须经 `evaluate.py` 调用，脚本已按此实现。
- **user site 必须启用**：`full-duplex-bench` 自身只装了 NeMo/torch/openai，`numpy`/`scipy`/`soundfile`/`tqdm`/`typing_extensions` 实际来自共享 user site（`~/.local/lib/python3.11/site-packages`）。节点镜像导出 `PYTHONNOUSERSITE=True` 会隐藏这些包，导致对齐（缺 `soundfile`）与评分（缺 `typing_extensions`）双双失败；调用方需 `unset PYTHONNOUSERSITE`，或按 setup 文档让环境自足。
- **`eval_backchannel.py` 依赖相对路径**：它读取 `./icc_gt_distribution.json`，因此 `evaluate.py --task backchannel` 必须从工作副本的 `evaluation/` 目录运行（该文件随 `evaluation/` 一起被复制）。以运行目录或 `$RUN_DIR` 作 cwd 会 `FileNotFoundError`。
- **judge 模型与口径**：官方 scorer 固定 `MODEL_NAME = "gpt-4-turbo"`（这也是默认）。端点若把它下架，可用 `--judge-model gpt-4o` 作平替——同为 GPT-4 系，且是上游 FDB 表对该列的命名；替换会改变评分口径，必须在结果里记录实际模型，且不与 `gpt-4-turbo` 轮次直接比较。`--skip-align` 复用已生成的 `output.json` 只补跑 judge；`gpt-4-turbo` 通道恢复后换回默认即可复现原口径。
