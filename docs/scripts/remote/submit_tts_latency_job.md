# TTS 基线作业提交

`submit_tts_latency_job.sh` 使用已经核对的 `vc submit` 参数接口，申请 `pdgpu-4090` 单 GPU、8 CPU、32G 内存及既有 round1:v0.4 镜像。要求 `TTS_TASK_ROOT`、`TTS_OUTPUT` 显式给出绝对路径；环境变量只转发 TTS 实验与固定模型路径，参数用 shell 转义构造。节点内使用镜像 conda，源码与权重从共享盘读取。唯一入口为 `run_tts_latency_node_job.sh`，提交日志写入独立输出父目录。

提交成功只说明调度器接受；须继续检查 job 状态、依赖报告、组件测试及 cold/warm smoke，确认真实推理开始后才能报告“测试运行中”。完整基线结束以 `baseline/summary.json` 和 `exit_code.txt=0` 为准。

可显式传递 `TTS_HEALTH_TIMEOUT` 和 `TTS_STACK_DIAGNOSTIC`，用于排障作业；诊断结果与正式测量分开保存。

`TTS_CODEC_LOAD_THREADS` 可显式转发到节点，仅控制 codec 启动加载，不改变热态推理线程数。

`TTS_SCREEN_JOB=1` 选择筛选节点入口，任务描述为 `tts-latency-screen`；其他设置与原基线相同。此开关由提交端选择脚本，不转发任意命令到节点。

可转发 `TTS_ONLY_ARMS` 作为经过 shell 转义的字符串；节点端只按数组参数交给 argparse 的枚举校验。
