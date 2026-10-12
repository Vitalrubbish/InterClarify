# run_xtalk_duplex_node_job.sh

## 功能与核心步骤

在获分配的 4090 作业中使用独立同步目录运行官方模型 smoke，先校验 source_manifest.json 中每份本地文件的 SHA256，确保远端测试对应本地源码副本；模型与测试全部使用 conda。加载共享存储已有官方 checkpoint/base，模型只见逻辑 GPU 0，服务使用独立端口；轮询 health 后运行 duplex_runtime_smoke.py，保存 health、GPU 信息、环境版本、服务日志与 report。

trap 只关闭本作业启动的模型服务。默认模型环境为共享 interclarify-dev，客户端为镜像 xtalk-round1-client。模型烟测使用脚本文本和模拟 PCM；完整音频及 FDB 是 A4 的后续验收。

模型服务进程在 health 前退出时，轮询立即失败，避免错误等待 600 秒。
