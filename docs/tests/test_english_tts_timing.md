# TTS 时序指标回归

`TTSTimingTests` 区分队列断流和音频内部静音：已及时送达的两段PCM仍可有长首尾静音；真正迟到的PCM另计供音缺口。检查合成计算/音频时长比与600ms音频覆盖计数，防止再次用“模拟供音断流为0”代替连贯性验收。

使用本地conda运行 `python -m unittest discover -s tests -p test_english_tts_timing.py`。测试为确定性合成信号，不代表真实Kokoro听感。

时间读法回归在远端模型conda内运行，确认明确at语境的9:30/3:15/09:05/00:00转换、比率/小数/非法分钟不变；原请求文本不改。
