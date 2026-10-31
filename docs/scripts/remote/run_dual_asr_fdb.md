# 受限双ASR作业入口

对应`scripts/remote/run_dual_asr_fdb.sh`。独立run目录及flock保证同项目单作业；只读复用SoulX/SenseVoice与Nemotron两组conda和权重。资源固定为1×4090、4CPU、32GiB、总1800秒，显存22GiB、输出128MiB、启动可用磁盘30GiB停止线；不自动重试或放宽。

需要设置`SOULX_SOURCE`、`SOULX_RUN_ID`、`SOULX_FDB_MANIFEST`，smoke使用`SOULX_DUAL_SMOKE=1`。脚本核验源码和manifest、启动独立Nemotron worker，等待就绪后启动含SenseVoice的SoulX回放，采样两进程显存和RSS；结束保留退出码并清理子进程及私有socket。提交前须重查队列与资源，调度1800秒限制涵盖加载和分析。
