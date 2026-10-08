# `scripts/remote/run_p1_2_node_job.sh`

## 作用

P1.2 作业的容器内执行体。步骤：

1. **前置探测**：用 `$PYTHON` 对 `IC_STT_ENDPOINT`（默认 `127.0.0.1:31607`）与 `IC_TTS_ENDPOINT`（默认 `127.0.0.1:31608`）做 TCP 连通性检查；不可达则打印错误并退出码 3，提示先按任务单部署 moshi-server；
2. **合成场景音频**：`prepare_p1_2_scenarios.py --profile cluster`（需要 TTS 服务）；
3. **运行双工链路**：`run_p1_2_live_link.py --profile cluster --output-root $ARTIFACT_ROOT/p1_2_live`，由 runner 自行拉起官方 LLM 服务子进程、连续执行场景并写运行目录。

日志写入 `$ARTIFACT_ROOT/p1_2_live/logs_submit/node.<UTC>.log`；环境固定 `PYTHONPATH=<repo>/src`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`PYTHONNOUSERSITE=True`。

可用环境变量覆盖：`INTERCLARIFY_ROOT`、`INTERCLARIFY_MODEL_ROOT`、`INTERCLARIFY_ARTIFACT_ROOT`、`IC_PYTHON`、`IC_STT_ENDPOINT`、`IC_TTS_ENDPOINT`。
