# 远端 Layer 1 数据构建与审计

`scripts/remote/run_layer1_data.sh` 在已申请的单个 CPU 作业中执行构建及审计，无类。环境变量显式指定冻结源码、独立训练 conda prefix、完整源数据/清单、官方 tokenizer、外部排除清单、审计长度和新 run 输出。

脚本验证 conda-meta 与解释器，冻结 Git 提交和已安装包版本，限制 Python 用户包、线程数 4、虚拟内存 28GiB、core dump；构建最长 4 小时，审计最长 1 小时。依赖清单由标准库importlib.metadata读取，避免pip工具自身损坏阻断数据检查，不修改环境包。退出码写入独立 run，失败日志保留。申请 4 CPU/32GiB/0GPU，同时最多一个此类数据作业。数据目录预算由核心模块检查，原始 shard 和环境额外核对远端配额，不复制模型。

脚本拒绝已有输出；生成中断时在同一 conda 下使用 Python 构建入口的 `--resume`，只允许相同输入恢复。原始索引中断需新目录，保留失败证据。完整任务命令见 [004 远端任务单](../../issue/004_remote_data_execution.md)。

004最终交付增加审查材料导出：机器审计通过后调用prepare_layer1_review.py，生成前32条完整可读事件表及固定分层抽查清单，不自动写accepted/reviewer或将人审标为完成。抽查使用已经生成的1000/200/300数据，不增加训练曝光。

用户取消全库过滤后，正式默认仅抽6000原始对话再过滤/去重/切分，可按受限调试机配置执行。LAYER1_DATA_THREADS、MEMORY_KIB、BUILD_TIMEOUT、AUDIT_TIMEOUT、REVIEW_TIMEOUT分别覆盖线程、地址空间KiB及各阶段秒数；调试机由父进程固定1CPU/nice10/2GiB硬限，配置线程1、构建1800秒/审计900秒/材料300秒，外层3600秒。只读来源字节验真仍保留，绝不退回全库对话过滤。原4CPU/32GiB是已停止的全库作业申请，不是6000样本的强制要求。
