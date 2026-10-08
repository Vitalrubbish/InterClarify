# `scripts/remote/run_p1_2_node_job.sh`

## 作用

P1.2 作业的容器内执行体。GPU 分配：GPU 0 跑官方 DuplexCascade 控制模型（bf16，约 17 GB），GPU 1 跑 Kyutai STT/TTS 服务。步骤：

1. **启动 Kyutai 服务**：调 [start_kyutai_services.sh](start_kyutai_services.sh)（幂等）从共享存储拉起 STT（31607）与 TTS（31608），等待端口就绪；失败退出码 3 并保留 `interclarify-kyutai/logs/` 服务日志；
2. **合成场景音频**：`prepare_p1_2_scenarios.py --profile cluster`（走本作业 TTS 服务）；
3. **运行双工链路**：`run_p1_2_live_link.py --profile cluster --output-root $ARTIFACT_ROOT/p1_2_live`，由 runner 校验权重、拉起官方 LLM 服务子进程、连续执行场景并写运行目录。

日志写入 `$ARTIFACT_ROOT/p1_2_live/logs_submit/node.<UTC>.log`；环境固定 `PYTHONPATH=<repo>/src`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`PYTHONNOUSERSITE=True`（Kyutai 服务脚本会自行解除离线变量并使用共享缓存）。

可用环境变量覆盖：`INTERCLARIFY_ROOT`、`INTERCLARIFY_MODEL_ROOT`、`INTERCLARIFY_ARTIFACT_ROOT`、`IC_PYTHON`、`KYUTAI_ROOT`、`IC_STT_GPU`、`IC_TTS_GPU`。
