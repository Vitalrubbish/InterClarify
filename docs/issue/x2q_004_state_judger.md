# X2Q-004：状态 Judger 与参考时间投影

状态：待实施。依赖：X2Q-002，以及 X2Q-003 的协议映射。协议：[质量测试计划第 7 节](../dev/X2-Turn/qualtity_test_on_fdb.md#7-judger构建参考状态而非评价自身输出)。

## 目标

实现独立离线 Judger，以核验参考和可见前缀建立状态标签，不读取待测 X2-Turn 的转写/状态。区分 ASR 锚定的目标流参考与真实到达时刻的因果诊断。

## 交付

- `scripts/remote/x2_turn_fdb_judger.py` 及 `docs/scripts/remote/x2_turn_fdb_judger.md`。
- 冻结的实际 judge 模型、提示词、采样参数、标签准则、缓存和预算；非 FDB 开发试标记录。
- 带单标签/允许集合/不可判、证据截止点、版本与审核信息的参考；80 ms 投影及冲突 mask。
- 正式参考分层盲审与一致性记录；缺少人工审核时结果明确标为自动参考。

## 验收

无未来前缀泄露；不把 noidle 简化为固定起始帧数，不把静音判成 complete；uncertain 预测与 unjudgeable 参考区分。无法唯一重建的目标位置不强造金标，所有指标带参考覆盖率。Judger 不进入产品控制链路，不启动既有官方内容判题。
