# Nemotron＋SoulX音频组合检查

对应`scripts/remote/nemotron_soulx_probe.py`。`rpc()`访问私有Unix socket；`run_case()`用接收线程把同一80ms PCM16包依次交给Nemotron和SoulX队列，用独立轮询线程即时发布ASR结果，主线程串行运行SoulX。800ms队列积压报错，不丢包赶进度。

两个`FrontendConsumer`在每次提交后独立读取并比较。逐块核对控制消费的观察上界不超过实际音频、正文前缀不回写、关闭保留最后在线版本；报告原始在线／排空文字、状态计数、消费版本、pending帧及token重放次数，保留完整事件。

`main()`复用已审核SoulX加载器和权重键检查，但将SenseVoice类临时替换成拒绝调用的空壳，不加载第二套ASR；模型加载后恢复模块类。SoulX分配两个CPU线程、显存比例0.35，与ASR进程共享调度卡。输入为已有FLEURS标定完整／截断、已有英文示例及静音，保存来源摘要、采样率和增益。不接入LLM、CoT或播放，不以出现complete声称语义正确。

启动前校验复用加载器SHA256，报告显式记录Nemotron与SoulX revision；不因共享目录当前main变化自动升级模型。
