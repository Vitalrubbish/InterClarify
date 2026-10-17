# TTS 生成语音可懂度诊断

`tts_intelligibility_check.py` 在远端单独的 GPU 作业中，使用既有 `nemotron_en` conda 环境和固定本地 ASR 权重，对本次 TTS 筛选保存的 WAV 做离线转写。它不接入运行时、不替换 ASR、不下载或升级依赖；目的是辅助发现门槛降低后的漏读/重复，不能代替人工自然度评价。

固定来源为已有锁文件中的 `nvidia/nemotron-speech-streaming-en-0.6b@ebe59e5a817142986528bbbee5dba8db7b38ed50`，环境已核对 torch 2.11.0+cu128、transformers 5.15.1。使用本地官方 README 的 `pipeline('automatic-speech-recognition', model=...)` 接口；读取 WAV 后转换到单声道 16kHz 浮点数组，避免网络音频/外部解码器依赖。

`edit_counts` 计算归一化英文单词的替换、删除、插入；`run` 逐条保留转写与错误，按 PCM 摘要缓存完全相同音频的识别结果，但每条仍独立计入其期望文本。失败不能填空字符串后伪装为成功。报告分别提供语料总词数加权 WER、整句完全一致数与失败数，不将 ASR 差异直接断言为 TTS 错误。

CLI `--screen` 指向已完成筛选根，`--model`、`--lock` 指向已有模型和锁文件，`--output` 要求新目录。输出建议为筛选根的 `intelligibility/`，报告生成器会读取 summary；检查必须在调度器分配节点的独立作业运行，不占登录节点 GPU。原始 WAV 不改动，模型摘要与依赖版本随输出保存。

`--extra-screen` 可追加独立早期编译复测的 WAV，arm 名加 `_retest`，保留来源区别。最终对比只在相同模式、同卡实验对应的候选/control 之间解释，不将不同模式或复测分配直接混排。
