# `scripts/remote/submit_tts_throughput_ab_job.sh`

## 功能与边界

把 `run_tts_throughput_ab_node_job.sh` 提交到 `pdgpu-4090`：**单卡 8 CPU / 32G**（MOSS x-talk 单 GPU 任务的上限口径），镜像与 A4 验收一致（`sjtu_yukai-xuanzhang-xtalk-round1:v0.3`）。只做提交与日志落盘，不改变节点脚本行为。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INTERCLARIFY_DUPLEX_ROOT` | 必填 | 同步后的源码根，作为节点上的工作目录 |
| `DUPLEX_A4_IMAGE` | `…xtalk-round1:v0.3` | 与 A4 验收共用镜像 |
| `TTS_AB_JOB_NAME` | `xtalk-tts-throughput` | 作业名 |
| `TTS_AB_GPUS` / `TTS_AB_CPU` / `TTS_AB_MEM` | `1` / `8` / `32G` | 资源 |
| `XTALK_*`、`TTS_AB_*`、`RUN_TAG`、`MOSS_ENV`、`CLIENT_ENV`、`TTS_PORT` | – | 透传给节点脚本 |

## 注意

- 提交日志落在 `data/runs/submit_logs/submit.tts_throughput.<UTC>.log`，作业名与环境变量决定可比性；同一 tag 复用会覆盖 `reports/tts_throughput/<tag>/`。
- 不要 `export` 以 `JOB_NAME` 结尾的变量（`vc` 会把它替换成作业名占位符，损坏节点命令）。
