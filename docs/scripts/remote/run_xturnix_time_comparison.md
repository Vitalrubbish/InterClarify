# 短延迟对照远端入口

`scripts/remote/run_xturnix_time_comparison.sh` 在单个调度 GPU 作业中串行完成模型锁复核、冻结数据准备、真实 ASR 预热、事件采集和三策略评分。必须设置唯一的 `XTURNIX_TIME_RUN_ID` 和已有冻结文本目录 `XTURNIX_TIME_INPUTS`，复用现有 ASR/PT conda，不在登录节点推理。

脚本没有业务类。主流程先检查 conda、GPU 可见性与 30GiB 可用盘，独立目录已有则拒绝；调用者必须通过调度器分配 GPU，显卡可见性本身不是调度凭据。`cleanup` 只停止本次新建的采集和服务进程组及监控器，保留退出码、硬件、资源及进程状态。ASR 服务使用独立端口 18815，不改现役配置；预热源只用于就绪核查，不进入校准分母。

调度时必须使用一个活动作业、1×24GiB GPU、8 CPU、32GiB RAM，并从外层施加 7,200 秒总超时；事件采集另有 6,000 秒限时。显存超过 22GiB 或输入加输出超过约 1.2GiB 时停止并保留原因。音频下载 worker=1，源音频与归一化副本合计≤1GiB；逐例 trace 限制使合计≤200MiB。

示例（在远端登录节点，先确认没有其他活动作业）：

```bash
vc list
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition pdgpu-a10 --job xturnix-time-control \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 /absolute/path/to/submit.log \
  --cmd 'XTURNIX_TIME_RUN_ID=xtx014-time-r1 XTURNIX_TIME_INPUTS=/absolute/path/to/frozen-inputs timeout --signal=TERM --kill-after=30s 7200 bash /absolute/path/to/repo/scripts/remote/run_xturnix_time_comparison.sh'
```

原始 manifest 含历史，留远端；回收仅包含无正文事件、状态、比较结果和执行摘要。认证、排队或运行失败均不能填作模型对照已完成。
