# TextTurn 训练提交

对应 `scripts/remote/submit_textturn_training.sh`。用户已授权启动训练，实际提交前先用 `vc list` 核对单活动作业，再在独立冻结 worktree 设置 TEXTTURN_RUN_ID 运行本脚本。默认4090分区，1 GPU、8 CPU、32GiB，4h超时；源码、数据、模型及依赖均记录在 run 和 submit_logs。

本轮累计8 GPU小时限制由 run 台账管理，提交入口不自行追加第二个作业或重试训练。调度失败须保留原因；训练完成后再串行开展候选允许的评估。
