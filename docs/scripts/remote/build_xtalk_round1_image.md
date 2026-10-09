# `scripts/remote/build_xtalk_round1_image.sh`

## 整体作用

封装首轮 X-Talk 验收镜像的构建与推送。以现有 `xtalk:v0.17` 为基座、通过 BuildKit named build contexts 提供 wheelhouse 与三份固定源码树，使 `$XTALK_ROUND1_ROOT` 下的模型缓存、产物目录不进入构建上下文。默认只构建本地镜像，`PUSH=1` 时构建后推送到 registry。

## 核心流程

- 校验四个构建上下文目录（`wheels/`、`qwen-asr/`、`moss-source/`、`xtalk/`）存在，缺失立即退出。
- 执行 `DOCKER_BUILDKIT=1 docker build -f Dockerfile.round1`，用 `--build-context` 把四个目录映射为构建上下文，默认镜像名与任务单一致（`...xtalk-round1:v0.1`）。
- 构建失败显式报错退出，避免把空产物记为成功；`PUSH=1` 时再 `docker push`。

路径与镜像名可用 `XTALK_ROUND1_ROOT`、`XTALK_ROUND1_IMAGE` 覆盖；registry 不允许覆盖已有 tag，升级时递增版本号。
