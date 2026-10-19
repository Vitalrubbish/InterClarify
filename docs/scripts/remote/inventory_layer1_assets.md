# Layer 1 资产盘点

`scripts/remote/inventory_layer1_assets.py` 是不加载模型的只读盘点工具，使用 Python 标准库，在已有 conda 环境执行。无类；`file_record` 流式计算完整文件 SHA256，核对读取前后的 inode、大小和修改时间，并读取 safetensors 头中的参数名、形状、dtype、偏移；`git_record` 记录提交、工作树状态和非忽略源码实际摘要；`asset_record` 递归扫描资产并保留逐文件错误；`main` 写入独立输出目录及退出码。

历史核验记录见 [远端任务单](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/001_remote_execution.md)。输出目录已有则拒绝覆盖。缺失资产、空目录、读取异常、损坏头或运行中变化使退出码为 1；未提供资产或重复名称属于参数错误。目录 symlink 不递归，普通文件 symlink 记录解析目标；外部链接资产的内容也计算摘要。Git 子仓库需要独立 `--xtalk`，不从父仓库提交推断其版本。记录安装包版本及实际解释器；不抓取环境变量或凭据。

报告只证明指定范围的文件盘点，不证明文件来自所声称 revision、许可证已审核、完整权重加载成功或运行时对齐。张量头目录不替代 005 的参数恢复审计；缺失证据不能变成默认成功。模型和大文件报告留远端，仅将紧凑摘要交回仓库。
