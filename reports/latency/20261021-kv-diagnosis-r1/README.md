# Issue 051 缓存生成分歧诊断

状态：完成，退出0。协议与资源额度见[051](../../../docs/issue/051_kv_cache_generation_divergence.md)。

仅对固定分歧会话前五拍复现，比较实际服务、完整前缀与拆分前缀的KV/logit，固定共同控制token后检查首正文候选；BF16原后端、BF16 eager、FP32 eager依次执行。源码摘要见[source_identity.json](source_identity.json)，原049-r2源码与输出不修改。

远端根：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-kv-diagnosis-20261021-r1/`；结果在`output/`，`diagnostic.log`保留模型启动和错误，`exit_code.txt`为最终状态。脚本仅诊断，不改变生产权重或配置。

任务ID：`job-179254796055509425847-xuan-zhang`。真实权重对照完成；本地conda的tiny Qwen完整/拆分前向诊断冒烟检查用于验证脚本调用形状，真实原因以远端结果为准。

首轮已复现实际生成ID差异并取得BF16/FP32对照，最终原因及实际处理后分数由[第二轮报告](../20261021-kv-diagnosis-r2/README.md)统一说明。

完整results.json保留本地，不纳入Git；结果摘要与原文摘要哈希见[第二轮关键证据](../20261021-kv-diagnosis-r2/evidence_summary.json)，远端output原始文件保留。
