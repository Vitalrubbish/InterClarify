# P1 DuplexCascade 复现

P1 对应 [engineering_implementation.md](../engineering_implementation.md) 第 5 节。当前先实现 P1.1 的服务器资产准备，保持官方 ASR、LLM、TTS 和 micro-turn 路径不变；InterClarify 的 Layer 2 决策尚未接入。

## 已实现

- [sync_from_github.sh](../../scripts/remote/sync_from_github.sh)：服务器从 GitHub `main` 更新干净项目 checkout；
- [prepare_p1_assets.py](../../scripts/remote/prepare_p1_assets.py)：在服务器共享存储下载和校验固定官方代码、DuplexCascade 权重与基础模型；
- [P1.1 任务单](../jobs/p1_official_assets.md)：记录 GitHub 中转、conda 环境、Hugging Face 认证和验收证据。

## 进度

资产准备脚本尚未在集群执行。完成 `manifest.json` 验收后，继续实现固定最小输入的官方推理适配，并保存原始输出、GPU 峰值显存和实时因子；实时 ASR–LLM–TTS 链路属于 P1.2。
