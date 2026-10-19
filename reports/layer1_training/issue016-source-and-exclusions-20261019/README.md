# 来源验真与外部隔离进度

源码：dc0cc7b/dfd36d3。UltraChat固定revision为f220fe796ce3ed62fbe1681b45ce6cbc9c6cabe0，10个shard共9,288,990,895字节已全部下载、大小/SHA256核验通过；恢复任务最终退出0。调试机另外以单CPU、512MiB地址空间硬限和240秒墙钟上限独立复核，44.31秒完成、峰值19,656KiB、退出0。

逐文件URL/大小/摘要、下载及独立复核退出码见 [source_verification.json](source_verification.json)。正式切分尚未生成，源文件完成不表示004/006放行。下载恢复004a已归档。

## 实际排除清单

`manifests/exclusions.json`已在远端生成，SHA256为877836703f689380e2087dd3e9fdb7b989c24ee6917feafb269a7b118a667997。包含3325个规范化文本摘要、1186条逐文件来源记录；来源、覆盖计数和缺测ID见 [exclusion_coverage.json](exclusion_coverage.json)。保留完整清单在远端，仓库回收摘要和精确引用。

FLEURS为100条test及1条dev，全部排除；历史五例使用真实Word事件文本。FDB v1.0五子集共727例目录齐全，其中synthetic_user_interruption的context/interrupt字段可用；candor_turn_taking的119例只有TURN-TAKING时间标注，无transcription.json或其他普通文本。标记不当作正文，未虚构转写；reviewed和coverage_complete均false。其余来源已提取文本，完整文本隔离尚有119例缺口。

[3项排除工具测试](exclusion_tests.txt)在本地和远端均通过，检查缺文本拒收、确定性和逐轮命中排除。实际构建在调试机单CPU、nice10、2GiB地址空间限制下执行，未读取模型、未申请GPU。清单ID只作外部来源溯源，不与UltraChat数字ID混用。

本任务的来源验真已完成；[016](../../../docs/issue/016_external_data_exclusion.md)继续跟踪转写覆盖缺口，不能把本文当作全部隔离审查已完成。
