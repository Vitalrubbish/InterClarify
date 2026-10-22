# InterClarify

InterClarify 研究全双工语音代理在用户话轮内是否应主动澄清、何时介入，以及澄清内容是否合理。正式研究方案见 [docs/research_design.md](docs/research_design.md)，工程安排见 [docs/engineering_implementation.md](docs/engineering_implementation.md)。

系统以 DuplexCascade 为运行底座，计划由 X2-Turn 提供转写与用户话轮状态，Layer 1 负责表达与思考调用，Layer 2 异步思考，经统一仲裁器与单一 TTS 播放路径发声。当前先接入与测试 X2-Turn；Layer 0 的系统 backchannel 时机预测及训练保留在后续总计划。运行底座来自独立维护的 [X-Talk fork](https://github.com/Vitalrubbish/xtalk)。

| 内容 | 位置 |
| --- | --- |
| 研究方案与评测范围 | [docs/research_design.md](docs/research_design.md) |
| 工程第一步：X2-Turn 接入与 FDB 测试计划 | [docs/engineering_implementation.md](docs/engineering_implementation.md) |
| X2-Turn 测试数据：历史 FLEURS 子集与远端现状 | [核查记录](docs/dev/X2-Turn/fleurs_subset_verification.md) |
| X2-Turn 测试计划：转写质量与末端 complete | [简化计划](docs/dev/X2-Turn/complete_test_on_fleurs.md) |
| 本地 conda 环境 | [docs/local_environment.md](docs/local_environment.md)（`interclarify-dev`） |
| 工作单管理 | [docs/issue](docs/issue/README.md)（本轮 FDB 测试已取消，FLEURS 核查已完成） |
| 已采用的运行时配置 | [docs/runtime_baseline.md](docs/runtime_baseline.md) |
| FDB 评测结果 | [reports/fdb](reports/README.md) |
| X-Talk 源码版本 | [configs/xtalk_runtime_source.json](configs/xtalk_runtime_source.json) |
| 英文运行配置 | [docs/configs/xtalk_duplex_english_runtime.md](docs/configs/xtalk_duplex_english_runtime.md) |

本地与远端统一使用 conda。通用开发环境依据 `environment.yml` 与 `requirements.txt` 创建；ASR、TTS、模型服务与 FDB 评分依赖分别隔离。真实模型训练和集群测试在远端调度作业中执行。新代码同步提供 `docs` 同路径中文说明；权重、音频与大日志不提交 Git。
