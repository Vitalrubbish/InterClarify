# X2 单帧流式探针

对应 `scripts/remote/x2_streaming_probe.py`。本脚本只回答“X2Streaming-ASR 能否在 16kHz、80ms 一帧、12.5Hz 的节拍下跑满实时”，不启动 SoulX、不写教师帧、不改状态规则。模型权重、处理器参数和门槛由 `configs/x2_streaming_probe.json` 冻结。

## 首块合同

首块用 3.36s 确定性合成音（220Hz 正弦叠固定噪声）自检，断言：

- 首块用户音频 9000 样本，用户音频预填 56 个 mel 帧；
- 处理器额外加入 32 个 streaming pad 对应的 256 个 mel 帧，因此送入模型的 `input_features` 是 `[1, 128, 312]`，`input_ids` 是 39 个 streaming pad；
- 之后每块 1680 样本、8 个 mel 帧，形状 `[1, 128, 8]`；
- 首次与第二次音频前向的卷积 padding cache 分别为 `conv1 [1,128,2]`、`conv2 [1,1280,1]`，第二次不改变形状。

上一轮失败的原因是把 `input_features[:, :56]` 当成时间切片，实际切掉了 128 个 mel 通道，导致 cache 的 `128` 与 `56` 不匹配。正确做法是完整送入首块 `[1,128,312]`；56 只是用户音频预填帧，不是张量总帧数。合同不通过时立即终止，不跑真实音频。

## 流式节拍

`StreamRun` 每次只向 `model.generate` 交付一个特征块，并让生成器在墙钟到达该块音频覆盖时刻后再产出下一块：

- 第 0 个 token 使用首块，覆盖用户音频 9000 样本（562.5ms）；
- 第 k 个 token（k≥1）使用从 `frame_index*hop-win//2` 开始的 1680 样本，新增 80ms 用户音频；
- 生成器用绝对起始时刻计算目标时间，因此计算慢于 80ms 时不会通过延后 `sleep` 把积压藏起来；
- 音频结束后补 8 个 80ms 静音帧（`flush_frames`），只为收尾输出和组闭合；这些 token 标为 `pad`，不计入实时门槛的 `x2_rtf` 与 `backlog` 分布。

`[P]`（id 32）与 `[W]`（id 33）按模型合同分组：`[W]` 开始一个词，遇到下一个 `[P]` 或 `[W]` 时闭合。没有前导 `[W]` 的文本 token 记为 `unbound`；流结束仍未闭合的组单独记录，不冒充已闭合词。

## 逐帧字段

每个 token 写入 `<case>.frames.jsonl`，包含：

- `frame`、`token_id`、`chunk_index`、`feature_shape`、`is_wait`、`is_word`；
- `wall_ms`：相对本流起点的墙钟；`feed_at`：该块特征交付时刻；
- `audio_frame_end_ms = (frame+1)*80`；
- `coverage_end_ms`：生成该 token 所需的音频覆盖端点；
- `frame_lag_ms = wall_ms - audio_frame_end_ms`，含模型算法延迟（约 482.5ms，6 帧 delay 加半个窗）；
- `decode_latency_ms = 产 token 时刻 - 该块特征交付时刻`，即该步真实计算耗时；
- `backlog_ms = wall_ms - coverage_end_ms`，即墙钟相对已覆盖音频的滞后；
- `pad`：该 token 对应音频结束后补的静音；
- `cumulative_text`、`delta_text`。

## 汇总与门槛

`summary()` 给出：

- `x2_rtf`：真实音频 token 的 `decode_latency_ms` 总和 / 音频时长；`x2_rtf_including_flush` 额外计入收尾静音；
- `frame_lag_ms`、`backlog_ms`、`decode_latency_ms` 的 P50/P95/max；
- 60s 流首尾 5 秒 `backlog` P50 与 `backlog_drift_ms`；
- 闭合组数、`[W]`/`[P]` 数、`unbound_tokens`、未闭合尾组；
- 组闭合延迟（帧数与墙钟）；
- 组闭合后被改写次数与示例；
- 文本乱序/回改次数与示例；
- `padding_cache` 调用次数、特征形状计数、峰值显存。

`evaluate_gate()` 同时检查：最大 `x2_rtf ≤ 0.6`、最大 `backlog_ms` P95 ≤ 320ms、60s 首尾漂移 ≤ 160ms、`peak_reserved_mib ≤ 12288`。任一条不满足时保留具体数值，`result.json` 的 `gate.checks` 指出失败项。

## 输入与输出

`--manifest` 必须是冻结的 30 条 FDB 清单；脚本逐条核对 `input.wav`、`pause.json`、`transcription.json` 的 SHA256，并按教师链路口径做 `min(0.05/rms, 0.9/peak)` 增益归一化。默认选择最长用例、`candor_pause_handling-16`、`candor_turn_taking-102`，再按清单顺序拼接 60s 连续流。

输出目录必须不存在，包含 `input_manifest.json`、`contract.json`、各用例 `frames.jsonl`、`result.json`，运行入口另存 `gpu_memory_mib.txt`、`source.sha256`、`model.sha256` 和 `exit_code.txt`。`--case` 只跑单条，`--skip-continuous` 跳过 60s 流，`--contract-only` 只做首块自检。
