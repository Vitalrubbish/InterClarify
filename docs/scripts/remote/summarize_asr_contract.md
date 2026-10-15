# `scripts/remote/summarize_asr_contract.py`

## 功能与边界

把 `run_asr_contract_ab_node_job.sh` 的逐臂事件流合成一份 Markdown/JSON 对照表。只读产物（`asr_events.jsonl`/`asr_report.json`），不加载模型、只用标准库。

## 口径

- `raw 改写` / `可见改写`：事件流里 `rewritten` / `visible_rewritten` 的计数。前者是官方 demo 口径下的改写，后者是我们交给运行时的那份文本的改写（**必须为 0**）。
- `提交延迟`：最终词在**已定稿前缀**里首次出现的时间减去它在 **raw 转写**里首次出现的时间（都用事件的 `arrival_seconds`，实时回放下它跟随音频位置；终止事件没有 `audio_seconds`，所以不能只用它）——即运行时比官方口径晚多久拿到这个词。
- `挂起的词`：用户音频结束时 raw 转写比已定稿前缀**多出的词数**（刻意扣住的可改写尾巴有多长），给中位数与最大值。
- `冻结`：定稿前缀落后 raw 超过 8 个词的最长连续时长（token 级提交修复前的症状：字符串比较会让可见文本永久冻住）；`提交停滞`：解码器回改到「已交给调用方」的 token 的次数（正常应为 0）。
- `最终转写距离`：该臂逐样本的最终转写与 baseline 臂（默认 `window-0`）的词级 Levenshtein 距离，取中位数；`raw`/`可见` 两种文本各算一份。
- `有改写的样本`：出现 raw 改写的样本数，用来看改写是集中在少数长样本还是普遍存在。

## 输出

- `asr_contract.md`：一张表（每 arm：样本数、音频秒、raw/可见改写次数、有改写的样本数、尾部释放延迟中位/最大、可见与 raw 的最终距离），加"判据"小节。
- `asr_contract.json`：同样的内容 + 逐样本明细（含两种最终转写），便于后续脚本消费。

## 用法

```bash
python scripts/remote/summarize_asr_contract.py \
  --run-dir data/runs/asr_contract_<tag> --report-dir reports/asr_contract/<tag> \
  --tag <tag> [--baseline window-0]
```

节点脚本已在两臂跑完后自动调用；`--baseline` 用于换参考臂。
