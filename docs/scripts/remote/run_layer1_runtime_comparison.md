# 官方 Word 控制循环单卡对照入口

`scripts/remote/run_layer1_runtime_comparison.sh` 无类。要求 `LAYER1_COMPARISON_ROOT`、新的 `LAYER1_COMPARISON_OUTPUT` 和已核验的 `LAYER1_WORD_MANIFEST`；不再内置 Nemotron raw 或完整词变体。`LAYER1_COMPARISON_CASE` 可限定一个样本。

脚本校验源码摘要、输入和设备，在独立模型/客户端 conda 环境启动 BF16 发布 checkpoint；最长等待 300 秒 readiness，随后运行唯一 Word 对照配置。EXIT trap 关闭本作业模型进程组并保存退出码；不覆盖既有输出。经 vc 调度申请 1×4090、8 CPU、32GB 主存。

入口不运行 ASR/TTS、不训练、不执行 FDB。Word manifest 和样本来源须先按 [001 任务单](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/001_remote_execution.md)核验；比较器结果、集成生命周期和资产证据齐全后再判断 001 放行。
