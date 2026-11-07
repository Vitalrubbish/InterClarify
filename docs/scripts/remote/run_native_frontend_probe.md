# 远端前端受限诊断入口

对应 `scripts/remote/run_native_frontend_probe.sh`。脚本没有模型类，负责冻结输入与源码、启动单卡前端回放，并在退出时关闭所属进程组。它保留为当前 SoulX＋X2 的诊断工具；完整系统评测使用[半双工入口](run_fdb30_half_duplex.md)。

入口要求调度器已分配 GPU、`NTF_SCHEDULED_RUN=1`、干净的 `SOULX_SOURCE`、唯一 `SOULX_RUN_ID`、固定 `SOULX_FDB_MANIFEST`，以及由 `SOULX_WARMUP_AUDIO` 指定的 7.8 秒英文预热音频。使用既有 SoulX／ASR conda，检查环境标识、输入摘要、空闲盘至少 10GiB 和独占前端锁，拒绝覆盖已有输出目录。

`NTF018_GROUP` 或 `NTF_FRONTEND_GROUP` 选择单路、双路或矩阵回放，每个条件使用新进程。通用脚本仍支持 `fdb-dual`／`fdb-single` 诊断组，要求提供 `NTF_ACCEPTANCE_GATE` 和摘要；旧 NTF-019 专用包装与评分工具已退役，不再提供过期提交命令。源码清单只记录现存脚本与配置。

每作业单卡 4090、4 CPU、32GiB RAM，模型每路一个 worker、计算线程各不超过 2。脚本逐秒检查显存 22528MiB、进程组 RSS 32GiB、输出 128MiB 和 1750 秒收尾线，调度器另限 1800 秒；PCM 上限为 4MiB。延迟与积压照实记录，不按旧 800ms 时长停止。

`cleanup` 保留退出码并清理本次进程组。有限预热失败保留诊断，完整条件另记自身退出结果；矩阵外层退出码不代替逐条件审计。磁盘扫描只容忍子路径消失的 ENOENT 竞争，要求根目录存在且总量有效，其他错误立即停止。

该脚本不提交作业、筛选结果、自动重试或清理历史 run。真实模型诊断须在远端调度环境执行，本地 shell 检查不代表模型或性能验收。
