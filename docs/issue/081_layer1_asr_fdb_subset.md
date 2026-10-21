# Issue 081：原1k ASR候选重跑固定FDB子集

状态：远端调度已接收，2026-10-21。用户授权先重跑FDB子集，不运行完整319例，不重训或切换线上候选。

## 冻结范围

使用030历史25例/70份输入资产，五类各5例：candor_pause_handling、synthetic_pause_handling、candor_turn_taking、synthetic_user_interruption、icc_backchannel。原清单摘要`d5885326eedab8f450843d3737ce08ccf98ebe6de89d7958b5628a8ba731cc40`以文件实际核验为准；代码同时核对父协议登记摘要，禁止换样本或根据结果挑权重。

新候选`ASR_R4_delayed_punctuation`最终checkpoint `d1f4d05e4ed1b29dbe8550ffaa02be389673975f7929b33ec1420ef2d70c44a1`。旧对照`T2_R3_delayed_start`为`266a37a28699d0c3f36b6a6305374bc89a1a2ff2af7a37fd1eb4caf1ad915346`，其训练目录已不在现役路径，不能直接重跑。调整为只执行新候选25例；接话/打断对照从065已完成的同运行配置完整FDB逐例结果中提取相同5例，不与完整319例聚合比例混比。其余三类旧子集早于现役TTS/KV策略，仅作带限制的历史观察，不称为匹配因果对照。

现役X-Talk d6dc3bf、Nemotron EN160、Kokoro af_heart、600ms micro-turn、首段300ms/后续1200ms、会话KV复用、duplex_greedy_v1/单beam/repetition_penalty=1.0、系统backchannel关闭。每例独立会话，正式output.wav与原音频等长，另存5秒连续静音尾窗仅供诊断。单一仲裁和播放路径不改。

## 实现、执行与评分

适配现有子集入口以登记ASR最终候选和当前运行快照，核验训练/重载/数据摘要及权重身份；不复用历史134文件旧运行快照。ASR→TTS→模型顺序预热，ASR warmup180秒，health核对进程存活。保留全部生成ID及输入/时间线。

回放后停止推理服务再评分。复用现有完整两轴评分模块，仅在独立子集评分进程把两轴预期数设为各5；官方Parakeet转写与Smooth官方评分，Interruption沿冻结官方时序规则重算，GPT明确待补，不调用API。其余三类保留原音频窗与诊断尾窗的播放/暂停/附和/协议证据，不冒称官方评分通过或全面人工听审。

资源：远端调度2×4090/16CPU/64GiB，worker0、线程4、并发1、4小时硬上限；输出20GiB、空闲盘至少50GiB、单文件8GiB。使用现役conda、冻结源码worktree，权重只读引用，失败与退出码保留，不在登录节点运行真实模型。

- [ ] 输入、源码、当前运行配置及两候选身份冻结，相关检查通过。
- [ ] 新候选25会话完成，传输/协议/音频输出和原窗/尾窗覆盖分别记录。
- [ ] 新候选两轴各5例官方对齐及授权时序评分完成，对照提取065同5例；漏答/负延迟如实保留，GPT pending。
- [ ] 数值对照、逐例证据和退出码回收，报告不把5例开发回归视为泛化能力结论，完成后归档。

作业`job-179259065594024820461-xuan-zhang`，冻结源码805a12a；路径和阶段状态见[本轮报告](../../reports/fdb/20261021-asr-subset-r1/README.md)。
