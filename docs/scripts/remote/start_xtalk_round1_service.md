# `scripts/remote/start_xtalk_round1_service.sh`

## 整体作用

读取首轮配置和模型锁定记录，以前台进程启动 LLM、XTurnix 或 MOSS TTS。ASR 当前使用独立 smoke，尚无完整 X-Talk 服务适配。脚本不提交集群作业，不改变配额或停止已有进程。

## 核心流程

Shell 入口调用准备环境中的 `run_xtalk_round1.py serve`。其 `serve` 函数读取环境名、端口、GPU 和 snapshot 路径，检查锁定模型 ID、目录与源码提交，通过 `os.execvp` 执行 `conda run --no-capture-output`。LLM 与 XTurnix 使用本地模型目录；MOSS 直接在 conda 环境启动固定服务封装的 Python 入口，显式设置模型、tokenizer、codec 和 48 kHz 输出。

`XTALK_ROUND1_MODEL_ROOT` 指向 `models.lock.json` 所在目录；TTS 另需 `XTALK_MOSS_SERVICE_ROOT`、`XTALK_MOSS_SOURCE_ROOT`。GPU 使用当前作业内可见卡的逻辑编号；若已有 `CUDA_VISIBLE_DEVICES`，从该列表中选择对应卡，避免引用作业未分配的设备。

执行命令见 [../../jobs/xtalk_round1_baseline.md](../../jobs/xtalk_round1_baseline.md)。日志重定向和作业调度由调用者负责。
