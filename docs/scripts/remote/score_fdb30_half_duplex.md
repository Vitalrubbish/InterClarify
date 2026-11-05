# FDB30 完整系统评分

`scripts/remote/score_fdb30_half_duplex.py` 独立读取完成的固定 30 条实录，不加载控制器或重新生成回答。`main` 验证样本完整性、输入和标注摘要、逐帧播放录音来源、官方 FDB 提交及 Parakeet 权重摘要。

先将真实播放录音截到原输入时长，再按打断结束点裁去前段并用 Parakeet 词时间戳评分。调用 `score_duplex` 的 `behavior` 和冻结官方函数核对 TOR／延迟，停顿分 Candor 与 Synthetic 汇总。对齐与评分工作目录独立于不可改写的推理目录。

最后复制官方评估入口并调用打断回答相关性 judge，凭据只从既有文件或环境读取并传给子进程，不写入产物。judge 失败时保留已完成的时序指标，明确状态并返回非零；只有十份 rating 均产生才标记完成。输出 `summary.json` 含逐例结果、分组指标和来源。固定子集不宣称为全量 FDB；没有 backchannel，ICC／JSD 不适用。

远端 conda 评分环境，单张 4090、4 CPU、32GiB、外层 3600 秒；推理作业退出后才提交评分。无业务类，不改写原始输入与实录。
