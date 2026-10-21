# run_full_fdb_two_axes.sh

单个双4090调度作业内，先核对源码/训练checkpoint/数据身份和现役conda，再对评分环境执行本轮输入3秒裁片及静音的官方对齐与judge预检，随后加载当前微调模型及Nemotron/Kokoro，串行回放完整两轴，停推理服务后进行官方对齐与评分。当前配置固定300/1200ms、KV复用、600ms拍长及显式greedy策略，X-Talk来自已发布提交。

无类。check_budget控制总输出30GiB、空闲盘50GiB；wait_ready检查服务并在死亡时提前失败；cleanup回收各进程组、登记退出码。外部timeout为8小时，调度器限制2×4090/16CPU/64GiB，并发1、线程4、单文件8GiB。输出首次创建，重复任务必须更换run_id；不覆盖原始FDB、旧测试或上游评分脚本。

066修复：NeMo官方评分模型解包需要超过1GiB的单文件，调整至8GiB；临时文件放入输出/tmp，保持总磁盘和空闲盘限额。

067：用户决定暂缓GPT评分，默认FULL_FDB_DEFER_JUDGE=1，预检写deferred_by_user且不调用API，评分命令显式传--defer-judge。回放/官方对齐正常执行，顶部summary整合推理/评分和GPT待补状态。之后有可用原judge时可显式关闭该开关补跑，不能自动换用其他模型。

068：评分预检后按ASR→TTS→LLM串行启动并逐个等health；ASR启动预热单独180秒，在线会话规则不变。wait_ready检查实际服务PID，避免ASR失败后仍等待无关LLM。r3失败日志保留，修复使用独立r4。
