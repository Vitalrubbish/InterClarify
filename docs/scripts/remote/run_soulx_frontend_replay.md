# 受限前端音频检查入口

对应 `scripts/remote/run_soulx_frontend_replay.sh`。无类，使用 `SOULX_SOURCE`、`SOULX_RUN_ID`、`SOULX_AUDIO_MANIFEST` 指向独立源码、唯一输出和冻结音频清单；只读复用 `turncontrol-comparison` 的模型、上游与conda。

入口检查conda和30GiB空盘，锁定单个回放、固定离线环境及4个CPU线程。复制小型manifest并保存源码摘要；后台推理进程受1100秒、128MiB目录、22GiB设备显存停止线约束，调度命令外层另加1200秒上限。结果和exit code保留，不删除失败run或自动扩容。仅在调度节点执行模型，不在登录节点推理。

`SOULX_TIMING_MODE` 默认为 `realtime`；若单独执行限速功能核查则显式设为 `causal` 并使用新run ID。后者不证明实时吞吐。
