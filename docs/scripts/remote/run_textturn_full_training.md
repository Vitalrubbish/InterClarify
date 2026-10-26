# 完整轨迹远端训练执行

`scripts/remote/run_textturn_full_training.sh`使用远端既有conda、固定qwen3-0.6b及tt-010-fulltraj-r1，调用train_textturn.py与完整轨迹训练配置。运行目录必须新建，记录源码提交、依赖、训练日志、资源采样及退出码，不覆盖旧TT-002／TT-010运行。

2026-10-26按用户明确指令取消训练任务时间上限，移除进程13800秒timeout，训练配置同设max_wall_seconds=null；有限epoch结束或质量gate不放行时正常退出。显存22GiB、资产10GiB／报告2GiB停止线、30GiB空盘门槛仍保留，调度器限制1张24GiB GPU／8CPU／RAM32GiB。每10秒记录资源采样，资源命令失败或越界都会结束入口并清理训练子进程。

独立进程组及退出trap负责回收子进程并记录退出码。GPU进程不使用不适合CUDA虚拟地址空间的ulimit-v，不增加GPU并行任务。旧累计GPU预算限制此前已按用户授权取消。
