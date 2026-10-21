# 当前微调模型完整FDB两轴任务

状态：预检失败，退出1；官方Parakeet解包触发单文件1GiB限制（Errno27），未开始正式回放，未生成指标。工作单见[065](../../../docs/issue/archive/065_full_fdb_two_axes.md)。

使用T2_R3_delayed_start最终checkpoint（SHA256：266a37a28699d0c3f36b6a6305374bc89a1a2ff2af7a37fd1eb4caf1ad915346），采用300/1200ms TTS、KV复用、600ms拍长及duplex_greedy_v1/重复惩罚1.0。冻结InterClarify f25d9d1、X-Talk d6dc3bff0a512d13f4352bce6105aec80b7f9960、官方FDB 3e799c45a045256f47d5f1c9cda90157e2d2ec9e。

完整v1.0两轴：Smooth Turn-Taking/candor_turn_taking 119例、1668.996秒；User Interruption/synthetic_user_interruption 200例、5598.976秒，共319例。数量与官方dataset README一致，原始数据和标注已逐文件冻结，清单SHA256为b804734cc4a030e629b16891468259958b8170a4a495e8909227bf4f716eb5be。

远端根`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-fdb-two-axes-20261021-r1/`，源码在`source/`，完整清单为`full_corpus_manifest.json`，输出为`data/r1/`。只提交简明记录与身份；WAV、大trace和完整清单留远端，不纳入Git。

阶段：评分ASR与judge预检→319例实时回放→官方Parakeet词级对齐→两轴官方评分。Judge沿用gpt-4-turbo兼容端点，Smooth轴无LLM判题。官方输出严格原音频时长，5秒尾窗音频仅供诊断。原始官方流程与异常、漏答和实际覆盖率保留，不将执行成功等同于语义通过。

资源上限：2×4090/16CPU/64GiB、8小时、并发1、线程4、输出30GiB、空闲盘50GiB、单文件1GiB。本地4项清单/暂存测试与bash语法验证通过；评分模型仅在分配GPU上运行。

任务ID：`job-179255450314330572677-xuan-zhang`，run_id=`full-fdb-two-axes-065-r1`。源码、训练完成记录及319例/638个文件验证已通过；评分预检状态持续跟踪，不提前记为完成。

修复由[066](../../../docs/issue/archive/066_fdb_alignment_file_limit.md)跟踪：单文件改8GiB，总输出仍30GiB，独立r2重提。原r1的1GiB预算和失败日志保留为历史，不改写为新预算。
