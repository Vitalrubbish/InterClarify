# ParaThink

原名 InterClarify。现有服务器资产路径、历史记录和 GitHub 地址保留原名，详见[远端约定](docs/remote_workspace.md)。

ParaThink 研究独立 thinking 流在语音 Agent 倾听与表达期间持续工作带来的优势，工作包括 Agent 框架、边听边想与边说边想两组 benchmark，以及大规模对话数据与训练。研究背景、目标、参考文章和三篇子文档见 [docs/research_design.md](docs/research_design.md)，工程安排见 [docs/engineering_implementation.md](docs/engineering_implementation.md)。

当前研究前端采用 **Nemotron Teacher Forcing＋SoulX-Duplug**，Nemotron原始正文与五状态逐步联合写入SharedContext。最新官方控制格式与文字门控对照已交付，但完整回放25/30、5条积压触限，状态未整体改善，见[报告](reports/soulx/20261031-nemotron-teacher-gate/README.md)。五类用户状态送入 Layer 1，仅有效用户打断额外直接停止活动输出；具体合同见[架构设计](docs/research_design/architecture.md)。新链路尚未接入，已采用的运行底座仍为 DuplexCascade、Nemotron、Kokoro 与 [X-Talk fork](https://github.com/Vitalrubbish/xtalk) `ca9b23c`。

| 内容 | 位置 |
| --- | --- |
| 研究方案与评测范围 | [docs/research_design.md](docs/research_design.md) |
| 工程实施计划 | [docs/engineering_implementation.md](docs/engineering_implementation.md) |
| SoulX 前端路线与对照实验 | [docs/dev/SoulX-Duplug](docs/dev/SoulX-Duplug/README.md) |
| 已归档的 TextTurn／VoxTurn／XTurnix 路线 | [docs/archive/dev](docs/archive/dev/README.md) |
| 本地 conda 环境 | [docs/local_environment.md](docs/local_environment.md)（`parathink-dev`） |
| 工作单与历史实验 | [docs/issue/README.md](docs/issue/README.md) |
| 已采用的运行时配置 | [docs/runtime_baseline.md](docs/runtime_baseline.md) |
| FDB 评测结果 | [reports/fdb](reports/README.md) |
| X-Talk 源码版本 | [configs/xtalk_runtime_source.json](configs/xtalk_runtime_source.json) |
| 英文运行配置 | [docs/configs/xtalk_duplex_english_runtime.md](docs/configs/xtalk_duplex_english_runtime.md) |

本地与远端统一使用 conda。通用开发环境依据 `environment.yml` 与 `requirements.txt` 创建；ASR、TTS、模型服务与 FDB 评分依赖分别隔离。真实模型训练和集群测试在远端调度作业中执行。新代码同步提供 `docs` 同路径中文说明；权重、音频与大日志不提交 Git。
