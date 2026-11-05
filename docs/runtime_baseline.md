# 当前运行基线

更新：2026-11-05。按用户确认，X-Talk 保留为工程框架，DuplexCascade 相关实现退出父仓库。当前可执行基线为 SoulX＋独立 X2＋Qwen2.5-7B-Instruct＋IndexTTS 的半双工评测链路。该链路是独立评测入口，尚未完成 X-Talk 常驻集成或 Layer 1 训练。

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

## 清理与单元测试

NTF-061／062 已归档。删除 DuplexCascade 及旧组件链路的七个专用测试文件；删除 Context 中只读取静态字典的并发测试，真实联合发布期间的并发读取和副本隔离仍由 `test_independent_frontend.py` 覆盖。旧服务的两项权重键／映射测试与独立恢复测试重复，也随退役文件删除。

当前前端的 EOS、屏障、取消、EOF 和资源测试分别保护组件及联合发布合同，继续保留。旧评分中仍适用的词数／时长阈值、提前响应零截断和空响应延迟检查迁至 [当前评分测试](tests/test_score_fdb30_half_duplex.md)。

复用本地 `interclarify-dev` conda，完整回归 **95 项通过、无跳过**，较清理前 149 项净减少 54 项。活动 Python 导入无已删模块引用，Markdown 本地文件链接及差异空白检查通过。通用依赖版本保持原值，远端环境与冻结作业未修改；本地回归不代表修复后 TOR／延迟通过。
