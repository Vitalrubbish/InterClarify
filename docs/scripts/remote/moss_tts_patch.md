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
| `XTALK_TTS_LOCAL_COMPILE` | `off`（默认）/ `inductor` / `cudagraph` | T1：用 `_local_loop` 替换码本循环。该实现把 local cache 与 `cache_position` 交给调用方持有，循环体内不再构造 Python 对象；`inductor` 用 `torch.compile(mode="default")`，`cudagraph` 用 `mode="reduce-overhead"` 捕获 CUDA 图。首次会话做一次 warmup（用**该帧真实的** hidden state、采样标量与绑定的 `sample_token`，保证编译图与后续帧一致），失败则回退 eager 并把 traceback 记进日志 |
| `XTALK_TTS_LOCAL_ATTN` | `upstream`（默认）/ `sdpa` | 只把 **local transformer** 的注意力换成 sdpa，并把它的本地 cache 换成静态 cache（`_use_dynamic_local_cache=False`，即上游编译路径用的那种），backbone 仍是 flash-attn。**编译它的前提**：flash-attn 的 helper 用 `position_ids` 的**张量值**选 varlen 分支（`modeling_flash_attention_utils._flash_attention_forward`），而 local transformer 是"1 个 query × 17 个 key、无 attention mask"，该分支既会被走到又数据相关，`fullgraph=True` 无法 trace（`Data-dependent branching`）。sdpa 是单个可 trace 的 kernel，且这个尺寸下比 flash-attn 包装更便宜 || `XTALK_TTS_SAMPLE` | `upstream`（默认）/ `greedy` / `topk` | T2：替换 `sample_token`。`greedy` 一次 `argmax`；`topk` 先取 top-k（默认 k=30）再在 k 个候选上做 nucleus，避免对全词表 `sort`；`do_sample=False` 或 `temperature=0` 时三种档位都退化为 argmax（与上游一致） |
| `XTALK_TTS_METRICS` | `0`（默认）/ `1` | 输出 `[tts-metric] … frames=… audio_s=… wall_s=… rtf=… local_s=… backbone_s=… local_pct=…`。**限速**：满 `_METRIC_MIN_FRAMES=6` 帧（0.48s 音频）或 `_METRIC_MIN_WALL_SECONDS=1.0` 才出一行，`end_text` 强制收尾一行；每行只统计"自上一行以来"的帧与墙钟，因此汇总要**求和**而不是取某一行 |
| `XTALK_TTS_PROFILE` | 空（默认）=关闭 | 把每回合前 `XTALK_TTS_PROFILE_FRAMES`（默认 60）帧的 `torch.profiler`（CUDA activities）逐 kernel 表**追加**写到该路径，并额外打一行机器可读的 `[moss-patch] profile frames=… device_s=… cpu_s=… top=<kernel>:<秒>:<次数> | …`。profiler 在 TTS 服务进程内运行，因此同一回合同时覆盖模型与 codec 解码；表头记录回合号与已剖析帧数。剖析会拖慢这些帧，其 rtf 不可当读数，只看 device/cpu 与 top kernel |
| `XTALK_TTS_PROFILE_FRAMES` | `60` | 每回合剖析的帧数上限 |

## 部署默认值

补丁自身三个开关默认全关（对上游零影响、可随时关闭）。**产品化默认值在配置里**：`configs/xtalk_round1.yaml` 的 `services.tts.local_attn: sdpa` + `local_compile: inductor`，`serve tts` 启动 TTS 服务时把它们转成上面的环境变量（环境中已显式设置则以环境为准；已清理的单卡吞吐 A/B 正是靠这一点逐臂改一个变量）。2026-10-15 在 4090 上的实测：每帧 75.0ms → 35.0ms（2.14×），稳态 rtf 1.06 → 2.25；首次编译 43.6s，A4 作业在 TTS 健康检查后用 `tts_warmup` 预热把它挪到启动阶段（见任务单 §9.6.7）。

## 结构

