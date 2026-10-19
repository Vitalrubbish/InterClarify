# Issue 016：完成来源验真与外部评测排除清单

状态：进行中。日期：2026-10-19。父任务：[004](004_training_data_and_annotation.md)。用户授权优先推进来源与排除工作。

- [x] 保持唯一来源下载实例，十个固定shard已全部验真、下载退出0，另做独立流式复核通过。
- [ ] 从实际FLEURS 100条、历史五例和完整FDB材料提取文本摘要、来源ID与逐文件摘要，拒绝空覆盖或缺字段。
- [x] 明确FDB原始ID与UltraChat ID命名空间不同，不用相同数字ID误排；按普通文本、每轮和完整对话摘要排除。
- [x] 交付构建工具、3项远端测试、同路径说明和实际清单；119条无转写记录missing，reviewed=false。

实际清单：训练根manifests/exclusions.json，3325个规范化文本摘要、1186条逐文件来源记录。FLEURS含100 test+1 dev，历史5例，FDB五子集727例目录齐全；candor_turn_taking的119例仅有时间标注，均无transcription.json，文本覆盖未完成，不伪造reviewed=true。证据与缺测ID见[排除覆盖](../../reports/layer1_training/issue016-source-and-exclusions-20261019/exclusion_coverage.json)。本issue保持进行中以跟踪实际缺口。

实施选择：文本匹配沿用现有NFKC/词规范化摘要，增加对话各轮及连续完整文本的外部匹配；生成计划前过滤。已删除的工程/研究文档按用户要求保留删除，不重新创建。真实下载和完整材料核查仍是实际验收条件。
