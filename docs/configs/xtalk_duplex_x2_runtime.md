# X2 Duplex 配置

用途说明（2026-10-18）：本文说明保留的历史/诊断实现。当前目标已确定为 Nemotron EN 160ms + Kokoro；新组合接入和训练按 [issue 任务](../issue/README.md) 推进，本文参数不代表新组合已部署。

仅把 ASR 改为 X2StreamingClient，80 ms 输入；其余模型协议、600 ms micro-turn、VAD 与唯一 MOSS 播放链保留。


X2 duplex 的会话能力 `acoustic_vad_enabled=false` 由服务端按连续 ASR 能力确定。禁用声学 VAD 检测、声学开始/结束信号及 pause/resume 调度；保持会话级连续 PCM 与每拍文本读取。浏览器在握手后创建关闭 VAD 的输入设备，旧客户端声学信号在网关被忽略。Qwen 与内部文本提交边界保持原行为。验证覆盖残留 VAD 信号不触发 ASR 控制、静音和播放期间连续输入、同一解码会话及握手能力。
