# Issue 028：移除真实清单开训限制

2026-10-20按用户澄清修正027：006先用模仿Nemotron输入形式的合成轨迹适配，真实录音清单不应成为开训前置。本修正保留原始r5数据、三训练臂、512窗口及预算。

`release_blockers`删除对真实`acceptance.sample_manifest`的依赖。合成dev资产改为`text_dev_manifest`、`dev_selection_config`、`evaluator`；前者直接绑定004已审计的r5 manifest及摘要，其中已含200条文本dev，不新增录音采集任务。

[9项本地回归](tests.txt)在conda `interclarify-tts-bench`全部通过：真实清单为空或尚未交付时不阻断合成训练；合成dev清单缺失/引用错误、资产摘要变更、选择配置缺失及其他训练预算错误仍拒绝。该检查未启动GPU或正式训练，未重复执行未改动的张量恢复测试。

[当前准备状态](readiness.json)不再包含真实清单缺项。仍需交付合成dev评测器与评价/选择配置，再更新准备状态和放行标记；不直接将`training_released`设为true。真实清单在后续迁移验收前准备，合成评测改善与真实Nemotron效果分别报告。

027的计划及远端日志保留历史执行事实，其报告已注明旧门禁被本修正取代。用户原有工作区变更未纳入本次提交。
