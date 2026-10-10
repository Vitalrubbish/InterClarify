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
- **镜像体积**：v0.1 约 57.5 GB（base 31.7 GB + 三个独立 torch/vLLM 环境）。已通过压平并精简基座（`xtalk-lean:v0.1`，31.7 → 21.8 GB，431 层 → 1 层）与后续在 lean 基座上重建 round-one（v0.2）来降低体积；详见第 8 节。
- 音质、日期/时间读法、人名与停播仍需人工试听；`COMPLETE` 仅表示独立请求执行完成。

## 7. 下一步

补齐 Qwen ASR 的会话隔离、累计前缀/修订、临时 final 与 reset/clone 适配，生成可运行的 X-Talk 全链路配置，再进行音频闭环、用户附和、有效插话与 FDB smoke；完成冻结门禁后才开始无 System Backchannel 的控制层改造。

## 8. 基座瘦身与镜像体积

`xtalk:v0.17` 是 431 层迭代链，后续层覆盖了早先安装的文件（最典型是 2.59 GB 的 `vllm==0.10.2` 层被 `vllm==0.16.0` 覆盖），这些死字节仍随镜像分发；同时它带着本组合不用的栈（onnxruntime/funasr/modelscope/sherpa、pynini/pyopenjtalk、gradio/wandb/kubernetes/verl、node）。

| 镜像 | 大小 | 层数 | 说明 |
| --- | --- | --- | --- |
| `xtalk:v0.17` | 31.7 GB | 431 | 原始基座 |
| `xtalk-lean:v0.1` | 21.8 GB | 1 | 压平 + 剔除无用栈（保留 vLLM 硬依赖 ray/numba/opencv/pyarrow/triton） |
| `xtalk-round1:v0.1` | 57.5 GB | — | 基于 v0.17 的首轮镜像 |
| `xtalk-round1:v0.2` | 见构建产物 | — | 基于 lean 基座重建 |

压平与剔除流程见 [build_xtalk_lean_base.sh](../scripts/remote/build_xtalk_lean_base.md)；剔除在 build 阶段执行（集群 `docker run` 以映射用户启动，无法删除 root 拥有的文件）。进一步可考虑按作业拆分镜像或把 ASR 适配到 vLLM 0.16 以消掉 vLLM 0.14.0 独立环境。

## 9. 全链路测试（ASR → LLM → TTS）

`chain` 模式（`submit_xtalk_round1_job.sh chain`）在 4 卡节点上启动三服务，再用同一输入 `request.wav` 顺序走 ASR（逻辑卡 2）→ LLM → TTS，日志同时复制到仓库根目录 `data/runs/<tag>/`（已 gitignore）。这是顺序分阶段测量，不是并发全双工。首轮完成记录 tag `20261009T171546Z`：

| 阶段 | 指标 | 值 |
| --- | --- | --- |
| ASR（预热后） | 音频相对首 partial | 1.20 s |
| ASR | 纯解码 RTF | 0.121 |
| ASR | 最终转写 | "Please tell me a very long and detailed story about a dragon." |
| LLM | 首 token | **0.108 s** |
| LLM | 总耗时（256 token 上限） | 13.4 s |
| TTS（首次请求） | 首音频 | 266 s（冷启动） |
| TTS | 输出时长 / 采样率 | 66.2 s / 48 kHz |

**延迟读数**：LLM 首 token 与 TTS 热态首音频（服务作业中 0.17 s）都在**亚秒级**；ASR 首 partial 约 **1.2 s**（非亚秒）。但整条链路wall 时间被 **TTS 首个请求的编译冷启动**支配：MOSS 首请求需数分钟编译，且不稳定——services 作业冷启动 68 s，chain 首轮 266 s，二次 chain 重跑在 TTS 预热阶段卡死超过 28 分钟（GPU 空转、无新日志），只能终止作业。因此“全链路亚秒”**尚未证明**：必须先把 TTS 服务预热到热态，再测链路，否则测到的是编译时间。

**内容读数**：ASR 正确转写英文输入；LLM（Qwen3-8B-AWQ）默认输出原始 ` thinking` 推理链、且在 256 token 处被截断，没有给出面向用户的最终回答；TTS 把这段推理链（含 markdown）合成为 66 s 音频。也就是说**链路能跑通、内容非空**，但当前 LLM 输出不适合直接播报，需要去 ` thinking`、限制或提升 max_tokens，并替换中文测试音/中文参考音色。

**待办**：给 chain 固定“先预热 TTS 到热态再计时”的流程并处理 MOSS 首请求编译卡死（例如固定输入形状、提高超时、或预编译缓存），然后再复测亚秒级端到端。
