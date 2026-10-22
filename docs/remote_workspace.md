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
| `InterClarify/benchmark/fdb_v1_0` | FDB v1.0 评测数据 |
| `interclarify-fdb-two-axes-20261021-r4` | FDB 两轴最终结果 |
| `Full-Duplex-Bench` | 官方 FDB 评分仓库 |
| `interclarify-x2-turn-complete` | X2-Turn 固定输入、模型、离线源码包、锁与回放结果根目录 |

## 固定 conda 环境

| 用途 | 环境 |
| --- | --- |
| 通用与模型服务 | `~/miniconda3/envs/interclarify-dev` |
| FDB 官方评分 | `~/miniconda3/envs/full-duplex-bench` |
| ASR 组件 | `~/interclarify-english-integration-20261018-v1/envs/asr` |
| TTS 组件 | `~/interclarify-english-integration-20261018-v1/envs/tts` |
| FLEURS 数据准备 | `~/miniconda3/envs/interclarify-x2-turn-data`（Python 3.11，固定 `whisper-normalizer==0.1.12`） |
| X2-Turn vLLM 服务 | `~/miniconda3/envs/interclarify-x2-turn-vllm`（Python 3.11，`vllm==0.19.1`、`transformers==5.5.1`） |

`paratalker-dev` 与 `sidecar` 属于其他项目，不纳入 InterClarify 清理。

## 维护记录

2026-10-22 已完成旧训练/选型资产、旧 X2 环境与缓存清理，记录释放约 301G。现役模型、ASR/TTS conda、评分环境、运行快照及 FDB 数据/最终结果保留，旧 X2 模型与环境不能假定仍存在。完整清理明细可从 Git 历史追溯；远端日志为 `~/cleanup_remote_assets.dry-run.log`、`~/cleanup_remote_assets.execute.log` 和 `~/cleanup_second.log`。这些是当时维护记录，新的作业仍须重新预检磁盘和环境。

同日重新登录核查：旧 `interclarify-asr-selection/dataset`、`runs` 和默认 HF 缓存路径不存在；上述 execute/second 两份日志当时也未找到，不能再作为当前可读证据。历史 FLEURS `en_us/test` 100 条的固定 revision、选样规则及可恢复范围见 [核查记录](dev/X2-Turn/fleurs_subset_verification.md)。本次没有恢复或下载数据。

2026-10-22 已按 [X2Q-010](issue/archive/x2q_010_x2_turn_deployment.md) 部署冻结版本 X2-Turn：`models/X2-Turn-4B-0812`（固定 revision）、`models/X2-Turn-4B-0812-vllm`（导出）、`source/x2_turn_sources.tar.gz`（离线源码包）与 `env/x2_turn_*.json` 锁；服务诊断证据在 `runs/deploy-20261022-r4`。安装与下载按用户指示在调试机执行，GPU 推理只走 `vc`。详见[部署报告](../reports/x2_turn_complete/20261022-deploy/README.md)。

2026-10-22 已按 [X2Q-009](issue/archive/x2q_009_fleurs_data.md) 恢复并冻结 FLEURS 英文子集：`interclarify-x2-turn-complete/dataset/fleurs_en_us` 保存 100 test + 1 dev、manifest、数据锁、下载事件和复核日志；独立 conda 与包版本记录在 `interclarify-x2-turn-complete/env`。证据摘要见 [报告](../reports/x2_turn_complete/20261022-fleurs-subset/README.md)。本轮只恢复输入，未部署或运行 X2-Turn。

## 运行约定

- 会话、模型与环境使用 conda；模型和 conda 环境按只读方式复用，不复制权重。
- 每个作业使用独立 `run_id` 与输出目录，保留源码提交、输入摘要、资源上限、退出码和失败日志。
- 维护操作串行执行，优先同文件系统 `rename`，避免复制大模型或音频，也不做无界整盘扫描。
- 删除或迁移前先核对当前作业、磁盘/内存配额和其他项目。
- 当前运行快照与稳定入口之间的映射在任务单中登记，作业运行期间不得删除对应源码。
