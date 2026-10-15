# MOSS-TTS-Realtime 吞吐 A/B

- tag: `20261014T151046Z`
- run dir: `/mnt/cloudstorfs/sjtu_home/xuan.zhang/InterClarify/data/runs/tts_throughput_20261014T151046Z`
- 固定文本、`--stream-chunk-words 6 --gap-seconds 0.02`、同一张卡的同一份权重；每个 arm 重启服务（各自独立端口），先跑 `cold` 再跑 `warm`。
- 每个 arm 只改一个变量：`t1-*` 只改本地码本循环的执行后端（采样保持 upstream），`t2-*` 只改采样头（编译保持 off）。
- `steady rtf = audio_s / (wall_s - first_audio_s)`：剔除一次性的会话启动与 prefill；`服务端 rtf` = `Σaudio_s/Σwall_s`（对所有 `[tts-metric]` 行求和，中位数另列），`local/backbone 占比` = 该 arm 的 CUDA event 累计秒数 ÷ 墙钟。

| arm | 编译 | 生效 | cold 首包 s | warm 首包 s | warm 音频 s | warm 墙钟 s | steady rtf | 服务端 rtf | 服务端中位 | local 占比 | backbone 占比 | 相对 baseline | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 否 | 否 | 1.70 | 0.35 | 27.36 | 26.29 | 1.05 | 1.06 | 1.06 | 69% | 13% | 1.0x | 上游路径 |
| t1-sdpa | 否 | 否 | 1.55 | 0.32 | 31.20 | 27.85 | 1.13 | 1.16 | 1.18 | 65% | 13% | 1.1x | 上游路径 |
| t1-sdpa-cudagraph | 是 | 是 | - | 55.21 | 30.24 | 123.94 | 0.44 | 0.25 | 2.19 | 48% | 6% | 0.4x | compiled |
| t1-sdpa-inductor | 是 | 是 | 45.34 | 0.34 | 34.08 | 17.95 | 1.93 | 0.53 | 2.24 | 48% | 6% | 1.8x | compiled |
| t1-sdpa-profile | 是 | 是 | - | 9.59 | 24.88 | 78.57 | 0.36 | 0.33 | 1.76 | 18% | 9% | 0.3x | compiled |

## 说明

- baseline 稳定态 rtf = **1.05**（>1 才追得上实时；本轮 A4 实测交付率约 0.2–0.5）。
- profile 臂（t1-sdpa-profile）的逐 kernel 表在 `metrics/<arm>.profile.txt`，用来判断时间花在 codec 解码、backbone 前向还是本地码本循环上。
- 判据：`t1-*` 只有在 `编译=是` 且 `生效=是` 且 `warm` rtf 明显高于 baseline 时才算成立；
- 采样档位（`t2-greedy`/`t2-topk`）会改变音频内容，质量需试听 `warm/tts.wav`，本报告只给吞吐。
