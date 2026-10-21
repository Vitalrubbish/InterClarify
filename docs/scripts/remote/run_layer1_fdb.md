# 原1k ASR候选固定FDB子集任务

`scripts/remote/run_layer1_fdb.sh`在调度的2张4090上执行081固定25例回归，无类。要求冻结`LAYER1_FDB_ROOT`源码、`LAYER1_XTALK_ROOT`及新`LAYER1_FDB_OUTPUT`，`LAYER1_TRAIN_RUN`指向已完成078目录。逐项核对训练退出0、1240步/2480序列/1000对话、112个LoRA变化、冻结参数不变、独立078配置/协议摘要及最终checkpoint和重载身份。

原030清单25会话/70份音频标注逐文件验证后暂存。X-Talk采用d6dc3bf干净src（本轮复用065 r4的只读checkout），不使用旧134文件快照；运行配置为300/1200ms TTS、600ms micro-turn、会话KV复用，模型health核对duplex_greedy_v1与repetition_penalty=1.0。每例独立会话、原生ASR输入、官方等长输出及独立5秒诊断尾窗，不人工补点。

评分环境先对3秒语音和2秒静音做官方对齐预检；ASR→TTS→模型串行启动，ASR warmup180秒，health等待核对进程存活。回放结束停推理服务后，对Smooth和Interruption各5例做官方对齐与TOR/Latency；GPT保持暂缓。`fdb_subset_report.py`另核对25例输出时长和原窗/尾窗播放，不能把transport通过当作语义正确。

单作业2GPU/16CPU/64GiB、线程4、worker0、并发1、4小时硬限；输出20GiB/空闲盘50GiB/单文件8GiB，现役conda、不复制模型，失败与退出码保留。旧T2训练路径已缺失，不尝试重训或重新恢复；两轴旧对照从065同运行配置结果提取相同5例，其他三类仅作本轮诊断。历史040报告仍代表当时旧配置和评分状态。

082将诊断和音频格式回归放在已有soundfile的客户端conda执行；r1已完成回放的恢复评分由独立`run_layer1_fdb_scoring.sh`处理，不重复推理。
