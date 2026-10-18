# 官方控制循环单卡诊断入口

`scripts/remote/run_layer1_runtime_comparison.sh` 无类。脚本核验 source.sha256、独立输出目录与设备，在独立模型/客户端 conda 环境启动单卡服务；等待最长 300 秒 readiness 后运行比较器，退出时关闭服务并保存退出码。模型恢复完整发布 checkpoint，BF16、64-token 贪心；调度资源起步 1×4090、8 CPU、32GB。

当前入口针对历史 Nemotron 累计文本，使用 first-nonempty、600ms 和 raw/有界 complete_word 两种诊断发布；`LAYER1_COMPARISON_CASE` 可限定样本。它没有原始 Kyutai Word 输入，不能作为官方 Word 对齐验收命令。本轮计划维护不修改脚本执行行为。

001b 应直接修改现有入口和比较器，使必验只运行一套官方 Word 输入配置；单步和固定输出仅按需排错，准确命令随实现更新。任务范围见 [001 远端任务单](../../issue/001_remote_execution.md)。本脚本不执行 ASR/TTS、训练或 FDB，不以退出 0 代替父任务放行。
