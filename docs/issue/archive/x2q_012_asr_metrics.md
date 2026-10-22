# X2Q-012：转写 WER 与平均末端文本延迟

状态：已完成并归档（2026-10-22）。依赖：[X2Q-009](x2q_009_fleurs_data.md)、[X2Q-011](x2q_011_streaming_replay.md) 的参考与 trace 合同。依据：[测试计划](../../dev/X2-Turn/complete_test_on_fleurs.md)。

## 目标与工作内容

保留基本 ASR 质量测试，与 complete 是否命中独立统计。

- 固定 `whisper-normalizer==0.1.12` 的 `EnglishTextNormalizer`，同版本原始参考和 EOF 排空后的最终转写采用相同标准化。
- 汇总语料级 `WER=(S+D+I)/N_ref`，保存逐例 S/D/I、参考词数和最终假设；不以逐例 WER 均值代替语料 WER。
- 正常完成但空转写时计删除；运行失败记 null，单列可评分覆盖，不静默移除计划样本。
- 在线末端延迟取 EOF 前、观察窗结束前最后一次词汇文本变化的接收时间减 `t_end`，保留负值；标点/空白不延后词汇指标。
- 报文本延迟均值、P50/P95 和有效数；空转写/运行失败记 null，EOF 后补字及其耗时另列。
- 延迟与 WER 一起展示，不把文件末端冒称真实发声末端，也不把漏词造成的提前停止解释为完整转写更快。

## 交付

在 `scripts/remote/x2_turn_complete_test.py` 增加独立 ASR 评分入口，更新镜像说明中的标准化、WER 和末端时序方法。补充既有测试及说明，覆盖手算 S/D/I、空转写、控制未命中但转写可评分、负延迟、纯标点更新与 EOF 补字。

## 验收

- [x] S/D/I 与参考词数汇总正确，参考及标准化版本固定。
- [x] WER 和文本延迟都有分母与失败覆盖，complete 未命中不剔除 ASR 样本。
- [x] 在线文本时序与最终转写评分分开，冻结 trace 可重算相同结果。
- [x] 本地使用 conda 验证逻辑，不引入 Judger 或强制对齐。


## 完成记录

已在 `scripts/remote/x2_turn_complete_test.py` 交付对应入口；实现说明见 [脚本说明](../../scripts/remote/x2_turn_complete_test.md)，测试说明见 [镜像测试文档](../../tests/test_x2_turn_complete_test.md)。本地 `interclarify-dev` conda 使用固定 `whisper-normalizer==0.1.12`，15 项 unittest 通过；连同既有部署测试共 22 项 pytest 通过。模拟 WebSocket 完整验证真实 80 ms 分块、5 秒静音与窗后 EOF，并覆盖故障及手算指标。

本单仅完成回放和离线评分逻辑，不产生模型实测分数。X2Q-009 冻结输入未改写，X2Q-010 权重与部署已完成；远端单卡预热、冒烟及正式 100 条测试由 X2Q-014 执行。
