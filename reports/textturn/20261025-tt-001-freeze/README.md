# TT-001 正式文本数据冻结

2026-10-25 完成。固定 UltraChat revision `f220fe7` 的 train_0 完整963,569,677字节，LFS SHA256为 `83e8bf5ad58dad37317e20daf8dd8fcdf483a8ff29ba73351a47cad3c2cad368`。旧事件文件未恢复，正式时序明确为新构建的合成事件。

| 集合 | 来源对话 | 决策快照 | keep/start/stop |
| --- | --- | --- | --- |
| train | 160 | 10,000 | 9520/320/160 |
| pilot，train子集 | 160 | 2,000 | 1520/320/160 |
| dev | 200 | 13,378 | 12778/400/200 |
| test | 300 | 19,994 | 19094/600/300 |

测试四类各300个来源组；训练完整陈述start为160/320。每条是包含两次start、正常完成、停顿、短附和和打断的连续综合轨迹。控制窗480ms、User随机1—2 token、Assistant每窗8 token，播放完成单独模拟。没有超长排除；全部仅监督最后的动作token。训练对话实际160，未达到1000上限，不把窗口数算成对话。

切分前检查来源前四轮的完整归一化文本精确重复及5词Jaccard≥0.85近重复，843个合格组中按固定种子选择660个。保留Git历史报告中的来源ID及哈希文件名并排除，来源范围进一步限于10000—94999；review来源不进入任何正式集合。同源不跨集合，FDB/FLEURS/Easy Turn均未作为训练来源。历史正文未全部恢复，无法证明全历史语义近重复排除，独立性结论限于已恢复来源标识和本批文本去重。

标注为保守语义规则加代理抽检，非逐例人工审核。正常请求与陈述完整保留；停顿仅放在明确不完整的问句开头。停止指令按首次明确可见的pause/stop/Wait触发，Please前缀保持keep。抽检12条训练来源的完整请求与陈述、4条轨迹的关键窗口，记录见 spot_check.json（原始文件`spot_check.json`已归档）。样例回归及机会评分共11项测试通过；实际模型训练尚待远端运行。

冻结资产位于本地 `artifacts/textturn/tt-001-frozen-r3`，远端目标为 `~/parathink-textturn/dataset/tt-001-frozen-r3`。manifest.json（原始文件`manifest.json`已归档） 保存输入及输出摘要，split_index.json（原始文件`split_index.json`已归档） 保存全部来源和切分。构建入口及说明见 [数据冻结说明](../../../docs/scripts/training/freeze_textturn_dataset.md)。

本交付允许TT-002受限机制试训。短附和和停止指令使用小型模板集合，时序及播放均为合成，尚无可回放语音或Nemotron在线成绩；文本模型测试不能作为TT-004在线通过证据。

## 原始产物保存

本页为Git保留的结果汇总；逐例JSON／CSV、trace、样本正文及资源采样不再入库。本地归档位于`artifacts/report_archive/reports/textturn/20261025-tt-001-freeze/`，具体文件与SHA256见本地`artifacts/report_archive/archive_index.json`；已有远端run路径保持原样。复现时读取归档，不从报告链接下载原始产物。Git历史未重写。
