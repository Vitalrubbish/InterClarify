# FDB30 完整链路调度入口

`scripts/remote/run_fdb30_half_duplex.sh` 启动私有 Unix socket 的 Qwen 与 IndexTTS 服务，再运行双路前端。必须通过三卡调度，前端、LLM、TTS 各一卡，环境分别复用现有 conda。`SOULX_SOURCE` 冻结源码、`SOULX_RUN_ID` 新运行目录、`SOULX_MODE` 为 smoke 或 formal。

脚本重建原英语参考声音并验证与 TurnControlComparison 完全相同的 SHA256，复用固定 FDB30 manifest。后台服务预热后启动前端。每五秒记录目录大小和分配显卡的显存，任一卡超过 22GiB 即停止。目录上限 2GiB、前端时限 6600 秒、外层作业 7200 秒；退出时结束本作业所属进程组并保留日志与退出码。单文件上限 1GiB，三个模型进程各自限制显存份额，调度主存 64GiB；同一实验锁阻止重叠推理。

无业务类。`cleanup` 保留真实退出码并关闭所属服务，不操作其他项目进程或清理历史运行结果。

调度器可能只设置 `NVIDIA_VISIBLE_DEVICES`：优先读取 CUDA 显式列表，否则读取容器内 `nvidia-smi` 可见索引，均要求正好三卡；不把未设置 CUDA 环境变量误判为未分配 GPU。
