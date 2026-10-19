# 官方权重完整链路接话复核

`scripts/remote/full_chain_smoke.py` 无产品新类。`run_sample` 用真实ASRManager接收80ms音频帧，Assembler按产品600ms会话时钟读取当时ASR结果，官方权重生成的真实控制与正文经原有TTSManager/协调器/播放器输出真实Kokoro PCM。

`play`按队列顺序以PCM时长模拟headless播放并确认，记录首非静音代理与输出WAV；收到停播清空该响应尚未播放队列，保留已经交付的音频事实。`observe`记录原始事件与响应/请求ID，不伪造生成文本。`run`读取冻结历史manifest、核对音频SHA256，逐例隔离会话，保存完整时间线、assistant token IDs、2/5/12秒新回答及音频覆盖；协议/ASR/TTS错误单列，缺测保留。

原音频后发送12秒记账的静音维持在线ASR并排出尾词，不发送ASRFinal/人工让轮；标注边界不进入在线逻辑。仅作当前配置迁移诊断，不复现官方Kyutai输入，不当作独立评测或完整FDB。真实模型在远端conda两卡作业执行，LLM/ASR/TTS使用独立服务和明确设备。
