# 完整FDB两轴r4：串行服务预热

状态：Running，启动预检与全部服务health通过，正式回放已启动，已观察到首个a4_report.json。当前微调模型T2_R3_delayed_start、300/1200ms TTS、KV复用、600ms micro-turn和duplex_greedy_v1保持。完整319例：119例Smooth Turn-Taking、200例User Interruption，原始清单SHA256 b804734cc4a030e629b16891468259958b8170a4a495e8909227bf4f716eb5be。

按用户决定暂缓GPT相关性评分，不更换judge；保留官方转写与两轴TOR/Latency。源码19f0371、X-Talk d6dc3bff0a512d13f4352bce6105aec80b7f9960，官方FDB 3e799c45a045256f47d5f1c9cda90157e2d2ec9e。

r3评分ASR预检通过，随后并行启动时Nemotron预热超原30秒而失败，已取消且无正式回放样本。r4串行启动ASR→TTS→LLM，ASR仅启动预热限时180秒，线上EOF/取消仍30秒；health等待核对实际PID，失败提前退出。原r1/r2/r3产物不覆盖。

远端根`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-fdb-two-axes-20261021-r4/`，输出`data/r4/`，日志`job.log`。预算2×4090/16CPU/64GiB、8小时、单并发，30GiB输出/50GiB空闲/8GiB单文件，评分后GPT明确待补。原始WAV、trace与完整数据清单留远端。

当前有效任务：`job-179256336071350402616-xuan-zhang`，run_id=full-fdb-two-axes-065-r4。已确认模型condition=T2_R3_delayed_start、generation_policy=duplex_greedy_v1，日志有KV命中。结果尚未完成，不提前填TOR/Latency。
