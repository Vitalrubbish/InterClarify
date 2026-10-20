# T2_R3 固定 FDB 子集测试作业

`scripts/remote/run_layer1_fdb.sh` 在调度的 2 张 4090 上启动 Nemotron/Kokoro 组件服务及唯一模型服务，只测试最终候选 `T2_R3_delayed_start`。独立 conda、冻结源码和 xtalk 快照必须存在，输出目录拒绝覆盖；候选固定为 040 训练目录的最终 checkpoint，不通过小子集结果挑选权重。

脚本先核验训练退出 0、1,235 步/2,469 序列、1,000 条对话、112 个 LoRA 变化、冻结参数不变、干净进程重载和生成 IDs 复现；再复用 008a 的 134 文件 X-Talk 源快照与 030 的 25 会话 FDB 清单。`layer1_fdb.py prepare` 只复制冻结输入作为只读副本，`run` 调用 `duplex_a4_replay.run_fdb_batch`，固定英语运行配置、原生 ASR、独立会话、5 秒诊断尾窗和官方等长输出 WAV。

请求 2×4090/16CPU/64GiB、线程 4、单并发、4 小时上限，输出 10GiB、空闲盘 15GiB；LLM 与 ASR/TTS 分卡，子进程退出时清理。入口只做推理和数据回收，不调用官方 judge；官方评分、完整 FDB 和人工音频复核未执行，不能用 transport PASS 代替语义正确性。旧 round1、round2_t2 模式及 B0/T1/T2/T3/T2_R2 条件选择已删除。
