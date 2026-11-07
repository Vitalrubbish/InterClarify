# 当前运行基线

更新：2026-11-07。X-Talk 保留为工程框架。当前可执行基线为 SoulX＋独立 X2＋Qwen2.5-7B-Instruct＋IndexTTS 的半双工评测链路，尚未完成 X-Talk 常驻集成或 Layer 1 训练。已确认的两层设计以[总体架构](research_design/architecture.md)及模块协议为准。

| 模块 | 当前采用值 |
| --- | --- |
| 工程框架 | 独立 `xtalk/` checkout，版本见 [源码登记](configs/xtalk_runtime_source.md) |
| 控制 | SoulX 原生 SenseVoice 与五状态，complete 后省略整段重识别 |
| 正文 | 独立 X2Streaming-ASR，EOS 闭合完整词 |
| 联合提交 | 同源 PCM，每 160ms 两路完成后原子发布 |
| 语言模型 | Qwen2.5-7B-Instruct，普通半双工回答，最大 128 新 token、seed42 |
| TTS | IndexTTS-1.5，首段 20／后续 40 字符，可取消播放 |
| 评分 | 固定 FDB30，TOR／延迟，不调用 judge |

有效 complete 且有新正文时生成回答，有效 nonidle 时取消生成与播放，已播内容保留。正文只追加，内部 reset 不清空 X2 正文。推理使用固定 SoulX 回放线程及常驻 X2 辅助线程，每个模型进程计算线程预算为 2。完整系统评测按用户指令不执行原生一致性检查，明确记录未执行，不声明等价。

入口与资源见[完整链路方案](dev/SoulX-Duplug/fdb30_half_duplex.md)、[运行脚本](scripts/remote/run_fdb30_half_duplex.md)及[评分脚本](scripts/remote/score_fdb30_half_duplex.md)。修复前首轮结果见[报告](reports/soulx/20261105-fdb30-half-duplex/README.md)；修复后完整复测由 [NTF-054](issue/NTF-054.md) 跟踪，不能把提交或本地回归视为远端验收。

DuplexCascade 服务、旧训练恢复器、Nemotron／Kokoro 组合配置与专用重放测试已删除，可从 Git 历史追溯。远端旧模型与冻结作业资产保持原样；X-Talk 独立仓库本次未修改。

## 工具保留与清理范围

按本轮用户明确指令，DCT-016 退役已结束的 NTF-019 单／双路前端专用评分、作业包装及专用测试，并同步删除同路径说明。DCT-017 移除已被实现取代的早期修复方案与独立 complete 审计报告；旧内容可从 Git 历史追溯。

通用前端探针、`analyze_native_frontend.py` 审计、X2 工具和播放／评分组件继续保留：当前推理、评分或回归仍依赖这些组件，不能按早期工作单编号删除。前端 EOS、屏障、取消、EOF、资源与完整系统 TOR／延迟测试保持。

当前 Layer 1／2 协议、数据构造与 pilot v1 历史材料保留；11 月 5 日首轮评测指标、JSON 与 NTF-054 活动复测证据保持，首轮报告只更新已失效的说明引用。远端冻结源码、作业、模型和环境保持，通用依赖不升级。

本轮复用 `interclarify-dev` conda，完整本地回归 107 项通过，较清理前移除 5 项退役评分专用检查；shell 语法与差异检查通过。全仓库 Markdown 本地链接和锚点检查通过，清理前的 62 处失效引用已消除；35 份当前协议、配置、pilot 与保留评测证据的文件摘要一致。本地验证不代表远端性能或协议运行能力已经验收。
