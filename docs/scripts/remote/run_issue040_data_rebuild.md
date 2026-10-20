# Issue 040 数据重建任务单

`scripts/remote/run_issue040_data_rebuild.sh` 在远端独立冻结源码中重建下一无文本拍启动的数据，无类，不训练模型。入口要求 `ISSUE040_SOURCE_COMMIT` 等于当前提交；使用现役 conda、原 UltraChat、官方 tokenizer、原排除表和同一种子，构建后审计与冻结 r5 的身份、正文、跨度和随机事件一致性。新目录固定为 `issue040-delayed-start-data`，已存在则拒绝覆盖。

资源为单 CPU、nice 10、线程 1、虚拟地址空间 2GiB、单文件 2GiB、目录 10GiB、空闲盘至少 5GiB；无 GPU、并发 1。构建/审计/统计分别限时 1800/900/300 秒。运行前检查 `vc list` 和磁盘，轻量 CPU 数据任务沿用 r5 的调试机受限执行方式；集群模型测试仍须调度。

输出包括配置、源码提交、环境、构建日志、审计、退出码及 `sequence_inventory.json`。清点 train 的三视图完整 2048 序列、监督 token、每 epoch 有效 batch 2 的步数、向上取整 10% warmup 预估；仅供下一实验冻结，不能替代训练器放行索引或自动启动第三轮。dev/test 原分区不参与训练清点，人审状态按当前数据单独保持 pending，不继承 r5 豁免。

在冻结源码根目录执行 `ISSUE040_SOURCE_COMMIT=<commit> bash scripts/remote/run_issue040_data_rebuild.sh`。保留失败目录，不删旧结果腾空间。完成后将摘要和日志复制回本地报告，Issue 040 仍跟踪训练与重测。
