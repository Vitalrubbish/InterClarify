# layer1_fdb.py

## 功能与边界

`scripts/remote/layer1_fdb.py` 暂存冻结的 25 例 FDB 子集，并调用现有真实音频全链路回放驱动。它不创建独立文本回放器，不参与产品决策或播放。

## 核心方法

- `file_hash` 分块计算原始文件 SHA256。
- `prepare(manifest_path, output)` 验证清单恰好包含 25 个唯一 `input.wav`，逐文件核对大小与摘要；拒绝目录穿越、历史生成输出混入和覆盖既有目录。全部验证通过后才复制音频与标注，原始测试集不变。
- `run` 读取当前英语运行配置，替换为作业内服务 URL，逐子集调用 `duplex_a4_replay.run_fdb_batch`。每例独立会话，使用原生 Nemotron 增量输入和 5 秒连续静音诊断尾窗；正式输出保持原始音频等长。
- `main` 只分发 `prepare` 与 `run`，真实模型、ASR、TTS 与资源由远端作业管理。

transport 通过不等于能力通过；官方评分与内容复核仍需独立执行。
