# run_full_fdb_two_axes.sh

单个双4090调度作业内，先核对源码/训练checkpoint/数据身份和现役conda，再对评分环境执行本轮输入3秒裁片及静音的官方对齐与judge预检，随后加载当前微调模型及Nemotron/Kokoro，串行回放完整两轴，停推理服务后进行官方对齐与评分。当前配置固定300/1200ms、KV复用、600ms拍长及显式greedy策略，X-Talk来自已发布提交。

无类。check_budget控制总输出30GiB、空闲盘50GiB；wait_ready检查服务并在死亡时提前失败；cleanup回收各进程组、登记退出码。外部timeout为8小时，调度器限制2×4090/16CPU/64GiB，并发1、线程4、单文件1GiB。输出首次创建，重复任务必须更换run_id；不覆盖原始FDB、旧测试或上游评分脚本。
