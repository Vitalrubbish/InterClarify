# XTX-003：实现真实时钟回放与两组件事件采集

状态：待实施。依赖：[XTX-001](README.md)、[XTX-002](../archive/XTurnix/xtx_002_component_deployment.md)。依据：[质量测试计划第 3、4、6 节](../../dev/XTurnix/quality_test_on_fleurs.md)。

## 目标

让固定音频按真实时钟流经 Nemotron 和 XTurnix，获得可独立评分的因果 trace，不在回放时预知最后 token 或最佳接话时机。

## 工作内容

- 每条录音独立会话，以 80ms 音频包实时发送，并独立读取 ASR 增量；不等完整录音、不等句末标点、不额外等待表达 micro-turn。
- 按冻结策略将当时可见的累计前缀送入 XTurnix。最多一个在途控制请求，记录排队、合并和丢弃；真实停顿按 XTX-002 合同触发。
- 持续以 Listen 条件采集影子动作，start 不关闭 ASR、不切换 Speak、不播放；记录全部 start/keep，包括最后词汇前的动作。
- 文件发送后继续 5 秒静音，随后真实 EOF 排空；区分原始文件末端、在线采集截止、EOF 与排空阶段，EOF 后结果保留但不混入在线主指标。
- 在同一测量客户端单调时钟下记录 ASR 接收、请求发送和控制返回，保存事件序号、token/delta、词汇变化、输入版本、停顿来源、请求 ID、状态与分数。
- 输出全部计划样本的运行状态与失败原因；取消、超时、服务错误和会话清理不得污染后续录音。

## 交付

在 `scripts/remote/xturnix_fleurs_test.py` 中提供 replay 入口；同步更新 `docs/scripts/remote/xturnix_fleurs_test.md`，说明回放器、输入快照和事件记录的职责与核心方法。少量契约测试写入 `tests/test_xturnix_fleurs_test.py`，对应说明为 `docs/tests/test_xturnix_fleurs_test.md`。

## 验收

- [ ] 模拟服务可核查真实到达顺序、单请求上限、5 秒尾窗和 EOF 阶段，不产生无限队列。
- [ ] 原始前缀与控制请求关联可追溯，没有提前注入完整转写、最后 token 或参考答案。
- [ ] 所有原始 start 均记录，失败样本不从计划清单消失。
- [ ] 会话串行且相互隔离，超时/取消后的迟到结果不会进入下一条记录。
- [ ] 实现与同路径文档同步，模拟结果明确不属于真实模型成绩。

## 资源与边界

本地用 conda 做少量协议验证，真实模型运行交给 XTX-005。trace/结果累计≤2GiB，失败或慢服务不得增加并发。不修改两个模型的权重、解码语义或现役播放链。
