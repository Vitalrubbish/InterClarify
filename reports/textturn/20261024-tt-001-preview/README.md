# TT-001：连续综合话轮检查批次

更新：2026-10-25。按用户反馈，当前检查批次以**连续综合话轮**为单位，替换此前按纯Listen／纯Speak阶段分开的15个场景。六个固定来源各构建一条轨迹，每条都跨越Listen和Speak，含两次start，保留同一时钟和当前已经可见的历史。

保持480ms控制窗、User非空输入随机1—2 token、Assistant每窗8 token模拟生成。随机话中停顿、剩余播放尾窗和下一轮等待仍分开处理；没有训练模型、执行GPU作业或接入真实播放器。**本批全为review，TT-001仍实施中，正式来源及切分尚未冻结。**

直接查看综合轨迹逐窗表（原始文件`samples.md`已归档），表中动作均为监督目标；review_samples.json（原始文件`review_samples.json`已归档）保留每窗完整输入及动作loss mask，timelines.json（原始文件`timelines.json`已归档）记录观察和状态执行事件，source_records.json（原始文件`source_records.json`已归档）保留来源，manifest.json（原始文件`manifest.json`已归档）给出目标及缺口。

## 六条片段包含什么

| 轨迹 | 连续路径 | 观察窗 |
| --- | --- | --- |
| mixed_dialogue_2 | 陈述输入→start→生成完且仍播放→用户打断stop→继续用户表达→再次start→正常播完→等待 | 29 |
| mixed_dialogue_3 | 陈述输入→start→I see附和→正常播完→下一轮陈述→再次start→正常播完→等待 | 83 |
| mixed_dialogue_0 | 提问及话中停顿→start→Hmm附和→用户打断stop→续说新要求→再次start→正常播完→等待 | 57 |
| mixed_dialogue_9 | 提问及话中停顿→start→Right附和→正常播完→下一轮陈述→再次start→正常播完→等待 | 42 |
| mixed_dialogue_19 | 提问→start→Hmm附和→正常播完→下一轮请求→再次start→正常播完→等待 | 97 |
| mixed_dialogue_6 | 提问→start→I see附和→用户拒绝后stop→继续用户表达→再次start→正常播完→等待 | 35 |

例如mixed_dialogue_2的一段真实构建结果如下；不重复列更早的用户陈述分片。

| 时刻 | 状态／事件 | User新增 | Assistant新增／状态 | 目标token |
| --- | --- | --- | --- | --- |
| 5280ms | Listen | no-voice，完整陈述已让轮 | 尚未生成回答 | tt_start |
| 5280ms | 模拟仲裁接受start | — | Listen→Speak | 无新动作 |
| 5760—8160ms | Speak | no-voice | 按8 token／窗推进，末窗生成完 | 每窗tt_keep |
| 8640ms | Speak | no-voice | 已生成完，尚在播放 | tt_keep |
| 9120ms | Speak | Please | 无新助手文本 | tt_keep |
| 9600ms | Speak | stop | 仍在播放 | tt_stop |
| 9600ms | 模拟仲裁接受stop | 已到达的打断文本保留 | Speak→Listen，只保留已生成前缀 | 无新动作 |
| 10080—11040ms | Listen | I love visiting the ocean分片到达 | 不再生成原回答 | 每窗tt_keep |
| 11520ms | Listen | no-voice，新表达已让轮 | 尚未生成下一回答 | tt_start |
| 11520ms后 | Speak | no-voice | 生成下一回答→剩余播放尾窗→playback_complete→Listen等待 | 每观察窗tt_keep |

这些状态变化模拟唯一仲裁器接受监督动作，先保留动作执行前的快照，再记录执行事件；不把模型预测直接当成已播放。正常playback_complete不产生stop。

## 当前统计

