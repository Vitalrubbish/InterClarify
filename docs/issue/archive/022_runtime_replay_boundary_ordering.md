# Issue 022：Word回放拍界顺序与逐拍差异定位

状态：已取消（用户接受运行时抖动，不再排查）。日期：2026-10-20。父任务：017（已关闭的加载核验），关联：[005历史记录](https://github.com/Vitalrubbish/InterClarify/blob/3f470719bb0958546cc3c75e506cfb043b3fe438/docs/issue/archive/005_training_runtime_and_resource_probe.md)。本单元只排查受影响的001服务回归，不改模型权重、产品策略、输入清单或数值验收门槛。

## 问题与证据

017 r4真权重零更新已通过，但五例136拍服务回归只有4/5一致。第4例request=5（第6拍）在prompt_token_ids偏移71首次分歧：参考本拍为` bathroom with like`，集成为` bathroom with like the`；随后一拍分别为`the steam`与`steam`。前5拍prompt/生成IDs一致，分歧当拍生成IDs也一致。

首个非空Word为0.8120505698秒，名义第6拍为4.4120505698秒；`the`记录到达4.4136404991秒，晚约1.59ms。参考实际请求记录4.4147777241秒。当前回放两条路径各自按墙钟调度，未记录每个Word实际入队及每拍截窗时刻；因此尚不能区分调度/测试器抖动与运行时行为缺陷，不能以零更新通过代替服务回归通过。

来源：job-179242557114450383845-xuan-zhang、源码12d478a；完整第4例（旧报告已从工作树清理，原路径`reports/layer1_training/issue017-loading-20261019/r4-review/issue017-runtime-regression-r4/comparison/historical-4-independent_free_replay.json`）、回归摘要（旧报告已从工作树清理，原路径`reports/layer1_training/issue017-loading-20261019/r4-review/issue017-runtime-regression-r4/comparison/summary.json`）、审查报告（旧报告已从工作树清理，原路径`reports/layer1_training/issue017-loading-20261019/README.md`）。r4零更新退出0，服务回归退出1；失败原件保留，001原验收不改写。

## 关闭决定

2026-10-20用户明确将上述毫秒级拍界差异视为运行时抖动，要求直接关闭017。本排查单随之取消并归档，不增加观测、不修改回放器或X-Talk、不提交新测试作业。原始回归结果保留，不作为已修复行为缺陷记账。
