# `tests/test_moss_tts_patch.py`

## 功能与边界

验证 `scripts/remote/moss_tts_patch.py`：**循环重写的等价性**、采样档位契约、滑动窗口、每回合指标行与 import hook。用确定性的假 local transformer（`FakeLocalTransformer`/`FakeModel`）代替真实权重，因此不需要 GPU。

等价性用例需要真实上游类 `mossttsrealtime.streaming_mossttsrealtime.MossTTSRealtimeInference`，只在 **TTS conda 环境（`xtalk-round1-moss`）** 可导入；其它环境整文件 skip（torch 缺失即 skip，不报错）。

## 用例

| 用例 | 断言 |
| --- | --- |
| `LoopEquivalenceTests`（3 个） | `_local_loop`（贪心）与真实上游 `_generate_local_transformer_impl` 在**无历史/有重复惩罚/窗口饱和**三种输入上逐 token 相等 |
| `SamplingTests`（3 个） | `_sample_greedy` = argmax；`_sample_topk` 的采样值落在 top-k 内且形状与上游一致；`XTALK_TTS_SAMPLE=greedy` 下 `_patched_sample_token` 退化为 argmax |
| `HistoryTests` | 滑动窗口右对齐（最新帧在尾部、顺序为时间序）且有界（不超过 `_HISTORY_CAPACITY`） |
| `MetricsTests` | `[tts-metric]` 每回合只出一行，含 `frames=`/`audio_s=`/`rtf=`，报告后帧计数归零 |
| `ImportHookTests` | 临时目录伪造 `mossttsrealtime.streaming_mossttsrealtime`，经 `install()` 的 meta-path 包装后导入即被打上 `_xt_patched` |

## 运行

```bash
# TTS 环境：9 个用例全跑
PYTHONPATH=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/moss-source/moss_tts_realtime \
  conda run -n xtalk-round1-moss python -m unittest tests.test_moss_tts_patch

# 其它环境：整文件 skip（torch 缺失）
conda run -n xtalk-round1-client python -m unittest tests.test_moss_tts_patch
```
