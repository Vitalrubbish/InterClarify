# TextTurn修复配置

`configs/textturn_repair.json`冻结20261027种子、160ms发布、独立生成／播放、100000／10000快照预算、100／20来源目标、2048输入上限和CPU单线程／2GiB起始限制。构造时限明确为1800秒，磁盘上限2GiB，以压缩完整快照保存；不沿用旧512MiB上限删除数据。`configs/textturn_repair_pilot.json`冻结有限pilot参数，每臂最多5轮，完整词表CE、学习率1e-4、组内三类等份合并及统一clip1，正式full和外部测试关闭。
