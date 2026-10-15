# `scripts/remote/run_tts_throughput_ab_node_job.sh`

## 功能与边界

在**单张 4090** 上量测 MOSS-TTS-Realtime 的合成吞吐，对比"上游路径"与 `moss_tts_patch.py` 的 T1/T2 各 arm。每个 arm **重启一次 TTS 服务**（用该 arm 的环境变量），对同一段固定文本、以 `--stream-chunk-words 6 --gap-seconds 0.02` 的流式方式合成两遍：`cold`（首个会话，可能包含编译/图捕获）与 `warm`（稳定态）。只调用现成的 `run_xtalk_round1.py serve tts` 与 `tts-smoke`，不加载也不改动模型代码。

**每个 arm 只改一个变量**：`t1-*` 只改本地码本循环的执行后端（采样保持 `upstream`），`t2-*` 只改采样头（编译保持 `off`），否则差值无法归因。默认臂表按 2026-10-14 的实测瓶颈组织：每帧墙钟 ≈82ms、device 只有 ≈24ms、633 次 kernel 里有 ~450 次来自 16 个码本的本地前向 → 因此先用 `t1-sdpa` 隔离"换注意力/静态 cache"这一步，再看 `t1-sdpa-cudagraph`/`t1-sdpa-inductor` 两个编译后端；`t1-sdpa-profile` 是同一配置加 `torch.profiler` 的测量副本，给出 device/cpu 与 top kernel。

**每个 arm 用独立端口**（`TTS_PORT + 序号`，经 `serve tts --port` 覆盖）：上一 arm 的服务退出较慢时，既不会答到新的 `/health`，也不会占住新服务的端口（上一轮就是被这个竞态废掉了两个 arm）。健康判定要求"本进程存活 + 日志出现 `[warmup] Backend loaded` + 自己的端口连续两次应答成功"。

## 输入（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INTERCLARIFY_ROOT` | 必填 | 同步后的源码根（提交脚本传入） |
| `XTALK_ROUND1_ROOT` / `XTALK_ROUND1_MODEL_ROOT` | 必填 | 参考音色/场景目录 与 模型 snapshot 根 |
| `RUN_TAG` | UTC 时间戳 | 产物目录名 |
| `MOSS_ENV` / `CLIENT_ENV` | `xtalk-round1-moss` / `xtalk-round1-client` | 服务与 smoke 的 conda 环境 |
| `TTS_PORT` | `8004` | 起始端口；第 i 个 arm 用 `TTS_PORT + i`，经 `serve tts --port` 覆盖配置 |
| `TTS_AB_ARMS` | `baseline:off:upstream t1-sdpa:off:upstream:sdpa t1-sdpa-cudagraph:cudagraph:upstream:sdpa t1-sdpa-inductor:inductor:upstream:sdpa t1-sdpa-profile:cudagraph:upstream:sdpa,profile,warm-only` | `名字:XTALK_TTS_LOCAL_COMPILE:XTALK_TTS_SAMPLE[:flags]`，flags 逗号分隔：`sdpa` 打开 `XTALK_TTS_LOCAL_ATTN`、`profile` 打开 `XTALK_TTS_PROFILE`、`warm-only` 跳过 `cold`。采样臂（`t2-greedy`/`t2-topk`）实测只值 ~5%，需要时再用 `TTS_AB_ARMS` 显式列出 |
| `TTS_AB_TEXT` | 一段约 75 词的英文回答 | 固定负载；长度决定要合成多少音频 |
| `TTS_AB_CHUNK_WORDS` / `TTS_AB_GAP_SECONDS` | `6` / `0.02` | 模拟 LLM 逐 token 投喂 |
| `TTS_AB_RESUME` | `0` | `1` 时跳过已有 `-warm/tts_report.json` 的 arm（端口序号不变），用于作业在编译阶段被杀后用**同一个 `RUN_TAG`** 续跑 |
| `TTS_AB_INDUCTOR_THREADS` | `1` | 传给服务进程的 `TORCHINDUCTOR_COMPILE_THREADS`；编译在服务进程内进行，限制并行编译 worker 是控制峰值内存的关键（默认按 CPU 数起 worker，曾把整容器打爆） |
| `TTS_AB_ALLOC_CONF` | `expandable_segments:True` | 传给服务进程的 `PYTORCH_CUDA_ALLOC_CONF`，降低图捕获时的显存碎片 |

