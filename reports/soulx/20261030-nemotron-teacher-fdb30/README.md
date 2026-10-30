# Nemotron Teacher Forcing 与 FDB 三轴小样本

2026-10-30。已实现[同步方案](../../../docs/dev/SoulX-Duplug/nemotron_teacher_forcing.md)，两份权重固定，Nemotron 每步真实解码结束并交付文字后，SoulX 输入当前音频、原始新增教师文字及 ASR 结束符，预测状态并联合覆盖 Context，发布后才允许 ASR 推进下一块。SenseVoice 不加载、不调用；下游 LLM／TTS 未接入。

**结论：接入及30/30条实时回放完成，3185帧同步顺序通过；控制器与 Context 已使用同一份本步教师正文，但状态质量没有整体改善。** ASR 排空全文与上一轮独立组合30/30相同；停顿组在线 WER 略高，接话边界后 complete 覆盖增加，停顿误 complete 和打断 nonidle 覆盖变差。不能据链路跑通宣称语义控制达标。

## 实现与冻结

- 实际推理源码 `b143bff`，初始接入提交 `06ed959`；GitHub 已推送。
- Nemotron EN0.6B revision `ebe59e5a817142986528bbbee5dba8db7b38ed50`，FP32、lookahead1；SoulX revision `61701c4ab8193cc1ee2220d3848872ac6c720142`，上游源码摘要固定。
- Transformers 生成源码 SHA256 `c45e19eb4534a2478f8e4825dc35a28fb5efe5a2f8d09695e4b2ea532b4dbd82`。内存调整 `_sample` 顺序使 streamer 最后 token 先于下一特征读取；类方法在 generation 结束后恢复，不修改环境文件。
- 复用历史 FDB30 manifest：接话10、停顿10、打断10，音频513.1915秒。引用与标注只离线评分，不输入模型。
- 本逻辑话轮软重置保留音频／教师 KV、字符游标和下一次输入的有效状态；未知输出不反馈。保留原生两条完成规则，分开记录原始预测和规则改写。
- 本轮真实0时刻对齐160ms处理块，初始回看零填充，保留640样本前瞻；历史原生 process 有40ms初始占位，比较时不能把粒度差异忽略。离线整段 RMS 标定沿用历史配置，不宣称线上因果增益。

本地 conda 下6项教师文字／屏障、4项 Context、5项 SenseVoice 前端回归、5项原 Nemotron 服务检查通过，共20项。脚本语法及冻结 Transformers AST 编译检查通过。

## 远端预检

单作业、1×4090、4CPU、32GiB；ASR 与 SoulX 各2线程、显存比例0.55／0.35；显存停止线22GiB、结果128MiB、1800秒、音频积压800ms。复用既有两个 conda 与模型，不复制大型权重。

第一轮 `job-179336761878288219987-xuan-zhang` 在加载阶段主动停止：核查发现 Transformers 从模型类获取 `_sample`，实例绑定不能替换实际解码方法；修复后重新冻结提交，不将该轮算作测试成功。

第二轮 `job-179336789523255028144-xuan-zhang`，run `nemotron-teacher-smoke-20261030-r2` 退出0，三轴各1条通过，合计309帧。最大积压329.8ms；预检仍出现提前 complete，不宣称语义质量达标。


## 三轴结果与同样本对照

正式作业 `job-179336810567755358882-xuan-zhang`，北京时间21:48提交，30条全部完成，回放和分析退出码0；22:01核查服务器队列为空。对照为[上一轮 Nemotron 独立组合](../20261030-nemotron-fdb30/README.md)，输入及参考未重新抽样。以下时机均为处理音频位置，不能代替墙钟端到端延迟或真实停播。

| 指标 | 旧独立组合 | 本轮教师文字 |
| --- | ---: | ---: |
| 成功回放 | 30/30 | 30/30 |
| 停顿组在线 WER，288参考词 | 36/288＝12.50% | 37/288＝12.85% |
| 打断组在线 WER，189参考词 | 16/189＝8.47% | 16/189＝8.47% |
| 接话：边界后有 complete | 2/10 | 7/10 |
| 接话：边界前有 complete | 8/10 | 7/10 |
| 停顿：区间中有 complete | 5/11区间 | 6/11区间 |
| 打断：区间中有 nonidle | 10/10 | 9/10 |
| 打断：首个 nonidle 中位延迟 | 880ms，分母10 | 1000ms，分母9 |
| 打断：结束边界后有 complete | 3/10 | 5/10 |
| 打断：结束边界前有 complete | 8/10 | 8/10 |

接话组没有独立文字参考，不计算 WER。WER 统一小写、去标点、保留词内撇号；数字与拼写不做语义等价。[UH]／[UM]按发声词计。接话边界前与边界后可以在同一条都出现，不能把7/10边界后覆盖解释为7/10正确：严格“没有边界前 complete，且边界后有 complete”只有1/10（ID91）；打断同口径也只有1/10（ID43）。接话边界后首个 complete 的位置延迟中位310ms（7条），打断为392ms（5条）。

