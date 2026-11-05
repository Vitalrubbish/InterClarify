# NTF-054：执行线程与 complete 交接修复后的复测

2026-11-05 21:22最新状态：按用户明确指令取消完整系统的原生控制一致性检查，停止修复短窗变化；新源码固定82ff9ba，r3 smoke作业job-179388489846387768877-xuan-zhang已提交，当前Pending。顺序衔接PID3997827已启动，状态waiting_smoke；smoke通过后才提交正式30条及TOR／延迟评分。完整预热、线程预算、跳过事件、录音和资源审计保留，未执行的对照明确记为disabled_by_user／passed=null。提交证据见[launch_r3.json](launch_r3.json)。

21:04后原因调查已完成，见[失败分析](failure_analysis.md)：真实权重基线完整复现原3处差异；仅补齐被省去的 CPU 特征提取后，随机状态与275条对照轨迹全部一致。根因为 complete 整段识别省略后 dither 的 CPU RNG 消耗发生偏移。诊断不代表正式复测已通过；推理修复、三条smoke、固定30条和评分仍待恢复。

2026-11-05 20:44复核：r2已在预热后的控制对照阶段失败，退出1，三条smoke样本尚未开始；正式30条及评分未提交。当前队列为空。自动衔接进程另于17:49:33因调度查询连接失败退出，不能继续将本轮状态表述为排队或自动推进。

## 固定条件

当前r3实现提交为 `82ff9ba`，历史r2为 `65d15e6`，均已推送GitHub。输入manifest SHA256为 `403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07`。比较对象是[修复前正式r2](../20261105-fdb30-half-duplex/README.md)。新版本固定SoulX回放线程、常驻X2辅助线程，各模型进程CPU计算线程为2，并跳过complete后的整段SenseVoice识别；短窗识别、reset、160ms联合发布及complete-only回答合同保持。r3按用户指令取消原生控制对照。

## 资源与步骤

r3提交前队列为空；账户存储约186.67GB／1TB，GPU配额8张。仅串行提交作业：smoke三条通过后正式30条，推理释放后单卡评分。推理3×4090、12CPU／64GiB、7200秒、每卡22GiB、输出2GiB、PCM16MiB；评分1×4090、4CPU／32GiB、3600秒。仅TOR与延迟，保留失败记录。

| 阶段 | run ID | job ID | 状态 |
| --- | --- | --- | --- |
| smoke-r1 | `ntf054-half-smoke-20261105-r1` | `job-179386787087491282885-xuan-zhang` | 已离队，无退出码／最终结果；衔接停止 |
| smoke-r2 | `ntf054-half-smoke-20261105-r2` | `job-179387030286102615198-xuan-zhang` | 约19:00退出1；控制对照失败，正式样本0/3 |
| formal-r2 | `ntf054-half-20261105-r2-formal` | 未提交 | smoke未通过 |
| score-r2 | `ntf054-half-20261105-r2-score` | 未提交 | 无正式推理结果 |
| smoke-r3 | `ntf054-half-smoke-20261105-r3` | `job-179388489846387768877-xuan-zhang` | 21:22为Pending，已取消原生控制对照 |
| formal-r3 | `ntf054-half-20261105-r3-formal` | 待smoke通过后提交 | 顺序衔接已启动 |
| score-r3 | `ntf054-half-20261105-r3-score` | 待正式推理通过后提交 | 仅TOR／延迟 |

验收需核对新execution／ready预算、预热与正式SoulX线程ID、complete识别跳过事件、播放实录及完整固定分母。r3只核对一致性检查的明确取消记录，不执行原生对照；r2限定差异对照结果保留作历史证据。完成作业和低延迟分别报告，不能由本地回归推定GPU性能。

远端冻结目录为 `~/parathink-soulx-duplug/source/ntf054-65d15e6`，独立detached worktree，工作区干净。源码归档 `submit_logs/ntf054-65d15e6-source.tar.gz` 的SHA256为 `0b09c31e3054957869d59d7ce1f5f550f4971d97933f144e113252b4c8793e77`，与本地从同提交生成的scripts／configs归档一致；native_soulx.json的SHA256为 `128978377266770c1cdee4c244c81eefb3b3c85d7536b4707eff528e36412ba9`。四套推理conda均已核对存在，仅复用原资产。

