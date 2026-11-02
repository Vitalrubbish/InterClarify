# 用户话轮的 SharedContext 当前值接口

2026-11-02，用户确认原生SoulX控制＋独立X2Streaming-ASR流式正文，替代逐块联合发布。新合同待[NTF-017](../../issue/NTF-017.md)实现；本轮只设计与建单，不能用旧接口通过记录替代新合同验收。完整方案见[独立流式前端](independent_streaming_frontend.md)。

## 1. 独立更新与原子读取

同一逻辑用户话轮以稳定的session_id／turn_id定位一份当前记录。按用户指定，X2在EOS闭合发射组后以完整词追加正文，SoulX状态就绪即更新状态；无逐块配对、跨路屏障、固定发布周期或complete等待。

Context不接收生成中的BPE／子词草稿。一个闭合组可有多个完整词，按官方组拼接规则一次发布；不要求一词一快照，不为组内各词伪造独立时标，也不改变下游tokenizer。已有正文不可回改，WAIT、WORD、空格或空ASR步都不能替代EOS。

每个写入在短锁内与记录最新值合并，只改变本路字段，再提供完整快照的原子读取。不能将线程此前读到的旧整帧写回，覆盖另一条路的新结果。推理、网络等待和落盘均不持锁；来源内的迟到或重复提交需拒绝，跨路进度允许不同。

仍只提供当前值，不增加历史正文、正文版本、替换patch、历史查询、事件游标或complete锁存。实现时分别提供正文／状态更新入口；旧publish_user_frame的整帧覆盖及单一进度约束须迁移，不假定现实现已支持并发合并。

## 2. 当前记录与时间边界

| 字段组 | 含义 |
| --- | --- |
| session_id／turn_id／status | 稳定身份、open或closed；关闭不等于语义完成 |
| text／source | X2的EOS闭合组累计全文，来源固定为x2_streaming_asr；开放组子词不进入正文，内部SenseVoice文字只作控制与诊断 |
| text_observed_until | 产生该正文时ASR实际已观察的真实采样上界，不证明此前所有词已发射 |
| text_available_at／text_published_at | EOS实际闭合且组拼接完成的时间与Context写入时间，采用可比较单调时钟 |
| state_token／state_accepted | 最新原生五状态及有效性；外层service_state、完成来源分别保留 |
| controller_generation | 原生reset后的控制代次，不是新逻辑话轮 |
| state_processed_until／state_observed_until | 状态主块与完整音频观察的真实采样上界，padding另记 |
| state_available_at／state_published_at | 状态实际可用与发布的可比较单调时间 |
| 完整性字段 | 区分传输／整理缺口和ASR尾部状态；没有可靠尾词信号则为unknown |

旧processed_until若保留，只兼容表示SoulX主块截止；正文更新不要求它增长。各组时序只由所属路推进，状态变化不刷新正文时间，正文变化不刷新状态时间。原子快照不表示音文同块对齐，也不保证尾词完整。ASR暂时无新增token不等于静音或句子结束。

## 3. 生命周期与正文来源

控制器reset不清空正文，不结束X2Streaming-ASR，不创建新turn_id；外部PCM账本与内部控制缓存分开管理。user_complete不触发ASR结束、正文重识别或final标记。内部SenseVoice完整话轮识别仍可按原生服务执行，结果不覆盖共享正文。

X2已闭合组按官方规则形成只追加累计正文，不经SenseVoice拼合或SoulX控制归一化。空返回和识别异常不清空已有文字；不允许缺少结果时换成内部窗口文字。任一路失败显式终止验证样本并保留记录。

只有运行时显式关闭才终结逻辑话轮；关闭后拒绝两路迟到回调。EOF不补造complete或EOS，不强制提交开放组；在线已闭合正文、开放组token、未处理真实采样和显式drain诊断分别保留，排空结果不回填在线记录。组闭合不等于整轮转写完成。

## 4. 下游消费与直接停止

Layer 1／2在各自输入边界读取最新快照；一次更新不创建新用户消息，不自动改变已建立的模型输入／KV、已生成或已听内容。正文、状态与元数据分开编码，ASR标签没有控制权限。

当前状态会被覆盖，慢消费者仍可能跳过短暂complete；本轮不增加历史投递或锁存。普通正式回答仍由Layer 1在当前turn实际读到有效complete后生成；本轮不额外增加尾词等待门或语义否决层，尾词尚未到达的风险需在后续接入中验证。

活动输出期间有效nonidle直接调用唯一停止执行点，不等待ASR、Context消费者或日志；其他状态不映射为start／keep。停止请求与物理停播分别记录。

## 5. 验收与历史

NTF-017检查交错更新无丢失、各路时间不串写、reset连续、关闭拒绝迟到和直接停止去重；真实模型的完整预热、时序与质量由NTF-018／019验证。每个实现文件同步更新docs同路径说明，既有容量限额保留。

历史[160ms联合发布](streaming_transcript_publication.md)、[双ASR配对发布](../../archive/dev/SoulX-Duplug/dual_asr_publication.md)与教师同步均已被本合同替代。旧[六视图接口检查](../../../reports/soulx/20261030-current-context-test/README.md)和[双ASR18/30报告](../../../reports/soulx/20261031-dual-asr-publication/README.md)保留原解释，不作为新接口通过证据。
