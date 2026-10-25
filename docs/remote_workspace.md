# 远端工作目录约定

2026-10-25启动TT-008：源码`3fa4481`位于`~/parathink-textturn/source/tt008-r1`，冻结清单`dataset/tt-008-ultrachat-r1/manifest.json`；run为`tt-008-20261025-r1`，作业`job-179292031704516676972-xuan-zhang`。480ms首阶段已稳定运行，160ms在同作业内串行接续；原预算提交前剩7549 GPU秒，单作业上限7200秒。详见[运行记录](../reports/textturn/20261025-ultrachat-prefix-retest/README.md)，尚未完成两周期结果交付。

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

`paratalker-dev` 与 `sidecar` 属于其他项目，不纳入 ParaThink 清理。

## 维护记录

2026-10-25最终核查：160ms作业`job-179291166384532199286-xuan-zhang`于15:26:47正常结束，100/100、退出码0、1540秒；480ms为100/100、退出码0、1530秒。两次均未知0，无活动作业。全部200条trace、输入及模型摘要、计时及本地评分产物摘要核对完成，终检JSON为`~/parathink-textturn/inspection/fdb-action-final-audit-20261025.json`。TT-005／006／007已交付归档，本轮累计21251GPU秒，低于8小时。见[联合结果](../reports/textturn/20261025-fdb-action-only/README.md)。

2026-10-25最新状态：480ms `tt-005-006-20261025-r4`在14:56:10结束，100/100、退出码0、实际1530秒。160ms原续接进程已退出且日志无原因，旧waiting状态已备份；在无活动作业、累计预算核对后补交`tt-007-20261025-r1`，作业`job-179291166384532199286-xuan-zhang`当前Running，源码仍为`4e325bb`、输入及候选不变。补交前剩9089秒，本次上限7200秒。

2026-10-25用户纠正FDB仅监控TextTurn：旧r3已停止，实际占卡1012秒并保留trace。修正源码`4e325bb`冻结在`~/parathink-textturn/source/fdb-action-v1`；480ms run为`tt-005-006-20261025-r4`，作业`job-179290983788774807672-xuan-zhang`运行中。160ms run预留`tt-007-20261025-r1`，清单已冻结，续接器等待r4成功结束并释放GPU后重新核算预算提交，此时尚无160ms GPU作业。r4提交前累计18181秒、剩10619秒。详见[动作监控运行记录](../reports/textturn/20261025-fdb-action-only/README.md)。下方r1—r3条目是历史记录，不代表当前继续执行模拟回答协议。

2026-10-25按用户指令启动TT-005／006：共用源码冻结于`~/parathink-textturn/source/fdb-v3`（`9d5376d`），50＋50录音清单为`dataset/tt-005-006-fdb-r2/manifest.json`。当前run为`tt-005-006-20261025-r3`、调度ID为`job-179290834177188572331-xuan-zhang`，单卡串行、最多2小时。r1摘要抄写错误及r2磁盘监控格式问题已修复并保留原日志、trace和实际占卡；r3提交前累计占卡17169秒，剩11631秒。详见[联合运行记录](../reports/textturn/20261025-fdb-cross-dataset/README.md)。当前为执行阶段，未交付正式成绩、未归档工作单。

2026-10-25评分修复：独立源码`~/parathink-textturn/source/scoring-v2`冻结`ec0bf36`，用已有conda数据环境执行单线程标准库离线重评，2GiB地址空间、60秒超时，无GPU任务。输出`inspection/scoring-v2/formal-r2`及`text-r2`；模型和v1结果未修改。[v2报告](../reports/textturn/20261025-scoring-v2/README.md)记录未知覆盖与训练构造／配比审核，接话语义标注仍不足。

2026-10-25后续核查：TextTurn训练`tt-002-20261025-r1`和评估`tt-004-20261025-r1`均退出码0，评估调度ID为`job-179287011405618549973-xuan-zhang`，当前无活动作业。full第2轮候选保留在训练run的`best`；正式300来源／1200语音场景结果见[核查报告](../reports/textturn/20261025-tt-004-results/README.md)。语音原始未通过，评分口径缺口待修正，不再把pipeline的evaluation_submitted视为未执行。原始日志、adapter及语音资产均未删除，本次只读取并取回结果，无新增GPU作业。

