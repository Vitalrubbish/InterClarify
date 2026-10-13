# DuplexCascade 标记探针任务单

## 1. 目的与范围

回答一个诊断问题：`user_interruption` 轴上模型为什么不吐 `<|user interruption|>`？

背景见 [A4 任务单 §9.2](xtalk_a4_remote_acceptance.md)：`user_interruption` 五个样本的官方 judge 平均分 0.6（TOR 1.0、latency 1.536s），4/5 样本被打断后仍在念旧答案，原因是模型只吐了 `<|user backchannel|>`（官方语义下不 reset），只有样本 102 吐了 `interruption`。而 `<|user backchannel|>` 只 flush 不 reset 是**官方设计**的一部分，因此该失败不能用"我们偏离了官方"解释。

本探针要区分两种仍有意义的原因：

1. **文本流形态**：我们交给模型的文本带句子标点与大小写、按 0.6s 累积前缀差分、并按 `REWRITE` 回写历史；官方 demo 用流式 STT 的逐词流。
2. **上游能力**：DuplexCascade 权重本身对"打断 vs 附和"的判别在这些输入上不稳（全轮次 25 个会话只吐过 4 次 `interruption`）。

范围：**只加诊断**。不改官方脚本、不改运行时行为、不动 reset 语义、不引入策略偏离。判定为"文本流是病灶"之后才讨论是否改运行时。

## 2. 方法

重放已录制的 ASR 微轮，而不是重跑音频链路：

- 输入：某次 A4 run 的 FDB `user_interruption` 样本目录（含 `a4_report.json` 的 `update_asr` 事件与 `interrupt.json`）。
- 时钟：默认 0.6s 固定网格（`--clock grid`），保证所有变体看到完全相同的 `delta` 序列。
- 变体：`raw`（对照，等于运行时）、`strip`（去句子标点）、`strip_lower`（再去大小写）。
- 每拍按 `DuplexRuntimeAdapter` 的方式调用官方模型服务：user 微轮送文本（空即 `<|no voice|>`），assistant 微轮送回生成的 token id。

归一化只作用于 wire 边界，内部前缀/差分/`REWRITE` 回写保持不变——与将来真正要落的改动一一对应。

复刻时最容易写错的一处：`REWRITE` 会把新前缀按字符数重新分配到**已发出的** user 微轮上，只有剩下的尾巴才是本拍新增微轮；初版探针在这里多发了一遍整句，导致 `raw` 变体产生了生产中不存在的 `interruption`，整轮作废。保真度实测到的另一个坑是时钟相位（生产时钟会吸收生成耗时），详见 §5.1。

## 3. 提交与运行

```bash
export INTERCLARIFY_DUPLEX_ROOT=/mnt/cloudstorfs/sjtu_home/xuan.zhang/InterClarify
export DUPLEX_PROBE_TAG=<UTC-tag>
export DUPLEX_PROBE_SAMPLE_ROOT=$INTERCLARIFY_DUPLEX_ROOT/data/runs/20261013T070801Z/fdb/user_interruption/synthetic_user_interruption
export DUPLEX_PROBE_SAMPLES=1,10,100,101,102
export DUPLEX_PROBE_VARIANTS=raw,strip,strip_lower
bash scripts/remote/submit_duplex_probe_job.sh
```

- 提交前自检（本机、不占 GPU）：加 `--dry-run` 直接跑 `probe_duplex_markers.py`，确认时钟与 `delta` 序列合理。
- 资源：1×4090（模型 bf16 7B，峰值显存约 16.5 GiB，11 GiB 卡放不下）、8 CPU、32G 内存（单 GPU 作业的调度上限）。
- 作业可能被 LowGpuUsage 策略打断；探针全程占用 GPU，只需关注模型加载阶段不要过久。

## 4. 产物

- `data/runs/duplex_marker_probe/<tag>/`：`duplex_marker_probe.json`（逐拍）、`.summary.json`（紧凑）、`probe.log`、`services/duplex_model.log`、`model_health.json`。
- `reports/duplex_marker_probe/<tag>/`：紧凑归档，入库。

