# UltraChat 远端串行作业

对应 `scripts/remote/run_textturn_ultrachat.sh`。无类。`run_step`启动受控进程组，`cleanup`处理退出、超时和信号，清理模型及回放进程并写入退出码。

启动时确认已有conda元数据、独立输出路径及至少30GiB可用盘，保存清单、预算、源码提交、包版本、模型及tokenizer摘要。仅加载原固定TextTurn候选，不加载ASR、回答模型或TTS；ASR输入复用保存事件。健康检查后先480ms／8 token，后160ms／3 token，每种配置逐例写进度和trace，并独立评分。

最多1卡、8CPU、32GiB和一个推理工作线程；外层timeout覆盖两种配置。每10秒监控显存、项目资产、报告及可用盘，22GiB显存、10GiB资产、2GiB报告或可用盘低于30GiB时终止并保留证据。模型服务与回放均使用现有conda，不修改环境。资源监控中的资产和报告沿用已有TextTurn根目录总量口径。调度Running不足以证明稳定，需同时检查健康信息、连续逐例成功、trace增长、进程及多次资源采样。
