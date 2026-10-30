# 远端FDB报告的延迟核查

2026-10-30，按用户要求实际登录贵州HPC，只读核对已有FDB最终报告，没有运行模型、重新评分或修改原始结果。当前报告能给出的是完整系统的响应延迟；没有“临时转写到稳定”的字段，不能将以下数值解释成ASR稳定时间。

## 数据来源与配置

远端原件为`/hpc_stor03/sjtu_home/xuan.zhang/turncontrol-comparison/campaigns/20261030-syn-r1/final-report.json`，SHA256为`cf1b49d865b1babd74444cc94987a7f12979ecc8ae27a1333519e6db7449411e`，本次实际读取确认`passed=true`、1344条唯一记录、评分窗口`zero_to_frozen_input_end`。远端管理状态为complete；与已有本地同摘要报告逐项核对一致。

接话和打断使用`20261029-tts20-full-r2`的实录与已完成评分；Synthetic停顿是后来的计时修复补测，不改变这两个延迟轴。实际配置从接话run的`results/config.json`核实：推理提交`6de0d7096d78ee7de80a4ad1a3aa8084315ebc13`，SenseVoiceSmall＋SoulX-Duplug＋Qwen2.5-7B-Instruct＋IndexTTS1.5，首段20／后续40字符、infer／beam3、shared2双卡布局、seed42。它不是ParaThink新SharedContext前端运行，不能将其成绩当成新接入的实测。

## 核实数值

下表SoulX链路仅统计TOR成功样本；失败不填0。均值直接核对远端聚合，P50／P90／P95及最大值依据原报告逐例latency读取计算，分位数采用线性插值。

| 指标 | 成功／总样本 | 平均 | P50 | P90 | P95 | 最大 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Smooth Turn Taking：接话响应 | 118／119 | 1.2563秒 | 0.975秒 | 2.393秒 | 2.4915秒 | 2.690秒 |
| User Interruption：用户打断后的回复 | 199／200 | 1.7323秒 | 1.600秒 | 2.880秒 | 3.040秒 | 6.960秒 |

latency为标注交接／打断结束锚点至输出评分ASR首词开始的差，按官方规则负值截零；当前逐例字段未保留截零前值，不能据此判断没有提前响应。两轴分别只有1条未满足有效回复判定；这两条不进入延迟分母。评分只观察冻结输入等长窗口，不把录音延长尾部并入分数。

这些数包含输入处理、控制等待、LLM首段生成、TTS与播放等待，首词位置由评分ASR测量，不是物理声卡首音时刻。User Interruption指标衡量打断结束后回复开始的等待，不是取消旧声音的停播延迟。停顿两个轴不报告latency；XTurnix无TOR成功样本，latency为null，不能记为0秒，也不能据自定义接入下的零输出认定模型独立能力。

## 与转写稳定时间的区别

本报告未提供ASR前缀稳定耗时、确认次数、稳定前缀提交策略或修订风险。为确认可追溯性，还只读检查了FDB接话ID1的事件文件，确有原始`asr_result`和调用时间，但不含本项目新前端的完整generation／音频片段账本；若要按上一轮同口径计算稳定时间，需要另做原始轨迹对齐与重置边界审核，不能从1.2563秒中拆出或推算。

因此可直接引用：“当前20／40配置在FDB上的SoulX完整链路平均接话响应延迟为1.256秒，118／119条有效；用户打断后平均回复延迟为1.732秒，199／200条有效。”上一轮[已有轨迹稳定性统计](../20261030-asr-stability/README.md)的1.12秒是不同测量，不与此互换，也不能直接叠加成组合实测值。

## 本地证据与操作边界

复核摘要保存于`artifacts/soulx/20261030-fdb-latency-check/summary.json`，原报告本地副本位于`/home/vitalrubbish/TurnControlComparison/artifacts/remote/tts20-final-report.json`；原始逐例数据按项目约定不提交Git。远端使用既有conda做小型JSON统计，CPU线程1、地址空间2GiB、单命令超时30秒，没有提交GPU作业或修改其他项目文件。
