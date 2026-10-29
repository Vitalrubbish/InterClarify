# 工程实施计划

更新：2026-10-29。本文按已确认的 SoulX-Duplug 路线整理实施顺序，删除重复旧选型与运行日志；研究范围和模块合同分别见[研究方案](research_design.md)与[架构设计](research_design/architecture.md)。新链路尚未接入，本次整理不启动适配、训练或远端作业。

## 1. 运行底座与目标

现役底座仍为 X-Talk `ca9b23c`、DuplexCascade、Nemotron EN160 与 Kokoro，参数见[运行配置](runtime_baseline.md)。目标控制器为 **SoulX-Duplug**；ASR 优先适配 Nemotron，失败或组合实测不满足后续确认要求时回退 SenseVoiceSmall，依据见[适配调研](dev/SoulX-Duplug/asr_adapter_assessment.md)。同一活动话轮只使用一个权威转写来源。

| 模块 | 实施职责 |
| --- | --- |
| ASR 与 Shared Context | 持续发布版本化转写，提供下游快照和有序更新读取；写入不等待完成判断 |
| SoulX-Duplug | 保留音频路径和原生五类用户状态，衔接在线转写；状态全部作为 Layer 1 输入 |
| Layer 1 | 在正常输入边界读取状态与转写，在当前 turn 看到对应 `user_complete` 后开始普通正式回答；负责思考请求与表达 |
| 输出运行时 | 统一管理 FIFO、TTS 与播放器；活动输出期间的有效 `user_nonidle` 额外直接触发停止，准备阶段也可取消 |
| Layer 2（后续） | 只发布内部 CoT，供 SoulX 与 Layer 1 使用，不生成话轮建议或待播正文 |
| Layer 0（后续） | 只预测系统附和时机，正文由表达路径提供，经同一输出运行时发声 |

其他用户状态不进入输出运行时，不映射为 start 或 keep；完成状态不新建独立 LLM 回答调用。系统保持唯一仲裁执行点与单一 TTS 播放所有权，已听内容不可撤销。状态、生成、提交、取消与实际播放分别记录，具体打断及恢复规则见[架构第 2 节](research_design/architecture.md#2-模块与动作边界)。

## 2. 前端适配顺序

1. **冻结协议与资产**：锁定模型、上游代码与环境版本，核算显存和磁盘峰值，不升级现役 ASR/TTS 环境。
2. **衔接音频与文本**：Nemotron 与 SoulX 接收同一持续音频，按真实解码完成事件、观察边界和文本版本配对，验证词内增量、文本单次消费及缓存修订。ASR 未就绪不能伪装为空增量，无新增文字不等于声学静音。
3. **交付 Context 接口**：按稳定 `turn_id` 写入转写，提供快照和按游标读取；用只读消费者替身核查幂等、乱序、关闭及 EOF 分离，见[接口合同](dev/SoulX-Duplug/shared_context_interface.md)。
4. **验证组合表现**：此前 [Easy Turn 英文集方案](dev/SoulX-Duplug/quality_test.md)计划全量 617 条 Listen 影子回放，报告完整性判断、原生／兜底分支、实测延迟与失败覆盖，执行仍待重新确认。它不承担附和、打断或可听播放验收。
5. **后续完整链路**：明确状态输入编码、Layer 1 生成边界和直接打断接口，再验证输出标识失效、停播确认及新输出恢复；旧 DuplexCascade 控制不能与新路径重复执行。

160ms 是 ASR 名义分块，不是组合延迟承诺。若触发 SenseVoiceSmall 回退，先独立冻结配置、转写修订及 Context 映射，不在活动话轮中热切换。

## 3. 后续研究模块

SoulX 联合音频 token、转写文本 token 与已发布 CoT token 的目标已确认，当前不实现。序列、边界编码、缓存、触发方式、输出是否扩展及训练配置按[架构第 2.5 节](research_design/architecture.md#25-soulx-的-cot-条件化控制)后续确定，不继承旧文本控制器协议。

Layer 1 表达与思考调用、Layer 2 分步分析及两组专项训练采用[共同训练约定](research_design/architecture.md#7-共同训练与数据约定)。Layer 0 系统附和专项保留在总计划，具体模型、数据规模和预算实施前细化，当前不采集或训练。Layer 3 定位待统一，不新增实现。

完整话轮评测另行规划，可参考 FDB 的接话、停顿、用户附和及打断子集；系统附和须独立核查合理性与实际发声。控制返回时间不能代替可听响应时间，历史 FDB/FLEURS 作业不自动恢复。

## 4. 环境、资源与交付

本地与远端均使用 conda，真实模型训练和集群测试在远端调度作业执行。SoulX 实验使用独立根目录 `~/parathink-soulx-duplug/`，现役模型与环境只读复用，目录见[远端约定](remote_workspace.md)。

此前公开集验证设计的上限为：1×24GiB GPU、8 CPU、32GiB RAM、batch=1、一个活动作业，显存停止线 22GiB；下载并发≤2、CPU worker≤2，单会话一个在途请求、待处理音频≤800ms。单作业≤4小时，冒烟与正式运行累计≤4 GPU小时；启动空盘≥30GiB，新增资产≤10GiB，其中报告／trace≤2GiB。执行前核算全量时长和峰值，触限停止，不自动扩容。这些限制不覆盖已有 TextTurn 训练的独立授权。

实施代码、配置及必要契约测试同步维护 `docs` 下同路径中文说明；交付冻结配置、manifest、逐例 trace、汇总、资源记录与中文报告。工作单仅依用户明确指令建立，完成后归档；本次不新建工作单。

## 5. 历史路线入口

| 路线 | 保留状态与证据 |
| --- | --- |
| [TextTurn](dev/TextTurn/README.md) | 数据、训练、接入及评测见[工作单](issue/TextTurn/README.md)；TT-010 有限 pilot 最后记录见[修复报告](../reports/textturn/20261027-dataset-repair/README.md)，不自动进入 full 或恢复 TT-011 |
| [XTurnix](issue/XTurnix/README.md) | XTX-001—005 及可行性分析已归档；正式 FLEURS 作业已取消，来源审核未形成可冻结监督，旧训练草案已撤下 |

历史协议及运行证据保留在对应文档和报告，不作为 SoulX 已实现能力或当前实施授权。
