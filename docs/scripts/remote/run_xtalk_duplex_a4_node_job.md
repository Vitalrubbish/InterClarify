# `scripts/remote/run_xtalk_duplex_a4_node_job.sh`

A4 节点执行入口：校验清单、资产和三张 GPU，检查 conda 依赖，执行 X-Talk A1–A3 回归和根仓库驱动测试，启动官方 DuplexCascade/Qwen3-ASR/MOSS，运行官方模型 smoke、真实音频回放和可选 FDB。

`record_step` 追加逐步 JSONL；`wait_http` 检查服务 health、日志及启动进程；`stop_services` 仅清理本作业进程组。失败、阻塞和未覆盖状态进入 `a4_summary.json`；自动 PASS 只表示本次自动检查通过，完整 A4 仍需任务单列出的额外场景/对照/资源证据。

必填 `INTERCLARIFY_DUPLEX_ROOT`；默认共享路径、环境、服务端口见脚本开头。可覆盖输入、长会话轮数、FDB 子集/仓库/任务、输出目录和 conda 环境。提交包装器将这些环境变量传入节点。

默认硬失败退出非零，`DUPLEX_A4_REQUIRE_COMPLETE=1` 要求所有自动步骤 PASS。输出目录重复使用会拒绝启动。完整用法、GPU 分卡和回收文件见 [任务单](../../xtalk_a4_remote_acceptance.md)。
