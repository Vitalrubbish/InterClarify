# XTurnix 停顿 token 诊断探针

`scripts/remote/xturnix_pause_probe.py` 是用户要求的诊断探针，不属于 XTX-005/006 的冻结协议。它只加载冻结的 XTurnix-PT，在相同文本上比较加/不加 `<|pause|>` 时的 `<|start|>` 比例；不加载 Nemotron、不重放音频、不写正式 run 目录。

## 三种配置

| 配置 | 用户内容 |
| --- | --- |
| `no_pause` | 原始 ASR 文本 |
| `pause_at_end` | 文本末尾直接追加一个 `<|pause|>` |
| `pause_mid_and_end` | 在文本中段随机词间插入一个 `<|pause|>`，再在末尾追加一个 |
| `pause_at_end_stripped` | 先按官方规则去掉末尾标点，再在末尾追加一个 `<|pause|>` |
| `pause_mid_and_end_stripped` | 去末尾标点后，在文本中段随机词间插入一个 `<|pause|>`，再在末尾追加一个 |

后两种是对照组：官方 `turn_pipeline` 会去掉最后一轮用户文本的末尾标点，而末尾一旦跟着 `<|pause|>`，标点就不再位于末尾。对照可区分“pause token 本身”与“末尾标点未被去掉”的影响。

中段位置按 `case_id`、配置名与固定 seed 选择，位于文本长度 20%—80% 的空格边界；`samples.csv` 记录实际偏移和完整内容，可逐条复核。token 直接拼接、不额外加空格，与 X-Talk 中 pause 段渲染后的连续 user 内容一致。

## 文本集

- `asr_smoke_test`：XTX-005 冒烟 5 条 test 的 EOF 最终 ASR 文本。
- `asr_smoke_dev`：冒烟的 1 条 dev 最终 ASR 文本。
- `reference_test`：冻结 manifest 中 100 条 test 参考文本，仅作较大样本的文本敏感性检查；这不是 ASR 文本，不能替代正式分母。

探针不读取参考答案来决定在线时机；参考文本只作为诊断输入。

## 运行

```bash
cd <frozen source worktree>
XTURNIX_PROBE_TAG=xtx-pause-probe-20261023-a10-r1 \
  XTURNIX_PROBE_SOURCE_RUN=xtx-005-smoke-20261023-a10-r4 \
  XTURNIX_PROBE_PARTITION=pdgpu-a10 \
  bash scripts/remote/submit_xturnix_pause_probe.sh
```

输出：

```text
<root>/runs/<probe_run_id>/
├── probe.log
├── probe.json       # 环境、模型、seed、各文本集/配置的 start 数与比例
├── samples.csv      # 逐条 action、分数、中段偏移、内容摘要与内容
├── gpu.csv
└── exit_code.txt
```

## 边界

- 本探针把 `<|pause|>` 人为加在录音结束后或句中，属于冻结协议明确禁止的“由文件末端补点”；结果只回答“加 pause 是否改变动作”的诊断问题。
- 不把探针结果并入正式成绩，不据此调阈值、改抽样或宣称话轮准确率。
- 正式 100 条仍应使用冻结的 `run_xturnix_fleurs_job.sh`；本探针不替代正式回放。
