# 短延迟对照配置

`configs/xturnix_short_latency.json` 固定 XTX-014 本轮预算与有限候选刻度。用户选定 500ms 主预算，300/800ms 为敏感性；不包含 LLM/TTS。

`thresholds` 用于纯文本及联合策略，1.01 表示禁止该时段启动；`waits_ms` 用于纯时间策略；`joint_times_ms` 为每个预算对应的三段 ASR 无增量等待时间，三个语义阈值不升高。候选选择只在校准会话进行。

健康与容量字段约束真实事件中的接收/消费进度、轮询及音频/输出量。配置不含参考停顿触发，不向模型 prompt 添加时间。协议见[短延迟对照](../dev/XTurnix/short_latency_comparison.md)。
