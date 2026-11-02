# 远端工作目录约定

更新：2026-11-02。用户要求清除`turncontrol-comparison`的全部旧实验，并重新克隆官方SoulX-Duplug。旧comparison结果、源码worktree和`source/6de0d70`加载器退役；模型／评分模型、conda与公共依赖继续保留。新源码入口为`~/parathink-soulx-duplug/upstream/soulx-duplug`的独立官方Git checkout，本地对应`third_party/soulx-duplug`子模块，详见[源码说明](third_party/soulx-duplug.md)。本次不运行推理／训练，历史证据在既有报告和ParaThink runs中保留。

项目现名为 ParaThink。下表中的 `InterClarify`、`interclarify-*` 是已有服务器目录或环境的真实名称，继续保留以兼容现役资产；GitHub 地址与历史报告链接同样保留，未执行远端仓库或目录迁移。新建通用开发环境默认使用 `parathink-dev`。

根目录为 `/hpc_stor03/sjtu_home/xuan.zhang/`。远端只保留当前源码、模型、数据、现役 conda 环境与评测入口；运行输出使用独立目录，不覆盖既有结果。

| 位置 | 用途 |
| --- | --- |
| `InterClarify` | 当前项目仓库 |
| `xtalk` | X-Talk fork 源码；模型库、缓存与日志已移除 |
| `DuplexCascade` | 官方 DuplexCascade 参考仓库 |
| `interclarify-p0-models` | Qwen2-7B、DuplexCascade 权重与 HF 辅助资产 |
| `interclarify-asr-selection/models` | Nemotron 与 alignment 资产 |
| `interclarify-tts-selection-20261018/models` | Kokoro 模型 |
| `interclarify-english-integration-20261018-v1/envs` | 现役 ASR/TTS conda 环境 |
| `interclarify-english-integration-20261018-v6` | 组件入口；`envs` 软链到 v1 |
| `interclarify-runtime-20261021-adopted` | 当前运行时源码快照 |
| `interclarify-runtime-current` | 指向当前运行时快照的稳定入口 |
| `interclarify-xturnix-fleurs` | 历史归档：XTurnix FLEURS 冻结输入与评测输出；XTX-001 数据在 `dataset/fleurs_en_us`，XTX-002 环境/模型在 `envs/xturnix`、`models/xturnix-pt` |
| `InterClarify/benchmark/fdb_v1_0` | FDB v1.0 评测数据 |
| `interclarify-fdb-two-axes-20261021-r4` | FDB 两轴最终结果 |
| `Full-Duplex-Bench` | 官方 FDB 评分仓库 |
| `parathink-textturn` | 历史归档：TextTurn 独立实验；源码`source/`、冻结集`dataset/`、训练`runs/`、提交日志`submit_logs/` |
| `parathink-soulx-duplug` | ParaThink 前端独立部署与检查根目录，复用下面的资产；状态见[部署记录](dev/SoulX-Duplug/deployment.md) |
| `turncontrol-comparison/models/soulx-duplug` | 复用 SoulX tokenizer、基座和状态权重，不复制或修改 |
| `turncontrol-comparison/models/sensevoice-small` | 首版英文 ASR 权重，只读复用 |
| `parathink-soulx-duplug/upstream/soulx-duplug` | 新克隆官方仓库`a0b9063`，独立Git checkout，替代旧comparison源码软链 |
| `turncontrol-comparison/upstream/frozen-20261028/soulx-duplug` | 保留只读上游参考，不作为新实验依赖 |

## 固定 conda 环境

| 用途 | 环境 |
| --- | --- |
| 通用与模型服务 | `~/miniconda3/envs/interclarify-dev` |
| FDB 官方评分 | `~/miniconda3/envs/full-duplex-bench` |
| ASR 组件 | `~/interclarify-english-integration-20261018-v1/envs/asr` |
| TTS 组件 | `~/interclarify-english-integration-20261018-v1/envs/tts` |
| SoulX 与 SenseVoiceSmall | `~/turncontrol-comparison/envs/soulx`，只读复用，不修改该项目依赖 |

`paratalker-dev` 与 `sidecar` 属于其他项目，不纳入 ParaThink 清理。

## 实验与维护记录

以下源码worktree和作业状态均为历史记录；comparison旧实验已按NTF-014清理，不能直接复用已移除的`source/6de0d70`加载器恢复旧教师入口。后续以新的官方checkout为起点，配置与实验需另立工作单。

