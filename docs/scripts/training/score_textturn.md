# TextTurn 机会评分

对应 `scripts/training/score_textturn.py`，属于 TT-002 开发比较和 TT-004 文本评估。无需加载模型。

`score_predictions` 以冻结 opportunity_id 聚合完整窗口；正常接话及陈述句分别统计及时 start，打断统计及时 stop，停顿及附和统计发生任一错误动作的机会。正确 keep 数量不会稀释错误。缺失预测、报错或超长仍保留原计划分母，不能算成功等待。每项返回分子／分母、比例和 Wilson 95% 区间。

动作及时性以 allowed_visible_ms 为起点，加上观察窗关闭前的等待和实测动作耗时；控制耗时与480ms窗内等待分开。`score_file` 保存逐机会 CSV 及 JSON 汇总；离线给定状态结果明确记录为诊断，无法替代 Nemotron 在线、Context 一致性或实际播放验收。