## 5. 判读标准

### 5.1 探针保真度实测到的两个坑

1. **网格相位**：运行时的时钟在生成慢于间隔时会被推迟（`next_tick = max(now, next_tick + interval)`）。实测生产的首个请求可能要 5s 以上（预热），样本 101 全程只走了 32 拍而纯网格是 46 拍。因此 `--clock grid` 无法逐拍复现生产，`reproduced_matches_recorded` 只能当参考；精确复现需要用**录制下来的每拍耗时**驱动时钟（`services/duplex_model.log` 每条请求都有 `seconds`/`prompt_tokens`，但会话→样本映射在"同为 N 拍"的样本间存在歧义，例如样本 1 与 10 都是 44 拍，须靠答案文本或标记形状消歧）。
2. **`REWRITE` 剩余量**：见上文"容易写错的一处"。初版探针在这点上写错，导致 `raw` 变体产生了生产中不存在的 `interruption`，整轮结果作废。

因此本探针的结论按可信度分两层：**变体之间的相对比较**（同一相位下）可直接采信；**与生产绝对行为的一致性**需要 5.1.1 的精确时钟或"保留 timelines 的重跑"来支撑。


1. **先看保真**：`raw` 的 `reproduced_protocol_tokens` 是否复现 `recorded_protocol_tokens` 的标记模式。网格相位与运行时不必逐拍相同，因此 `reproduced_matches_recorded` 可能为 false；若连标记模式（如 `talking, finish talking, backchannel×N`）都不复现，本探针的结论只能作为**方向性**证据，须回退到"保留 timelines 后重跑"。
2. **再看变量**：同一 `sample` 下 `raw` 与 `strip`/`strip_lower` 的 `markers_after_interrupt`：
   - 出现 `interruption`/`talking` → 标点/大小写是真实病灶，按 §6 落地归一化；
   - 仍只有 `backchannel` 或空 → 标点这条线作废，**不改代码**，转去找其它未验证环节（见 §6 修正与 §7）。
3. `text_after_interrupt` 判断翻标记之后是否真的换了话题（对应官方 judge 的评分对象）。

## 6. 结果（2026-10-13，tags `20261013T111116Z` / `20261013T111925Z` / `20261013T121244Z`）

样本：`user_interruption` 的 1/10/100/101/102。判据：打断窗口内是否出现 `<|user interruption|>`，以及打断之后模型是否给出新话题文本。

**保真**：`raw` 与生产录制逐标记一致的有 10/100/102——**包括 10/100 的"无 interruption"失败和 102 的"有 interruption"成功**；样本 1 多出 1 个尾随 `<|user is thinking|>`，样本 101 多出 14 个（101 的生产时钟被 TTS 回调阻塞、只走了 33 拍，网格无法对齐，见 §5.1）。

| 样本 | 生产录制 | `raw` | `strip` | `strip_lower` | `burst` |
| --- | --- | --- | --- | --- | --- |
| 1 | backchannel×3 | ✗（+1 thinking） | ✗ | ✗ | **✓** 12.63s，答"理财目标" |
| 10 | backchannel | ✗（逐标记一致） | ✗ | ✗ | ✗ |
| 100 | backchannel×2 | ✗（逐标记一致） | ✗ | ✓ 12.63s → 19 连 thinking（文本是收尾句） | ✗ |
| 101 | backchannel×2 | ✗（14 连 thinking） | ✓ 13.24s → 24 连 thinking（无文本） | **✓** 13.24s，干净，答"修水龙头" | ✗ |
| 102 | interruption ✓ | ✓（逐标记一致） | ✓ | ✓ | **✗ 反而丢掉 interruption** |

**稳定性**：`raw`、`strip_lower`、`burst` 各重跑 2 次，重复之间逐标记完全相同 → 同一输入下贪心解码是确定的；上表的差异是**文本驱动的真实效应**，不是随机噪声。

**结论**：

