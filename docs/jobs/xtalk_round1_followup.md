# 任务单：接通 X-Talk 框架与首轮模型

## 1. 当前目标

2026-10-10 根据用户反馈，下一步聚焦框架连接：让 Qwen ASR、回答 LLM、MOSS TTS 与 X-Talk 在同一会话中正常工作。删除上一版的中文样本采集、质量评测、重复测量与延迟预算要求，长会话和 FDB 也留到框架接通后的阶段。

组件保持 Qwen3-ASR 1.7B、Qwen3-8B-AWQ（关闭 thinking）、MOSS-TTS-Realtime + codec、XTurnix-ZH Base。System Backchannel 关闭，Layer 0 移除，Layer 2/3 尚不启用；沿用 X-Talk 的事件、轮次控制和唯一播放链路。

首轮模型服务已有运行记录，见 [xtalk_round1_baseline_results.md](xtalk_round1_baseline_results.md)。当前仍缺 Qwen ASR 的框架适配，不能把独立模型 smoke 当成框架已经接通。

## 2. 下一步四项工作

| 编号 | 工作 | 完成标准 |
| --- | --- | --- |
| T1 | 修复现有测试与启动配置 | 项目回归通过，当前镜像能够加载配置要求的依赖 |
| T2 | 接入 Qwen ASR | X-Talk 能接收音频并得到累计转写，重置与会话隔离正常 |
| T3 | 接通真实 ASR→LLM→TTS | 一段请求在同一会话中完成识别、回答与播放，LLM 增量直接进入 TTS |
| T4 | 做最小连接检查并记录结果 | 连续两轮可运行，播放期间仍接收输入，插话停止后可以继续 |

顺序为 T1 → T2 → T3 → T4。本次只安排工作，下面未勾选的项目均尚未完成。

## 3. T1：修复测试与启动配置

- 修复 `tests/test_xtalk_round1.py` 中缺少 `stream_chunk_words` 的测试参数，使现有项目回归通过。
- 将提交入口的默认镜像与当前 `flash_attention_2` 配置统一：当前脚本默认 v0.2，配置依赖 v0.3 中的 flash-attn。启动时检查实际依赖与镜像版本。
- 检查模型锁定路径和配置是否匹配，保留本次使用的提交、模型 revision、镜像 digest 与必要日志。已有原始产物可以直接复用，无须为了连接框架重新跑完整首轮测试。

这部分在 InterClarify 修改脚本与配置；代码修改同步更新对应实现文档。

## 4. T2：在 X-Talk fork 接入 Qwen ASR

先写接口设计，再实现适配。现有 `Qwen3ASRClient` 与当前 ASR 抽象不匹配，需要补齐：

- 接收 16 kHz 单声道 PCM16，返回当前累计文本并保留前缀修订。
- 实现 `clone` / `reset`，会话缓存独立，重置后能处理新的请求。
- 区分临时 flush 与输入结束，临时 flush 后仍能继续接收音频。
- 模型推理不阻塞音频接收；取消、超时及退出能释放本会话资源。

Qwen 推理环境与 X-Talk 客户端环境继续隔离，采用明确的模型服务协议与异步客户端。复用 DefaultService / DefaultAgent 和已有轮次逻辑。交付接口测试、对应文档及一份可实例化的 X-Talk 运行配置；当前准备 YAML 仍只用于模型准备。

## 5. T3：接通真实流式链路

使用现有测试音频即可，不新增采集任务：

1. 音频进入同一个 X-Talk 会话，ASR 转写交给原有 Agent。
2. LLM 请求显式关闭 thinking，增量输出到达后直接送入现有 StreamingTextTTS 链路。
3. 客户端接收并播放音频，记录识别、生成、TTS 与播放是否完成。

不能先收集完整 LLM 回复再按固定速度分块回放；现有 6 词分块测试仅作为独立 TTS 检查保留。只保存必要事件和时间戳，不要求 p50/p95、性能预算或正式音质评分。独立首包时间不能作为端到端响应时间。

## 6. T4：最小连接检查

- [ ] 一段普通请求完成 ASR、LLM、TTS 和播放。
- [ ] LLM 增量直接驱动 TTS，能够在文本结束前收到音频。
- [ ] 连续两轮请求正常，旧转写和旧音频不串入新响应。
- [ ] 系统播放期间仍能接收用户输入。
- [ ] 一次有效插话能停止剩余生成与播放，随后继续同一会话；已播内容仍保留。
- [ ] 系统附和保持关闭，没有新增播放通道。