## 顺序衔接

r3使用新源码内的衔接脚本，SHA256为7e876b2e2fdf58133d0dec0d64cf8b09b2367c986883e9a8c287f0e7d472c9db；PID3997827，绑定单CPU、2GiB地址空间、最长12小时。只读队列查询最多4次尝试，5／15／30秒退避，失败不按空队列处理；提交不自动重试。r3状态、日志及提交回执位于analysis/ntf054-half-campaign-20261105-r3/。r3源码目录为source/ntf054-82ff9ba，独立干净detached worktree；scripts／configs归档SHA256为e593ef2bc3b92c2800053ff4ff4b0f9d8e36b1577158dd32034e55e538f8bf05，与本地一致；配置及输入摘要与r2相同。本地153项完整回归及编译、空白检查通过。

[衔接脚本](../../../scripts/remote/fdb30_retest_followup.md)的r2 PID2769918已退出，state为failed。其17:49:33调用`vc list`时调度接口10.24.18.34:6443拒绝连接，vc随后报告内部NameError并退出1，衔接脚本未重试而停止。该故障与稍后的模型控制对照失败分别记录。启动采样RSS为21976KiB；部署在 `submit_logs/ntf054-followup.py`，SHA256为 `c389f3ccb0fe18bfe27ba3ea921b3ac1e28b6a5b7c5fb693e6461a893f49cc31`，没有改变模型提交。进程原限制为单CPU、2GiB地址空间和12小时。

当前状态、日志、各阶段提交回执和审计分别保存在 `analysis/ntf054-half-campaign-20261105-r2/` 的state.json、campaign.log、*.submit.txt及*.audit.json。每30秒检查一次队列；前一作业离队、退出0且审计通过后才提交下一阶段，任何失败均记录并停止，无自动重跑。状态和来源摘要见[launch.json](launch.json)，其中attempt_history保留r1记录。衔接的3项本地检查已通过，覆盖错误线程／预算／跳过行为拒绝、单作业防重及失败退出码阻断。

## 重提记录

旧r1衔接于17:07:40记录`Job ended without successful exit marker`并退出，旧PID2603757已不在运行。按用户要求重提前再次确认队列为空、r2输出及状态目录未使用，保留旧目录；现有记录不足以判定旧作业被删除还是调度失败。源码工作区仍干净，模型提交、配置摘要、输入与资源不变，没有并行保留旧任务。

## 20:44状态核验与失败证据

本轮模型已成功加载，前端及X2实际CPU预算均为2／interop1，complete识别策略为跳过。两轮各59批预热完整，文字修订、有效complete、reset、WAIT、EOS及联合发布覆盖均为true。第一轮控制调用P95为108.53ms、最大1107.80ms，第二轮P95为106.58ms、最大108.33ms；这些是预热计算时间，不代表正式在线积压或TOR。

放行失败来自原生对照`passed=false`：complete分支第27步的整段重识别确实按授权省去，服务文字为空；但后续trace第192项在相同PCM摘要下，官方参考转写为`And moving into higher education back.`，适配路径为`I moving into higher education back.`。这超出只允许整段服务识别缺失的比较范围。现有快照没有证明差异是随机状态、数值执行或其他机制导致，不能直接放宽校验掩盖它。

result.json的cases为空，未开始三个正式smoke样本；formal及score目录不存在。此次检查没有重提新GPU任务或修改模型。复测工作仍未完成，应先定位该对照差异，并为调度查询临时失败补充受限重试，再重启后续流程。

机器可读证据见[status_20261105_2044.json](status_20261105_2044.json)，保存两轮预热、首次差异、衔接错误及五份远端证据SHA256；远端同名快照保存在r2 campaign目录的status_snapshot.json。
