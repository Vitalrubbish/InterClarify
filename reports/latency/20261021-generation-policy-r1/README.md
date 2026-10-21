# Issue 061：显式生成参数验证

状态：已提交，结果待回收。线上服务新策略为`duplex_greedy_v1`：显式greedy、单beam、repetition_penalty=1.0，采样参数关闭，不继承模型目录配置。服务health与每次完成统计登记相同策略，固定请求探针自动拒绝规则缺失/改变。

固定049同一108对历史prompt，验证新策略的缓存有/无对齐情况；旧输出不作为新策略答案。首段300ms、后续1200ms、600ms micro-turn、BF16与权重保持原条件。完整对话/自然度不在本轮重测。

本地conda：9项模型服务/缓存测试及3项延迟/策略测试通过。远端额度1×4090/8CPU/32GiB、1小时、线程2、单并发，输出1GiB上限。独立源码根`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-generation-policy-20261021-r1/source`，结果留同根上级output，原始trace不提交Git。

任务ID：`job-179255097501464783961-xuan-zhang`，已进入Running；服务完成历史权重校验后执行新策略。
