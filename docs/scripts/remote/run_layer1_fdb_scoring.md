# 完成已回放子集的评分

`scripts/remote/run_layer1_fdb_scoring.sh`用于082恢复，无类。要求冻结源码、081 r1完整回放目录与新评分目录；先核对25例transport、子条件退出0、候选及生成策略，再复制两轴各5例输入/输出WAV和标注，逐文件验证摘要。

在有soundfile的客户端conda运行4项回归及25例诊断；评分进程复用现役NeMo conda做10例官方对齐和时序评分，GPT暂缓。不运行ASR/LLM/TTS服务或重复实时回放，不修改原WAV或r1退出1状态。

通过调度运行1×4090/8CPU/32GiB、线程4、单并发、1小时，输出10GiB/空闲盘50GiB/单文件8GiB。`replay_reuse.json`保留原回放身份和复制摘要，评分及总退出码独立记录。
