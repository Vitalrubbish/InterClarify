# X2与SoulX同卡作业入口

`scripts/remote/run_x2_teacher_fdb.sh`复用ASR／SoulX两套conda，在调度分配的同一张4090启动独立进程，以私有Unix socket通信。必须给出冻结`SOULX_SOURCE`、独立`SOULX_RUN_ID`和`SOULX_FDB_MANIFEST`。目录存在即失败，源码／输入摘要写入run；与其他前端共用排他锁。

默认执行固定30条；`SOULX_TEACHER_SMOKE=1`只取三轴各一条作预检。X2先完成两会话真实语音预热，再启动SoulX并沿用旧预热合同。进程显存配额分别55%和35%，合计采样超22528MiB、结果超128MiB或运行超1700秒立即停止，外层调度1800秒；1GPU／4CPU／32GiB，数值库每进程最多2线程，作业内离线。

回放结束调用原三轴分析和X2归因分析，对照远端冻结r6目录。退出保留回放实际退出码，清理模型进程和私有socket，不删除历史结果。
