# 原生 pause 使用核查与真实模型诊断

更新：2026-10-24，XTX-014。已完成固定官方源码核查、官方接口合同回放及冻结 PT 的远端 CPU FP32 真实前向；退出码 0，推理错误 0。训练相关工作单已搁置归档，未更新模型参数或切换现役控制。完整协议见[pause 使用方案](../../../docs/dev/XTurnix/pause_usage.md)。

## 1. 结论

**官方 pending/gate 合同可以正常工作；直接在当前末尾追加 `<|pause|>` 会改变输入并压低 start，不能替代该合同。本次小样例未显示末端接话覆盖提升，不宣称已解决低召回。**

固定官方 X-Talk `5f0d9959edf1026588246efbed827b078cbb114c` 的类文件与本地参考 fork 逐字节一致。真实模型为 PT `d4b0403`，原生 pause 编码实测为单 token `151674`；未扩词表。源码和文档摘要见[reference_audit.json](reference_audit.json)。

## 2. 官方实际用法

当前停顿先设 `speech_pause_seen` 和 `pending_pause_offset`，当前模型文本末尾先不写 pause。用户之后续说时，pending 才在之前的位置成为句内 token，相同偏移不重复插入。Listen 下只有原始 start 且 gate 打开才提交 start，缓存 keep 不会因停顿变成 start；匹配的原始分数可复用，重复 pause 不重复启动，新发声关闭 gate。

按实际事件依次调用官方客户端的形式为：

```python
await detector.async_detect(text=prefix)
await detector.async_detect(text=prefix, speech_pause=True)
await detector.async_detect(speech_start=True)
await detector.async_detect(text=extended_prefix)
```

第二步需要传当前文本以进入动作映射；单独调用 `async_detect(speech_pause=True)` 更新状态后立即返回 IDLE。最后一步在真正续说后提交先前 pending 的句内 pause。这里的示例描述接口合同，不表示本项目已接入完整 X-Talk/vLLM 服务。

固定官方源码对应的 11 项已有测试、诊断状态机的 3 项测试均通过，另直接回放了[官方客户端接口轨迹](official_client_contract.json)。该接口轨迹使用显式 mock 原始动作，只验证合同；下面的分数来自真实 PT 前向，二者不混称。

## 3. 真实 PT 的 sanity 结果

| 条件 | 英文问句 start 分数 | 中文问句 start 分数 | 停顿时动作 |
| --- | ---: | ---: | --- |
| 不插文本 token，保留相同 gate | 0.551812 | 0.809876 | 缓存 start 在 gate 打开后提交一次 |
| 官方 pending | 0.551812 | 0.809876 | 当前末尾保持 pending，缓存 start 提交一次 |
| 直接末尾插入 | 2.8873e-8 | 2.7621e-8 | 原始动作变 keep，不提交 start |

同一问句在停顿前即使原始 start，gate 尚未打开也不提交；停顿后的第二次重复事件不重复启动。官方 pending 没有通过改变末尾文本来“激活”模型，而是在合适时机放行已得到的动作。

另一个请求轨迹先出现未完前缀，再续说。末端 start 分数为无标记 0.438768、pending 0.228233、直接末尾插入 5.2179e-7，三者都没有提交 start。续说时 pending 已成为句内 token，说明原生 pause 会影响后续语义分数，但不能把任意低分请求强制变成 start。pause token 本身不携带 300ms、1s 等连续时长。

## 4. 8 个自然 dev 话轮的机制对照

| 条件 | 末端观察的 start 候选 | 句中首次提交 start | 首次 start 位于末端 | 始终未提交 start |
| --- | ---: | ---: | ---: | ---: |
| 无文本 pause，保留 gate | 2/8 | 4/8 | 1/8 | 3/8 |
| 官方 pending | 1/8 | 3/8 | 1/8 | 4/8 |
| 直接末尾插入 | 0/8 | 0/8 | 0/8 | 8/8 |

