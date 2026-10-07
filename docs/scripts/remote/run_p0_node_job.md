# `scripts/remote/run_p0_node_job.sh`

## 作用

在集群容器内执行 P0 验收：运行环境检查、音频探测与两次相同配置的回放冒烟，把全部证据写入共享存储，便于从开发机直接验收。

## 证据目录

```text
$INTERCLARIFY_ARTIFACT_ROOT/p0_env/<UTC 时间戳>/
├── environment.txt     # check_env.py（require-gpu）报告
├── env.json            # 机器可读环境报告
├── audio_io.json       # 音频设备探测（headless => NO_DEVICES）
├── smoke/              # p0-smoke-a 与 p0-smoke-b 两次运行
├── nvidia-smi.txt
├── git.txt             # 提交与工作树状态
└── run.log
```

## 环境变量

`INTERCLARIFY_ROOT`（默认 `/opt/interclarify`）、`INTERCLARIFY_ARTIFACT_ROOT`、`IC_RUN_TAG`、`IC_PYTHON`（默认 `/opt/conda/envs/interclarify-dev/bin/python`）。脚本将 `HF_ENDPOINT` 默认设为 hf-mirror，并设置 `PYTHONNOUSERSITE=True`、`PYTHONPATH=$REPO_ROOT/src`。

## 退出码

以环境检查的退出码收尾：环境不完整或（要求 GPU 时）无 CUDA 设备则非零，作业视为未通过。
