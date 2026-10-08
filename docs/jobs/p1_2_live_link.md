# 任务单：P1.2 实时双工链路

## 目标

对应 [engineering_implementation.md](../engineering_implementation.md) 第 5.2 节 P1.2：分离 ASR、控制模型和 TTS 服务；以脚本化音频验证系统发声时仍接收用户音频；验证静音、backchannel、常规回答、用户打断停播和继续倾听；连续运行一组脚本化场景并观察崩溃、队列堆积和音频设备抢占。

## 前置条件

- P1.1 资产就绪（见 [p1_official_assets.md](p1_official_assets.md)）：DuplexCascade 快照权重 SHA-256 校验通过、基础模型 `Qwen/Qwen2-7B-Instruct` 就位；
- 镜像 `…/interclarify-p0:v0.2` 含 `interclarify-dev` 环境（websockets 12.0、msgpack、sounddevice 等已在 `requirements.txt` 固定）；
- **Kyutai STT/TTS 已部署到共享存储**（2026-10-08 完成，见 [../3rd-party/KyutaiServices.md](../3rd-party/KyutaiServices.md)）：`moshi-server 0.6.4`（为 sm_89 构建）+ `stt-1b-en_fr-candle` / `tts-1.6b-en_fr` / `tts-voices` 快照（均带 SHA-256 清单）+ 本地路径化配置 + Python 3.12.8 venv（moshi 0.2.8、torch 2.6.0）。作业容器内由 [start_kyutai_services.sh](../../scripts/remote/start_kyutai_services.sh) 自动拉起并等待就绪，无需手工部署；端口就绪探测失败会以退出码 3 快速失败并保留服务日志（`interclarify-kyutai/logs/`）。
- 场景语音音频：作业第一步用 TTS 合成到仓库 `assets/p1_2_scenarios/`（已在调试节点验证 TTS 合成链路，7 段语音 RMS 0.036–0.113）。

## 资源与队列

| 项 | 值 |
| --- | --- |
| 队列 | `pdgpu-4090` |
| GPU / CPU / 内存 | 2 / 16 / 64G（GPU 0 跑官方控制模型 bf16，GPU 1 跑 Kyutai STT/TTS；队列单 GPU 上限 8 核、32G） |
| 任务数 | 1 |
| 端口 | 31606（LLM，runner 拉起）、31607（STT）、31608（TTS），均为节点本地 |

## 执行

```bash
# 0) 同步代码（服务器）：见 scripts/remote/sync_from_github.sh
# 1) 提交作业（登录节点或调试节点均可，vc 可用）
bash scripts/remote/submit_p1_2_job.sh
vc list -j <JOBID>
vc logs -t <TASKID>
```

容器内执行 [run_p1_2_node_job.sh](../../scripts/remote/run_p1_2_node_job.sh)：启动共享存储上的 Kyutai STT/TTS（GPU 1）→ `prepare_p1_2_scenarios.py` 合成 6 个场景的语音音频 → `run_p1_2_live_link.py` 校验权重、拉起官方 LLM 服务（GPU 0，bf16、本地快照）、连续执行全部场景（同连接 `Reset` 间插、虚拟播放 sink、已播音频落盘），产物写入 `$ARTIFACT_ROOT/p1_2_live/<run-id>/`。

场景清单（`configs/p1_2_scenarios.json`）：`silence_warmup`（纯静音不误答）、`regular_answer`（常规回答）、`pause_then_continue`（停顿 `<|no voice|>` 后继续倾听）、`barge_in_stop`（播放 3s 后插话，停播并回答新问题）、`backchannel_long_speech`（长语音期间的倾听/backchannel）、`continuous_two_questions`（连续快速两问）。

## 验收

