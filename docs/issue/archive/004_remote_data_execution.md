# Issue 004 远端数据执行任务单

状态：完成，已归档。父任务：[004](004_training_data_and_annotation.md)。

最终run_id为`issue004-build-r5`，源码`7cda3b1`。调试节点`d6-hpc-debuggpu-001`使用独立conda：CPU0、nice10、2GiB虚拟地址空间、单文件2GiB、目录10GiB、可用磁盘保留5GiB；构建1800秒、机器审计900秒、外层3600秒。最多一个生成进程，无GPU。34项相关测试通过，正式构建与审计退出0。

使用[受限重建入口](../../scripts/remote/run_issue004_alignment_rebuild.md)，冻结checkout HEAD为ISSUE004_SOURCE_COMMIT；从源码配置生成有效配置，保存摘要。输入是已验真的十个UltraChat shard、发布tokenizer与已审查外部排除清单。只抽取6000条，过滤后5278候选，切分1000/200/300；数值规范化及原文两个域均检查重复。输出目录拒绝覆盖，恢复要求构建身份和代码摘要完全一致。

用户取消r5新增人工审查，入口显式传递豁免理由，构建身份和human_review记录一致；不导出review目录，不伪造签署。机器通过后回收[机器原件](../../../reports/layer1_training/issue004-build-20261019-r5/completed/audit.json)，训练正文和序列留远端。r4生成目录及仓库旧副本已按授权删除；r5-attempt1在规则完善时取消，不作为正式交付。

数据关闭条件满足，训练仍受005/007约束。实际输出根为`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue004-build-r5/`。
