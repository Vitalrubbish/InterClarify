# FDB周期对照的串行续接

对应 `scripts/remote/continue_textturn_fdb.sh`，属于TT-007，无类。只在用户授权的新对照测试中使用。

脚本以已有conda CPU环境记录`submit_logs/<run_id>.pipeline.json`。取得独立文件锁，等待`TEXTTURN_PREDECESSOR_RUN`对应run的退出码，再确认`vc list`没有活动作业；原作业成功退出且释放GPU后才调用共用提交器。

`state`持久化等待、提交、停止和实际调度返回。原作业失败、超出7800秒等待期限、累计预算不足或调度提交失败都会明确记录停止原因；不重复申请GPU，也不扩展原预算。真正提交时由共用提交器重新读取实际StartTime／EndTime，不能在等待时提前估算额度。

设置`TEXTTURN_RUN_ID`、`TEXTTURN_PREDECESSOR_RUN`、`TEXTTURN_FDB_MANIFEST`及`TEXTTURN_FDB_CONFIG`，在冻结源码worktree启动。续接器仅单线程、无模型、无GPU；可以在远端后台等待，但它的waiting状态不能称已提交GPU作业。状态包含submitted和实际调度编号时才表示提交完成。同一run已有状态文件时拒绝再次启动。

2026-10-25运行核查发现：原后台进程已退出，但状态文件仍停在waiting，日志为空，现有证据不足以确定退出原因。waiting文件不能证明续接进程仍存活或已经提交。此次保留旧状态，核对前序成功和无活动作业后，直接使用共用提交器补交，pipeline记录恢复方式和真实调度编号。没有据此修改冻结模型、输入或扩大预算。
