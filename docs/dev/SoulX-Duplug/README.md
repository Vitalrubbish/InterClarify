# SoulX-Duplug 路线

更新：2026-11-02。用户要求清除comparison端历史实验并重新clone官方仓库。当前以本地 [third_party/soulx-duplug](../../../third_party/soulx-duplug) 子模块为可审查源码入口，远端改用ParaThink独立根下新克隆的`upstream/soulx-duplug`，版本与说明见[依赖文档](../../third_party/soulx-duplug.md)。旧comparison加载器和实验worktree退役，不作为新实验入口。

当前采用**原生SenseVoice控制＋独立X2正文＋仅complete交接同步**。NTF-015／016已交付原生封装、冻结加载器、同源PCM／160ms屏障和独立X2适配，本地契约验收后归档，见[交付记录](../../reports/soulx/20261102-native-independent-frontend/README.md)。[NTF-017／020／018／019](../../issue/README.md)继续待实施。NTF-021／022相关实现分支已撤回，NTF-023—025未实施归档，历史范围见[恢复记录](../../reports/soulx/20261102-external-asr-plan-restore/README.md)。

## 当前实施顺序

按015→016→017→020→018→019依次完成原生封装、同源音频／X2正文、异步Context、complete交接、完整预热和固定FDB30验收。预热预检通过才启动正式30条；旧教师实验不作为新封装等价性或双路实时性通过证据。

## 当前前端设计

- SoulX保留内部SenseVoice教师、门控、窗口修订、状态反馈和原生reset，外接正文不注入状态KV，内部文字只作控制与诊断。
- 同一持续PCM分别驱动控制与X2；X2按原生80ms步推进，真实EOS闭合组后按完整词追加正文，不暴露子词草稿，多词组一次可见。
- 两路每160ms完成X2两个80ms步及SoulX本步后才推进下一周期；结果各自就绪更新所属Context字段，短锁合并并原子读取，无配对发布等待；控制器reset不清正文或交接，不结束X2。
- 四类非complete立即交付，有效nonidle直接停止；complete只有真实进度追齐且正文已提交后才ready。后续nonidle／incomplete取消旧交接，超时不强行放行，ready不保证尾词必齐。
- 完整合同见[独立前端](independent_streaming_frontend.md)及[Context接口](shared_context_interface.md)。下游尚未接入，现役Agent不因计划恢复而切换。

## 历史合同与验证记录

以下为历史改造记录，不作为当前执行合同。NTF-007—012教师实验保留证据；X2同卡30/30、延迟及规范性通过，状态未整体改善，见[最终报告](../../reports/soulx/20261101-ntf012-x2-teacher-fdb30/README.md)与[归因](../../reports/soulx/20261101-ntf012-x2-teacher-fdb30/regression_analysis.md)。历史已授权或现役等措辞只描述当时状态，不恢复作业。

- 前端包含Nemotron教师文本、SoulX音频编码及状态预测；同一活动话轮的SharedContext正文只用Nemotron一个权威来源，不再使用SenseVoice控制文字或双路配对队列。NTF-007/008 已交付逐帧即时发布、音频embedding有界缓冲和 `A_n→T_n→EOS` 对齐，`PairedPublisher`及complete后整轮重识别已删除。读取与关闭规则见[接口设计](shared_context_interface.md)，最新结果见[NTF-008报告](../../../reports/soulx/20261101-ntf008-teacher-buffer/README.md)。
- 2026-10-31历史：曾采用[双ASR缓存发布](../../archive/dev/SoulX-Duplug/dual_asr_publication.md)，SenseVoice提供控制文字、Nemotron独立提供正文，状态配对后发布。NTF-005正式18/30完整、12条触及800ms停止线，实时与状态质量未通过，见[报告](../../../reports/soulx/20261031-dual-asr-publication/README.md)。该路线已由 Nemotron 唯一教师文本取代，代码与文档已归档。

2026-10-30此前按用户明确指令回滚：撤回`bd86478`的原生delta草稿＋controller片段整段覆盖，撤回`b00afac`与`6930fa7`的固定起点重识别候选文档。运行代码与前端测试恢复到`484ca32`对应基线，保留160ms正文／状态联合覆盖接口；这会恢复旧窗口整理及已知gap，并不表示旧方案质量达标。历史测试报告、原始证据和离线汇总脚本保留，未恢复旧Nemotron组合代码或提交新远端作业。既有conda下前端5项、SharedContext及TextTurn Context共7项、独立Nemotron服务5项检查全部通过；用户原有未提交修改保持不变。

用户已授权 Nemotron 按160ms持续解码、直接 teacher forcing 文字，0.6B仅发布用户状态；两份模型权重固定，通过逐块屏障同步推进，见[工程同步方案](nemotron_teacher_forcing.md)。接入及 FDB 三轴各10条实测已完成：3185帧同步顺序通过，状态质量没有整体改善，见[报告](../../../reports/soulx/20261030-nemotron-teacher-fdb30/README.md)；[工作单](../../issue/README.md)已归档。SenseVoice及旧独立组合保留为历史基线，不恢复其作业。

