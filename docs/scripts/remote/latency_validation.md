# latency_validation.py

## 作用与设计

提供延迟分解报告和固定请求缓存对照。probe 从基线 trace 按实际历史长度选择三个会话，每会话连续回放最多12拍，分别无缓存/有缓存，重复三次并独立会话；逐请求核对生成ID，报告实际长度、命中和首token/整拍耗时。第一拍为冷请求，单列统计。

analyze 按 session/request/response 关联模型trace、适配器/TTS诊断、时间线与客户端播放，输出每个回复的里程碑、相邻耗时、总和核对及各臂统计。参考锚点沿用 FDB turn_taking/interruption_end，其他子集用有参考词结束时间时补充，缺失保留为空。首正文不混用首控制标记，参考锚点后无回复保留漏答，原音频窗口和诊断尾窗分开。

核心方法：logged_events 读取有标识诊断；response_rows 建立同回复分解；stats 汇总样本数、均值和P50/P95；analyze 写JSON/CSV；probe 固定输入ID验证缓存收益。计算时间使用同节点单调时钟，首token耗时为预填充与首token选择的代理，不宣称纯GPU kernel计时。

## Issue 061：自动核对生成规则

probe先读取health中的generation_policy，再用require_generation_policy核对每个完成响应携带的规则。缺失或变化即失败，结果记录本轮实际策略；旧trace仍可作为固定prompt输入来源，不将旧输出当新策略标准答案。缓存有/无请求使用同一模型服务的新显式策略，继续保留实际token分歧。
