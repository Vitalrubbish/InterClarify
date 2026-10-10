# 首轮验收结果：Qwen ASR + MOSS TTS 模型服务

> 2026-10-10 审查补充：下文保留各轮历史记录，尚不作为冻结结论。0.72 秒是人为分块输入下的独立 TTS 首包，1.2 秒 ASR 指标为输入音频进度；真实墙钟和在线链路仍待核验。报告第 4 节正文“三次均在 flush 前出音频”与 cold 项不符，以表格为准。原始远端产物尚未在本次审查取得；下一步见 [xtalk_round1_followup.md](xtalk_round1_followup.md)。

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

`chain` 模式（`submit_xtalk_round1_job.sh chain`）在 4 卡节点上启动三服务，再顺序走 ASR（逻辑卡 2）→ LLM（关闭思考）→ TTS，各阶段前后都做预热，日志复制到 `data/runs/<tag>/`（已 gitignore）。这是顺序分阶段测量，不是并发全双工。有效完成记录 tag `20261010T025525Z`：

| 阶段 | 指标 | 值 |
| --- | --- | --- |
| ASR（预热后） | 音频相对首 partial | 1.20 s |
| ASR | 纯解码 RTF | 0.120 |
| LLM（`enable_thinking=false`） | 首 token | **0.083 s** |
| LLM | 总耗时（256 token 上限） | 12.7 s |
| TTS（默认编译路径） | 首音频 | 136 s |

**延迟读数**：LLM 首 token 稳定在**亚秒级**（0.083 s），且关闭思考后内容是干净的故事正文（不再有 ` thinking`）。ASR 首 partial 约 **1.2 s**、解码 RTF 0.12。**TTS 是唯一瓶颈**：MOSS 在 `attn_impl=sdpa` 时对 `torch.compile` 走 StaticCache 路径，并按 prefill 长度逐个重编译，导致“每个新长度首请求”都要编译数分钟。实测三种模式都不理想：

| `torch_compile` | 首音频 | 说明 |
| --- | --- | --- |
| `default`（静态编译） | 136 s（新长度） / 0.17 s（重复长度） | 长度一变就重编译，运行时不可用 |
| `disable`（eager） | ~1.9 s | 无重编译，但生成远慢于实时（RTF>1） |
| `dynamic`（`assume_static_by_default=False`） | 98 s | 一次编译适配任意长度，但编译与生成都极慢（272 s 出 2.24 s 音频） |

因此**“全链路亚秒”目前不成立**，卡点是 MOSS TTS 的编译策略，而不是 ASR/LLM。按输入形状预热（同形状跑两遍）在运行时不可行（用户输入与回复长度不可预知），已被否决。MOSS 源码本身提供了免编译路径：当 `attn_impl=flash_attention_2` 时用 `DynamicCache`、跳过编译（`streaming_mossttsrealtime.py:86-105`）；该路径需要 `flash-attn`，当前环境未安装。建议下一步：安装匹配 torch 2.9.1+cu128 / py3.12 的 flash-attn 并切到 `attn_impl=flash_attention_2` 复测；或对 MOSS 服务做固定/预编译改动。**后续决定**：源码编译 flash-attn 曾在共享调试机 OOM，因此 `xtalk-round1:v0.3` 采用官方 `v2.8.3` release 的预编译 `flash_attn-2.8.3+cu12torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl`（无编译），MOSS 环境保持上游 torch 2.9.1+cu128 钉版；验证通过后再把 `configs/xtalk_round1.yaml` 的 `attn_impl` 切到 `flash_attention_2` 复测。

**内容读数**：关闭思考后 LLM 输出正常的英文故事（无 `思考`）；ASR 转写正确。但测试音与参考音色仍是英文资产，需换中文后复测。

## 10. v0.3 复测：flash-attn（`attn_impl=flash_attention_2`）

镜像 `xtalk-round1:v0.3`（MOSS 环境保持 torch 2.9.1+cu128，安装官方预编译 `flash_attn-2.8.3+cu12torch2.9` wheel，无编译；见 [../scripts/remote/Dockerfile.round1.md](../scripts/remote/Dockerfile.round1.md)）。作业 `job-179162725903634772669-xuan-zhang`，节点 `d6-hpc-gpu-054`，tag `20261010T102317Z`，`failures=0`，配置 `tts.attn_impl=flash_attention_2`。

| 阶段 | v0.2（sdpa + compile） | v0.3（flash_attention_2） |
| --- | --- | --- |
| ASR 首 partial | 1.2 s | 1.2 s |
| LLM 首 token | 0.083 s | 0.081 s |
| TTS 首音频（长回复整段喂入） | 81.76 s | **17.06 s** |
| TTS warmup（短文本）首音频 | — | 1.22 s |

- `service_logs/tts.log` 出现 “You are attempting to use Flash Attention 2 ...”，确认 flash-attn 生效；**不再按 prefill/生成长度重编译**。
- 长文本 17.06 s 来自链式测量把整段回复一次性喂入（大 prefill）；短文本热路径仅 1.22 s，说明该路径本身很快。`audio_before_flush=false` 是因为测量客户端 push 后 2.9 ms 就 flush，不代表流式能力。
- 结论：TTS 的 `torch.compile` 瓶颈（v0.2 的 81.76 s / 首轮 136 s）已被 flash-attn 的 DynamicCache 路径消除，首音频不再随长度爆炸。

### 10.1 分块流式复测（更接近真实对话）

同一作业追加 `chain-tts-stream` 步骤：把同一段 LLM 回复按 **6 词/片、片间 0.12 s** 分块推送（模拟 token 流式），tag `20261010T104729Z`，`failures=0`。

| TTS 输入方式 | 首音频 | `audio_before_flush` | 分片数 |
| --- | --- | --- | --- |
| 整段一次性喂入 | 16.94 s | false | 1 |
| 分块流式（6 词/片） | **0.72 s** | **true** | 35 |

在真实流式输入下 TTS 首音频为 **0.72 s（亚秒）**，且在 flush（4.11 s）之前已开始出音频，满足增量合成要求。整段喂入的 16.94 s 只是“先做完大 prefill 再出音频”的测量假象。至此全链路（流式口径）为：ASR 首 partial 1.2 s、LLM 首 token 0.081 s、TTS 首音频 0.72 s。
