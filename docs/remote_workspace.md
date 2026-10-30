# 远端工作目录约定

更新：2026-10-30。本文维护目录与环境位置，历史作业进度统一链接报告；本次已登录贵州 HPC，复用 Nemotron 与 SoulX 的模型及两组 conda，实施教师文字同步前端。其他路径和历史作业不由此推断当前状态。

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
| `turncontrol-comparison/upstream/frozen-20261028/soulx-duplug` | 已核查 `a0b9063` 官方源码，只读复用 |

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

| 记录 | 证据与状态 |
| --- | --- |
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
