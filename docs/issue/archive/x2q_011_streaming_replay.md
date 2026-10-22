# X2Q-011：实现真实时钟回放与原始记录

状态：已完成并归档（2026-10-22）。依赖：[X2Q-009](x2q_009_fleurs_data.md)、[X2Q-010](x2q_010_x2_turn_deployment.md) 的数据和协议合同；本地可先用模拟服务验证。依据：[测试计划](../../dev/X2-Turn/complete_test_on_fleurs.md)。

## 目标与工作内容

让 ASR 与控制指标共用同一轮真实流式输入及原始记录。

- 每条录音独立会话、batch=1，80 ms 分块按源时钟到达，发送/接收独立运行，不整段快速上传。
- 用客户端 monotonic 时钟记录最后一个原始块发送完成的 `t_end`，同时保存计划文件末端、发送迟到及事件到达时刻。
- 输入后按相同节奏送 5 秒静音，窗结束后才发 EOF；最终排空超时 60 秒，独立记账。
- 保存原始文本/状态 delta、ID/概率、累计文本、窗末在线文本、最终文本、EOF/done 时间、错误和退出码。
- 保留文件尾静音，不向模型提供隐藏语音末端或参考文本，不增加状态确认或控制器。
- 每个计划样本均有成功或失败记录，不覆盖已有 run_id，不把冒烟计为新增正式样本。

## 交付

在 `scripts/remote/x2_turn_complete_test.py` 提供回放入口和 trace，更新对应说明的回放类、事件处理和核心方法。新增 `tests/test_x2_turn_complete_test.py` 与 `docs/tests/test_x2_turn_complete_test.md`，用模拟服务验证接收时戳、发送节奏、尾窗和 EOF 顺序。

## 验收

- [x] 输入时钟、`t_end`、观察窗、EOF/done 可追溯，接收不被发送循环阻塞。
- [x] 状态为原生输出，文本未被状态门控删除。
- [x] 断连、超时、空输出和 EOF 后补字/补状态可以区分。
- [x] 本地 conda 检查逻辑，真实模型检查在远端受限作业执行；trace 足够支持后续两个评分单独立重算。


## 完成记录

已在 `scripts/remote/x2_turn_complete_test.py` 交付对应入口；实现说明见 [脚本说明](../../scripts/remote/x2_turn_complete_test.md)，测试说明见 [镜像测试文档](../../tests/test_x2_turn_complete_test.md)。本地 `interclarify-dev` conda 使用固定 `whisper-normalizer==0.1.12`，15 项 unittest 通过；连同既有部署测试共 22 项 pytest 通过。模拟 WebSocket 完整验证真实 80 ms 分块、5 秒静音与窗后 EOF，并覆盖故障及手算指标。

本单仅完成回放和离线评分逻辑，不产生模型实测分数。X2Q-009 冻结输入未改写，X2Q-010 权重与部署已完成；远端单卡预热、冒烟及正式 100 条测试由 X2Q-014 执行。
