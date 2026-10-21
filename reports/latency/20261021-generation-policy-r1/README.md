# Issue 061：显式生成参数验证

状态：完成，退出码0。线上服务新策略为`duplex_greedy_v1`：显式greedy、单beam、repetition_penalty=1.0，采样参数关闭，不继承模型目录配置。服务health与每次完成统计登记相同策略，固定请求探针自动拒绝规则缺失/改变。

固定049同一108对历史prompt，验证新策略的缓存有/无对齐情况；旧输出不作为新策略答案。首段300ms、后续1200ms、600ms micro-turn、BF16与权重保持原条件。完整对话/自然度不在本轮重测。

本地conda：9项模型服务/缓存测试及3项延迟/策略测试通过。远端额度1×4090/8CPU/32GiB、1小时、线程2、单并发，输出1GiB上限。独立源码根`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-generation-policy-20261021-r1/source`，结果留同根上级output，原始trace不提交Git。

任务ID：`job-179255097501464783961-xuan-zhang`，已进入Running；服务完成历史权重校验后执行新策略。

## 实测结果与远端同步

固定108对请求全部生成ID一致，此前150-token输入的三次重复均一致；每个响应的显式策略与health登记相同。机器摘要见[summary.json](summary.json)，包含原始结果哈希、任务ID及远端主仓库提交。此次结果确认该固定语料通过，不承诺所有BF16输入逐token恒等。

远端`/hpc_stor03/sjtu_home/xuan.zhang/InterClarify`已fast-forward到`30f0e7ae708ca222058cf5c2aad91f6a393774a9`，新默认策略代码已在主源码入口可用，其他未提交文件保持。没有在登录节点启动或保留常驻模型服务；后续从更新后的源码启动服务时自动生效。旧冻结快照和旧测量保留原参数，不能与新策略结果混作同一条件。

原始probe/trace留远端output，约10.6MiB，不提交Git；本次未重新测量端到端延迟、自然度或完整FDB控制行为。本地13项相关测试通过，远端9项模型服务/缓存及3项延迟/策略测试通过。
