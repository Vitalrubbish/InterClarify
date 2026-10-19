# Issue 016：完成来源验真与训练／评测来源隔离登记

状态：完成，已归档。日期：2026-10-19。父任务：[004](004_training_data_and_annotation.md)。FDB补转写子任务及其阻塞条件按用户要求取消。

用户明确取消为FDB补119条转写及其训练阻塞条件。训练只读取固定UltraChat来源；FDB/FLEURS/历史五例单独保留，不进入训练、开发或checkpoint选择。已有转写的文本摘要仅作辅助重复检查，完整FDB文本覆盖不再是016完成条件，也不据此新增ASR/人工转写任务。

- [x] 保持唯一来源下载实例，十个固定shard已全部验真、下载退出0，另做独立流式复核通过。
- [x] 核对已登记外部来源与样本目录，保存已有文本及文件摘要；FDB无转写只列可选检查范围，不阻塞来源隔离登记。
- [x] 明确FDB原始ID与UltraChat ID命名空间不同，不用相同数字ID误排；按普通文本、每轮和完整对话摘要排除。
- [x] 修正构建工具与回归测试，明确reviewed表示来源清点及可用材料检查，text_coverage_complete单独报告；4项远端测试通过。

原清单有3325个文本摘要和1186条来源记录；119条FDB无转写是可选文本检查的范围限制，不再认定为任务缺口。旧报告保留原执行事实，新清单另记审查口径，不手改旧布尔值冒充覆盖完整。

实施选择：文本匹配沿用现有NFKC/词规范化摘要，增加对话各轮及连续完整文本的外部匹配；生成计划前过滤。已删除的工程/研究文档按用户要求保留删除，不重新创建。真实下载和完整材料核查仍是实际验收条件。

完成证据：提交d7b90ca，run_id为issue016-scope-correction-r2。远端清单已按新规则重建，reviewed/coverage_complete=true，text_coverage_complete=false；3325个辅助摘要与修正前完全一致，未伪造文本。新清单SHA256为6599f6968dfaf83185812eedceaace8e7a8ea5b57967a5ffa51269b3aec40944，旧清单另存原件。[范围修正报告](../../../reports/layer1_training/issue016-source-and-exclusions-20261019/scope_correction.json)及[测试原件](../../../reports/layer1_training/issue016-source-and-exclusions-20261019/scope_correction_tests.txt)齐全。004正式切分/人审、017真权重对照等仍独立验收。
