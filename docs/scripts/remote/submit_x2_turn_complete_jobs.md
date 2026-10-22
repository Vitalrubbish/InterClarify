# X2-Turn 部署作业提交

无类。`scripts/remote/submit_x2_turn_complete_jobs.sh` 把 X2Q-010 的三个阶段提交到调度器：`setup` 与 `model` 是 CPU 作业，`deploy` 是单卡作业。脚本只提交、不等待、不自动重试，提交成功不等于阶段通过。

## 参数

| 变量 | 含义 |
| --- | --- |
| `X2_TURN_ROOT` | 固定实验根目录 |
| `X2_TURN_SOURCE` | 冻结的 InterClarify 源码检出 |
| `X2_TURN_STAGE` | `setup`、`model` 或 `deploy` |
| `X2_TURN_TAG` | 唯一运行标签，决定输出与提交日志名 |
| `X2_TURN_SOURCE_COMMIT` | 可选，默认取源码检出 HEAD |
| `X2_TURN_IMAGE` | 容器镜像，默认沿用现役 xtalk-round1 镜像 |
| `X2_TURN_GPU_PARTITION` | 默认 `pdgpu-4090`，可换同规格 24 GiB 分区 |
| `X2_TURN_CONDA_ENV` | conda 环境前缀，`model` 阶段用它调用 Python |
| `X2_TURN_SETUP_TIMEOUT` / `X2_TURN_MODEL_TIMEOUT` / `X2_TURN_DEPLOY_TIMEOUT` | 默认各 14400 秒 |
| `HF_ENDPOINT` | `model` 阶段下载入口，默认 `hf-mirror.com` |
| `X2_TURN_SMOKE_AUDIO` | 可选，传给 deploy 作业 |

## 资源与隔离

- `setup`：`pdcpu`，4 CPU、16 GiB、0 GPU；输出在 `ROOT/runs/<tag>/setup`。
- `model`：`pdcpu`，4 CPU、16 GiB、0 GPU；结果直接写入 `ROOT/models` 与 `ROOT/env`。
- `deploy`：单卡 24 GiB、8 CPU、32 GiB；输出在 `ROOT/runs/<tag>/deploy`。
- 提交日志为 `ROOT/logs/<tag>-<stage>.log`，已存在则拒绝覆盖，避免覆盖上一轮证据。

## 用法

```bash
export X2_TURN_ROOT=~/interclarify-x2-turn-complete
export X2_TURN_SOURCE=~/interclarify-x2-turn-complete/source/InterClarify-<commit>
for stage in setup model deploy; do
  X2_TURN_STAGE=$stage X2_TURN_TAG=deploy-20261022-r1 \
    bash "$X2_TURN_SOURCE/scripts/remote/submit_x2_turn_complete_jobs.sh"
done
```

三个阶段按顺序执行：`model` 依赖 `setup` 建立的 conda 环境与源码检出，`deploy` 依赖前两个阶段的锁和权重。提交后用 `vc list`、`vc logs` 与作业输出目录的 `exit_code.txt` 判断结果；失败时保留日志，不自动加卡或无限重试。