1. 标点、大小写、碎片粒度**确实能确定性地改变**打断判定，"标点完全不相关"这个说法不成立。
2. 但**没有任何变体构成修复**：三种变体各只救一个样本（`raw`→102、`strip_lower`→101、`burst`→1），且互相抵消（`burst` 让 102 丢掉本来可用的 interruption；`strip_lower` 让 100 退化成 19 连 `thinking`）。打断前的 `talking → finish talking` 在所有变体里都稳定，唯一致命的就是打断分类本身。
3. 因此**不做任何文本归一化改动**：归一化既不构成修复，也不是缺失的修复。`<|user is thinking|>`/`<|user is talking|>` 的长连吐（14–24 次）与打断分类是同一类判定不稳的表现。

**修正（同日）**：上游仓库自带的 Full-Duplex-Bench 结果表显示，DuplexCascade 在同一 `synthetic_user_interruption` 子集上拿到 **TOR 0.955 / GPT-4o 4.016 / latency 1.225**，而我们是 1.0 / 0.6 / 1.536。所以"上游能力不足"不成立，退化的根因**仍未定位**，差异只可能在我们这条输入链路，最可疑的是模型唯一的输入——ASR 文本流（本探针只对它做变换，结构上测不出这一点）。本节的第 2、3 条结论仍成立（归一化不是修复），但不可据此把责任推给上游。下一步见 [A4 任务单 §9.2](xtalk_a4_remote_acceptance.md) 的待验证路径。

**追加实验：真值词流（同日，tag `20261013T121244Z`）**。把用户侧流整体换成 FDB 自带的真值句子（`truth` 去标点、`truth_punct` 保留书面标点；context 按录制跨度铺开、interrupt 按 `timestamp[0..1]` 逐词铺开；历史严格单调、不触发 `REWRITE`），同作业跑 `raw` 作对照：

| 样本 | `raw`（对照） | `truth` | `truth_punct` |
| --- | --- | --- | --- |
| 1 | backchannel×3（+1 尾随 thinking） | backchannel | backchannel |
| 10 | backchannel（逐标记一致） | **42 连 talking，彻底退化** | **interruption ✓** |
| 100 | backchannel×2（逐标记一致） | backchannel×6 + thinking | backchannel×6 + thinking×3 |
| 101 | backchannel×2 + 14 连 thinking | backchannel×7 + thinking | backchannel×6 + thinking |
| 102 | **interruption ✓**（逐标记一致） | **46 连 talking，反而丢掉** | interruption ✓ |

**结论（重要）**：**真值词流同样不构成修复**，且翻转方向两边都有（样本 10 只在带标点时翻；样本 102 在去标点时反而退化）。这排除了"我们的 ASR 用词 / 标点 / 大小写 / 碎片粒度"这一整类解释——模型在"自己作答中途收到一句插问"这一输入类上的判定本身不稳。因此病因仍在未与官方对齐的环节：官方 STT（Kyutai `delayed-streams-modeling`，逐词流、自带延迟）的**词到达时序**，或该输入类上的固有不稳。下一步见 [A4 任务单 §9.2](xtalk_a4_remote_acceptance.md)。

**机制线索：判定由"模型自身是否已在说话"主导（同日，tag `20261013T121244Z`）**。把 15 个"样本×变体"按"打断到达那一刻**之前**模型已生成的答案词数"分组，与打断那拍的标记对照：

| 打断前已生成的答案文本 | 打断那拍的标记 | 计数 |
| --- | --- | --- |
| **0 词**（尚未开口） | `talking`（`102 raw` 随后走到 `finish talking → interruption`） | 3/3 |
| **72–103 词**（已在说话） | `backchannel` | 10/11（唯一例外 `10 truth_punct` 给 `interruption`） |

| 样本 | `raw` 打断前答案 | `raw` 打断标记 | `truth` | `truth_punct` |
| --- | --- | --- | --- | --- |
| 1 | 103 词 | backchannel | 85 词 → backchannel | 85 词 → backchannel |
| 10 | 93 词 | backchannel | **0 词 → 全 `talking`** | 72 词 → **interruption** |
| 100 | 92 词 | backchannel | 76 词 → backchannel | 74 词 → backchannel |
| 101 | 102 词 | backchannel | 96 词 → backchannel | 83 词 → backchannel |
| 102 | **0 词** | **interruption ✓** | 0 词 → 全 `talking` | 78 词 → backchannel（后转 interruption） |

