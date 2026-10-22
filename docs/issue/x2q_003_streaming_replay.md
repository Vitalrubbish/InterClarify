# X2Q-003：X2-Turn 远端部署与实时回放

状态：待实施。依赖：X2Q-002 输入清单。协议：[质量测试计划第 2、4、10 节](../dev/X2-Turn/qualtity_test_on_fdb.md#4-实时回放与记录)。

## 目标

在远端隔离 conda 部署冻结的 X2-Turn 与作者 vLLM overlay，完成不经演示门控的原始流式输出采集。确认服务端实际 delay=480 ms，验证输出步与 80 ms 网格对应关系。

## 交付

- `scripts/runtime/x2_turn_stream.py`、`scripts/remote/x2_turn_fdb_replay.py`、`scripts/remote/run_x2_turn_fdb_job.sh`，以及各自的 docs 同路径说明。
- `configs/x2_turn_fdb_quality.json` 及镜像说明，包含环境/模型/源码锁、输入节奏、固定尾窗和资源限制。
- 必要时提交只读观测补丁 `patches/x2_turn_realtime_trace.patch` 及对应说明，保持生成行为。
- 远端协议诊断 trace：独立发送/接收、monotonic 到达时刻、输入截止点、文本/状态/EOF 分离。

## 验收

音频块按源时钟到达，不整段快速上传、不在隐藏用户末端发 EOF；每样本独立会话。确认状态头加载、六类输出、空 delta/帧编号/EOF 补齐映射。不能测实时或映射不可靠时明确失败，不用离线两遍推理顶替。正式全量执行属于 X2Q-006。
