# 双路联合快照契约检查

对应`tests/test_independent_frontend.py`。FakeEngine使用真实decode_emit产生确定性WAIT或EOS组，Clock提供可控单调时间；控制支路执行官方SoulX方法和微型CPU依赖，不加载权重。

X2Tests检查子词／多词EOS组、WORD未闭合不提交、64 token上限、前缀保护、WAIT进度与正文时间不变及取消后的迟到计算。

AudioTests验收两种完成顺序、第一帧及nonidle在双路实际完成前不可见、统一发布时间和原始可用时间、WAIT整批提交、提交返回前不能启动下一批、连续生产者、PCM摘要与实际窗口、reset后正文／PCM／步号连续、EOF一帧／两帧及真实边界，以及4MiB和分配前预算。NTF-030新增超过800ms及12800采样后仍能继续、保持PCM连续和正常提交的验证。异常、关闭竞态、缺失／重复／过期／篡改回执、开放DECODE、Context校验与容量／写入失败均不提交半帧或释放下一步。

并发读者只看到完整批次，深副本不能回改内部span；过期批次和关闭后的写入不能覆盖当前值。篡改回执包含控制／80ms开始时间缺失、非有限或晚于完成，验证这些错误在提交前失败。读取耗时、模型调用、屏障等待与提交分别记录，尾词保持unknown。

运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p test_independent_frontend.py -v`。NTF-017采用联合提交合同；真实模型及实时性验收见NTF-018／019。

NTF-018增加可选并发调度检查：两路能在同批同时开始；一侧结束时另一侧未结束不得提交，下一批仍不能启动；一侧异常时必须等另一侧设备worker收尾后才允许detach。默认串行用例继续保持原行为。

完整系统评测扩容检查：显式16MiB允许超过旧4MiB的输入暂存，但模型临时分配和超大传输包仍在分配前拒绝；记录容量，超限取消且不推进输入。旧4MiB拒绝用例保留。
