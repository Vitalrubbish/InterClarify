# Nemotron＋SoulX：FDB 三类各10条实测

2026-10-30，按用户要求在远端单卡运行30条真实音频。以下统计针对前端文本和五类状态，不是接入LLM／TTS后的官方完整系统得分。

**结论：当前适配的完成判断不可靠，停顿误完成较多；用户打断均检测到nonidle，但典型等待较长。** 连续转写已跑通，不代表SoulX对新文本节奏及reset的语义适配完成。本轮没有修改模型行为或重跑挑选更好的结果。

## 抽样与执行

固定种子20261030、按ID字典序形成候选后无放回抽样；接话10条、停顿10条（Candor／Synthetic各5条）、用户打断10条。原始音频合计513.1915秒，完整实时回放，不另补静音。FDB输入文件本身包含的静音属于原输入；例如接话文件通常带约5秒后续音频，打断文件带约15秒后续音频。标注仅用于事后评分。

推理源码`860740c`，本地离线分析`e6dd306`；作业`job-179333017126166764434-xuan-zhang`，1×4090、4CPU、32GiB，单活动作业。复用已冻结Nemotron EN0.6B FP32 lookahead1与SoulX revision，两个既有conda环境分进程；80ms实时时钟送同一PCM。整段RMS0.05／峰值0.9标定沿用r2，不宣称因果AGC。

清单SHA256：`403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07`。实际回放通过 30/30；契约异常 0 帧。完整清单、原始事件、在线与排空全文、逐帧CSV保存在本地 `artifacts/soulx/20261030-nemotron-fdb30-r1/`，远端run为 `~/parathink-soulx-duplug/runs/nemotron-soulx-fdb30-20261030-r1/`。

最终退出码0，结束后核对队列为空。3196条状态中有52条经过上游规则修正，文本token缓存重放54次；队列等待最大379.75ms，设备显存采样峰值7420MiB，SoulX进程峰值分配／保留3.962／4.055GiB。run占盘约18MiB。下载包SHA256 `84b246773b180dbae88a425a5320d651048a747f56da5ec60e2d5d3b2fa57271`，38项归档文件逐项校验通过。

## 计时与判断口径

状态时间使用真实音频处理截止；另保留包含前瞻的观察上界。接话以turn_taking.json起点为用户结束边界，打断以interrupt.json终点为打断语句结束边界，统计打断结束时排除打断开始之前的正常context完成。严格边界前、比边界早160ms以上、观察上界仍在边界前分别记录，避免40ms前瞻及160ms控制粒度混淆。停顿区间使用左闭右开，不以整段存在complete推断停顿误判。

没有人工句法边界或原生complete金标，所以“官方边界前complete”是可核验的时序诊断，不能把一切较早的语义句子结束都判成模型错误。原始预测、上游规则修正、最终发布状态分列；运行通过不等于状态准确。

## 分组结果

| 项目 | Smooth turn taking | Pause handling | User interruption |
| --- | ---: | ---: | ---: |
| 抽样数 | 10 | 10 | 10 |
| 成功回放 | 10 | 10 | 10 |
| 出现过complete的样本 | 8 | 8 | 9 |
| complete事件总数 | 17 | 26 | 22 |

### smooth_turn_taking

- 官方结束边界后有complete：2/10。
- 官方结束边界前有complete：8/10；其中早160ms以上：8/10。
- 提前超过1秒的样本：6/10。
- complete的完整音频观察上界仍早于边界：8/10。
- 边界后首个complete的处理音频位置延迟，中位240.0ms，范围80.0—400.0ms；分母2，不是墙钟响应或播放延迟。

若允许结束边界前160ms这一控制块粒度，边界附近或之后出现complete为3/10（ID17、3、54）；其中ID54最后一次complete只比边界早10ms。但这3条均另有更早的complete，严格“没有提前complete、且边界后正常complete”的样本为0/10。不能将严格2/10直接解释为其余8条完全没有临近结束的预测。

