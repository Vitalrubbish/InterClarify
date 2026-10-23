# 远端工作目录约定

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
| `interclarify-xturnix-fleurs` | XTurnix FLEURS 冻结输入与后续评测输出；XTX-001 数据在 `dataset/fleurs_en_us`，XTX-002 环境/模型在 `envs/xturnix`、`models/xturnix-pt` |
| `InterClarify/benchmark/fdb_v1_0` | FDB v1.0 评测数据 |
| `interclarify-fdb-two-axes-20261021-r4` | FDB 两轴最终结果 |
| `Full-Duplex-Bench` | 官方 FDB 评分仓库 |

## 固定 conda 环境

| 用途 | 环境 |
| --- | --- |
| 通用与模型服务 | `~/miniconda3/envs/interclarify-dev` |
| FDB 官方评分 | `~/miniconda3/envs/full-duplex-bench` |
| ASR 组件 | `~/interclarify-english-integration-20261018-v1/envs/asr` |
| TTS 组件 | `~/interclarify-english-integration-20261018-v1/envs/tts` |

`paratalker-dev` 与 `sidecar` 属于其他项目，不纳入 InterClarify 清理。

## 维护记录

2026-10-23 完成 XTX-002：在 `interclarify-xturnix-fleurs` 下创建隔离 conda 环境 `envs/xturnix`（Python 3.12.15、torch 2.11.0+cu128、transformers 4.57.1），下载并锁定 `models/xturnix-pt`（`xcczach/xturnix-pt@d4b0403`），只读复核 Nemotron `ebe59e5`。dev 协议证据在 `runs/xtx-002-probe-20261023-r3`；未覆盖现役 ASR/TTS/评分环境。证据见 [XTX-002 报告](../reports/xturnix_fleurs/20261023-xtx-002-protocol/README.md)。

2026-10-23 完成 XTX-001：在 `interclarify-xturnix-fleurs` 新建冻结数据目录，只读复用 `interclarify-x2-turn-complete` 的 TSV 与 101 个 WAV 后重新选择并哈希；未删除旧数据，旧目录仍不恢复为现役依赖。证据见 [XTX-001 报告](../reports/xturnix_fleurs/20261023-xtx-001-data-freeze/README.md)。

2026-10-23 仅回退 InterClarify/X-Talk 仓库中的本轮 X2-Turn 实现和测试，保留现役运行基线。本次没有登录服务器删除模型、conda 环境、固定数据或原始报告；此前新增的 `interclarify-x2-turn-complete` 和两个 X2-Turn conda 环境不再作为现役依赖，其当前远端状态仍需另行核查。不能把本次代码回退解释为已释放远端磁盘。

2026-10-22 已完成旧训练/选型资产、旧 X2 环境与缓存清理，记录释放约 301G。现役模型、ASR/TTS conda、评分环境、运行快照及 FDB 数据/最终结果保留，旧 X2 模型与环境不能假定仍存在。完整清理明细可从 Git 历史追溯；远端日志为 `~/cleanup_remote_assets.dry-run.log`、`~/cleanup_remote_assets.execute.log` 和 `~/cleanup_second.log`。这些是当时维护记录，新的作业仍须重新预检磁盘和环境。

## 运行约定

- 会话、模型与环境使用 conda；模型和 conda 环境按只读方式复用，不复制权重。
- 每个作业使用独立 `run_id` 与输出目录，保留源码提交、输入摘要、资源上限、退出码和失败日志。
- 维护操作串行执行，优先同文件系统 `rename`，避免复制大模型或音频，也不做无界整盘扫描。
- 删除或迁移前先核对当前作业、磁盘/内存配额和其他项目。
- 当前运行快照与稳定入口之间的映射在任务单中登记，作业运行期间不得删除对应源码。