- 前端持续接收音频，可与下游表达、思考并发执行。Layer 0 仍负责系统附和时机；未来 CoT 从 Context 反馈至前端，当前不实现条件化扩展。
- SoulX 保留音频路径和原生五类用户状态，全部送入 Layer 1；普通正式回答在当前 turn 读取对应 `user_complete` 后生成，不额外发起独立回答调用。
- 活动输出期间有效 `user_nonidle` 额外直接触发停止，涵盖 preparing 和 playing；其他状态不进入输出运行时，不映射为 start 或 keep。完整路径见[架构第 2.2 节](../../research_design/architecture.md#22-前端状态与系统附和)。
- 后续联合音频 token、转写文本 token 与已发布 CoT token 的目标已确认，当前不实现。输入序列、缓存、触发、输出是否扩展及训练方式见[架构第 2.5 节](../../research_design/architecture.md#25-soulx-的-cot-条件化控制)。
- 保持单一仲裁执行点、单一 TTS 播放所有权和已听内容不可撤销；

## 验证设计与实施状态

最新配对修复已交付：首个ASR特殊块仅初始化，后续按真实读取范围覆盖SoulX主块截止后再预测，保留原空增量规则。预检3/3通过，但完整复测25/30、28/30均触及800ms积压线；同样本部分状态指标改善，整体实时未验收，见[配对复测报告](../../../reports/soulx/20261030-nemotron-teacher-alignment/README.md)。工作单NTF-003已归档，不继续扩大实现或占用作业。

2026-10-30用户已指令撤下[Nemotron＋SoulX独立适配](nemotron_integration.md)，该路线保留为历史实验，专用代码／运行入口已移除。此前复用单一Nemotron前缀来源、SoulX音频与五状态；四视图真实时钟探针通过结构和消费一致性检查，105次正文更新、124条状态，回调至正文可见P95约6.06ms，不额外等1秒。尚未切换首版或现役Agent，完成状态时机、完整词提交和EOF尾部仍有边界，见[实际报告](../../../reports/soulx/20261030-nemotron-integration/README.md)。

已按[ASR 前端设计](asr_frontend_design.md)实现原始文本与标签保全、滑窗修订、五状态及其文本依据、SharedContext事务与独立消费者。六视图实时回放中145次ASR与299条状态写入一致，两个消费者各读取912事件；2个非静音视图关闭时仍有gap，低音量原幅度识别明显较差，backchannel实际音频预测未覆盖。结果、失败修复及延迟见[实现与检查报告](../../../reports/soulx/20261029-shared-context/README.md)，不能据此宣称识别或五状态语义质量全面通过。

已登录贵州 HPC 确认并复用 TurnControlComparison 的两组模型、冻结源码和共用 conda；最初单卡组件加载检查见[部署说明](deployment.md)和[部署报告](../../../reports/soulx/20261029-frontend-deployment/README.md)。随后已提供独立Context实现及状态事件；Layer 1状态token编码、下游模型和真实播放仍待接入，不继承其他项目的 `speak` 动作映射。

此前[质量测试方案](quality_test.md)保留为 Nemotron 历史设计：全量回放英文 Easy Turn 集共 617 条，仅评价 Listen 影子观察与 Context 接口，不包含下游 LLM 或实际播放。首版 ASR 已调整，该方案不能直接执行；若后续复用数据集，须先冻结 SenseVoiceSmall 配置与窗口转写合同，执行另行确认。

首版已用实际只读消费者核对话轮快照、修订、重置历史和中间文字可读，仍需区分正文覆盖与接口搬运。Nemotron 的音频观察配对、词内增量和缓存适配留待后续。此前自建场景、额外开发集和200条抽样方案已撤回；TextTurn／XTurnix仅保留历史协议与证据，不继承其专属输入、动作token或训练门槛。

实施顺序及资源见[工程计划](../../engineering_implementation.md)，本轮输入与执行范围见[检查任务说明](frontend_audio_check.md)。实现及少量契约测试均有同路径中文说明；工作单仅按明确建单指令建立，本次教师文字接入与实验已按用户指令建单，仍不训练。

2026-10-31按用户授权实施NTF-004：恢复官方控制文字格式与门控，保留Nemotron原始正文发布、音频覆盖配对、soft reset和原状态规则；独立审计待消费文字与缓存修订。本地30项、远端预检3/3通过；正式25/30完整、5条积压触限，状态未整体改善，EOF仍有待消费尾部。详见[对照报告](../../../reports/soulx/20261031-nemotron-teacher-gate/README.md)。工作单已归档，队列已清空。

用户新增的计算推进屏障详见[设计第2.1节](independent_streaming_frontend.md#21-每160ms音频步的推进屏障)：当前组内token连续解至EOS，WAIT算步完成；屏障不等complete交接ready，不阻塞实时收音或当前有效nonidle停止。
