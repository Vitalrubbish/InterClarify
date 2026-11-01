# X2 单帧实时探针

对应实现：`scripts/remote/x2_streaming_probe.py`。用于NTF-011独立可行性门槛，不加载SoulX。采用官方冻结源码`0aca80597bb1399c0be4002de5bc62c0a779c542`的自适应协议，避免用基础Voxtral的固定延迟`generate()`误测X2。

## 类与方法

`X2Engine`只加载一份bf16模型，显式恢复检查点中的英语language-tag，并按官方自适应路径关闭固定AdaRMS延迟条件。`reset()`创建独立的音频注意力、卷积padding及文本KV缓存，用2600样本合成零音经过官方封装得到`[1,128,272]`；前32个音频帧进入LM左填充预热，额外2个合成帧不计入真实流。`encode()`要求后续特征为`[1,128,8]`，逐次校验卷积缓存与模块的通道／左填充长度一致。缓存延续，不重编码既有真实音频。

`step()`每次编码1680样本窗口、前进1280样本，执行一次LISTEN。等待token为32；33触发连续DECODE，直到EOS=2才结束。`decode_emit()`限制最多64个文本token；越界直接失败，不伪造EOS。一个80ms音频帧可产生多个文本token。

`ClosedGroups.append()`只接受EOS闭合组，用官方`join_emit_texts`拼接显示文字；每次重新解码所有历史token前缀并核对旧文本，列出回改证据。该审计验证token／解码前缀不变，不宣称模型逐词语义绝对正确。

`run_stream()`在每个实际观察截止时刻喂入一帧，记录覆盖边界、观察边界、token产生时刻、组闭合、缓存及累计正文。首帧窗口包含200个左侧零样本和1480个真实样本；因此正常帧STFT观察领先80ms覆盖边界200样本（12.5ms）。EOF只补足最后窗口，补零量单列，不追加诊断排空帧。

## 指标与执行

- `x2_rtf`为逐帧特征提取、编码、LISTEN与全部DECODE、文本审计耗时之和／真实音频时长，不计实时等待与合成预热；包含EOF窗口计算。
- `frame_lag_ms`从本帧真实覆盖边界算起；`backlog_ms`从实际真实观察截止算起。连续60s漂移为最后帧积压减第一帧积压，绝对值不超过160ms才通过。
- `group_close_delay_ms`为同帧最后文本token至EOS的墙钟差。回改次数和未闭合组单列；失败保留traceback及最后形状。
- `peak_gpu_mib`为CUDA设备总使用量采样峰值（独占调度卡，含CUDA上下文），并另报PyTorch allocated／reserved峰值。shell同时每秒保存`nvidia-smi`设备采样。

`main()`先校验模型和官方依赖文件摘要，再执行3.36s合成音合同自检；失败立即停止。之后测冻结FDB30中的最长用例、停顿16和接话102，最后按原清单顺序拼接恰好60s音频。逐条校验全部冻结文件摘要，增益沿用`min(0.05/rms,0.9/peak)`。四条必须全部完成，RTF≤0.6、积压P95≤320ms、漂移≤160ms、显存≤12288MiB，才通过NTF-011。

结果包含`result.json`、逐帧`*.frames.jsonl`及逐token的`*.tokens.jsonl`。异常或门槛失败退出1，不启动NTF-012。
