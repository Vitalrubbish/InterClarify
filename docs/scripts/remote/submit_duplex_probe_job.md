# `scripts/remote/submit_duplex_probe_job.sh`

## 功能与边界

本地入口：把一个**单 GPU**的 marker 探针作业提交到 `pdgpu-4090` 分区。只负责拼环境变量并调用 `vc submit`；实际工作由 [run_duplex_probe_node_job.sh](run_duplex_probe_node_job.sh) 执行。

## 关键环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `INTERCLARIFY_DUPLEX_ROOT` | 必填 | 同步后的源码目录，同时决定节点侧脚本路径 |
| `DUPLEX_PROBE_SAMPLE_ROOT` | 必填（传递） | 被重放的录制样本目录 |
| `DUPLEX_PROBE_IMAGE` | 复用 `DUPLEX_A4_IMAGE` | 镜像 |
| `DUPLEX_PROBE_JOB_NAME` | `xtalk-duplex-marker-probe` | 作业名 |
| `DUPLEX_PROBE_GPUS` / `_CPU` / `_MEM` | `1` / `8` / `32G` | 资源申请（单 GPU 作业上限为 8 CPU / 32G） |

`DUPLEX_*` 与 `XTALK_ROUND1*` 前缀的环境变量会被整体转发到节点（`DUPLEX_PROBE_TAG`、`DUPLEX_PROBE_VARIANTS`、`DUPLEX_PROBE_CLOCK` 等据此生效）。

## 用法

```bash
export INTERCLARIFY_DUPLEX_ROOT=/mnt/cloudstorfs/sjtu_home/xuan.zhang/InterClarify
export DUPLEX_PROBE_SAMPLE_ROOT=$INTERCLARIFY_DUPLEX_ROOT/data/runs/<a4-tag>/fdb/user_interruption/synthetic_user_interruption
export DUPLEX_PROBE_SAMPLES=1,10,100,101,102
bash scripts/remote/submit_duplex_probe_job.sh
```

提交日志落在 `data/runs/submit_logs/submit.probe.<UTC>.log`。查询与取日志用 `vc list` / `vc logs`。
