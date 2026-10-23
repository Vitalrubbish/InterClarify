# run_xturnix_listen_calibration.sh

## 作用与流程

在单个调度 GPU 作业内运行 XTX-010 Listen 校准。脚本复用 `interclarify-xturnix-fleurs/envs/xturnix` conda 与只读 PT 权重，输入为已冻结的准备目录，输出使用不可覆盖的独立 run_id。训练、Speak、ASR、TTS 和现役切换均不执行。

同一受限入口也支持 XTX-014 原生 pause 诊断：设置 `XTURNIX_CAL_ENTRYPOINT=xturnix_pause_usage_probe.py`、`XTURNIX_CAL_TIMEOUT_SECONDS=900`。入口只允许原校准与该诊断两个脚本，超时只允许 1—1,800 秒；默认仍是原校准 1,800 秒，不改变旧 run 或评分配置。

启动时检查 conda 标记、输入摘要、空闲磁盘≥30 GiB，限制输入≤10 MiB，运行超时 1,800 秒。作业申请 1 GPU、8 CPU、32 GiB RAM；环境线程≤8，模型 batch=1。采样 GPU 显存并保留进程 RSS；超过 22 GiB 显存或 100 MiB 结果大小则终止计算，退出码与清理结果保留。失败不覆盖重跑，不自动增配。

## 提交示例

在检查 `vc list` 没有其他活动作业后，从冻结源码目录提交：

```bash
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition pdgpu-a10 --job xturnix-listen-calibration \
  --num-task 1 --cpu-per-task 8 --mem-per-task 32G --gpu-per-task 1 \
  JOB=1:1 /path/to/new-submit.log \
  --cmd 'XTURNIX_CAL_RUN_ID=unique-run XTURNIX_CAL_INPUTS=/path/to/frozen-inputs bash /path/to/source/scripts/remote/run_xturnix_listen_calibration.sh'
```

调度包装会改写命令里的字面量 `JOB`，因此运行时变量使用 `XTURNIX_CAL_*`。先提交已测试源码并建立独立 detached worktree，不覆盖远端主仓库的修改。原始输入/分数留远端，报告保存模型和输入哈希、工作点、完整分母、失败、资源及退出证据。
