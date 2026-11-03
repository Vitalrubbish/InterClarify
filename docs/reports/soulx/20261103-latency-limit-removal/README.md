# NTF-030：取消原生前端800ms停止条件

2026-11-03。按用户明确指令完成本地实现与验证，NTF-030归档。NTF-019已[按用户审核通过归档](../20261103-ntf019-fdb30/README.md)；其29/30、退出1与单路对照缺失保持原记录。

## 改动

| 文件 | 最终行为 |
| --- | --- |
| `scripts/runtime/dual_audio.py` | 删除未读PCM超过12800采样及墙钟进度超过800ms的中止；`_check_bounds()`继续限制PCM合计4MiB，传输和模型内部分配前检查保持 |
| `scripts/remote/native_frontend_probe.py` | 原生单路参考同步取消时长门槛；`replay()`不再因送音迟到或联合发布延迟超过800ms停止，迟到／延迟仍记录；新run显式保存时长停止条件为null |
| `scripts/analysis/analyze_native_frontend.py` | `audit_case()`不再因延迟或未读时长判失败，仍检查容量、完整批次、EOS、来源、顺序和关闭；积压图移除800ms停止线及固定纵轴上限 |
| `scripts/analysis/analyze_native_frontend_fdb.py` | 固定FDB30曲线移除800ms停止线，仍以真实时间绘图 |

真实时钟供音、160ms双路完成后联合提交、单worker／路、4MiB PCM、显存22GiB、RSS32GiB、单作业1800秒／128MiB及启动磁盘10GiB要求保持。容量或作业资源触限仍明确失败，不用减速、丢帧、无限排队或改写时间戳代替。

范围为当前原生控制＋独立X2路线及其单路参考、分析器。旧教师替换实验的冻结配置和已退役入口保留历史，不由本单恢复。历史run、图和机器审核JSON不重写，取消时长门槛不等于已经证明实时性或修复过音频编码长尾。

## 验证

本地既有`interclarify-dev` conda执行完整169项检查，全部通过，无跳过。重点回归：

- 单／双路正式与预热均允许16001采样未读量及超过800ms墙钟积压，PCM保持连续，EOF实际采样和联合提交完整。
- 真实线程将首包处理延迟1秒，后续送音迟到和控制发布延迟均超过800ms，仍完成全部3000采样并保存真实指标。
- 超过4MiB的传输或模型内部分配仍拒绝；关闭、迟到回执、开放EOS、失败单侧结果不提交。
- 离线审计接受长延迟及较大未读时长，仍拒绝容量越界和篡改EOS。

验证命令：`conda run --no-capture-output -n interclarify-dev python -m unittest discover -s tests -q`。实现与修改测试的同路径中文说明已同步；`git diff --check`通过。

本次没有连接远端、执行GPU回放或启动LLM。用户已明确暂不推进后续接入，031—035草案未实施归档，无活动LLM工作单。原工作单保存在本地`docs/issue/archive/NTF-030.md`，沿用不纳入Git的约定，本报告保留范围与验收记录。
