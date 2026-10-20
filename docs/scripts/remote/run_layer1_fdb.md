# 四配置FDB新组合测试作业

`scripts/remote/run_layer1_fdb.sh`在调度的2张4090上启动Nemotron/Kokoro组件服务及唯一模型服务，串行测试B0/T1/T2/T3。独立conda和源码/xtalk冻结快照必须存在，拒绝覆盖输出；候选来自006首轮最终checkpoint，不通过小子集结果挑选权重。

复用008a归档的X-Talk源码快照（419f283），以该次`source.sha256`逐项验证134个src文件，与当前本地fork完全一致；远端主xtalk仓库有其他工作，不修改或拉取它。X-Talk输出取消、TTS分段、ASR客户端保持原快照行为，四配置共用。

`scripts/remote/layer1_fdb.py`用于冻结样本暂存和条件驱动，无产品类。`prepare`复核030清单及每份音频/标注的大小/SHA256，只复制指定25目录作为只读来源副本；不重新取目录前五，不复制历史系统输出。`run`依次调用现有`duplex_a4_replay.run_fdb_batch`，参数固定当前英语运行配置、原生ASR、独立会话、5秒诊断尾窗，官方输出WAV仍与输入长度相同。驱动保留逐样本失败，不将静默或未评分当作成功接话。

请求2×4090/16CPU/64GiB，线程4、禁core dump，一个并发作业，4小时timeout；轮次输出限10GiB且磁盘至少15GiB空闲。LLM与ASR/TTS分卡，候选切换先停止并回收旧模型服务；所有子进程在退出时清理。健康与权重证据写入各条件目录，ASR/TTS参数固定。

本入口仅推理和回收数据，不调用内容judge；FDB官方对齐/评分、人工内容检查仍标pending。真实输出和能力报告由007/008后续汇总，不能用退出0或transport PASS代替TOR或语义正确性。
