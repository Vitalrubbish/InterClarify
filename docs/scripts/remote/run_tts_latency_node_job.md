# TTS 远端节点任务

`run_tts_latency_node_job.sh` 在分配到的单张 4090 内运行组件实验，使用既有镜像的 conda 环境；所有输出置于新目录，不修改现役 checkout、权重或依赖。入口参数为 `TTS_TASK_ROOT`（独立 Git checkout）、`TTS_OUTPUT`（不存在的路径），其余路径默认指向已核对的共享模型根。

流程为来源/锁文件/音色/GPU登记、MOSS 依赖检查、CPU 确定性测试、启动唯一 TTS 服务、health 探测、固定文本 WebSocket 冷启动与热态探针、原 X-Talk 客户端 smoke、35 条文本的两模式三轮基线。探针或 smoke 失败即停止，完整回放不运行。只启动 TTS，不调用 ASR/LLM 或播放器，不据此宣称 FDB 通过。

服务置于独立进程组，退出 trap 只清理本任务服务与 GPU 采样进程。`TTS_BATCH_FRAMES=0`、`TTS_EARLY_COMPILE=0` 是基线；其他值仅供后续依赖门禁通过后显式提交。第一项任务不自动进入后续 arm。GPU 每秒采样，实际 CUDA 分配沿用调度器，launcher 使用逻辑 GPU 0。

`tts_latency_benchmark.py` 的 `--probe` 显式运行一条文本的一个模式，用于真实服务接入验证，输出注明 probe；正式模式仍强制至少 30 条、3 轮。长句 cold probe 与后续两个新会话探针分目录，便于识别编译和逐会话开销。

CPU 组件测试显式关闭服务实验开关和 trace，避免作业环境污染“开关关闭时静默”等契约测试；测试完成后服务仍使用原实验环境。该隔离不会跳过或放宽用例。

health 超时由 `TTS_HEALTH_TIMEOUT` 配置，默认 600 秒，启动超时后清理本任务进程组：先 TERM，最多等 20 秒，再 KILL，避免启动停滞时永久占用 GPU。`TTS_STACK_DIAGNOSTIC=1` 启用服务栈诊断，此类作业只用于排障，不计为正式热态基线。
