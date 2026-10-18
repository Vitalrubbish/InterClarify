# Nemotron / Kokoro 接入验收

2026-10-18，冻结源码v6。ASR作业 `job-179233016243237430568-xuan-zhang`、TTS作业 `job-179233016334530866399-xuan-zhang`，均为远端单张4090、8CPU、32GB，退出码均0。包版本见environment，实际源码见source.sha256；权重摘要引用 `reports/layer1_training/issue001-inventory-20261018/inventory_summary.json`。远端根目录 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-english-integration-20261018-v6/`，原始日志和WAV保留其data/runs/r4-asr、r4-tts。

| 项目 | Nemotron EN160 | Kokoro af_heart |
| --- | --- | --- |
| 精度/输出 | FP32；16kHz PCM16输入 | 48kHz mono PCM16输出 |
| 加载耗时，含导入/设备准备 | 70.02秒 | 87.25秒 |
| readiness | 两次真实语音输出并清理 | 短/较长文本真实合成 |
| GPU采样峰值 | 2906MiB | 1322MiB |
| 进程峰值RSS | 2514592KiB | 1660388KiB |

ASR六场景通过：正常、三秒停顿恢复、同流两轮、串行会话、短尾EOF及取消重连。五次完整识别的末次独立轮询与EOF文本一致，无前缀回写或代际污染；首文本1.00–1.38秒，最大音频投送迟到4.54ms。构造停顿例将chances识别为answers，保留原始识别差异，不把接口通过当作任务正确率通过。逐例时间线和collection_manifest明确真实回放/构造输入，禁止进入训练。

这些场景来自同一条FLEURS dev录音及构造变体，不是五条独立录音。`final_word_delivery.json`按最终识别文本统计各词首次可见时刻与音频EOF前覆盖，不能当作人工逐词对齐的识别延迟或泛化质量。

两轮连续输入中36/50个最终识别词在音频EOF前可见，剩余14词经排空后交付；正常输入为24/25，其余三个完整场景为25/25。这说明持续输入的尾部交付仍需在更长会话中评估，不能从本轮无丢词外推长会话实时延迟达标。

TTS以固定脚本文本每50ms追加5字符，分段参数12/160字符、250ms。三类请求结果如下，统计只有三例，不代表总体分布：

| 场景 | 首PCM | 首可听代理 | 模拟供音断流 |
| --- | --- | --- | --- |
| 短确认 | 0.692秒 | 1.032秒 | 0 |
| 日期时间澄清 | 0.400秒 | 0.700秒 | 0 |
| 长回答 | 0.579秒 | 0.899秒 | 0 |

首可听代理使用-45dBFS、连续30ms非静音并模拟按包到达播放；包含聚合等待，未包含ASR、真实LLM等待或声卡。短确认超过亚秒目标，如实保留。取消重连通过；真实Kokoro经原有RuntimeAdapter、TTSManager、协调器和播放管理器，短附和不误停、有效插话后不再交付旧PCM、新响应隔离通过。该项控制输入为脚本，不证明官方B0已具备正确的ASR语义判断。底层旧GPU合成可能继续，网络取消耗时不是GPU释放时间。

初始失败均保留：ASR首轮IEEE float WAV容器读取失败、第二轮浮点转int16舍入静音；TTS首轮CUDA voice pack接口不兼容。后续发现的碎词计时已修复，最新真实增量自动验收通过。旧结果的摘要见补充失败清单，原日志留远端。

自动接入验收通过；人工日期读法和跨段韵律由003c试听确认。`listening/`保存本地可试听WAV，音频按仓库规则不入Git；可从上述远端verification目录恢复。这里没有执行适配训练、FDB或完整ASR→真实LLM→TTS验收，001仍未放行。compact_summary是从原始summary提取的摘要；artifact_sha256保留原件摘要，逐例JSON保留关键轨迹，避免重复提交大日志。

逐例JSON仅压缩序列化空白，解码后的字段与原件逐项相同；原始字节摘要与本地紧凑文件摘要分别见artifact_sha256、compact_sha256，不能混用。原始/proc文本留远端，峰值RSS已提取至compact_summary。
