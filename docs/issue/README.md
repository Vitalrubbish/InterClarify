# 工作单管理

更新：2026-10-24。按用户最新指令，当前先利用 ASR 的时间信息辅助话轮控制，暂不训练模型，独立 VAD 不作为前置。

## 当前路线

[XTX-014：ASR 时间观测与无训练 Listen 控制](XTurnix/xtx_014_asr_time_control.md)已进入原生 pause 核查与机制诊断，具体方案见[路线文档](../dev/XTurnix/asr_time_control.md)。先使用文字无增量时长、ASR 接收/消费进度与冻结 XTurnix 分数，验证能否在误抢话受控、等待有界时提高末端接话召回。归档与路线已补充；按用户随后明确指令，先核查并尝试[原生 pause](../dev/XTurnix/pause_usage.md)，当前不训练。

[XTX-010](XTurnix/xtx_010_control_baseline_calibration.md)的 Listen 纯文本阶段已完成并保留为基线，Speak 校准后置。[真实结果](../../reports/xturnix_training/20261023-listen-calibration/README.md)为留出误抢话 10.78%→5.39%、末端召回 44.31%→28.74%，未达到预设工作点，新阈值未部署。XTX-014 不依赖 Speak 校准或完整四类训练数据。

## 归档与历史

训练相关 XTX-008、009、011—013 已按用户指令移入 `docs/issue/archive/XTurnix/`，状态为搁置归档，未完成验收保留，不标记训练已通过。XTX-009 的 48 会话辅助审核和 XTX-010 的基线证据继续保留，XTX-007 分析与讨论此前已完成归档。详细清单见[XTurnix 归档入口](XTurnix/README.md#vad-assisted-training)。

| 工作单组 | 当前状态 |
| --- | --- |
| [ASR 时间无训练控制](XTurnix/README.md#当前工作) | XTX-014 原生 pause 诊断进行中；XTX-010 保留 Listen 基线，Speak 后置 |
| [原分析及训练路线](XTurnix/README.md#vad-assisted-training) | XTX-007 已完成；008、009、011—013 搁置归档，不计完成率 |
| [FLEURS 两组件测试](XTurnix/README.md#fleurs-evaluation) | XTX-001—005 已完成；006 正式作业已取消，pause 诊断已完成，正式成绩未产生 |

原 FLEURS/FDB 输入、报告与取消状态保留，不参与新策略选参，不恢复已撤下的 X2-Turn 实现。已查看的 Listen 留出集仅作回归/探索性诊断，不能继续当作新路线独立测试。

研究范围与模块职责见[研究主文档](../research_design.md)，工程顺序见[工程实施计划](../engineering_implementation.md)。保持单一控制策略、唯一仲裁执行点与单一 TTS 播放所有权；当前不接 CoT、Layer 0/1/2 或真实播放，不替换现役控制器。实现和必要测试需有同路径中文说明；真实模型仅在远端 conda 受限作业验证，完成验收后归档，搁置项与完成项明确区分。后续新工作单仍依据用户明确指令建立。
