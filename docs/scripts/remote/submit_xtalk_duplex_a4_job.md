# `scripts/remote/submit_xtalk_duplex_a4_job.sh`

将 A4 节点入口提交到 `pdgpu-4090`，默认 round1 v0.3 镜像和 3 GPU / 24 CPU / 96G。必须先同步独立源码与清单；脚本只提交作业，不同步源码、不下载模型。

```bash
export INTERCLARIFY_DUPLEX_ROOT=/shared/xtalk-duplex-a4/current-snapshot
bash scripts/remote/submit_xtalk_duplex_a4_job.sh
```

`DUPLEX_A4_IMAGE/GPUS/CPU/MEM/JOB_NAME` 控制镜像和资源；其余已设置的 `DUPLEX_*`、`XTALK_*` 路径与配置由包装器以 shell 引用传递。提交日志写入 `artifacts/a4/submit_logs`；使用 `vc list -j <JOBID>`、`vc logs -t <TASKID>` 查看。
