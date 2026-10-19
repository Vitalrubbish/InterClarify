# Issue 004 对齐后重建入口

`scripts/remote/run_issue004_alignment_rebuild.sh` 在调试机调用已有 `run_layer1_data.sh`，不定义业务类。入口先核对传入的 `ISSUE004_SOURCE_COMMIT` 与源码快照 HEAD，再固定已验真 UltraChat、发布 tokenizer、排除清单、4096 审计窗口和新的 `issue004-build-r5` 目录。`taskset` 限制单 CPU，`nice` 降低优先级，虚拟地址空间限制 2GiB，单文件上限 2GiB，外层 3600 秒；构建、审计、材料导出分别限制 1800/900/300 秒。输出目录已存在则拒绝覆盖。

这个入口只生成和审计新目录，不负责删除历史数据或填写人工签署。r3 的删除与 r4 的验证结果见[019归档工作单](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/019_duplex_data_alignment_audit.md)。远端使用已有独立 conda 环境；r5机器通过后按用户豁免授权完成数据交付。

r5入口改用源码自带配置，在运行前复制成仅改变磁盘预算为10GiB的冻结有效配置；输出固定issue004-build-r5，用户豁免理由显式传递，不再导出人工审查。r5完成后删除r4。
