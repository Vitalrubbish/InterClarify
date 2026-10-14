# `scripts/remote/run_tts_throughput_ab_node_job.sh`

## 功能与边界

在**单张 4090** 上量测 MOSS-TTS-Realtime 的合成吞吐，对比"上游路径"与 `moss_tts_patch.py` 的 T1/T2 各 arm。每个 arm **重启一次 TTS 服务**（用该 arm 的环境变量），对同一段固定文本、以 `--stream-chunk-words 6 --gap-seconds 0.02` 的流式方式合成两遍：`cold`（首个会话，可能包含编译/图捕获）与 `warm`（稳定态）。只调用现成的 `run_xtalk_round1.py serve tts` 与 `tts-smoke`，不加载也不改动模型代码。

## 输入（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INTERCLARIFY_ROOT` | 必填 | 同步后的源码根（提交脚本传入） |
| `XTALK_ROUND1_ROOT` / `XTALK_ROUND1_MODEL_ROOT` | 必填 | 参考音色/场景目录 与 模型 snapshot 根 |
| `RUN_TAG` | UTC 时间戳 | 产物目录名 |
| `MOSS_ENV` / `CLIENT_ENV` | `xtalk-round1-moss` / `xtalk-round1-client` | 服务与 smoke 的 conda 环境 |
| `TTS_PORT` | `8004` | 与 `configs/xtalk_round1.yaml` 的 `services.tts.port` 一致 |
| `TTS_AB_ARMS` | `baseline:off:upstream t2-greedy:off:greedy t2-topk:off:topk t1-inductor:inductor:greedy t1-cudagraph:cudagraph:greedy` | `名字:XTALK_TTS_LOCAL_COMPILE:XTALK_TTS_SAMPLE` |
| `TTS_AB_TEXT` | 一段约 75 词的英文回答 | 固定负载；长度决定要合成多少音频 |
| `TTS_AB_CHUNK_WORDS` / `TTS_AB_GAP_SECONDS` | `6` / `0.02` | 模拟 LLM 逐 token 投喂 |

## 产物

- `data/runs/tts_throughput_<tag>/<arm>-{cold,warm}/{tts.wav,tts_report.json}`：客户端侧读数（`audio_seconds`、`wall_seconds`、`first_audio_seconds`、`flush_seconds`）。
- `data/runs/tts_throughput_<tag>/logs/<arm>.service.log`：服务日志；其中 `[moss-patch] …`（arm 摘要、warmup 用时、回退告警）与 `[tts-metric] …`（每回合帧数/音频秒/墙钟/rtf）被抽到 `metrics/<arm>.{patch,metric}.log`。
- `reports/tts_throughput/<tag>/tts_throughput.{md,json}`：由 `summarize_tts_throughput.py` 生成的对照表与判据。
- `data/runs/tts_throughput_<tag>/{run.log,gpu.csv,source_check.txt}`：运行记录、卡型与 source manifest 校验（不一致直接拒绝量测）。

## 判定

- `steady rtf = audio_s / (wall_s - first_audio_s)`：剔除一次性会话启动/prefill 后的稳定态吞吐；**>1 才追上实时**。
- `t1-*` 只有在服务日志出现 `torch.compile(_local_loop) ready` 且 `warm` rtf 明显高于 baseline 时才算成立；出现 `falling back to eager` 即该 arm 无效。
- `t2-*` 的吞吐与采样开销相关，但会改变音频内容，须试听后再决定是否采用。

## 用法

```bash
INTERCLARIFY_DUPLEX_ROOT=$PWD XTALK_ROUND1_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1 \
XTALK_ROUND1_MODEL_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/models \
RUN_TAG=20261014T000000Z bash scripts/remote/submit_tts_throughput_ab_job.sh
```

单臂可复用：`TTS_AB_ARMS="t1-cudagraph:cudagraph:greedy" …`。
