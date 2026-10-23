# xturnix_pause_usage_probe.py

## 作用与设计

XTX-014 的原生 pause 机制诊断，按[核查方案](../../dev/XTurnix/pause_usage.md)在真实 PT 模型上比较不插 token、官方 pending 插入和直接末尾插入。它是参考合同回放，不是完整 X-Talk 部署。

`PauseState` 保存当前用户文本、已提交的 pause 偏移、pending 偏移、gate 和一次性 start latch。`update_text` 在真正续说时提交 pending；`pause` 记录停顿而不直接追加 token；`render` 按实验条件生成模型文本；`map_start` 只在原始 start 且 gate 打开时提交一次 start。

`select_cases` 从已冻结 dev 中选择 20 个有句中停顿的原话轮，按原观察顺序派生事件，并添加 3 条独立标识的脚本 sanity。历史、标签和当前前缀分别记录；不会读取 test 或 FLEURS/FDB。

`run_probe` 复用官方 pipeline 和模型锁校验，对相同完整输入缓存原始模型分数。每条事件记录输入摘要、pause 数、pending/gate/latch、原始动作、实际提交与来源时刻，另保存模型实际调用次数、错误和资源。首次文字、pause、恢复、新文字与重复 pause 的关键契约由少量无模型测试核验。

输入、模型和代码均留摘要；原始记录保存在独立远端 run。新入口只用于诊断，旧 pause 探针、Listen 基线、现役框架与模型均不覆盖。

通过已有受限 runner 设置 `XTURNIX_CAL_ENTRYPOINT=xturnix_pause_usage_probe.py`、`XTURNIX_CAL_TIMEOUT_SECONDS=900`，其余输入/模型/独立 run_id 参数沿用原合同。只允许远端 conda 调度 GPU 执行，单卡、单作业，不启动 vLLM 或新的播放服务。

GPU 队列持续 Pending 时可设置 `XTURNIX_CAL_DEVICE=cpu`，使用远端 4 CPU/16 GiB 作业及最多 1,800 秒。`main` 固定裁取原顺序前 8 个自然话轮加 3 个 sanity，FP32 不变；CUDA 调用与显存字段关闭，设备明确记为 CPU、CUDA 占用为 null。CPU 结果只支持机制行为，不能作为 GPU 延迟比较。模型仍不在本地或登录节点运行。
