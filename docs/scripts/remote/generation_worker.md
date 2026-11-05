# generation_worker.py

## 功能与来源

从 TurnControlComparison 的 `scripts/remote/generation_worker.py` 复用，用于 FDB30 半双工完整系统评测。原文件 SHA256 为 `d07221d924aeae9af0a1347f39ca639999f0a3792242edb469e94c385ba87267`。冻结副本随本项目提交，不依赖远端旧运行目录。

## 类与核心方法

`Backend` 加载离线 Qwen2.5-7B 或 IndexTTS-1.5，分别执行文本增量生成和分段音频合成。`dispatch` 串行化模型请求并处理取消；`request`、`request_stream` 提供私有 Unix socket 协议。`main` 验证 conda、显卡与显存比例，预热后记录 ready 回执。
