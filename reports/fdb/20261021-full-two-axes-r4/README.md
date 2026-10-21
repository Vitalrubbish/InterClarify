# 完整FDB两轴r4：最终转写与时序评分

状态：2026-10-21完成当前授权范围，319例回放、官方转写和两轴时序评分全部完成；回放、评分及作业退出码均为0。GPT相关性评分仍按用户决定暂缓，不能称为完整GPT评分完成。当前微调模型T2_R3_delayed_start、300/1200ms TTS、KV复用、600ms micro-turn和duplex_greedy_v1保持。完整319例：119例Smooth Turn-Taking、200例User Interruption，原始清单SHA256 b804734cc4a030e629b16891468259958b8170a4a495e8909227bf4f716eb5be。

模型从官方权重初始化，使用1000条UltraChat对话的T2去句读视图微调，采用末文字后首个no-voice拍启动回答及加权控制损失。最终checkpoint SHA256为266a37a28699d0c3f36b6a6305374bc89a1a2ff2af7a37fd1eb4caf1ad915346。no-voice仅表示该拍无新增ASR文本，不等同真实声学静音。

## 结果

| 轴 | 已转写／总例数 | 官方规则有效接话 | TOR | 有效接话平均延迟 |
| --- | --- | --- | --- | --- |
| Smooth Turn-Taking | 119/119 | 59/119 | 49.58% | 1.023秒 |
| User Interruption | 200/200 | 160/200 | 80.00% | 1.183秒 |

Smooth使用冻结官方evaluate.py，退出0，并与同规则逐例重算核对一致。User Interruption使用官方ASR脚本按插话结束位置裁剪并转写，再按冻结官方规则计算TOR/Latency；GPT分支未执行，evaluation_rc与average_rating保持null。正式输出严格与原输入等长，额外5秒诊断尾窗不进入评分。

TOR将无词，或词跨度不足1秒且词数不超过3的样本计为未接话；两个轴分别有60例和40例未达到该标准，不宜全部解释为完全静默。延迟只统计有效接话，未接话不填0；负延迟按官方聚合规则归零。Smooth有5例原始负延迟（118、22、35、36、61），范围−10.27至−1.03秒，表明首个有效输出早于标注交接锚点，不能把归零当作零延迟正确接话。User Interruption无负延迟。TOR也不证明回答切合插话内容，内容质量仍待GPT或人工检查。

目前结果显示自然接话覆盖不足；没有本轮同条件官方原权重的完整对照，不能仅凭该表归因于去句读训练或量化微调收益。

## 回收与验收

北京时间17:18:39回收并核对[最终summary](completed/summary.json)、[回放summary](completed/replay_summary.json)、[Smooth逐例时序](completed/smooth_turn_taking.json)、[Interruption逐例时序](completed/user_interruption.json)及[来源摘要和退出码](completed/collection.json)。回放summary的official_scoring=pending是评分前生成的阶段快照，最终状态以最终summary为准。请求范围通过，full_scoring_complete=false专指GPT评分待补；不表示模型能力达到验收目标。

按用户决定暂缓GPT相关性评分，不更换judge；保留官方转写与两轴TOR/Latency。源码19f0371、X-Talk d6dc3bff0a512d13f4352bce6105aec80b7f9960，官方FDB 3e799c45a045256f47d5f1c9cda90157e2d2ec9e。

r3评分ASR预检通过，随后并行启动时Nemotron预热超原30秒而失败，已取消且无正式回放样本。r4串行启动ASR→TTS→LLM，ASR仅启动预热限时180秒，线上EOF/取消仍30秒；health等待核对实际PID，失败提前退出。

远端根`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-fdb-two-axes-20261021-r4/`，输出`data/r4/`，日志`job.log`。预算2×4090/16CPU/64GiB、8小时、单并发，30GiB输出/50GiB空闲/8GiB单文件，评分后GPT明确待补。原始WAV、trace与完整数据清单留远端。

任务：`job-179256336071350402616-xuan-zhang`，run_id=full-fdb-two-axes-065-r4。已确认模型condition=T2_R3_delayed_start、generation_policy=duplex_greedy_v1，日志有KV命中。用户要求启动评分时，既有作业已自动转入评分阶段，沿用同一作业完成，没有重复提交或重跑回放。回收后vc list无活动作业；原始WAV与大日志保留远端。GPT相关性评分待后续配置与授权。