| 记录 | 证据与状态 |
| --- | --- |
| 固定FDB30同卡对照 | `parathink-soulx-duplug/source/4568ecf`；`runs/ntf009-teacher-fdb30-20261101-r1` 30/30完整、退出0，主块P95 219.2ms、无800ms；状态语义未整体改善，见[报告](../reports/soulx/20261101-ntf009-teacher-fdb30/README.md) |
| 教师单块缓冲与即时发布 | `parathink-soulx-duplug/source/4c81904`；`runs/ntf008-teacher-smoke-20261101-r2` 三轴预检3/3、退出0，主块发布P95≤240.9ms、`buffer_overflow=0`，complete无重识别；`r1`失败run保留，见[报告](../reports/soulx/20261101-ntf008-teacher-buffer/README.md) |
| 教师文本纯追加 | `parathink-soulx-duplug/source/e54a9fe`；`runs/ntf007-teacher-smoke-20261101-r1` 三轴预检3/3、退出0，104项本地通过；无门控、检查点或重放，最大积压555ms，见[报告](../reports/soulx/20261101-ntf007-teacher-append-only/README.md) |
| 双ASR独立计算与配对发布 | `parathink-soulx-duplug/source/101b61a`；预检3/3通过，`runs/dual-asr-fdb30-20261031-r1`正式18/30、12条800ms触限、退出1；2134帧配对审计通过，实时及整体质量未通过；11-01队列为空，见[报告](../reports/soulx/20261031-dual-asr-publication/README.md) |
| 官方格式与门控教师对照 | `parathink-soulx-duplug/source/ba3ba47`；预检3/3通过，`runs/nemotron-teacher-gate-fdb30-20261031-r1`正式25/30、5条积压触限退出1；未见整体质量改善，01:06:38队列为空，见[报告](../reports/soulx/20261031-nemotron-teacher-gate/README.md) |
| 教师文字音频覆盖配对修复 | `parathink-soulx-duplug/source/98f347e`；`runs/nemotron-teacher-align-fdb30-20261030-r1`／`r2` 实际25/30／28/30积压触限，退出1；预检3/3通过，23:39队列为空，见[复测报告](../reports/soulx/20261030-nemotron-teacher-alignment/README.md) |
| Nemotron Teacher Forcing FDB30 | `parathink-soulx-duplug/source/b143bff` 冻结源码；`runs/nemotron-teacher-smoke-20261030-r2` 预检退出0，`runs/nemotron-teacher-fdb30-20261030-r1` 正式小样本；状态以[报告](../reports/soulx/20261030-nemotron-teacher-fdb30/README.md)为准 |
| TT-010 r5有限pilot | 最新记录为2026-10-27 12:47，新版两轮评估完成、当时第3／5轮；源码`source/tt010-repair-20261027-r1`，run `tt010-repair-pilot-20261027-r1`，当前状态未重查，见[修复报告](../reports/textturn/20261027-dataset-repair/README.md) |
| TT-011续接 | r1超时、r2全keep未放行后停止，外部测试未提交；不随有限pilot恢复，见[外部记录](../reports/textturn/20261026-tt-011-external-evaluation/README.md)与[r2报告](../reports/textturn/20261026-tt-010-balanced-training/README.md) |
| TT-005—008 | FDB两周期及UltraChat重测均交付，见[FDB联合结果](../reports/textturn/20261025-fdb-action-only/README.md)与[UltraChat结果](../reports/textturn/20261025-ultrachat-prefix-retest/README.md) |
| TextTurn初始训练与验收 | TT-001数据`dataset/tt-001-frozen-r3`，Qwen3-0.6B位于`models/qwen3-0.6b`；训练run `tt-002-20261025-r1`，见[验收报告](../reports/textturn/20261025-tt-004-results/README.md)与[v2评分](../reports/textturn/20261025-scoring-v2/README.md) |
| XTurnix冻结环境与数据 | 隔离环境`interclarify-xturnix-fleurs/envs/xturnix`、模型`models/xturnix-pt`；[数据报告](../reports/xturnix_fleurs/20261023-xtx-001-data-freeze/README.md)、[协议报告](../reports/xturnix_fleurs/20261023-xtx-002-protocol/README.md) |
| 2026-10-24阈值实验撤回 | 18个过期worktree、7份脚本已清理；5个原始run及离线输入／日志移至`~/interclarify-retired-threshold-experiments-20261024/`，清单`cleanup_manifest.json`；模型、conda与原始FLEURS/FDB资产保留，明细从Git历史追溯 |
| 旧X2资产清理 | 2026-10-22曾记录释放约301G；后续代码回退不等于远端资产释放。历史日志`~/cleanup_remote_assets.dry-run.log`、`~/cleanup_remote_assets.execute.log`、`~/cleanup_second.log`，当前环境与空间不能由旧记录推断 |

历史`Running`、PID和剩余额度均是当时观察，不代表现在仍有效。TT-010后来取消训练总时限及旧累计GPU预算，有限pilot仍按既定轮数结束，全部非时长资源限制保留；其他实验按各自已确认预算执行。

## 运行约定

- 会话、模型与环境使用 conda；模型和 conda 环境按只读方式复用，不复制权重。
- 每个作业使用独立 `run_id` 与输出目录，保留源码提交、输入摘要、资源上限、退出码和失败日志。
- 维护操作串行执行，优先同文件系统 `rename`，避免复制大模型或音频，也不做无界整盘扫描。
- 删除或迁移前先核对当前作业、磁盘/内存配额和其他项目。
- 当前运行快照与稳定入口之间的映射在任务单中登记，作业运行期间不得删除对应源码。
