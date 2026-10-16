# prepare_asr_endpoint.py

为官方模型接话诊断建立五例 FDB manifest，不推理。`main` 固定 `candor_turn_taking` 的 1/10/100/101/102，保留输入 WAV 的摘要及 `[TURN-TAKING]` 标注区间；区间结束作为报告的让轮参考时间，完整区间也保留。要求 16kHz 单声道，不静默改变音频。

FDB 此子集未提供可确认的逐字参考，所以不填造 WER 真值，`reference` 为空、WER 为 null。独立预热复用 FLEURS dev，与五个测试样本隔离。让轮标注只供离线计时，不能进 ASR 或控制模型提示。
