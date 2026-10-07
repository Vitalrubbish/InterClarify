# `prepare_p1_assets.py`

## 文件作用

`scripts/remote/prepare_p1_assets.py` 在服务器端准备 P1.1 所需的 DuplexCascade 代码和模型资产。它读取 `configs/base.yaml` 与 `configs/cluster.yaml` 的固定版本，下载内容到共享模型目录，计算关键文件 SHA-256，并在共享产物目录写出机器可读清单。脚本不把模型文件写入仓库，也不记录 Hugging Face token。

## 主要流程

1. 合并 `cluster` 配置并记录配置摘要；
2. 在模型目录维护官方 DuplexCascade checkout，拒绝脏工作树，并切换到 `repo_commit`；若当前已处于目标提交且工作树干净则跳过网络 fetch（计算节点可能无法访问 GitHub，登录节点预置的 clone 仍可复用）；
3. 按 `--provider` 选择下载来源：
   - `huggingface`：用服务器的 `HF_ENDPOINT` 与 Hugging Face 认证下载固定 `hf_revision`；
   - `modelscope`（集群默认）：从 ModelScope 镜像下载，逐个文件按清单 SHA-256 校验，并用 `configs/base.yaml` 的 `duplexcascade.weight_sha256` 证明权重与固定 HF revision 逐字节一致；支持 HTTP Range 断点续传，`README.md`/`.gitattributes`/`configuration.json`/`LICENSE` 等元数据文件失败只告警不中断；
4. 检查 `model_state.safetensors`、`train_cfg.json` 和 `tokenizer/`；
5. 按 `train_cfg.json` 下载官方基础模型（可用 `--skip-base-model` 只做底座资产预取）；
6. 输出 `manifest.json`、`resolved_config.yaml`、`assets.env` 和失败时的 `failure.json`。

## 参数与路径

- `--repo-root`：GitHub checkout；默认读取 `INTERCLARIFY_ROOT`；
- `--model-root`：服务器共享模型目录；默认 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models`；
- `--artifact-root`：服务器共享证据目录；默认 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts`；
- `--run-id`：证据子目录名；不提供时使用 UTC 时间戳；
- `--provider`：`huggingface` 或 `modelscope`；默认读 `IC_ASSET_PROVIDER`，缺省 `huggingface`；
- `--dry-run`：只解析路径和版本，不访问网络；
- `--skip-base-model`：跳过 `train_cfg.json` 指定的基础模型，清单状态为 `PARTIAL`。

模型缓存位于 `<model-root>/huggingface`（HF）与 `<model-root>/modelscope`（镜像）；DuplexCascade 源码位于 `<model-root>/duplexcascade/source`。脚本强制模型目录和证据目录位于仓库外，降低误把大文件写入 Git 工作树的风险。

## 清单字段

`manifest.json` 记录 `provider`、官方源码 URL 与提交、Hugging Face 仓库与 revision、权重文件大小和 SHA-256、`train_cfg.json` 摘要、基础模型配置摘要、配置 digest、主机和 HF endpoint。使用 `modelscope` 时额外记录 ModelScope 的 `revision`（提交）、`equivalent_hf_revision` 与权重 `matches_pinned_sha256=true`。`token_value_recorded` 固定为 `false`；清单不会保存 token 内容。

## 为什么提供 ModelScope 路径

集群到 `hf-mirror` 的连接实测约 0.1–1.5 MB/s 且大文件常中断（`ChunkedEncodingError`），而 ModelScope CDN 约 9–10 MB/s 且支持 Range。两者权重内容 SHA-256 相同（`603070a3…`），因此用 ModelScope 加速不改变固定底座。
