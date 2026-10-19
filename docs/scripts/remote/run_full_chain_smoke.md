# 当前英文完整链路单节点作业

`run_full_chain_smoke.sh`要求冻结源码根与新输出目录，校验逐文件摘要；在两张调度分配的4090上并行启动三个服务：官方LLM独占第一卡，Nemotron和Kokoro共用第二卡，均使用既有独立conda。分别执行真实readiness预热后调用full_chain_smoke.py的五例，退出关闭本作业进程组、保存各服务日志、health、GPU采样和退出码。

必须通过vc申请2 GPU、16 CPU、64GB主存；禁止登录节点推理。音频、checkpoint/base和组件权重使用既有冻结路径，不下载新模型，不执行训练或FDB。`FULL_CHAIN_ROOT`与`FULL_CHAIN_OUTPUT`必须新建且独立，不覆盖旧诊断。