2026-10-25 新建 `~/parathink-textturn`，TT-001正式数据位于 `dataset/tt-001-frozen-r3`，固定Qwen3-0.6B位于 `models/qwen3-0.6b`。训练源码 `source/74b0846`，训练run为 `runs/tt-002-20261025-r1`，4090单卡作业 `job-179286310634760697957-xuan-zhang`。只读复用已由conda创建的XTurnix隔离环境；ASR/TTS仍使用现有各自conda，不在现役环境安装依赖。评估源码位于 `source/evaluation-v1`，续接器状态在 `submit_logs/tt-004-20261025-r1.pipeline.json`；成功放行后才提交评估，不把等待状态写为完成。原主仓库未被reset或覆盖。

2026-10-24 按用户要求将当前实现恢复至阈值实验前的 `13ba980`，清除 XTurnix 实验目录下 18 个过期源码 worktree 与 7 份撤回实验启动脚本。其后产生的 5 个原始 run、离线输入及对应日志已移至 `~/interclarify-retired-threshold-experiments-20261024/`，清单为 `cleanup_manifest.json`；这些只保留历史证据，不是现役入口。模型、conda、现役运行快照和原 FLEURS/FDB 资产保留，详见[回滚记录](dev/XTurnix/rollback_cleanup.md)。

2026-10-23 完成 XTX-002：在 `interclarify-xturnix-fleurs` 下创建隔离 conda 环境 `envs/xturnix`（Python 3.12.15、torch 2.11.0+cu128、transformers 4.57.1），下载并锁定 `models/xturnix-pt`（`xcczach/xturnix-pt@d4b0403`），只读复核 Nemotron `ebe59e5`。dev 协议证据在 `runs/xtx-002-probe-20261023-r3`；未覆盖现役 ASR/TTS/评分环境。证据见 [XTX-002 报告](../reports/xturnix_fleurs/20261023-xtx-002-protocol/README.md)。

2026-10-23 完成 XTX-001：在 `interclarify-xturnix-fleurs` 新建冻结数据目录，只读复用 `interclarify-x2-turn-complete` 的 TSV 与 101 个 WAV 后重新选择并哈希；未删除旧数据，旧目录仍不恢复为现役依赖。证据见 [XTX-001 报告](../reports/xturnix_fleurs/20261023-xtx-001-data-freeze/README.md)。

2026-10-23 仅回退 ParaThink/X-Talk 仓库中的本轮 X2-Turn 实现和测试，保留现役运行基线。本次没有登录服务器删除模型、conda 环境、固定数据或原始报告；此前新增的 `interclarify-x2-turn-complete` 和两个 X2-Turn conda 环境不再作为现役依赖，其当前远端状态仍需另行核查。不能把本次代码回退解释为已释放远端磁盘。

2026-10-22 已完成旧训练/选型资产、旧 X2 环境与缓存清理，记录释放约 301G。现役模型、ASR/TTS conda、评分环境、运行快照及 FDB 数据/最终结果保留，旧 X2 模型与环境不能假定仍存在。完整清理明细可从 Git 历史追溯；远端日志为 `~/cleanup_remote_assets.dry-run.log`、`~/cleanup_remote_assets.execute.log` 和 `~/cleanup_second.log`。这些是当时维护记录，新的作业仍须重新预检磁盘和环境。

## 运行约定

- 会话、模型与环境使用 conda；模型和 conda 环境按只读方式复用，不复制权重。
- 每个作业使用独立 `run_id` 与输出目录，保留源码提交、输入摘要、资源上限、退出码和失败日志。
- 维护操作串行执行，优先同文件系统 `rename`，避免复制大模型或音频，也不做无界整盘扫描。
- 删除或迁移前先核对当前作业、磁盘/内存配额和其他项目。
- 当前运行快照与稳定入口之间的映射在任务单中登记，作业运行期间不得删除对应源码。
