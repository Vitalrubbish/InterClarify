# TTS 作业提交包装

`scripts/remote/submit_tts_selection_job.sh` 将单个候选提交到 `vc` 调度器。无类。入口根据 `TTS_BACKEND` 选择 CPU 或单 4090 资源，默认 8 CPU/32G，使用已有 round1 v0.4 镜像。

提交前复制节点脚本到带 UTC 时间的不可变文件，避免开发时更新入口影响正在执行的 shell。`TTS_SELECTION_OUTPUT` 必须是新目录；不清理已有输出。返回 job ID，并把提交日志保留远端；报告只导出所需模型日志，不导出包含完整环境变量的 vc 提交日志。
