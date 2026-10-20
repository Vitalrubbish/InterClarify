# 首轮四配置作业入口

`scripts/remote/run_layer1_round1.sh`无类；在一个受调度单GPU作业中登记B0并串行调用T1/T2/T3单臂入口。沿用`LAYER1_TRAIN_ROOT`、`LAYER1_TRAINING_ROOT`、`LAYER1_TRAINING_ENV`，轮次根目录使用`LAYER1_ROUND_OUTPUT`且拒绝覆盖。

先核验独立conda与调度器身份、磁盘和正式计划，运行12项适配契约及已有CPU张量恢复测试。B0只保存官方资产引用及零优化器步状态；没有虚构训练或FDB评测结果。

每个训练臂有独立输出，记录开始、结束、退出码及资源摘要。任一失败立即停止后续臂，轮次状态列出未执行条件，保留失败及已有checkpoint；只有三臂均退出0且summary通过才标记执行完成。训练成功不表示FDB或内容检查通过。

调度资源固定1×4090、8CPU、32GiB物理内存，线程4、禁core dump；物理主存由调度器cgroup约束，不设置妨碍CUDA映射的虚拟地址上限。每臂8小时/5GiB，轮次16GiB输出/至少15GiB空闲；外层timeout为87,000秒，TERM后30秒KILL。输出阶段记录与日志增量保存，不在人为占GPU的空循环中等待。
