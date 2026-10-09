# `scripts/remote/submit_p0_job.sh`

## 作用

向 `pdgpu-4090` 队列提交 P0 验收作业。P0 不跑模型，默认只申请 1 张 GPU（仅用于证明固定环境能识别加速器）。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INTERCLARIFY_ROOT` | 共享存储仓库路径 | 传给容器内脚本 |
| `P0_IMAGE` | `.../sjtu_yukai-xuanzhang-interclarify-p0:v0.2` | 运行镜像 |
| `P0_JOB_NAME` | `interclarify-p0-env` | 作业名 |
| `P0_GPUS` | `1` | 每任务 GPU 数 |
| `P0_CPU_PER_GPU` | `8` | 每卡 CPU 配额 |
| `P0_MEM_PER_GPU_G` | `32` | 每卡内存（GB） |
| `INTERCLARIFY_ARTIFACT_ROOT` | 共享存储产物根 | 证据与提交日志位置 |

## 提交命令

```bash
bash scripts/remote/submit_p0_job.sh
```

脚本按 `vc submit` 约定拼装参数，把提交日志重定向到 `$ARTIFACT_ROOT/p0_env/logs_submit/submit.JOB.log`，并在容器内执行 [run_p0_node_job.sh](run_p0_node_job.md)。跟踪用 `vc list -j <JOBID>`、`vc logs -t <TASKID>`。
