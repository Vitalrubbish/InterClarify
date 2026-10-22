# X2Q-010：部署冻结版本 X2-Turn 流式服务

状态：待实施。依赖：[X2Q-008](archive/x2q_008_complete_protocol.md)；真实音频预热依赖 [X2Q-009](x2q_009_fleurs_data.md) 的 dev 输入。依据：[测试计划](../dev/X2-Turn/complete_test_on_fleurs.md)。

## 目标与工作内容

在远端隔离 conda 部署原始 ASR/状态双头服务，为两类指标提供真实输出。

- 固定 X2-Turn `67ec3fe49f1977ee3129f7eaed603c04d8ed23c5` 和作者 vLLM 0.19.1 overlay 基线 `b1388b1fbf5aaef47937fabe98931211684666a6`。
- 下载 `x-square-robot/X2-Turn-4B-0812`，锁定实际 HF revision、tokenizer、导出配置与权重哈希，不额外下载无关变体。
- 确认状态头已加载、服务端有效 delay=480 ms；客户端报告字段不能替代有效配置检查。
- 提供原始文本 delta、状态 delta 和完成事件，核对 `turn_end` / ID38 对应 complete，其余类别/概率也保留。
- 绕开演示能量门、idle 文本抑制和 `FrameTurnController`，不启动回答 LLM/TTS。
- 在调度 GPU 上用独立 dev 完成加载/预热与协议诊断，失败留账、预热不计分。

## 交付

拟由 `scripts/remote/run_x2_turn_complete_job.sh` 管理服务生命周期，镜像说明为 `docs/scripts/remote/run_x2_turn_complete_job.md`，解释入口、阶段、参数和清理方法。远端保存模型/环境/源码锁、有效配置、日志与预热证据。

## 验收

- [ ] 独立 conda 可复现，未覆盖现役 ASR/TTS/评分环境。
- [ ] 真实服务输出 ASR 和原生状态，验证 complete 映射与有效 delay。
- [ ] 推理仅通过 vc，最多 1×24 GiB GPU、8 CPU、32 GiB RAM、单作业 4 小时；安装/下载最多 4 CPU、16 GiB RAM、并发 2。
- [ ] 保存资源峰值并遵守整轮磁盘预算，失败不自动加卡或无限重试。

服务启动或预热成功不等于正式测试完成。
