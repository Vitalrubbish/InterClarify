# `scripts/remote/setup_xtalk_round1_env.sh`

## 整体作用

在允许下载与安装的节点完成首轮模型服务验收的准备工作：创建 round-one 根目录，克隆并固定四份源码仓库，创建四个 conda 环境并安装各自的依赖（LLM 与 turn detector 复用镜像 base 环境，无需创建）。脚本幂等：已有 checkout 必须已经处于固定提交，已有 conda 环境直接复用；任何不一致以非零退出。

## 核心步骤

- `clone_pinned`：按任务单固定提交克隆 X-Talk、Qwen3-ASR、MOSS 服务封装与 MOSS 源码；目录已存在时校验 HEAD，不覆盖本地改动。git 协议不可达时允许 tarball 导入的树：`PINNED_UPSTREAM_COMMIT` 文件记录上游固定提交，同样参与一致性校验。
- `create_env`：缺少环境时才创建 `python=3.12 + pip` 的 conda 环境，共四个（tools/asr/moss/client）；LLM 与 turn detector 直接复用镜像 base 环境（vLLM 0.16.0），不建 `xtalk-round1-vllm`。
- `install_env`：按任务单的安装命令逐个环境装依赖，PyPI 默认走清华 tuna 镜像，MOSS 额外保留 PyTorch cu128 官方索引；tuna 上 vllm 0.14.0 只有元数据不一致的 sdist（`+cu101`），因此 vllm 本体改从阿里云镜像（有 manylinux x86_64 wheel）安装，asr 环境的其余依赖在 vllm 就位后再装。四个安装相互独立，并行执行后统一等待。

脚本不触碰 GPU，也不执行 MOSS 封装的 `install.sh`/`start.sh`。所有路径可通过环境变量覆盖，默认指向共享存储 `/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1`。
