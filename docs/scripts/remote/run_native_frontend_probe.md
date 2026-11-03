# NTF-018远端受限作业

对应`scripts/remote/run_native_frontend_probe.sh`。只能在分配了GPU的调度作业中运行；`NTF_SCHEDULED_RUN=1`由提交命令设置，不在登录节点手工运行。避免在环境变量名中使用调度器会替换的`JOB`占位符。脚本使用既有SoulX／ASR conda，要求干净冻结源码、原FDB30摘要、空闲盘至少10GiB和独占前端锁，输出目录存在则拒绝覆盖。

`NTF018_GROUP=dual`依次启动两个全新进程执行有限／完整双路；`single`只执行单路完整参考。两组各提交一次，合计最多2作业，不自动重跑。有限臂失败保留退出码，并继续测一次完整臂；外层作业退出码可能因有限臂失败非零，018的实时门槛取`dual-full`自身退出0、完整覆盖、3/3和资源记录，不能只看外层退出码。

首次调度因变量名占位替换在模型脚本启动前失败，已占用第1作业。剩余作业改用`NTF018_GROUP=matrix`，按双路有限／双路完整／单路完整顺序各执行一次，保持独立新进程；总时长和输出仍按单作业限制，不追加第3作业。该变更在任何条件开始前冻结，不能用于结果出来后的筛选重跑。

每作业单卡4090、4CPU、32GiB RAM，唯一模型worker／路、CPU线程各≤2；脚本每秒检查显存22528MiB、进程组RSS32GiB、输出128MiB和1750秒收尾线。调度器另限制1800秒与32GiB；文件大小也有限制。触限终止整个进程组，保存resource_stop及exit_code，不进入下一条件。RAM按RSS／调度内存限制，不使用会破坏CUDA虚拟地址映射的地址空间上限。

必须先只读检查`vc list`、账户配额和磁盘。待复测参考命令（仅取得追加作业授权后，替换实际冻结源码执行）：

```bash
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition pdgpu-4090 --job ntf018-matrix-20261103-r2 \
  --num-task 1 --cpu-per-task 4 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 "$HOME/parathink-soulx-duplug/submit_logs/ntf018-matrix-20261103-r2.log" \
  --cmd 'export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}; NTF_SCHEDULED_RUN=1 NTF018_GROUP=matrix SOULX_SOURCE=FROZEN_SOURCE SOULX_RUN_ID=ntf018-matrix-20261103-r2 SOULX_FDB_MANIFEST=FROZEN_MANIFEST timeout --kill-after=10 1800 bash FROZEN_SOURCE/scripts/remote/run_native_frontend_probe.sh'
```

本轮r1矩阵作业已结束且未通过，原2次提交额度已用完。上方r2命令仅供获批后的新增复测，不覆盖r1；当前没有可自动提交的剩余额度。模型与数据复用，不复制权重；本脚本不负责提交作业、换卡或放行019。
