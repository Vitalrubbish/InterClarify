# Issue 022：Word回放拍界顺序与逐拍差异定位

状态：待办。日期：2026-10-20。父任务：[017](017_training_loader_zero_update.md)，关联：[005](005_training_runtime_and_resource_probe.md)。本单元只排查受影响的001服务回归，不改模型权重、产品策略、输入清单或数值验收门槛。

## 问题与证据

017 r4真权重零更新已通过，但五例136拍服务回归只有4/5一致。第4例request=5（第6拍）在prompt_token_ids偏移71首次分歧：参考本拍为` bathroom with like`，集成为` bathroom with like the`；随后一拍分别为`the steam`与`steam`。前5拍prompt/生成IDs一致，分歧当拍生成IDs也一致。

首个非空Word为0.8120505698秒，名义第6拍为4.4120505698秒；`the`记录到达4.4136404991秒，晚约1.59ms。参考实际请求记录4.4147777241秒。当前回放两条路径各自按墙钟调度，未记录每个Word实际入队及每拍截窗时刻；因此尚不能区分调度/测试器抖动与运行时行为缺陷，不能以零更新通过代替服务回归通过。

来源：job-179242557114450383845-xuan-zhang、源码12d478a；[完整第4例](../../reports/layer1_training/issue017-loading-20261019/r4-review/issue017-runtime-regression-r4/comparison/historical-4-independent_free_replay.json)、[回归摘要](../../reports/layer1_training/issue017-loading-20261019/r4-review/issue017-runtime-regression-r4/comparison/summary.json)、[审查报告](../../reports/layer1_training/issue017-loading-20261019/README.md)。r4零更新退出0，服务回归退出1；失败原件保留，001原验收不改写。

## 工作项与验收

- [ ] 先登记对照说明，补充两路径Word实际投递、队列变更与tick截窗观测；明确首拍锚点及同刻事件排序，不将请求发出时刻直接当作截窗时刻。
- [ ] 从固定五例输入构建边界诊断，解释首处分歧；保留双方独立生成历史及完整原始IDs，识别测试器责任或运行时责任。
- [ ] 依据证据修复相应最小模块并同步同路径中文说明、相关测试；如需改变回放协议，先登记理由、适用范围和旧新证据关系，不静默替换原验收。
- [ ] 在远端独立conda、最多1×4090/8CPU/32GiB、单次回归600秒/输出5GiB预算内，用新run_id完成固定五例回归并核对136拍prompt/生成IDs、历史、控制和正文；失败不得挑选性丢弃。
- [ ] 回收退出码、原始时间线、来源摘要与资源结果后回填017关闭决策。若只能确认失败，继续保持017和训练门禁未通过，不通过反复重试挑选成功结果。

本次只登记问题，未修改回放器或X-Talk实现，未执行新的诊断作业。
