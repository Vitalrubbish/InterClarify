# X2Q-013：complete 输出比例与首次延迟

状态：已完成并归档（2026-10-22）。依赖：[X2Q-011](x2q_011_streaming_replay.md) 的 trace 合同。依据：[测试计划](../../dev/X2-Turn/complete_test_on_fleurs.md)。

## 目标与工作内容

控制 token 只测输入结束后的 complete 比例和首次延迟，不实现逐位置 Judger 或五类准确率。

- 仅识别原生 `turn.delta` 的 `turn_end` / ID38；标签和 ID 不一致记协议异常，不匹配转写字符串或控制器 accept。
- `[t_end, t_end+5s]` 内任意一帧 complete 即命中，不要求新转换或连续多帧；重复输出不增加样本成功数。
- 主输出率为命中数 / 全部计划正式样本数，另报成功完成回放条件下的比例和运行失败数。
- 命中延迟取窗内首次接收时间减 `t_end`，汇总条件均值、P50/P95、最大值及命中数。未命中为 null，不填 0 或 5000 ms。
- 提前 complete、只在 EOF 后出现、全程未出现分别留账；提前出现不自动算窗内成功，EOF 后不补算命中。
- 未完整观察满 5 秒即失败的样本明确标识，保留已有观测，不凭部分窗口宣称完整未命中或测试成功。

## 交付

在 `scripts/remote/x2_turn_complete_test.py` 增加独立 complete 评分入口，更新镜像说明的时窗和统计方法。补充既有测试及说明，覆盖时窗左右边界、仅提前/EOF 后出现、重复帧、无命中、异常 ID 和中途失败。

## 验收

- [x] 手算 trace 与实现一致，只用实际接收时间评分。
- [x] 未命中/失败不产生零延迟，输出率与条件延迟同时报告。
- [x] 原生状态与控制器合成事件分开，不依赖语义金标或 LLM Judger。
- [x] 指标不宣称状态准确率或系统实际接话成功率。


## 完成记录

已在 `scripts/remote/x2_turn_complete_test.py` 交付对应入口；实现说明见 [脚本说明](../../scripts/remote/x2_turn_complete_test.md)，测试说明见 [镜像测试文档](../../tests/test_x2_turn_complete_test.md)。本地 `interclarify-dev` conda 使用固定 `whisper-normalizer==0.1.12`，15 项 unittest 通过；连同既有部署测试共 22 项 pytest 通过。模拟 WebSocket 完整验证真实 80 ms 分块、5 秒静音与窗后 EOF，并覆盖故障及手算指标。

本单仅完成回放和离线评分逻辑，不产生模型实测分数。X2Q-009 冻结输入未改写，X2Q-010 权重与部署已完成；远端单卡预热、冒烟及正式 100 条测试由 X2Q-014 执行。
