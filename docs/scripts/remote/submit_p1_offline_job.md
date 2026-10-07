# `scripts/remote/submit_p1_offline_job.sh`

## 作用

把 P1.1 离线样例提交到 `pdgpu-4090`（单卡）。Qwen2-7B + LoRA 以 bf16 载入约 17GB，单张 4090（24GB）足够；官方 `server.py` 默认 fp32 不适用单卡。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INTERCLARIFY_ROOT` | `…/InterClarify` | 共享存储仓库 |
| `INTERCLARIFY_MODEL_ROOT` | `…/interclarify-p0-models` | 权重与 tokenizer |
| `INTERCLARIFY_ARTIFACT_ROOT` | `…/interclarify-p0-artifacts` | 运行产物 |
| `P1_OFFLINE_IMAGE` | `…/interclarify-p0:v0.2` | 运行镜像 |
| `P1_OFFLINE_JOB_NAME` | `interclarify-p1-offline` | 作业名 |
| `P1_OFFLINE_GPUS` / `P1_OFFLINE_CPU` / `P1_OFFLINE_MEM_G` | `1` / `8` / `64` | 资源 |

## 使用

```bash
bash scripts/remote/submit_p1_offline_job.sh
vc list -j <JOBID>
vc logs -t <TASKID>
```

提交日志：`$ARTIFACT_ROOT/p1_offline/logs_submit/submit.JOB.log`。
