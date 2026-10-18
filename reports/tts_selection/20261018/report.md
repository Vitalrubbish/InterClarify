# 英文 TTS 远端流式测试报告

每模型 60 条相同文本；另有首次请求及 3 条预热，均不计入正式分位数。时间单位为毫秒，RTF 为生成墙钟/音频时长（越小越好）。

首可听代理：10ms RMS、连续 30ms 超过 -45dBFS，映射到保留到达等待的模拟播放时钟。不是声卡实测或首个可理解单词；自然度待用户试听。传输完成只表示结束协议正常且返回非空音频，不证明文本读全或音质合格。

| 系统 | 传输完成/尝试 | 首包 p50/p95 | 首可听代理 p50/p95 | RTF p50 | 累计断流秒 |
| --- | --- | --- | --- | --- | --- |
| kokoro | 60/60 | 122/138 | 439/461 | 0.026 | 0.000 |
| kyutai | 60/60 | 737/759 | 812/1128 | 0.426 | 0.000 |
| moss | 60/60 | 561/62880 | 1809/63405 | 1.611 | 172.320 |
| pocket | 60/60 | 156/226 | 352/535 | 0.452 | 0.594 |

CPU 与 GPU、帧级音频流与分段合成须结合调研及环境清单解释，不能把该表当作同算力模型排名。每类只有 20 条，尾部分位数不构成服务 SLA。

moss：60 条测量完整，但包装作业退出 127；详见执行说明，不将该作业记为通过。

## kokoro

远端证据目录：`/mnt/cloudstorfs/sjtu_home/xuan.zhang/interclarify-tts-selection-20261018/runs/kokoro`。

| 类别 | 首包 p50/p95 | 首可听代理 p50/p95 |
| --- | --- | --- |
| clarification | 116/118 | 416/438 |
| confirmation | 122/124 | 444/455 |
| answer | 136/140 | 446/466 |

首块时长 p50/p95：4450/11261ms；采样率 24000Hz。

| 阈值 | 首非静音代理 p50/p95 | 有效样本 |
| --- | --- | --- |
| -50dBFS | 438/457 | 60/60 |
| -45dBFS | 439/461 | 60/60 |
| -40dBFS | 444/466 | 60/60 |

首次请求与预热（秒）：

- cold clarification_01：首包 2.220，首非静音代理 2.520。
- warmup clarification_01：首包 0.064，首非静音代理 0.364。
- warmup clarification_02：首包 0.121，首非静音代理 0.421。
- warmup clarification_03：首包 0.120，首非静音代理 0.430。

## kyutai

远端证据目录：`/mnt/cloudstorfs/sjtu_home/xuan.zhang/interclarify-tts-selection-20261018/runs/kyutai-r2`。

| 类别 | 首包 p50/p95 | 首可听代理 p50/p95 |
| --- | --- | --- |
| clarification | 736/755 | 806/1084 |
| confirmation | 737/749 | 801/1128 |
| answer | 737/805 | 832/1044 |

首块时长 p50/p95：80/80ms；采样率 24000Hz。

| 阈值 | 首非静音代理 p50/p95 | 有效样本 |
| --- | --- | --- |
| -50dBFS | 757/878 | 60/60 |
| -45dBFS | 812/1128 | 60/60 |
| -40dBFS | 885/1368 | 60/60 |

首次请求与预热（秒）：

- cold clarification_01：首包 15.683，首非静音代理 15.793。
- warmup clarification_01：首包 0.754，首非静音代理 0.874。
- warmup clarification_02：首包 0.779，首非静音代理 0.799。
- warmup clarification_03：首包 0.755，首非静音代理 0.755。

## moss

远端证据目录：`/mnt/cloudstorfs/sjtu_home/xuan.zhang/interclarify-tts-selection-20261018/runs/moss-r1`。

| 类别 | 首包 p50/p95 | 首可听代理 p50/p95 |
| --- | --- | --- |
| clarification | 251/63065 | 1164/64955 |
| confirmation | 436/4160 | 1185/7170 |
| answer | 2998/3262 | 3358/3838 |

首块时长 p50/p95：80/80ms；采样率 48000Hz。

| 阈值 | 首非静音代理 p50/p95 | 有效样本 |
| --- | --- | --- |
| -50dBFS | 1406/63246 | 59/60 |
| -45dBFS | 1809/63405 | 59/60 |
| -40dBFS | 3130/63829 | 59/60 |

首次请求与预热（秒）：

- cold clarification_01：首包 70.720，首非静音代理 72.267。
- warmup clarification_01：首包 0.247，首非静音代理 1.081。
- warmup clarification_02：首包 61.105，首非静音代理 61.442。
- warmup clarification_03：首包 63.712，首非静音代理 65.025。

## pocket

远端证据目录：`/mnt/cloudstorfs/sjtu_home/xuan.zhang/interclarify-tts-selection-20261018/runs/pocket-cpu-r1`。

| 类别 | 首包 p50/p95 | 首可听代理 p50/p95 |
| --- | --- | --- |
| clarification | 157/267 | 316/535 |
| confirmation | 129/231 | 359/556 |
| answer | 166/226 | 366/486 |

首块时长 p50/p95：80/80ms；采样率 24000Hz。

| 阈值 | 首非静音代理 p50/p95 | 有效样本 |
| --- | --- | --- |
| -50dBFS | 352/535 | 60/60 |
| -45dBFS | 352/535 | 60/60 |
| -40dBFS | 361/536 | 60/60 |

首次请求与预热（秒）：

- cold clarification_01：首包 0.184，首非静音代理 0.364。
- warmup clarification_01：首包 0.126，首非静音代理 0.466。
- warmup clarification_02：首包 0.156，首非静音代理 0.216。
- warmup clarification_03：首包 0.163，首非静音代理 0.263。
