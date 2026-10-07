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

退出码聚合三类结果，任一失败即非零，作业不会在冒烟失败时仍报 `Completed`：

1. `check_env.py --require-gpu` 的退出码（环境缺依赖或不可见 CUDA）；
2. 两次 `run_p0_smoke.py` 的退出码；
3. 冒烟一致性内联校验：两次运行的事件类型序列与 `metrics.json` 必须相同，否则失败。

`check_audio_io.py` 为信息性探测（headless 允许 `NO_DEVICES`），不计入失败。脚本末尾把三类返回码合并为最终退出码并写入 `run.log`。
