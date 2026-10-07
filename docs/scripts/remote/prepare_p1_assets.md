# `prepare_p1_assets.py`

## 文件作用

`scripts/remote/prepare_p1_assets.py` 在服务器端准备 P1.1 所需的 DuplexCascade 代码和模型资产。它读取 `configs/base.yaml` 与 `configs/cluster.yaml` 的固定版本，下载内容到共享模型目录，计算关键文件 SHA-256，并在共享产物目录写出机器可读清单。脚本不把模型文件写入仓库，也不记录 Hugging Face token。

## 主要流程

1. 合并 `cluster` 配置并记录配置摘要；
2. 在模型目录维护官方 DuplexCascade checkout，拒绝脏工作树，并切换到 `repo_commit`；
3. 使用服务器的 `HF_ENDPOINT` 和 Hugging Face 认证下载固定 `hf_revision`；
4. 检查 `model_state.safetensors`、`train_cfg.json` 和 `tokenizer/`；
5. 按 `train_cfg.json` 下载官方基础模型（可用 `--skip-base-model` 只做底座资产预取）；
6. 输出 `manifest.json`、`resolved_config.yaml`、`assets.env` 和失败时的 `failure.json`。

## 参数与路径

- `--repo-root`：GitHub checkout；默认读取 `INTERCLARIFY_ROOT`；
- `--model-root`：服务器共享模型目录；默认 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models`；
- `--artifact-root`：服务器共享证据目录；默认 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts`；
- `--run-id`：证据子目录名；不提供时使用 UTC 时间戳；
- `--dry-run`：只解析路径和版本，不访问网络；
- `--skip-base-model`：跳过 `train_cfg.json` 指定的基础模型，清单状态为 `PARTIAL`。

模型缓存位于 `<model-root>/huggingface`，DuplexCascade 源码位于 `<model-root>/duplexcascade/source`。脚本强制模型目录和证据目录位于仓库外，降低误把大文件写入 Git 工作树的风险。

## 清单字段

`manifest.json` 记录官方源码 URL 与提交、Hugging Face 仓库与 revision、权重文件大小和 SHA-256、`train_cfg.json` 摘要、基础模型配置摘要、配置 digest、主机和 HF endpoint。`token_value_recorded` 固定为 `false`；清单不会保存 token 内容。