| 项目 | 实际值 |
| --- | --- |
| 来源／去重组／综合轨迹 | 6／6／6 |
| 同时有Listen和Speak的轨迹 | 6／6 |
| 逐窗快照／有标签／未标注 | 343／343／0 |
| keep／start／stop | 328／12／3 |
| 陈述式start | 6／12，50% |
| Assistant非空生成窗 | 153；143窗为8 token，其余10个末块为1—7 token |
| 无新增用户文字的观察窗 | 207／343，约60.3%；不等同声学静音 |
| 最大输入／超长排除 | 667 token／0 |
| 正式train／dev／独立test | 0／0／0 |

类别按同一综合轨迹内的阶段记录：smooth共122窗，natural_completion 187窗，interruption 13窗，backchannel 5窗，pause 16窗。不同来源组分别为6、6、3、5、2，不能跨类别相加当作更多独立对话。343个窗口也不等于343个独立场景；正式训练分层采样及规模目标仍以工作单为准，不能用本批大量keep宣称质量达标。

## 上下文与来源边界

- start执行后才把当前用户文字提交为完整用户历史，下一窗开始发布助手增量；start快照不能看到下一回答。每条轨迹的第二次start读取前面真实已构造的上下文，不另建独立会话。
- 短附和在Speak中标keep，结束后以backchannel标记写入历史，清空当前用户缓冲，避免与后续新请求粘连；助手保持Speak。
- stop执行后停止本轮生成，已生成前缀保留generated_only/interrupted标记，不当作完整已播放回答。当前用户打断文字不清空，同阶段尚未到达的文字及后续续说继续在Listen累加。未生成的助手后缀不进入后续历史。
- 正常生成结束不退出Speak；随机1—3窗播放尾巴后，playback_complete将已完成正文入历史，再转Listen并随机等待1—5窗。当前窗口计数和生成完成状态可见，未来等待长度及语义计划不可见。
- 若续说改变了原请求，后续助手回答使用显式synthetic_annotation短文本，不能冒称是原UltraChat回答或模型实测输出。其余回答引用固定来源的相应turn，完整原始记录保留。

## 验证及未完成项

八项单线程CPU契约测试通过；其中综合测试跨越两次start、一次stop及自然完成，核对用户剩余文字不丢失、附和只关闭一次、未来助手后缀不泄漏。实际Qwen tokenizer逐窗复核343个输入／动作mask／历史缓冲、153个助手前缀、五次附和关闭及三次打断上下文提交，全部模板和tokenizer重载一致；重复构建产物相同，六条轨迹均含两种状态及两次start。证据见audit.json（原始文件`audit.json`已归档）、verification.json（原始文件`verification.json`已归档）和sha256.json（原始文件`sha256.json`已归档）。

来源、tokenizer revision及上游下载证据不变：固定UltraChat revision f220fe796ce3ed62fbe1681b45ce6cbc9c6cabe0的分片前1MiB，仅取完整行，未完成整分片LFS核验。Qwen3-0.6B tokenizer固定c1899de289a04d12100db370d81485cdf75e47ca。所有同源派生在review，未完成旧来源分组／切分和测试使用历史核验，正式1000训练／200开发／300测试对话目标及真实语音仍缺。

480ms、8 token和随机等待只是合成调度，没有真实Nemotron／LLM／TTS时间戳，也不具备独立模型评测结果。training_allowed=false、independent_test_ready=false，TT-001不归档。

实现为[构建器](../../../scripts/training/build_textturn_dataset.py)，参数见[配置](../../../configs/textturn_dataset_preview.json)，使用方法见[中文说明](../../../docs/scripts/training/build_textturn_dataset.md)。本地复用conda interclarify-dev、CPU线程1；完整tokenizer及JSONL候选保留artifacts/textturn/tt-001-review-final。目录日期保留首次交付日期，本页更新日期表示当前版本。

## 原始产物保存

本页为Git保留的结果汇总；逐例JSON／CSV、trace、样本正文及资源采样不再入库。本地归档位于`artifacts/report_archive/reports/textturn/20261024-tt-001-preview/`，具体文件与SHA256见本地`artifacts/report_archive/archive_index.json`；已有远端run路径保持原样。复现时读取归档，不从报告链接下载原始产物。Git历史未重写。
