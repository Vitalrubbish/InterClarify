# NTF-054：执行线程与 complete 交接修复后的复测

2026-11-05 20:44复核：r2已在预热后的控制对照阶段失败，退出1，三条smoke样本尚未开始；正式30条及评分未提交。当前队列为空。自动衔接进程另于17:49:33因调度查询连接失败退出，不能继续将本轮状态表述为排队或自动推进。

## 固定条件

模型实现提交为 `65d15e6`，已推送GitHub。输入manifest SHA256为 `403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07`。比较对象是[修复前正式r2](../20261105-fdb30-half-duplex/README.md)。新版本固定SoulX回放线程、常驻X2辅助线程，各模型进程CPU计算线程为2，并跳过complete后的整段SenseVoice识别；短窗识别、reset、160ms联合发布及complete-only回答合同保持。

## 资源与步骤

远端队列检查为空；账户存储约186.90GB／1TB，可用约838GB，GPU配额8张。仅串行提交作业：smoke三条通过后正式30条，推理释放后单卡评分。推理3×4090、12CPU／64GiB、7200秒、每卡22GiB、输出2GiB、PCM16MiB；评分1×4090、4CPU／32GiB、3600秒。仅TOR与延迟，保留失败记录。

| 阶段 | run ID | job ID | 状态 |
| --- | --- | --- | --- |
| smoke-r1 | `ntf054-half-smoke-20261105-r1` | `job-179386787087491282885-xuan-zhang` | 已离队，无退出码／最终结果；衔接停止 |
| smoke-r2 | `ntf054-half-smoke-20261105-r2` | `job-179387030286102615198-xuan-zhang` | 约19:00退出1；控制对照失败，正式样本0/3 |
| formal-r2 | `ntf054-half-20261105-r2-formal` | 未提交 | smoke未通过 |
| score-r2 | `ntf054-half-20261105-r2-score` | 未提交 | 无正式推理结果 |

验收需核对新execution／ready预算、预热与正式SoulX线程ID、complete识别跳过事件、限定差异的控制对照、播放实录及完整固定分母。完成作业和低延迟分别报告，不能由本地146项检查推定GPU性能。

远端冻结目录为 `~/parathink-soulx-duplug/source/ntf054-65d15e6`，独立detached worktree，工作区干净。源码归档 `submit_logs/ntf054-65d15e6-source.tar.gz` 的SHA256为 `0b09c31e3054957869d59d7ce1f5f550f4971d97933f144e113252b4c8793e77`，与本地从同提交生成的scripts／configs归档一致；native_soulx.json的SHA256为 `128978377266770c1cdee4c244c81eefb3b3c85d7536b4707eff528e36412ba9`。四套推理conda均已核对存在，仅复用原资产。

## 顺序衔接

[衔接脚本](../../../scripts/remote/fdb30_retest_followup.md)的r2 PID2769918已退出，state为failed。其17:49:33调用`vc list`时调度接口10.24.18.34:6443拒绝连接，vc随后报告内部NameError并退出1，衔接脚本未重试而停止。该故障与稍后的模型控制对照失败分别记录。启动采样RSS为21976KiB；部署在 `submit_logs/ntf054-followup.py`，SHA256为 `c389f3ccb0fe18bfe27ba3ea921b3ac1e28b6a5b7c5fb693e6461a893f49cc31`，没有改变模型提交。进程原限制为单CPU、2GiB地址空间和12小时。

当前状态、日志、各阶段提交回执和审计分别保存在 `analysis/ntf054-half-campaign-20261105-r2/` 的state.json、campaign.log、*.submit.txt及*.audit.json。每30秒检查一次队列；前一作业离队、退出0且审计通过后才提交下一阶段，任何失败均记录并停止，无自动重跑。状态和来源摘要见[launch.json](launch.json)，其中attempt_history保留r1记录。衔接的3项本地检查已通过，覆盖错误线程／预算／跳过行为拒绝、单作业防重及失败退出码阻断。

## 重提记录

旧r1衔接于17:07:40记录`Job ended without successful exit marker`并退出，旧PID2603757已不在运行。按用户要求重提前再次确认队列为空、r2输出及状态目录未使用，保留旧目录；现有记录不足以判定旧作业被删除还是调度失败。源码工作区仍干净，模型提交、配置摘要、输入与资源不变，没有并行保留旧任务。

## 20:44状态核验与失败证据

本轮模型已成功加载，前端及X2实际CPU预算均为2／interop1，complete识别策略为跳过。两轮各59批预热完整，文字修订、有效complete、reset、WAIT、EOS及联合发布覆盖均为true。第一轮控制调用P95为108.53ms、最大1107.80ms，第二轮P95为106.58ms、最大108.33ms；这些是预热计算时间，不代表正式在线积压或TOR。

放行失败来自原生对照`passed=false`：complete分支第27步的整段重识别确实按授权省去，服务文字为空；但后续trace第192项在相同PCM摘要下，官方参考转写为`And moving into higher education back.`，适配路径为`I moving into higher education back.`。这超出只允许整段服务识别缺失的比较范围。现有快照没有证明差异是随机状态、数值执行或其他机制导致，不能直接放宽校验掩盖它。

result.json的cases为空，未开始三个正式smoke样本；formal及score目录不存在。此次检查没有重提新GPU任务或修改模型。复测工作仍未完成，应先定位该对照差异，并为调度查询临时失败补充受限重试，再重启后续流程。

机器可读证据见[status_20261105_2044.json](status_20261105_2044.json)，保存两轮预热、首次差异、衔接错误及五份远端证据SHA256；远端同名快照保存在r2 campaign目录的status_snapshot.json。
