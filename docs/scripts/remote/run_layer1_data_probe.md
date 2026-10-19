# 数据诊断及来源恢复作业入口

`scripts/remote/run_layer1_data_probe.sh` 在单个4CPU/8GiB/0GPU作业内串行执行：新增19项数据测试、4项下载测试、发布tokenizer与真实首shard的32条诊断；仅在以上均通过且 LAYER1_RECOVER_SOURCE=1 时恢复完整来源下载。无类，模型和训练均不启动。

显式环境为 LAYER1_DATA_ROOT、LAYER1_TRAIN_ROOT、LAYER1_TRAINING_ENV、LAYER1_PROBE_OUTPUT 和 LAYER1_TOKENIZER。校验独立conda及新输出，冻结源码和依赖，限制虚拟内存7GiB、线程4、测试各120秒、诊断300秒和下载4小时。probe_exit_code.txt单独记录诊断退出，exit_code.txt记录整个作业；下载未完成不掩盖已通过诊断，也不伪造来源完成。

调度器会按提交日志名自动生成同名 `.sh` wrapper，`--cmd` 必须引用本仓库冻结入口，不能引用与日志同名的外部脚本。日志放独立 submit_logs，避免覆盖入口或自递归。首次临时提交曾触发这一行为，失败原件保留在远端，后续使用此独立入口。
