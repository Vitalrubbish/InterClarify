# 完整轨迹训练提交

`scripts/remote/submit_textturn_full_training.sh`取得共用提交锁，核对无活动作业、run未存在、audit通过且绑定当前manifest，再提交既有镜像上的单任务：1张24GiB GPU、8CPU、32GiB RAM、外层4小时。stdout保留调度回执，不把排队写成已经训练。

用户已明确授权核查后直接启动，并取消旧累计GPU剩余预算限制；本入口不读取旧累计预算账本，但不取消单作业资源门槛或质量放行。环境变量TEXTTURN_RUN_ID指定独立run，默认数据为tt-010-fulltraj-r1；实际提交后记录job ID及稳定运行证据到TT-010报告。
