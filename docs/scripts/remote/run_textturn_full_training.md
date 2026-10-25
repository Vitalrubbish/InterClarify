# 完整轨迹远端训练执行

`scripts/remote/run_textturn_full_training.sh`使用远端既有conda、固定qwen3-0.6b及tt-010-fulltraj-r1，调用train_textturn.py与新的完整轨迹训练配置，不修改历史TT-002入口。运行目录必须新建，记录源码提交、依赖、训练日志及退出码。

按用户最新指令不再检查原3991秒累计剩余预算；保留单作业timeout13800秒、显存22GiB停止线、原资产10GiB／报告2GiB停止线和30GiB空盘门槛。调度器限制RAM32GiB，避免对CUDA进程使用不适合GPU虚拟地址空间的ulimit-v。独立进程组及退出trap负责回收子进程。没有新增GPU并行作业。
