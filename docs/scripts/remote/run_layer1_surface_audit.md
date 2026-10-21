# Issue 073远端审计任务

`scripts/remote/run_layer1_surface_audit.sh`使用已有训练conda，串行检查数据及历史ASR轨迹，无类。入口要求冻结源码提交、独立新输出目录、既有040a数据和训练索引，不创建GPU服务。

任务限制单CPU亲和性、数值库线程1、worker0、4GiB虚拟地址空间、30分钟总时长、单文件256MiB、输出2GiB、空闲盘10GiB；nice 10运行，退出码、源码与环境身份写入本轮目录。此任务仅作有界CPU数据诊断，沿用既有远端轻量诊断方式；真实模型与集群测试仍须调度，本单不包含这些操作。

启动前核查`vc list`和磁盘，使用Git冻结worktree运行，不覆盖远端主仓库或040a数据。`ISSUE073_SOURCE_COMMIT`指定源码，`ISSUE073_OUTPUT`指定独立输出目录；所有逐条文本和原始ASR清单留远端，Git只回收统计、摘要及必要的简短复核记录。
