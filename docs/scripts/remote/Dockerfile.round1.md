# `scripts/remote/Dockerfile.round1`

从 `xtalk-lean:v0.1` 构建通用模型服务镜像。Qwen3-ASR 退役后，仅创建 tools、moss、client、turnsense 四个 conda 环境；LLM 复用 base。ASR 环境和模型资产独立准备，不再复制或安装 Qwen ASR 源码。

配方没有类或方法。主要步骤为复制固定 MOSS/X-Talk 源码及 TurnSense 服务，以只读 wheelhouse 安装依赖，然后清理 conda 缓存。BuildKit named contexts 仅为 `wheels`、`moss-source` 和 `xtalk`，避免将权重缓存纳入构建上下文。

MOSS 保留 torch 2.9.1+cu128、Transformers 5.0.0 和预编译 flash-attn 2.8.3；客户端保留既有 optional extras，X2 双工配置自身不加载声学 VAD。TurnSense 保留独立 ONNX 栈。依赖锁与固定来源见通用配置及历史验收记录。

使用 `build_xtalk_round1_image.sh` 时必须显式指定新的未使用 `XTALK_ROUND1_IMAGE` 标签。配方尚未在本次清理中重建或发布，现有 v0.4 镜像内容保持历史状态。旧 overlay 继承原镜像，不能用于移除底层的 Qwen 环境；需要不含该环境的镜像时从本配方重新构建。
