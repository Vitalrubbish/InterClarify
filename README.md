# ParaThink

ParaThink 研究独立 thinking 流在语音 Agent 倾听与表达期间持续工作的收益，包括 Agent 框架、两组 benchmark 及对话数据与训练。研究范围见[研究方案](docs/research_design.md)，已确认的模块协作见[总体架构](docs/research_design/architecture.md)。

当前前端为 SoulX-Duplug 原生控制＋独立 X2Streaming-ASR，同源音频每 160ms 联合提交正文和状态。可执行基线是 SoulX＋X2＋Qwen2.5-7B-Instruct＋IndexTTS 的独立半双工评测；Layer 1／2 协议已设计，持久 Context、thinking 接入和专项训练尚未实施。X-Talk 保留为工程框架，尚未完成常驻集成。

| 内容 | 入口 |
| --- | --- |
| 研究方案与总体架构 | [研究方案](docs/research_design.md)、[架构](docs/research_design/architecture.md) |
| Layer 1／2 协议 | [表达协议](docs/dev/layer1/protocol.md)、[思考协议](docs/dev/layer2/protocol.md) |
| 工程实施与运行基线 | [工程计划](docs/engineering_implementation.md)、[运行基线](docs/runtime_baseline.md) |
| SoulX＋X2 前端 | [路线入口](docs/dev/SoulX-Duplug/README.md) |
| 数据构造与文本试造 | [数据设计](docs/dev/layer1_training/data_construction.md)、[pilot](docs/datagen/README.md) |
| 活动工作与评测证据 | [工作单](docs/issue/README.md)、[报告索引](reports/README.md) |
| 环境与源码 | [本地 conda](docs/local_environment.md)、[远端约定](docs/remote_workspace.md)、[X-Talk 版本](configs/xtalk_runtime_source.json) |

官方 SoulX 源码固定在 [Git 子模块](third_party/soulx-duplug)，clone 时使用 `--recurse-submodules`，已有仓库执行 `git submodule update --init third_party/soulx-duplug`。依赖与版本见[源码说明](docs/third_party/soulx-duplug.md)。服务器资产路径和 GitHub 地址保留原名。

本地与远端统一使用 conda，新建通用环境名为 `parathink-dev`，已有 `interclarify-dev` 可复用；真实模型训练和集群测试在远端调度作业执行。实现与同路径中文文档同步，权重、音频和大日志不提交 Git。
