# 实验报告

Git只保留审阅后的README汇总：结论、关键分母、限制、源码／模型版本和原始产物位置。逐例JSON／CSV、trace、样本正文、资源采样与完整manifest保存在远端run及本地artifacts，不再推送到GitHub，也不使用git add -f绕过此规则。

## 当前SoulX前端结果

| 报告 | 状态与用途 |
| --- | --- |
| [SharedContext实现与音频检查](soulx/20261029-shared-context/README.md) | 六视图实时回放完成，145次ASR／299条状态／每消费者912事件一致；2个非静音视图仍有正文缺口，backchannel音频预测未覆盖 |
| [已有轨迹的转写稳定时间](soulx/20261030-asr-stability/README.md) | 两个主视图23个可确认前缀端点：最后变化中位0.64秒／额外2次更新，三次确认中位1.12秒／额外5次更新；三次一致仍有后续改写反例 |
| [远端FDB延迟核查](soulx/20261030-fdb-latency/README.md) | 实际读取远端最终报告：SoulX完整链路平均接话1.256秒、打断后回复1.732秒；P95分别2.492／3.040秒，不是ASR稳定耗时 |
| [FDB原始转写稳定与提交等待](soulx/20261030-fdb-asr-stability/README.md) | 672条ASR轨迹重建通过；7103个可确认前缀端点三次确认新增等待中位481ms、P95约1603ms；5894个端点缺证据，三次一致仍有后续改写 |

## 当前TextTurn结果

| 报告 | 状态与用途 |
| --- | --- |
| [新版数据修复与pilot训练](textturn/20261027-dataset-repair/README.md) | r5数据160／54／200来源，52656／9526／75767窗；本地及远端核查通过，有限pilot训练已Running，质量待评 |
| [FDB提前start与stop诊断](textturn/20261025-fdb-start-stop-audit/README.md) | 141次提前start均为空窗，但存在未完成语义；stop均0，输入合同差异与960ms持续状态需分开解释，无新模型作业 |
| [FDB 480ms与160ms对照](textturn/20261025-fdb-action-only/README.md) | 同样本两次各100条，均退出码0、未知0；仅监控TextTurn动作，TT-005／006／007已归档 |
| [句末start行为计数](textturn/20261025-start-after-end/README.md) | 原600条中，原录音发完后出现start为365条；需按句末Listen/Speak分层解释，不能视作语义正确率 |
| [评分v2与数据审核](textturn/20261025-scoring-v2/README.md) | 错误与未知分开；原接话语义评分仍未完成，数据构造及采样建议未实施 |
| [训练与验收核查](textturn/20261025-tt-004-results/README.md) | 训练完成，合成文本达标；语音原始评分缺陷已披露 |
| [训练交付](textturn/20261025-tt-002-training/README.md) | full第2轮候选已保存并重载验证，不代表全部能力通过 |
| [数据冻结](textturn/20261025-tt-001-freeze/README.md) | train/dev/test为160/200/300来源，训练10000窗 |
| [早期检查样例](textturn/20261024-tt-001-preview/README.md) | 历史review批次，非正式训练或验收成绩 |

[FDB各50条外部测试](../docs/dev/TextTurn/fdb_cross_dataset_plan.md)及160ms同样本对照均已交付；两次3周期门槛的名义时长不同，等待均值须保留各自有效样本分母，不代替完整四类验收。

## 历史结果

| 报告 | 用途与限制 |
| --- | --- |
| [FDB完整两轴r4](fdb/20261021-full-two-axes-r4/README.md) | 旧候选319例，非当前TextTurn结果，GPT相关性待补 |
| [FDB固定子集](fdb/20261021-asr-subset-r1/README.md) | 历史25例记录，不与当前条件直接合并 |
| [XTurnix输入冻结](xturnix_fleurs/20261023-xtx-001-data-freeze/README.md) | 旧路线来源与基线 |
| [XTurnix协议](xturnix_fleurs/20261023-xtx-002-protocol/README.md) | 旧模型、环境及协议 |
| [XTurnix回放器](xturnix_fleurs/20261023-xtx-003-replay/README.md) | 旧回放实现记录 |
| [XTurnix评分器](xturnix_fleurs/20261023-xtx-004-scoring/README.md) | 旧离线评分记录 |
| [XTurnix冒烟](xturnix_fleurs/20261023-xtx-005-smoke-a10/README.md) | 旧路线5例诊断，非正式100例成绩 |
| [XTurnix pause诊断](xturnix_fleurs/20261023-pause-token-probe/README.md) | 旧输入格式诊断，不恢复已取消实验 |
| [来源审核](xturnix_training/20261023-source-audit/README.md) | 旧48会话来源审核，非训练通过 |

## 原始产物归档

2026-10-25按用户要求将59个原始产物移出Git当前树，原始字节约6.08MiB；本地文件保留在`artifacts/report_archive/reports/`，相对目录不变。`artifacts/report_archive/archive_index.json`记录逐文件原路径、归档路径、大小及SHA256，索引本身也不入库。远端原始模型、录音、日志和run未删除，具体路径见各报告。Git历史未重写。

`reports/.gitignore`默认拒绝原始产物，只放行目录、README.md及忽略规则。后续报告把必要数字写进汇总，产物仍在远端或artifacts复现，不把整批输入、预测或逐例证据当文档推送。
