# 新版数据pilot集群执行

`run_textturn_repair_pilot.sh`只在调度计算节点运行，在既有conda环境串行训练旧／新pilot。固定一GPU、8CPU、32GiB内存，线程≤8，不启动数据worker；不设置应用层训练总时限，有限遍历自然结束。每10秒核对显存22GiB、资产10GiB、报告2GiB及空盘30GiB停止线，失败终止整个进程组并保存退出码。源码摘要、包版本、资源日志和训练日志按独立run保存。

`submit_textturn_repair_pilot.sh`检查唯一活动作业、数据审核与摘要、冻结源码和新run目录，再以单卡24GiB的A10分区提交一个作业。旧／新pilot属于同一作业中的串行阶段，不恢复full或TT-011。提交不等于实际训练，必须根据调度状态及首个更新日志确认。