1. 运行目录含 `manifest.json`、`resolved_config.yaml`、`environment.txt`、`events.jsonl`、`metrics.json`、`artifacts/`（官方服务日志 + 每场景 `played_*.f32le` 已播音频）；
2. 双工证据：`barge_in_stop` 场景中 `frames_sent_while_speaking > 0`，且存在 `user_barge_in`（含打断时刻播放头位置）与 `audio_control stop` 后的 `playback_stopped`（`cancelled_samples > 0`）；插话后再次 `answer_phase`（继续倾听/恢复）；
3. `metrics.json` 的 `checks` 全部 `pass`（`backchannel` 为信息项：出现与否都记录观测值）；`silence_warmup` 无 ASR、无 TTS；
4. 稳定性：6 场景连续运行无崩溃；`send_underruns==0`（无音频发送抢占），`playback_max_backlog_samples` 有记录，无 `session_timeout`（或仅有并能解释）；
5. 权重为固定快照（`weight_verified` 事件，`--no-verify-weight` 未使用），服务代码为固定提交、零修改；
6. 本地 CPU 测试 `tests/test_p1_2_realtime.py` 全绿（提交前已在开发机验证 31/31）。

## 执行结果（2026-10-08）

| 项 | 值 |
| --- | --- |
| 作业 | `job-179146072814769675121-xuan-zhang`（Completed；首次提交 `job-179146027480894011099` 暴露容器缺 libssl 1.1，补共享存储兼容库后重提） |
| 节点 | `d6-hpc-gpu-053`（2×RTX 4090，GPU 0 控制模型 / GPU 1 Kyutai STT+TTS） |
| 提交 | `416eaf0`（工作树干净） |
| 运行目录 | `interclarify-p0-artifacts/p1_2_live/ic-20261008T120009-9dac0cd2/`（含 `artifacts/played_*.f32le` 已播音频 + 官方服务日志） |
| 仓库内证据 | [`experiments/p1_2_live/ic-20261008T120009-9dac0cd2/`](../../experiments/p1_2_live/ic-20261008T120009-9dac0cd2/)（见 [说明](../../experiments/p1_2_live/README.md)） |

**结论：`status=PASS`，6/6 场景期望全部通过，`send_underruns=0`，墙钟 240.8s。**

`metrics.json` 摘要（采样率 24 kHz，已播/取消时长按样本数折算）：

```text
silence_warmup          no_asr=pass                                   （纯静音零 ASR 零 TTS）
regular_answer          answer=pass user_asr=pass  发声期收帧= 56  已播 8.80s
pause_then_continue     answer=pass user_asr=pass  发声期收帧=108  已播24.88s 取消8.48s 服务端插话=1
barge_in_stop           answer=pass user_asr=pass  barge_in_stop=pass  发声期收帧=73
                        已播35.78s 取消1.22s 客户端插话=1 服务端插话=1 backchannel=1
backchannel_long_speech answer=pass user_asr=pass  发声期收帧=128 已播10.12s 取消76.66s 服务端插话=14
continuous_two_questions answer=pass user_asr=pass  发声期收帧= 52  已播 4.64s
duplex: 5/6 场景在系统发声期间持续收用户音频（共 417 帧）；打断停播成功 1/1
```

关键事件链（`events.jsonl`）：`weight_verified`（固定快照校验）→ `playback_started` → `user_barge_in`（含打断时刻播放头位置）→ 服务端 `<|user interruption|>` + `audio_control stop` → `playback_stopped`（`cancelled_samples` 只含未播尾部）→ 新 `answer_phase`。验收清单第 1–6 项满足。

行为观察（官方控制模型的真实表现，非缺陷）：停顿场景中模型在 3.5s 停顿内先作答、被继续说话的用户打断后再次作答；长语音场景中模型多次尝试接话均被用户打断（`server_barge_in=14`），符合 DuplexCascade micro-turn 话轮决策。

## 已知取舍（执行后更新）

- 首次作业失败暴露容器 libssl 1.1 缺失：已将调试节点的 `libssl/libcrypto.so.1.1` 复制到 `interclarify-kyutai/lib/` 并由启动脚本注入 `LD_LIBRARY_PATH`；
- 调试节点（RTX 2080 Ti，sm_75）无法运行 candle STT（bf16 kernel 按 `__CUDA_ARCH__ >= 800` 门控），故二进制按 sm_89 构建、STT 与全链路在 4090 队列验证；TTS（torch）在调试节点完成合成链路验证；
- 场景语音在作业内经 TTS 重新合成（两次合成摘要不同为采样随机性，`live_link_start` 事件记录当次 SHA-256，可追溯）；
- 其余同部署前记录：headless 用虚拟播放 sink + 已播音频落盘代替扬声器；STT 为英/法语料；事件字典扩展归 P1.3。
