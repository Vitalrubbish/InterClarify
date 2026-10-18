# InterClarify

InterClarify 研究全双工语音代理在用户话轮内主动澄清的时机、措辞与任务恢复。研究范围见 [研究设计](docs/research_design.md)，阶段与模块边界见 [工程方案](docs/engineering_implementation.md)。底座为独立维护的 [X-Talk fork](https://github.com/Vitalrubbish/xtalk)，保持唯一控制执行者与唯一 TTS 播放所有权，Layer 2 尚未接入。

当前英文 ASR 主线选择 **Nemotron EN 0.6B / 160ms**，接入与 Layer 1 接话适配尚未验收。Qwen3-ASR 因回写引发的交付停滞已退役；现有 X2 链路仅保留用于回归诊断。历史阶段 A 自动门禁通过不代表新 ASR 组合已通过质量与延迟验收。

| 内容 | 位置 |
| --- | --- |
| 英文 TTS 最终选型 | [选型报告](docs/tts_selection_decision.md)：Pocket 为英文实时主线接入对象，Kokoro 为音质优先对照；运行时替换待验收 |
| ASR 最终测试报告与原始结果 | [报告](reports/asr_selection/20261016-results/summary.md) |
| ASR 选择与后续适配 | [选型决定](docs/asr_selection_decision.md) |
| 清理范围与历史源码恢复 | [清理记录](docs/asr_cleanup.md) |
| 新英文链路的 FDB 子集推进 | [前置缺口、接入顺序与测试范围](docs/fdb_subset_retest_plan.md) |
| 阶段 A 历史证据 | [验收记录](docs/xtalk_a4_remote_acceptance.md)、[结果目录](reports/duplex_acceptance/) |
| X2 诊断运行配置 | [配置](configs/xtalk_duplex_x2_runtime.json)、[说明](docs/configs/xtalk_duplex_x2_runtime.md) |
| 通用模型服务与 MOSS 补丁 | [服务工具](docs/scripts/remote/run_xtalk_round1.md)、[TTS 补丁](docs/scripts/remote/moss_tts_patch.md) |

本地与远端均使用 conda。通用环境按 `environment.yml` 创建，并在该环境安装 `requirements.txt`；模型与 X-Talk 依赖按各服务说明隔离。已具备相关依赖的 conda 环境可以运行离线测试：

```bash
conda env create -f environment.yml
conda run -n interclarify-dev python -m pip install -r requirements.txt
conda run -n interclarify-dev env PYTHONPATH=xtalk/src:. python -m unittest discover -s tests -q
```

真实模型与集群验证在远端进行。A4 诊断入口为 `scripts/remote/submit_xtalk_duplex_a4_job.sh`，必须显式设置 `DUPLEX_ASR_BACKEND=x2`、`DUPLEX_ASR_ENV`（独立 conda prefix）、`DUPLEX_X2_SOURCE`、`DUPLEX_X2_MODEL` 与同步源码根目录；见 [节点脚本说明](docs/scripts/remote/run_xtalk_duplex_a4_node_job.md)。没有可默认启动的 Nemotron 部署配置。
