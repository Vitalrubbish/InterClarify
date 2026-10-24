# ParaThink

原名 InterClarify。现有服务器资产路径、历史记录和 GitHub 地址保留原名，详见[远端约定](docs/remote_workspace.md)。

ParaThink 研究独立 thinking 流在语音 Agent 倾听与表达期间持续工作带来的优势，工作包括 Agent 框架、边听边想与边说边想两组 benchmark，以及大规模对话数据与训练。研究背景、目标、参考文章和三篇子文档见 [docs/research_design.md](docs/research_design.md)，工程安排见 [docs/engineering_implementation.md](docs/engineering_implementation.md)。

当前运行底座保留 DuplexCascade、Nemotron EN160、Kokoro 与 X-Talk `ca9b23c`。2026-10-24 按用户要求回到阈值调整前的 `13ba980`，校准与 ASR 时间策略实验已从当前目录撤回，见[回滚记录](docs/dev/XTurnix/rollback_cleanup.md)。Nemotron ASR＋XTurnix 是待接入方案，尚未部署新控制链路。Layer 1 表达、Layer 2 异步思考、统一仲裁及单一 TTS 播放路径的目标分工见研究文档。运行底座来自独立维护的 [X-Talk fork](https://github.com/Vitalrubbish/xtalk)。

| 内容 | 位置 |
| --- | --- |
| 研究方案与评测范围 | [docs/research_design.md](docs/research_design.md) |
| 工程实施计划：Nemotron＋XTurnix | [docs/engineering_implementation.md](docs/engineering_implementation.md) |
| FLEURS 两组件质量与延迟测试计划 | [docs/dev/XTurnix/quality_test_on_fleurs.md](docs/dev/XTurnix/quality_test_on_fleurs.md) |
| 本地 conda 环境 | [docs/local_environment.md](docs/local_environment.md)（`parathink-dev`） |
| 工作单管理 | [XTurnix 工作单](docs/issue/XTurnix/README.md)（保留基点记录，不自动恢复取消测试或训练） |
| 已采用的运行时配置 | [docs/runtime_baseline.md](docs/runtime_baseline.md) |
| FDB 评测结果 | [reports/fdb](reports/README.md) |
| X-Talk 源码版本 | [configs/xtalk_runtime_source.json](configs/xtalk_runtime_source.json) |
| 英文运行配置 | [docs/configs/xtalk_duplex_english_runtime.md](docs/configs/xtalk_duplex_english_runtime.md) |

本地与远端统一使用 conda。通用开发环境依据 `environment.yml` 与 `requirements.txt` 创建；ASR、TTS、模型服务与 FDB 评分依赖分别隔离。真实模型训练和集群测试在远端调度作业中执行。新代码同步提供 `docs` 同路径中文说明；权重、音频与大日志不提交 Git。
