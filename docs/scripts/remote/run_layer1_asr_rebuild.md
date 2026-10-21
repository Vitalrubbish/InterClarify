# 原1k延后句读数据重建任务

`scripts/remote/run_layer1_asr_rebuild.sh`执行077数据回归、固定来源重建、完整审计、ASR训练索引及60条原073用户轮的复核卡片导出，无类。指定`LAYER1_ASR_ROOT`冻结worktree和新的`LAYER1_ASR_DATA_OUTPUT`，使用已有训练conda，不覆盖旧目录。

单CPU亲和性、线程1、worker0、nice10、4GiB地址空间，测试各120秒，重建/审计合计1800秒；新数据10GiB/空闲盘20GiB，退出码与源码记录写入输出。无GPU，不启动训练；完整文字留远端，紧凑证据回收后交078。
