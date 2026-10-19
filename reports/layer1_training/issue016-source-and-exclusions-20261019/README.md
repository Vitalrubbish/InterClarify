# 来源验真与外部隔离进度

源码：dc0cc7b/dfd36d3。UltraChat固定revision为f220fe796ce3ed62fbe1681b45ce6cbc9c6cabe0，10个shard共9,288,990,895字节已全部下载、大小/SHA256核验通过；恢复任务最终退出0。调试机另外以单CPU、512MiB地址空间硬限和240秒墙钟上限独立复核，44.31秒完成、峰值19,656KiB、退出0。

逐文件URL/大小/摘要、下载及独立复核退出码见 [source_verification.json](source_verification.json)。正式切分尚未生成，源文件完成不表示004/006放行。下载恢复004a已归档。

## 实际排除清单

初次`manifests/exclusions.json`的SHA256为877836703f689380e2087dd3e9fdb7b989c24ee6917feafb269a7b118a667997，包含3325个文本摘要和1186条来源记录；原检查口径与范围见 [exclusion_coverage.json](exclusion_coverage.json)。用户随后取消FDB补转写要求，实际清单已按下述范围修正重建，旧原件另存，不覆盖历史证据。

FLEURS为100条test及1条dev，历史五例使用真实Word事件文本。FDB v1.0五子集共727例目录齐全；candor_turn_taking的119例无普通文本。初版错误地将此设为训练前置，现按用户要求取消，不补转写、不虚构文本。训练只读取固定UltraChat，FDB单独用于评测，已有文本摘要仅辅助重复检查。

[3项排除工具测试](exclusion_tests.txt)在本地和远端均通过，检查缺文本拒收、确定性和逐轮命中排除。实际构建在调试机单CPU、nice10、2GiB地址空间限制下执行，未读取模型、未申请GPU。清单ID只作外部来源溯源，不与UltraChat数字ID混用。

范围修正提交d7b90ca，远端run_id为issue016-scope-correction-r2：清单按实际源文件重建，reviewed/coverage_complete=true表示来源清点通过，text_coverage_complete=false仍如实记录可选文本范围；3325个辅助摘要与之前完全相同。新SHA256为6599f6968dfaf83185812eedceaace8e7a8ea5b57967a5ffa51269b3aec40944，见[修正记录](scope_correction.json)与[4项远端回归](scope_correction_tests.txt)。[016](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/016_external_data_exclusion.md)完成归档，正式数据生成、人审及005/007继续独立验收。