- `install()`：插入 `_PatchFinder`（meta-path 包装器），使目标模块 `exec_module` 之后立刻调用 `apply_patch`；并把本模块 logger 提到 INFO 且 `basicConfig` 兜底（服务在 uvicorn 下默认只显示 WARNING，否则指标行不会出现在服务日志里）。当 `XTALK_TTS_LOCAL_COMPILE != off` 时调用 `relax_dynamo_logging()`：把 `logging.Logger.warning_once` 等标准方法加进 `torch._dynamo.config.ignore_logger_methods`，否则 transformers 在 flash-attn 里的一次 `warning_once` 会让 `fullgraph=True` 直接失败。
- `_local_loop(model, cache, cache_positions, hidden_states, output_token, history, history_filled, …, do_sample, sample_token, mode)`：码本循环的忠实重实现，供 eager 与编译两条路径共用，因此 A/B 各 arm 只在执行后端上不同；`mode="upstream"` 时把采样原样交回上游 `sample_token`。
- `_compile_target(capacity, repetition_window)`：编译路径的**饱和门**——重复惩罚只回看最近 `repetition_window` 帧，所以窗口填满 `min(capacity, repetition_window)` 帧后，编译调用里的每个参数都是常量（每会话一张图，而不是每个帧数一张图）。
- `_attach(inferencer)`：挂载滑动窗口（`_HISTORY_CAPACITY = 128`，右对齐、只保留最近 `repetition_window` 帧）、`cache_positions` 复用张量、编译 runner、CUDA event 列表、profiler 与指标计数；`XTALK_TTS_LOCAL_ATTN=sdpa` 时先调 `switch_local_attention`，开启指标时用 `_wrap_backbone` 包住 backbone 的 `forward` 以单独计时。**backbone 的 event 列表挂在 model 上**：服务每回合新建 inference 对象而 model 共享，挂在对象上会让第一个回合之后的 `backbone_s` 恒为 0。`inference ready` 行记录 `attention=`，作为该 arm 是否真的换了注意力的证据。
- `switch_local_attention(inferencer)`：把 local transformer 的 `config._attn_implementation` 设为 `sdpa`、`_use_dynamic_local_cache` 设为 `False`（静态本地 cache）、`_should_compile_local_transformer` 设为 `False`（后端由本补丁的开关决定）。
- `_push_history`/`_record_frame`/`_log_metrics`/`_reset_metrics`：窗口维护与指标切片；`prefill` 先复位窗口与计数器再跑上游（prefill 内部就会生成新回合的第 1 帧），`step` 追加帧，`finish`/`drain` 出限速行，`end_text` 强制收尾并关闭 profiler。`_timed_call`/`_consume_events` 用 CUDA event 累加"本地码本循环"与"backbone 前向"的秒数。
- `apply_patch(module)`：替换 `MossTTSRealtimeInference` 的 `__init__`/`generate_local_transformer`/`prefill`/`step`/`finish`/`reset_generation_state`（以及会话的 `end_text`/`drain` 用于指标），`greedy`/`topk` 时再替换 `sample_token`。编译路径**真正被走到**时打印一次 `compiled path engaged frame=… filled=… target=…`。
- 关键日志（用于判定 arm 是否有效）：`torch.compile(_local_loop) ready`（图建好）、`compiled warmup done in …s`（warmup 通过）、`compiled warmup failed, falling back to eager: …` + traceback（回退）、`compiled path engaged`（编译路径被真实帧使用）。

## 正确性与验证

`tests/test_moss_tts_patch.py` 用确定性的假 local transformer，把 `_local_loop` 与**真实上游** `_generate_local_transformer_impl` 在同一输入上对比（无惩罚、有惩罚、窗口饱和三种，另加经 `sample_token` 派发一种），要求逐 token 相等；另覆盖采样档位形状/候选集与 `do_sample=False` 退化、滑动窗口右对齐与有界、`_attach` 必须定义热路径读取的每个字段、饱和门取值、CUDA event 记账、限速指标行、profiler 开关与落盘、`relax_dynamo_logging`，以及"假模块被 import hook 打补丁"。torch 不可用的环境整文件 skip。