## 产物

- `data/runs/tts_throughput_<tag>/<arm>-{cold,warm}/{tts.wav,tts_report.json}`：客户端侧读数（`audio_seconds`、`wall_seconds`、`first_audio_seconds`、`flush_seconds`）。
- `data/runs/tts_throughput_<tag>/logs/<arm>.service.log`：服务日志。`[moss-patch] …`（arm 摘要、warmup 用时、回退 traceback、`compiled path engaged`）与 `[tts-metric] …`（限速切片：帧数/音频秒/墙钟/rtf/本地与 backbone 秒数）在**该 arm 全部跑完后**才抽到 `metrics/<arm>.{patch,metric}.log`——编译发生在 smoke 的第一帧，提前抽会漏掉关键行。
- `data/runs/tts_throughput_<tag>/metrics/<arm>.profile.txt`：仅在 `profile` 臂生成，逐回合的 `torch.profiler` kernel 表。
- `reports/tts_throughput/<tag>/tts_throughput.{md,json}`：由 `summarize_tts_throughput.py` 生成的对照表与判据。
- `data/runs/tts_throughput_<tag>/metrics/<arm>.resources.txt`：每个 arm 在 healthy / 每个 phase 前后各记一条 `free -m`、显存占用与最占内存的 python 进程；**即使 pod 被杀，这些快照也已落在共享盘上**，是判断"是否被内存打爆"的唯一证据。
- `data/runs/tts_throughput_<tag>/{run.log,gpu.csv,source_check.txt}`：运行记录、卡型与 source manifest 校验（不一致直接拒绝量测）。

## 失败处理

- arm 起不来（进程死亡/`[warmup] Failed`/超时）→ 记 `ENV-FAILED`，抓服务日志尾部，继续下一个 arm；**只有第一个 arm** 失败才中止整轮（那说明节点本身有问题）。
- smoke 返回非 0 → 记 `smoke-failed` 并打印服务日志尾部；两种失败都会出现在 `run.log` 的 `arms summary` 里。
- arm 结束后无论成败都会 `stop_service` 并等端口不再应答，避免影响下一个 arm。
- 每个 phase 开始前会先删掉同名输出目录：续跑时残留的 `-cold/` 会让 `tts-smoke` 的 `mkdir(exist_ok=False)` 直接失败（已在 2026-10-15 修）。
- **pod 级被杀**（服务与 bash 一起消失、日志戛然而止、`vc list` 里作业直接不见了）：已知触发点是编译/图捕获阶段的峰值内存（inductor 默认按 CPU 数起并行编译 worker）。此时用 `TTS_AB_RESUME=1` + 同一个 `RUN_TAG` 重投，已完成的 arm 会被跳过；并用 `metrics/<arm>.resources.txt` 的最后几条快照确认内存压力。

## 判定

- `steady rtf = audio_s / (wall_s - first_audio_s)`：剔除一次性会话启动/prefill 后的稳定态吞吐；**>1 才追上实时**。
- `t1-*` 成立需要三条同时满足：日志有 `torch.compile(_local_loop) ready`（编译列=是）、有 `compiled path engaged`（生效列=是）、`warm` rtf 明显高于 baseline；出现 `falling back to eager` 或缺失 engaged 都说明该 arm 反映的不是编译后的成绩。
- `t2-*` 的吞吐与采样开销相关，但会改变音频内容，须试听后再决定是否采用。
- `profile` 臂用 kernel 表判断时间构成：codec 解码占大头则本地循环/采样方向作废，backbone 占大头则下一步应打 backbone 前向。

## 用法

```bash
INTERCLARIFY_DUPLEX_ROOT=$PWD XTALK_ROUND1_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1 \
XTALK_ROUND1_MODEL_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/models \
RUN_TAG=20261014T000000Z bash scripts/remote/submit_tts_throughput_ab_job.sh
```

单臂可复用：`TTS_AB_ARMS="t1-cudagraph:cudagraph:greedy" …`。
