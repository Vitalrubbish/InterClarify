# TextTurn 机会评分

对应 `scripts/training/score_textturn.py`，属于 TT-002 开发比较和 TT-004 文本评估。无需加载模型。

`score_predictions` 以冻结 opportunity_id 聚合完整窗口；正常接话及陈述句分别统计及时 start，打断统计及时 stop，停顿及附和统计发生任一错误动作的机会。正确 keep 数量不会稀释错误。缺失预测、报错或超长仍保留原计划分母，不能算成功等待。每项返回分子／分母、比例和 Wilson 95% 区间。

动作及时性以 allowed_visible_ms 为起点，加上观察窗关闭前的等待和实测动作耗时；控制耗时与480ms窗内等待分开。`score_file` 保存逐机会 CSV 及 JSON 汇总；离线给定状态结果明确记录为诊断，无法替代 Nemotron 在线、Context 一致性或实际播放验收。

v2修复：`outcome_metric`统一汇总pass/fail/unknown、已判定覆盖、实际错误与计划分母上下界。缺失预测为unknown；若已观测到明确错误，仍判fail并另保留缺失。误动作率只统计实际错误，不再把缺失伪装成错误；机会分数用保守上界扣除未知，避免漏预测反而提高分数。原始全窗完整结果不受影响，新增字段解释分母，CSV采用LF。

TT-010完整轨迹的listen和首个start前inter_chunk_gap窗口，按同scenario合并进smooth接话机会；否则只评分start锚点会漏掉用户尚在输入时的错误start。暂停仍独立统计禁抢话，打断后Listen继续输入不并入先前接话机会。仅对带scenario_variant的新格式应用映射，旧冻结类别评分不变。
