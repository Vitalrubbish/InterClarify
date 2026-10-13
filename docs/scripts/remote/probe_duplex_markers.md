# `scripts/remote/probe_duplex_markers.py`

## 功能与边界

把一段**已录制**的 ASR 微轮序列重新喂给官方 DuplexCascade 权重，用来隔离一个变量：交给模型的那份文本长什么样（句子标点、大小写、碎片粒度），会不会改变它吐出的 interleave 标记（`<|user is talking|>` / `<|user finish talking|>` / `<|user interruption|>` / `<|user backchannel|>`）。

它是**纯文本闭环**：不读音频、不启 ASR/TTS，只从样本目录的 `a4_report.json` 里取 `update_asr` 事件（时间 + 累积文本），按运行时的 0.6s 微轮时钟重放，并完全按 `DuplexRuntimeAdapter` 的方式调用官方模型服务（每拍发一条 user 微轮 + 累积的 assistant token id，取回生成 token id 再塞回历史）。

边界：它只做诊断，不参与验收判据，也不改运行时行为。

## 复刻的运行时语义

重放严格照抄两处纯逻辑，改动其中任何一处都必须同步本脚本：

- `MicroTurnAssembler.flush` / `_accept_asr`：`delta` 由累积前缀差分得到，前缀被改写时记为 `REWRITE`；
- `DuplexRuntimeAdapter._append_user`：`REWRITE` 时按字符数把**已发出的** user 微轮逐段替换（官方没有这个回写行为，因此它本身也是被观察对象）。

`_request_history()` 的 wire 形态（user 送文本、assistant 送 token id）与 `duplex_model_service.py` 的 `<|no voice|>` 渲染规则保持一致。

**容易写错的一处**：`REWRITE` 时 `_append_user` 先把新前缀按字符数**重新分配到已发出的** user 微轮上，只有分配后剩下的尾巴才作为本拍新增微轮；早先版本的探针错把整个前缀又发了一遍，等于让模型看到问句重复（表现为答案复用被改写掉的旧措辞），整轮结果作废。改动这里必须与 `runtime_adapter.py` 同步。

## 变体

| 变体 | 效果 |
| --- | --- |
| `raw` | 与运行时完全一致，用作保真对照 |
| `strip` | 去掉句子级标点与引号（保留 `'`、`-`、数字），折叠空白，保留大小写 |
| `strip_lower` | 在 `strip` 基础上再转小写 |
| `burst` | 累积到 ≥3 词才作为一条 user 微轮发出，模拟"词成串到达"，不在 `REWRITE` 时回写历史 |
| `truth` | **不看录制的 ASR 文本**，改用 FDB `interrupt.json` 的真值句子：context 按录制跨度铺开、interrupt 按声明的窗口 `timestamp[0..1]` 逐词铺开；去标点，形如流式 STT 的词流 |
| `truth_punct` | 同 `truth`，但保留元数据里的书面标点（凑成"真值词 × 有无标点"的 2×2 对照） |

归一化只作用于**送给模型的文本**（wire 边界），内部前缀、差分与 `REWRITE` 回写仍按原始文本进行。

## 类设计与核心方法

- `normalize(text, variant)`：单个微轮的文本归一化；归一化后为空即变成 `<|no voice|>`。
- `MarkerReplay`：一次会话的重放器。`accept()` 更新可见前缀，`flush()` 产出一条 user 微轮，`wire_history()` 组装请求体，`tick()` 发一次生成并记录该拍的 `delta`/`wire_text`/`markers`/`text`/`token_ids`/`prompt_tokens`/耗时。
- `asr_stream(report)`：从 `a4_report.json` 抽 `(seconds, text)`。
- `replay_sample(...)`：跑完一个样本，返回录制标记与重放标记、逐拍日志、以及打断结束之后的文本。
- `main()`：对每个样本 × 每个变体重放，写完整结果与 `.summary.json`。

## 时钟

`--clock grid`（默认）固定 0.6s 网格：所有变体看到完全相同的 `delta` 序列，A/B 不受生成耗时漂移污染。`--clock absorbed` 让生成耗时顺延下一拍，更接近运行时在推理慢于间隔时的行为，但不同变体之间会产生相位差，只用于单变体保真对照。

## 用法

```bash
conda run --no-capture-output -n xtalk-round1-client python scripts/remote/probe_duplex_markers.py \
  --sample-root data/runs/<tag>/fdb/user_interruption/synthetic_user_interruption \
  --model-url http://127.0.0.1:8006 \
  --variants raw,strip,strip_lower --clock grid \
  --out data/runs/duplex_marker_probe/<probe-tag>/duplex_marker_probe.json
```

`--dry-run` 只重放时钟与 `delta`，不调模型，用于提交前自检（本机即可跑）。其余参数：`--samples`（逗号分隔样本名，默认全部）、`--interval`（默认 0.6）、`--max-new-tokens`（默认 64）、`--repeats`（同一变体重跑次数，用来暴露贪心解码在同输入上的不稳定性，结果标记为 `raw#1`、`raw#2`）。

## 产物

- `<out>`：完整逐拍日志（每个样本每个变体）、录制标记、重放标记、打断后文本。
- `<out>.summary.json`：去掉逐拍明细的紧凑版，供归档。

## 判读

1. **保真对照**：先看 `raw` 的 `reproduced_matches_recorded` 与 `reproduced_protocol_tokens`。网格相位与运行时不同，逐标记完全一致不保证；但若 `raw` 复现出同样的标记模式（如 `talking → finish talking → backchannel …`），说明重放可信。
2. **变量判定**：比较同一 `sample` 下 `raw` 与 `strip`/`strip_lower` 的 `markers_after_interrupt`。若打断轮从 `backchannel` 翻成 `talking`/`interruption`，则标点/大小写是真实病灶；若完全不翻，则归因转向上游权重的标记判别能力，不再改运行时。
3. `text_after_interrupt` 用来判断翻标记之后，模型是否真的在回答新问题。
