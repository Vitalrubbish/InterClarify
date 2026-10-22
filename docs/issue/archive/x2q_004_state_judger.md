# X2Q-004：状态 Judger 与参考时间投影

状态：已取消，2026-10-22 归档。用户决定不再执行本轮 FDB 测试，以下为取消前的工作范围。后续数据核查见 [FLEURS 记录](../../dev/X2-Turn/fleurs_subset_verification.md)。

## 目标

实现独立离线 Judger，以核验参考和可见前缀建立状态标签，不读取待测 X2-Turn 的转写/状态。区分 ASR 锚定的目标流参考与真实到达时刻的因果诊断。

## 交付

- `scripts/remote/x2_turn_fdb_judger.py` 及 `docs/scripts/remote/x2_turn_fdb_judger.md`。
- 冻结的实际 judge 模型、提示词、采样参数、标签准则、缓存和预算；非 FDB 开发试标记录。
- 带单标签/允许集合/不可判、证据截止点、版本与审核信息的参考；80 ms 投影及冲突 mask。
- 正式参考分层盲审与一致性记录；缺少人工审核时结果明确标为自动参考。

## 验收

无未来前缀泄露；不把 noidle 简化为固定起始帧数，不把静音判成 complete；uncertain 预测与 unjudgeable 参考区分。无法唯一重建的目标位置不强造金标，所有指标带参考覆盖率。Judger 不进入产品控制链路，不启动既有官方内容判题。
