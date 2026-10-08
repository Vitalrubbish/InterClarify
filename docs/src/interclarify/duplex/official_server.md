# `src/interclarify/duplex/official_server.py`

## 作用

P1.2 的控制模型服务进程管理：把**未修改**的官方 `server.py` 以独立 OS 子进程启动，权重来自 P1.1 已逐字节校验的本地快照（不再每次从 HF 下载）。与官方三服务架构一致：本进程只管控制模型（LLM），ASR/TTS 仍是独立的 Kyutai 服务。

## 主要接口

### `OfficialDuplexServer`

子进程管理器。参数镜像官方 CLI（端口、STT/TTS ws、device、dtype、`max_new_tokens`、`overlap_window_s`、tts voice、`stt_pre_silence_s` 等）外加 `python_exe`、`log_path`、`ready_timeout_s`。

- `build_command()`：组装子进程命令行 `python -m interclarify.duplex.official_server ...`（测试亦覆盖）；
- `start()`：启动子进程（stdout/stderr 写入 `log_path`，继承环境并确保 `PYTHONPATH` 含本仓库 `src`、`HF_HUB_OFFLINE=1`），轮询端口直到接受连接——官方实现里端口绑定发生在模型加载完成后，所以端口就绪即权重已加载；
- `stop()`：幂等终止；支持上下文管理器。

### `main(argv)`（子进程入口）

从 `source_root` 用 importlib 导入官方 `server.py`（`from model import Model` 依赖其文件头部的 `sys.path` 处理，源码零改动），随后**复刻官方 `main()`**：构建 tokenizer（快照 `tokenizer/` 优先，失败回退基础模型慢速 tokenizer）、加入六个控制 token、`enable_lora_adapter()`、`load_state_dict(strict=False)`，最后 `asyncio.run(KyutaiBridgeServer.run(port))`。

### `verify_weight_sha256(snapshot_dir, filename, expected)`

流式 SHA-256 校验，摘要不符直接抛错；runner 在启动服务前调用。

## 有记录的偏离（执行补充，非行为改变）

1. HF snapshot 下载替换为本地快照（P1.1 已验证 `weight_sha256` 一致）；
2. 基座按 **bf16** 加载以适配 24 GB RTX 4090（与 P1.1 适配器相同；权重数值不变）；
3. 全程离线（`HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE`）。

控制 token 列表直接复用 `official_control.SPECIAL_TOKENS`（项目内单一来源，与 `server.py` 的 `SPECIAL_TOKENS` 一致）。
