# `run_p1_assets_node_job.sh`

## 文件作用

P1.1 资产准备作业的容器内入口。它在集群节点上调用 [prepare_p1_assets.py](../../../scripts/remote/prepare_p1_assets.py)，下载并校验官方源码、gated DuplexCascade 权重和基础模型，并把日志写到共享存储。

## 关键行为

- 环境变量：`INTERCLARIFY_ROOT`（默认 `/opt/interclarify`）、`INTERCLARIFY_MODEL_ROOT`、`INTERCLARIFY_ARTIFACT_ROOT`、`IC_HF_TOKEN_FILE`、`IC_PYTHON`、`HF_ENDPOINT`；
- `HF_ENDPOINT` 默认 `https://hf-mirror.com`，`PYTHONNOUSERSITE=True`；
- Hugging Face token 从 `HF_TOKEN` 或 `IC_HF_TOKEN_FILE`（默认 `$INTERCLARIFY_ROOT/hf_token.txt`，已被 `.gitignore` 排除）读取，**不写入命令行或证据文件**；
- 缺少 token 时立即以退出码 2 失败，不发起下载；
- 用镜像内的 `interclarify-dev` 解释器运行，脚本 rc 通过管道透传，写 `logs_submit/node.<UTC>.log`。

## 为什么用作业而不是登录节点后台进程

登录节点上用 `nohup`/`screen` 启动的长下载会被交互式会话的进程组清理中断；`vc submit` 交作业后进程独立于登录会话，可安全运行数小时，并可断点续传（`huggingface_hub` 会复用 `.incomplete` 分块）。
