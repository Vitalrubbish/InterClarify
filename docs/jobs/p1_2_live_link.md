# 任务单：P1.2 实时双工链路

## 目标

对应 [engineering_implementation.md](../engineering_implementation.md) 第 5.2 节 P1.2：分离 ASR、控制模型和 TTS 服务；以脚本化音频验证系统发声时仍接收用户音频；验证静音、backchannel、常规回答、用户打断停播和继续倾听；连续运行一组脚本化场景并观察崩溃、队列堆积和音频设备抢占。

## 前置条件

- P1.1 资产就绪（见 [p1_official_assets.md](p1_official_assets.md)）：DuplexCascade 快照权重 SHA-256 校验通过、基础模型 `Qwen/Qwen2-7B-Instruct` 就位；
- 镜像 `…/interclarify-p0:v0.2` 含 `interclarify-dev` 环境（websockets 12.0、msgpack、sounddevice 等已在 `requirements.txt` 固定）；
- **Kyutai STT/TTS 服务**：作业节点 `127.0.0.1:31607/31608` 需已运行 `delayed-streams-modeling` 的 Rust `moshi-server`（README 的 config：`config-stt-en_fr-hf.toml`、`config-tts.toml`）。集群镜像未内置 Rust 工具链，部署方式（二选一，按节点记录实际方式与版本）：
  1. 在具备 Rust 的机器按官方仓库（kyutai-labs/delayed-streams-modeling）编译 release 二进制，放入共享存储，作业节点直接运行；
  2. 使用 Kyutai 发布的容器/预编译包在作业节点拉起（需与镜像网络互通）。
  若 STT/TTS 暂不可部署，节点脚本以退出码 3 快速失败——此时按第 5.4 节失败处理策略，先以预录音频 + 虚拟播放时钟完成控制路径验证（本 harness 已支持），设备链路单独补齐。

## 资源与队列

| 项 | 值 |
| --- | --- |
| 队列 | `pdgpu-4090` |
| GPU / CPU / 内存 | 1 / 8 / 32G（队列限制：单 GPU ≤8 核、≤32G） |
| 任务数 | 1 |
| 端口 | 31606（LLM，runner 拉起）、31607（STT）、31608（TTS），均为节点本地 |

## 执行

```bash
# 0) 同步代码（服务器）：见 scripts/remote/sync_from_github.sh
# 1) 在作业节点准备 STT/TTS moshi-server（见前置条件）
# 2) 提交作业（登录节点）
bash scripts/remote/submit_p1_2_job.sh
vc list -j <JOBID>
vc logs -t <TASKID>
```

容器内执行 [run_p1_2_node_job.sh](../../scripts/remote/run_p1_2_node_job.sh)：先探测 STT/TTS → `prepare_p1_2_scenarios.py` 用 TTS 合成 6 个场景的语音音频 → `run_p1_2_live_link.py` 校验权重、拉起官方 LLM 服务（bf16、本地快照）、连续执行全部场景（同连接 `Reset` 间插、虚拟播放 sink、已播音频落盘），产物写入 `$ARTIFACT_ROOT/p1_2_live/<run-id>/`。

场景清单（`configs/p1_2_scenarios.json`）：`silence_warmup`（纯静音不误答）、`regular_answer`（常规回答）、`pause_then_continue`（停顿 `<|no voice|>` 后继续倾听）、`barge_in_stop`（播放 3s 后插话，停播并回答新问题）、`backchannel_long_speech`（长语音期间的倾听/backchannel）、`continuous_two_questions`（连续快速两问）。

## 验收

1. 运行目录含 `manifest.json`、`resolved_config.yaml`、`environment.txt`、`events.jsonl`、`metrics.json`、`artifacts/`（官方服务日志 + 每场景 `played_*.f32le` 已播音频）；
2. 双工证据：`barge_in_stop` 场景中 `frames_sent_while_speaking > 0`，且存在 `user_barge_in`（含打断时刻播放头位置）与 `audio_control stop` 后的 `playback_stopped`（`cancelled_samples > 0`）；插话后再次 `answer_phase`（继续倾听/恢复）；
3. `metrics.json` 的 `checks` 全部 `pass`（`backchannel` 为信息项：出现与否都记录观测值）；`silence_warmup` 无 ASR、无 TTS；
4. 稳定性：6 场景连续运行无崩溃；`send_underruns==0`（无音频发送抢占），`playback_max_backlog_samples` 有记录，无 `session_timeout`（或仅有并能解释）；
5. 权重为固定快照（`weight_verified` 事件，`--no-verify-weight` 未使用），服务代码为固定提交、零修改；
6. 本地 CPU 测试 `tests/test_p1_2_realtime.py` 全绿（提交前已在开发机验证 31/31）。

## 执行结果

待执行。执行后补充：作业号、节点、提交号、运行目录、`metrics.json` 摘要（各场景 checks、双工计数、墙钟时长）、已知取舍。

## 已知取舍

- headless 集群无麦克风/扬声器：麦克风由 24 kHz 预生成 wav 按实时 pacing 注入，扬声器由虚拟播放所有者 + 已播音频落盘代替；本地有设备的开发机可用 `--playback-sink sounddevice` 走真实声卡（对应第 5.4 节的降级路径声明）；
- ASR 语言为英/法（Kyutai STT），场景语音为英文；目标域“日程时间选择”的中文适配若需要替换 ASR/TTS，必须先保存本官方组合的结果（第 5.1 节）；
- 播放队列堆积观测在客户端侧（backlog 峰值 + 发送 pacing 欠 run）；服务端 `audio_q` 满丢旧属官方既有行为，不在 P1.2 修改；
- 统一事件日志（P1.3）会复用本运行目录的 `events.jsonl` 格式并扩展事件字典（`micro_turn_tick`、`layer0/layer1_decision`、修订版本等）。
