# 候选干净进程重载

`scripts/training/run_layer1_alignment.py` 只保留 `verify_candidate`：在独立干净进程中完整加载官方权重，调用 `layer1_candidate.load_candidate` 恢复最终 `T2_R3_delayed_start` 检查点，校验资产、LoRA 白名单、最终 epoch 游标和 checkpoint 摘要，并复现训练结束时的协议生成 IDs。

脚本无阶段调度、短跑、恢复对照或正式/探针双模式；输出为单个 JSON 报告，必须写入新路径。旧 `run` 子命令、100 步探针及候选可服务豁免已删除；正式候选只有完整最终 epoch 一种身份。
