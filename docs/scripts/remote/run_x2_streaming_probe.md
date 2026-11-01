# 远端 X2 单帧探针入口

`run_x2_streaming_probe.sh` 在调度分配的一张 4090 上加载 X2Streaming-ASR 并运行单帧探针。读取 `SOULX_ROOT`、`SOULX_SOURCE`、`SOULX_RUN_ID`、`SOULX_FDB_MANIFEST` 和可选的 `SOULX_X2_MODEL`，不启动 SoulX。

## 前置

- `~/interclarify-english-integration-20261018-v1/envs/asr` 存在且 includes transformers 5.15.1；
- `~/turncontrol-comparison/models/x2streaming-asr/model.safetensors` 存在，SHA256 与 `configs/x2_streaming_probe.json` 一致；
- 冻结 FDB30 清单存在；
- `$SOULX_ROOT/runs` 可写，剩余空间不少于 30GiB。

## 行为

1. 建立 `runs/$SOULX_RUN_ID`，拒绝覆盖；用 `.x2-streaming.lock` 串行化同类作业。
2. 记录探针、配置和清单摘要，核对权重 SHA256，写 `model.sha256`。
3. 固定离线环境变量、缓存目录和线程数，外层 1700s 超时。
4. 后台启动探针并每 2s 采样本进程显存；超过 22528MiB、输出超过 256MiB 或超时即终止。
5. 保留真实退出码和 `probe/result.json`；门槛不通过时探针以非零退出，但结果文件仍完整保留。

## 提交示例

```bash
vc submit --image docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4 \
  --partition pdgpu-4090 --job ntf011-x2-probe --num-task 1 \
  --cpu-per-task 4 --mem-per-task 32G --gpu-per-task 1 \
  --cmd 'SOULX_SOURCE=/path/to/source/<commit> SOULX_RUN_ID=ntf011-x2-probe-20261101-r1 SOULX_FDB_MANIFEST=/path/to/fdb30.json timeout -k 20s 1800s bash /path/to/source/<commit>/scripts/remote/run_x2_streaming_probe.sh'
```

单作业、单并发；不使用登录节点。探针不联网、不训练、不写问题单范围外的资产。
