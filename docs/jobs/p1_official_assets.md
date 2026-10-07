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

1. `manifest.json` 的 `status=PASS`、`provider` 已记录（本任务用 `modelscope`）；
2. `source.commit` 等于固定官方提交 `4289302…`；
3. DuplexCascade 权重、`train_cfg.json` 和 tokenizer 均存在；
4. `duplexcascade.weight.sha256` 等于 `configs/base.yaml` 的 `weight_sha256`，且 `matches_pinned_sha256=true`；`modelscope.equivalent_hf_revision` 等于固定 HF revision；后续推理只使用该清单对应缓存；
5. `base_model.config` 存在，`assets.env` 可供官方 `server.py` 复用同一权重快照；
6. 记录任务提交号、节点、证据路径和失败原因（若有）。

## 集群作业方式

登录节点上的后台下载会被交互式会话清理中断，因此资产下载改为 `vc` 作业执行（见 [submit_p1_assets_job.sh](../../scripts/remote/submit_p1_assets_job.sh)）：

```bash
IC_ASSET_PROVIDER=modelscope bash scripts/remote/submit_p1_assets_job.sh   # 默认 pdcpu，4 CPU / 16G
vc list -j <JOBID>
vc logs -t <TASKID>
```

node 脚本默认 `IC_ASSET_PROVIDER=modelscope`：从 ModelScope 镜像按 SHA-256 校验下载（快、支持断点续传），不需要 token；仅当改用 `huggingface` 时才从 `INTERCLARIFY_ROOT/hf_token.txt`（已 gitignore）读取 token，且不放到命令行或证据里。

## 执行结果（2026-10-07）

| 项 | 值 |
| --- | --- |
| 作业 | `job-179138059345760136585-xuan-zhang`（Completed，rc=0） |
| 节点 | `d6-hpc-cpu-015`（`pdcpu`） |
| 提交 | 见仓库 `main`；镜像 `…/interclarify-p0:v0.2` |
| 证据 | `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts/p1_assets/20261007T134316Z/` |

`manifest.json` 核对：

```text
status=PASS, provider=modelscope
source.commit=42893024ca90c8de8ac3ed624467ebc123512ff8
duplexcascade.revision=c3dd51ce9a5a7d27f810ffd5dab309f132a94d28
duplexcascade.equivalent_hf_revision=31c038ece2f006a28722dd60d1df3868fbb2cc42
duplexcascade.weight.bytes=17419657672
duplexcascade.weight.sha256=603070a3…  matches_pinned_sha256=true
duplexcascade.tokenizer_files=6
base_model.repo_id=Qwen/Qwen2-7B-Instruct  revision=8dce1f8a2d3286a7adf09b977e661350ad67e40a
base_model.config.sha256=8b9a4f6c…
```

验收清单第 1–6 项全部满足。资产位于共享存储：

- 官方源码：`interclarify-p0-models/duplexcascade/source`（固定提交 `4289302`）；
- DuplexCascade 快照：`interclarify-p0-models/modelscope/sbintuitions--DuplexCascade/c3dd51ce…`；
- 基础模型：`interclarify-p0-models/modelscope/Qwen--Qwen2-7B-Instruct/8dce1f8a…`；
- 环境导出：`…/20261007T134316Z/assets.env`。

> 说明：`hf-mirror` 路径在本集群不可用（约 0.1–1.5 MB/s 且大文件中断），改用 ModelScope 镜像；权重 SHA-256 与固定 HF revision 的 LFS blob 名一致，故内容等价。下一次 P1.1 步骤是“固定最小输入的官方推理适配”。

## 历史记录

早期作业 `job-179137597372421357871-xuan-zhang`（HF 直连）、`job-179137679109398113880-xuan-zhang`（GitHub fetch）和 `job-179137696446759664545-xuan-zhang`（Qwen README 元数据中断）均失败，仅作排障参考，不改变上面结论。

