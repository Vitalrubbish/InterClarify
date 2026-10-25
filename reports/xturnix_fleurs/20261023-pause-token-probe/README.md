# XTurnix 停顿 token 诊断：句末 `<|pause|>` 不触发 start

2026-10-23。用户要求在冒烟后检查“录音结束加 `<|pause|>` 是否会让 XTurnix 接话”。本报告只回答诊断问题，不替代正式 100 条测试；正式作业已按用户要求取消。

## 结论

**句末加 `<|pause|>` 不会触发 start，反而会压低 start。** 同时，最小 sanity 对照表明**调用格式本身没有坏**：同一 pipeline、同一 `state="listening"`、同一 prompt 下，模型卡中文问句得到 `<|start|>`（0.810），英文问句 “What time should we leave tomorrow?” 也得到 `<|start|>`（0.552）。但一旦在末尾追加 `<|pause|>`，这两条都变成 `<|keep|>`，start 分数降到约 1e-8。

因此更准确的判断是：

- **不是** `turn_pipeline`、state、prompt 或消息格式用错；
- **是** 把 XTurnix 当成“录音结束检测器”用错了。它是话轮让渡（turn-taking）分类器，不是 VAD/端点检测器；FLEURS 朗读陈述句本来就不是它训练分布中的“用户说完并让出话轮”；
- `<|pause|>` 在官方 X-Talk 里是**闸门**，不是触发器。它只在模型原始动作已经是 `<|start|>` 时放行接话，不能把 keep 变成 start；
- 官方实现对录音末尾的 pause 还会保持 pending，等后续文本到达才写入对话；在最后补一个 pause token 不是官方触发路径。

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

唯一一条无 pause 的 start 样本是 `test/5910253289107526048.wav`：

| 配置 | 动作 | start 分数 |
| --- | --- | ---: |
| 无 pause | `<|start|>` | 0.5295 |
| 句末 pause | `<|keep|>` | 1.38e-08 |
| 句中＋句末 pause | `<|keep|>` | 3.51e-08 |

## Sanity：调用格式核对

| 文本 | 无 pause | 句末 pause |
| --- | --- | --- |
| 中文问句（模型卡） | `<|start|>` 0.8099 | `<|keep|>` 2.76e-08 |
| 英文问句 “What time should we leave tomorrow?” | `<|start|>` 0.5518 | `<|keep|>` 2.89e-08 |
| 英文问句 “Could you help me move this table?” | `<|keep|>`（start 0.4388） | `<|keep|>` 9.05e-08 |
| 英文陈述 “The weather is nice today.” | `<|keep|>`（start 0.2331） | `<|keep|>` 1.09e-08 |
| 中文陈述 “今天天气不错。” | `<|keep|>`（start 0.4335） | `<|keep|>` 2.48e-08 |

这组对照说明：

1. pipeline 能把问句判成 start，调用格式有效；
2. 模型确实依赖文本中的问句/话轮线索，而不是“文件结束”这一事实；
3. pause token 在末尾会把原本 start 的问句也压成 keep，因此它不是“说完了”的正向信号。

## 为什么 FLEURS 几乎不 start

- FLEURS 是朗读陈述句，不是自然对话；没有真实的“用户让出话轮”事件。模型在陈述句上给出 keep 是合理的。
- XTurnix 是纯文本话轮分类器，不理解声学停顿、语调或录音结束；它只能从文本内容判断。朗读句往往没有问句或其他让轮线索。
- 正式回放的 ASR 文本还有 10% WER 和句界合并（例如 “shore. Swimming” 被识别成 “shoreming”），进一步削弱了句末线索；但干净参考文本也只有 1/100 start，说明 ASR 错误不是主因。
- 官方用法只在真实因果 VAD/上游分段给出 pause 时把 pause 作为**闸门**；它不是“录音结束自动 start”的兜底。把 pause 补在 EOF 既不符合冻结协议，也不会产生 start。

## 作业与证据

| 项目 | 值 |
| --- | --- |
| 作业 | `job-179275630072577789666-xuan-zhang` |
| 节点 / GPU | `d6-hpc-gpu-045` / NVIDIA A10 |
| 时间（UTC） | 19:51:45—19:52:22，退出码 0 |
| 源码提交 | `e29f6a3` |
| 模型 | `~/interclarify-xturnix-fleurs/models/xturnix-pt` |
| 文本集 | 5 test ASR＋1 dev ASR＋100 test 参考＋5 sanity，共 111 例 × 5 配置 = 555 次前向 |
| 探针耗时 | 19.575 秒 |
| 运行目录 | `~/interclarify-xturnix-fleurs/runs/xtx-pause-probe-20261023-a10-r4` |

| 文件 | SHA256 |
| --- | --- |
| `probe.json` | `818dec04a80f2c7d4ae1ff5ef8a72812a5e1b3e61c185c7d04d5f669c5e9bab6` |
| `samples.csv` | `b4baedbec45f45c8529ddaa3ca5085eb8e4a5b7d7e058ae4026926a52d0a0391` |
| `probe.log` | `a851f3dfbbd3dbb9ea437b3d798be9e61eb732f0071813e3f495471c978321b7` |
| `gpu.csv` | `89e43f320cb19a1c66ff2418e44cc04ab0aa5c8ce9d38f7d9eb483460855f3c6` |
| 提交日志 | `xtx-pause-probe-20261023-a10-r4.log` |

## 边界

- 本探针把 pause 人为加在录音结束后或句中，属于冻结协议明确禁止的“由文件末端补点”；只用于回答诊断问题，不并入正式分母，不据此调阈值、改抽样或宣称话轮准确率。
- 正式 100 条作业已按用户要求取消，未产生正式成绩；XTX-006 仍未完成。
- 探针只加载 XTurnix，不加载 Nemotron、不访问 ASR 服务、不写正式 run 目录。
- 若目标是“朗读句末检测/端点检测”，应换用端点检测或专门的话轮结束模型；XTurnix-PT 不是该任务模型。若目标是验证 XTurnix 的话轮判断，输入应是自然对话中的让轮点，并只把真实因果 pause 作为闸门。
- 入口与参数见 [xturnix_pause_probe](../../../docs/scripts/remote/xturnix_pause_probe.md)。

## 原始产物保存

本页为Git保留的结果汇总；逐例JSON／CSV、trace、样本正文及资源采样不再入库。本地归档位于`artifacts/report_archive/reports/xturnix_fleurs/20261023-pause-token-probe/`，具体文件与SHA256见本地`artifacts/report_archive/archive_index.json`；已有远端run路径保持原样。复现时读取归档，不从报告链接下载原始产物。Git历史未重写。
