# 首轮验收结果：Qwen ASR + MOSS TTS 模型服务

本文件记录按 [xtalk_round1_baseline.md](xtalk_round1_baseline.md) 执行的首轮验收证据。运行镜像 `sjtu_yukai-xuanzhang-xtalk-round1:v0.1`（直接基于 `xtalk:v0.17` 构建，manifest digest `sha256:acc050db798b49b849a12384677af386a026d333b239a9f323704494180058e4`），代码提交 `11ce89195a460b93fc582fa8e7583c486c532cc8`。

## 1. 作业与产物

| 模式 | 作业 | 节点 | 结果 | 产物目录 |
| --- | --- | --- | --- | --- |
| asr | `job-179155077392804775360-xuan-zhang` | d6-hpc-gpu-054 | 完成，failures=0 | `$XTALK_ROUND1_ARTIFACT_ROOT/asr/20261009T130449Z/` |
| services | `job-179155137396193283175-xuan-zhang` | d6-hpc-gpu-069 | 完成，failures=0 | `$XTALK_ROUND1_ARTIFACT_ROOT/services/20261009T131558Z/` |

环境记录在 `$XTALK_ROUND1_ARTIFACT_ROOT/env/`（base + 四个 `xtalk-round1-*` 的 pip freeze / conda explicit）。计算节点为 4×RTX 4090 24 GB，驱动 `580.105.08`（CUDA 13.0）。

## 2. 独立 ASR（三档解码窗口）

`request.wav`（16 kHz 单声道，4.4 s）按 80 ms 原速输入，`--gpu-index 0`：

| 窗口 | status | 模型加载 | 首 partial | 修订数 | 纯解码 RTF | 最终转写 |
| --- | --- | --- | --- | --- | --- | --- |
| 0.6 s | COMPLETE | 50.8 s | 4.13 s | 4 | 0.885 | Please tell me a very long and detailed story about a dragon. |
| 1.2 s | COMPLETE | 37.6 s | 4.68 s | 2 | 0.858 | 同上 |
| 2.0 s | COMPLETE | 36.9 s | 5.35 s | 1 | 0.796 | 同上 |

纯解码 RTF 均小于 1，具备实时解码余量。首 partial 接近音频末尾，说明当前官方流式接口在给定 `unfixed_chunk_num/unfixed_token_num` 下偏“后端集中输出”，不满足低首字延迟；窗口越大修订越少。该行为属模型侧限制，需在 ASR 适配阶段用累计前缀/修订语义处理。

## 3. 三服务与上游测试

`services` 作业各步全部 PASS：`env_imports`、`llm_service_up`、`turn_detector_service_up`、`tts_service_up`、`endpoint_checks`、`xturnix_adapter_probe`、`pytest_moss_tts_realtime`、`pytest_full`、`tts-cold`、`tts-warm`、`tts-gap2`。

- 服务：LLM `xtalk-round1-llm`（Qwen3-8B-AWQ，vLLM 0.16.0）、turn detector 服务名 `xturnix`、MOSS TTS 输出 48 kHz。
- XTurnix 适配器实测：listening → `START_GENERATION`，speaking → `STOP_SPEAKING`，均在合法集合内。
- 上游测试：`tests/test_moss_tts_realtime.py` 10 passed；完整 `pytest` 87 passed / 3 skipped。
- LLM 流式 `chat/completions` 正常返回增量 chunk。

## 4. MOSS TTS 冷启动/热态/双流

| 运行 | status | 首音频 | flush | flush 前有音频 | 采样率 | 音频时长 | wall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tts-cold | COMPLETE | 68.2 s | 2.0 s | 否 | 48 kHz | 12.24 s | 267 s |
| tts-warm | COMPLETE | 0.169 s | 2.0 s | 是 | 48 kHz | 11.44 s | 10.8 s |
| tts-gap2 | COMPLETE | 0.166 s | 4.0 s | 是 | 48 kHz | 9.76 s | 11.4 s |

冷启动首次编译约 1 分钟量级，不能当稳态延迟；热态首包约 0.17 s，且三次都在 flush 前已有音频输出，满足增量合成要求。

## 5. 峰值显存（4090 采样，`gpu_samples.csv`）

| GPU | 角色 | 峰值占用 |
| --- | --- | --- |
| 0 | LLM | 22048 / 24564 MiB (90%) |
| 1 | turn detector | 9472 / 24564 MiB (39%) |
| 2 | 未使用（ASR 独立作业） | 0 |
| 3 | MOSS TTS + codec | 12596 / 24564 MiB (51%) |

LLM 单卡接近 90%，是本组合最紧的一环；四卡分服务方案在 24 GB 卡上可运行。

## 6. 待确认与缺口

- **测试音频语言**：`request.wav` 取自 `assets/p1_2_scenarios/barge_in_stop/01_question.wav`，实际为英文问句（转写为英文）。任务单要求中文测试音，需补一份中文 16 kHz 音频再复测 ASR；参考音色同理需替换为中文音色。
- **首字延迟**：ASR 首 partial 接近句尾，需在 A0 适配阶段确认 `chunk_size_sec`、`unfixed_chunk_num/token_num` 与输入步长的组合。
- **镜像体积**：v0.1 约 57.5 GB（base 31.7 GB + 三个独立 torch/vLLM 环境）。若需精简，可考虑合并环境或去除客户端重型依赖，但不影响本轮验收。
- 音质、日期/时间读法、人名与停播仍需人工试听；`COMPLETE` 仅表示独立请求执行完成。

## 7. 下一步

补齐 Qwen ASR 的会话隔离、累计前缀/修订、临时 final 与 reset/clone 适配，生成可运行的 X-Talk 全链路配置，再进行音频闭环、用户附和、有效插话与 FDB smoke；完成冻结门禁后才开始无 System Backchannel 的控制层改造。
