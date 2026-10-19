# Issue 014：实际释放远端冗余缓存空间

状态：完成，2026-10-19。范围：用户要求归拢后直接释放可清理资产占用，不涉及其他项目。

- [x] 核对现行脚本、活动进程/任务和原始结果，采用精确清单串行执行，不全盘高并发扫描。
- [x] 删除14个已结束TTS实验的Inductor/Triton编译缓存，不删除原始WAV、日志和JSON。
- [x] 删除已退役的Nemotron多语、旧Python Kyutai和Pocket候选权重及2套专用环境；保存模型配置/来源摘要和conda/pip清单，没有再复制权重。
- [x] 当前Nemotron EN、Kokoro、Pocket环境种子、Rust Kyutai参考和独立训练prefix保留，当前客户端导入及19个删除目标不存在检查通过。
- [x] 记录逐目标磁盘块计量及失败/恢复操作，未新增集群作业；本轮删除前目标占用合计约20.58GiB，不冒充共享配额差值实测。

[执行报告](../../../reports/maintenance/20261019-cache-reclamation/README.md)。原件位于远端 `interclarify-archive/maintenance/cache-reclamation-20261019/`。011清理和012归拢的历史结论保留，本轮收益独立计量；不改变训练门禁。任务完成归档。
