# X2Q-010：实时 complete 回放与统计

状态：待实施。依赖：X2Q-008。[协议](../dev/X2-Turn/complete_test_on_fleurs.md)。

实现固定数据清单、WebSocket 实时回放、原始 trace、基本转写 WER 与平均末端文本延迟、complete 结束后输出率和首次延迟；提供脚本/测试的 docs 同路径说明。WER 沿用历史 EnglishTextNormalizer，语料级汇总 S/D/I，并保留空转写和失败覆盖。文本末端以最后一次在线词汇变化计时，EOF 补齐单列。以可人工核算 trace 和模拟协议验证时窗边界、提前/EOF 后输出、重复状态、空结果和运行失败。只简化控制测试，不加入 Judger 或控制器。
