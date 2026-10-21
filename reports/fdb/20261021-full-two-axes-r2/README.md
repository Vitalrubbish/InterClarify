# 完整FDB两轴r2：修复评分模型解包限额

状态：评分ASR预检通过；随后原judge返回503，任务退出1，未开始正式回放。对应[065](../../../docs/issue/065_full_fdb_two_axes.md)与[066](../../../docs/issue/archive/066_fdb_alignment_file_limit.md)。

r1在官方Parakeet解包预检触发单文件1GiB限制，退出1，未跑正式319例。r2将单文件上限调至8GiB，临时目录纳入输出/tmp；输出总量30GiB、空闲盘50GiB、2×4090/16CPU/64GiB、8小时、单并发保持。保留r1日志与失败身份，不覆盖旧输出。

当前模型与评测输入不变：T2_R3_delayed_start checkpoint SHA256 266a37a28699d0c3f36b6a6305374bc89a1a2ff2af7a37fd1eb4caf1ad915346；首段300ms/后续1200ms、600ms micro-turn、KV复用、duplex_greedy_v1。完整Smooth Turn-Taking 119例、User Interruption 200例，清单SHA256 b804734cc4a030e629b16891468259958b8170a4a495e8909227bf4f716eb5be。

修复源码fe1d7da，X-Talk d6dc3bff0a512d13f4352bce6105aec80b7f9960，官方FDB 3e799c45a045256f47d5f1c9cda90157e2d2ec9e。远端根`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-fdb-two-axes-20261021-r2/`，输出`data/r2/`，源码`source/`，完整输入清单`full_corpus_manifest.json`；完整WAV、trace与清单留远端。

用户已明确暂缓GPT评分，后续由067以独立r3继续完整回放、官方转写及两轴时序指标，GPT分数保持待补，不改用其他模型。
