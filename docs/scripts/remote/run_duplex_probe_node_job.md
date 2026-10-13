# `scripts/remote/run_duplex_probe_node_job.sh`

## 功能与边界

节点侧入口：在**单张 GPU** 上启动官方权重的对话模型服务，等 `/health` 就绪后跑
[probe_duplex_markers.py](probe_duplex_markers.md)，最后把紧凑证据复制到报告目录。

只做"模型服务 + 纯文本重放"，不启动 ASR/TTS，不跑回归，不产出音频，因此不构成验收步骤，也不写 `steps.jsonl`。

## 关键环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `INTERCLARIFY_DUPLEX_ROOT` | 必填 | 同步后的源码目录 |
| `DUPLEX_PROBE_SAMPLE_ROOT` | 必填 | 含 `<样本>/a4_report.json` 的目录（如某次 A4 run 的 FDB 子集输出） |
| `DUPLEX_PROBE_SAMPLES` | 空（全部） | 逗号分隔的样本名 |
| `DUPLEX_PROBE_VARIANTS` | `raw,strip,strip_lower` | 变体列表 |
| `DUPLEX_PROBE_REPEATS` | `1` | 每个样本/变体重跑次数，用于检测同一输入下解码是否稳定 |
| `DUPLEX_PROBE_CLOCK` | `grid` | 时钟模式 |
| `DUPLEX_PROBE_TAG` | UTC 时间戳 | 输出目录名 |
| `DUPLEX_PROBE_OUTPUT` | `data/runs/duplex_marker_probe/<tag>` | 原始产物目录（已存在则退出 2） |
| `DUPLEX_PROBE_REPORT_DIR` | `reports/duplex_marker_probe/<tag>` | 归档目录 |
| `DUPLEX_MODEL_ENV` / `DUPLEX_CLIENT_ENV` | `interclarify-dev` / `xtalk-round1-client` | 模型服务与探针所在环境 |

## 流程

1. 校验 checkpoint、base model 与 `DUPLEX_PROBE_SAMPLE_ROOT` 存在。
2. `CUDA_VISIBLE_DEVICES=<第一张卡>` 启动 `duplex_model_service.py`，日志落 `services/duplex_model.log`；`wait_http` 轮询 `/health`（上限 1800s，日志出现 Traceback 即失败）并保存 `model_health.json`。
3. 跑探针，stdout 落 `probe.log`。
4. 复制 `duplex_marker_probe.json`、`duplex_marker_probe.summary.json`、`model_health.json`、`probe.log` 到归档目录；退出码即探针退出码。
5. `trap` 里按进程组停止服务。

## 产物

- `data/runs/duplex_marker_probe/<tag>/`：完整逐拍结果、`duplex_marker_probe.summary.json`、服务日志、`run.log`。
- `reports/duplex_marker_probe/<tag>/`：紧凑归档（入库）。

## 依赖与前置

- 单卡即可；模型为 bf16 的 7B + LoRA，峰值显存约 16.5 GiB，11 GiB 的卡放不下。
- 探针输入是**已录制**的 `a4_report.json`，所以必须先用 [run_xtalk_duplex_a4_node_job.sh](run_xtalk_duplex_a4_node_job.sh) 产出一次 FDB 推理。
