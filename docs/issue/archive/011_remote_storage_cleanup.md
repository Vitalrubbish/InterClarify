# Issue 011：清理远端无用环境与过时目录

状态：完成，2026-10-19。范围：按用户授权删除Qwen3-ASR模型及旧ASR/TTS选型开发实现，不涉及其他项目。

- [x] 核对现行脚本、当前进程/调度任务、conda prefix及软链接；v1是v2–v6实际环境来源，保留v1/v6。
- [x] 删除Qwen3-ASR专用模型缓存、源码、服务/测试/说明与专用conda环境；保存模型来源、配置及环境包清单。
- [x] 删除旧ASR选型source及8份快照，TTS选型source和五份旧开发树的脚本/测试/配置/说明，清理重复传输包。
- [x] 仅保留约4.03MB主源码恢复档及99KB补充档，精确删除路径和SHA256齐全；原始runs/reports/日志/试听数据不删。
- [x] 删除后核对当前Nemotron/Kokoro模型、环境软链接、训练环境、官方权重及Kyutai参考保留；当前客户端导入通过，退役目标已不存在。

[执行结果](../../../reports/maintenance/20261019-retired-selection/README.md)：共47个文件/目录级目标。主清单清理前du占用扣主恢复档后约6.25GiB，不冒充共享配额减少实测。远端原件与恢复档位于 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-maintenance-20261019/`。

本次没有删除现役Pocket克隆种子、Nemotron多语诊断资产、X2/MOSS历史诊断、其他项目环境或共享conda缓存。没有运行新GPU测试，不改变训练门禁。任务完成归档。
