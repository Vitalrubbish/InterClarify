# duplex_model_service.py

## 功能与边界

为 X-Talk 的 DuplexRuntimeAdapter 提供 DuplexCascade 权重的 raw ChatML 流式推理服务。ASR、TTS、仲裁与播放由 X-Talk 管理；本服务只加载模型、维护会话缓存并返回生成结果。真实模型只在远端 conda 与获分配 GPU 上运行。

## 类设计与核心方法

`OfficialDuplexModel` 按 `train_cfg.json` 加载本地 Qwen2-7B-Instruct，resize token embedding，创建 q/v LoRA 与 embedding/head 保存层，再通过 `scripts/runtime/layer1_model.py` 严格恢复官方 state。tokenizer 使用 fast 实现，BF16 推理，所有参数冻结并 `eval()`。可选 `--adaptation` 在官方权重恢复后调用 `scripts/runtime/layer1_candidate.py` 加载已登记候选；不提供时为 B0。

`PrefixCachePool` 按显式 `session_id` 保存有界 `DynamicCache`，管理前缀匹配、会话淘汰、字节/token/会话数上限与 TTL。缓存取出后独占使用，成功结束且长度核对通过才归还；历史改写、取消或错误会丢弃在用缓存。完整历史与原始生成 ID 始终是事实来源。

`build_prompt_ids` 用官方 header、`<|im_end|>\n` 与 `<|no voice|>` 单 ID 展平微回合历史；历史使用 token ID 而非解码文本，避免重新编码无法逐 token 复现。超过上下文时拒绝请求并报告实际 token 数，不静默裁剪。

`build_generation_config` 使用独立 `GenerationConfig`，固定 `duplex_greedy_v1`：greedy、单 beam、`repetition_penalty=1.0`，不继承模型目录中的采样参数。生成时传入 `num_logits_to_keep=1`，只为最后一位计算 LM head，降低长历史显存占用。

HTTP 接口：

- `GET /health`：登记模型目录、token ID、加载状态、候选信息与生成策略。
- `POST /generate`：接收微回合历史与 `max_new_tokens`，以 NDJSON 流返回 `text`、`token_ids`、`prompt_tokens`、`finish_reason` 或 `error`。
- 可选的 `audit_prompt` 与生成 ID 诊断端点用于离线核对，不改变产品调用契约。

客户端断开通过 stopping criteria 取消后台生成。服务全局串行锁避免多个会话同时占用模型；每次请求记录 prompt/generated token 数、finish reason、耗时与峰值显存。

## 远端启动

```bash
conda run --no-capture-output -n interclarify-dev python scripts/remote/duplex_model_service.py \
  --checkpoint /path/to/DuplexCascade \
  --base-model /path/to/Qwen2-7B-Instruct \
  --port 8006
```

需要加载微调候选时增加 `--adaptation /path/to/checkpoint.pt`。运行不下载模型、不启动训练；源码、权重资产与环境版本须在任务清单中冻结。
