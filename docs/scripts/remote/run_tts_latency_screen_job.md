# TTS 筛选节点入口

`run_tts_latency_screen_job.sh` 复用 round1:v0.4 镜像 conda 和共享固定模型。在独立 checkout 中运行依赖核验、真实 MOSS CPU 等价性测试，随后用客户端 conda 执行 `tts_latency_experiments.py`。`TTS_TASK_ROOT`、`TTS_OUTPUT` 必须显式提供；已有目录不覆盖。作业结束保存 `exit_code.txt`，失败仍保留 preflight 日志。

`TTS_SCREEN_JOB=1` 使现有提交包装器选择此入口，并把任务描述改为 tts-latency-screen；默认仍提交原 baseline 入口。资源保持单 GPU / 8 CPU / 32G。各 arm 在同一分配卡顺序运行，不并发加载服务或触碰原基线 checkout。
