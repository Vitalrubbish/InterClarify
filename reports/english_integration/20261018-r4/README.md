# Nemotron EN160 服务接入验收

2026-10-18，冻结源码v6。ASR作业`job-179233016243237430568-xuan-zhang`在远端单张4090、8CPU、32GB下退出0。当前保留本次ASR服务、真实增量、EOF及生命周期证据；Kokoro最新结果见[continuity-r3](../../tts_continuity/20261019-r3/README.md)，旧r4-tts结果和试听副本已清理。

| ASR项目 | 实测 |
| --- | --- |
| 精度／输入 | FP32，16kHz PCM16，160ms模型窗口 |
| 加载耗时，含导入与设备准备 | 70.02秒 |
| readiness | 两次真实语音输出并清理 |
| GPU采样峰值 | 2906MiB |
| 进程峰值RSS | 2514592KiB |

六场景覆盖正常、三秒停顿恢复、同流两轮、串行会话、短尾EOF及取消重连。五次完整识别的末次独立轮询与EOF文本一致，无前缀回写或代际污染；首文本1.00–1.38秒，最大音频投送迟到4.54ms。构造停顿例将chances识别为answers，原输出保留，接口通过不能替代识别质量验收。

这些场景来自同一条FLEURS dev录音及构造变体，不是五条独立录音。两轮连续输入中36/50个最终识别词在音频EOF前可见，其余14词经排空后交付；正常例24/25，其余三个完整例25/25。`final_word_delivery.json`按最终识别文本估计首次可见时刻，不是人工词对齐延迟，不能外推长会话实时性。

`r4-asr/verification`保留逐例输入、到达与前缀记录；ASR包版本见`environment/asr.*`，权重引用[发布资产清单](../../layer1_training/issue001-inventory-20261018/inventory_summary.json)。`compact_summary.json`为原始结果摘要，`artifact_sha256.json`及`compact_sha256.json`分别记录原始字节与紧凑副本摘要；这些历史完整采集清单不因删除旧TTS副本而改写，其TTS条目可在[删除前固定提交](https://github.com/Vitalrubbish/InterClarify/tree/6ca5eea/reports/english_integration/20261018-r4)查看。

原始日志与音频留远端`interclarify-english-integration-20261018-v6/data/runs/r4-asr`，实际位置按[远端路径映射](../../maintenance/20261019-home-consolidation/README.md)查找。组件接入通过不等于Layer 1语义、FDB或完整音频链验收；当前完整链证据另见[B0](../../full_chain/20261019-b0/README.md)。
