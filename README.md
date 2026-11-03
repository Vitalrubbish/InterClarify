# ParaThink

现有服务器资产路径、历史记录和 GitHub 地址保留原名，详见[远端约定](docs/remote_workspace.md)。

ParaThink 研究独立 thinking 流在语音 Agent 倾听与表达期间持续工作带来的优势，工作包括 Agent 框架、边听边想与边说边想两组 benchmark，以及大规模对话数据与训练。研究背景、目标、参考文章和三篇子文档见 [docs/research_design.md](docs/research_design.md)，工程安排见 [docs/engineering_implementation.md](docs/engineering_implementation.md)。

当前以官方 **SoulX-Duplug** 源码为起点。本地源码在 [third_party/soulx-duplug](third_party/soulx-duplug)，作为 Git 子模块固定官方提交；clone 父仓库时使用 `--recurse-submodules`，已有仓库执行 `git submodule update --init third_party/soulx-duplug`。源码与依赖说明见[子模块说明](docs/third_party/soulx-duplug.md)。

第一阶段 ASR-Frontend 采用 **SoulX-Duplug 官方配置＋并行 X2Streaming-ASR**：SoulX 保留内部 SenseVoice 控制与原生五状态，独立 X2 只向 SharedContext 提供 EOS 闭合的完整词正文，两路每 160ms 完成后联合提交。合同见[独立流式前端](docs/dev/SoulX-Duplug/independent_streaming_frontend.md)，交付与验收见[NFT-015/016](docs/reports/soulx/20261102-native-independent-frontend/README.md)、[NTF-017](docs/reports/soulx/20261102-ntf017-joint-publication/README.md)、[NTF-018](docs/reports/soulx/20261103-ntf018-warmup/README.md)、[NTF-019](docs/reports/soulx/20261103-ntf019-fdb30/README.md)和[NTF-030](docs/reports/soulx/20261103-latency-limit-removal/README.md)。当前前端工作已收口，后续 LLM 接入暂缓。

| 内容 | 位置 |
| --- | --- |
| 研究方案与评测范围 | [docs/research_design.md](docs/research_design.md) |
| 工程实施计划 | [docs/engineering_implementation.md](docs/engineering_implementation.md) |
| SoulX 前端路线 | [docs/dev/SoulX-Duplug](docs/dev/SoulX-Duplug/README.md) |
| 本地 conda 环境 | [docs/local_environment.md](docs/local_environment.md)（`parathink-dev`） |
| 工作单 | [docs/issue/README.md](docs/issue/README.md) |
| 已采用的运行时配置 | [docs/runtime_baseline.md](docs/runtime_baseline.md) |
| FDB 固定 30 条验收 | [docs/reports/soulx/20261103-ntf019-fdb30](docs/reports/soulx/20261103-ntf019-fdb30/README.md) |
| X-Talk 源码版本 | [configs/xtalk_runtime_source.json](configs/xtalk_runtime_source.json) |
| 英文运行配置 | [docs/configs/xtalk_duplex_english_runtime.md](docs/configs/xtalk_duplex_english_runtime.md) |

本地与远端统一使用 conda。通用开发环境依据 `environment.yml` 与 `requirements.txt` 创建；ASR、TTS、模型服务与 FDB 评分依赖分别隔离。真实模型训练和集群测试在远端调度作业中执行。新代码同步提供 `docs` 同路径中文说明；权重、音频与大日志不提交 Git。
