# 提交 UltraChat 重测

对应 `scripts/remote/submit_textturn_ultrachat.sh`。无类。入口要求独立RUN_ID和已冻结MANIFEST，使用现有conda数据环境在登录节点做轻量核查。通过提交锁、活动作业查询和不覆盖检查，防止并发及覆盖历史产物。

提交前从vc三日历史逐项查询所有TextTurn作业实际StartTime／EndTime，包含失败和撤回作业，累计不得少于已核查的21251秒，并强制包含训练、旧验收及160ms FDB记录。原8 GPU小时扣实际累计，再预留60秒清理，上限7200秒；余额不足启动即拒绝。核对固定adapter摘要，预算和调度原文先落盘，再提交1卡、8CPU、32GiB、单任务。任务内两个周期串行；没有另开额度或后台续接器。

调度日志、budget.json及submission.txt位于根目录submit_logs，实际源码使用独立冻结worktree。重复提交必须使用新运行编号，重新核对所有已发生占卡时间。
