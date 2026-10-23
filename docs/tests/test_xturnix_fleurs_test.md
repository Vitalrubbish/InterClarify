# XTurnix FLEURS 数据、回放与评分测试

`tests/test_xturnix_fleurs_test.py` 用合成 WAV/TSV、模拟服务和合成 trace 验证数据入口、回放合同与离线评分，不下载真实 FLEURS、不加载模型，也不替代远端 101 条冻结验收或真实时序结果。

## 数据冻结

- 选择规则严格按 `SHA256(filename)` 升序，数量不足时失败。
- 只读复用模式生成 manifest、历史基线和复核记录。
- 篡改音频后 `verify_manifest` 失败；未带 `--overwrite` 的重复冻结被拒绝。
- 历史基线常数与来源提交、文档一致。

## 回放合同

- 默认配置仍是 80ms 传输、63 个静音尾窗包（5.04 秒）和 5 秒主窗口；启用 pause 的配置被拒绝。
- 控制调度器同时只有一个在途请求；后到前缀替换尚未开始的旧前缀。截止后返回的旧请求标为 `post_cutoff`，排队项记 `control_dropped`。
- 模拟 ASR 与控制器跑完整条回放，核对 80ms 包顺序、5 秒尾窗、在线截止、EOF 与排空阶段的事件顺序。
- 控制输入始终来自当时已观察到的 ASR 文本，参考答案不会进入在线请求；所有原始 start 保留在 trace。
- 首个样本的 ASR 传输失败仍写入 `status.json`；清理后第二个样本使用新会话，不继承第一条的迟到结果。
- 控制线程无法停止时，当前样本标记 fatal，后续计划样本记为 `skipped`，不会在未知会话状态下继续。
- 词形 token 比较区分词内补全/新词与仅标点变化。

## 离线评分

- 锚点取最后在线词汇增量或词内补全；仅标点变化、`post_cutoff` 与 EOF 文本不移动锚点。
- 命中延迟可手算：锚点 2.000 秒、start 2.120 秒得到 120ms；链路估计单列为 `413.582852 + 120 = 533.582852ms`，与实测增量分开。
- 提前 start 保留负的相对时间；旧前缀、窗外、截止后和完整窗口内的无 start 分别归类，主延迟均为 null。同时间戳按事件序号判定先后，序号早于锚点的 start 单列且不计命中。
- 窗口未采满时，已出现的有效 start 仍记为命中，同时标记 `window_complete=false`；没有 start 则记 `incomplete_window`，不补 5 秒。
- 空转写按删除计入 WER；合成分母测试覆盖命中、空转写、回写、失败四类样本，确认全部计划分母、CSV 行数、null 延迟和语料 WER 一致。

以上模拟只证明数据、回放与评分合同，不产生真实模型质量或延迟成绩。

运行：

```bash
conda run -n parathink-dev python -m unittest tests.test_xturnix_fleurs_test -v
```