结论：**主导线索是模型自身的说话状态**——"我在说话时对方出声"默认解释为附和（继续讲）；只有尚未开口时才把新用户文本当作夺轮内容。样本 102 之所以是唯一成功案例，是因为它在打断到达前 18 拍都是 `talking`（没有开口）；其余四个样本都在约 3s 就答完了上下文问题（`first_audio_seconds` = 2.6–3.3s），打断（9.2–9.8s）必然落在"我正在说话"的窗口内。这也解释了该轴几乎必挂的**结构性**原因：FDB 合成打断固定落在上下文问题结束后约 4s，而本链路 3s 就开口且答案很长。副产品：`raw`/`truth`/`truth_punct` 三个变体在"是否已开口"上分叉（如样本 10、102），正是此前观察到的"文本形态能双向翻转判定"的来源。

**时序量测（同日，排除"ASR 比用户输入慢"）**：用 FDB 逐词时间戳（`transcription.json`，15 个样本）与音频能量端点比对 `update_asr` 到达时刻：

- 更新间隔**中位数 0.61s**（每拍一条），无卡顿；`user_interruption` 里唯一的长间隔（7.3–9.1s）是上下文问题与打断之间的静音。
- 末条文本 − 语音实际结束 = **−0.53 ~ +0.95s**（多数 +0.1~0.3s），逐词延迟 0.0–0.6s 且不累积 → 延迟就是"0.6s 分块 + 推理"的地板，**ASR 不落后**。
- 上下文问题的语音在 **2.3–2.7s** 就结束（`context.wav` 长 5.2s，其余为静音），模型 2.6–3.3s 开口属**准时**；打断语音落在 9.3–13.4s，此时样本 1/10/100/101 已连续说话 **5.9–7.0s**，而 102 为 **−5.0s（尚未开口）**。
- 因此该轴失败**无法**由"ASR 太慢"解释：在"已开口→附和"的规则下，推迟用户文本只会更糟、提前也救不回来；要翻转只能让模型在那拍不处于说话状态，或提供尚未复刻的判别线索（官方 STT 逐词流形态）。

**另一条独立输入噪声**：ASR 的首条文本可能是乱码——`synthetic_user_interruption/100` 首条为中文 `我。`，模型据此回了"To provide a comprehensive answer, it would be helpful if you could specify the context or topic..."。

## 7. 假如将来仍判定需要落地（本轮未采用）

若后续（例如换用更接近官方 STT 的逐词流、或改变打断检测的责任归属）证明文本形态确实是稳定病灶，可按下列方式落地：

- 位置：`xtalk/src/xtalk/duplex_control/runtime_adapter.py` 的 wire 边界，只在构造 `_request_history()` 的 user 文本时归一化。
- 保持：内部前缀、`prefix_version`、`REWRITE` 回写仍用原始 ASR 文本（回写按字符数切分，不能被归一化打断）。
- 效果：归一化后为空的微轮变成 `<|no voice|>`，与官方逐词流"没有新词"的形态一致。
- 开关：`duplex_normalize_user_text`（默认值由本探针结论决定），大小写单独一档便于回滚。
- 依赖同步：X-Talk 单测（标点-only → no_voice、`REWRITE` 计数不变、`prefix_version` 不变）与 `docs/src/xtalk/duplex_control/runtime_adapter.md`(+`.zh.md`)。

## 8. 本轮明确不做

- 不改官方 `server.py`、官方评分脚本与 reset 语义。
- 不加"被打断必须让出话轮"之类的策略规则（那是对官方语义的显式偏离，属产品决定）。
- 不做 `burst` 之外的粒度实验（如逐词流复刻）；`burst` 变体已实现，可在同一作业里用 `DUPLEX_PROBE_VARIANTS` 追加。
