# TT-011 远端执行合同

对应 `configs/textturn_external_evaluation.json`。绑定TT-010完整轨迹训练run、调度ID、源码和manifest摘要；训练成功后固定候选，不改模型或阈值。两项新run均为20261026-r1，先UltraChat，再FDB。

仅执行160ms，UltraChat每周期3 token，比TT-010平均每160ms约8/3 token略快；不做因果对照。每项单卡24GiB／8CPU／32GiB／7200秒，预留60秒清理；显存22GiB、资产10GiB、报告2GiB、可用盘30GiB停止线。等待训练截止2026-10-26 03:00（北京时间），保留训练自身13800秒／外层4小时限制。本配置没有累计GPU秒配额。