### user_interruption

- 官方结束边界后有complete：3/10。
- 官方结束边界前有complete：8/10；其中早160ms以上：8/10。
- 提前超过1秒的样本：7/10。
- complete的完整音频观察上界仍早于边界：8/10。
- 边界后首个complete的处理音频位置延迟，中位490.7ms，范围117.3—544.0ms；分母3，不是墙钟响应或播放延迟。
- 打断发声区间内有有效nonidle：10/10；出现新的nonidle状态转移：10/10。
- 首个nonidle相对打断开始的处理音频位置延迟，中位880.0ms，范围256.0—1781.3ms。
- 没有活动播放或真实停播回调，本项只说明检测token，不是打断停播成功率。

3条边界后complete中，只有ID20没有在打断开始后、结束前另报complete；它仍在消费到词内前缀`tom`时完成，Context最新已经是`tomorrow`。ID74在10.20秒的complete消费文本仍为初始问题`…to space`，存在旧context延后完成；因此本组8/10的“打断区间内边界前complete”不能不加区分地全部解释为新打断句子的句中误判。完整控制输入已逐帧保留。

### pause_handling

- 共11个官方停顿区间；5个区间出现complete，涉及5/10条样本。
- 按完整观察上界落在停顿区间计数：5个区间。
- 最后一个参考词结束后出现complete：0/10；该组原始文件普遍紧贴发声结束，不能把EOF后缺少继续观察等同于漏检。

## 文字核查

接话10条缺少独立参考文字，不计算WER。停顿使用transcription.json，用户打断使用interrupt.json的context＋interrupt；二者均不输入模型。词级评分统一小写、去标点、保留词内撇号，不将数字与拼写形式做语义等价，以下是原始规范化WER，不是人工判定的语义准确率。

| 任务 | 有参考样本 | 参考词数 | S＋D＋I | 微平均WER |
| --- | ---: | ---: | ---: | ---: |
| pause_handling | 10 | 288 | 36 | 12.50% |
| user_interruption | 10 | 189 | 16 | 8.47% |

在线与排空全文有差异的共6条，全部属于停顿组：Candor ID161、Synthetic ID131／132／41／53／70。部分尾词只在EOF排空返回，例如ID131的`on top`；即使排空也不保证完整，例如ID41仍只到`Gone with the`，参考为`Gone With the Wind`。另有真实错词：打断ID104将`Should I…`识别为`Told I…`，`garden`停在`guard`。因此WER包含识别错误、参考分词差异和在线尾部缺失，不能直接推导成语义正确率。停顿参考中的`[UH]`／`[UM]`在本口径归一化为发声词参与计算。

## 代表性问题

| 样本 | 实际complete | 参考位置与后续 |
| --- | --- | --- |
| 接话ID51 | 4.92秒，控制文本`California was` | 官方结束7.82秒；这是待续结构，提前约2.90秒，且后续没有再次complete |
| 接话ID83 | 3.80秒，控制文本`…did you like grad` | 官方结束6.32秒，词内前缀就完成，提前约2.52秒 |
| 停顿Synthetic ID132 | 5.56秒，控制文本`…the visuals were effective` | 官方停顿5.46—7.24秒，之后还有`but … the conclusion needs more impact` |
| 停顿Candor ID161 | 4.28秒，generation新控制文本为空 | 原始预测与发布均为complete，reset后无新消费文本仍给出完成，前端只保证引用可追溯，不能保证语义合理 |
| 打断ID9 | 打断开始9.379秒，首个nonidle11.16秒 | 检测等待约1.781秒；11.80秒在`…what's the price`给complete，官方打断结束13.037秒 |

这些现象不能仅归因于Nemotron识别质量：新ASR词内增量、实际消费滞后、token重分词、原生规则和reset上下文都可能影响状态，需要分项对照；本轮没有SenseVoice同样本对照，不作单因素归因。

