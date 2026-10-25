# XTX-003：真实时钟回放与事件采集

2026-10-23。状态：客户端实现与本地契约测试完成；尚未在远端运行真实模型回放。本报告只证明回放器合同，不产生 start 延迟、WER、模型质量或真实时序成绩。

## 结论

- `scripts/remote/xturnix_fleurs_test.py` 新增 `replay` 入口，按 XTX-002 冻结配置逐条串行回放：80ms 音频包、80ms/5.04 秒静音尾窗、5 秒主窗口、EOF 排空，以及 Listen 条件下不执行 start 的影子决策。
- ASR 前缀由独立轮询线程读取，控制调度器最多一个在途请求、只保留最新未开始前缀；排队、替换、截止丢弃和截止后返回均写入 trace。
- 每条录音使用独立 ASR 会话与空的控制器历史。失败样本保留在 `status.json`；会话清理失败或控制线程无法停止时停止后续样本并记 `skipped`，避免污染。
- 参考答案不进入在线控制输入；控制请求只使用当时已观察到的 ASR 文本，trace 保留输入版本、请求 ID、发送/返回单调时钟、动作与分数。
- 本地单元测试验证了包顺序、尾窗、EOF 阶段、单请求上限、最新前缀策略、失败分母、会话隔离和迟到结果隔离。测试中的模拟服务不是 Nemotron 或 XTurnix 实测。

## 交付文件

| 文件 | SHA256 |
| --- | --- |
| `scripts/remote/xturnix_fleurs_test.py` | `bc439ae31fc0eedd6beeed733795582b2149f0c05b663f0b15ddf02e992e89d7` |
| `tests/test_xturnix_fleurs_test.py` | `dca5a63bd6d9ecc99748fddf5d7c279c3e648af028dcf975c83a996ddce72e08` |
| `docs/scripts/remote/xturnix_fleurs_test.md` | `4ad6dca852a6de9236e60b4992b1f947a105ea0446ec943adc8b444fbcce7408` |
| `docs/tests/test_xturnix_fleurs_test.md` | `d9fdc032f9bae311d266caac0db0af6ba4a2413201b9b615332dfa8d2ee68047` |
| `configs/xturnix_fleurs_test.json` | `ae121007859ab3d7c6d07d38688082bffb0a6803cda3490b0c8b34f6b111fb43`（未改动） |

配置仍为 XTX-002 冻结版本；回放器不接受 80ms 传输、160ms 模型分块、单在途/单排队、5 秒尾窗或 5 秒主窗口的任何放宽，也拒绝启用 pause 注入。

## 验收映射

| 验收项 | 证据 |
| --- | --- |
| 模拟服务核查真实到达顺序、单请求上限、5 秒尾窗与 EOF 阶段，不产生无限队列 | `test_replay_trace_phases_and_no_reference_injection`、`test_one_in_flight_latest_prefix_and_post_cutoff_result`、`test_default_contract_uses_five_second_tail` |
| 原始前缀与控制请求关联可追溯，未注入完整转写、最后 token 或参考答案 | trace 的 `asr_observation` / `control_request` / `control_completed`；测试断言控制输入是已观察文本子集且不含参考文本 |
| 所有原始 start 均记录，失败样本不消失 | 调度器不抑制 start；`test_failed_sample_is_recorded_and_next_session_is_isolated`、`test_stuck_control_aborts_instead_of_reusing_the_session` |
| 会话串行隔离，超时/取消后的迟到结果不进入下一条 | 逐例新建会话、截止标记、迟到结果 `under_cutoff=false`；失败样本测试验证第二条使用新会话 |
| 实现与同路径文档同步，模拟结果不属于真实模型成绩 | 本报告、脚本说明与测试说明均明确边界 |

## 本地验证

环境：`conda run -n interclarify-dev`。

```text
python -m unittest tests.test_xturnix_fleurs_test -v
Ran 10 tests ... OK

python -m unittest discover -s tests -v
Ran 72 tests ... OK
```

回放测试使用合成 WAV、模拟 ASR 与模拟控制器，只运行约 1.4 秒，不加载模型、不访问网络。默认配置另行断言为 63 个 80ms 尾窗包、5 秒主窗口。

## 输出合同

```text
runs/<run_id>/replay/
├── config.json
├── input_snapshot.json
├── traces/{test,dev}/*.jsonl
├── status.json
└── replay_report.json
```

`status.json` 覆盖全部计划样本的 `completed` / `failed` / `skipped` 及原因。`input_snapshot.json` 不含参考文本；XTX-004 从冻结 manifest 离线读取参考并评分。

## 边界与后续

- 本报告没有真实模型证据。真实回放、远端作业入口、资源峰值和 5 条冒烟属于 XTX-005；100 条正式回放与报告属于 XTX-006。
- 回放器不计算 `t_asr_last`、`t_start_after_last`、窗口命中、WER 或链路估计；这些由 XTX-004 从 trace 离线完成。
- 暂停注入仍关闭：没有因果 VAD 或上游分段事件，不使用 EOF、文件时长、参考文本或事后对齐补点。
- 不训练、不调阈值、不接入 Layer 1/TTS/播放器，也不改变唯一播放所有权。

## 原始产物保存

本页为Git保留的结果汇总；逐例JSON／CSV、trace、样本正文及资源采样不再入库。本地归档位于`artifacts/report_archive/reports/xturnix_fleurs/20261023-xtx-003-replay/`，具体文件与SHA256见本地`artifacts/report_archive/archive_index.json`；已有远端run路径保持原样。复现时读取归档，不从报告链接下载原始产物。Git历史未重写。
