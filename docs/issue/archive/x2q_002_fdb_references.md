# X2Q-002：FDB 输入清单与核验参考

状态：已取消，2026-10-22 归档。用户决定不再执行本轮 FDB 测试，以下为取消前的工作范围。后续数据核查见 [FLEURS 记录](../../dev/X2-Turn/fleurs_subset_verification.md)。

## 目标

冻结远端 FDB v1.0 四项预期 672 例及 v1.5 user_backchannel 99 场景的实际清单，建立可靠转写、目标用户发声区间和最终发声末端。禁止用旧系统输出或未经听审的 ASR 草稿冒充金标。

## 交付

- `scripts/remote/x2_turn_fdb_data.py` 及 `docs/scripts/remote/x2_turn_fdb_data.md`。
- 含输入/标注哈希、声道说明、转写来源、对齐与人工核验版本的远端 manifest；缺失、混合说话人和局部参考单列。
- 不改变原始音频时长、静音和样本分组的输入规范，以及每项指标的 eligible/total。

## 验收

确认 metadata 事件时间不被当成真实发声结束；局部参考不比较整段转写；参考不进入在线模型。数据/对齐使用隔离 conda 与资源上限，更新镜像说明后再归档。
