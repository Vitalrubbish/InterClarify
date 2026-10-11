# 第一套 X-Talk 组件组合与连接基线

## 1. 文档作用

本文是当前 X-Talk 运行底座的唯一长期登记：固定已验证的来源、组件、运行配置和连接验收结论。它替代已完成的模型准备、适配器设计、轮次检测迁移和框架接通任务单；这些历史过程仍可从 Git 历史追溯，但不再作为当前执行入口。

当前阶段只进入 X-Talk fork 的 P1 控制层改造。Layer 0 和 System Backchannel 保持关闭；InterClarify 的 Layer 2 不在本阶段实现。

## 2. 固定来源与组件

| 项目 | 当前固定值 | 说明 |
| --- | --- | --- |
| X-Talk fork | `Vitalrubbish/xtalk`，`feature/qwen3-asr-adapter@d9303c819c96230e527ea5159e7c74f1b5841a3e` | 当前联调提交；上游基座为 `5f0d9959edf1026588246efbed827b078cbb114c` |
| 远端镜像 | `sjtu_yukai-xuanzhang-xtalk-round1:v0.3`，digest `sha256:a8eb99d8cafadc7f906ae6b24378f6686ce0c52ab8ac063b9c4f59de8ed47d23` | 已用于本次复测；镜像标签不能替代 fork 提交 |
| ASR | `Qwen/Qwen3-ASR-1.7B` + `Qwen3ASRClient` | 独立 ASR conda 环境和 HTTP 服务；返回累计文本，支持修订、临时 flush、`reset` 与 `clone` |
| LLM | `Qwen/Qwen3-8B-AWQ` + `DefaultAgent` | vLLM 服务；`enable_thinking=false` |
| TTS | `OpenMOSS-Team/MOSS-TTS-Realtime` + `MOSS-Audio-Tokenizer` | 唯一 TTS/播放链路；使用 `flash_attention_2` |
| 轮次检测 | TurnSense ONNX 服务 | 音频式 complete/incomplete/invalid 判断，不使用 XTurnix |
| 系统附和 | `backchannel_model=null`，`backchannel_source_dir=null` | System Backchannel 和 Layer 0 均关闭 |

具体模型来源、端口、依赖版本、GPU 分配和流式参数见 [configs/xtalk_round1.yaml](../configs/xtalk_round1.yaml)。可直接由 `Xtalk.from_config` 实例化的组件配置见 [configs/xtalk_round1_runtime.json](../configs/xtalk_round1_runtime.json)。

## 3. 已通过的连接门禁

2026-10-11 在 `d9303c8` 上完成远端复测：作业 `job-179169773753587979695-xuan-zhang`，节点 `d6-hpc-gpu-054`，tag `20261011T054900Z`，共 8/8 steps PASS、`failures=0`。

- 两轮顺序会话均得到独立 `response_id`、`response_finished=true`、`audio_received=true` 和 `audio_before_tts_finished=true`，报告为 `status=COMPLETE` 且 `errors=[]`。
- 播放开始后发送有效插话，旧响应收到 `stop_tts`，新响应完成；`barge_in_stop_observed=true`、`continuation_finished=true`，且没有把旧响应的完成事件误计为新响应完成。
- Qwen ASR 适配器离线契约测试 9/9 通过；InterClarify 的 link-driver 回归 6/6 通过；本仓库完整本地测试 21/21 通过。

远端产物保存于 `…/xtalk-round1/artifacts/link/20261011T054900Z/`，并复制到被 Git 忽略的 `data/runs/20261011T054900Z/`。headless 客户端的音频回执只验证交付、停止和响应生命周期，不代表声卡播放质量。

## 4. 当前保留的远端入口

- [run_xtalk_round1.py](scripts/remote/run_xtalk_round1.md)：模型锁、依赖检查与服务启动；
- [run_xtalk_round1_node_job.sh](scripts/remote/run_xtalk_round1_node_job.md)：集群节点中的 `asr`、`services`、`chain`、`link` 执行；
- [submit_xtalk_round1_job.sh](scripts/remote/submit_xtalk_round1_job.md)：提交远端作业；
- [qwen3_asr_service.py](scripts/remote/qwen3_asr_service.md)、[TurnSense 服务](scripts/remote/turnsense/README.md) 和 [xtalk_link_check.py](scripts/remote/xtalk_link_check.md)：当前连接链路的服务与验收驱动。

运行前后均使用 conda 环境。若更换此表中的 X-Talk 提交、模型、轮次检测器或播放链路，必须重新运行 `link` 的顺序和插话检查。

## 5. 下一阶段边界

连接通过不代表 P1 完成。下一步遵循 [xtalk_modification_plan.md](xtalk_modification_plan.md) 实现并测试：

1. 前缀版本、请求/候选/响应 ID 与统一事件时间线；
2. micro-turn 调度和 Layer 1 的 `SILENCE` / `ANSWER` 候选；
3. 单一 `OutputArbiter` 与单一播放所有权；
4. 提前回答、用户附和与有效插话的区分，以及 FDB smoke。

正式模型基线冻结、中文/多场景质量评测、长会话、Layer 2 主动澄清和真人实验仍未开始。
