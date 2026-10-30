# Nemotron 同步解码进程

复用现有 `NativeNemotron` 加载与两会话预热，在独立 ASR conda 中运行。`SynchronizedNemotron.run()` 保留原生 RNNT 缓存和重叠特征窗口；特征生成器在本步完全消费且 streamer 交付后发布完成事件，然后等待客户端确认，才读取和编码下一块。

`synchronized_sample()` 对摘要固定的 Transformers `_sample` 做内存 AST 调整：将模型 generation kwargs 更新移到 streamer 交付之后、停止条件之前。原因是原始 kwargs 更新会在 streamer 最后一个 token 到达前预取下一块，直接在原生成器内等待会死锁。Transformers 从模型类获取解码函数，因此在单流 generation 的 try/finally 中临时替换类方法，结束后恢复，不能仅绑定实例方法。仅单流、贪心、单卡运行，磁盘依赖与权重不变；节点结构不符立即失败。

`BarrierSession.complete_step()` 发布真实窗口与完成时刻并等待 `release`；取消会唤醒等待，重复或越序释放被拒绝。Unix socket 提供 create／push／poll／release／close；音频接收独立持续进行，最多保留800ms待处理数据。EOF 后解除屏障排空，结果仅作诊断，不写在线 Context。
