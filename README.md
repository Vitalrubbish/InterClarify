# ParaThink

现有服务器资产路径、历史记录和 GitHub 地址保留原名，详见[远端约定](docs/remote_workspace.md)。

ParaThink 研究独立 thinking 流在语音 Agent 倾听与表达期间持续工作带来的优势，工作包括 Agent 框架、边听边想与边说边想两组 benchmark，以及大规模对话数据与训练。研究背景、目标、参考文章和三篇子文档见 [docs/research_design.md](docs/research_design.md)，工程安排见 [docs/engineering_implementation.md](docs/engineering_implementation.md)。

当前重新以官方 **SoulX-Duplug** 源码为起点。本地源码在 [third_party/soulx-duplug](third_party/soulx-duplug)，作为Git子模块固定官方提交；clone父仓库时使用`--recurse-submodules`，已有仓库执行`git submodule update --init third_party/soulx-duplug`。源码与依赖说明见[子模块说明](docs/third_party/soulx-duplug.md)。

当前采用[原生SenseVoice控制＋独立X2正文](docs/dev/SoulX-Duplug/independent_streaming_frontend.md)。NTF-015／016的原生封装、同源PCM／160ms推进屏障和独立X2适配已完成本地实现及契约验收，见[交付记录](docs/reports/soulx/20261102-native-independent-frontend/README.md)；[NTF-017联合Context](docs/reports/soulx/20261102-ntf017-joint-publication/README.md)已完成本地交付和全量144项检查：每160ms双路完成后一起提交正文与状态，再允许下一批推进，前端停止钩子已移除；[NTF-020](docs/reports/soulx/20261103-ntf020-handoff-retirement/README.md)已取消额外交接等待并归档，[NTF-018](docs/reports/soulx/20261103-ntf018-warmup/README.md)已通过完整预热、真实权重对照及并发三轴3/3并归档；[NTF-019](docs/issue/NTF-019.md)已启动固定FDB30双／单路验收。

此前Nemotron／X2教师前端及固定实验保留为历史改造证据：NTF-011／012实时性和规范分词通过、状态质量未整体改善，见[同卡报告](docs/reports/soulx/20261101-ntf012-x2-teacher-fdb30/README.md)。这些适配器不等同于官方原生推理。comparison历史实验按NTF-014清理，公共模型与conda继续保留；本次已授权018及通过后的019远端模型测试；018已验收通过并启动019，用户已取消提交次数限制，不训练或切换下游。

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
