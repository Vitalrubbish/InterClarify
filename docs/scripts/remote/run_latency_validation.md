# run_latency_validation.sh

脚本在调度器分配的双4090作业中运行：模型单独占GPU0，ASR与Kokoro共用GPU1；沿用现役conda，不创建模型副本。先验证checkpoint、固定25会话数据和源码摘要，运行必要回归，再串行运行三臂、两组固定文本供给与固定历史缓存探针，最后生成分段报告。

无类。check_budget 控制输出和空闲磁盘；wait_ready 确认服务启动；cleanup 关闭各服务进程组、写退出码。输出目录首次创建，重复执行必须更换 run_id。外部timeout限制4小时，计算/内存由调度器约束；缓存常驻总额512MiB，峰值显存另行记录。
