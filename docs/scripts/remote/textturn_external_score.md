# TT-011 外部回归评分

对应 `scripts/remote/textturn_external_score.py`。`score`读取已冻结的逐前缀审核和实际自由运行trace，依照首次可判定前缀的实际可见时间评估1000ms内有效stop；另列stop输出、影子生效、自然结束、当时不在Speak及观察不足，正常finish不计stop成功。未审核前缀保持unknown。

短附和的误stop仅统计已审核可见前缀；残字不继承未来完整文本。分列无更新stop、播放尾窗stop、普通及陈述start、finish后再次start。start是行为计数，接话语义和停顿语义覆盖不足保留空值；历史停止词锚点仅在原诊断文件中，不作为新主评分。清晰文本和录制ASR分别汇总，不把录制ASR称为本次真实识别。

`score_fdb`保留原两臂指标，再按动作实际返回时刻构造连续Speak区间，计算与首末有效ASR更新区间重叠严格大于960ms的行为，以及有新增转写窗口的stop。缺失转写时保留未知。FDB行为统计不能自动推断语义质量。输出逐例JSON／CSV和汇总JSON，与旧评分分开保存。
