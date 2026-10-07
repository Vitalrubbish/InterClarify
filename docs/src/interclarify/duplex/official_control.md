# `src/interclarify/duplex/official_control.py`

## 作用

官方 DuplexCascade 控制模型的**薄离线适配器**（[engineering_implementation.md](../../../engineering_implementation.md) 第 5.2 节 P1.1）。官方提交只有实时 `server.py`，没有独立离线样例，因此本模块用固定文本 micro-turn 序列驱动同一控制 token 生成逻辑，并记录原始输出、GPU 峰值显存与相对 micro-turn 窗口的实时因子。

## 直接复用官方、不改动的部分

- 从磁盘导入 `3rd-party/DuplexCascade/model.py` 的 `Model`（`load_official_model_class` 用 `importlib` 加载，不写 `sys.path`、不改源码）；
- 六个控制 token 与 `server.py` 的 `SPECIAL_TOKENS` 完全一致；
- 每个 micro-turn 的提示词拼装（`prepare_llm_tokens` / `llm_tick_task`）按官方逻辑复刻；
- 权重 `model_state.safetensors` 以 `strict=False` 加载，与 `server.py` 相同。

## 主要接口

### `build_prompt_tokens(tokenizer) -> PromptTokens`

复刻 `server.py` 的 `prepare_llm_tokens`，得到 `header_user`、`header_assist`、`im_end_id`、`im_end_nl_ids`、`no_voice_ids`、`special_token_ids`、`special_id_to_text`、`skip_for_text` 等。

### `append_user_micro_turn(tokens, history_ids, delta_text, encode)`

就地追加一个官方 micro-turn 用户片段：user 头 +（新词或 `<|no voice|>`）+ `<|im_end|>\n` + assistant 头。

### `OfficialControlAdapter`

- `__init__(snapshot_dir, base_model_path, source_root, device, dtype, max_new_tokens, micro_turn_seconds)`：构建慢/快 tokenizer、加入特殊 token、加载官方 `Model`、`enable_lora_adapter()`、`.to(device)`、`load_state_dict(strict=False)`；
- `run_turn(history_ids, delta_text, index)`：拼提示词、`generate`（`do_sample=False`、`eos=im_end_id`）并解析新 token 为特殊控制 token 与文本；返回 `MicroTurnResult`；
- `run_script(script)`：按脚本逐 micro-turn 运行，跨轮维护同一 `history_ids`；
- `cuda_peak_memory_mb()`：返回峰值显存（allocated/reserved）。

## 关键约束与取舍

- **不修改权重、不添加 Layer 2 逻辑**；适配器只是调用官方代码；
- 官方 `server.py` 默认以 fp32 载入（80GB 卡可行），适配器改用 **bf16** 以便在 24GB 4090 上运行——这是内存精度选择，不改变权重数值；
- 固定环境中 `transformers 4.44.2` 自带的 `tokenizers 0.19.1` 无法解析本仓库的 fast `tokenizer.json`（`ModelWrapper` 反序列化报错），因此优先尝试 fast、失败回退到 **慢速 Qwen2 tokenizer**；两者对相同文本产生等价 token id；
- 文本离线没有音频时长，`rtf_vs_micro_turn = 总生成耗时 / (micro-turn 数 × 0.6s)`，用于衡量控制模型能否跟上 0.6s micro-turn 节奏；
- 本模块不启动 ASR/TTS，也不做 TTS 播放。
