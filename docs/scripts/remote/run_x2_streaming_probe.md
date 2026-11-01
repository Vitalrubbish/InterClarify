# X2 探针单作业入口

对应`scripts/remote/run_x2_streaming_probe.sh`。仅在调度器分配的单张4090上运行，复用远端`asr` conda和现有模型。与SoulX回放共用`.frontend-replay.lock`，拒绝同项目重叠模型作业。

调用前设置`SOULX_SOURCE`为冻结Git worktree、`SOULX_RUN_ID`为新run标识、`SOULX_FDB_MANIFEST`为冻结FDB30清单。脚本建立独立输出目录，保存源码／清单摘要和实际提交号；输出目录已存在即失败。

入口强制离线，Python与数值库线程上限2，调度资源固定1GPU／4CPU／32GiB。内部timeout为1740秒，外层提交再用1800秒限制。每秒检查显存和结果大小，超过22528MiB或256MiB即停止子进程，并写`resource_stop.txt`；退出时清理子进程、监视进程并保留真实退出码。至少保留1GiB磁盘余量，禁止复制模型或在登录节点执行推理。

调度提交形式：`vc submit --partition pdgpu-4090 --num-task 1 --cpu-per-task 4 --mem-per-task 32G --gpu-per-task 1`，使用既有镜像和独立提交日志。提交前必须确认队列无其他本项目GPU作业。
