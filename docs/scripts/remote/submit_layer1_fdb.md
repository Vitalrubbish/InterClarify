# ASR候选FDB子集提交

`scripts/remote/submit_layer1_fdb.sh`无类，使用明确指定的冻结`LAYER1_FDB_ROOT`和新输出`LAYER1_FDB_OUTPUT`，只读引用078最终候选与065 r4的d6dc3bf X-Talk checkout。提交前执行方核查现役作业和磁盘，不恢复缺失旧训练路径。

vc任务2×4090/16CPU/64GiB、单任务/单并发，timeout14400秒，预算由正式入口逐段复核；现役conda。逐例输出和原始时间线留远端，后续回收退出码、完整覆盖、正式两轴子集时序与客户端诊断，不自动运行完整FDB或GPT评分。
