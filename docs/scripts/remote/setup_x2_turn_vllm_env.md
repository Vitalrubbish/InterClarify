# X2-Turn vLLM 环境安装

无类。`scripts/remote/setup_x2_turn_vllm_env.sh` 在一个独立 conda 环境中安装固定版本 X2-Turn 推理依赖，只写入 `interclarify-x2-turn-complete` 根目录和同名环境，不触碰现役 ASR/TTS/评分环境。脚本设计为 CPU 作业入口，不在登录节点或 GPU 节点执行重安装。

## 固定版本

- X2-Turn 源码 `67ec3fe49f1977ee3129f7eaed603c04d8ed23c5`。
- vLLM `0.19.1`，标签 `v0.19.1`，对应提交 `b1388b1fbf5aaef47937fabe98931211684666a6`。
- 作者 overlay 补丁 `voxtral-realtime/patches/vllm-voxtral-mtp.patch`，共 10 个 Python 文件。

## 为什么用 wheel 而不是源码构建

作者指南要求 clone 固定提交后源码安装。源码构建 vLLM 需要完整 CUDA 工具链和远高于本工作单安装预算（4 CPU、16 GiB RAM）的编译资源，在远端集群不现实，因此改为安装官方 `vllm==0.19.1` wheel，再把作者 overlay 应用到这个 wheel 上。为免"0.19.1 + overlay"变成含糊描述，脚本会先用浅克隆取得固定提交，逐文件比较 wheel 中 10 个待改文件与提交内容的 SHA256；任何一处不一致立即中止，不继续应用补丁。全部哈希写入环境锁，`install_method` 明确记录为 `official wheel + pinned overlay patch`。

## 执行流程

1. 检查工作盘空闲空间，低于 100 GiB 退出。
2. 若环境不存在，用 conda-forge 镜像创建 Python 3.11 环境（默认 `~/miniconda3/envs/interclarify-x2-turn-vllm`）。
3. 从 PyPI 镜像安装 `vllm==0.19.1`、`mistral-common`、`soundfile`、`websockets`、`huggingface_hub`；关闭 pip 缓存，避免重复占用磁盘。
4. 浅克隆并检出两个固定提交；vLLM 按标签拉取，保证 `install_vllm_overlay.sh` 的标签检查通过。
5. 校验 wheel 与固定提交的 10 个文件一致。
6. 清理固定 checkout 后运行作者安装脚本应用补丁，再把补丁后的模块和新模块 `voxtral_mtp_utils.py` 覆盖到 site-packages。
7. 导入检查：`vllm` 可导入，`turn.delta` 协议类存在，六类状态表可读。
8. 写环境锁 `ROOT/env/x2_turn_vllm_environment.json`。

## 参数

| 变量 | 含义 |
| --- | --- |
| `X2_TURN_ROOT` | 固定实验根目录，必填 |
| `X2_TURN_SETUP_OUTPUT` | 本次安装输出目录，必须不存在 |
| `X2_TURN_CONDA_ENV` | conda 环境前缀，默认 `~/miniconda3/envs/interclarify-x2-turn-vllm` |
| `X2_TURN_CONDA_MIRROR` | conda-forge 镜像，默认清华镜像 |
| `X2_TURN_PIP_INDEX` | PyPI 镜像，默认清华镜像 |

## 输出

`X2_TURN_SETUP_OUTPUT` 下保存 `conda_create.log`、`pip_install.log`、`pip_freeze.txt`、`wheel_vs_source.tsv`、`patched_files.tsv`、`overlay_install.log`、`import_check.json`。环境锁记录 Python 版本、安装方式、镜像、10 个文件的应用前/固定提交/应用后哈希、overlay 新模块哈希、关键包版本和完整 `pip freeze`。

脚本不重试、不加资源；conda 或 pip 失败时保留日志并让作业失败，后续由工作单决定是否调整镜像或版本。
