# `scripts/remote/run_xtalk_round1.py`

用途说明（2026-10-18）：本文说明保留的历史/诊断实现。当前目标已确定为 Nemotron EN 160ms + Kokoro；新组合接入和训练按 [issue 任务](../../issue/README.md) 推进，本文参数不代表新组合已部署。

通用模型准备、依赖检查、服务启动与独立 TTS 流式检查工具。Qwen3-ASR 已退役，删除 ASR smoke、修订前缀处理、ASR 依赖检查和服务启动入口；ASR 由独立脚本与配置管理。脚本没有自定义类。

- `read_config` / `write_json`：读取版本化 YAML，写入 UTF-8 结果。
- `download_models` / `model_path`：首次解析不可变 revision，复用模型锁，拒绝模型 ID 或固定版本漂移；只下载当前配置列出的 LLM、MOSS 与 codec。
- `check_dependencies`：检查 LLM、TurnSense 或 MOSS 的钉版和可导入性。
- `new_report_directory`：只为 TTS probe 保存实际使用的 TTS/codec、MOSS 来源和服务参数，避免把其他已缓存模型冒充活动组件。
- `tts_smoke`：并发发送文本和接收 PCM，记录首包、flush、分片与参考音频摘要；支持按词切分，保存 WAV，不以有声输出代替质量验收。
- `serve` / `select_gpu`：选择作业可见卡内的逻辑编号，在对应 conda 环境启动 LLM、TurnSense 或 MOSS；`--port` 可覆写端口。MOSS 检查固定源码和 dirty 状态，通过 `sitecustomize` 安装吞吐补丁，显式环境参数优先于配置默认值。
- `build_parser` / `main`：提供 `download`、`tts-smoke`、`check-deps` 与 `serve`，角色仅为 `llm`、`turn_detector`、`tts`。

下载在准备环境进行，TTS smoke 在具备 X-Talk 客户端依赖的 conda 环境进行，真实服务在远端运行。每次 smoke 使用新输出目录，旧 Qwen 测试通过 Git 历史复核。