官方边界前的 complete 是时序诊断；缺少逐句语义完成金标，不能把每个早报都当作语义错误。但下列待续结构和漏检可以逐帧核查：

| 个案 | 实际观察 |
| --- | --- |
| 接话 ID51 | 4.96秒正文停在 California was，原始 nonidle 被空增量计数规则改为 complete；7.68秒正文停在 pretty 时又由模型原始预测 complete，官方结束7.82秒 |
| 接话 ID83 | 4.00秒模型原始 complete，当时正文仅到 graduate；5.28秒到 are you going 时由规则改为 complete，官方结束6.32秒 |
| 打断 ID20 | 标注打断11.043—13.229秒内仅有7帧idle、6帧backchannel，没有有效nonidle；实际教师正文持续增长，不能归为旧门控未消费文字 |
| 打断 ID9 | 首个nonidle晚于打断开始约3.101秒，旧轮约1.781秒；12.96秒正文仍在词内前缀时模型原始预测complete |

停顿6个受影响区间来自 Candor ID127／161／40／50、Synthetic ID53／70；Synthetic ID132 本轮区间内没有complete，但5.28秒已有一次，早于5.46秒停顿开始。不能仅凭区间内计数下降就判个案语义合理。

## 在线文字、EOF与规则

30条排空全文与旧轮完全相同，因此没有证据支持 ASR 本身准确率因教师文字接入提高。在线全文只有停顿 ID50、Synthetic ID70 与旧轮不同，均是尾部交付差异；ID50少交付一个参考词使总错误数多1。原始音频之后不追加测试静音，最后一个可配对完整块之后仍有768—3199个真实样本（约48—200ms，30条范围）未作为主处理块消费，部分已经作为640样本前瞻可见；ASR 排空另外处理这些尾部，不能回填在线结果或补造 complete。

本轮7条在线与排空全文不同，均为停顿组：Candor ID161／50、Synthetic ID131／132／41／53／70。排空 WER 为28/288＝9.72%，但不是在线成绩；例如ID131尾部 on top 只在排空出现，ID41即使排空仍缺参考末词。完整文字和逐帧依据保存在本地原始产物中。

3185帧中2503帧教师增量为空，均是实际完成的空步骤，未用 pending 冒充空字。原始状态计数：idle2129、nonidle916、backchannel49、incomplete19、complete72。发布前的原生空增量计数规则共改写32帧：21帧变incomplete、11帧变complete；nonidle→idle分支本轮没有触发。发布complete合计83；个案中的提前complete并非全部由计数分支直接改写产生。该规则会反馈到后续KV，**原始72次complete也不是关闭规则消融后的结果**；本轮未运行该消融，代码已提供独立开关。未知预测0帧，远场过滤拒绝nonidle19帧；backchannel仅观测到，不作其语义准确率评价。

## 顺序、资源与边界

本地取得证据包后独立复查全部3185帧：连续步骤、原始字符拼接、ASR完成≤控制开始≤教师输入≤状态完成≤发布≤释放，以及下一步解码开始≥前步释放全部通过；冻结源文件摘要与 Git `b143bff` 一致。模型每步只读取当前教师增量，Context正文与该步教师全文一致，旧独立组合中的“最新正文不等于实际消费正文”已消除。

合计设备显存采样峰值7574MiB；输出目录约6.2MiB。最大发布积压451.6ms、中位124.3ms，没有通过放慢音频回放掩盖积压，资源停止线均未触发。预检源及正式源使用相同提交和权重。

本轮同时改变门控、文字序列组织、soft reset与初始块对齐，是完整配置对照，不能将每项状态变化单独归因于 teacher forcing。样本仅每轴10条，且没有真实播放、LLM或TTS；nonidle覆盖不是实际停播成功率。当前结论为同步工程合同通过，状态语义质量仍未达可放心交接的程度，现役Agent未切换。

## 产物

远端根 `~/parathink-soulx-duplug/`，源码 `source/b143bff`，正式输出 `runs/nemotron-teacher-fdb30-20261030-r1/`；预检独立保存在 `runs/nemotron-teacher-smoke-20261030-r2/`。冻结源码通过 SFTP 传输后逐包核对摘要，源码包 SHA256 `f2f2d9c16a5209ff293bc44c47b16050cf910996dea7c924e82479d6b1294e4f`。

本地原始证据保存在 `artifacts/soulx/20261030-nemotron-teacher-smoke-r2/` 与 `artifacts/soulx/20261030-nemotron-teacher-fdb30-r1/`，不将逐帧正文和 JSON 推送到 Git。

正式证据包 SHA256 `b1f4176f4b5bf7cdd0d94712fd1666ab1ccb6ddf5096aec2f525819e980b28f4`；预检证据包 `536833e95f7af281f9f7d785688aa4456dc7112ec1e71b10cde7b81787f660d9`。本地可运行 `conda run -n interclarify-dev python scripts/remote/nemotron_teacher_fdb.py analyze --probe artifacts/soulx/20261030-nemotron-teacher-fdb30-r1/probe --output <new-analysis-directory>` 重算。
