# Issue 004 数据生成与 DuplexCascade 官方对齐审计

日期：2026-10-19。范围：旧 `issue004-build-r3` 的生成配置、事件计划、编码器，以及前 32 条人工审计材料。下表记录修复前的静态语义复核；修复和r4重建由[019归档工作单](https://github.com/Vitalrubbish/InterClarify/blob/6ca5eea/docs/issue/archive/019_duplex_data_alignment_audit.md)记录。

| 检查项 | 官方依据 | 当前行为与结论 |
| --- | --- | --- |
| token 与消息格式 | 论文 3.2；发布 `server.py` | 五类控制 token、no-voice、ChatML user/assistant header 与结束符对应。构建器用发布 tokenizer 验证单 ID；关闭 system backchannel 与发布的普通版一致。|
| 用户/assistant 分拍 | 论文 3.3.1–3.3.2 | 原样用户按发布 tokenizer 随机取 1–7 token；assistant 编码后按最多 10 个正文 ID 切片。用户切片遇共享字符 offset 可延长超过 7 个基础 token，去句读后不重分拍；这两项是本项目为保留原文和三视图对应采取的偏离。|
| 等待与接话 | 论文 3.3.1 | 非末用户片段监督 talking；末片段监督 finish 并生成首个回答片段。assistant 后续拍默认以 no-voice 输入续写。|
| 自然停顿 | 论文 3.3.2 | 仅非末用户片段之后以 0.10 概率插入 1–5 个 no-voice/talking 拍。末片段不插入等待，是本项目明确的边界选择。|
| 用户附和 | 论文 3.3.2 | 回答续写拍以 0.01 概率把 no-voice 换成短文本，监督 backchannel 并继续同一回答。首个回答片段、打断拍不参加采样；分母与论文“每个系统微轮”字面口径不完全相同。|
| 打断 | 论文 3.3.2 | 有后续用户轮且旧回答至少两片段时，以 0.30 概率选未结束边界；首个新用户片段监督 interruption 并丢弃旧回答尾部，随后 talking，最后 finish 启动新回答。条件分母较论文“每个系统长轮”窄。|
| 回答后思考 | 论文 3.3.2 | 未被打断的回答后加入 1–20 个 no-voice/thinking 拍。|
| 句读增强空拍 | 项目 004/006 设计 | **发现偏差**：原样只含可删除标点的片段去句读后变成 no-voice，原控制与正文监督不变。前 32 条有 49 个、涉及 28 条对话，其中 39 个直接监督无声接话。需修复和重建。|

官方论文明确给出行为与概率，但[官方仓库](https://github.com/sbintuitions/DuplexCascade/tree/42893024ca90c8de8ac3ed624467ebc123512ff8)没有公开完整训练数据生成器。因此本结论是**与已公开协议和论文语义的对齐检查**，不是与作者训练样本逐字节一致的声明。官方依据为[论文第 3.2–3.3 节](https://arxiv.org/html/2603.09180v1#S3.SS3)及[固定提交的 `server.py`](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py)。

计数方法：扫描当时r3前32份逐条材料的事件表，筛出“用户原样去空白后非空，去句读文本去空白后为空”的行。结果为 `response_start=39`、`user_continuation=10`。例如旧审计20的 event 131 为原样 `.`、去句读为空、控制为 finish。r3远端产物和仓库审计副本已按用户要求删除，保留上述缺陷摘要，不再提供旧材料签署入口。

**审计结论：** 基础双工事件和发布 token 协议总体对齐；r3去句读视图存在可复现的无声监督冲突。019已修复并生成r4，后经数值形式修订形成[r5正式产物](../reports/layer1_training/issue004-build-20261019-r5/README.md)：全量机器审计通过，前32条6222个事件独立核对没有来源用户片段变为空串。r5全量机器审计通过，用户明确取消新增人工复审，004已关闭归档；r4产物已删除。