产物只需运行配置、实际 fork 提交、环境/模型来源和一次联调的必要日志。连接失败时记录最小复现，先修接口和状态，不扩展评测体系。

## 7. 执行与交接

本地执行接口、配置和确定性测试；GPU 模型推理及集群测试在远端进行，两端使用 conda。X-Talk 适配代码留在独立 fork，InterClarify 维护任务单与运行来源记录，不复制第二套运行时。

本任务完成仅表示框架连接通过。中文质量评测、延迟预算、长会话、FDB 和正式基线冻结留到后续阶段，不作为当前接通工作的前置条件。接通后再按 [../xtalk_modification_plan.md](../xtalk_modification_plan.md) 推进无 System Backchannel 的控制层改造。

## 8. T1 完成记录（2026-10-10）

- 测试修复：`tests/test_xtalk_round1.py` 的 `tts_smoke` 用例补上缺失的 `stream_chunk_words=0`，并新增 `test_stream_chunk_words_splits_text_incrementally` 覆盖按词分片。`interclarify-dev` 环境下 `unittest discover tests` 15/15 通过（`test_p0_artifacts.py` 需要 numpy，`xtalk-round1-tools` 环境无 numpy，属环境差异）。
- 镜像统一：`submit_xtalk_round1_job.sh` 默认镜像由 `v0.2` 改为 `v0.3`（v0.3 才带 MOSS 环境所需的 flash-attn）。
- 依赖检查：`run_xtalk_round1.py` 新增 `check-deps --role {asr,llm,tts}`，按 `dependency_candidates` 校验 torch / transformers / vLLM（TTS 角色含 `moss_flash_attn`）的版本与可导入性；node job 在所有模式前置 `dependency_check` 步骤，失败即中止。`xtalk_round1.yaml` 增补 `moss_flash_attn: "2.8.3"`。
- 模型锁一致：`$XTALK_ROUND1_ROOT/models/models.lock.json` 的 `model_id` 与配置一致；ASR `7278e1e7`、LLM `4da05a8e`、TTS `75682787`、codec `3cd226ba`、turn detector `b69ac8a4`。复用已有首轮产物，未为接通重跑完整首轮。

本次对接使用的来源记录：

| 项 | 值 |
| --- | --- |
| InterClarify 提交 | 本 T1 提交（见 `git log`；基线 `cb47d24`） |
| X-Talk fork | `Vitalrubbish/xtalk`（远端 main），起点 `5f0d9959edf1026588246efbed827b078cbb114c` |
| 首轮镜像 | `sjtu_yukai-xuanzhang-xtalk-round1:v0.3`，digest `sha256:a8eb99d8cafadc7f906ae6b24378f6686ce0c52ab8ac063b9c4f59de8ed47d23` |
| 模型 revision | ASR `7278e1e7` / LLM `4da05a8e` / TTS `75682787` / codec `3cd226ba` / XTurnix `b69ac8a4` |

T1 完成。T2–T4 见第 4–6 节。

## 9. T2 进展记录（2026-10-10）

接口设计见 [qwen3_asr_adapter_design.md](qwen3_asr_adapter_design.md)。基座为 X-Talk fork `5f0d995`（含 `ASR` 抽象 `models/asr/interfaces.py`、`StreamingTextTTS`、`DefaultService/DefaultAgent`）。

- 适配器：在 fork 分支 `feature/qwen3-asr-adapter`（worktree `InterClarify/xtalk/`，origin `Vitalrubbish/xtalk`）重写 `src/xtalk/models/asr/qwen3asr_client.py`：接收 `bytes`、`recognize_stream(*, is_final, chat_history)` 返回**累计文本**、实现 `reset`/`clone`/`stream_chunk_bytes_hint`，会话按 `session_id` 隔离。离线契约测试 `tests/test_qwen3_asr_client.py` 5/5 通过。**fork 改动尚未提交**（遵循 fork 的 `AGENTS.md`：仅在明确要求时提交）。
- 服务：新增 `scripts/remote/qwen3_asr_service.py`（FastAPI 包装官方 `Qwen3ASRModel.LLM` 流式 API，按会话保留状态）；`run_xtalk_round1.py serve asr` 与配置 `services.asr` 的 host/port 已接入。
- 运行配置：`configs/xtalk_round1_runtime.json` 可被 `Xtalk.from_config` 实例化（已核对得到 `Qwen3ASRClient` / `DefaultAgent` / `MossTTSRealtime`），`DefaultAgent` 显式关闭 thinking，System Backchannel 关闭。

T2 代码与文档完成，尚缺 T3（真实流式链路）与 T4（集群最小连接检查）。