## 用法

由 `scripts/remote/run_xtalk_round1.py` 的 `serve tts` 自动注入；原单卡吞吐 A/B（已随 2026-10-15 清理移除，数字见任务单 §9.6.7）按 arm 逐个覆盖环境变量。手工验证：

```bash
XTALK_TTS_LOCAL_COMPILE=cudagraph XTALK_TTS_SAMPLE=greedy XTALK_TTS_METRICS=1 \
  bash scripts/remote/run_xtalk_round1.py --config configs/xtalk_round1.yaml \
  --model-root "$XTALK_ROUND1_MODEL_ROOT" serve tts --gpu-index 0
```

## 注意

- 只支持单会话（batch size 1）——服务即为该配置；重复惩罚按批内每一行 gather/scatter，逻辑与上游一致。
- 压缩 arms 会**改变音频内容**（贪心/top-k 采样与上游不同），吞吐提升不等于质量通过，须试听 `warm/tts.wav`。
- 编译 arms 若报 `torch.compile … failed` 或 `falling back to eager`，该 arm 只反映回退后的 eager 性能；**没有** `compiled path engaged` 的 arm 同样不是编译后的成绩（例如合成太短、窗口未饱和）。
- 服务每帧调用一次 `finish`（`drain(max_steps=1)`），因此指标行必须按"行内增量"读、跨行求和；单行 `rtf` 会高度抖动。
- profiler 只剖析每回合最初的固定帧数，会略微拖慢这些帧；请只把它当作时间构成证据，不要拿它的绝对吞吐当读数。
- `local_s`/`backbone_s` 是 CUDA event 之间的**墙钟**（含"CPU 发不出活导致 GPU 空转"的空隙），不是 kernel 执行时间；两者都能对上时说明这几段占了整帧墙钟的大头，真正的 device 时间要看 profile 臂的 `device_s`/`device/帧`。2026-10-14 在 4090 上实测：baseline 每帧墙钟 ≈75ms、device ≈24ms（其中 1-token GEMV 47%、633 次 kernel/帧），即约七成帧时间在等 CPU 派发；启用 sdpa + 编译码本循环后每帧降到 ≈35ms（本地 13.3ms + backbone 18.3ms + codec/其他 ≈3ms）。

## 2026-10-17 开头编译实验准备

新增 `XTALK_TTS_EARLY_COMPILE=1`，默认关闭。`_apply_history_penalty` 使用固定形状窗口与设备上的有效长度，按词表计数掩码施加惩罚；无效填充不会惩罚 token 0，重复 token 不会多次叠加惩罚。`_local_loop` 增加可选有效长度张量，旧调用保持原逻辑。实验路径覆盖首帧与未满窗口，逻辑历史每轮复位。编译缓存按后端与实验开关分隔；warmup 覆盖无惩罚和带掩码两条路径，并保存/恢复采样 RNG。记录 eager/compiled 帧数和前 1/5/10/50 帧墙钟。编译失败可观测地回退。尚未通过远端数值、性能与音质验收，默认路径不变。

`relax_dynamo_logging` 仅加入实际存在的 `warning_once` 扩展，兼容没有导入 transformers 的 CPU 检查。trace 开启时，`_log_early_frame` 逐帧记录关联的 eager/compiled 计数；该 CPU 时间包含预热，应与独立 warmup/热态结果区分。

原 CUDA event 切片在 trace 开启时同步输出 `gpu.slice` 关联事件（仍仅消费已完成 event，不执行全局同步）；pending 数量保留，末尾尚未完成的时间不伪装为零开销。

失败边界：构建 runner 与 warmup 失败会记录 traceback 并回退 eager；正式帧执行若失败则由原服务记为响应失败，不盲目重放可能已推进的 RNG/KV。运行期重编译检测与此类错误的恢复仍需远端验证，不视为 TTS-003 已验收。
