# TextTurn 远端训练作业

对应 `scripts/remote/run_textturn_training.sh`。只读复用已经由 conda 创建的 XTurnix 隔离环境（torch 2.11.0、transformers 4.57.1、peft 0.19.1），不更改现役 ASR/TTS 或其他项目环境。固定模型及 TT-001 数据存放在 `~/parathink-textturn`。

启动检查 conda 元数据及至少30GiB可用盘，保存源码提交和依赖清单。进程组由 timeout 限制在4h内，退出或触限会终止训练子进程；每10秒检查单卡显存22GiB、资产10GiB和报告2GiB。CPU8、内存32GiB由调度器限制，训练无数据 worker。完整训练是否继续由开发集 gate 决定，入口不读取测试数据。
