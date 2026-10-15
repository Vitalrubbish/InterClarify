# `scripts/remote/build_xtalk_round1_image.sh`

## 整体作用

封装首轮 X-Talk 验收镜像的构建与推送。以现有 `xtalk:v0.17` 为基座、通过 BuildKit named build contexts 提供 wheelhouse 与三份固定源码树，使 `$XTALK_ROUND1_ROOT` 下的模型缓存、产物目录不进入构建上下文。默认只构建本地镜像，`PUSH=1` 时构建后推送到 registry。

## 核心流程

- **两种模式**：默认（`OVERLAY=0`）从零构建 `Dockerfile.round1`；`OVERLAY=1` 构建 [Dockerfile.round1.overlay](Dockerfile.round1.overlay.md)——以已发布 tag（`OVERLAY_BASE`，默认 `...:v0.3`）为 base 的增量层，用于"只多一个依赖"的改动（从零重建约 1 小时且要推十几 GB，增量层几分钟、几百 MB）。
- 校验四个构建上下文目录（`wheels/`、`qwen-asr/`、`moss-source/`、`xtalk/`）存在，缺失立即退出（仅从零模式需要）。
- 额外校验 `wheels/` 中存在预编译 flash-attn wheel（`flash_attn-*.whl`）；缺失即退出并提示从官方 `v2.8.3` release 下载 `flash_attn-2.8.3+cu12torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl`（或从可达镜像 `hf-mirror.com/gueraf/flash-attn-wheels` 取同名逐字节副本）。因为 MOSS 环境直接安装该 wheel，不再源码编译。
- **归一化 flash wheel 文件名**：官方 wheel 文件名带本地版本（`...+cu12torch2.9...`），但 wheel 内 `METADATA` 的 `Version` 是 `2.8.3`，pip ≥ 24 会判为 “inconsistent version” 并丢弃→回退到 sdist 编译（正是之前把调试机搞崩的路径）。脚本会复制出与元数据一致的 `flash_attn-2.8.3-<py>-<abi>-<plat>.whl` 供构建使用（仅从零模式需要）。
- 执行 `DOCKER_BUILDKIT=1 docker build -f Dockerfile.round1`，用 `--build-context` 把四个目录映射为构建上下文，默认镜像名为已验证的 `...xtalk-round1:v0.4`。发布新镜像时通过 `XTALK_ROUND1_IMAGE` 指定新 tag，并在组件基线中登记 digest 与复测结果。
- **失败检测**：本机 `docker` CLI 在 BuildKit 报 `ERROR: failed to solve` 时仍返回退出码 0，因此脚本改为把构建输出落盘并检查错误标记、且构建后 `docker image inspect` 确认 tag 存在，任一不满足即判失败退出（不再误报 “built/pushed”）。
- `PUSH=1` 时再 `docker push`。

路径与镜像名可用 `XTALK_ROUND1_ROOT`、`XTALK_ROUND1_IMAGE` 覆盖；registry 不允许覆盖已有 tag，升级时递增版本号。
