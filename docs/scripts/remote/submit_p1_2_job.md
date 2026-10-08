# `scripts/remote/submit_p1_2_job.sh`

## 作用

把 P1.2 实时双工链路作业提交到 SJTU 集群 `pdgpu-4090`（单卡 RTX 4090 跑官方控制模型 bf16；脚本化场景经无头客户端 + 虚拟播放 sink 运行，节点无需音频设备）。沿用 P1.1 作业的镜像与资源规格。

## 执行

```bash
bash scripts/remote/submit_p1_2_job.sh
vc list -j <JOBID>
vc logs -t <TASKID>
```

容器内执行 [run_p1_2_node_job.sh](run_p1_2_node_job.sh)。可通过环境变量覆盖：`P1_2_IMAGE`、`P1_2_JOB_NAME`、`P1_2_GPUS`、`P1_2_CPU`、`P1_2_MEM_G`、`INTERCLARIFY_ROOT`、`INTERCLARIFY_MODEL_ROOT`、`INTERCLARIFY_ARTIFACT_ROOT`。

## 前置（关键）

作业所在节点必须已有 Kyutai STT/TTS `moshi-server` 在 `127.0.0.1:31607/31608` 运行，否则节点脚本会以退出码 3 快速失败并指向任务单。部署方式见 [任务单 p1_2_live_link.md](../../../docs/jobs/p1_2_live_link.md)。
