# NTF-054：执行线程与 complete 交接修复后的复测

2026-11-05，用户已授权启动。三条smoke已提交，当前等待4090调度，模型尚未启动。受限顺序衔接进程已运行，尚无本轮新成绩。

## 固定条件

模型实现提交为 `65d15e6`，已推送GitHub。输入manifest SHA256为 `403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07`。比较对象是[修复前正式r2](../20261105-fdb30-half-duplex/README.md)。新版本固定SoulX回放线程、常驻X2辅助线程，各模型进程CPU计算线程为2，并跳过complete后的整段SenseVoice识别；短窗识别、reset、160ms联合发布及complete-only回答合同保持。

## 资源与步骤

远端队列检查为空；账户存储约186.90GB／1TB，可用约838GB，GPU配额8张。仅串行提交作业：smoke三条通过后正式30条，推理释放后单卡评分。推理3×4090、12CPU／64GiB、7200秒、每卡22GiB、输出2GiB、PCM16MiB；评分1×4090、4CPU／32GiB、3600秒。仅TOR与延迟，保留失败记录。

| 阶段 | run ID | job ID | 状态 |
| --- | --- | --- | --- |
| smoke | `ntf054-half-smoke-20261105-r1` | `job-179386787087491282885-xuan-zhang` | Pending，等待三卡调度 |
| formal | `ntf054-half-20261105-r1-formal` | 待自动提交 | 等smoke离队及核验 |
| score | `ntf054-half-20261105-r1-score` | 待自动提交 | 等正式推理离队及核验 |

验收需核对新execution／ready预算、预热与正式SoulX线程ID、complete识别跳过事件、限定差异的控制对照、播放实录及完整固定分母。完成作业和低延迟分别报告，不能由本地146项检查推定GPU性能。

远端冻结目录为 `~/parathink-soulx-duplug/source/ntf054-65d15e6`，独立detached worktree，工作区干净。源码归档 `submit_logs/ntf054-65d15e6-source.tar.gz` 的SHA256为 `0b09c31e3054957869d59d7ce1f5f550f4971d97933f144e113252b4c8793e77`，与本地从同提交生成的scripts／configs归档一致；native_soulx.json的SHA256为 `128978377266770c1cdee4c244c81eefb3b3c85d7536b4707eff528e36412ba9`。四套推理conda均已核对存在，仅复用原资产。

## 顺序衔接

[衔接脚本](../../../scripts/remote/fdb30_retest_followup.md)已在远端以base conda启动，PID为2603757，状态为waiting_smoke。脚本部署在 `submit_logs/ntf054-followup.py`，SHA256为 `c389f3ccb0fe18bfe27ba3ea921b3ac1e28b6a5b7c5fb693e6461a893f49cc31`，与本地源码一致；该脚本单独冻结，不改变模型提交。启动采样RSS为21700KiB，限定单CPU、2GiB地址空间和12小时。

状态、日志、各阶段提交回执和审计分别保存在 `analysis/ntf054-half-campaign-20261105-r1/` 的state.json、campaign.log、*.submit.txt及*.audit.json。每30秒检查一次队列；前一作业离队、退出0且审计通过后才提交下一阶段，任何失败均记录并停止，无自动重跑。状态和来源摘要见[launch.json](launch.json)。衔接的3项本地检查已通过，覆盖错误线程／预算／跳过行为拒绝、单作业防重及失败退出码阻断。
