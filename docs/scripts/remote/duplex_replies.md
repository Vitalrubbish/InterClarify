# duplex_replies.py

## 功能与来源

从 TurnControlComparison 的 `scripts/remote/duplex_replies.py` 复用，用于 FDB30 半双工完整系统评测。原文件 SHA256 为 `eccc73c5060ee3ce8065ab5d3ae768f20e38d265382e062e71336b522c2b9c3b`。冻结副本随本项目提交，不依赖远端旧运行目录。

## 类与核心方法

`ReplySession` 管理一次会话的请求、取消和可听历史。`start` 排队普通 LLM 回答；生成、TTS、取消 RPC 和已播尾部识别分别由独立线程处理。`cancel` 保留已播历史，首音前取消不留下助手消息。`take_segment` 按首段和后续字符预算切分文本。`close` 等待后台清理结束，避免跨样本泄漏。
