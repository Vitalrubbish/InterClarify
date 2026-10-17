# TTS 可懂度诊断计量测试

`test_tts_intelligibility_check.py` 在 CPU 验证大小写/标点归一化、替换/删除/插入计数、空转写与空参考边界，以及按总词数加权的 WER。它不加载识别模型；真实 WAV 转写在已有远端 ASR conda 环境单独运行。
