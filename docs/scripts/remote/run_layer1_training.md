# 远端训练及资源短跑入口

`scripts/remote/run_layer1_training.sh`要求冻结源码、独立训练conda、唯一新输出目录及受调度的一张24GiB4090。无类；检查JobID及CUDA/NVIDIA设备分配，记录源码、环境、GPU，随后调用串行probe编排模块。

必填`LAYER1_TRAIN_ROOT`、`LAYER1_TRAINING_ROOT`、`LAYER1_TRAINING_ENV`、`LAYER1_TRAIN_OUTPUT`。模型和官方源码默认只读复用现有资产。申请8CPU/32GiB/1GPU，线程最多4、禁core dump，不限制CUDA虚拟地址空间；单阶段最多900秒、整体5400秒，外层调度命令限5700秒，最多一个GPU作业。输出目录拒绝覆盖；退出码含失败写入exit_code.txt。

只执行005短跑，不能运行三组正式适配或通过007/008。训练资产留远端，回收JSON、少量日志和摘要，避免把大checkpoint提交Git。
