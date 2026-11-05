# NTF-054：执行线程与 complete 交接修复后的复测

2026-11-05，按用户最新指令已以r2重新提交三条smoke，当前Pending，等待4090调度。r1已离队且无成功退出标记，旧衔接进程已退出；新衔接进程已启动，尚无本轮新成绩。

## 固定条件

模型实现提交为 `65d15e6`，已推送GitHub。输入manifest SHA256为 `403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07`。比较对象是[修复前正式r2](../20261105-fdb30-half-duplex/README.md)。新版本固定SoulX回放线程、常驻X2辅助线程，各模型进程CPU计算线程为2，并跳过complete后的整段SenseVoice识别；短窗识别、reset、160ms联合发布及complete-only回答合同保持。

## 资源与步骤

远端队列检查为空；账户存储约186.90GB／1TB，可用约838GB，GPU配额8张。仅串行提交作业：smoke三条通过后正式30条，推理释放后单卡评分。推理3×4090、12CPU／64GiB、7200秒、每卡22GiB、输出2GiB、PCM16MiB；评分1×4090、4CPU／32GiB、3600秒。仅TOR与延迟，保留失败记录。

| 阶段 | run ID | job ID | 状态 |
| --- | --- | --- | --- |
| smoke-r1 | `ntf054-half-smoke-20261105-r1` | `job-179386787087491282885-xuan-zhang` | 已离队，无退出码／最终结果；衔接停止 |
| smoke-r2 | `ntf054-half-smoke-20261105-r2` | `job-179387030286102615198-xuan-zhang` | 17:18:23提交，Pending |
| formal-r2 | `ntf054-half-20261105-r2-formal` | 待自动提交 | 等smoke-r2离队及核验 |
| score-r2 | `ntf054-half-20261105-r2-score` | 待自动提交 | 等正式推理离队及核验 |

验收需核对新execution／ready预算、预热与正式SoulX线程ID、complete识别跳过事件、限定差异的控制对照、播放实录及完整固定分母。完成作业和低延迟分别报告，不能由本地146项检查推定GPU性能。

远端冻结目录为 `~/parathink-soulx-duplug/source/ntf054-65d15e6`，独立detached worktree，工作区干净。源码归档 `submit_logs/ntf054-65d15e6-source.tar.gz` 的SHA256为 `0b09c31e3054957869d59d7ce1f5f550f4971d97933f144e113252b4c8793e77`，与本地从同提交生成的scripts／configs归档一致；native_soulx.json的SHA256为 `128978377266770c1cdee4c244c81eefb3b3c85d7536b4707eff528e36412ba9`。四套推理conda均已核对存在，仅复用原资产。

## 顺序衔接

[衔接脚本](../../../scripts/remote/fdb30_retest_followup.md)已在远端以base conda重新启动，r2 PID为2769918，状态为waiting_smoke，跟踪新smoke job ID；启动采样RSS为21976KiB。脚本部署在 `submit_logs/ntf054-followup.py`，SHA256仍为 `c389f3ccb0fe18bfe27ba3ea921b3ac1e28b6a5b7c5fb693e6461a893f49cc31`，已重新核对与本地一致；该脚本单独冻结，不改变模型提交。限定单CPU、2GiB地址空间和12小时。

当前状态、日志、各阶段提交回执和审计分别保存在 `analysis/ntf054-half-campaign-20261105-r2/` 的state.json、campaign.log、*.submit.txt及*.audit.json。每30秒检查一次队列；前一作业离队、退出0且审计通过后才提交下一阶段，任何失败均记录并停止，无自动重跑。状态和来源摘要见[launch.json](launch.json)，其中attempt_history保留r1记录。衔接的3项本地检查已通过，覆盖错误线程／预算／跳过行为拒绝、单作业防重及失败退出码阻断。

## 重提记录

旧r1衔接于17:07:40记录`Job ended without successful exit marker`并退出，旧PID2603757已不在运行。按用户要求重提前再次确认队列为空、r2输出及状态目录未使用，保留旧目录；现有记录不足以判定旧作业被删除还是调度失败。源码工作区仍干净，模型提交、配置摘要、输入与资源不变，没有并行保留旧任务。
