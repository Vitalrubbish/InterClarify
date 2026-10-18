# 远端 TTS 选型作业

`scripts/remote/run_tts_selection_job.sh` 在调度分配的单张 RTX 4090 上顺序启动指定候选服务并运行统一客户端。没有类。入口校验新输出目录，保存 GPU、CPU、依赖、输入和脚本哈希，以进程组跟踪自己的服务并在退出时清理；不停止其他用户或已有实验。

`TTS_BACKEND` 选择模型，`TTS_SELECTION_ROOT` 指向共享实验目录。MOSS 服务复用现役 `run_xtalk_round1.py`，其编译参数保持现役配置；其他候选使用原生回调实验 HTTP 服务。所有模型均用 2 个 PyTorch CPU 线程。默认超时 600s 启动、180s 请求（MOSS 编译冷请求 600s）。正式运行前复制脚本、CSV 与 manifest。

Pocket 使用 CPU，优先申请 `pdcpu`；其 `gpu.txt` 可以记录无 GPU 的诊断信息而不判为推理失败。其他模型申请 `pdgpu-4090` 单卡。MOSS 必须使用镜像 `/opt/conda` 内已带 flash-attn 的环境；共享盘同名环境缺该依赖，不能混用。MOSS 健康检查早于惰性模型加载，其 cold 请求包含加载，不能与已加载模型的 cold 推理直接比较。
