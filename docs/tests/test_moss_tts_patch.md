# `tests/test_moss_tts_patch.py`

## 功能与边界

验证 `scripts/remote/moss_tts_patch.py`：**循环重写的等价性**、采样档位契约、注意力/cache 切换、编译饱和门、CUDA event 记账（含跨回合共享的 backbone 列表）、滑动窗口、限速指标行、profiler 摘要与 import hook。用确定性的假 local transformer（`FakeLocalTransformer`/`FakeModel`）代替真实权重，因此不需要 GPU。

等价性用例需要真实上游类 `mossttsrealtime.streaming_mossttsrealtime.MossTTSRealtimeInference`，只在 **TTS conda 环境（`xtalk-round1-moss`）** 可导入；其它环境整文件 skip（torch 缺失即 skip，不报错）。

## 用例

| 用例 | 断言 |
| --- | --- |
| `LoopEquivalenceTests`（5 个） | `_local_loop` 与真实上游 `_generate_local_transformer_impl` 在**无历史/有重复惩罚/窗口饱和**三种输入上逐 token 相等；`mode='upstream'` 确实经 `sample_token` 派发（16 次调用）且结果与贪心一致；`do_sample=False` 退化为 argmax |
| `SamplingTests`（3 个） | `_sample_greedy` = argmax；`_sample_topk` 的采样值落在 top-k 内且形状与上游一致；`XTALK_TTS_SAMPLE=greedy` 下 `_patched_sample_token` 退化为 argmax |
| `AttachStateTests` | `_attach` 必须定义热路径读取的**每个**字段（防"门读了未定义字段"这类 bug 复现） |
| `CompileGateTests`（3 个） | 饱和门 = `min(capacity, repetition_window)`；窗口大于容量时取容量；无窗口时取容量 |
| `EventAccountingTests` | 只有 `end` 事件已完成的 CUDA event 对会被累加（毫秒→秒），未完成的对留到下一行 |
| `HistoryTests` | 滑动窗口右对齐（最新帧在尾部、顺序为时间序）且有界（不超过 `_HISTORY_CAPACITY`） |
| `MetricsTests`（3 个） | 达标切片输出一行且含 `frames=`/`audio_s=`/`rtf=`/`local_s=`/`backbone_s=`；不足 6 帧且未强制时静默、`force=True` 时输出；开关关闭时只计数不落日志，报告后帧计数归零 |
| `CompileSupportTests`（7 个） | `relax_dynamo_logging` 把 `Logger.warning_once` 等加入 `torch._dynamo.config.ignore_logger_methods`；`_wrap_backbone` 把 event 列表挂在 model 上（服务每回合换 inference 对象，共享 model 才能持续计时）；`switch_local_attention` 只改 local transformer（切 sdpa、静态本地 cache、关闭上游自编译）而不动 backbone；`XTALK_TTS_LOCAL_ATTN` 解析（只有 `sdpa`/`traceable` 生效）；`_log_profile_summary` 输出可被报告解析的 `frames=/device_s=/cpu_s=/top=` 行；`_dump_profile` 每次只追加一张表并记录剖析帧数；`XTALK_TTS_PROFILE[_FRAMES]` 解析 |
| `ImportHookTests` | 临时目录伪造 `mossttsrealtime.streaming_mossttsrealtime`，经 `install()` 的 meta-path 包装后导入即被打上 `_xt_patched` |

## 运行

```bash
# TTS 环境：25 个用例全跑
PYTHONPATH=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/moss-source/moss_tts_realtime \
  conda run -n xtalk-round1-moss python -m unittest tests.test_moss_tts_patch

# 其它环境：整文件 skip（torch 缺失）
conda run -n xtalk-round1-client python -m unittest tests.test_moss_tts_patch
```
