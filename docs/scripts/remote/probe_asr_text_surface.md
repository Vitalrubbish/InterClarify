# Nemotron 文本表面形式探针

`scripts/remote/probe_asr_text_surface.py` 在远端单 GPU 上加载当前 EN160 模型一次，按清单顺序读取少量16kHz单声道 PCM16 WAV，并复用 `NativeNemotron` 的原生解码路径。主函数逐条记录音频 SHA256、输出文本及增量、推理秒数、模型目录与处理器设置；探针不修改模型、ASR 服务、训练数据或人审记录。

输入音频须在任务单中记录合成脚本文本或真实来源，输出只用于检查大小写、缩写和数字/时间/日期的转写表面形式。`AudioBuffer` 限每条音频最多30秒；执行命令另限制单 GPU、CPU/内存和总墙钟。若识别错误，应同时保留输入脚本与原始输出，不把预期文字伪装成 ASR 结果。当前小任务按用户要求在调试节点0号2080 Ti受限执行，已撤销重复排队的调度作业；详见[020任务单](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/020_asr_text_surface_alignment.md)。

实测在0号2080 Ti以32GiB虚拟地址空间上限完成六条探针，GPU采样峰值2648MiB，退出0；16GiB地址空间版本加载失败。原始输出与资源证据见[核验报告](../../../reports/asr_text_surface/20261019/README.md)。
