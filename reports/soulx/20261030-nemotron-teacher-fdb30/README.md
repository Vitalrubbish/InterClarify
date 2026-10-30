# Nemotron Teacher Forcing 与 FDB 三轴小样本

2026-10-30。已实现[同步方案](../../../docs/dev/SoulX-Duplug/nemotron_teacher_forcing.md)，两份权重固定，Nemotron 每步真实解码结束并交付文字后，SoulX 输入当前音频、原始新增教师文字及 ASR 结束符，预测状态并联合覆盖 Context，发布后才允许 ASR 推进下一块。SenseVoice 不加载、不调用；下游 LLM／TTS 未接入。

当前状态：三轴各1条预检已完成，30条同样本实验运行中，最终质量结论待结果更新。

## 实现与冻结

- 实际推理源码 `b143bff`，初始接入提交 `06ed959`；GitHub 已推送。
- Nemotron EN0.6B revision `ebe59e5a817142986528bbbee5dba8db7b38ed50`，FP32、lookahead1；SoulX revision `61701c4ab8193cc1ee2220d3848872ac6c720142`，上游源码摘要固定。
- Transformers 生成源码 SHA256 `c45e19eb4534a2478f8e4825dc35a28fb5efe5a2f8d09695e4b2ea532b4dbd82`。内存调整 `_sample` 顺序使 streamer 最后 token 先于下一特征读取；类方法在 generation 结束后恢复，不修改环境文件。
- 复用历史 FDB30 manifest：接话10、停顿10、打断10，音频513.1915秒。引用与标注只离线评分，不输入模型。
- 本逻辑话轮软重置保留音频／教师 KV、字符游标和下一次输入的有效状态；未知输出不反馈。保留原生两条完成规则，分开记录原始预测和规则改写。
- 本轮真实0时刻对齐160ms处理块，初始回看零填充，保留640样本前瞻；历史原生 process 有40ms初始占位，比较时不能把粒度差异忽略。离线整段 RMS 标定沿用历史配置，不宣称线上因果增益。

本地 conda 下6项教师文字／屏障、4项 Context、5项 SenseVoice 前端回归、5项原 Nemotron 服务检查通过，共20项。脚本语法及冻结 Transformers AST 编译检查通过。

## 远端预检

单作业、1×4090、4CPU、32GiB；ASR 与 SoulX 各2线程、显存比例0.55／0.35；显存停止线22GiB、结果128MiB、1800秒、音频积压800ms。复用既有两个 conda 与模型，不复制大型权重。

第一轮 `job-179336761878288219987-xuan-zhang` 在加载阶段主动停止：核查发现 Transformers 从模型类获取 `_sample`，实例绑定不能替换实际解码方法；修复后重新冻结提交，不将该轮算作测试成功。

第二轮 `job-179336789523255028144-xuan-zhang`，run `nemotron-teacher-smoke-20261030-r2` 退出0，三轴各1条通过，合计309帧。最大积压329.8ms；预检仍出现提前 complete，不宣称语义质量达标。

## 产物

远端根 `~/parathink-soulx-duplug/`，源码 `source/b143bff`，正式输出 `runs/nemotron-teacher-fdb30-20261030-r1/`；预检独立保存在 `runs/nemotron-teacher-smoke-20261030-r2/`。冻结源码通过 SFTP 传输后逐包核对摘要，源码包 SHA256 `f2f2d9c16a5209ff293bc44c47b16050cf910996dea7c924e82479d6b1294e4f`。

本地原始证据保存在 `artifacts/soulx/20261030-nemotron-teacher-smoke-r2/` 与 `artifacts/soulx/20261030-nemotron-teacher-fdb30-r1/`，不将逐帧正文和 JSON 推送到 Git。
