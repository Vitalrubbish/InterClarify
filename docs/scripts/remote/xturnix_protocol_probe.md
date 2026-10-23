# XTurnix 协议预热探针

`scripts/remote/xturnix_protocol_probe.py` 用 dev 录音串行验证 XTX-002 的两组件协议：Nemotron 原生输出、暂停不结束会话、EOF 排空与会话清理，以及 XTurnix 的 Listen 动作、去标点、上下文上限和资源峰值。它是诊断证据，不计算正式 start 延迟或 WER。

## 输入与输出

输入为冻结配置、dev 音频、XTurnix 模型目录和已预热的 Nemotron 服务地址。输出目录写入：

| 文件 | 内容 |
| --- | --- |
| `probe.json` | 汇总、全部检查项、资源峰值和 `passed` |
| `asr_evidence.json` | 健康响应、会话、逐版本文本、暂停标记、EOF、清理结果 |
| `xturnix_evidence.json` | 模型加载、调用记录、归一化对照、上下文失败路径、GPU/RSS 峰值 |

探针不读取正式 test 子集，也不把结果并入正式分母。

## ASR 流程

`AsrClient` 封装 `/health`、创建会话、输入、结果读取和删除。`ResultObserver` 以冻结的 50ms 周期读取结果，只保留 `prefix_version` 变化的快照，并记录客户端单调接收时间；同一会话最多一个在途读取。

`run_asr` 按 80ms 真实时钟发送 dev 音频，在录音中点发送一次 `is_final=true` 暂停标记，随后继续发送；音频结束后发送 5.04 秒静音，再以空音频和 `end_stream=true` 做真实 EOF 排空。最后检查：

- 健康响应中的模型、160ms 分块、FP32 和两次预热与配置一致；
- 文本版本严格单调且为前缀扩展；
- 暂停后仍产生更长的最终文本，说明暂停没有结束会话；
- 删除后结果接口返回 404，第二会话仍可创建、结束和清理；
- 清理后服务仍健康。

## XTurnix 流程

`safe` 加载官方 `turn_pipeline.py` 后，通过本地 `transformers.pipeline` 加载模型，记录加载耗时。配置要求 `max_seq_length` 与模型内 `xturnix_config` 一致，Listen 只允许 `start/keep`。

`run_xturnix` 以最终 ASR 文本的三段前缀和完整文本调用模型，记录请求 ID、控制输入序号、原始/归一化输入及其摘要、状态、动作、两动作分数和收发单调时间。另用模型卡给出的完整问句做一次 `contract_example` 诊断，验证 start/keep 动作路径本身可用；该诊断不属于 FLEURS 样本，也不参与正式指标。归一化检查直接调用官方 `prepare_messages` 与 `strip_trailing_punctuation`：

- 末尾标点与空白被去除，内部逗号、大小写和词序保留；
- 原始文本与规范化文本得到相同动作和分数；
- 超长单条用户消息触发 `cannot fit max_length`，不静默截断；
- Speaking 状态只返回 `stop/keep`。

所有调用串行执行，不并发请求。任何检查失败时写出完整证据后返回非零，不以部分成功掩盖失败。XTurnix 以官方 `turn_pipeline.py` 在独立 conda 进程中加载，不新建 HTTP 文本生成服务；`pipe` 进程退出即释放模型，ASR 服务由作业入口单独启停。

## 运行

探针必须由 `run_xturnix_protocol_probe.sh` 在调度 GPU 作业中启动；它假设 Nemotron 服务已经完成真实语音预热。示例：

```bash
~/interclarify-xturnix-fleurs/envs/xturnix/bin/python \
  scripts/remote/xturnix_protocol_probe.py \
  --config configs/xturnix_fleurs_test.json \
  --dev-audio ~/interclarify-xturnix-fleurs/dataset/fleurs_en_us/audio/dev/786465049904960526.wav \
  --asr-url http://127.0.0.1:18805 \
  --output <new-output-dir>
```

探针本身不启动或停止服务，不修改输入音频，不训练、不调阈值、不接入 Layer 1/TTS/播放器。
