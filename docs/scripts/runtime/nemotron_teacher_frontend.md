# Nemotron 教师文字前端

`NemotronTeacherFrontend` 只使用固定 SoulX 音频编码与 LLM 权重，独占本逻辑话轮 KV；不调用 SenseVoice 或原生文字门控。`process_step()` 在 ASR 单步完成后输入待反馈状态、当前音频 embedding、原始新增文字的 tokenizer 编码和 ASR 结束符，贪心预测一个状态，联合覆盖 SharedContext。未知输出不作为下一步输入。

字符游标由原始累计正文推进，每段仅注入一次，不补空格；累计 token 解码必须还原教师正文。`reset_controller()` 只清理计数和发声标志，保留 KV、教师正文与待反馈状态；`close()` 保留最后在线正文并释放 KV。序列 token 总数有上限。

原始状态与发布状态分开，`nonidle_to_idle` 和 `empty_nonidle_count` 独立标记；可关闭后者。音频块、回看和前瞻由回放器按真实采样位置提供，观察上界同时包含 Nemotron 的实际窗口。每步外部审计记录教师输入、预测、联合发布的时间；Context 不保存历史版本。