## 逐样本时序结果

下表提前量为所有边界前complete中最早一次相对边界的时间差，负值表示早于标注。打断组只看打断开始后的complete。停顿组列误complete的区间数。

| 样本 | 回放 | 边界后complete | 最早提前量（秒）／停顿误complete区间 | 打断nonidle延迟（毫秒） | WER |
| --- | --- | --- | --- | --- | --- |
| candor_turn_taking-102 | 通过 | False | -0.320 | — | 无参考 |
| candor_turn_taking-17 | 通过 | True | -2.640 | — | 无参考 |
| candor_turn_taking-3 | 通过 | True | -5.520 | — | 无参考 |
| candor_turn_taking-39 | 通过 | False | -21.100 | — | 无参考 |
| candor_turn_taking-51 | 通过 | False | -4.500 | — | 无参考 |
| candor_turn_taking-54 | 通过 | False | -3.530 | — | 无参考 |
| candor_turn_taking-56 | 通过 | False | 无 | — | 无参考 |
| candor_turn_taking-76 | 通过 | False | 无 | — | 无参考 |
| candor_turn_taking-83 | 通过 | False | -2.520 | — | 无参考 |
| candor_turn_taking-91 | 通过 | False | -0.530 | — | 无参考 |
| candor_pause_handling-127 | 通过 | False | 1/1 | — | 9.7% |
| candor_pause_handling-16 | 通过 | False | 0/2 | — | 6.2% |
| candor_pause_handling-161 | 通过 | False | 1/1 | — | 21.7% |
| candor_pause_handling-40 | 通过 | False | 0/1 | — | 22.7% |
| candor_pause_handling-50 | 通过 | False | 1/1 | — | 13.8% |
| synthetic_pause_handling-131 | 通过 | False | 0/1 | — | 10.7% |
| synthetic_pause_handling-132 | 通过 | False | 1/1 | — | 4.2% |
| synthetic_pause_handling-41 | 通过 | False | 0/1 | — | 20.8% |
| synthetic_pause_handling-53 | 通过 | False | 0/1 | — | 9.7% |
| synthetic_pause_handling-70 | 通过 | False | 1/1 | — | 14.3% |
| synthetic_user_interruption-104 | 通过 | False | -1.184 | 960.0 | 10.0% |
| synthetic_user_interruption-118 | 通过 | False | -1.621 | 1226.7 | 5.9% |
| synthetic_user_interruption-131 | 通过 | False | -0.981 | 1152.0 | 0.0% |
| synthetic_user_interruption-136 | 通过 | True | -2.816 | 586.7 | 8.7% |
| synthetic_user_interruption-164 | 通过 | False | -1.088 | 800.0 | 0.0% |
| synthetic_user_interruption-18 | 通过 | True | -2.283 | 394.7 | 15.8% |
| synthetic_user_interruption-20 | 通过 | True | 无 | 437.3 | 11.8% |
| synthetic_user_interruption-43 | 通过 | False | 无 | 960.0 | 6.2% |
| synthetic_user_interruption-74 | 通过 | False | -3.669 | 256.0 | 10.0% |
| synthetic_user_interruption-9 | 通过 | False | -1.237 | 1781.3 | 18.8% |

## 可复现与边界

本地逐帧CSV与完整文字审阅入口：`artifacts/soulx/20261030-nemotron-fdb30-r1/inspection.md`，结构化分组及个案：`analysis/analysis.json`。分析命令：`conda run -n interclarify-dev python scripts/remote/nemotron_soulx_fdb.py analyze --probe artifacts/soulx/20261030-nemotron-fdb30-r1/evidence/probe --output <new-analysis-directory>`。

本轮仅30条固定抽样，不做阈值搜索、模型训练或整体质量推广。在线文字与EOF后排空严格分开，WER只使用在线结果。前端状态不能代替真实回答、停播及用户体验指标。
