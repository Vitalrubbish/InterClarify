# 完整FDB两轴r3：暂缓GPT评分

状态：调度器已接受并Running，启动预检中，指标未生成。用户已明确暂缓GPT回答相关性评分，保留以后使用原judge补跑的能力。此次继续全部319例实时回放、官方Parakeet词级对齐和两轴TOR/响应延迟。

Smooth Turn-Taking：119例，运行官方evaluate.py；User Interruption：200例，按冻结官方1秒/3词规则重算时序，保留原始负延迟和官方归零口径，GPT分数为null、deferred_by_user。请求范围执行通过与完整评分完成分别登记，不用执行成功冒充GPT评分完成。

模型T2_R3_delayed_start，checkpoint SHA256为266a37a28699d0c3f36b6a6305374bc89a1a2ff2af7a37fd1eb4caf1ad915346；300/1200ms TTS、600ms拍长、KV复用、duplex_greedy_v1/重复惩罚1.0，系统backchannel关闭。源码b4ab705、X-Talk d6dc3bff0a512d13f4352bce6105aec80b7f9960；完整清单SHA256 b804734cc4a030e629b16891468259958b8170a4a495e8909227bf4f716eb5be。

远端根`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-fdb-two-axes-20261021-r3/`，输出`data/r3/`，任务日志`job.log`。资源2×4090/16CPU/64GiB、8小时、并发1，输出30GiB、空闲盘50GiB、单文件8GiB。r1/r2失败日志保留，r3不覆盖旧结果。

本地6项清单/时序规则测试通过、bash语法通过。大WAV、逐请求trace及完整数据清单留远端，Git只保留摘要与路径。

任务ID：`job-179256291703117654931-xuan-zhang`，run_id=`full-fdb-two-axes-065-r3`。实际关闭GPT判题由FULL_FDB_DEFER_JUDGE=1及评分--defer-judge双重登记。

启动检查：319例/638文件和源码/微调权重校验通过；官方Parakeet语音及静音对齐预检通过；judge_preflight记录deferred_by_user/api_called=false。模型与ASR/TTS服务正在加载，正式回放启动另行核查。

后续启动失败：并行服务启动时Nemotron预热超过30秒并隔离，未产生正式回放；已取消作业，保留日志。068改为串行服务启动与独立180秒预热，r4重提，正式在线超时不变。
