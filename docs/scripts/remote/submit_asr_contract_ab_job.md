# `scripts/remote/submit_asr_contract_ab_job.sh`

## 功能与边界

把 [run_asr_contract_ab_node_job.sh](run_asr_contract_ab_node_job.sh) 提交到集群（默认 `pdgpu-4090`，单卡）。只做三件事：拼节点命令、转发 `XTALK_*`/`ASR_AB_*`/`RUN_TAG`/`ASR_ENV`/`CLIENT_ENV` 环境变量、用 `vc submit` 落地，并把提交日志写到 `data/runs/submit_logs/submit.asr_contract.<UTC>.log`。与其它提交脚本一致：**不转发名字以 `JOB_NAME` 结尾的变量**（`vc` 会把字面量 `JOB_NAME` 重写，导致节点命令被破坏）。

## 输入（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INTERCLARIFY_DUPLEX_ROOT` | 必填 | 同步后的源码根 |
| `DUPLEX_A4_IMAGE` | `sjtu_yukai-xuanzhang-xtalk-round1:v0.4` | 作业镜像（含 ASR 环境与模型） |
| `ASR_AB_JOB_NAME` | `xtalk-asr-contract` | 作业名 |
| `ASR_AB_GPUS` / `ASR_AB_CPU` / `ASR_AB_MEM` | `1` / `8` / `32G` | 资源 |
| `ASR_AB_PARTITION` | `pdgpu-4090` | 分区 |
| `RUN_TAG`、`ASR_AB_AUDIO_ROOT`、`ASR_AB_PER_SUBSET`、`ASR_AB_WINDOWS`、`ASR_AB_TOKEN_NUM` | 见节点脚本 | 直接透传 |

## 用法

```bash
INTERCLARIFY_DUPLEX_ROOT=$PWD XTALK_ROUND1_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1 \
XTALK_ROUND1_MODEL_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/models \
RUN_TAG=20261015T000000Z bash scripts/remote/submit_asr_contract_ab_job.sh
```
