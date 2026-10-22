# X2-Turn 权重下载与 vLLM 导出

`scripts/remote/prepare_x2_turn_model.py` 把 Hugging Face 上的 X2-Turn 检查点固定到一个 revision，校验文件大小与 LFS 哈希，推导服务端实际使用的转写延迟，并导出 vLLM 可直接加载的目录。脚本只恢复模型资产，不启动服务、不回放音频、不产生指标。

## 固定范围

- 仓库 `x-square-robot/X2-Turn-4B-0812`，revision `49c62a9b1170f2ab5168e763b84c2ac5c6b5e1ee`。
- 只下载 `model.safetensors`、`params.json`、`tekken.json`、`config.json`、`generation_config.json`、`processor_config.json`、许可证与说明文件，不拉取其他变体。
- 该 revision 自带 `params.json` 与 `tekken.json`，因此不需要额外下载 `Voxtral-Mini-4B-Realtime-2602` 基底。

## 延迟来源

有效延迟不是客户端字段，而是 `tekken.json` 的 `audio.transcription_delay_ms = 480`；它与 `frame_rate = 12.5` 对应每 token 80 ms、共 6 个 delay token。`config.json` 的 `default_num_delay_tokens = 6` 与 `audio_length_per_tok = 8`（hop 160、16 kHz）给出同一结果。`compute_delay` 要求两个来源一致，否则失败；服务作业还会用 `mistral-common` 读取 `get_num_delay_tokens()`，核对服务端真正使用的值。

## 函数

- `tree_metadata`：读取固定 revision 的文件树，得到每个文件的大小与 LFS SHA256。
- `verify_snapshot`：逐个允许文件核对存在性、大小；有 LFS 摘要时再核对 SHA256，并标注该文件是否完成哈希校验。
- `compute_delay`：交叉核对 `config.json` 与 `tekken.json`，返回 token 数、每 token 毫秒数与总延迟。
- `inspect_tokenizer_delay`：在带 `mistral-common` 的环境中按服务端读取路径取 delay token 数。
- `download`：用 `snapshot_download` 按 revision 与允许模式下载，事件写入 `ROOT/logs/x2_turn_model_events.jsonl`。
- `export_for_vllm`：调用固定源码中的 `export_mtp_for_vllm.py`，把 HF 权重映射为 mistral 键并生成 `consolidated.safetensors`，随后对导出目录逐文件计算 SHA256。
- `prepare` / `verify` / `inspect`：完整准备、离线复核既有锁、打印冻结延迟。

## 使用

```bash
PY=~/miniconda3/envs/interclarify-x2-turn-vllm/bin/python
$PY scripts/remote/prepare_x2_turn_model.py --root ~/interclarify-x2-turn-complete prepare
$PY scripts/remote/prepare_x2_turn_model.py --root ~/interclarify-x2-turn-complete verify
```

默认 `HF_ENDPOINT` 为 `https://hf-mirror.com`，可用同名环境变量或 `--endpoint` 覆盖；revision 始终固定。

## 输出

- `ROOT/models/X2-Turn-4B-0812`：固定 revision 的 HF 检查点。
- `ROOT/models/X2-Turn-4B-0812-vllm`：导出目录，含 `consolidated.safetensors`。
- `ROOT/env/x2_turn_model_lock.json`：revision、endpoint、逐文件大小与 SHA256、延迟推导、导出工具哈希、导出文件哈希。

`verify` 不重新下载，只按锁与远端文件树复核；哈希漂移即失败。导出需要约 10.5 GiB 额外磁盘，计入整轮资产预算。
