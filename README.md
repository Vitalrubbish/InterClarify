# InterClarify

InterClarify 研究全双工语音代理在用户话轮内主动澄清的时机、措辞与任务恢复。研究范围见 [研究设计](docs/research_design.md)，实现边界见 [工程方案](docs/engineering_implementation.md)。运行底座为独立维护的 [X-Talk fork](https://github.com/Vitalrubbish/xtalk)，保持唯一控制执行者与唯一 TTS 播放所有权。

2026-10-18 用户确定英文组合为 **Nemotron EN 0.6B / 160ms + Kokoro 82M**，开始 Layer 1 训练适配。组件接入、训练及新组合验收尚未完成；Layer 2 尚未接入。现存 X2 + MOSS 入口仅作历史诊断，不能直接启动新组合。

| 内容 | 位置 |
| --- | --- |
| 最新开发与测试任务、依赖和完成条件 | [docs/issue](docs/issue/README.md) |
| ASR 选型与测量依据 | [正式选型报告](docs/asr_selection_report.md)、[实测](reports/asr_selection/20261016-results/summary.md) |
| 官方输入对齐后的接话证据 | [复测记录](docs/asr_official_input_retest.md) |
| Kokoro 选择与 TTS 实测 | [正式选型报告](docs/tts_selection_report.md) |
| 历史基线、运行结果与过时文档恢复 | [证据索引](docs/baseline_evidence.md)、[清理记录](docs/asr_cleanup.md) |

本地与远端使用 conda。通用开发环境依据 `environment.yml` 与 `requirements.txt` 创建；ASR、TTS、模型训练和 FDB 依赖分别隔离并锁定。真实模型训练和集群测试在远端调度作业中执行。新代码同步提供 docs 同路径中文说明；权重、音频与大日志不提交 Git。
