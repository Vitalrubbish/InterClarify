# 远端TextTurn诊断入口

`scripts/remote/run_textturn_diagnostics.sh`在单个调度作业内运行inspect或compare阶段。通过`TEXTTURN_RUN_ID`指定新目录，`TEXTTURN_DIAGNOSTIC_PHASE`指定阶段，默认使用现有远端conda和冻结完整轨迹数据。脚本记录源码、日志和资源，异常退出停止进程组并保留退出码。

每次提交前检查`vc list`无活动作业，以既有4090镜像申请1 GPU、8 CPU、32GiB RAM。脚本每10秒检查显存22GiB、项目资产10GiB、报告2GiB和30GiB空盘停止线；诊断7200秒由Python检查、外层timeout兜底。两阶段串行，禁止在登录节点直接运行模型。

追加的confirm阶段需显式设置`TEXTTURN_DIAGNOSTIC_CANDIDATE`为固定adapter路径；在compare结束且无活动作业后串行提交，不能自动替换候选。

`TEXTTURN_DIAGNOSTIC_CONFIG`可指定已冻结的条件性第四臂配置，默认仍为前三臂配置。切换配置需新run及真实源码摘要，不修改正在执行的作业。
