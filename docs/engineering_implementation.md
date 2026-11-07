# 工程实施计划

更新：2026-11-07。实施依据为[研究方案](research_design.md)、[总体架构](research_design/architecture.md)和[当前工作单](issue/README.md)。本轮仅清理仓库，不启动训练或远端作业。

## 1. 已有实现

| 范围 | 当前状态与入口 |
| --- | --- |
| SoulX＋X2 前端 | 同源 PCM、原生五状态、独立完整词正文、160ms 联合提交；见[前端合同](dev/SoulX-Duplug/independent_streaming_frontend.md)与[快照接口](dev/SoulX-Duplug/shared_context_interface.md) |
| 普通半双工评测 | Qwen2.5-7B-Instruct、可取消 IndexTTS 与播放实录；见[运行基线](runtime_baseline.md) |
| 修复后复测 | 固定执行线程、计算线程预算及跳过 complete 整段识别已实现，完整远端验收仍由 [NTF-054](issue/NTF-054.md) 跟踪 |
| 文本数据试造 | 五个独立来源、13 条模拟轨迹已生成；[pilot](datagen/README.md)未适配当前全部协议，不用于正式训练 |

X-Talk 保留为独立工程框架，当前评测尚未完成常驻集成。源码和模型版本见[运行基线](runtime_baseline.md)与[部署说明](dev/SoulX-Duplug/deployment.md)。

## 2. 后续实现边界

Layer 1 按[周期协议](dev/layer1/protocol.md)建立持久 Context，每三批前端输入组成 480ms 常规周期，保留三个子块及其状态；新增正文去重、逐批缓冲、tokenizer 与缓存适配尚待实施。思考请求和系统附和分别使用专用 token，系统附和当前不附正文或定义发声。

有效打断由唯一输出执行点逐批处理，不等待三拍。首音前取消删除本次回答及对应缓存并合并用户两段；首音后保留全部生成文本，续说作为新用户片段。该上下文整理层尚未接入，不能用现有半双工消息整理代替其验收。

Layer 2 按[周期协议](dev/layer2/protocol.md)使用冻结模型，只读对话与上一轮分析，仅将最终 result 同源交付两个下游。模型接入、结果注入、SoulX 条件化训练及主动澄清生成边界仍待实施。详细训练与两项 benchmark 留待后续讨论。

## 3. 执行与维护

本地和远端使用 conda。真实模型训练与集群测试仅在远端调度作业执行，资源、并发、时限和输出预算按对应工作单冻结；NTF-054 继续沿用其已确认限制。本轮不修改远端环境、共享模型、冻结源码或运行中的作业。

已结束的前端专用评分和过时方案退出当前入口，仍被现役推理、评分或测试调用的通用组件保留。实现变更同步维护 `docs` 同路径中文说明；本轮范围与验证见[运行基线](runtime_baseline.md#工具保留与清理范围)。
