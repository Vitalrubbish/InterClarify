# 单卡Nemotron＋SoulX检查入口

对应`scripts/remote/run_nemotron_soulx_probe.sh`，要求调度节点、冻结`SOULX_SOURCE`和唯一`SOULX_RUN_ID`。ASR使用既有Python3.12 conda，SoulX使用既有Python3.11 conda，分别串行调用各自模型，避免依赖冲突；只读复用模型，不复制权重。

复用前端单作业锁，检查30GiB空盘；私有socket放在短临时目录，退出清理子进程和socket。每进程CPU线程2，PyTorch显存比例分别0.55／0.35。等待ASR预热最长300秒，总执行1700秒、外层调度1800秒；设备显存合计22GiB停止线、输出128MiB、单文件128MiB，触限明确失败并保留exit code及日志。运行前保存全部适配源码摘要。
