# `scripts/remote/start_kyutai_services.sh`

## 作用

在任意能看见共享存储的节点（作业容器内或手动调试）幂等启动 P1.2 所需的 Kyutai STT/TTS 服务：二进制、配置、模型与 Python venv 均在共享存储 `interclarify-kyutai/`（构建与版本见 [../../3rd-party/KyutaiServices.md](../../3rd-party/KyutaiServices.md)）。已运行则跳过，随后用 bash `/dev/tcp` 探测等待端口就绪（默认各 600 秒），未就绪返回非零。

## 用法

```bash
bash scripts/remote/start_kyutai_services.sh [stt_gpu=1] [tts_gpu=1]
# 环境变量：KYUTAI_ROOT、IC_STT_PORT=31607、IC_TTS_PORT=31608、
#           IC_KYUTAI_READY_TIMEOUT_S=600
```

服务日志在 `$KYUTAI_ROOT/logs/`（`stt-31607.log`、`tts-31608.log`），由 [run_p1_2_node_job.sh](run_p1_2_node_job.md) 在作业中调用，也可手动调试时单独使用。
