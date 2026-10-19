# 单卡零更新验证入口

`scripts/remote/run_layer1_zero_update.sh`在获分配单张4090上执行005加载测试、推理服务回归和独立零更新对照，无类。明确冻结源码、独立conda、官方/base/checkpoint目录、新输出和GPU分配，依赖版本用标准库读取。

显式变量LAYER1_ZERO_ROOT、LAYER1_TRAINING_ENV、LAYER1_ZERO_OUTPUT；资产可通过LAYER1_MODEL_HOME/LAYER1_OFFICIAL_SOURCE指定。最大线程4，虚拟地址空间28GiB，测试各120秒、外层对照1500秒，禁core dump；申请8CPU/32GiB/1×24GiB4090，整体墙钟1800秒，输出预算5GiB。集群实际规则为每张GPU最多8CPU/32GiB，最初64GiB申请被拒绝后下调，不通过多申请GPU绕过。两个模型干净进程串行加载，源码/资产/logits/参数摘要和失败日志保留，退出码写入产物。

该入口只跑零更新，不训练，不在调试机加载7B权重。服务恢复逻辑共用后必须重跑受影响的001原始Word对照，不能仅凭HTTP替身测试宣称真实服务回归完成。
