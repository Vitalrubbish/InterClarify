# 对齐验证作业入口

`scripts/remote/run_layer1_alignment.sh`在已分配的一张4090和独立conda中执行036验证，不自行提交其他任务。无类。入口检查调度作业、单GPU、BF16、conda身份及磁盘余量，冻结源码与环境；限制CPU线程4、禁用数据worker/在线模型下载，外层1小时硬超时，记录退出码。变量沿用`LAYER1_TRAIN_ROOT`、`LAYER1_TRAINING_ROOT`、`LAYER1_TRAINING_ENV`、`LAYER1_TRAIN_OUTPUT`，模型与官方源码路径可显式传入。
