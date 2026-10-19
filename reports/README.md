# 当前证据索引

2026-10-19。`reports`按验证链保留最新有效结果；来源清单、资产摘要、外部隔离和路径迁移记录是当前构建依赖，不能仅因日期较早而删除。以下目录为当前保留范围。

| 验证链 | 最新证据与用途 |
| --- | --- |
| ASR选型 | [完整100条比较](asr_selection/20261016-results/summary.md)，替代旧25条smoke |
| 当前ASR输入形式 | [大小写、缩写及数值探针](asr_text_surface/20261019/README.md) |
| Nemotron服务接入 | [EN160集成验证](english_integration/20261018-r4/README.md)，旧TTS结果由continuity-r3替代 |
| Kokoro连续语音 | [最终r3与用户试听结果](tts_continuity/20261019-r3/README.md) |
| 当前完整链基线 | [Nemotron→DuplexCascade→Kokoro B0](full_chain/20261019-b0/README.md) |
| 发布资产与来源 | [资产清单及UltraChat来源](layer1_training/issue001-inventory-20261018/README.md) |
| 官方输入对齐 | [原生Word最终验收](layer1_training/issue001-word-20261019/README.md)，替代旧raw/complete-word诊断 |
| 正式训练数据 | [r5全量机器验收](layer1_training/issue004-build-20261019-r5/README.md)，004已按用户豁免授权关闭 |
| 来源验证与评测隔离 | [最终隔离口径](layer1_training/issue016-source-and-exclusions-20261019/README.md) |
| 训练加载准备 | [当前加载/零更新进展](layer1_training/issue017-loading-20261019/README.md)，不把未完成作业计为通过 |
| 缓存及退役资产清理 | [当前回收记录](maintenance/20261019-cache-reclamation/README.md) |
| 远端路径映射 | [当前目录迁移清单](maintenance/20261019-home-consolidation/README.md) |
| 退役组件清理 | [退役资产及恢复信息](maintenance/20261019-retired-selection/README.md) |

已删除旧ASR契约、阶段A的Qwen/X2/MOSS报告、smoke25、TTS旧连贯性版本及旧集成TTS输出、早期运行时/输入验证、数据管线实现和debug探针。保留目录中的来源摘要、失败说明和对照计数仍用于解释该次最新结果，不代表保留另一份过时完整运行。

删除前的已提交证据可从[固定提交6ca5eea](https://github.com/Vitalrubbish/InterClarify/tree/6ca5eea/reports)查阅；本次不改写Git历史。远端服务器产物未因这次仓库清理删除。归档文档保留本地并受`.gitignore`管理，当前文档中的历史归档链接固定到该提交，保证从GitHub也能查阅。后续新结果替换同一验证链的旧版本，并同步更新本索引和引用。
