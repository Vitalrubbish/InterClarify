# `tests/test_p1_offline_control.py`

## 作用

P1.1 离线控制适配器的 CPU 单元测试（不加载 7B 模型），验证控制 token 与提示词拼装是否与官方 `server.py` 一致。

## 用例

- `test_prompt_tokens_include_control_tokens`：`build_prompt_tokens` 产出非空 user/assistant 头、单个 `<|no voice|>`、有效 `im_end_id`，以及 5 个 assistant 控制 token（每个映射到单个 id）。
- `test_append_user_micro_turn_text_and_silence`：有文本时拼 user 头 + 词 + assistant 头且不含 `<|no voice|>`；`None` 时包含 `<|no voice|>`。
- `test_default_script_shape`：默认脚本为含字符串与 `null` 的序列。

## 依赖

需要本地 DuplexCascade 快照的 `tokenizer/`；找不到时 `pytest.skip`。优先 fast tokenizer，失败回退慢速 Qwen2 tokenizer。

## 运行

```bash
conda run -n interclarify-dev python -m pytest -q tests/test_p1_offline_control.py
```
