# X2Q-005：转写、末端延迟与状态评分

状态：待实施。依赖：X2Q-002—004 的数据合同。协议：[质量测试计划第 5—8 节](../dev/X2-Turn/qualtity_test_on_fdb.md#5-转写-wer)。

## 目标

从冻结参考和原始 trace 独立重算 WER、用户说完到最后词汇更新的延迟，以及严格逐帧和事件级状态匹配。

## 交付

- `scripts/remote/x2_turn_fdb_score.py` 及 `docs/scripts/remote/x2_turn_fdb_score.md`。
- `tests/test_x2_turn_fdb_quality.py` 及对应说明，验证时钟/EOF、空转写、末词漏识别、缺帧、投影冲突与一对一事件匹配。
- 逐例、分子集、语料级统计；WER 的 S/D/I 分母、延迟均值/分位数及覆盖、五类 macro-F1 与额外 uncertain/missing 预测列。

## 验收

最后词汇更新时间、协议 done 和 EOF 后补字分开；失败不记零延迟，漏末词不被当成快速完成。严格匹配不做事后时间规整，容差指标独列；idle 不掩盖少数类。小型人工可算 trace 与实际产物可重复得到一致结果。
