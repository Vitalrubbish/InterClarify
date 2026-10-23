# XTurnix 停顿 token 诊断：句末 `<|pause|>` 不会触发 start

2026-10-23。用户要求在冒烟后检查“录音结束加 `<|pause|>` 是否会让 XTurnix 接话”。本报告只回答这个诊断问题，不替代正式 100 条测试；正式作业已按用户要求取消。

## 结论

**不会。** 在冻结的 XTurnix-PT 上，句末追加 `<|pause|>` 不但没有提高 `<|start|>` 比例，反而把原本就很低的 start 概率进一步压低：

- 5 条 test ASR 文本：无 pause 0/5，句末 pause 0/5，中段＋句末 pause 0/5。
- 1 条 dev ASR 文本：所有配置均 0/1。
- 100 条 test 参考文本：无 pause 1/100（1%），句末 pause 0/100，中段＋句末 pause 0/100；去掉末尾标点的两个对照组也均为 0/100。

唯一一条无 pause 的 start 样本，在句末加 pause 后变成 keep：

| 文本 | 配置 | 动作 | start 分数 |
| --- | --- | --- | --- |
| `test/5910253289107526048.wav` | 无 pause | `<|start|>` | 0.5295 |
| 同上 | 句末 `<|pause|>` | `<|keep|>` | 1.38e-08 |
| 同上 | 中段＋句末 `<|pause|>` | `<|keep|>` | 3.51e-08 |

## 三种主配置与两个对照

| 配置 | 内容 |
| --- | --- |
| `no_pause` | 原始文本；官方 pipeline 会去掉末尾标点 |
| `pause_at_end` | 原始文本 + 句末 `<|pause|>` |
| `pause_mid_and_end` | 随机词间 `<|pause|>` + 句末 `<|pause|>` |
| `pause_at_end_stripped` | 先去末尾标点，再加句末 `<|pause|>` |
| `pause_mid_and_end_stripped` | 先去末尾标点，再加中段＋句末 `<|pause|>` |

后两个对照用于排除“末尾标点未去掉”这一混淆：结果仍是 0 次 start，说明抑制来自 pause token 本身，而不是标点保留。

## 分文本集结果

| 文本集 | 配置 | start | 比例 | 平均 start 分数 |
| --- | --- | ---: | ---: | ---: |
| 5 条 test ASR | 无 pause | 0/5 | 0% | 0.1853 |
| 5 条 test ASR | 句末 pause | 0/5 | 0% | 2.4e-08 |
| 5 条 test ASR | 中段＋句末 pause | 0/5 | 0% | 1.26e-07 |
| 1 条 dev ASR | 无 pause | 0/1 | 0% | 0.2434 |
| 1 条 dev ASR | 句末 pause | 0/1 | 0% | 9e-09 |
| 1 条 dev ASR | 中段＋句末 pause | 0/1 | 0% | 1.1e-08 |
| 100 条 test 参考 | 无 pause | 1/100 | 1% | 0.2288 |
| 100 条 test 参考 | 句末 pause | 0/100 | 0% | 1.3e-08 |
| 100 条 test 参考 | 中段＋句末 pause | 0/100 | 0% | 9.95e-07 |
| 100 条 test 参考 | 去标点＋句末 pause | 0/100 | 0% | 4.04e-05 |
| 100 条 test 参考 | 去标点＋中段＋句末 pause | 0/100 | 0% | 6.92e-05 |

## 解释

1. **pause 不是“用户说完”的信号。** 模型把句末 pause 理解为“用户还在继续”，因此更倾向于 `<|keep|>`；start 分数从 0.2—0.5 降到 1e-5—1e-8。
2. **X-Talk 的 pause 只是闸门，不是触发器。** 官方 `_map_action_locked` 只有在模型原始动作已经是 `<|start|>` 且 `speech_pause_seen=true` 时才放行接话；pause 本身不会把 keep 变成 start。本探针已经直接看原始动作，仍然是 keep。
3. **官方实现对“末尾 pause”还有一层延迟。** X-Talk 的 pause 段要等到后续文本到达才会写进对话；录音正好结束时，pause 仍处于 pending，模型看到的仍是没有 pause token 的前缀。因此“在最后加一个 pause token”既不是官方触发路径，也不能改善原始 keep。
4. **FLEURS 是朗读陈述句。** 这批文本原本就几乎不产生 start；0/5 与 XTX-002 dev 探针一致，不是回放或服务故障。

## 作业与证据

| 项目 | 值 |
| --- | --- |
| 作业 | `job-179275585902741423135-xuan-zhang` |
| 节点 / GPU | `d6-hpc-gpu-038` / NVIDIA A10 |
| 时间（UTC） | 19:44:54—19:45:24，退出码 0 |
| 源码提交 | `03f44e6` |
| 模型 | `~/interclarify-xturnix-fleurs/models/xturnix-pt` |
| 文本集 | 5 test ASR＋1 dev ASR＋100 test 参考，共 106 例 × 5 配置 = 530 次前向 |
| 探针耗时 | 17.66 秒 |
| 运行目录 | `~/interclarify-xturnix-fleurs/runs/xtx-pause-probe-20261023-a10-r3` |

| 文件 | SHA256 |
| --- | --- |
| `probe.json` | `2aa2e24d5cef71366c40b1122618e2976b232b769dbcd9bb0e5a92a82e779f9a` |
| `samples.csv` | `16e6ba56d5de2c2c4a4b2a0cc38c0dc66f71d0a4102dc4600d7cd9aff6eecbe7` |
| `probe.log` | `7e0db75127b581e7a9643e7262f79c681f4811f867dcbaa9c5bb5fa0adec39fb` |
| `gpu.csv` | `9255c08c4890725fa008d339c3957fdc8124bb33623bac93df66ec2272882073` |
| 提交日志 | `xtx-pause-probe-20261023-a10-r3.log` |

## 边界

- 本探针把 pause 人为加在录音结束后或句中，属于冻结协议明确禁止的“由文件末端补点”；只用于回答诊断问题，不并入正式分母，不据此调阈值、改抽样或宣称话轮准确率。
- 正式 100 条作业已按用户要求取消，未产生正式成绩；XTX-006 仍未完成。
- 探针只加载 XTurnix，不加载 Nemotron、不访问 ASR 服务、不写正式 run 目录。
- 入口与参数见 [xturnix_pause_probe](../../../docs/scripts/remote/xturnix_pause_probe.md)。
