# 调试机轻量数据诊断与内存实测

日期：2026-10-19。用户明确要求轻量检查直接在远端调试机执行；对应 [015](../../../docs/issue/archive/015_debug_node_data_validation.md)。源码固定 `5df0ef0135e51cf912262520b90b576547c071d7`，使用既有独立训练conda。没有修改模型、生成规则或训练门禁。

## 实测结果

在 `d6-hpc-debuggpu-001` 对32条真实UltraChat对话运行发布tokenizer诊断，核对首shard完整SHA256、固定种子计划和两种句读视图监督一致性。退出码0，墙钟6.894秒，用户/系统CPU时间4.495/0.582秒，子进程峰值RSS为153,536KiB（约149.94MiB），生成约1.02MiB产物。资源原件见 [resources.json](resources.json)，诊断原件见 [debug_probe_report.json](debug_probe_report.json)。

运行前可用内存为298,708,156KiB（约284.9GiB）。仅启动一个诊断子进程，绑定CPU 0，nice=10，线程1；虚拟地址空间软/硬上限均2GiB，CPU时间180秒、墙钟360秒、单文件128MiB上限、禁用core dump。输入源采用1MiB块计算SHA256，不把约919MiB的首shard完整载入内存。峰值RSS计量对象为诊断子进程，文件页缓存不计入该值；此次结果只证明有界32条检查的开销，不能外推全库去重/训练。

## 已有计算作业结果

检查时r4已运行，故保留其唯一下载进程，没有重新下载或重复单元测试。远端计算作业的19项数据测试和4项下载恢复测试全部通过，日志见 [数据测试](scheduled_pipeline_tests.txt)、[下载测试](scheduled_download_tests.txt)。其32条发布tokenizer诊断也已通过，见 [scheduled_probe_report.json](scheduled_probe_report.json)。两次诊断报告完全相同。

32条共5072个micro-turn：speaking 1281、finish 151、interruption 35、backchannel 28、thinking 1254，另有2323拍纯正文。原样/去句读有效监督token均为32,327，两视图共70个序列。它们是首shard诊断前缀，不是正式去重切分或已人审训练集；两份报告均保持diagnostic_only=true、training_allowed=false。

原件位于训练根 `data/runs/issue004-debug-probe-20261019-r1/` 与 `issue004-probe-recover-20261019-r4/`。r4已恢复来源下载，最近检查4/10文件通过校验，完整下载仍未验收。今后同规模单元测试和小样本数据检查可按本次限制直接在调试机执行，不再因这类任务排队；全库建库、模型加载和训练另作资源实测。
