# 正式第二轮T2训练入口

`scripts/remote/run_layer1_t2_round2.sh`在单GPU调度作业中执行完整T2第二轮，不运行短跑。无类。启动时检查conda、单张4090/BF16、完整配置与用户短跑豁免，保存源码摘要和环境。调用正式训练器完成1,000条T2、2,428序列、1,214步；2e-5、warmup122、控制权重1/10/5/2/1，只更新112个已有LoRA张量。

资源为1×4090/8CPU/32GiB、并发1、数据worker0，CPU线程4，整个任务最长8小时；训练子进程最多27,900秒，最终干净进程候选加载最多900秒。单训练目录5GiB，总目录6GiB，空闲保留5GiB。保存203/406/609/812/1015/1214步，全部检查点保留；最终epoch用于后续测试。失败保留日志/退出码，不自动缩窗或重启。输出必须全新，不覆盖首轮。

变量使用`LAYER1_TRAIN_ROOT`、`LAYER1_TRAINING_ROOT`、`LAYER1_TRAINING_ENV`、`LAYER1_TRAIN_OUTPUT`，可覆盖模型与官方源码位置。正式训练结束后执行`run_layer1_alignment.py verify --formal`，核验全参数摘要及生成IDs。未启动FDB重测，后续仍由037跟踪。
