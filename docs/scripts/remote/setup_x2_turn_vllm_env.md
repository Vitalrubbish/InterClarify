# X2-Turn vLLM 环境安装

无类。`scripts/remote/setup_x2_turn_vllm_env.sh` 在一个独立 conda 环境中安装固定版本 X2-Turn 推理依赖，只写入 `interclarify-x2-turn-complete` 根目录和同名环境，不触碰现役 ASR/TTS/评分环境。脚本设计为 CPU 作业入口，不在登录节点或 GPU 节点执行重安装。

## 固定版本

- X2-Turn 源码 `67ec3fe49f1977ee3129f7eaed603c04d8ed23c5`。
- vLLM `0.19.1`，标签 `v0.19.1`，对应提交 `b1388b1fbf5aaef47937fabe98931211684666a6`。
- 作者 overlay 补丁 `voxtral-realtime/patches/vllm-voxtral-mtp.patch`，共 10 个 Python 文件。

调度节点无法访问 `github.com`，因此固定源码由 [源码包](build_x2_turn_source_bundle.md) 离线提供，安装阶段不联网克隆。

## 依赖固定

除 `vllm==0.19.1` 外，`transformers` 固定为 `5.5.1`。transformers 5.10 起在 `ProcessingMixin.prepare_inputs_layout` 中调用 `fetch_audio()`，而 vLLM 0.19.1 自带的 `MistralCommonFeatureExtractor` 没有该方法，服务会在引擎初始化阶段报 `AttributeError`；vLLM 0.19.1 的依赖声明也显式排除 `5.5.0`，因此取 `5.5.1`。版本检查与安装结果写入环境锁的 `packages` 与 `pip freeze`。

## 为什么用 wheel 而不是源码构建

作者指南要求 clone 固定提交后源码安装。源码构建 vLLM 需要完整 CUDA 工具链和远高于本工作单安装预算（4 CPU、16 GiB RAM）的编译资源，在远端集群不现实，因此改为安装官方 `vllm==0.19.1` wheel，再把作者 overlay 应用到这个 wheel 上。

为免"0.19.1 + overlay"变成含糊描述，脚本用补丁里的 `index <pre>..<post>`（git blob SHA-1）作独立依据：wheel 中 10 个待改文件的 blob 必须等于补丁前置哈希，才说明它与固定提交逐字节相同；不相等立即中止。补丁在临时 git 索引中用 `git apply --index` 应用，由 git 再校验前置哈希，并核对应用后的后置哈希。全部哈希写入环境锁。

## 执行流程

1. 检查工作盘空闲空间，低于 100 GiB 退出。
2. 若环境不存在，用 conda-forge 镜像创建 Python 3.11 环境（默认 `~/miniconda3/envs/interclarify-x2-turn-vllm`）。
3. 安装 `vllm==0.19.1`、`mistral-common`、`soundfile`、`websockets`、`huggingface_hub`；已安装同版本时跳过，关闭 pip 缓存避免重复占用磁盘。
4. 校验源码包摘要与传入的 `X2_TURN_SOURCE_BUNDLE_SHA256` 一致并解压。
5. 核对 wheel 与源码包内 10 个文件的 git blob 等于补丁前置哈希。
6. 在临时 git 索引中应用补丁，核对后置哈希，再把补丁后的模块与 `voxtral_mtp_utils.py` 覆盖到 site-packages。
7. 导入检查：`vllm` 可导入，`turn.delta` 协议类存在，六类状态表可读。
8. 写环境锁 `ROOT/env/x2_turn_vllm_environment.json`。

## 参数

| 变量 | 含义 |
| --- | --- |
| `X2_TURN_ROOT` | 固定实验根目录，必填 |
| `X2_TURN_SETUP_OUTPUT` | 本次安装输出目录，必须不存在 |
| `X2_TURN_SOURCE_BUNDLE_SHA256` | 源码包压缩文件摘要，必填 |
| `X2_TURN_CONDA_ENV` | conda 环境前缀，默认 `~/miniconda3/envs/interclarify-x2-turn-vllm` |
| `X2_TURN_CONDA_MIRROR` | conda-forge 镜像，默认清华镜像 |
| `X2_TURN_PIP_INDEX` | PyPI 镜像，默认清华镜像 |

## 输出

`X2_TURN_SETUP_OUTPUT` 下保存 `conda_create.log`、`pip_install.log`、`pip_freeze.txt`、`patched_files.tsv`、`wheel_vs_source.tsv`、`overlay_install.log`、`overlay_index.txt`、`installed_files.tsv`、`import_check.json`。环境锁记录 Python 版本、安装方式、镜像、源码包摘要、10 个文件的前后置哈希与安装哈希、overlay 新模块哈希、关键包版本和完整 `pip freeze`。

脚本不重试、不加资源；conda 或 pip 失败时保留日志并让作业失败，后续由工作单决定是否调整镜像或版本。脚本可以重复执行：已安装同版本 wheel 时跳过安装；site-packages 已带补丁时核对后置哈希后跳过打补丁；输出目录必须每次新建，旧证据不被覆盖。`pdcpu` 排队时可改为在调试机串行执行。
