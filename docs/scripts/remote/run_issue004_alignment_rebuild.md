# Issue 004 对齐后重建入口

`scripts/remote/run_issue004_alignment_rebuild.sh` 在调试机调用已有 `run_layer1_data.sh`，不定义业务类。入口先核对传入的 `ISSUE004_SOURCE_COMMIT` 与源码快照 HEAD，再固定已验真 UltraChat、发布 tokenizer、排除清单、4096 审计窗口和新的 `issue004-build-r4` 目录。`taskset` 限制单 CPU，`nice` 降低优先级，虚拟地址空间限制 2GiB，单文件上限 2GiB，外层 3600 秒；构建、审计、材料导出分别限制 1800/900/300 秒。输出目录已存在则拒绝覆盖。

这个入口只生成和审计新目录，不负责删除历史数据或填写人工签署。r3 的删除与 r4 的验证结果须在[019 工作单](../../issue/019_duplex_data_alignment_audit.md)登记。远端使用已有独立 conda 环境；机器通过后仍待用户人工审计。
