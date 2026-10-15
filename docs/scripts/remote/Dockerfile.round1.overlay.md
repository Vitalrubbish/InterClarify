# `scripts/remote/Dockerfile.round1.overlay`

## 整体作用

round-one 验收镜像的**增量层**配方：以**已发布**的镜像 tag 为 base，只追加本次需要的改动，避免动 `Dockerfile.round1` 里那层"一次装五个 conda 环境"的 `RUN`。

## 为什么需要它

`Dockerfile.round1` 的五个环境写在同一个 `RUN` 里，带来两个代价：

1. **重建慢**：该 `RUN` 挂了 `--mount=from=wheels`（约 6 GB wheelhouse），缓存键包含挂载内容，wheelhouse 一变就整层失效；实测用**逐字节相同**的 v0.3 Dockerfile 重跑，BuildKit 仍然从零重装（约 1 小时）。
2. **推送贵**：该层内容一变就是一个新 blob，`docker push` 要推十几 GB。

所以"只多一个依赖"这类改动不该走从零重建，而应写成 base=v0.3、只跑一条 `pip install` 的增量层：构建 2–3 分钟，推送只有几百 MB（其余层仓库里已有，天然去重）。

## 当前内容（v0.4 = v0.3 + 后端 VAD 依赖）

- base：`...xtalk-round1:v0.3`（`--build-arg BASE_IMAGE` 可覆盖）。
- 改动：在 client 环境安装 `onnxruntime==1.31.0`，并在构建期自检 `import onnxruntime` 成功。
- 原因：duplex 运行时的后端 VAD 在 client 进程内跑，而 `VADManager` 在"没有配置 VAD 模型"时会整体禁用，导致 ASR 片段边界被推迟到音频流结束（见 [任务单 §9.5.4.2](../../xtalk_a4_remote_acceptance.md)）。`onnxruntime` 只由 `xtalk[silero-vad]`（或 `[fast-enhancer]`）extra 提供，v0.3 的 client 环境没有。
- 为什么只装这一个包、而不是重跑 `-e "xtalk[example,dev,silero-vad]"`：后者会让 pip 重解整棵 extras 依赖树（实测在 `langchain-openai` 上反复回溯，耗时数分钟），而本次需要新增的只有 `onnxruntime` 及其小依赖。
- 为什么离线装：`pypi.org` 在这个 17MB wheel 上会长时间卡住（2026-10-15 从零构建与增量构建各遇到一次，日志停在 `Downloading onnxruntime-... (17.4 MB)` 不动），而 wheelhouse 里已有 1.31.0 同版本 wheel；缺的 `coloredlogs`/`humanfriendly` 两个小 wheel 已补进 wheelhouse。

## 与 `Dockerfile.round1` 的关系

`Dockerfile.round1` 仍是**从零构建的权威配方**，描述每个已发布 tag 里应该有什么；两个文件在"增量转正"时必须保持一致（即：先在 `Dockerfile.round1` 里把该依赖写进对应环境，再用本文件发布增量层）。若增量层越积越多，就按 `Dockerfile.round1` 从零重建一次，把 base 提升到新 tag。

## 用法

```bash
OVERLAY=1 PUSH=1 bash scripts/remote/build_xtalk_round1_image.sh
# 等价手工命令
DOCKER_BUILDKIT=1 docker build -f scripts/remote/Dockerfile.round1.overlay \
  --build-arg "BASE_IMAGE=.../xtalk-round1:v0.3" \
  -t ".../xtalk-round1:v0.4" .
docker push ".../xtalk-round1:v0.4"
```

base 缺失时脚本会提示先 `docker pull`；构建同样有"BuildKit 报了错但 CLI 返回 0"的兜底检查（见 [build_xtalk_round1_image.md](build_xtalk_round1_image.md)）。
