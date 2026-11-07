# 通用前端回放与预热

对应 `scripts/remote/native_frontend_probe.py`。模块为 SoulX＋X2 提供预热、同源回放、逐批观察和清理，当前[半双工评测](fdb30_half_duplex.md)直接复用这些函数；独立运行可选择 `dual-limited`、`dual-full`、`single-full` 诊断条件。旧前端专用评分已退役。

## 类与会话

`SingleLane` 提供原生控制参考，保持连续 PCM、真实到达时钟与默认 4MiB 上限。reset 回收未消费 PCM 后，原生调用数可能超过名义批数，按下界检查并保存尾部余量；双路仍按实际 160ms 批次严格核验。

`fresh` 重置 seed42 和原生会话，双路创建独立 X2 会话及私有 SharedContext，模型权重常驻。`cleanup` 关闭观察、清理控制 KV、PCM、文字和回调，并清理 X2 会话；保留权重与内核缓存，核对 reset 缓冲摘要和清理结果。

`replay` 使用唯一生产者，按真实时钟将 80ms 音频包写入有界账本，计算屏障不暂停送音。逐批记录回执、采样范围、状态、EOS 正文、联合快照、读取时刻和积压，EOF 只处理实际存在的半批。可选消费回调在联合发布后触发下游，完成回调在前端清理前关闭输出。

`fresh`／`replay` 的 `pcm_limit_bytes` 默认 4MiB，完整半双工评测显式传入 16MiB；可选诊断静音由评测入口添加，不回填历史轨迹。`compress=True` 无损 gzip 保存逐帧字段，写盘不持 Context 锁；长延迟不按旧 800ms 条件中止。

## 预热与比较

`prepare_warmup` 对固定英文语音使用 RMS0.05／峰值0.9 增益、PCM16 往返量化及既定静音尾部，保存增益、摘要和策略标识；静音或非有限输入拒绝进入预热。`full_warmup` 先覆盖多种 SenseVoice 长度，再运行两轮完整拓扑，检查文字修订、有效 complete、reset、WAIT 和多 token EOS。所有实际模型调用在 inference_mode 中执行。

SoulX 在回放线程执行，X2 使用同一常驻辅助线程，预热与正式回放不交换执行者。运行记录保存实际线程、CPU 预算、控制执行策略及 X2 ready 信息；缺失覆盖不作为就绪成功。

`compare_native` 用相同 PCM、种子和 reset 比较官方过程与观测封装。默认策略只允许 complete 服务整段识别被跳过，其他音频 token、短窗识别、状态、服务与缓冲差异均拒绝；显式关闭跳过可运行严格比较。`full_warmup(check_native_equivalence=False)` 不执行该比较，并记录 `disabled_by_user`、`passed=null`。当前完整系统按用户要求使用关闭配置，覆盖与清理检查仍执行。

`limited_warmup` 保留有限控制覆盖参考，X2 仍使用相同真实语音预热；它只用于诊断，不等同于完整预热就绪。

## 入口与记录

`select_samples` 对默认 preflight 选择固定三条；通用 `--suite fdb30` 支持完整条件，要求固定 manifest 及已验收证据 JSON／SHA256，门槛在加载模型前核对。旧专用作业包装已经移除，完整系统使用自己的冻结入口与验收合同。

`run` 冻结配置并执行预热、清理与指定诊断套件，保存逐例错误、退出结果和资源信息。`summarize` 分别汇总首帧、稳定阶段、主块／观察延迟、SenseVoice 与 X2 耗时，以及 P50／P95／max；子阶段不得与父阶段重复求和。测试只验证这些边界，真实权重与性能验证须在远端调度作业进行。
