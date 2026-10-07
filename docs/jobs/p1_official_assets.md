# 任务单：P1.1 官方 DuplexCascade 资产准备

## 目标

在远端 `pdgpu-4090` 环境完成 [engineering_implementation.md](../engineering_implementation.md) 第 5.2 节 P1.1 的前置工作：通过 GitHub 同步 InterClarify，固定官方 DuplexCascade 提交和 Hugging Face revision，在服务器共享存储下载并校验官方源码、适配器权重和基础模型。

权重不经过本地开发机，也不进入 Git。此任务只准备并核对资产；实时 ASR/TTS 服务和固定最小输入的推理运行在后续步骤执行。

## 固定版本与目录

| 项 | 值 |
| --- | --- |
| 项目分支 | `main` |
| 项目 GitHub | `https://github.com/Vitalrubbish/InterClarify.git` |
| 官方代码提交 | `42893024ca90c8de8ac3ed624467ebc123512ff8` |
| Hugging Face revision | `31c038ece2f006a28722dd60d1df3868fbb2cc42` |
| 模型目录 | `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models` |
| 证据目录 | `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts/p1_assets/<run-id>` |

## 服务器执行

以下命令在服务器登录节点或分配到的作业内执行。GitHub 私有仓库认证和 Hugging Face gated 权重认证由服务器已有凭据提供；不要把 token 放到命令行或提交到仓库。

```bash
export INTERCLARIFY_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/InterClarify
export INTERCLARIFY_GIT_URL=https://github.com/Vitalrubbish/InterClarify.git
export INTERCLARIFY_MODEL_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models
export INTERCLARIFY_ARTIFACT_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts

bash "$INTERCLARIFY_ROOT/scripts/remote/sync_from_github.sh"
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda run -n interclarify-dev python \
  "$INTERCLARIFY_ROOT/scripts/remote/prepare_p1_assets.py" \
  --repo-root "$INTERCLARIFY_ROOT" \
  --model-root "$INTERCLARIFY_MODEL_ROOT" \
  --artifact-root "$INTERCLARIFY_ARTIFACT_ROOT"
```

集群镜像若未预装 `interclarify-dev`，先运行 `bash scripts/remote/setup_env.sh`。集群配置默认使用 `HF_ENDPOINT=https://hf-mirror.com`；若镜像返回 gated 访问错误，先在服务器端完成 Hugging Face 登录并接受模型页面条件，再重试同一命令。

## 验收

1. `manifest.json` 的 `status=PASS`；
2. `source.commit` 等于固定官方提交；
3. `duplexcascade.revision` 等于固定 HF revision，且权重文件、`train_cfg.json` 和 tokenizer 均存在；
4. `duplexcascade.weight.sha256` 已记录，后续推理只使用该清单对应缓存；
5. `base_model.config` 存在，`assets.env` 可供官方 `server.py` 复用同一 HF 缓存；
6. 记录任务提交号、节点、证据路径和失败原因（若有）。

## 当前状态

本地脚本和任务单已准备，尚未在服务器下载模型。此前从本地直连 `js-hpc` 得到 SSH `Permission denied`；下一次执行应先把本提交推送到 GitHub，再在服务器按上面命令拉取。
