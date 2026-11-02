# 用户话轮的 SharedContext 当前值接口

2026-11-02，状态：当前接口设计，尚未实施。用户恢复[NTF-015—020](../../issue/README.md)为active；正文／状态独立更新由NTF-017实施，仅complete交接由NTF-020实施，实际链路由NTF-018／019验证，见[恢复记录](../../reports/soulx/20261102-external-asr-plan-restore/README.md)与[独立前端](independent_streaming_frontend.md)。本次仅恢复设计入口。

## 1. 独立更新与原子读取

同一逻辑用户话轮以稳定session_id／turn_id定位一份当前记录。X2在EOS闭合组后追加完整词，SoulX原始状态立即记录；四类非complete状态立即供下游读取，只有complete用于开始回答时经过交接同步。结果发布无逐块配对或固定周期；模型推进按[设计第2.1节](independent_streaming_frontend.md#21-每160ms音频步的推进屏障)执行每160ms屏障，X2两个80ms步与SoulX本步均完成后才进入下一周期。交接pending不增加新的推进阻塞。

Context不接收生成中的BPE／子词草稿。一个闭合组可有多个完整词，按官方组拼接规则一次发布；不要求一词一快照，不为组内各词伪造独立时标，也不改变下游tokenizer。已有正文不可回改，WAIT、WORD、空格或空ASR步都不能替代EOS。

每个写入在短锁内与记录最新值合并，只改变本路字段，再提供完整快照的原子读取。不能将线程此前读到的旧整帧写回，覆盖另一条路的新结果。推理、网络等待和落盘均不持锁；来源内的迟到或重复提交需拒绝，跨路进度允许不同。

仍只提供当前值，不增加历史正文、正文版本、替换patch、历史查询或事件游标。本次允许每话轮最多一条当前complete交接记录，用于有界等待与取消，替代此前完全不保留complete的约束；不建立历史事件队列或消费ack。实现时分别提供正文、原始状态、解码进度和交接更新入口；旧publish_user_frame的整帧覆盖及单一进度约束须迁移，不假定现实现已支持。

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
| asr_processed_until／asr_observed_until／asr_progress_available_at | X2完成整步解码的主块、真实观察边界和可用时间；WAIT无新字也推进，不等于正文观察范围 |
| completion_id／completion_status | 单个当前交接身份与none／pending／ready／cancelled／timed_out；原始complete不等于ready |
| completion_target_sample／deadline／ready_at | 创建时固定的原始complete实际观察截止、交接截止及实际ready时间；包含原始来源与对应正文已提交组数 |
| 完整性字段 | 区分传输／整理缺口和ASR尾部状态；没有可靠尾词信号则为unknown |

旧processed_until若保留，只兼容表示SoulX主块截止；正文更新不要求它增长。各组时序只由所属路推进，状态变化不刷新正文时间，正文变化不刷新状态时间。原子快照不表示音文同块对齐，也不保证尾词完整。ASR暂时无新增token不等于静音或句子结束。

解码进度独立于正文：X2收包、特征预取不能推进已完成进度，必须完成该80ms步及其DECODE；WAIT完成而正文不变时，仅推进进度字段，不改text_available_at。否则complete会因“没有新字就没有进度”而无限等待。调度器另持有本160ms步的两侧完成标记与释放时间；它不要求当前文字变更，也不以completion_status=ready为释放条件。

## 3. 生命周期与正文来源

控制器reset不清空正文，不结束X2Streaming-ASR，不创建新turn_id；外部PCM账本与内部控制缓存分开管理。user_complete不触发ASR结束、正文重识别或final标记。内部SenseVoice完整话轮识别仍可按原生服务执行，结果不覆盖共享正文。

X2已闭合组按官方规则形成只追加累计正文，不经SenseVoice拼合或SoulX控制归一化。空返回和识别异常不清空已有文字；不允许缺少结果时换成内部窗口文字。任一路失败显式终止验证样本并保留记录。

只有运行时显式关闭才终结逻辑话轮；关闭后拒绝两路迟到回调。EOF不补造complete或EOS，不强制提交开放组；在线已闭合正文、开放组token、未处理真实采样和显式drain诊断分别保留，排空结果不回填在线记录。组闭合不等于整轮转写完成。

## 4. 下游消费与直接停止

Layer 1／2在各自输入边界读取最新快照；一次更新不创建新用户消息，不自动改变已建立的模型输入／KV、已生成或已听内容。正文、状态与元数据分开编码，ASR标签没有控制权限。

四类非complete原始状态直接供Layer 1读取。原始complete只作诊断与pending来源，不作为已可回答的complete token直接编码到Layer 1输入。必须在交接ready后，将对应complete与当前已闭合正文在同一输入边界交付；仅state_accepted=true不足以开始正式回答。普通回答仍在当前turn现有生成流程内开始，不新建独立回答调用。

交接固定原始complete的state_observed_until为目标C，等待X2完成覆盖C及原生真实前瞻的步骤、当前DECODE真实EOS闭合、相应闭合组全部提交；领先时可立即ready，不要求新词或下一个EOS。所有检查及ready标记与最新正文在同一锁内提交；正文不复制为历史版本，保留对应已提交组数供审计。

pending和尚未使用的ready遇后到有效nonidle／incomplete即取消；nonidle直接停止仍即时执行。idle／backchannel和内部reset不取消，ready记录不随下一帧idle消失。Layer 1按completion_id最多使用一次，不增加消费ack；关闭或新合法交接替换后，迟到结果不能复活旧候选。取消与放行在同一执行域串行判断，已构造的模型输入不会被Context自动回改。

交接采用非阻塞定时器。首轮completion_wait_timeout_ms=800，deadline与原始complete主块到交接的既有800ms总延迟停止线取较早者，不能叠加预算；重复complete不续期。超时则timed_out、验证样本失败并保留证据，不强制ready或提交半词。EOF真实前瞻不足不得用drain补成在线就绪。

ready只表示上述计算／提交同步通过，不保证此前所有词已发射；尾词未知保留unknown并统计ready后追加的文字。初版不增加空步计数、固定160／320ms延后或必须等待下一个EOS的规则，具体边界见[设计第4.1节](independent_streaming_frontend.md#41-仅-complete-的回答交接同步)。

活动输出期间有效nonidle直接调用唯一停止执行点，不等待ASR、Context消费者或日志；其他状态不映射为start／keep。停止请求与物理停播分别记录。

## 5. 验收与历史

NTF-017／020已恢复为active，负责交错更新、生命周期及complete同步；NTF-018／019负责完整预热和原始状态／ready交接验收。以上仍为待实施合同，不能因工作单恢复就当作已交付。原始状态与交接质量仍须分别报告，不能用延后ready伪装SoulX原始状态改善。

历史[160ms联合发布](streaming_transcript_publication.md)、[双ASR配对发布](../../archive/dev/SoulX-Duplug/dual_asr_publication.md)与教师同步均已被本合同替代。旧[六视图接口检查](../../../reports/soulx/20261030-current-context-test/README.md)和[双ASR18/30报告](../../../reports/soulx/20261031-dual-asr-publication/README.md)保留原解释，不作为新接口通过证据。

## 6. 160ms推进与Context更新

屏障只限制下一音频步的模型调用。当前X2第一个80ms闭合组、两次WAIT进度和SoulX状态均各自就绪更新，Context锁、日志及消费者不阻塞整步完成回执。step_id不表示文字版本或同一声学词尾，实际主块／观察范围继续分别保存；单个原子快照可处于本周期两侧先后完成的中间状态。

当complete目标所需的真实观察范围只能在后续周期覆盖时，先按两侧完成条件释放当前推进屏障，交接保持pending并独立计时。禁止以ready等待屏障、再以屏障等待ready；EOF未完成周期不能借drain补成在线交接。
