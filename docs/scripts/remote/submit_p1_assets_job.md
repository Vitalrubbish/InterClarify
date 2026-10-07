# `submit_p1_assets_job.sh`

## 文件作用

把 P1.1 资产准备作业提交到 SJTU 集群。任务只做下载与哈希，因此默认提交到 CPU 队列 `pdcpu`，不占用 GPU、也不触发 GPU 利用率看门狗。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INTERCLARIFY_ROOT` | `/hpc_stor03/sjtu_home/xuan.zhang/InterClarify` | 共享存储仓库 |
| `INTERCLARIFY_MODEL_ROOT` | `…/interclarify-p0-models` | 模型与源码目录 |
| `INTERCLARIFY_ARTIFACT_ROOT` | `…/interclarify-p0-artifacts` | 证据与日志目录 |
| `P1_IMAGE` | `…/interclarify-p0:v0.2` | 运行镜像 |
| `P1_JOB_NAME` | `interclarify-p1-assets` | 作业名 |
| `P1_PARTITION` | `pdcpu` | 队列 |
| `P1_CPU_PER_TASK` / `P1_MEM_PER_TASK_G` | `4` / `16` | 每任务资源 |

## 使用

```bash
bash scripts/remote/submit_p1_assets_job.sh
vc list -j <JOBID>
vc logs -t <TASKID>
```

提交日志写入 `$ARTIFACT_ROOT/p1_assets/logs_submit/submit.JOB.log`。
