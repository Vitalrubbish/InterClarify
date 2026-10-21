# 远端工作目录约定

根目录为 `/hpc_stor03/sjtu_home/xuan.zhang/`。只在顶层保留当前源码、模型/数据、现役conda和训练入口；同一实验完成后的源码快照、失败日志、试听和报告放入 `interclarify-archive/`，不再继续堆放顶层版本目录。

| 位置 | 用途 |
| --- | --- |
| `InterClarify`、`xtalk`、`DuplexCascade` | 当前项目仓库与官方参考 |
| `interclarify-layer1-training-20261019` | 当前数据获取、独立训练环境与后续训练准备 |
| `interclarify-asr-selection`、`interclarify-tts-selection-20261018` | 实际模型、数据和环境种子；名字虽旧，当前仍被依赖 |
| `interclarify-english-integration-20261018-v1`、`v6` | v1承载实际组件conda，v6是现行路径入口，不能移动绝对prefix |
| `interclarify-p0-models`、`interclarify-kyutai`、`interclarify-x2` | 官方/base资产、Kyutai参考及X2历史诊断（仓库内实现已移除） |
| `interclarify-archive/runs/<原目录名>` | 已结束的对齐、集成快照、TTS修复和B0诊断原件 |
| `interclarify-archive/maintenance/`、`transfers/` | 清理/迁移记录及恢复档、历史传输包 |

2026-10-19已归拢24个历史目录，顶层可见目录50→26，删除1个空目录；精确路径迁移见 [清单](../reports/maintenance/20261019-home-consolidation/result.json)。旧报告中的绝对路径继续表示当时运行来源，查找当前原件应按清单映射，不能为改路径而改写实验摘要。

维护操作串行执行，优先同文件系统rename，避免复制大模型和音频或高并发整盘扫描。现役环境先查软链接和conda注册，不移动嵌入绝对prefix的环境；当前任务、磁盘/内存和作业配额均须先核对。其他项目、共享包缓存和原始研究结果不因名称过时而删除。

014进一步直接删除旧选型的Nemotron多语/Python Kyutai/Pocket权重及前两者专用环境，还有已结束TTS实验的编译缓存；只保留来源和配置，现役模型/环境种子及原始结果仍在。此项释放与012归拢分开计量，见[014记录](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/014_remote_cache_reclamation.md)。

2026-10-21 延迟测试依赖检查：最终候选训练manifest仍引用 `interclarify-layer1-training-20261019/source/91b7eb2/reports/layer1_training/issue001-inventory-20261018/inventory_summary.json`。该清单是现役权重加载依赖，误删后已按训练登记SHA256恢复；使用当前加载器期间保留此文件。延迟测试独立快照位于 `interclarify-latency-20261021-r2/source`，不可在对应作业运行中删除；恢复与重提见Issue 050。

2026-10-21用户采用300ms首段及KV复用后，当前可用运行快照为`interclarify-runtime-20261021-adopted/source`，稳定入口`interclarify-runtime-current`指向该快照。后续延迟任务将`LATENCY_SOURCE`设为该入口、`LAYER1_XTALK_ROOT`设为其`xtalk`子目录，并使用独立输出目录；脚本只执行current条件。旧049/051/061冻结实验源码不改写，远端旧`xtalk`工作区的其他修改保持原样。本次只同步默认值和脚本，未启动新GPU测试。