三种条件使用相同的停顿事件、默认 0.5 动作选择与一次性 latch，区别只在 token 位置。末端候选单独记录原始分数，即使之前已提交过 start，也继续在固定 Listen 的影子轨迹中打分；首次提交位置另列，不能把二者混作实际闭环召回。

这 8 个话轮来自已冻结 dev，均含多个参考停顿，按预先固定的 ID 哈希顺序选取，并非独立测试。停顿由既有参考前缀/时间形成，sanity 则为人工脚本；本次没有真实 ASR 无增量计时、在线音频或播放状态转换。表中计数只作机制诊断，不作为控制质量成绩。结果未支持在该小样例上提高末端接话覆盖，更不能据此选择新阈值或宣称上线收益。

## 5. 调度、资源与完整覆盖

| 尝试 | 调度 ID | 结果 |
| --- | --- | --- |
| A10 r1 | `job-179277595040143133715-xuan-zhang` | Pending 时撤销 |
| 4090 r2 | `job-179277675198310775624-xuan-zhang` | Pending 时撤销 |
| CPU r3 | `job-179277747271132523843-xuan-zhang` | `d6-hpc-cpu-005`，4 CPU/16 GiB/0 GPU，退出码 0 |

GPU 队列持续 Pending 后先撤销原作业，再提交 CPU，始终只保留一个活动作业。原 20 话轮 GPU 计划未执行，清单保留在[planned_gpu_cases.json](planned_gpu_cases.json)；CPU 在产生模型结果前改为原顺序前 8 个自然话轮＋全部 3 个 sanity，实际清单见[case_manifest.json](case_manifest.json)，与[事前清单](planned_cases.json)一致。

- 执行源码：`123b9e124fd175e4b74c272024ac6d70ef70b326`，独立 worktree；实际脚本哈希与该提交逐字节一致。
- 模型锁的 21 个文件复核通过；既有 conda、torch 2.11.0+cu128、transformers 4.57.1，实际设备为 CPU、FP32、4 线程，未创建环境或下载权重/音频。
- 11 条轨迹 × 3 条件，共 246 条事件记录；完整相同模型输入可缓存，实际模型前向 103 次，错误 0；每条轨迹每条件最多一次 start，均在 gate 打开后提交。
- probe 运行 331.96 秒；资源监控 UTC 为 2026-10-23 17:53:31—18:00:00，进程峰值 RSS 4,102,828 KiB（约 3.91 GiB），作业导出前输出 209 KiB，未触发资源停止线。
- CUDA 峰值字段为 null。沿用 runner 的 `gpu_samples.csv` 中显存 0 仅表示未使用 GPU，不能把它当作 GPU 模型性能；CPU 时间不与旧 A10 推理时间比较。

## 6. 可复核证据与后续范围

[summary.json](summary.json)保存三条件结果、调用数、模型/代码/设备和资源；[events.csv](events.csv)保存全部事件的分数、输入摘要、pending/gate/latch 与提交结果，去除了自然对话正文；[execution_evidence.json](execution_evidence.json)、[source_commit.txt](source_commit.txt)及[exit_code.txt](exit_code.txt)保存实际执行来源与退出证据。原始带模型文本的事件留远端独立 run，不提交 Git。

回收压缩包 SHA256：`de019488f443cd2e52ae8bbe2e93800299d03a8731168c2a216ddc780ed10ab7`，本地与远端一致。已核对原始文件摘要、执行脚本、事前/实际案例清单，并复算三条件计数和 gate/latch 约束。原始 run 为 `~/interclarify-xturnix-fleurs/runs/xtx-014-pause-usage-20261024-r3`，不覆盖旧 pause 或 Listen 实验。

原生 pause 子诊断完成，XTX-014 整体仍未完成：后续需把真实 ASR 时间估计适配成停顿事件，并验证异常、旧版本与在线收益。训练相关 XTX-008、009、011—013 已搁置归档；[ASR 时间无训练路线](../../../docs/dev/XTurnix/asr_time_control.md)保留，Speak 校准后置，不自动训练或部署。
