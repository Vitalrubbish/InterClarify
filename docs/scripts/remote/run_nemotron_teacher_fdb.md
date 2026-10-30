# 远端教师文字实验启动脚本

`run_nemotron_teacher_fdb.sh` 在调度分配的一张4090上启动独立 ASR 与 SoulX conda 进程，读取 `SOULX_SOURCE`、`SOULX_RUN_ID`、`SOULX_FDB_MANIFEST`。独立目录、互斥锁与来源摘要确保可复现，不覆盖旧结果。

两进程各2线程，调度4CPU／32GiB，合计显存22GiB、输出目录128MiB、1800秒外层时限；磁盘不足或800ms输入积压时失败。清理函数终止本脚本子进程并保留退出码，权重与环境只读复用。主实验默认保留原生空增量规则，可经环境变量关闭该分支作消融。

NTF-004：模型回放失败时也执行离线分析并保留原退出码，避免部分轨迹缺少汇总。分析只读原始结果，不将部分样本改成成功。配置冻结见`configs/nemotron_teacher_gated.json`；模型和conda继续只读复用。
