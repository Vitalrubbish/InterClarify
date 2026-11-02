# 用户话轮的 SharedContext 联合快照接口

2026-11-02，状态：NTF-017待实施合同。用户最新确认每160ms批次在SoulX与X2均处理完成后，统一写入文本和状态token；不写原始PCM，也不设置前端专用停止钩子。此修订替代此前正文／状态独立立即写入方案。NTF-015／016已交付的内部回调仍待迁移，历史结果见[交付记录](../../reports/soulx/20261102-native-independent-frontend/README.md)。[工作单](../../issue/NTF-017.md)和[前端设计](independent_streaming_frontend.md)为实施依据。

## 1. 每160ms联合提交

同一逻辑用户话轮以稳定session_id／turn_id定位一份当前记录，step_id标记160ms源音频批次。SoulX完成本次原生调用及其反馈、服务／reset，X2顺序完成两个80ms音频步及可能的DECODE至真实EOS，才允许一次联合写入。两路可以串行计算；任何先完成结果均只留在本批次有界暂存器。

写入内容为本批次最新X2闭合组累计正文、SoulX状态token／有效性、控制代次、服务来源及两路真实进度。Context不保存PCM、开放组子词或两路计算中的半帧。X2第一帧产生的文字等本160ms批次完成后可见；WAIT无新字仍完成本步，联合提交保留原正文，不等新词、下一组EOS或整轮识别。

联合入口在短锁内校验身份、当前批次、两侧完成及追加前缀，合并最新生命周期／交接字段，再一次替换当前前端观察。读取返回完整副本，只能看到上一个或当前完整批次。不能把工作线程此前读取的整份快照回写覆盖较新交接或生命周期。推理、网络、日志和消费者不持该锁。

严格顺序为两路完成→联合提交成功→允许下一批次模型推进；写入失败即终止样本，不释放下一步。输入生产者持续按真实时钟到达。complete ready不作为该提交或下一周期推进条件；消费者无需ack。仍不增加历史正文、版本查询、patch或无界待发布队列。

## 2. 当前记录与时间边界

| 字段组 | 含义 |
| --- | --- |
| session_id／turn_id／status | 稳定身份与open／closed，内部reset不创建新话轮 |
| step_id／batch_published_at | 最新已联合提交的源批次和原子写入时间，不是历史正文版本 |
| source／text／committed_groups | 来源固定x2_streaming_asr、EOS闭合组累计全文及已提交组数，不含子词草稿 |
| text_observed_until／text_available_at／text_published_at | 产生当前正文的真实观察上界、实际闭合拼接时间和首次联合发布该正文的时间；无新字时不刷新 |
| state_token／state_accepted／controller_generation | 本批次原生五状态、有效性与控制代次；service_state和完成来源分别记录 |
| state_processed_until／state_observed_until／state_available_at／state_published_at | 本批次状态的真实主块、观察边界、原始可用时间及联合发布时间，padding另计 |
| asr_processed_until／asr_observed_until／asr_progress_available_at | X2本批次最后实际完成80ms步的真实处理／观察边界及实际可用时间；WAIT也推进 |
| completion_id／completion_status | 至多一条当前交接及none／pending／ready／cancelled／timed_out，原始complete不等于ready |
| completion_target_sample／deadline／ready_at | 固定原始complete实际观察目标、交接截止与实际ready时间，保留对应已提交组数 |
| 完整性 | 传输／整理缺口、后端明确尾部状态；缺乏可靠尾词信号时为unknown |

有新正文时，text_published_at与本批次state_published_at均取batch_published_at；各自available_at保留模型实际完成时刻。正文不变时保留此前text_observed_until、text_available_at和text_published_at，继续推进当前批次、状态及ASR进度。可用到发布的等待必须包含本160ms屏障，不能回填成提前可见。

旧processed_until若保留，只兼容SoulX真实主块截止。两侧同一step_id不证明实际观察范围相同：startup／reset padding、回看及前瞻沿用[采样映射](independent_streaming_frontend.md#22-ntf-015016采样映射与实现冻结)。ASR处理／观察范围不保证此前所有词已发射，WAIT不等于静音或句子结束。

## 3. 生命周期与失败

模型侧只保存当前批次的一条控制回执、两条80ms进度和至多两组闭合正文。X2每步进度仍在内部诊断中分别记录，供后续联合提交校验；收包、特征预取不算解码完成。

reset不结束X2、不清空正文、不改变全局step_id；原生SenseVoice整轮识别仍属控制诊断，不覆盖正文。complete不触发ASR结束、额外重识别或final标记。EOF只按实际存在的终止帧验收完整批次，不补造状态或EOS；开放组、未处理PCM和drain保留在诊断中，不回填在线正文。

任一路错误、缺失／重复／过期回执、Context校验／容量失败或关闭／取消均不得提交半帧，上一完整快照保留，失败样本显式停止。关闭后拒绝迟到回调，旧结果不能重开话轮。原子关闭／交接超时可更新生命周期元数据，但不能在两路未完成时单独刷新文本、状态token或ASR进度。

## 4. 下游消费与complete交接

Layer 1／2在各自合法输入边界读取同一份已提交文本和状态。一次联合写入不创建新用户消息，不自动回改已构造的模型输入、KV、生成历史或已听内容。前端不直接操作输出；不再为nonidle设置早于联合提交的停止钩子。下游读取本批次快照后按既有输出生命周期处理，唯一输出执行点、停止幂等和实际停播确认仍保留。

所有五状态采用相同的160ms提交门槛。四类非complete在提交后可供正常消费；原始complete同样在本批次提交，只有NTF-020额外数据交接通过才可用于正式回答。候选固定原始state_observed_until为C、原始state_available_at与控制代次，不能把批次发布时间当作新的起算点。

NTF-020只使用已提交批次的真实ASR进度和闭合正文检查ready；若本批次已覆盖目标即可在同次事务中ready，否则pending直到后续已联合提交批次满足条件。对应nonidle／incomplete也在所属批次提交后才取消旧候选，不使用未发布的内部状态提前改变下游行为。idle／backchannel和内部reset不自动取消；Layer 1按completion_id至多使用一次。

ready及取消与最新正文在同一锁内复核，不能覆盖更新批次。非阻塞超时定时器只修改交接元数据；首轮timeout为800ms，deadline与原始complete到ready的既有800ms总延迟线取较早者，屏障和提交等待计入同一预算。重复complete不续期，超时标记失败，不强行ready；EOF不能用drain补足在线覆盖。

屏障完成不代表尾词齐备；ready只承诺真实计算与正文提交条件。继续保留unknown尾部并统计ready后新增文字，不增加空步、固定额外延时或强制EOS规则。

## 5. 验收与迁移

NTF-017覆盖两种完成顺序、暂存不可见、一次联合提交、WAIT不刷新正文时间、提交成功后才推进、并发读取／关闭和失败无半帧。NTF-020覆盖仅基于已提交批次的ready／取消／超时，NTF-018／019记录原始计算、屏障等待、联合发布时间及读取时间，不用发布延迟伪装原始状态改善。

现有015／016的独立回调和停止钩子是此前合同的实现事实；NTF-017需调整SharedContext及三份适配模块、测试和同路径说明。当前未实施本合同，也未重新运行模型。旧[160ms联合发布](streaming_transcript_publication.md)只作历史参考，不恢复教师注入、整个旧buffer回写或基于步号伪造真实窗口对齐。
