# 原1k ASR条件提交入口

`scripts/remote/submit_layer1_asr_training.sh`无类；要求`LAYER1_ASR_ROOT`指向已冻结worktree、`LAYER1_ASR_TRAIN_OUTPUT`为新目录，使用077 r2数据和078配置/协议。通过vc调度单4090/8CPU/32GiB、单任务、并发1，整任务timeout28800秒；现役训练conda，不复制权重。

提交前由执行方核查`vc list`与磁盘。真实训练入口核验所有证据、GPU和预算，先跑数据/加权目标/协议回归，正式单epoch训练后独立进程重载候选。不自动运行FDB或切换线上模型；退出码、收据和运行报告必须如实回收。
