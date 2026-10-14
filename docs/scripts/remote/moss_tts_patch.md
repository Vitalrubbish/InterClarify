# `scripts/remote/moss_tts_patch.py`

## 功能与边界

MOSS-TTS-Realtime 的**运行时吞吐补丁**。上游 checkout 被 `configs/xtalk_round1.yaml` 的 `sources.moss_source.commit` 固定，且 `run_xtalk_round1.py` 在启动前会断言 `git diff --quiet`，因此不能直接改上游源码；本模块通过启动期注入的 `sitecustomize` 在 `mossttsrealtime.streaming_mossttsrealtime` **导入完成后**给类打补丁。默认三个开关全关时行为与上游逐位一致。

打补丁的目标类与位置（实测确认）：

- 热路径是 `mossttsrealtime/streaming_mossttsrealtime.py` 里的 **`MossTTSRealtimeInference`**（`MossTTSRealtimeStreamingSession` 只缓冲文本并转发 `prefill`/`step`/`finish`）。
- 每个音频帧 = 1 次 backbone 前向 + **16 次 local transformer 前向**（`rvq=16`，逐码本串行）+ 采样；编解码帧率 24000/1920 = **12.5 Hz**（每帧 80ms 音频）。
- 上游只在非 flash-attention 路径编译这个循环（`_should_compile_local_transformer = not _use_dynamic_local_cache`），所以我们的 `attn_impl=flash_attention_2` 部署是全 eager。

## 两个开关

| 环境变量 | 取值 | 作用 |
| --- | --- | --- |
| `XTALK_TTS_LOCAL_COMPILE` | `off`（默认）/ `inductor` / `cudagraph` | T1：用 `_local_loop` 替换码本循环。该实现把 local cache 与 `cache_position` 交给调用方持有，循环体内不再构造 Python 对象；`inductor` 用 `torch.compile(mode="default")`，`cudagraph` 用 `mode="reduce-overhead"` 捕获 CUDA 图。首次会话做一次 warmup（把 16 个码本形状全部捕获），失败则回退 eager 并记日志 |
| `XTALK_TTS_SAMPLE` | `upstream`（默认）/ `greedy` / `topk` | T2：替换 `sample_token`。`greedy` 一次 `argmax`；`topk` 先取 top-k（默认 k=30）再在 k 个候选上做 nucleus，避免对全词表 `sort` |
| `XTALK_TTS_METRICS` | `0`（默认）/ `1` | 每回合输出一行 `[tts-metric] … frames=… audio_s=… wall_s=… rtf=…`，帧计数始终启用，两个杠杆不启用 |

## 结构

- `install()`：插入 `_PatchFinder`（meta-path 包装器），使目标模块 `exec_module` 之后立刻调用 `apply_patch`；并把本模块 logger 提到 INFO 且 `basicConfig` 兜底（服务在 uvicorn 下默认只显示 WARNING，否则指标行不会出现在服务日志里）。
- `_local_loop(model, cache, cache_positions, hidden_states, output_token, history, history_filled, …)`：码本循环的忠实重实现，供 eager 与编译两条路径共用，因此 A/B 各 arm 只在执行后端上不同。
- `_attach(inferencer)`：挂载滑动窗口（`_HISTORY_CAPACITY = 128`，右对齐、只保留最近 `repetition_window` 帧）、`cache_positions` 复用张量、编译 runner 与指标计数。
- `_push_history`/`_record_frame`/`_log_metrics`：窗口维护与每回合指标；`prefill` 重置、`step` 追加、`finish`/`end_text`/`drain` 各报告一次（帧数归零保证一回合只出一行）。
- `apply_patch(module)`：替换 `MossTTSRealtimeInference` 的 `__init__`/`generate_local_transformer`/`prefill`/`step`/`finish`/`reset_generation_state`（以及会话的 `end_text`/`drain` 用于指标），`greedy`/`topk` 时再替换 `sample_token`。

## 正确性与验证

`tests/test_moss_tts_patch.py` 用确定性的假 local transformer，把 `_local_loop` 与**真实上游** `_generate_local_transformer_impl` 在同一输入上对比（无惩罚、有惩罚、窗口饱和三种），要求逐 token 相等；另覆盖采样档位形状/候选集、滑动窗口右对齐与有界、指标行、以及"假模块被 import hook 打补丁"。torch 不可用的环境整文件 skip。

## 用法

由 `scripts/remote/run_xtalk_round1.py` 的 `serve tts` 自动注入；A/B 由 `run_tts_throughput_ab_node_job.sh` 驱动。手工验证：

```bash
XTALK_TTS_LOCAL_COMPILE=cudagraph XTALK_TTS_SAMPLE=greedy XTALK_TTS_METRICS=1 \
  bash scripts/remote/run_xtalk_round1.py --config configs/xtalk_round1.yaml \
  --model-root "$XTALK_ROUND1_MODEL_ROOT" serve tts --gpu-index 0
```

## 注意

- 只支持单会话（batch size 1）——服务即为该配置；重复惩罚按批内每一行 gather/scatter，逻辑与上游一致。
- 压缩 arms 会**改变音频内容**（贪心/top-k 采样与上游不同），吞吐提升不等于质量通过，须试听 `warm/tts.wav`。
- 编译 arms 若报 `torch.compile … failed` 或 `falling back to eager`，该 arm 只反映回退后的 eager 性能。
